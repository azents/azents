"""create teams table

Revision ID: a1628b972d3b
Revises: f0d61771feb3
Create Date: 2026-02-11 23:39:14.800163

"""

from typing import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "a1628b972d3b"
down_revision: str | Sequence[str] | None = "f0d61771feb3"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create the teams table."""
    op.create_table(
        "teams",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column(
            "workspace_id",
            sa.String(32),
            sa.ForeignKey("workspaces.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "parent_team_id",
            sa.String(32),
            sa.ForeignKey("teams.id", ondelete="CASCADE"),
            nullable=True,
        ),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("slug", sa.String(255), nullable=False),
        sa.Column("depth", sa.Integer, nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.UniqueConstraint("workspace_id", "slug", name="uq_teams_workspace_slug"),
        sa.CheckConstraint("depth >= 1 AND depth <= 3", name="chk_teams_depth"),
    )
    op.create_index("ix_teams_workspace_id", "teams", ["workspace_id"])
    op.create_index("ix_teams_parent_team_id", "teams", ["parent_team_id"])


def downgrade() -> None:
    """Drop the teams table."""
    op.drop_index("ix_teams_parent_team_id", table_name="teams")
    op.drop_index("ix_teams_workspace_id", table_name="teams")
    op.drop_table("teams")
