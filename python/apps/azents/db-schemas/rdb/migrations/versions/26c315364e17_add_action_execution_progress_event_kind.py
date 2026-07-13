"""Add action execution progress event kind."""

from collections.abc import Sequence

from alembic import op

revision: str = "26c315364e17"
down_revision: str | Sequence[str] | None = "0755571733db"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add the durable action execution progress event kind."""
    op.execute(
        "ALTER TYPE event_kind ADD VALUE IF NOT EXISTS 'action_execution_progress'"
    )


def downgrade() -> None:
    """Keep the PostgreSQL enum value during downgrade."""
