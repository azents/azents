"""Add Terminal policy columns."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "82df4f970f57"
down_revision: str | Sequence[str] | None = "a66397c7eabc"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add default-enabled Terminal policy at all three scopes."""
    op.add_column(
        "runtime_infrastructure_profiles",
        sa.Column(
            "terminal_enabled",
            sa.Boolean(),
            server_default=sa.true(),
            nullable=False,
        ),
    )
    op.add_column(
        "workspace_runtime_profiles",
        sa.Column(
            "terminal_enabled",
            sa.Boolean(),
            server_default=sa.true(),
            nullable=False,
        ),
    )
    op.add_column(
        "agents",
        sa.Column(
            "terminal_enabled",
            sa.Boolean(),
            server_default=sa.true(),
            nullable=False,
        ),
    )


def downgrade() -> None:
    """Remove Terminal policy columns."""
    op.drop_column("agents", "terminal_enabled")
    op.drop_column("workspace_runtime_profiles", "terminal_enabled")
    op.drop_column("runtime_infrastructure_profiles", "terminal_enabled")
