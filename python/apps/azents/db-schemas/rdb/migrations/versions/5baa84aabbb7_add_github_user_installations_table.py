"""add github_user_installations table

Revision ID: 5baa84aabbb7
Revises: a20651a5a9fe
Create Date: 2026-03-14

"""

from typing import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "5baa84aabbb7"
down_revision: str | Sequence[str] | None = "a20651a5a9fe"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create the github_user_installations table."""
    op.create_table(
        "github_user_installations",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column(
            "user_id",
            sa.String(32),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("installation_id", sa.BigInteger, nullable=False),
        sa.Column("account_login", sa.String(255), nullable=False),
        sa.Column("account_type", sa.String(50), nullable=False),
        sa.Column("account_avatar_url", sa.Text, nullable=False, server_default=""),
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
            "user_id",
            "installation_id",
            name="uq_github_user_installations_user_installation",
        ),
    )
    op.create_index(
        "ix_github_user_installations_user_id",
        "github_user_installations",
        ["user_id"],
    )


def downgrade() -> None:
    """Drop the github_user_installations table."""
    op.drop_index(
        "ix_github_user_installations_user_id",
        table_name="github_user_installations",
    )
    op.drop_table("github_user_installations")
