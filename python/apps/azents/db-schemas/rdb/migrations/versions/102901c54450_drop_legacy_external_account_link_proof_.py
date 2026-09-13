"""Drop legacy external account link proof tables.

Revision ID: 102901c54450
Revises: e905bfe74372
Create Date: 2026-09-13
"""

from typing import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "102901c54450"
down_revision: str | Sequence[str] | None = "e905bfe74372"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Remove the superseded browser-code proof persistence."""
    op.drop_table("external_account_link_candidates")
    op.drop_table("external_account_link_origins")


def downgrade() -> None:
    """Restore the legacy proof tables for application rollback."""
    op.create_table(
        "external_account_link_origins",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("workspace_id", sa.String(length=32), nullable=False),
        sa.Column("connection_id", sa.String(length=32), nullable=False),
        sa.Column("connection_configuration_generation", sa.Integer(), nullable=False),
        sa.Column("principal_id", sa.String(length=32), nullable=False),
        sa.Column(
            "provider",
            postgresql.ENUM(
                "slack", "discord", name="external_channel_provider", create_type=False
            ),
            nullable=False,
        ),
        sa.Column("identity_scope", sa.String(length=255), nullable=False),
        sa.Column("provider_tenant_id", sa.String(length=255), nullable=False),
        sa.Column(
            "provider_tenant_display_label", sa.String(length=255), nullable=False
        ),
        sa.Column("provider_user_id", sa.String(length=255), nullable=False),
        sa.Column("provider_display_label", sa.String(length=255), nullable=False),
        sa.Column("provider_interaction_id", sa.String(length=255), nullable=False),
        sa.Column("provider_channel_id", sa.String(length=255), nullable=False),
        sa.Column("provider_thread_id", sa.String(length=255), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("candidate_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column(
            "invalid_code_count", sa.Integer(), server_default="0", nullable=False
        ),
        sa.Column("cancelled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("consumed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "candidate_count >= 0 AND candidate_count <= 5 "
            "AND invalid_code_count >= 0 AND invalid_code_count <= 5",
            name="ck_external_account_link_origins_counts_bounded",
        ),
        sa.ForeignKeyConstraint(
            ["connection_id"], ["external_channel_connections.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["principal_id"], ["external_channel_principals.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id"], ["workspaces.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "connection_id",
            "provider_interaction_id",
            name="uq_external_account_link_origins_connection_interaction",
        ),
    )
    op.create_index(
        "ix_external_account_link_origins_expires_at",
        "external_account_link_origins",
        ["expires_at"],
        unique=False,
    )
    op.create_index(
        "ix_external_account_link_origins_workspace_id",
        "external_account_link_origins",
        ["workspace_id"],
        unique=False,
    )
    op.create_table(
        "external_account_link_candidates",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("origin_id", sa.String(length=32), nullable=False),
        sa.Column("user_id", sa.String(length=32), nullable=False),
        sa.Column("auth_session_id", sa.String(length=32), nullable=False),
        sa.Column("code_hash", sa.String(length=64), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("provider_proved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("cancelled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("consumed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("link_id", sa.String(length=32), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["auth_session_id"], ["sessions.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["link_id"], ["external_account_links.id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(
            ["origin_id"], ["external_account_link_origins.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "code_hash", name="uq_external_account_link_candidates_code_hash"
        ),
    )
    op.create_index(
        "ix_external_account_link_candidates_expires_at",
        "external_account_link_candidates",
        ["expires_at"],
        unique=False,
    )
    op.create_index(
        "ix_external_account_link_candidates_origin_id",
        "external_account_link_candidates",
        ["origin_id"],
        unique=False,
    )
    op.create_index(
        "ix_external_account_link_candidates_user_id",
        "external_account_link_candidates",
        ["user_id"],
        unique=False,
    )
