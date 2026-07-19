"""Add InputBuffer scheduling mode."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "b96607c4c3db"
down_revision: str | Sequence[str] | None = "0503badf57ee"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_SCHEDULING_MODE = postgresql.ENUM(
    "queue_only",
    "wake_session",
    name="input_buffer_scheduling_mode",
    create_type=False,
)


def upgrade() -> None:
    """Add and backfill producer-selected scheduling intent."""
    bind = op.get_bind()
    postgresql.ENUM(
        "queue_only",
        "wake_session",
        name="input_buffer_scheduling_mode",
    ).create(bind, checkfirst=True)
    op.add_column(
        "input_buffers",
        sa.Column("scheduling_mode", _SCHEDULING_MODE, nullable=True),
    )
    op.execute(
        sa.text(
            """
            UPDATE input_buffers
            SET scheduling_mode = CASE
                WHEN kind = 'agent_message'
                    AND metadata->>'message_kind' = 'send_message'
                    THEN 'queue_only'::input_buffer_scheduling_mode
                ELSE 'wake_session'::input_buffer_scheduling_mode
            END
            """
        )
    )
    op.alter_column("input_buffers", "scheduling_mode", nullable=False)
    op.create_index(
        "ix_input_buffers_session_id_scheduling_mode",
        "input_buffers",
        ["session_id", "scheduling_mode"],
        unique=False,
    )


def downgrade() -> None:
    """Remove InputBuffer scheduling intent."""
    op.drop_index(
        "ix_input_buffers_session_id_scheduling_mode",
        table_name="input_buffers",
    )
    op.drop_column("input_buffers", "scheduling_mode")
    postgresql.ENUM(name="input_buffer_scheduling_mode").drop(
        op.get_bind(),
        checkfirst=True,
    )
