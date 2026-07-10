"""add xai oauth sessions

Revision ID: bbdfefd7ddf2
Revises: f79809732650
Create Date: 2026-07-09 17:17:10.441383

"""

from typing import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "bbdfefd7ddf2"
down_revision: str | Sequence[str] | None = "aa9f349ff8fe"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add the xAI OAuth provider session schema."""
    with op.get_context().autocommit_block():
        op.execute("ALTER TYPE llm_provider ADD VALUE IF NOT EXISTS 'xai_oauth'")
    sa.Enum(
        "device",
        name="xai_oauth_connection_method",
    ).create(op.get_bind())
    sa.Enum(
        "pending",
        "connected",
        "cancelled",
        "expired",
        "failed",
        name="xai_oauth_session_status",
    ).create(op.get_bind())

    connection_method_enum = postgresql.ENUM(
        name="xai_oauth_connection_method", create_type=False
    )
    session_status_enum = postgresql.ENUM(
        name="xai_oauth_session_status", create_type=False
    )

    op.create_table(
        "xai_oauth_sessions",
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
        sa.Column("method", connection_method_enum, nullable=False),
        sa.Column("encrypted_device_code", sa.Text, nullable=False),
        sa.Column("user_code", sa.String(128), nullable=False),
        sa.Column("verification_uri", sa.Text, nullable=False),
        sa.Column("interval_seconds", sa.Integer, nullable=False),
        sa.Column(
            "status",
            session_status_enum,
            nullable=False,
            server_default="pending",
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
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
    )
    op.create_index(
        "ix_xai_oauth_sessions_workspace_id",
        "xai_oauth_sessions",
        ["workspace_id"],
    )
    op.create_index(
        "ix_xai_oauth_sessions_user_id",
        "xai_oauth_sessions",
        ["user_id"],
    )


def downgrade() -> None:
    """Remove the xAI OAuth provider session schema."""
    op.drop_index("ix_xai_oauth_sessions_user_id", table_name="xai_oauth_sessions")
    op.drop_index(
        "ix_xai_oauth_sessions_workspace_id",
        table_name="xai_oauth_sessions",
    )
    op.drop_table("xai_oauth_sessions")
    sa.Enum(name="xai_oauth_session_status").drop(op.get_bind())
    sa.Enum(name="xai_oauth_connection_method").drop(op.get_bind())
