"""drop github pats

Revision ID: b7d540720215
Revises: 8dfc9b5e1a2c
Create Date: 2026-06-28 18:08:50.294888

"""

from typing import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "b7d540720215"
down_revision: str | Sequence[str] | None = "8dfc9b5e1a2c"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Drop legacy GitHub PAT storage."""
    op.drop_index("ix_github_pats_workspace_id", table_name="github_pats")
    op.drop_table("github_pats")


def downgrade() -> None:
    """Recreate legacy GitHub PAT storage."""
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
