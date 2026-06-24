"""add auth tables

Revision ID: e34887ecbee0
Revises: 8f9eb22d95aa
Create Date: 2026-02-16 00:10:37.449661

"""

# pyright: reportUnknownArgumentType=false

from typing import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "e34887ecbee0"
down_revision: str | Sequence[str] | None = "8f9eb22d95aa"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create authentication-related tables."""
    # 1. Create workspace_user_role enum
    sa.Enum("owner", "manager", "member", name="workspace_user_role").create(
        op.get_bind()
    )
    role_enum = postgresql.ENUM(name="workspace_user_role", create_type=False)

    # 2. Add role column to workspace_users table
    op.add_column(
        "workspace_users",
        sa.Column(
            "role",
            role_enum,
            nullable=False,
            server_default="member",
        ),
    )

    # 3. Create workspace_user_identities table
    op.create_table(
        "workspace_user_identities",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column(
            "workspace_id",
            sa.String(32),
            sa.ForeignKey("workspaces.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "workspace_user_id",
            sa.String(32),
            sa.ForeignKey("workspace_users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("email", sa.String(255), nullable=False),
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
        sa.UniqueConstraint(
            "workspace_id",
            "email",
            name="uq_workspace_user_identities_workspace_email",
        ),
        sa.UniqueConstraint(
            "workspace_user_id",
            name="uq_workspace_user_identities_workspace_user",
        ),
    )

    # 4. Create password_logins table
    op.create_table(
        "password_logins",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column(
            "workspace_user_identity_id",
            sa.String(32),
            sa.ForeignKey("workspace_user_identities.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("password_hash", sa.Text, nullable=False),
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
        sa.UniqueConstraint(
            "workspace_user_identity_id",
            name="uq_password_logins_identity",
        ),
    )

    # 5. Create sessions table
    op.create_table(
        "sessions",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column(
            "workspace_user_identity_id",
            sa.String(32),
            sa.ForeignKey("workspace_user_identities.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("refresh_token", sa.String(64), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("prev_refresh_token", sa.String(64), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("user_agent", sa.Text, nullable=True),
        sa.Column("ip_address", sa.String(45), nullable=True),
        sa.Column("max_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "refresh_token_created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "last_used_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
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
        sa.UniqueConstraint("refresh_token", name="uq_sessions_refresh_token"),
    )
    op.create_index(
        "ix_sessions_workspace_user_identity_id",
        "sessions",
        ["workspace_user_identity_id"],
    )
    op.create_index("ix_sessions_refresh_token", "sessions", ["refresh_token"])
    op.create_index(
        "ix_sessions_prev_refresh_token", "sessions", ["prev_refresh_token"]
    )

    # 6. Create signup_email_verifications table
    op.create_table(
        "signup_email_verifications",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("email", sa.String(255), nullable=False),
        sa.Column("code", sa.String(6), nullable=False),
        sa.Column("csrf_token", sa.String(64), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("verified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )

    # 7. Create login_email_verifications table
    op.create_table(
        "login_email_verifications",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column(
            "workspace_id",
            sa.String(32),
            sa.ForeignKey("workspaces.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("email", sa.String(255), nullable=False),
        sa.Column("code", sa.String(6), nullable=False),
        sa.Column("csrf_token", sa.String(64), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("verified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )


def downgrade() -> None:
    """Drop authentication-related tables."""
    op.drop_table("login_email_verifications")
    op.drop_table("signup_email_verifications")
    op.drop_index("ix_sessions_prev_refresh_token", table_name="sessions")
    op.drop_index("ix_sessions_refresh_token", table_name="sessions")
    op.drop_index("ix_sessions_workspace_user_identity_id", table_name="sessions")
    op.drop_table("sessions")
    op.drop_table("password_logins")
    op.drop_table("workspace_user_identities")
    op.drop_column("workspace_users", "role")
    sa.Enum(name="workspace_user_role").drop(op.get_bind())
