"""add_github_pats_table

Revision ID: 9e78ce79930f
Revises: df2a19fc785c
Create Date: 2026-03-21 07:10:00.000000

"""

from typing import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "9e78ce79930f"
down_revision: str | Sequence[str] | None = "df2a19fc785c"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create the github_pats table."""
    op.create_table(
        "github_pats",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column(
            "workspace_id",
            sa.String(32),
            sa.ForeignKey("workspaces.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "user_id",
            sa.String(32),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("encrypted_token", sa.Text, nullable=False),
        sa.Column("github_username", sa.String(100), nullable=True),
        sa.Column("display_hint", sa.String(20), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.UniqueConstraint(
            "workspace_id", "user_id", name="uq_github_pats_workspace_user"
        ),
    )
    op.create_index("ix_github_pats_workspace_id", "github_pats", ["workspace_id"])


def downgrade() -> None:
    """Drop the github_pats table."""
    op.drop_index("ix_github_pats_workspace_id", table_name="github_pats")
    op.drop_table("github_pats")
