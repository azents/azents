"""Add isolated Google connection authority without changing existing grants."""

from typing import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "e5bb444eed80"
down_revision: str | Sequence[str] | None = "042a6603f202"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add one current grant and encrypted unpublished attempt/outcome storage."""
    op.execute(
        "ALTER TYPE system_setting_section ADD VALUE IF NOT EXISTS 'google_oauth' "
        "AFTER 'platform_github_app'"
    )
    op.execute(
        "CREATE TYPE google_oauth_connection_status AS ENUM "
        "('connected', 'reconnect_required')"
    )
    op.execute(
        "CREATE TYPE google_oauth_attempt_status AS ENUM "
        "('pending', 'exchanging', 'review', 'published', 'cancelled', 'failed')"
    )
    op.create_table(
        "google_oauth_connections",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column(
            "toolkit_id",
            sa.String(32),
            sa.ForeignKey("toolkit_configs.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("client_id", sa.Text(), nullable=False),
        sa.Column("encrypted_payload", sa.Text(), nullable=False),
        sa.Column(
            "status",
            postgresql.ENUM(
                "connected",
                "reconnect_required",
                name="google_oauth_connection_status",
                create_type=False,
            ),
            nullable=False,
        ),
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
        sa.UniqueConstraint("toolkit_id", name="uq_google_oauth_connections_toolkit"),
    )
    op.create_index(
        "ix_google_oauth_connections_toolkit",
        "google_oauth_connections",
        ["toolkit_id"],
    )
    op.create_table(
        "google_oauth_attempts",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("user_id", sa.String(32), nullable=False),
        sa.Column("session_id", sa.String(32), nullable=False),
        sa.Column(
            "workspace_id",
            sa.String(32),
            sa.ForeignKey("workspaces.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "agent_id",
            sa.String(32),
            sa.ForeignKey("agents.id", ondelete="CASCADE"),
            nullable=True,
        ),
        sa.Column(
            "target_toolkit_id",
            sa.String(32),
            sa.ForeignKey("toolkit_configs.id", ondelete="CASCADE"),
            nullable=True,
        ),
        sa.Column("encrypted_setup", sa.Text(), nullable=True),
        sa.Column("encrypted_candidate", sa.Text(), nullable=True),
        sa.Column(
            "status",
            postgresql.ENUM(
                "pending",
                "exchanging",
                "review",
                "published",
                "cancelled",
                "failed",
                name="google_oauth_attempt_status",
                create_type=False,
            ),
            nullable=False,
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("published_toolkit_id", sa.String(32), nullable=True),
        sa.Column("published_connection_id", sa.String(32), nullable=True),
        sa.Column("final_settings", postgresql.JSONB(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_index(
        "ix_google_oauth_attempts_scope",
        "google_oauth_attempts",
        ["session_id", "workspace_id", "agent_id"],
    )
    op.create_index(
        "ix_google_oauth_attempts_expiry", "google_oauth_attempts", ["expires_at"]
    )
    op.create_index(
        "ix_google_oauth_attempts_target",
        "google_oauth_attempts",
        ["target_toolkit_id"],
    )


def downgrade() -> None:
    """Permit empty-schema rollback only; never silently delete Google credentials."""
    populated = op.get_bind().scalar(
        sa.text(
            "SELECT EXISTS (SELECT 1 FROM google_oauth_connections)"
            " OR EXISTS (SELECT 1 FROM google_oauth_attempts)"
            " OR EXISTS (SELECT 1 FROM toolkit_configs WHERE toolkit_type = 'google')"
            " OR EXISTS (SELECT 1 FROM system_settings WHERE section = 'google_oauth')"
        )
    )
    if populated:
        raise RuntimeError(
            "Google authorization data exists. Preserve the schema and disable "
            "Google exposure before application rollback."
        )
    op.drop_table("google_oauth_attempts")
    op.drop_table("google_oauth_connections")
    op.execute("DROP TYPE google_oauth_attempt_status")
    op.execute("DROP TYPE google_oauth_connection_status")
    # The unused additive Section enum value is retained; rebuilding a shared
    # enum is unnecessary for empty Google rollback and risks unrelated settings.
