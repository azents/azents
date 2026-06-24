"""add mcp oauth connections

Revision ID: 5eb526754a74
Revises: c57516043fac
Create Date: 2026-06-23 02:41:23.912229

"""

from typing import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "5eb526754a74"
down_revision: str | Sequence[str] | None = "c57516043fac"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    mcp_oauth_connection_status = postgresql.ENUM(
        "connected",
        "reconnect_required",
        name="mcp_oauth_connection_status",
    )
    mcp_oauth_connection_status.create(op.get_bind(), checkfirst=True)

    op.create_table(
        "mcp_oauth_connections",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("toolkit_id", sa.String(length=32), nullable=False),
        sa.Column("issuer", sa.Text(), nullable=True),
        sa.Column("resource", sa.Text(), nullable=True),
        sa.Column("server_url", sa.Text(), nullable=False),
        sa.Column("authorization_endpoint", sa.Text(), nullable=False),
        sa.Column("token_endpoint", sa.Text(), nullable=False),
        sa.Column("registration_endpoint", sa.Text(), nullable=True),
        sa.Column("encrypted_client_id", sa.Text(), nullable=False),
        sa.Column("encrypted_client_secret", sa.Text(), nullable=True),
        sa.Column(
            "token_endpoint_auth_method",
            sa.String(length=64),
            nullable=False,
        ),
        sa.Column("scope", sa.Text(), nullable=True),
        sa.Column("encrypted_access_token", sa.Text(), nullable=True),
        sa.Column("encrypted_refresh_token", sa.Text(), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "status",
            postgresql.ENUM(
                "connected",
                "reconnect_required",
                name="mcp_oauth_connection_status",
                create_type=False,
            ),
            nullable=False,
        ),
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
        sa.ForeignKeyConstraint(
            ["toolkit_id"],
            ["toolkit_configs.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "toolkit_id",
            name="uq_mcp_oauth_connections_toolkit_id",
        ),
    )
    op.create_index(
        "ix_mcp_oauth_connections_toolkit_id",
        "mcp_oauth_connections",
        ["toolkit_id"],
        unique=False,
    )

    op.execute(
        """
        UPDATE toolkit_configs
        SET enabled = false,
            config = jsonb_set(config, '{auth_type}', '"oauth2"'::jsonb, true)
        WHERE config->>'auth_type' = 'oauth2_per_user'
        """
    )

    op.drop_table("mcp_auth_requests")
    op.drop_table("mcp_oauth2_tokens")


def downgrade() -> None:
    """Downgrade schema."""
    op.create_table(
        "mcp_oauth2_tokens",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("toolkit_id", sa.String(length=32), nullable=False),
        sa.Column("user_id", sa.String(length=32), nullable=False),
        sa.Column("encrypted_access_token", sa.Text(), nullable=False),
        sa.Column("encrypted_refresh_token", sa.Text(), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("token_type", sa.String(length=50), nullable=False),
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
        sa.ForeignKeyConstraint(
            ["toolkit_id"], ["toolkit_configs.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "toolkit_id", "user_id", name="uq_mcp_oauth2_tokens_toolkit_user"
        ),
    )
    op.create_index(
        "ix_mcp_oauth2_tokens_toolkit_id",
        "mcp_oauth2_tokens",
        ["toolkit_id"],
        unique=False,
    )

    op.create_table(
        "mcp_auth_requests",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("toolkit_id", sa.String(length=32), nullable=False),
        sa.Column("user_id", sa.String(length=32), nullable=False),
        sa.Column("muted", sa.Boolean(), nullable=False),
        sa.Column("last_requested_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_run_id", sa.String(length=64), nullable=True),
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
        sa.ForeignKeyConstraint(
            ["toolkit_id"], ["toolkit_configs.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "toolkit_id", "user_id", name="uq_mcp_auth_requests_toolkit_user"
        ),
    )
    op.create_index(
        "ix_mcp_auth_requests_toolkit_id",
        "mcp_auth_requests",
        ["toolkit_id"],
        unique=False,
    )

    op.drop_index(
        "ix_mcp_oauth_connections_toolkit_id",
        table_name="mcp_oauth_connections",
    )
    op.drop_table("mcp_oauth_connections")
    postgresql.ENUM(name="mcp_oauth_connection_status").drop(
        op.get_bind(), checkfirst=True
    )
