"""Remove the redundant event model order."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "629612c66084"
down_revision: str | Sequence[str] | None = "10fa347228db"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Remove logical ordering after validating every active model-input head."""
    op.execute(
        sa.text(
            """
            LOCK TABLE agent_sessions, events
            IN SHARE ROW EXCLUSIVE MODE
            """
        )
    )
    op.execute(
        sa.text(
            """
            DO $$
            BEGIN
                IF EXISTS (
                    SELECT 1
                    FROM agent_sessions AS session
                    JOIN events AS head
                      ON head.id = session.model_input_head_event_id
                    JOIN events AS event
                      ON event.session_id = session.id
                    WHERE event.reverted = false
                      AND event.id < head.id
                      AND event.model_order > head.model_order
                ) THEN
                    RAISE EXCEPTION
                        'Model-input head cannot be represented by event ID order';
                END IF;
            END
            $$;
            """
        )
    )
    op.drop_index("ix_events_session_model_order", table_name="events")
    op.drop_column("events", "model_order")
    op.drop_index("ix_agent_sessions_model_file_gc_lag", table_name="agent_sessions")
    op.drop_column("agent_sessions", "model_file_gc_cursor_model_order")
    op.drop_column("agent_sessions", "model_input_head_model_order")
    op.create_index(
        "ix_agent_sessions_model_file_gc_cursor",
        "agent_sessions",
        [
            sa.text("model_file_gc_cursor_event_id ASC NULLS FIRST"),
            "model_input_head_event_id",
        ],
        unique=False,
        postgresql_where=sa.text("model_input_head_event_id IS NOT NULL"),
    )


def downgrade() -> None:
    """Reconstruct logical ordering from event IDs."""
    op.drop_index(
        "ix_agent_sessions_model_file_gc_cursor",
        table_name="agent_sessions",
    )
    op.add_column(
        "events",
        sa.Column("model_order", sa.BigInteger(), nullable=True),
    )
    op.execute(
        sa.text(
            """
            WITH ordered AS (
                SELECT
                    id,
                    row_number() OVER (
                        PARTITION BY session_id
                        ORDER BY id ASC
                    ) * 1000 AS model_order
                FROM events
            )
            UPDATE events
            SET model_order = ordered.model_order
            FROM ordered
            WHERE events.id = ordered.id
            """
        )
    )
    op.alter_column("events", "model_order", nullable=False)
    op.create_index(
        "ix_events_session_model_order",
        "events",
        ["session_id", "model_order"],
        unique=True,
    )

    op.add_column(
        "agent_sessions",
        sa.Column("model_input_head_model_order", sa.BigInteger(), nullable=True),
    )
    op.add_column(
        "agent_sessions",
        sa.Column(
            "model_file_gc_cursor_model_order",
            sa.BigInteger(),
            server_default="0",
            nullable=False,
        ),
    )
    op.execute(
        sa.text(
            """
            UPDATE agent_sessions AS session
            SET model_input_head_model_order = head.model_order
            FROM events AS head
            WHERE head.id = session.model_input_head_event_id
            """
        )
    )
    op.execute(
        sa.text(
            """
            UPDATE agent_sessions AS session
            SET model_file_gc_cursor_model_order = cursor.model_order
            FROM events AS cursor
            WHERE cursor.id = session.model_file_gc_cursor_event_id
            """
        )
    )
    op.create_index(
        "ix_agent_sessions_model_file_gc_lag",
        "agent_sessions",
        ["model_file_gc_cursor_model_order", "model_input_head_model_order"],
        unique=False,
    )
