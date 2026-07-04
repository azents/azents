"""backfill ready session initializations

Revision ID: d05b0f8874f4
Revises: 2bac80165071
Create Date: 2026-07-03 19:09:31.013532

"""

from typing import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "d05b0f8874f4"
down_revision: str | Sequence[str] | None = "2bac80165071"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.execute(
        """
        INSERT INTO session_initializations (
            id,
            session_id,
            status,
            retry_count,
            completed_at,
            created_at,
            updated_at
        )
        SELECT
            md5(agent_sessions.id || '-initialization'),
            agent_sessions.id,
            'ready'::session_initialization_status,
            0,
            now(),
            now(),
            now()
        FROM agent_sessions
        WHERE NOT EXISTS (
            SELECT 1
            FROM session_initializations
            WHERE session_initializations.session_id = agent_sessions.id
        )
        """
    )
    op.execute(
        """
        INSERT INTO session_initialization_steps (
            id,
            initialization_id,
            session_id,
            sequence,
            step_key,
            step_type,
            status,
            blocking,
            retryable,
            attempt,
            depends_on_step_keys,
            resource_descriptors,
            completed_at,
            created_at,
            updated_at
        )
        SELECT
            md5(session_initializations.session_id || '-noop-ready'),
            session_initializations.id,
            session_initializations.session_id,
            1,
            'noop_ready',
            'noop_ready'::session_initialization_step_type,
            'completed'::session_initialization_step_status,
            false,
            false,
            1,
            '[]'::jsonb,
            '[]'::jsonb,
            now(),
            now(),
            now()
        FROM session_initializations
        WHERE session_initializations.status = 'ready'
          AND NOT EXISTS (
              SELECT 1
              FROM session_initialization_steps
              WHERE session_initialization_steps.initialization_id =
                  session_initializations.id
                AND session_initialization_steps.step_key = 'noop_ready'
          )
        """
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.execute(
        """
        DELETE FROM session_initialization_steps
        USING session_initializations
        WHERE session_initialization_steps.initialization_id =
            session_initializations.id
          AND session_initialization_steps.id =
            md5(session_initializations.session_id || '-noop-ready')
          AND session_initialization_steps.step_key = 'noop_ready'
        """
    )
    op.execute(
        """
        DELETE FROM session_initializations
        USING agent_sessions
        WHERE session_initializations.session_id = agent_sessions.id
          AND session_initializations.id = md5(agent_sessions.id || '-initialization')
        """
    )
