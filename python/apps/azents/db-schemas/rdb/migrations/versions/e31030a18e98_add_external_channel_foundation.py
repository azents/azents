"""add external channel foundation

Revision ID: e31030a18e98
Revises: 3ce0185dd474
Create Date: 2026-07-21 23:12:47.036006

"""

from typing import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

from azents.rdb.types.datetime import TimeZoneDateTime

# revision identifiers, used by Alembic.
revision: str = "e31030a18e98"
down_revision: str | Sequence[str] | None = "3ce0185dd474"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    sa.Enum(
        "pending",
        "attempting",
        "delivered",
        "failed",
        "unknown",
        "not_attempted",
        name="external_channel_delivery_status",
    ).create(op.get_bind())
    sa.Enum(
        "reply",
        "progress_create",
        "progress_update",
        "progress_delete",
        "control_message",
        name="external_channel_delivery_operation",
    ).create(op.get_bind())
    sa.Enum(
        "channel_action",
        "access_request",
        "binding_disconnect",
        "connection_disconnect",
        "manager_operation",
        name="external_channel_delivery_origin_type",
    ).create(op.get_bind())
    sa.Enum("finish", "continue", name="external_channel_action_mode").create(
        op.get_bind()
    )
    sa.Enum("active", "finished", name="external_channel_work_status").create(
        op.get_bind()
    )
    sa.Enum("session", "agent", name="external_channel_access_grant_scope").create(
        op.get_bind()
    )
    sa.Enum(
        "pending",
        "allowed",
        "denied",
        "blocked",
        "expired",
        name="external_channel_access_request_status",
    ).create(op.get_bind())
    sa.Enum("active", "disconnected", name="external_channel_binding_status").create(
        op.get_bind()
    )
    sa.Enum(
        "original", "edit", "delete", name="external_channel_message_revision_kind"
    ).create(op.get_bind())
    sa.Enum(
        "current", "edited", "deleted", name="external_channel_message_lifecycle"
    ).create(op.get_bind())
    sa.Enum(
        "human", "bot", "app", "system", name="external_channel_principal_author_type"
    ).create(op.get_bind())
    sa.Enum(
        "accepted",
        "ignored_unlinked",
        "processing",
        "processed",
        "failed",
        name="external_channel_event_status",
    ).create(op.get_bind())
    sa.Enum(
        "unclassified",
        "tracked",
        "ignored",
        "processed",
        name="external_channel_event_eligibility_state",
    ).create(op.get_bind())
    sa.Enum(
        "active", "unavailable", "deleted", name="external_channel_resource_status"
    ).create(op.get_bind())
    sa.Enum("thread", name="external_channel_resource_type").create(op.get_bind())
    sa.Enum("dedicated", "platform", name="external_channel_route_mode").create(
        op.get_bind()
    )
    sa.Enum("active", "inactive", name="external_channel_route_status").create(
        op.get_bind()
    )
    sa.Enum(
        "configuring",
        "active",
        "degraded",
        "reconnect_required",
        "disconnecting",
        "disconnected",
        name="external_channel_connection_status",
    ).create(op.get_bind())
    sa.Enum("http", "socket", name="external_channel_transport").create(op.get_bind())
    sa.Enum("slack", name="external_channel_provider").create(op.get_bind())
    op.create_table(
        "external_channel_principals",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column(
            "provider",
            postgresql.ENUM(
                "slack", name="external_channel_provider", create_type=False
            ),
            nullable=False,
        ),
        sa.Column("provider_tenant_id", sa.String(length=255), nullable=False),
        sa.Column("provider_user_id", sa.String(length=255), nullable=False),
        sa.Column(
            "author_type",
            postgresql.ENUM(
                "human",
                "bot",
                "app",
                "system",
                name="external_channel_principal_author_type",
                create_type=False,
            ),
            nullable=False,
        ),
        sa.Column("display_name", sa.String(length=255), nullable=True),
        sa.Column("avatar_url", sa.Text(), nullable=True),
        sa.Column("profile", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column(
            "first_observed_at",
            TimeZoneDateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "last_observed_at",
            TimeZoneDateTime(timezone=True),
            server_default=sa.text("now()"),
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
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "provider",
            "provider_tenant_id",
            "provider_user_id",
            name="uq_external_channel_principals_provider_tenant_user",
        ),
    )
    op.create_table(
        "external_channel_connections",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("workspace_id", sa.String(length=32), nullable=False),
        sa.Column(
            "provider",
            postgresql.ENUM(
                "slack", name="external_channel_provider", create_type=False
            ),
            nullable=False,
        ),
        sa.Column(
            "transport",
            postgresql.ENUM(
                "http", "socket", name="external_channel_transport", create_type=False
            ),
            nullable=False,
        ),
        sa.Column(
            "status",
            postgresql.ENUM(
                "configuring",
                "active",
                "degraded",
                "reconnect_required",
                "disconnecting",
                "disconnected",
                name="external_channel_connection_status",
                create_type=False,
            ),
            server_default="configuring",
            nullable=False,
        ),
        sa.Column("provider_app_id", sa.String(length=255), nullable=True),
        sa.Column("provider_tenant_id", sa.String(length=255), nullable=True),
        sa.Column("provider_bot_user_id", sa.String(length=255), nullable=True),
        sa.Column("http_callback_selector_hash", sa.String(length=128), nullable=True),
        sa.Column("encrypted_credentials", sa.Text(), nullable=True),
        sa.Column(
            "capabilities", postgresql.JSONB(astext_type=sa.Text()), nullable=True
        ),
        sa.Column(
            "provider_config", postgresql.JSONB(astext_type=sa.Text()), nullable=True
        ),
        sa.Column(
            "last_verified_at",
            TimeZoneDateTime(timezone=True),
            nullable=True,
        ),
        sa.Column(
            "last_health_at",
            TimeZoneDateTime(timezone=True),
            nullable=True,
        ),
        sa.Column(
            "disconnected_at",
            TimeZoneDateTime(timezone=True),
            nullable=True,
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
        sa.ForeignKeyConstraint(
            ["workspace_id"], ["workspaces.id"], ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_external_channel_connections_status",
        "external_channel_connections",
        ["status"],
        unique=False,
    )
    op.create_index(
        "ix_external_channel_connections_workspace_id",
        "external_channel_connections",
        ["workspace_id"],
        unique=False,
    )
    op.create_index(
        "uq_external_channel_connections_http_callback_selector_hash",
        "external_channel_connections",
        ["http_callback_selector_hash"],
        unique=True,
        postgresql_where=sa.text("http_callback_selector_hash IS NOT NULL"),
    )
    op.create_index(
        "uq_external_channel_connections_installation_identity",
        "external_channel_connections",
        ["workspace_id", "provider", "provider_tenant_id", "provider_app_id"],
        unique=True,
        postgresql_where=sa.text(
            "provider_tenant_id IS NOT NULL AND provider_app_id IS NOT NULL"
        ),
    )
    op.create_table(
        "external_channel_agent_routes",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("connection_id", sa.String(length=32), nullable=False),
        sa.Column("agent_id", sa.String(length=32), nullable=False),
        sa.Column(
            "status",
            postgresql.ENUM(
                "active",
                "inactive",
                name="external_channel_route_status",
                create_type=False,
            ),
            server_default="active",
            nullable=False,
        ),
        sa.Column(
            "route_mode",
            postgresql.ENUM(
                "dedicated",
                "platform",
                name="external_channel_route_mode",
                create_type=False,
            ),
            server_default="dedicated",
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
        sa.Column(
            "deactivated_at",
            TimeZoneDateTime(timezone=True),
            nullable=True,
        ),
        sa.ForeignKeyConstraint(["agent_id"], ["agents.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(
            ["connection_id"], ["external_channel_connections.id"], ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_external_channel_agent_routes_agent_id_status",
        "external_channel_agent_routes",
        ["agent_id", "status"],
        unique=False,
    )
    op.create_index(
        "ix_external_channel_agent_routes_connection_id",
        "external_channel_agent_routes",
        ["connection_id"],
        unique=False,
    )
    op.create_index(
        "uq_external_channel_agent_routes_active_dedicated_connection",
        "external_channel_agent_routes",
        ["connection_id"],
        unique=True,
        postgresql_where=sa.text("status = 'active' AND route_mode = 'dedicated'"),
    )
    op.create_table(
        "external_channel_blocks",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("agent_id", sa.String(length=32), nullable=False),
        sa.Column("principal_id", sa.String(length=32), nullable=False),
        sa.Column("blocked_by_user_id", sa.String(length=32), nullable=False),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("removed_by_user_id", sa.String(length=32), nullable=True),
        sa.Column(
            "removed_at",
            TimeZoneDateTime(timezone=True),
            nullable=True,
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
        sa.ForeignKeyConstraint(["agent_id"], ["agents.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(
            ["blocked_by_user_id"], ["users.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["principal_id"], ["external_channel_principals.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["removed_by_user_id"], ["users.id"], ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "agent_id",
            "principal_id",
            name="uq_external_channel_blocks_agent_principal",
        ),
    )
    op.create_table(
        "external_channel_events",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("connection_id", sa.String(length=32), nullable=False),
        sa.Column("provider_event_id", sa.String(length=255), nullable=False),
        sa.Column("event_type", sa.String(length=120), nullable=False),
        sa.Column("envelope", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column(
            "eligibility_state",
            postgresql.ENUM(
                "unclassified",
                "tracked",
                "ignored",
                "processed",
                name="external_channel_event_eligibility_state",
                create_type=False,
            ),
            server_default="unclassified",
            nullable=False,
        ),
        sa.Column(
            "status",
            postgresql.ENUM(
                "accepted",
                "ignored_unlinked",
                "processing",
                "processed",
                "failed",
                name="external_channel_event_status",
                create_type=False,
            ),
            server_default="accepted",
            nullable=False,
        ),
        sa.Column("transport_envelope_id", sa.String(length=255), nullable=True),
        sa.Column("provider_app_id", sa.String(length=255), nullable=True),
        sa.Column("provider_tenant_id", sa.String(length=255), nullable=True),
        sa.Column("provider_enterprise_id", sa.String(length=255), nullable=True),
        sa.Column("resource_correlation_key", sa.Text(), nullable=True),
        sa.Column("attempt_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("claim_owner", sa.String(length=120), nullable=True),
        sa.Column(
            "claim_until",
            TimeZoneDateTime(timezone=True),
            nullable=True,
        ),
        sa.Column("error_kind", sa.String(length=120), nullable=True),
        sa.Column("error_summary", sa.Text(), nullable=True),
        sa.Column(
            "provider_occurred_at",
            TimeZoneDateTime(timezone=True),
            nullable=True,
        ),
        sa.Column(
            "received_at",
            TimeZoneDateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "processing_started_at",
            TimeZoneDateTime(timezone=True),
            nullable=True,
        ),
        sa.Column(
            "processed_at",
            TimeZoneDateTime(timezone=True),
            nullable=True,
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
        sa.ForeignKeyConstraint(
            ["connection_id"], ["external_channel_connections.id"], ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "connection_id",
            "provider_event_id",
            name="uq_external_channel_events_connection_provider_event",
        ),
    )
    op.create_index(
        "ix_external_channel_events_connection_id_provider_timestamp",
        "external_channel_events",
        ["connection_id", "provider_occurred_at"],
        unique=False,
    )
    op.create_index(
        "ix_external_channel_events_status_received_at",
        "external_channel_events",
        ["status", "received_at"],
        unique=False,
    )
    op.create_table(
        "external_channel_resources",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("connection_id", sa.String(length=32), nullable=False),
        sa.Column(
            "resource_type",
            postgresql.ENUM(
                "thread", name="external_channel_resource_type", create_type=False
            ),
            nullable=False,
        ),
        sa.Column("provider_resource_key", sa.Text(), nullable=False),
        sa.Column(
            "status",
            postgresql.ENUM(
                "active",
                "unavailable",
                "deleted",
                name="external_channel_resource_status",
                create_type=False,
            ),
            server_default="active",
            nullable=False,
        ),
        sa.Column("labels", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column(
            "discovered_at",
            TimeZoneDateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "latest_activity_at",
            TimeZoneDateTime(timezone=True),
            nullable=True,
        ),
        sa.Column(
            "unavailable_at",
            TimeZoneDateTime(timezone=True),
            nullable=True,
        ),
        sa.Column(
            "deleted_at",
            TimeZoneDateTime(timezone=True),
            nullable=True,
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
        sa.ForeignKeyConstraint(
            ["connection_id"], ["external_channel_connections.id"], ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "connection_id",
            "resource_type",
            "provider_resource_key",
            name="uq_external_channel_resources_connection_type_provider_key",
        ),
    )
    op.create_index(
        "ix_external_channel_resources_connection_id_status",
        "external_channel_resources",
        ["connection_id", "status"],
        unique=False,
    )
    op.create_index(
        "ix_external_channel_resources_latest_activity_at",
        "external_channel_resources",
        ["latest_activity_at"],
        unique=False,
    )
    op.create_table(
        "external_channel_bindings",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("resource_id", sa.String(length=32), nullable=False),
        sa.Column("route_id", sa.String(length=32), nullable=False),
        sa.Column("agent_session_id", sa.String(length=32), nullable=False),
        sa.Column(
            "status",
            postgresql.ENUM(
                "active",
                "disconnected",
                name="external_channel_binding_status",
                create_type=False,
            ),
            server_default="active",
            nullable=False,
        ),
        sa.Column("projected_through_position", sa.String(length=255), nullable=True),
        sa.Column(
            "truncated_message_count", sa.Integer(), server_default="0", nullable=False
        ),
        sa.Column("truncated_size", sa.Integer(), server_default="0", nullable=False),
        sa.Column(
            "connected_at",
            TimeZoneDateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "disconnected_at",
            TimeZoneDateTime(timezone=True),
            nullable=True,
        ),
        sa.Column("disconnect_reason", sa.String(length=120), nullable=True),
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
        sa.ForeignKeyConstraint(
            ["agent_session_id"], ["agent_sessions.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["resource_id"], ["external_channel_resources.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["route_id"], ["external_channel_agent_routes.id"], ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_external_channel_bindings_agent_session_id_status",
        "external_channel_bindings",
        ["agent_session_id", "status"],
        unique=False,
    )
    op.create_index(
        "ix_external_channel_bindings_route_id_status",
        "external_channel_bindings",
        ["route_id", "status"],
        unique=False,
    )
    op.create_index(
        "uq_external_channel_bindings_active_resource_route",
        "external_channel_bindings",
        ["resource_id", "route_id"],
        unique=True,
        postgresql_where=sa.text("status = 'active'"),
    )
    op.create_table(
        "external_channel_messages",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("resource_id", sa.String(length=32), nullable=False),
        sa.Column("provider_message_key", sa.Text(), nullable=False),
        sa.Column("provider_position", sa.String(length=255), nullable=False),
        sa.Column(
            "lifecycle",
            postgresql.ENUM(
                "current",
                "edited",
                "deleted",
                name="external_channel_message_lifecycle",
                create_type=False,
            ),
            server_default="current",
            nullable=False,
        ),
        sa.Column(
            "author_type",
            postgresql.ENUM(
                "human",
                "bot",
                "app",
                "system",
                name="external_channel_principal_author_type",
                create_type=False,
            ),
            nullable=False,
        ),
        sa.Column("principal_id", sa.String(length=32), nullable=True),
        sa.Column("current_revision_id", sa.String(length=32), nullable=True),
        sa.Column("original_url", sa.Text(), nullable=True),
        sa.Column("pending_size", sa.Integer(), server_default="0", nullable=False),
        sa.Column(
            "provider_created_at",
            TimeZoneDateTime(timezone=True),
            nullable=True,
        ),
        sa.Column(
            "provider_updated_at",
            TimeZoneDateTime(timezone=True),
            nullable=True,
        ),
        sa.Column(
            "observed_at",
            TimeZoneDateTime(timezone=True),
            server_default=sa.text("now()"),
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
        sa.ForeignKeyConstraint(
            ["principal_id"], ["external_channel_principals.id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(
            ["resource_id"], ["external_channel_resources.id"], ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "resource_id",
            "provider_message_key",
            name="uq_external_channel_messages_resource_provider_message",
        ),
    )
    op.create_index(
        "ix_external_channel_messages_principal_id",
        "external_channel_messages",
        ["principal_id"],
        unique=False,
    )
    op.create_index(
        "ix_external_channel_messages_resource_id_provider_position",
        "external_channel_messages",
        ["resource_id", "provider_position"],
        unique=False,
    )
    op.create_table(
        "external_channel_access_requests",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("route_id", sa.String(length=32), nullable=False),
        sa.Column("resource_id", sa.String(length=32), nullable=False),
        sa.Column("source_message_id", sa.String(length=32), nullable=False),
        sa.Column("principal_id", sa.String(length=32), nullable=False),
        sa.Column(
            "status",
            postgresql.ENUM(
                "pending",
                "allowed",
                "denied",
                "blocked",
                "expired",
                name="external_channel_access_request_status",
                create_type=False,
            ),
            server_default="pending",
            nullable=False,
        ),
        sa.Column(
            "decision_policy_snapshot",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
        ),
        sa.Column(
            "expires_at",
            TimeZoneDateTime(timezone=True),
            nullable=False,
        ),
        sa.Column("agent_session_id", sa.String(length=32), nullable=True),
        sa.Column("decided_by_user_id", sa.String(length=32), nullable=True),
        sa.Column("decision_summary", sa.Text(), nullable=True),
        sa.Column(
            "decided_at",
            TimeZoneDateTime(timezone=True),
            nullable=True,
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
        sa.ForeignKeyConstraint(
            ["agent_session_id"], ["agent_sessions.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["decided_by_user_id"], ["users.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["principal_id"], ["external_channel_principals.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["resource_id"], ["external_channel_resources.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["route_id"], ["external_channel_agent_routes.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["source_message_id"], ["external_channel_messages.id"], ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "route_id",
            "source_message_id",
            name="uq_external_channel_access_requests_route_source_message",
        ),
    )
    op.create_index(
        "ix_external_channel_access_requests_agent_session_id",
        "external_channel_access_requests",
        ["agent_session_id"],
        unique=False,
    )
    op.create_index(
        "ix_external_channel_access_requests_status_created_at",
        "external_channel_access_requests",
        ["status", "created_at"],
        unique=False,
    )
    op.create_table(
        "external_channel_invocation_batches",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("binding_id", sa.String(length=32), nullable=False),
        sa.Column("trigger_message_id", sa.String(length=32), nullable=False),
        sa.Column("first_provider_position", sa.String(length=255), nullable=False),
        sa.Column("last_provider_position", sa.String(length=255), nullable=False),
        sa.Column(
            "truncation_message_count", sa.Integer(), server_default="0", nullable=False
        ),
        sa.Column("truncation_size", sa.Integer(), server_default="0", nullable=False),
        sa.Column("input_buffer_id", sa.String(length=32), nullable=True),
        sa.Column(
            "created_at",
            TimeZoneDateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["binding_id"], ["external_channel_bindings.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["input_buffer_id"], ["input_buffers.id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(
            ["trigger_message_id"],
            ["external_channel_messages.id"],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "binding_id",
            "trigger_message_id",
            name="uq_external_channel_invocation_batches_binding_trigger_message",
        ),
    )
    op.create_index(
        "ix_external_channel_invocation_batches_binding_id_created_at",
        "external_channel_invocation_batches",
        ["binding_id", "created_at"],
        unique=False,
    )
    op.create_table(
        "external_channel_message_revisions",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("message_id", sa.String(length=32), nullable=False),
        sa.Column("revision_key", sa.String(length=255), nullable=False),
        sa.Column(
            "revision_kind",
            postgresql.ENUM(
                "original",
                "edit",
                "delete",
                name="external_channel_message_revision_kind",
                create_type=False,
            ),
            nullable=False,
        ),
        sa.Column("normalized_body", sa.Text(), nullable=True),
        sa.Column(
            "attachment_metadata",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
        sa.Column("source_event_id", sa.String(length=32), nullable=True),
        sa.Column(
            "provider_occurred_at",
            TimeZoneDateTime(timezone=True),
            nullable=True,
        ),
        sa.Column(
            "observed_at",
            TimeZoneDateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            TimeZoneDateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["message_id"], ["external_channel_messages.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["source_event_id"], ["external_channel_events.id"], ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "message_id",
            "revision_key",
            name="uq_external_channel_message_revisions_message_revision_key",
        ),
        sa.UniqueConstraint(
            "message_id",
            "id",
            name="uq_external_channel_message_revisions_message_id_id",
        ),
    )
    op.create_index(
        "ix_external_channel_message_revisions_source_event_id",
        "external_channel_message_revisions",
        ["source_event_id"],
        unique=False,
    )
    op.create_foreign_key(
        "fk_external_channel_messages_current_revision",
        "external_channel_messages",
        "external_channel_message_revisions",
        ["id", "current_revision_id"],
        ["message_id", "id"],
        deferrable=True,
        initially="DEFERRED",
    )
    op.create_table(
        "external_channel_works",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("binding_id", sa.String(length=32), nullable=False),
        sa.Column(
            "status",
            postgresql.ENUM(
                "active",
                "finished",
                name="external_channel_work_status",
                create_type=False,
            ),
            server_default="active",
            nullable=False,
        ),
        sa.Column("schema_version", sa.Integer(), server_default="1", nullable=False),
        sa.Column("tasks", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("state_revision", sa.Integer(), server_default="1", nullable=False),
        sa.Column(
            "desired_progress_revision",
            sa.Integer(),
            server_default="0",
            nullable=False,
        ),
        sa.Column(
            "desired_progress_payload",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
        sa.Column(
            "progress_provider_message_key", sa.String(length=255), nullable=True
        ),
        sa.Column(
            "finished_at",
            TimeZoneDateTime(timezone=True),
            nullable=True,
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
        sa.ForeignKeyConstraint(
            ["binding_id"], ["external_channel_bindings.id"], ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_external_channel_works_binding_id_status",
        "external_channel_works",
        ["binding_id", "status"],
        unique=False,
    )
    op.create_index(
        "uq_external_channel_works_active_binding",
        "external_channel_works",
        ["binding_id"],
        unique=True,
        postgresql_where=sa.text("status = 'active'"),
    )
    op.create_table(
        "external_channel_access_grants",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("agent_id", sa.String(length=32), nullable=False),
        sa.Column("principal_id", sa.String(length=32), nullable=False),
        sa.Column(
            "scope",
            postgresql.ENUM(
                "session",
                "agent",
                name="external_channel_access_grant_scope",
                create_type=False,
            ),
            nullable=False,
        ),
        sa.Column("granted_by_user_id", sa.String(length=32), nullable=False),
        sa.Column("agent_session_id", sa.String(length=32), nullable=True),
        sa.Column("source_access_request_id", sa.String(length=32), nullable=True),
        sa.Column("revoked_by_user_id", sa.String(length=32), nullable=True),
        sa.Column(
            "revoked_at",
            TimeZoneDateTime(timezone=True),
            nullable=True,
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
        sa.CheckConstraint(
            "(scope = 'agent' AND agent_session_id IS NULL) OR "
            "(scope = 'session' AND agent_session_id IS NOT NULL)",
            name="ck_external_channel_access_grants_scope_session",
        ),
        sa.ForeignKeyConstraint(["agent_id"], ["agents.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(
            ["agent_session_id"], ["agent_sessions.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["granted_by_user_id"], ["users.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["principal_id"], ["external_channel_principals.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["revoked_by_user_id"], ["users.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["source_access_request_id"],
            ["external_channel_access_requests.id"],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_external_channel_access_grants_agent_id",
        "external_channel_access_grants",
        ["agent_id"],
        unique=False,
    )
    op.create_index(
        "ix_external_channel_access_grants_agent_session_id",
        "external_channel_access_grants",
        ["agent_session_id"],
        unique=False,
    )
    op.create_index(
        "uq_external_channel_access_grants_active_agent",
        "external_channel_access_grants",
        ["agent_id", "principal_id"],
        unique=True,
        postgresql_where=sa.text("scope = 'agent' AND revoked_at IS NULL"),
    )
    op.create_index(
        "uq_external_channel_access_grants_active_session",
        "external_channel_access_grants",
        ["agent_session_id", "principal_id"],
        unique=True,
        postgresql_where=sa.text("scope = 'session' AND revoked_at IS NULL"),
    )
    op.create_table(
        "external_channel_actions",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("agent_session_id", sa.String(length=32), nullable=False),
        sa.Column("client_tool_call_id", sa.Text(), nullable=False),
        sa.Column("binding_id", sa.String(length=32), nullable=False),
        sa.Column(
            "mode",
            postgresql.ENUM(
                "finish",
                "continue",
                name="external_channel_action_mode",
                create_type=False,
            ),
            nullable=False,
        ),
        sa.Column("state_revision", sa.Integer(), nullable=False),
        sa.Column(
            "request_payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False
        ),
        sa.Column("agent_run_id", sa.String(length=32), nullable=True),
        sa.Column("work_id", sa.String(length=32), nullable=True),
        sa.Column(
            "accepted_at",
            TimeZoneDateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "completed_at",
            TimeZoneDateTime(timezone=True),
            nullable=True,
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
        sa.ForeignKeyConstraint(
            ["agent_run_id"], ["agent_runs.id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(
            ["agent_session_id"], ["agent_sessions.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["binding_id"], ["external_channel_bindings.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["work_id"], ["external_channel_works.id"], ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "agent_session_id",
            "client_tool_call_id",
            name="uq_external_channel_actions_session_client_tool_call",
        ),
    )
    op.create_index(
        "ix_external_channel_actions_binding_id_created_at",
        "external_channel_actions",
        ["binding_id", "created_at"],
        unique=False,
    )
    op.create_table(
        "external_channel_invocation_batch_items",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("batch_id", sa.String(length=32), nullable=False),
        sa.Column("message_revision_id", sa.String(length=32), nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("provider_position", sa.String(length=255), nullable=False),
        sa.Column(
            "created_at",
            TimeZoneDateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["batch_id"], ["external_channel_invocation_batches.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["message_revision_id"],
            ["external_channel_message_revisions.id"],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "batch_id",
            "message_revision_id",
            name="uq_external_channel_invocation_batch_items_batch_revision",
        ),
        sa.UniqueConstraint(
            "batch_id",
            "sequence",
            name="uq_external_channel_invocation_batch_items_batch_sequence",
        ),
    )
    op.create_index(
        "ix_external_channel_invocation_batch_items_message_revision_id",
        "external_channel_invocation_batch_items",
        ["message_revision_id"],
        unique=False,
    )
    op.create_table(
        "external_channel_pending_contexts",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("resource_id", sa.String(length=32), nullable=False),
        sa.Column("message_revision_id", sa.String(length=32), nullable=False),
        sa.Column("provider_position", sa.String(length=255), nullable=False),
        sa.Column("normalized_size", sa.Integer(), nullable=False),
        sa.Column(
            "expires_at",
            TimeZoneDateTime(timezone=True),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            TimeZoneDateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["message_revision_id"],
            ["external_channel_message_revisions.id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["resource_id"], ["external_channel_resources.id"], ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "resource_id",
            "message_revision_id",
            name="uq_external_channel_pending_contexts_resource_message_revision",
        ),
    )
    op.create_index(
        "ix_external_channel_pending_contexts_expires_at",
        "external_channel_pending_contexts",
        ["expires_at"],
        unique=False,
    )
    op.create_index(
        "ix_external_channel_pending_ctx_resource_position",
        "external_channel_pending_contexts",
        ["resource_id", "provider_position"],
        unique=False,
    )
    op.create_table(
        "external_channel_delivery_attempts",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column(
            "origin_type",
            postgresql.ENUM(
                "channel_action",
                "access_request",
                "binding_disconnect",
                "connection_disconnect",
                "manager_operation",
                name="external_channel_delivery_origin_type",
                create_type=False,
            ),
            nullable=False,
        ),
        sa.Column("origin_id", sa.String(length=32), nullable=False),
        sa.Column(
            "operation",
            postgresql.ENUM(
                "reply",
                "progress_create",
                "progress_update",
                "progress_delete",
                "control_message",
                name="external_channel_delivery_operation",
                create_type=False,
            ),
            nullable=False,
        ),
        sa.Column(
            "request_payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False
        ),
        sa.Column(
            "status",
            postgresql.ENUM(
                "pending",
                "attempting",
                "delivered",
                "failed",
                "unknown",
                "not_attempted",
                name="external_channel_delivery_status",
                create_type=False,
            ),
            server_default="pending",
            nullable=False,
        ),
        sa.Column("channel_action_id", sa.String(length=32), nullable=True),
        sa.Column("binding_id", sa.String(length=32), nullable=True),
        sa.Column("provider_message_key", sa.String(length=255), nullable=True),
        sa.Column("error_kind", sa.String(length=120), nullable=True),
        sa.Column("error_summary", sa.Text(), nullable=True),
        sa.Column(
            "attempted_at",
            TimeZoneDateTime(timezone=True),
            nullable=True,
        ),
        sa.Column(
            "completed_at",
            TimeZoneDateTime(timezone=True),
            nullable=True,
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
        sa.ForeignKeyConstraint(
            ["binding_id"], ["external_channel_bindings.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["channel_action_id"], ["external_channel_actions.id"], ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_external_channel_delivery_attempts_binding_id_status",
        "external_channel_delivery_attempts",
        ["binding_id", "status"],
        unique=False,
    )
    op.create_index(
        "ix_external_channel_delivery_attempts_status_created_at",
        "external_channel_delivery_attempts",
        ["status", "created_at"],
        unique=False,
    )
    op.create_index(
        "uq_external_channel_delivery_attempts_operation_with_binding",
        "external_channel_delivery_attempts",
        ["origin_type", "origin_id", "binding_id", "operation"],
        unique=True,
        postgresql_where=sa.text("binding_id IS NOT NULL"),
    )
    op.create_index(
        "uq_external_channel_delivery_attempts_operation_without_binding",
        "external_channel_delivery_attempts",
        ["origin_type", "origin_id", "operation"],
        unique=True,
        postgresql_where=sa.text("binding_id IS NULL"),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(
        "uq_external_channel_delivery_attempts_operation_without_binding",
        table_name="external_channel_delivery_attempts",
        postgresql_where=sa.text("binding_id IS NULL"),
    )
    op.drop_index(
        "uq_external_channel_delivery_attempts_operation_with_binding",
        table_name="external_channel_delivery_attempts",
        postgresql_where=sa.text("binding_id IS NOT NULL"),
    )
    op.drop_index(
        "ix_external_channel_delivery_attempts_status_created_at",
        table_name="external_channel_delivery_attempts",
    )
    op.drop_index(
        "ix_external_channel_delivery_attempts_binding_id_status",
        table_name="external_channel_delivery_attempts",
    )
    op.drop_table("external_channel_delivery_attempts")
    op.drop_index(
        "ix_external_channel_pending_ctx_resource_position",
        table_name="external_channel_pending_contexts",
    )
    op.drop_index(
        "ix_external_channel_pending_contexts_expires_at",
        table_name="external_channel_pending_contexts",
    )
    op.drop_table("external_channel_pending_contexts")
    op.drop_index(
        "ix_external_channel_invocation_batch_items_message_revision_id",
        table_name="external_channel_invocation_batch_items",
    )
    op.drop_table("external_channel_invocation_batch_items")
    op.drop_index(
        "ix_external_channel_actions_binding_id_created_at",
        table_name="external_channel_actions",
    )
    op.drop_table("external_channel_actions")
    op.drop_index(
        "uq_external_channel_access_grants_active_session",
        table_name="external_channel_access_grants",
        postgresql_where=sa.text("scope = 'session' AND revoked_at IS NULL"),
    )
    op.drop_index(
        "uq_external_channel_access_grants_active_agent",
        table_name="external_channel_access_grants",
        postgresql_where=sa.text("scope = 'agent' AND revoked_at IS NULL"),
    )
    op.drop_index(
        "ix_external_channel_access_grants_agent_session_id",
        table_name="external_channel_access_grants",
    )
    op.drop_index(
        "ix_external_channel_access_grants_agent_id",
        table_name="external_channel_access_grants",
    )
    op.drop_table("external_channel_access_grants")
    op.drop_index(
        "uq_external_channel_works_active_binding",
        table_name="external_channel_works",
        postgresql_where=sa.text("status = 'active'"),
    )
    op.drop_index(
        "ix_external_channel_works_binding_id_status",
        table_name="external_channel_works",
    )
    op.drop_table("external_channel_works")
    op.drop_index(
        "ix_external_channel_message_revisions_source_event_id",
        table_name="external_channel_message_revisions",
    )
    op.drop_constraint(
        "fk_external_channel_messages_current_revision",
        "external_channel_messages",
        type_="foreignkey",
    )
    op.drop_table("external_channel_message_revisions")
    op.drop_index(
        "ix_external_channel_invocation_batches_binding_id_created_at",
        table_name="external_channel_invocation_batches",
    )
    op.drop_table("external_channel_invocation_batches")
    op.drop_index(
        "ix_external_channel_access_requests_status_created_at",
        table_name="external_channel_access_requests",
    )
    op.drop_index(
        "ix_external_channel_access_requests_agent_session_id",
        table_name="external_channel_access_requests",
    )
    op.drop_table("external_channel_access_requests")
    op.drop_index(
        "ix_external_channel_messages_resource_id_provider_position",
        table_name="external_channel_messages",
    )
    op.drop_index(
        "ix_external_channel_messages_principal_id",
        table_name="external_channel_messages",
    )
    op.drop_table("external_channel_messages")
    op.drop_index(
        "uq_external_channel_bindings_active_resource_route",
        table_name="external_channel_bindings",
        postgresql_where=sa.text("status = 'active'"),
    )
    op.drop_index(
        "ix_external_channel_bindings_route_id_status",
        table_name="external_channel_bindings",
    )
    op.drop_index(
        "ix_external_channel_bindings_agent_session_id_status",
        table_name="external_channel_bindings",
    )
    op.drop_table("external_channel_bindings")
    op.drop_index(
        "ix_external_channel_resources_latest_activity_at",
        table_name="external_channel_resources",
    )
    op.drop_index(
        "ix_external_channel_resources_connection_id_status",
        table_name="external_channel_resources",
    )
    op.drop_table("external_channel_resources")
    op.drop_index(
        "ix_external_channel_events_status_received_at",
        table_name="external_channel_events",
    )
    op.drop_index(
        "ix_external_channel_events_connection_id_provider_timestamp",
        table_name="external_channel_events",
    )
    op.drop_table("external_channel_events")
    op.drop_table("external_channel_blocks")
    op.drop_index(
        "uq_external_channel_agent_routes_active_dedicated_connection",
        table_name="external_channel_agent_routes",
        postgresql_where=sa.text("status = 'active' AND route_mode = 'dedicated'"),
    )
    op.drop_index(
        "ix_external_channel_agent_routes_connection_id",
        table_name="external_channel_agent_routes",
    )
    op.drop_index(
        "ix_external_channel_agent_routes_agent_id_status",
        table_name="external_channel_agent_routes",
    )
    op.drop_table("external_channel_agent_routes")
    op.drop_index(
        "uq_external_channel_connections_installation_identity",
        table_name="external_channel_connections",
        postgresql_where=sa.text(
            "provider_tenant_id IS NOT NULL AND provider_app_id IS NOT NULL"
        ),
    )
    op.drop_index(
        "uq_external_channel_connections_http_callback_selector_hash",
        table_name="external_channel_connections",
        postgresql_where=sa.text("http_callback_selector_hash IS NOT NULL"),
    )
    op.drop_index(
        "ix_external_channel_connections_workspace_id",
        table_name="external_channel_connections",
    )
    op.drop_index(
        "ix_external_channel_connections_status",
        table_name="external_channel_connections",
    )
    op.drop_table("external_channel_connections")
    op.drop_table("external_channel_principals")
    sa.Enum("slack", name="external_channel_provider").drop(op.get_bind())
    sa.Enum("http", "socket", name="external_channel_transport").drop(op.get_bind())
    sa.Enum(
        "configuring",
        "active",
        "degraded",
        "reconnect_required",
        "disconnecting",
        "disconnected",
        name="external_channel_connection_status",
    ).drop(op.get_bind())
    sa.Enum("active", "inactive", name="external_channel_route_status").drop(
        op.get_bind()
    )
    sa.Enum("dedicated", "platform", name="external_channel_route_mode").drop(
        op.get_bind()
    )
    sa.Enum("thread", name="external_channel_resource_type").drop(op.get_bind())
    sa.Enum(
        "active", "unavailable", "deleted", name="external_channel_resource_status"
    ).drop(op.get_bind())
    sa.Enum(
        "unclassified",
        "tracked",
        "ignored",
        "processed",
        name="external_channel_event_eligibility_state",
    ).drop(op.get_bind())
    sa.Enum(
        "accepted",
        "ignored_unlinked",
        "processing",
        "processed",
        "failed",
        name="external_channel_event_status",
    ).drop(op.get_bind())
    sa.Enum(
        "human", "bot", "app", "system", name="external_channel_principal_author_type"
    ).drop(op.get_bind())
    sa.Enum(
        "current", "edited", "deleted", name="external_channel_message_lifecycle"
    ).drop(op.get_bind())
    sa.Enum(
        "original", "edit", "delete", name="external_channel_message_revision_kind"
    ).drop(op.get_bind())
    sa.Enum("active", "disconnected", name="external_channel_binding_status").drop(
        op.get_bind()
    )
    sa.Enum(
        "pending",
        "allowed",
        "denied",
        "blocked",
        "expired",
        name="external_channel_access_request_status",
    ).drop(op.get_bind())
    sa.Enum("session", "agent", name="external_channel_access_grant_scope").drop(
        op.get_bind()
    )
    sa.Enum("active", "finished", name="external_channel_work_status").drop(
        op.get_bind()
    )
    sa.Enum("finish", "continue", name="external_channel_action_mode").drop(
        op.get_bind()
    )
    sa.Enum(
        "channel_action",
        "access_request",
        "binding_disconnect",
        "connection_disconnect",
        "manager_operation",
        name="external_channel_delivery_origin_type",
    ).drop(op.get_bind())
    sa.Enum(
        "reply",
        "progress_create",
        "progress_update",
        "progress_delete",
        "control_message",
        name="external_channel_delivery_operation",
    ).drop(op.get_bind())
    sa.Enum(
        "pending",
        "attempting",
        "delivered",
        "failed",
        "unknown",
        "not_attempted",
        name="external_channel_delivery_status",
    ).drop(op.get_bind())
