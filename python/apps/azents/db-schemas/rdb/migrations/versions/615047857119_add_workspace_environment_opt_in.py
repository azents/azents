"""Add Workspace environment identities and default-empty Agent selections."""

from typing import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "615047857119"
down_revision: str | Sequence[str] | None = "e5bb444eed80"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create empty tables without opting any Agent into shared secrets."""
    op.create_table(
        "workspace_environment_variables",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column(
            "workspace_id",
            sa.String(32),
            sa.ForeignKey("workspaces.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("name", sa.String(64), nullable=False),
        sa.Column("encrypted_value", sa.Text(), nullable=False),
        sa.UniqueConstraint(
            "workspace_id", "name", name="uq_workspace_environment_name"
        ),
    )
    op.create_table(
        "agent_workspace_environment_selections",
        sa.Column(
            "agent_id",
            sa.String(32),
            sa.ForeignKey("agents.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column(
            "variable_id",
            sa.String(32),
            sa.ForeignKey("workspace_environment_variables.id", ondelete="CASCADE"),
            primary_key=True,
        ),
    )
    op.create_index(
        "ix_agent_workspace_env_variable",
        "agent_workspace_environment_selections",
        ["variable_id"],
    )


def downgrade() -> None:
    """Remove shared settings without changing existing Agent-only values."""
    op.drop_table("agent_workspace_environment_selections")
    op.drop_table("workspace_environment_variables")
