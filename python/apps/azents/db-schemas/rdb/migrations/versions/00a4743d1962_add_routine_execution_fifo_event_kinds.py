"""Add Routine execution FIFO event kinds."""

from typing import Sequence

from alembic import op

revision: str = "00a4743d1962"
down_revision: str | Sequence[str] | None = "854782c43687"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add explicit Routine input kinds at their canonical enum positions."""
    op.execute(
        "ALTER TYPE event_kind ADD VALUE 'routine_trigger' AFTER 'routine_judgment'"
    )
    op.execute(
        "ALTER TYPE event_kind ADD VALUE 'routine_continuation' AFTER 'routine_trigger'"
    )
    op.execute(
        "ALTER TYPE event_kind ADD VALUE 'routine_notification' AFTER 'goal_updated'"
    )
    op.execute(
        "ALTER TYPE mailbox_item_kind ADD VALUE 'routine_trigger' "
        "AFTER 'turn_action_continuation'"
    )
    op.execute(
        "ALTER TYPE mailbox_item_kind ADD VALUE 'routine_continuation' "
        "AFTER 'routine_trigger'"
    )


def downgrade() -> None:
    """Preserve retained occurrence input instead of deleting execution authority."""
    raise RuntimeError("Routine execution input migration is irreversible.")
