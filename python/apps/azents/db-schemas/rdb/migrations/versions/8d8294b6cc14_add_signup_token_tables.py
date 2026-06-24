"""add signup token tables

Revision ID: 8d8294b6cc14
Revises: 283acd188c50
Create Date: 2026-06-17 12:59:21.845078

"""

from typing import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "8d8294b6cc14"
down_revision: str | Sequence[str] | None = "283acd188c50"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    signup_token_delivery_method = postgresql.ENUM(
        "manual",
        "email",
        name="signup_token_delivery_method",
        create_type=False,
    )
    signup_token_delivery_method.create(op.get_bind())

    op.create_table(
        "signup_tokens",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column("email", sa.String(length=255), nullable=False),
        sa.Column("created_by_user_id", sa.String(length=32), nullable=True),
        sa.Column(
            "delivery_method",
            signup_token_delivery_method,
            nullable=False,
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("max_uses", sa.Integer(), nullable=False),
        sa.Column("used_count", sa.Integer(), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "max_uses > 0",
            name="ck_signup_tokens_max_uses_positive",
        ),
        sa.CheckConstraint(
            "used_count >= 0 AND used_count <= max_uses",
            name="ck_signup_tokens_used_count_range",
        ),
        sa.ForeignKeyConstraint(
            ["created_by_user_id"],
            ["users.id"],
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("token_hash", name="uq_signup_tokens_token_hash"),
    )
    op.create_index("ix_signup_tokens_email", "signup_tokens", ["email"])
    op.create_index("ix_signup_tokens_expires_at", "signup_tokens", ["expires_at"])
    op.create_index(
        "ix_signup_tokens_created_by_user_id",
        "signup_tokens",
        ["created_by_user_id"],
    )
    op.create_index("ix_signup_tokens_revoked_at", "signup_tokens", ["revoked_at"])

    op.create_table(
        "signup_token_redemptions",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("signup_token_id", sa.String(length=32), nullable=False),
        sa.Column("user_id", sa.String(length=32), nullable=False),
        sa.Column("email", sa.String(length=255), nullable=False),
        sa.Column("ip_address", sa.String(length=64), nullable=True),
        sa.Column("user_agent", sa.Text(), nullable=True),
        sa.Column("redeemed_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["signup_token_id"],
            ["signup_tokens.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_signup_token_redemptions_signup_token_id",
        "signup_token_redemptions",
        ["signup_token_id"],
    )
    op.create_index(
        "ix_signup_token_redemptions_user_id",
        "signup_token_redemptions",
        ["user_id"],
    )
    op.create_index(
        "ix_signup_token_redemptions_email",
        "signup_token_redemptions",
        ["email"],
    )
    op.create_index(
        "ix_signup_token_redemptions_redeemed_at",
        "signup_token_redemptions",
        ["redeemed_at"],
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(
        "ix_signup_token_redemptions_redeemed_at",
        table_name="signup_token_redemptions",
    )
    op.drop_index(
        "ix_signup_token_redemptions_email",
        table_name="signup_token_redemptions",
    )
    op.drop_index(
        "ix_signup_token_redemptions_user_id",
        table_name="signup_token_redemptions",
    )
    op.drop_index(
        "ix_signup_token_redemptions_signup_token_id",
        table_name="signup_token_redemptions",
    )
    op.drop_table("signup_token_redemptions")
    op.drop_index("ix_signup_tokens_revoked_at", table_name="signup_tokens")
    op.drop_index(
        "ix_signup_tokens_created_by_user_id",
        table_name="signup_tokens",
    )
    op.drop_index("ix_signup_tokens_expires_at", table_name="signup_tokens")
    op.drop_index("ix_signup_tokens_email", table_name="signup_tokens")
    op.drop_table("signup_tokens")

    signup_token_delivery_method = postgresql.ENUM(
        "manual",
        "email",
        name="signup_token_delivery_method",
        create_type=False,
    )
    signup_token_delivery_method.drop(op.get_bind())
