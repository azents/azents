"""add live action execution ownership

Revision ID: 4ac866c17faf
Revises: 0755571733db
Create Date: 2026-07-13 22:10:10.489755

"""

from typing import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "4ac866c17faf"
down_revision: str | Sequence[str] | None = "0755571733db"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.execute("ALTER TYPE action_execution_status ADD VALUE IF NOT EXISTS 'cancelled'")
    op.add_column(
        "action_executions",
        sa.Column(
            "owner_generation",
            sa.BigInteger(),
            nullable=False,
            server_default="0",
        ),
    )
    op.alter_column("action_executions", "owner_generation", server_default=None)
    op.add_column(
        "action_executions",
        sa.Column("cancelled_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "action_executions",
        sa.Column("cancellation_summary", sa.Text(), nullable=True),
    )
    op.execute(
        """
        DELETE FROM events AS legacy
        USING action_executions AS execution, events AS canonical
        WHERE execution.status IN ('completed', 'failed')
          AND legacy.session_id = execution.session_id
          AND legacy.external_id = (
              'action_execution_result:' || execution.id || ':'
              || execution.status::text
          )
          AND canonical.session_id = execution.session_id
          AND canonical.external_id = 'action_execution_result:' || execution.id
        """
    )
    op.execute(
        """
        UPDATE events AS event
        SET external_id = 'action_execution_result:' || execution.id
        FROM action_executions AS execution
        WHERE execution.status IN ('completed', 'failed')
          AND event.session_id = execution.session_id
          AND event.external_id = (
              'action_execution_result:' || execution.id || ':'
              || execution.status::text
          )
        """
    )
    op.execute(
        """
        WITH terminal_snapshots AS (
            SELECT
                execution.id,
                execution.session_id,
                jsonb_build_object(
                    'action_execution',
                    jsonb_build_object(
                        'execution',
                        jsonb_strip_nulls(
                            jsonb_build_object(
                                'id', execution.id,
                                'session_id', execution.session_id,
                                'input_buffer_id', execution.input_buffer_id,
                                'action_type', execution.action_type,
                                'action', execution.action,
                                'status', execution.status::text,
                                'owner_generation', execution.owner_generation,
                                'failure_summary', execution.failure_summary,
                                'cancellation_summary', NULL,
                                'started_at', execution.started_at,
                                'completed_at', CASE
                                    WHEN execution.status::text = 'completed'
                                    THEN COALESCE(
                                        execution.completed_at,
                                        execution.updated_at,
                                        execution.created_at
                                    )
                                END,
                                'failed_at', CASE
                                    WHEN execution.status::text = 'failed'
                                    THEN COALESCE(
                                        execution.failed_at,
                                        execution.updated_at,
                                        execution.created_at
                                    )
                                END,
                                'cancelled_at', NULL,
                                'created_at', execution.created_at,
                                'updated_at', COALESCE(
                                    execution.completed_at,
                                    execution.failed_at,
                                    execution.updated_at,
                                    execution.created_at
                                )
                            )
                        ),
                        'events', COALESCE(
                            jsonb_agg(
                                jsonb_strip_nulls(
                                    jsonb_build_object(
                                        'id', progress.id,
                                        'action_execution_id',
                                            progress.action_execution_id,
                                        'session_id', progress.session_id,
                                        'sequence', progress.sequence,
                                        'kind', progress.kind::text,
                                        'step_key', progress.step_key,
                                        'command_argv', progress.command_argv,
                                        'content', progress.content,
                                        'exit_code', progress.exit_code,
                                        'created_at', progress.created_at
                                    )
                                )
                                ORDER BY progress.sequence
                            ) FILTER (WHERE progress.id IS NOT NULL),
                            '[]'::jsonb
                        )
                    )
                ) AS payload
            FROM action_executions AS execution
            LEFT JOIN action_execution_events AS progress
              ON progress.action_execution_id = execution.id
            WHERE execution.status IN ('completed', 'failed')
              AND NOT EXISTS (
                  SELECT 1
                  FROM events AS event
                  WHERE event.session_id = execution.session_id
                    AND event.external_id =
                        'action_execution_result:' || execution.id
              )
            GROUP BY execution.id
        ),
        ordered_snapshots AS (
            SELECT
                terminal_snapshots.*,
                COALESCE(
                    (
                        SELECT MAX(existing.model_order)
                        FROM events AS existing
                        WHERE existing.session_id = terminal_snapshots.session_id
                    ),
                    0
                ) + 1000 * ROW_NUMBER() OVER (
                    PARTITION BY terminal_snapshots.session_id
                    ORDER BY terminal_snapshots.id
                ) AS model_order
            FROM terminal_snapshots
        )
        INSERT INTO events (
            id,
            session_id,
            kind,
            payload,
            model_order,
            external_id,
            schema_version,
            reverted
        )
        SELECT
            replace(gen_random_uuid()::text, '-', ''),
            session_id,
            'action_execution_result',
            payload,
            model_order,
            'action_execution_result:' || id,
            '1',
            false
        FROM ordered_snapshots
        """
    )
    op.execute(
        """
        DELETE FROM action_executions
        WHERE status IN ('completed', 'failed')
        """
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column("action_executions", "cancellation_summary")
    op.drop_column("action_executions", "cancelled_at")
    op.drop_column("action_executions", "owner_generation")
