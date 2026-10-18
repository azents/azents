"""Add purpose-owned Routine judgment observation without normal Run usage."""

from collections.abc import Sequence

from alembic import op

revision: str = "854782c43687"
down_revision: str | Sequence[str] | None = "08a588456917"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Register the typed Session observation in the existing event stream."""
    op.execute(
        "ALTER TYPE event_kind ADD VALUE 'routine_judgment' BEFORE 'goal_updated'"
    )


def downgrade() -> None:
    """Do not remove retained judgment history as an implicit downgrade policy."""
    raise RuntimeError("Routine judgment observation migration is irreversible.")
