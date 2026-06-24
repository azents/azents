"""add password reset tokens

Revision ID: 38703f9ea36e
Revises: 8d8294b6cc14
Create Date: 2026-06-18 06:28:35.145008

"""

from typing import Sequence

import sqlalchemy as sa
from alembic import op

from azents.rdb.types.datetime import TimeZoneDateTime

revision: str = "38703f9ea36e"
down_revision: str | Sequence[str] | None = "8d8294b6cc14"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add the password reset token table."""
    op.create_table(
        "password_reset_tokens",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column("user_id", sa.String(length=32), nullable=False),
        sa.Column("created_by_user_id", sa.String(length=32), nullable=True),
        sa.Column("expires_at", TimeZoneDateTime(), nullable=False),
        sa.Column("used_at", TimeZoneDateTime(), nullable=True),
        sa.Column("revoked_at", TimeZoneDateTime(), nullable=True),
        sa.Column(
            "created_at",
            TimeZoneDateTime(),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            TimeZoneDateTime(),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["created_by_user_id"],
            ["users.id"],
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "token_hash",
            name="uq_password_reset_tokens_token_hash",
        ),
    )
    op.create_index(
        "ix_password_reset_tokens_user_id",
        "password_reset_tokens",
        ["user_id"],
    )
    op.create_index(
        "ix_password_reset_tokens_created_by_user_id",
        "password_reset_tokens",
        ["created_by_user_id"],
    )
    op.create_index(
        "ix_password_reset_tokens_expires_at",
        "password_reset_tokens",
        ["expires_at"],
    )
    op.create_index(
        "ix_password_reset_tokens_revoked_at",
        "password_reset_tokens",
        ["revoked_at"],
    )

    op.create_table(
        "password_reset_token_redemptions",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("password_reset_token_id", sa.String(length=32), nullable=False),
        sa.Column("user_id", sa.String(length=32), nullable=False),
        sa.Column("redeemed_at", TimeZoneDateTime(), nullable=False),
        sa.Column("ip_address", sa.String(length=64), nullable=True),
        sa.Column("user_agent", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(
            ["password_reset_token_id"],
            ["password_reset_tokens.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_password_reset_token_redemptions_password_reset_token_id",
        "password_reset_token_redemptions",
        ["password_reset_token_id"],
    )
    op.create_index(
        "ix_password_reset_token_redemptions_user_id",
        "password_reset_token_redemptions",
        ["user_id"],
    )
    op.create_index(
        "ix_password_reset_token_redemptions_redeemed_at",
        "password_reset_token_redemptions",
        ["redeemed_at"],
    )


def downgrade() -> None:
    """Remove the password reset token table."""
    op.drop_index(
        "ix_password_reset_token_redemptions_redeemed_at",
        table_name="password_reset_token_redemptions",
    )
    op.drop_index(
        "ix_password_reset_token_redemptions_user_id",
        table_name="password_reset_token_redemptions",
    )
    op.drop_index(
        "ix_password_reset_token_redemptions_password_reset_token_id",
        table_name="password_reset_token_redemptions",
    )
    op.drop_table("password_reset_token_redemptions")
    op.drop_index(
        "ix_password_reset_tokens_revoked_at",
        table_name="password_reset_tokens",
    )
    op.drop_index(
        "ix_password_reset_tokens_expires_at",
        table_name="password_reset_tokens",
    )
    op.drop_index(
        "ix_password_reset_tokens_created_by_user_id",
        table_name="password_reset_tokens",
    )
    op.drop_index(
        "ix_password_reset_tokens_user_id",
        table_name="password_reset_tokens",
    )
    op.drop_table("password_reset_tokens")
