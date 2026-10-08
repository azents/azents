"""Add Toolkit-local GitHub user connections and staged authorization."""

from typing import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "8c432dfdd6c6"
down_revision: str | Sequence[str] | None = "7b6d0eb501fb"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add isolated user-mode state without converting existing credentials."""
    attempt = postgresql.ENUM(
        "pending",
        "exchanging",
        "review",
        name="github_user_attempt_status",
        create_type=False,
    )
    connection = postgresql.ENUM(
        "connected",
        "reconnect_required",
        name="github_user_connection_status",
        create_type=False,
    )
    for enum in (attempt, connection):
        enum.create(op.get_bind(), checkfirst=True)
    op.create_table(
        "github_user_oauth_connections",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column(
            "toolkit_id",
            sa.String(32),
            sa.ForeignKey("toolkit_configs.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("app_id", sa.String(64), nullable=False),
        sa.Column("account_id", sa.BigInteger(), nullable=False),
        sa.Column("account_login", sa.String(255), nullable=False),
        sa.Column("account_avatar_url", sa.Text(), nullable=True),
        sa.Column("encrypted_access_token", sa.Text(), nullable=False),
        sa.Column("encrypted_registration", sa.Text(), nullable=False),
        sa.Column("status", connection, nullable=False),
        sa.Column("failure_reason", sa.String(64), nullable=True),
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
            "toolkit_id", name="uq_github_user_oauth_connections_toolkit"
        ),
    )
    op.create_index(
        "ix_github_user_oauth_connections_toolkit",
        "github_user_oauth_connections",
        ["toolkit_id"],
    )
    op.create_table(
        "github_user_oauth_attempts",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column(
            "toolkit_id",
            sa.String(32),
            sa.ForeignKey("toolkit_configs.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("user_id", sa.String(32), nullable=False),
        sa.Column("session_id", sa.String(32), nullable=False),
        sa.Column("workspace_id", sa.String(32), nullable=False),
        sa.Column("agent_id", sa.String(32), nullable=True),
        sa.Column("encrypted_setup", sa.Text(), nullable=False),
        sa.Column("encrypted_candidate", sa.Text(), nullable=True),
        sa.Column("captured_connection_id", sa.String(32), nullable=True),
        sa.Column("status", attempt, nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    op.create_index(
        "ix_github_user_oauth_attempts_toolkit",
        "github_user_oauth_attempts",
        ["toolkit_id"],
    )
    op.create_index(
        "uq_github_user_oauth_attempts_current",
        "github_user_oauth_attempts",
        ["toolkit_id"],
        unique=True,
    )


def downgrade() -> None:
    """Require explicit local credential removal before destructive rollback."""
    bind = op.get_bind()
    if bind.scalar(
        sa.text("SELECT EXISTS (SELECT 1 FROM github_user_oauth_connections)")
    ) or bind.scalar(
        sa.text(
            "SELECT EXISTS (SELECT 1 FROM github_user_oauth_attempts "
            "WHERE encrypted_candidate IS NOT NULL)"
        )
    ):
        raise RuntimeError(
            "Disconnect or explicitly remove local GitHub user credentials "
            "before schema downgrade."
        )
    op.drop_table("github_user_oauth_attempts")
    op.drop_table("github_user_oauth_connections")
    for name in ("github_user_attempt_status", "github_user_connection_status"):
        postgresql.ENUM(name=name).drop(op.get_bind(), checkfirst=True)
