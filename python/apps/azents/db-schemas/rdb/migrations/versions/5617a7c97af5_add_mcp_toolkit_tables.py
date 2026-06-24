"""add_mcp_toolkit_tables

Revision ID: 5617a7c97af5
Revises: cd45c5a32e37
Create Date: 2026-02-27 16:37:04.112530

"""

from typing import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "5617a7c97af5"
down_revision: str | Sequence[str] | None = "cd45c5a32e37"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add MCP Toolkit related columns and tables."""
    # 1. Add encrypted_credentials column to the toolkits table
    op.add_column(
        "toolkits",
        sa.Column("encrypted_credentials", sa.Text, nullable=True),
    )

    # 2. Create the mcp_oauth2_tokens table
    op.create_table(
        "mcp_oauth2_tokens",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column(
            "toolkit_id",
            sa.String(32),
            sa.ForeignKey("toolkits.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "user_id",
            sa.String(32),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("encrypted_access_token", sa.Text, nullable=False),
        sa.Column("encrypted_refresh_token", sa.Text, nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("token_type", sa.String(50), nullable=False, server_default="Bearer"),
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
            "toolkit_id", "user_id", name="uq_mcp_oauth2_tokens_toolkit_user"
        ),
    )
    op.create_index(
        "ix_mcp_oauth2_tokens_toolkit_id", "mcp_oauth2_tokens", ["toolkit_id"]
    )

    # 3. Create the mcp_auth_requests table
    op.create_table(
        "mcp_auth_requests",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column(
            "toolkit_id",
            sa.String(32),
            sa.ForeignKey("toolkits.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "user_id",
            sa.String(32),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "muted",
            sa.Boolean,
            nullable=False,
            server_default=sa.text("false"),
        ),
        sa.Column("last_requested_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_run_id", sa.String(64), nullable=True),
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
            "toolkit_id", "user_id", name="uq_mcp_auth_requests_toolkit_user"
        ),
    )
    op.create_index(
        "ix_mcp_auth_requests_toolkit_id", "mcp_auth_requests", ["toolkit_id"]
    )


def downgrade() -> None:
    """Drop MCP Toolkit related columns and tables."""
    op.drop_index("ix_mcp_auth_requests_toolkit_id", table_name="mcp_auth_requests")
    op.drop_table("mcp_auth_requests")

    op.drop_index("ix_mcp_oauth2_tokens_toolkit_id", table_name="mcp_oauth2_tokens")
    op.drop_table("mcp_oauth2_tokens")

    op.drop_column("toolkits", "encrypted_credentials")
