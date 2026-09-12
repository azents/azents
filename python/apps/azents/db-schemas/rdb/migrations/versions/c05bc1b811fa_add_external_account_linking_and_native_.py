"""Add optional external account links and generation-fenced native model settings."""

from typing import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "c05bc1b811fa"
down_revision: str | Sequence[str] | None = "dde8c8826107"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add only the external account feature schema."""
    postgresql.ENUM(
        "unknown", "delivered", "failed", name="external_model_notice_outcome"
    ).create(op.get_bind())
    op.create_table(
        "external_account_links",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("workspace_id", sa.String(length=32), nullable=False),
        sa.Column("user_id", sa.String(length=32), nullable=False),
        sa.Column(
            "provider",
            postgresql.ENUM(
                "slack", "discord", name="external_channel_provider", create_type=False
            ),
            nullable=False,
        ),
        sa.Column("identity_scope", sa.String(length=255), nullable=False),
        sa.Column("provider_user_id", sa.String(length=255), nullable=False),
        sa.Column(
            "provider_tenant_display_label", sa.String(length=255), nullable=False
        ),
        sa.Column("provider_display_label", sa.String(length=255), nullable=False),
        sa.Column(
            "linked_at",
            sa.DateTime(timezone=True),
            nullable=False,
        ),
        sa.Column(
            "revoked_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["workspace_id"], ["workspaces.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_external_account_links_user_id",
        "external_account_links",
        ["user_id"],
        unique=False,
    )
    op.create_index(
        "ix_external_account_links_workspace_id",
        "external_account_links",
        ["workspace_id"],
        unique=False,
    )
    op.create_index(
        "uq_external_account_links_active_external_identity",
        "external_account_links",
        ["workspace_id", "provider", "identity_scope", "provider_user_id"],
        unique=True,
        postgresql_where=sa.text("revoked_at IS NULL"),
    )
    op.create_index(
        "uq_external_account_links_active_user_provider_scope",
        "external_account_links",
        ["workspace_id", "user_id", "provider", "identity_scope"],
        unique=True,
        postgresql_where=sa.text("revoked_at IS NULL"),
    )
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
        sa.Column(
            "expires_at",
            sa.DateTime(timezone=True),
            nullable=False,
        ),
        sa.Column("candidate_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column(
            "invalid_code_count", sa.Integer(), server_default="0", nullable=False
        ),
        sa.Column(
            "cancelled_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
        sa.Column(
            "consumed_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
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
        sa.Column(
            "expires_at",
            sa.DateTime(timezone=True),
            nullable=False,
        ),
        sa.Column(
            "provider_proved_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
        sa.Column(
            "cancelled_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
        sa.Column(
            "consumed_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
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
    op.create_table(
        "external_model_drafts",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column(
            "provider",
            postgresql.ENUM(
                "slack", "discord", name="external_channel_provider", create_type=False
            ),
            nullable=False,
        ),
        sa.Column("connection_id", sa.String(length=32), nullable=False),
        sa.Column("principal_id", sa.String(length=32), nullable=False),
        sa.Column("link_id", sa.String(length=32), nullable=True),
        sa.Column("link_id_snapshot", sa.String(length=32), nullable=False),
        sa.Column("user_id", sa.String(length=32), nullable=True),
        sa.Column("user_id_snapshot", sa.String(length=32), nullable=False),
        sa.Column("binding_id", sa.String(length=32), nullable=False),
        sa.Column("session_id", sa.String(length=32), nullable=False),
        sa.Column("agent_id", sa.String(length=32), nullable=False),
        sa.Column("owner_interaction_key", sa.String(length=128), nullable=False),
        sa.Column("expected_generation", sa.BigInteger(), nullable=False),
        sa.Column(
            "options_snapshot", postgresql.JSONB(astext_type=sa.Text()), nullable=False
        ),
        sa.Column("selected_option_id", sa.String(length=64), nullable=False),
        sa.Column("selected_model_target_label", sa.String(length=80), nullable=False),
        sa.Column(
            "selected_reasoning_effort",
            postgresql.ENUM(
                "none",
                "minimal",
                "low",
                "medium",
                "high",
                "xhigh",
                "max",
                name="model_reasoning_effort",
                create_type=False,
            ),
            nullable=True,
        ),
        sa.Column(
            "selected_enabled_execution_options",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column("scope_label", sa.String(length=255), nullable=False),
        sa.Column(
            "expires_at",
            sa.DateTime(timezone=True),
            nullable=False,
        ),
        sa.Column(
            "cancelled_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
        sa.Column(
            "applied_at",
            sa.DateTime(timezone=True),
            nullable=True,
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
        sa.CheckConstraint(
            "expected_generation >= 0", name="ck_external_model_drafts_generation"
        ),
        sa.CheckConstraint(
            "num_nonnulls(cancelled_at, applied_at) <= 1",
            name="ck_external_model_drafts_terminal_times",
        ),
        sa.ForeignKeyConstraint(["agent_id"], ["agents.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(
            ["binding_id"], ["external_channel_bindings.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["connection_id"], ["external_channel_connections.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["link_id"], ["external_account_links.id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(
            ["principal_id"], ["external_channel_principals.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["session_id"], ["agent_sessions.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "connection_id",
            "owner_interaction_key",
            name="uq_external_model_drafts_connection_interaction",
        ),
    )
    op.create_index(
        "ix_external_model_drafts_expires_at",
        "external_model_drafts",
        ["expires_at"],
        unique=False,
    )
    op.create_index(
        "ix_external_model_drafts_session_id",
        "external_model_drafts",
        ["session_id"],
        unique=False,
    )
    op.create_table(
        "external_model_mutations",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column(
            "provider",
            postgresql.ENUM(
                "slack", "discord", name="external_channel_provider", create_type=False
            ),
            nullable=False,
        ),
        sa.Column("connection_id", sa.String(length=32), nullable=False),
        sa.Column("apply_interaction_key", sa.String(length=128), nullable=False),
        sa.Column("principal_id", sa.String(length=32), nullable=True),
        sa.Column("principal_id_snapshot", sa.String(length=32), nullable=False),
        sa.Column("provider_tenant_id_snapshot", sa.String(length=255), nullable=False),
        sa.Column("provider_user_id_snapshot", sa.String(length=255), nullable=False),
        sa.Column(
            "provider_tenant_display_label_snapshot",
            sa.String(length=255),
            nullable=False,
        ),
        sa.Column("actor_display_name_snapshot", sa.String(length=255), nullable=False),
        sa.Column("link_id", sa.String(length=32), nullable=True),
        sa.Column("link_id_snapshot", sa.String(length=32), nullable=False),
        sa.Column("user_id", sa.String(length=32), nullable=True),
        sa.Column("user_id_snapshot", sa.String(length=32), nullable=False),
        sa.Column("binding_id", sa.String(length=32), nullable=True),
        sa.Column("binding_id_snapshot", sa.String(length=32), nullable=False),
        sa.Column("session_id", sa.String(length=32), nullable=False),
        sa.Column("agent_id", sa.String(length=32), nullable=True),
        sa.Column("agent_id_snapshot", sa.String(length=32), nullable=False),
        sa.Column("old_model_target_label", sa.String(length=80), nullable=True),
        sa.Column(
            "old_reasoning_effort",
            postgresql.ENUM(
                "none",
                "minimal",
                "low",
                "medium",
                "high",
                "xhigh",
                "max",
                name="model_reasoning_effort",
                create_type=False,
            ),
            nullable=True,
        ),
        sa.Column(
            "old_enabled_execution_options",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column("new_model_target_label", sa.String(length=80), nullable=False),
        sa.Column("new_model_display_name", sa.String(length=255), nullable=False),
        sa.Column(
            "new_reasoning_effort",
            postgresql.ENUM(
                "none",
                "minimal",
                "low",
                "medium",
                "high",
                "xhigh",
                "max",
                name="model_reasoning_effort",
                create_type=False,
            ),
            nullable=True,
        ),
        sa.Column(
            "new_enabled_execution_options",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column("expected_generation", sa.BigInteger(), nullable=False),
        sa.Column("resulting_generation", sa.BigInteger(), nullable=False),
        sa.Column("provider_conversation_id", sa.Text(), nullable=False),
        sa.Column("provider_thread_id", sa.Text(), nullable=True),
        sa.Column(
            "notice_outcome",
            postgresql.ENUM(
                "unknown",
                "delivered",
                "failed",
                name="external_model_notice_outcome",
                create_type=False,
            ),
            server_default="unknown",
            nullable=False,
        ),
        sa.Column(
            "notice_attempted_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
        sa.Column("notice_error_summary", sa.String(length=255), nullable=True),
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
            "expected_generation >= 0 "
            "AND resulting_generation = expected_generation + 1",
            name="ck_external_model_mutations_generations",
        ),
        sa.ForeignKeyConstraint(["agent_id"], ["agents.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(
            ["binding_id"], ["external_channel_bindings.id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(
            ["connection_id"], ["external_channel_connections.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["link_id"], ["external_account_links.id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(
            ["principal_id"], ["external_channel_principals.id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(
            ["session_id"], ["agent_sessions.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "provider",
            "connection_id",
            "apply_interaction_key",
            name="uq_external_model_mutations_provider_connection_interaction",
        ),
    )
    op.create_index(
        "ix_external_model_mutations_link_id_snapshot",
        "external_model_mutations",
        ["link_id_snapshot"],
        unique=False,
    )
    op.create_index(
        "ix_external_model_mutations_session_id",
        "external_model_mutations",
        ["session_id"],
        unique=False,
    )
    op.add_column(
        "agent_sessions",
        sa.Column(
            "applied_profile_generation",
            sa.BigInteger(),
            server_default="0",
            nullable=False,
        ),
    )


def downgrade() -> None:
    """Remove only the external account feature schema."""
    op.drop_column("agent_sessions", "applied_profile_generation")
    op.drop_index(
        "ix_external_model_mutations_session_id", table_name="external_model_mutations"
    )
    op.drop_index(
        "ix_external_model_mutations_link_id_snapshot",
        table_name="external_model_mutations",
    )
    op.drop_table("external_model_mutations")
    op.drop_index(
        "ix_external_model_drafts_session_id", table_name="external_model_drafts"
    )
    op.drop_index(
        "ix_external_model_drafts_expires_at", table_name="external_model_drafts"
    )
    op.drop_table("external_model_drafts")
    op.drop_index(
        "ix_external_account_link_candidates_user_id",
        table_name="external_account_link_candidates",
    )
    op.drop_index(
        "ix_external_account_link_candidates_origin_id",
        table_name="external_account_link_candidates",
    )
    op.drop_index(
        "ix_external_account_link_candidates_expires_at",
        table_name="external_account_link_candidates",
    )
    op.drop_table("external_account_link_candidates")
    op.drop_index(
        "ix_external_account_link_origins_workspace_id",
        table_name="external_account_link_origins",
    )
    op.drop_index(
        "ix_external_account_link_origins_expires_at",
        table_name="external_account_link_origins",
    )
    op.drop_table("external_account_link_origins")
    op.drop_index(
        "uq_external_account_links_active_user_provider_scope",
        table_name="external_account_links",
        postgresql_where=sa.text("revoked_at IS NULL"),
    )
    op.drop_index(
        "uq_external_account_links_active_external_identity",
        table_name="external_account_links",
        postgresql_where=sa.text("revoked_at IS NULL"),
    )
    op.drop_index(
        "ix_external_account_links_workspace_id", table_name="external_account_links"
    )
    op.drop_index(
        "ix_external_account_links_user_id", table_name="external_account_links"
    )
    op.drop_table("external_account_links")
    postgresql.ENUM(
        "unknown", "delivered", "failed", name="external_model_notice_outcome"
    ).drop(op.get_bind())
