"""Add Kimi OAuth subscription schema.

Revision ID: c0a51320cfdb
Revises: a4d69bcc02e2
Create Date: 2026-07-19 20:08:57.580963

"""

from typing import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

from azents.rdb.types.datetime import TimeZoneDateTime

revision: str = "c0a51320cfdb"
down_revision: str | Sequence[str] | None = "a4d69bcc02e2"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add Kimi OAuth provider, session enums, and encrypted session table."""
    sa.Enum(
        "pending",
        "connected",
        "cancelled",
        "expired",
        "failed",
        name="kimi_oauth_session_status",
    ).create(op.get_bind())
    sa.Enum("device", name="kimi_oauth_connection_method").create(op.get_bind())
    with op.get_context().autocommit_block():
        op.execute("ALTER TYPE llm_provider ADD VALUE IF NOT EXISTS 'kimi_oauth'")
    op.create_table(
        "kimi_oauth_sessions",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("workspace_id", sa.String(length=32), nullable=False),
        sa.Column("user_id", sa.String(length=32), nullable=False),
        sa.Column(
            "method",
            postgresql.ENUM(
                "device",
                name="kimi_oauth_connection_method",
                create_type=False,
            ),
            nullable=False,
        ),
        sa.Column("encrypted_device_code", sa.Text(), nullable=False),
        sa.Column("encrypted_device_id", sa.Text(), nullable=False),
        sa.Column("user_code", sa.String(length=128), nullable=False),
        sa.Column("verification_uri", sa.Text(), nullable=False),
        sa.Column("interval_seconds", sa.Integer(), nullable=False),
        sa.Column(
            "expires_at",
            TimeZoneDateTime(timezone=True),
            nullable=False,
        ),
        sa.Column(
            "status",
            postgresql.ENUM(
                "pending",
                "connected",
                "cancelled",
                "expired",
                "failed",
                name="kimi_oauth_session_status",
                create_type=False,
            ),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            TimeZoneDateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            TimeZoneDateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["workspace_id"],
            ["workspaces.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_kimi_oauth_sessions_user_id",
        "kimi_oauth_sessions",
        ["user_id"],
        unique=False,
    )
    op.create_index(
        "ix_kimi_oauth_sessions_workspace_id",
        "kimi_oauth_sessions",
        ["workspace_id"],
        unique=False,
    )


def downgrade() -> None:
    """Remove Kimi OAuth sessions while retaining the provider enum value."""
    op.drop_index(
        "ix_kimi_oauth_sessions_workspace_id",
        table_name="kimi_oauth_sessions",
    )
    op.drop_index(
        "ix_kimi_oauth_sessions_user_id",
        table_name="kimi_oauth_sessions",
    )
    op.drop_table("kimi_oauth_sessions")
    sa.Enum("device", name="kimi_oauth_connection_method").drop(op.get_bind())
    sa.Enum(
        "pending",
        "connected",
        "cancelled",
        "expired",
        "failed",
        name="kimi_oauth_session_status",
    ).drop(op.get_bind())
