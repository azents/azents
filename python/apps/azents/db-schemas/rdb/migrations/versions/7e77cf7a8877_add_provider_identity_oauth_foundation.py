"""Add provider identity OAuth foundation."""

from typing import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "7e77cf7a8877"
down_revision: str | Sequence[str] | None = "c05bc1b811fa"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.execute(
        "ALTER TYPE system_setting_section ADD VALUE IF NOT EXISTS "
        "'slack_identity_oauth'"
    )
    op.execute(
        "ALTER TYPE system_setting_section ADD VALUE IF NOT EXISTS "
        "'discord_identity_oauth'"
    )
    postgresql.ENUM(
        "open",
        "claimed",
        "completed",
        "failed",
        "expired",
        name="external_account_oauth_attempt_status",
    ).create(op.get_bind(), checkfirst=True)
    op.create_table(
        "external_account_oauth_attempts",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("state_hash", sa.String(length=64), nullable=False),
        sa.Column("user_id", sa.String(length=32), nullable=False),
        sa.Column("auth_session_id", sa.String(length=32), nullable=False),
        sa.Column(
            "provider",
            postgresql.ENUM(
                "slack", "discord", name="external_channel_provider", create_type=False
            ),
            nullable=False,
        ),
        sa.Column("setting_generation", sa.String(length=64), nullable=False),
        sa.Column("redirect_uri", sa.Text(), nullable=False),
        sa.Column("encrypted_pkce_verifier", sa.Text(), nullable=True),
        sa.Column(
            "status",
            postgresql.ENUM(
                name="external_account_oauth_attempt_status", create_type=False
            ),
            server_default="open",
            nullable=False,
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("claimed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("failed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("failure_code", sa.String(length=120), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["auth_session_id"], ["sessions.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "state_hash",
            name="uq_external_account_oauth_attempts_state_hash",
        ),
    )
    op.create_index(
        "ix_external_account_oauth_attempts_user_session",
        "external_account_oauth_attempts",
        ["user_id", "auth_session_id"],
    )
    op.create_index(
        "ix_external_account_oauth_attempts_expires_at",
        "external_account_oauth_attempts",
        ["expires_at"],
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(
        "ix_external_account_oauth_attempts_expires_at",
        table_name="external_account_oauth_attempts",
    )
    op.drop_index(
        "ix_external_account_oauth_attempts_user_session",
        table_name="external_account_oauth_attempts",
    )
    op.drop_table("external_account_oauth_attempts")
    postgresql.ENUM(name="external_account_oauth_attempt_status").drop(
        op.get_bind(), checkfirst=True
    )
