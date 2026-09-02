"""Drop the obsolete Agent Shell policy column."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "7de5749cadd5"
down_revision: str | Sequence[str] | None = "82df4f970f57"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Remove the obsolete Agent Shell policy."""
    op.drop_column("agents", "shell_enabled")


def downgrade() -> None:
    """Restore a default-enabled Agent Shell policy."""
    op.add_column(
        "agents",
        sa.Column(
            "shell_enabled",
            sa.Boolean(),
            server_default=sa.true(),
            nullable=False,
        ),
    )
