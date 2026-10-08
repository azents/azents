"""Remove obsolete Toolkit visibility assignments without changing resources."""

from collections.abc import Sequence

from alembic import op
from sqlalchemy.dialects.postgresql import ENUM

revision: str = "7b6d0eb501fb"
down_revision: str | Sequence[str] | None = "95521a5a1bbc"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Delete visibility state and fail on unexpected dependencies."""
    op.drop_table("toolkit_scopes")
    ENUM(name="toolkit_scope_type").drop(op.get_bind(), checkfirst=False)


def downgrade() -> None:
    """Reject inventing historical visibility assignments after deletion."""
    raise RuntimeError(
        "Toolkit visibility scope removal is irreversible and forward-only; "
        "use a forward fix or an explicitly approved matching schema/data restore."
    )
