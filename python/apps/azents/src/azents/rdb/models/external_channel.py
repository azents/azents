"""External Channel persistence models."""

import datetime
import enum
from typing import Any

import sqlalchemy as sa
from azcommon.uuid import uuid7
from sqlalchemy.dialects.postgresql import ENUM, JSONB
from sqlalchemy.orm import Mapped, mapped_column

from azents.core.enums import (
    ExternalChannelAccessGrantScope,
    ExternalChannelAccessRequestStatus,
    ExternalChannelActionMode,
    ExternalChannelBindingActivationStatus,
    ExternalChannelBindingStatus,
    ExternalChannelConnectionStatus,
    ExternalChannelDeliveryOperation,
    ExternalChannelDeliveryOriginType,
    ExternalChannelDeliveryStatus,
    ExternalChannelEventEligibilityState,
    ExternalChannelEventStatus,
    ExternalChannelHydrationStatus,
    ExternalChannelMessageLifecycle,
    ExternalChannelMessageRevisionKind,
    ExternalChannelPrincipalAuthorType,
    ExternalChannelProvider,
    ExternalChannelResourceStatus,
    ExternalChannelResourceType,
    ExternalChannelRouteMode,
    ExternalChannelTransport,
    ExternalChannelWorkStatus,
)
from azents.rdb.models.base import RDBModel
from azents.rdb.types.datetime import TimeZoneDateTime


def _enum_values(enum_cls: type[enum.StrEnum]) -> list[str]:
    """Return StrEnum values stored in the DB."""
    return [value.value for value in enum_cls]


external_channel_provider_enum = ENUM(
    ExternalChannelProvider,
    name="external_channel_provider",
    create_type=False,
    values_callable=_enum_values,
)
external_channel_transport_enum = ENUM(
    ExternalChannelTransport,
    name="external_channel_transport",
    create_type=False,
    values_callable=_enum_values,
)
external_channel_connection_status_enum = ENUM(
    ExternalChannelConnectionStatus,
    name="external_channel_connection_status",
    create_type=False,
    values_callable=_enum_values,
)
external_channel_route_mode_enum = ENUM(
    ExternalChannelRouteMode,
    name="external_channel_route_mode",
    create_type=False,
    values_callable=_enum_values,
)
external_channel_resource_type_enum = ENUM(
    ExternalChannelResourceType,
    name="external_channel_resource_type",
    create_type=False,
    values_callable=_enum_values,
)
external_channel_resource_status_enum = ENUM(
    ExternalChannelResourceStatus,
    name="external_channel_resource_status",
    create_type=False,
    values_callable=_enum_values,
)
external_channel_hydration_status_enum = ENUM(
    ExternalChannelHydrationStatus,
    name="external_channel_hydration_status",
    create_type=False,
    values_callable=_enum_values,
)
external_channel_event_eligibility_state_enum = ENUM(
    ExternalChannelEventEligibilityState,
    name="external_channel_event_eligibility_state",
    create_type=False,
    values_callable=_enum_values,
)
external_channel_event_status_enum = ENUM(
    ExternalChannelEventStatus,
    name="external_channel_event_status",
    create_type=False,
    values_callable=_enum_values,
)
external_channel_principal_author_type_enum = ENUM(
    ExternalChannelPrincipalAuthorType,
    name="external_channel_principal_author_type",
    create_type=False,
    values_callable=_enum_values,
)
external_channel_message_lifecycle_enum = ENUM(
    ExternalChannelMessageLifecycle,
    name="external_channel_message_lifecycle",
    create_type=False,
    values_callable=_enum_values,
)
external_channel_message_revision_kind_enum = ENUM(
    ExternalChannelMessageRevisionKind,
    name="external_channel_message_revision_kind",
    create_type=False,
    values_callable=_enum_values,
)
external_channel_binding_status_enum = ENUM(
    ExternalChannelBindingStatus,
    name="external_channel_binding_status",
    create_type=False,
    values_callable=_enum_values,
)
external_channel_binding_activation_status_enum = ENUM(
    ExternalChannelBindingActivationStatus,
    name="external_channel_binding_activation_status",
    create_type=False,
    values_callable=_enum_values,
)
external_channel_access_request_status_enum = ENUM(
    ExternalChannelAccessRequestStatus,
    name="external_channel_access_request_status",
    create_type=False,
    values_callable=_enum_values,
)
external_channel_access_grant_scope_enum = ENUM(
    ExternalChannelAccessGrantScope,
    name="external_channel_access_grant_scope",
    create_type=False,
    values_callable=_enum_values,
)
external_channel_work_status_enum = ENUM(
    ExternalChannelWorkStatus,
    name="external_channel_work_status",
    create_type=False,
    values_callable=_enum_values,
)
external_channel_action_mode_enum = ENUM(
    ExternalChannelActionMode,
    name="external_channel_action_mode",
    create_type=False,
    values_callable=_enum_values,
)
external_channel_delivery_origin_type_enum = ENUM(
    ExternalChannelDeliveryOriginType,
    name="external_channel_delivery_origin_type",
    create_type=False,
    values_callable=_enum_values,
)
external_channel_delivery_operation_enum = ENUM(
    ExternalChannelDeliveryOperation,
    name="external_channel_delivery_operation",
    create_type=False,
    values_callable=_enum_values,
)
external_channel_delivery_status_enum = ENUM(
    ExternalChannelDeliveryStatus,
    name="external_channel_delivery_status",
    create_type=False,
    values_callable=_enum_values,
)


class RDBExternalChannelConnection(RDBModel):
    """Workspace-owned provider credential and transport boundary."""

    __tablename__ = "external_channel_connections"

    IX_WORKSPACE_ID = sa.Index(
        "ix_external_channel_connections_workspace_id",
        "workspace_id",
    )
    IX_STATUS = sa.Index("ix_external_channel_connections_status", "status")
    IX_SOCKET_LEASE_UNTIL = sa.Index(
        "ix_external_channel_connections_socket_lease_until",
        "socket_lease_until",
    )
    UQ_INSTALLATION_IDENTITY = sa.Index(
        "uq_external_channel_connections_installation_identity",
        "provider",
        "provider_tenant_id",
        "provider_app_id",
        unique=True,
        postgresql_where=sa.text(
            "provider_tenant_id IS NOT NULL AND provider_app_id IS NOT NULL"
        ),
    )
    UQ_HTTP_CALLBACK_SELECTOR_HASH = sa.Index(
        "uq_external_channel_connections_http_callback_selector_hash",
        "http_callback_selector_hash",
        unique=True,
        postgresql_where=sa.text("http_callback_selector_hash IS NOT NULL"),
    )

    id: Mapped[str] = mapped_column(
        sa.String(32),
        primary_key=True,
        init=False,
        default_factory=lambda: uuid7().hex,
    )
    workspace_id: Mapped[str] = mapped_column(
        sa.String(32),
        sa.ForeignKey("workspaces.id", ondelete="RESTRICT"),
        nullable=False,
    )
    provider: Mapped[ExternalChannelProvider] = mapped_column(
        external_channel_provider_enum,
        nullable=False,
    )
    transport: Mapped[ExternalChannelTransport] = mapped_column(
        external_channel_transport_enum,
        nullable=False,
    )
    status: Mapped[ExternalChannelConnectionStatus] = mapped_column(
        external_channel_connection_status_enum,
        nullable=False,
        server_default=ExternalChannelConnectionStatus.CONFIGURING.value,
    )
    provider_app_id: Mapped[str | None] = mapped_column(
        sa.String(255),
        nullable=True,
        default=None,
    )
    provider_tenant_id: Mapped[str | None] = mapped_column(
        sa.String(255),
        nullable=True,
        default=None,
    )
    provider_bot_user_id: Mapped[str | None] = mapped_column(
        sa.String(255),
        nullable=True,
        default=None,
    )
    http_callback_selector_hash: Mapped[str | None] = mapped_column(
        sa.String(128),
        nullable=True,
        default=None,
    )
    encrypted_credentials: Mapped[str | None] = mapped_column(
        sa.Text,
        nullable=True,
        default=None,
    )
    capabilities: Mapped[dict[str, Any] | None] = mapped_column(
        JSONB,
        nullable=True,
        default=None,
    )
    provider_config: Mapped[dict[str, Any] | None] = mapped_column(
        JSONB,
        nullable=True,
        default=None,
    )
    last_verified_at: Mapped[datetime.datetime | None] = mapped_column(
        TimeZoneDateTime,
        nullable=True,
        default=None,
    )
    last_health_at: Mapped[datetime.datetime | None] = mapped_column(
        TimeZoneDateTime,
        nullable=True,
        default=None,
    )
    disconnected_at: Mapped[datetime.datetime | None] = mapped_column(
        TimeZoneDateTime,
        nullable=True,
        default=None,
    )
    socket_lease_owner: Mapped[str | None] = mapped_column(
        sa.String(255),
        nullable=True,
        default=None,
    )
    socket_lease_until: Mapped[datetime.datetime | None] = mapped_column(
        TimeZoneDateTime,
        nullable=True,
        default=None,
    )
    socket_heartbeat_at: Mapped[datetime.datetime | None] = mapped_column(
        TimeZoneDateTime,
        nullable=True,
        default=None,
    )
    socket_gap_detected_at: Mapped[datetime.datetime | None] = mapped_column(
        TimeZoneDateTime,
        nullable=True,
        default=None,
    )
    socket_gap_reason: Mapped[str | None] = mapped_column(
        sa.String(255),
        nullable=True,
        default=None,
    )
    created_at: Mapped[datetime.datetime] = mapped_column(
        TimeZoneDateTime,
        init=False,
        nullable=False,
        server_default=sa.func.now(),
    )
    updated_at: Mapped[datetime.datetime] = mapped_column(
        TimeZoneDateTime,
        init=False,
        nullable=False,
        server_default=sa.func.now(),
        onupdate=sa.func.now(),
    )

    __table_args__ = (
        IX_WORKSPACE_ID,
        IX_STATUS,
        IX_SOCKET_LEASE_UNTIL,
        UQ_INSTALLATION_IDENTITY,
        UQ_HTTP_CALLBACK_SELECTOR_HASH,
    )


class RDBExternalChannelAgentRoute(RDBModel):
    """Persistent relationship between one Agent and provider connection."""

    __tablename__ = "external_channel_agent_routes"

    IX_AGENT_ID = sa.Index("ix_external_channel_agent_routes_agent_id", "agent_id")
    IX_CONNECTION_ID = sa.Index(
        "ix_external_channel_agent_routes_connection_id",
        "connection_id",
    )
    UQ_DEDICATED_CONNECTION = sa.Index(
        "uq_external_channel_agent_routes_dedicated_connection",
        "connection_id",
        unique=True,
        postgresql_where=sa.text("route_mode = 'dedicated'"),
    )

    id: Mapped[str] = mapped_column(
        sa.String(32),
        primary_key=True,
        init=False,
        default_factory=lambda: uuid7().hex,
    )
    connection_id: Mapped[str] = mapped_column(
        sa.String(32),
        sa.ForeignKey("external_channel_connections.id", ondelete="RESTRICT"),
        nullable=False,
    )
    agent_id: Mapped[str] = mapped_column(
        sa.String(32),
        sa.ForeignKey("agents.id", ondelete="RESTRICT"),
        nullable=False,
    )
    route_mode: Mapped[ExternalChannelRouteMode] = mapped_column(
        external_channel_route_mode_enum,
        nullable=False,
        server_default=ExternalChannelRouteMode.DEDICATED.value,
    )
    created_at: Mapped[datetime.datetime] = mapped_column(
        TimeZoneDateTime,
        init=False,
        nullable=False,
        server_default=sa.func.now(),
    )
    updated_at: Mapped[datetime.datetime] = mapped_column(
        TimeZoneDateTime,
        init=False,
        nullable=False,
        server_default=sa.func.now(),
        onupdate=sa.func.now(),
    )
    __table_args__ = (
        IX_AGENT_ID,
        IX_CONNECTION_ID,
        UQ_DEDICATED_CONNECTION,
    )


class RDBExternalChannelResource(RDBModel):
    """Canonical provider conversation or external work resource."""

    __tablename__ = "external_channel_resources"

    IX_CONNECTION_ID_STATUS = sa.Index(
        "ix_external_channel_resources_connection_id_status",
        "connection_id",
        "status",
    )
    IX_LATEST_ACTIVITY_AT = sa.Index(
        "ix_external_channel_resources_latest_activity_at",
        "latest_activity_at",
    )
    UQ_CONNECTION_TYPE_PROVIDER_KEY = sa.UniqueConstraint(
        "connection_id",
        "resource_type",
        "provider_resource_key",
        name="uq_external_channel_resources_connection_type_provider_key",
    )

    id: Mapped[str] = mapped_column(
        sa.String(32),
        primary_key=True,
        init=False,
        default_factory=lambda: uuid7().hex,
    )
    connection_id: Mapped[str] = mapped_column(
        sa.String(32),
        sa.ForeignKey("external_channel_connections.id", ondelete="RESTRICT"),
        nullable=False,
    )
    resource_type: Mapped[ExternalChannelResourceType] = mapped_column(
        external_channel_resource_type_enum,
        nullable=False,
    )
    provider_resource_key: Mapped[str] = mapped_column(sa.Text, nullable=False)
    status: Mapped[ExternalChannelResourceStatus] = mapped_column(
        external_channel_resource_status_enum,
        nullable=False,
        server_default=ExternalChannelResourceStatus.ACTIVE.value,
    )
    hydration_status: Mapped[ExternalChannelHydrationStatus] = mapped_column(
        external_channel_hydration_status_enum,
        nullable=False,
        server_default=ExternalChannelHydrationStatus.PENDING.value,
    )
    hydration_cursor: Mapped[str | None] = mapped_column(
        sa.Text,
        nullable=True,
        default=None,
    )
    hydration_high_watermark_position: Mapped[str | None] = mapped_column(
        sa.String(255),
        nullable=True,
        default=None,
    )
    reconciliation_boundary_received_at: Mapped[datetime.datetime | None] = (
        mapped_column(
            TimeZoneDateTime,
            nullable=True,
            default=None,
        )
    )
    reconciliation_boundary_event_id: Mapped[str | None] = mapped_column(
        sa.String(32),
        nullable=True,
        default=None,
    )
    hydration_error_kind: Mapped[str | None] = mapped_column(
        sa.String(120),
        nullable=True,
        default=None,
    )
    hydration_error_summary: Mapped[str | None] = mapped_column(
        sa.Text,
        nullable=True,
        default=None,
    )
    hydration_started_at: Mapped[datetime.datetime | None] = mapped_column(
        TimeZoneDateTime,
        nullable=True,
        default=None,
    )
    hydration_completed_at: Mapped[datetime.datetime | None] = mapped_column(
        TimeZoneDateTime,
        nullable=True,
        default=None,
    )
    labels: Mapped[dict[str, Any] | None] = mapped_column(
        JSONB,
        nullable=True,
        default=None,
    )
    discovered_at: Mapped[datetime.datetime] = mapped_column(
        TimeZoneDateTime,
        init=False,
        nullable=False,
        server_default=sa.func.now(),
    )
    latest_activity_at: Mapped[datetime.datetime | None] = mapped_column(
        TimeZoneDateTime,
        nullable=True,
        default=None,
    )
    unavailable_at: Mapped[datetime.datetime | None] = mapped_column(
        TimeZoneDateTime,
        nullable=True,
        default=None,
    )
    deleted_at: Mapped[datetime.datetime | None] = mapped_column(
        TimeZoneDateTime,
        nullable=True,
        default=None,
    )
    created_at: Mapped[datetime.datetime] = mapped_column(
        TimeZoneDateTime,
        init=False,
        nullable=False,
        server_default=sa.func.now(),
    )
    updated_at: Mapped[datetime.datetime] = mapped_column(
        TimeZoneDateTime,
        init=False,
        nullable=False,
        server_default=sa.func.now(),
        onupdate=sa.func.now(),
    )

    __table_args__ = (
        IX_CONNECTION_ID_STATUS,
        IX_LATEST_ACTIVITY_AT,
        UQ_CONNECTION_TYPE_PROVIDER_KEY,
    )


class RDBExternalChannelEvent(RDBModel):
    """Durably admitted provider event awaiting idempotent processing."""

    __tablename__ = "external_channel_events"

    IX_STATUS_RECEIVED_AT = sa.Index(
        "ix_external_channel_events_status_received_at",
        "status",
        "received_at",
    )
    IX_CONNECTION_ID_PROVIDER_TIMESTAMP = sa.Index(
        "ix_external_channel_events_connection_id_provider_timestamp",
        "connection_id",
        "provider_occurred_at",
    )
    IX_CONNECTION_CORRELATION_STATUS = sa.Index(
        "ix_external_channel_events_connection_correlation_status",
        "connection_id",
        "resource_correlation_key",
        "status",
        "received_at",
    )
    UQ_CONNECTION_PROVIDER_EVENT = sa.UniqueConstraint(
        "connection_id",
        "provider_event_id",
        name="uq_external_channel_events_connection_provider_event",
    )

    id: Mapped[str] = mapped_column(
        sa.String(32),
        primary_key=True,
        init=False,
        default_factory=lambda: uuid7().hex,
    )
    connection_id: Mapped[str] = mapped_column(
        sa.String(32),
        sa.ForeignKey("external_channel_connections.id", ondelete="RESTRICT"),
        nullable=False,
    )
    provider_event_id: Mapped[str] = mapped_column(sa.String(255), nullable=False)
    event_type: Mapped[str] = mapped_column(sa.String(120), nullable=False)
    envelope: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    eligibility_state: Mapped[ExternalChannelEventEligibilityState] = mapped_column(
        external_channel_event_eligibility_state_enum,
        nullable=False,
        server_default=ExternalChannelEventEligibilityState.UNCLASSIFIED.value,
    )
    status: Mapped[ExternalChannelEventStatus] = mapped_column(
        external_channel_event_status_enum,
        nullable=False,
        server_default=ExternalChannelEventStatus.ACCEPTED.value,
    )
    transport_envelope_id: Mapped[str | None] = mapped_column(
        sa.String(255),
        nullable=True,
        default=None,
    )
    provider_app_id: Mapped[str | None] = mapped_column(
        sa.String(255),
        nullable=True,
        default=None,
    )
    provider_tenant_id: Mapped[str | None] = mapped_column(
        sa.String(255),
        nullable=True,
        default=None,
    )
    provider_enterprise_id: Mapped[str | None] = mapped_column(
        sa.String(255),
        nullable=True,
        default=None,
    )
    resource_correlation_key: Mapped[str | None] = mapped_column(
        sa.Text,
        nullable=True,
        default=None,
    )
    attempt_count: Mapped[int] = mapped_column(
        sa.Integer,
        init=False,
        nullable=False,
        server_default="0",
    )
    claim_owner: Mapped[str | None] = mapped_column(
        sa.String(120),
        nullable=True,
        default=None,
    )
    claim_until: Mapped[datetime.datetime | None] = mapped_column(
        TimeZoneDateTime,
        nullable=True,
        default=None,
    )
    error_kind: Mapped[str | None] = mapped_column(
        sa.String(120),
        nullable=True,
        default=None,
    )
    error_summary: Mapped[str | None] = mapped_column(
        sa.Text,
        nullable=True,
        default=None,
    )
    provider_occurred_at: Mapped[datetime.datetime | None] = mapped_column(
        TimeZoneDateTime,
        nullable=True,
        default=None,
    )
    received_at: Mapped[datetime.datetime] = mapped_column(
        TimeZoneDateTime,
        init=False,
        nullable=False,
        server_default=sa.func.now(),
    )
    processing_started_at: Mapped[datetime.datetime | None] = mapped_column(
        TimeZoneDateTime,
        nullable=True,
        default=None,
    )
    processed_at: Mapped[datetime.datetime | None] = mapped_column(
        TimeZoneDateTime,
        nullable=True,
        default=None,
    )
    created_at: Mapped[datetime.datetime] = mapped_column(
        TimeZoneDateTime,
        init=False,
        nullable=False,
        server_default=sa.func.now(),
    )
    updated_at: Mapped[datetime.datetime] = mapped_column(
        TimeZoneDateTime,
        init=False,
        nullable=False,
        server_default=sa.func.now(),
        onupdate=sa.func.now(),
    )

    __table_args__ = (
        IX_STATUS_RECEIVED_AT,
        IX_CONNECTION_ID_PROVIDER_TIMESTAMP,
        IX_CONNECTION_CORRELATION_STATUS,
        UQ_CONNECTION_PROVIDER_EVENT,
    )


class RDBExternalChannelPrincipal(RDBModel):
    """Canonical provider participant identity independent from Azents users."""

    __tablename__ = "external_channel_principals"

    UQ_PROVIDER_TENANT_USER = sa.UniqueConstraint(
        "provider",
        "provider_tenant_id",
        "provider_user_id",
        name="uq_external_channel_principals_provider_tenant_user",
    )

    id: Mapped[str] = mapped_column(
        sa.String(32),
        primary_key=True,
        init=False,
        default_factory=lambda: uuid7().hex,
    )
    provider: Mapped[ExternalChannelProvider] = mapped_column(
        external_channel_provider_enum,
        nullable=False,
    )
    provider_tenant_id: Mapped[str] = mapped_column(sa.String(255), nullable=False)
    provider_user_id: Mapped[str] = mapped_column(sa.String(255), nullable=False)
    author_type: Mapped[ExternalChannelPrincipalAuthorType] = mapped_column(
        external_channel_principal_author_type_enum,
        nullable=False,
    )
    display_name: Mapped[str | None] = mapped_column(
        sa.String(255),
        nullable=True,
        default=None,
    )
    avatar_url: Mapped[str | None] = mapped_column(
        sa.Text,
        nullable=True,
        default=None,
    )
    profile: Mapped[dict[str, Any] | None] = mapped_column(
        JSONB,
        nullable=True,
        default=None,
    )
    first_observed_at: Mapped[datetime.datetime] = mapped_column(
        TimeZoneDateTime,
        init=False,
        nullable=False,
        server_default=sa.func.now(),
    )
    last_observed_at: Mapped[datetime.datetime] = mapped_column(
        TimeZoneDateTime,
        init=False,
        nullable=False,
        server_default=sa.func.now(),
    )
    created_at: Mapped[datetime.datetime] = mapped_column(
        TimeZoneDateTime,
        init=False,
        nullable=False,
        server_default=sa.func.now(),
    )
    updated_at: Mapped[datetime.datetime] = mapped_column(
        TimeZoneDateTime,
        init=False,
        nullable=False,
        server_default=sa.func.now(),
        onupdate=sa.func.now(),
    )

    __table_args__ = (UQ_PROVIDER_TENANT_USER,)


class RDBExternalChannelMessage(RDBModel):
    """Canonical external message state independent from AgentSession retention."""

    __tablename__ = "external_channel_messages"

    IX_RESOURCE_POSITION = sa.Index(
        "ix_external_channel_messages_resource_id_provider_position",
        "resource_id",
        "provider_position",
    )
    IX_PRINCIPAL_ID = sa.Index(
        "ix_external_channel_messages_principal_id",
        "principal_id",
    )
    UQ_RESOURCE_PROVIDER_MESSAGE = sa.UniqueConstraint(
        "resource_id",
        "provider_message_key",
        name="uq_external_channel_messages_resource_provider_message",
    )
    FK_CURRENT_REVISION = sa.ForeignKeyConstraint(
        ["id", "current_revision_id"],
        [
            "external_channel_message_revisions.message_id",
            "external_channel_message_revisions.id",
        ],
        name="fk_external_channel_messages_current_revision",
        use_alter=True,
        deferrable=True,
        initially="DEFERRED",
    )

    id: Mapped[str] = mapped_column(
        sa.String(32),
        primary_key=True,
        init=False,
        default_factory=lambda: uuid7().hex,
    )
    resource_id: Mapped[str] = mapped_column(
        sa.String(32),
        sa.ForeignKey("external_channel_resources.id", ondelete="RESTRICT"),
        nullable=False,
    )
    provider_message_key: Mapped[str] = mapped_column(sa.Text, nullable=False)
    provider_position: Mapped[str] = mapped_column(sa.String(255), nullable=False)
    lifecycle: Mapped[ExternalChannelMessageLifecycle] = mapped_column(
        external_channel_message_lifecycle_enum,
        nullable=False,
        server_default=ExternalChannelMessageLifecycle.CURRENT.value,
    )
    author_type: Mapped[ExternalChannelPrincipalAuthorType] = mapped_column(
        external_channel_principal_author_type_enum,
        nullable=False,
    )
    principal_id: Mapped[str | None] = mapped_column(
        sa.String(32),
        sa.ForeignKey("external_channel_principals.id", ondelete="SET NULL"),
        nullable=True,
        default=None,
    )
    current_revision_id: Mapped[str | None] = mapped_column(
        sa.String(32),
        nullable=True,
        default=None,
    )
    original_url: Mapped[str | None] = mapped_column(
        sa.Text,
        nullable=True,
        default=None,
    )
    pending_size: Mapped[int] = mapped_column(
        sa.Integer,
        init=False,
        nullable=False,
        server_default="0",
    )
    provider_created_at: Mapped[datetime.datetime | None] = mapped_column(
        TimeZoneDateTime,
        nullable=True,
        default=None,
    )
    provider_updated_at: Mapped[datetime.datetime | None] = mapped_column(
        TimeZoneDateTime,
        nullable=True,
        default=None,
    )
    observed_at: Mapped[datetime.datetime] = mapped_column(
        TimeZoneDateTime,
        init=False,
        nullable=False,
        server_default=sa.func.now(),
    )
    created_at: Mapped[datetime.datetime] = mapped_column(
        TimeZoneDateTime,
        init=False,
        nullable=False,
        server_default=sa.func.now(),
    )
    updated_at: Mapped[datetime.datetime] = mapped_column(
        TimeZoneDateTime,
        init=False,
        nullable=False,
        server_default=sa.func.now(),
        onupdate=sa.func.now(),
    )

    __table_args__ = (
        IX_RESOURCE_POSITION,
        IX_PRINCIPAL_ID,
        UQ_RESOURCE_PROVIDER_MESSAGE,
        FK_CURRENT_REVISION,
    )


class RDBExternalChannelMessageRevision(RDBModel):
    """Immutable normalized provider message revision."""

    __tablename__ = "external_channel_message_revisions"

    IX_SOURCE_EVENT_ID = sa.Index(
        "ix_external_channel_message_revisions_source_event_id",
        "source_event_id",
    )
    UQ_MESSAGE_REVISION_KEY = sa.UniqueConstraint(
        "message_id",
        "revision_key",
        name="uq_external_channel_message_revisions_message_revision_key",
    )
    UQ_MESSAGE_ID_ID = sa.UniqueConstraint(
        "message_id",
        "id",
        name="uq_external_channel_message_revisions_message_id_id",
    )

    id: Mapped[str] = mapped_column(
        sa.String(32),
        primary_key=True,
        init=False,
        default_factory=lambda: uuid7().hex,
    )
    message_id: Mapped[str] = mapped_column(
        sa.String(32),
        sa.ForeignKey("external_channel_messages.id", ondelete="CASCADE"),
        nullable=False,
    )
    revision_key: Mapped[str] = mapped_column(sa.String(255), nullable=False)
    revision_kind: Mapped[ExternalChannelMessageRevisionKind] = mapped_column(
        external_channel_message_revision_kind_enum,
        nullable=False,
    )
    normalized_body: Mapped[str | None] = mapped_column(
        sa.Text,
        nullable=True,
        default=None,
    )
    attachment_metadata: Mapped[dict[str, Any] | None] = mapped_column(
        JSONB,
        nullable=True,
        default=None,
    )
    reference_mappings: Mapped[dict[str, Any] | None] = mapped_column(
        JSONB,
        nullable=True,
        default=None,
    )
    source_event_id: Mapped[str | None] = mapped_column(
        sa.String(32),
        sa.ForeignKey("external_channel_events.id", ondelete="SET NULL"),
        nullable=True,
        default=None,
    )
    provider_occurred_at: Mapped[datetime.datetime | None] = mapped_column(
        TimeZoneDateTime,
        nullable=True,
        default=None,
    )
    observed_at: Mapped[datetime.datetime] = mapped_column(
        TimeZoneDateTime,
        init=False,
        nullable=False,
        server_default=sa.func.now(),
    )
    created_at: Mapped[datetime.datetime] = mapped_column(
        TimeZoneDateTime,
        init=False,
        nullable=False,
        server_default=sa.func.now(),
    )

    __table_args__ = (
        IX_SOURCE_EVENT_ID,
        UQ_MESSAGE_REVISION_KEY,
        UQ_MESSAGE_ID_ID,
    )


class RDBExternalChannelPendingContext(RDBModel):
    """Bounded route-and-resource context not yet projected to a session."""

    __tablename__ = "external_channel_pending_contexts"

    IX_ROUTE_RESOURCE_POSITION = sa.Index(
        "ix_external_channel_pending_ctx_route_resource_position",
        "route_id",
        "resource_id",
        "provider_position",
    )
    IX_EXPIRES_AT = sa.Index(
        "ix_external_channel_pending_contexts_expires_at",
        "expires_at",
    )
    UQ_ROUTE_RESOURCE_MESSAGE_REVISION = sa.UniqueConstraint(
        "route_id",
        "resource_id",
        "message_revision_id",
        name="uq_external_channel_pending_route_resource_message_revision",
    )

    id: Mapped[str] = mapped_column(
        sa.String(32),
        primary_key=True,
        init=False,
        default_factory=lambda: uuid7().hex,
    )
    route_id: Mapped[str] = mapped_column(
        sa.String(32),
        sa.ForeignKey("external_channel_agent_routes.id", ondelete="RESTRICT"),
        nullable=False,
    )
    resource_id: Mapped[str] = mapped_column(
        sa.String(32),
        sa.ForeignKey("external_channel_resources.id", ondelete="RESTRICT"),
        nullable=False,
    )
    message_revision_id: Mapped[str] = mapped_column(
        sa.String(32),
        sa.ForeignKey(
            "external_channel_message_revisions.id",
            ondelete="RESTRICT",
        ),
        nullable=False,
    )
    provider_position: Mapped[str] = mapped_column(sa.String(255), nullable=False)
    normalized_size: Mapped[int] = mapped_column(sa.Integer, nullable=False)
    expires_at: Mapped[datetime.datetime] = mapped_column(
        TimeZoneDateTime,
        nullable=False,
    )
    created_at: Mapped[datetime.datetime] = mapped_column(
        TimeZoneDateTime,
        init=False,
        nullable=False,
        server_default=sa.func.now(),
    )

    __table_args__ = (
        IX_ROUTE_RESOURCE_POSITION,
        IX_EXPIRES_AT,
        UQ_ROUTE_RESOURCE_MESSAGE_REVISION,
    )


class RDBExternalChannelBinding(RDBModel):
    """Lifecycle-owned link between one external resource and AgentSession."""

    __tablename__ = "external_channel_bindings"

    IX_AGENT_SESSION_ID_STATUS = sa.Index(
        "ix_external_channel_bindings_agent_session_id_status",
        "agent_session_id",
        "status",
    )
    IX_ROUTE_ID_STATUS = sa.Index(
        "ix_external_channel_bindings_route_id_status",
        "route_id",
        "status",
    )
    UQ_ACTIVE_RESOURCE_ROUTE = sa.Index(
        "uq_external_channel_bindings_active_resource_route",
        "resource_id",
        "route_id",
        unique=True,
        postgresql_where=sa.text("status = 'active'"),
    )

    id: Mapped[str] = mapped_column(
        sa.String(32),
        primary_key=True,
        init=False,
        default_factory=lambda: uuid7().hex,
    )
    resource_id: Mapped[str] = mapped_column(
        sa.String(32),
        sa.ForeignKey("external_channel_resources.id", ondelete="RESTRICT"),
        nullable=False,
    )
    route_id: Mapped[str] = mapped_column(
        sa.String(32),
        sa.ForeignKey("external_channel_agent_routes.id", ondelete="RESTRICT"),
        nullable=False,
    )
    agent_session_id: Mapped[str] = mapped_column(
        sa.String(32),
        sa.ForeignKey("agent_sessions.id", ondelete="RESTRICT"),
        nullable=False,
    )
    status: Mapped[ExternalChannelBindingStatus] = mapped_column(
        external_channel_binding_status_enum,
        nullable=False,
        server_default=ExternalChannelBindingStatus.ACTIVE.value,
    )
    activation_status: Mapped[ExternalChannelBindingActivationStatus] = mapped_column(
        external_channel_binding_activation_status_enum,
        nullable=False,
        server_default=(ExternalChannelBindingActivationStatus.WAITING_HYDRATION.value),
    )
    activation_trigger_message_id: Mapped[str | None] = mapped_column(
        sa.String(32),
        sa.ForeignKey("external_channel_messages.id", ondelete="RESTRICT"),
        nullable=True,
        default=None,
    )
    activated_at: Mapped[datetime.datetime | None] = mapped_column(
        TimeZoneDateTime,
        nullable=True,
        default=None,
    )
    projected_through_position: Mapped[str | None] = mapped_column(
        sa.String(255),
        nullable=True,
        default=None,
    )
    truncated_message_count: Mapped[int] = mapped_column(
        sa.Integer,
        init=False,
        nullable=False,
        server_default="0",
    )
    truncated_size: Mapped[int] = mapped_column(
        sa.Integer,
        init=False,
        nullable=False,
        server_default="0",
    )
    connected_at: Mapped[datetime.datetime] = mapped_column(
        TimeZoneDateTime,
        init=False,
        nullable=False,
        server_default=sa.func.now(),
    )
    disconnected_at: Mapped[datetime.datetime | None] = mapped_column(
        TimeZoneDateTime,
        nullable=True,
        default=None,
    )
    disconnect_reason: Mapped[str | None] = mapped_column(
        sa.String(120),
        nullable=True,
        default=None,
    )
    created_at: Mapped[datetime.datetime] = mapped_column(
        TimeZoneDateTime,
        init=False,
        nullable=False,
        server_default=sa.func.now(),
    )
    updated_at: Mapped[datetime.datetime] = mapped_column(
        TimeZoneDateTime,
        init=False,
        nullable=False,
        server_default=sa.func.now(),
        onupdate=sa.func.now(),
    )

    __table_args__ = (
        IX_AGENT_SESSION_ID_STATUS,
        IX_ROUTE_ID_STATUS,
        UQ_ACTIVE_RESOURCE_ROUTE,
    )


class RDBExternalChannelInvocationBatch(RDBModel):
    """One ordered external turn released through an authorized invocation."""

    __tablename__ = "external_channel_invocation_batches"

    IX_BINDING_ID_CREATED_AT = sa.Index(
        "ix_external_channel_invocation_batches_binding_id_created_at",
        "binding_id",
        "created_at",
    )
    UQ_BINDING_TRIGGER_MESSAGE = sa.UniqueConstraint(
        "binding_id",
        "trigger_message_id",
        name="uq_external_channel_invocation_batches_binding_trigger_message",
    )

    id: Mapped[str] = mapped_column(
        sa.String(32),
        primary_key=True,
        init=False,
        default_factory=lambda: uuid7().hex,
    )
    binding_id: Mapped[str] = mapped_column(
        sa.String(32),
        sa.ForeignKey("external_channel_bindings.id", ondelete="RESTRICT"),
        nullable=False,
    )
    trigger_message_id: Mapped[str] = mapped_column(
        sa.String(32),
        sa.ForeignKey("external_channel_messages.id", ondelete="RESTRICT"),
        nullable=False,
    )
    first_provider_position: Mapped[str] = mapped_column(sa.String(255), nullable=False)
    last_provider_position: Mapped[str] = mapped_column(sa.String(255), nullable=False)
    truncation_message_count: Mapped[int] = mapped_column(
        sa.Integer,
        nullable=False,
        server_default="0",
    )
    truncation_size: Mapped[int] = mapped_column(
        sa.Integer,
        nullable=False,
        server_default="0",
    )
    input_buffer_id: Mapped[str | None] = mapped_column(
        sa.String(32),
        sa.ForeignKey("input_buffers.id", ondelete="SET NULL"),
        nullable=True,
        default=None,
    )
    created_at: Mapped[datetime.datetime] = mapped_column(
        TimeZoneDateTime,
        init=False,
        nullable=False,
        server_default=sa.func.now(),
    )

    __table_args__ = (IX_BINDING_ID_CREATED_AT, UQ_BINDING_TRIGGER_MESSAGE)


class RDBExternalChannelInvocationBatchItem(RDBModel):
    """One immutable external message revision included in an invocation batch."""

    __tablename__ = "external_channel_invocation_batch_items"

    UQ_BATCH_SEQUENCE = sa.UniqueConstraint(
        "batch_id",
        "sequence",
        name="uq_external_channel_invocation_batch_items_batch_sequence",
    )
    UQ_BATCH_REVISION = sa.UniqueConstraint(
        "batch_id",
        "message_revision_id",
        name="uq_external_channel_invocation_batch_items_batch_revision",
    )
    IX_MESSAGE_REVISION_ID = sa.Index(
        "ix_external_channel_invocation_batch_items_message_revision_id",
        "message_revision_id",
    )

    id: Mapped[str] = mapped_column(
        sa.String(32),
        primary_key=True,
        init=False,
        default_factory=lambda: uuid7().hex,
    )
    batch_id: Mapped[str] = mapped_column(
        sa.String(32),
        sa.ForeignKey("external_channel_invocation_batches.id", ondelete="CASCADE"),
        nullable=False,
    )
    message_revision_id: Mapped[str] = mapped_column(
        sa.String(32),
        sa.ForeignKey(
            "external_channel_message_revisions.id",
            ondelete="RESTRICT",
        ),
        nullable=False,
    )
    sequence: Mapped[int] = mapped_column(sa.Integer, nullable=False)
    provider_position: Mapped[str] = mapped_column(sa.String(255), nullable=False)
    created_at: Mapped[datetime.datetime] = mapped_column(
        TimeZoneDateTime,
        init=False,
        nullable=False,
        server_default=sa.func.now(),
    )

    __table_args__ = (
        UQ_BATCH_SEQUENCE,
        UQ_BATCH_REVISION,
        IX_MESSAGE_REVISION_ID,
    )


class RDBExternalChannelAccessRequest(RDBModel):
    """Durable request to authorize one external principal invocation."""

    __tablename__ = "external_channel_access_requests"

    IX_STATUS_CREATED_AT = sa.Index(
        "ix_external_channel_access_requests_status_created_at",
        "status",
        "created_at",
    )
    IX_AGENT_SESSION_ID = sa.Index(
        "ix_external_channel_access_requests_agent_session_id",
        "agent_session_id",
    )
    UQ_ROUTE_SOURCE_MESSAGE = sa.UniqueConstraint(
        "route_id",
        "source_message_id",
        name="uq_external_channel_access_requests_route_source_message",
    )

    id: Mapped[str] = mapped_column(
        sa.String(32),
        primary_key=True,
        init=False,
        default_factory=lambda: uuid7().hex,
    )
    route_id: Mapped[str] = mapped_column(
        sa.String(32),
        sa.ForeignKey("external_channel_agent_routes.id", ondelete="RESTRICT"),
        nullable=False,
    )
    resource_id: Mapped[str] = mapped_column(
        sa.String(32),
        sa.ForeignKey("external_channel_resources.id", ondelete="RESTRICT"),
        nullable=False,
    )
    source_message_id: Mapped[str] = mapped_column(
        sa.String(32),
        sa.ForeignKey("external_channel_messages.id", ondelete="RESTRICT"),
        nullable=False,
    )
    principal_id: Mapped[str] = mapped_column(
        sa.String(32),
        sa.ForeignKey("external_channel_principals.id", ondelete="RESTRICT"),
        nullable=False,
    )
    status: Mapped[ExternalChannelAccessRequestStatus] = mapped_column(
        external_channel_access_request_status_enum,
        nullable=False,
        server_default=ExternalChannelAccessRequestStatus.PENDING.value,
    )
    decision_policy_snapshot: Mapped[dict[str, Any]] = mapped_column(
        JSONB,
        nullable=False,
    )
    expires_at: Mapped[datetime.datetime] = mapped_column(
        TimeZoneDateTime,
        nullable=False,
    )
    agent_session_id: Mapped[str | None] = mapped_column(
        sa.String(32),
        sa.ForeignKey("agent_sessions.id", ondelete="RESTRICT"),
        nullable=True,
        default=None,
    )
    decided_by_user_id: Mapped[str | None] = mapped_column(
        sa.String(32),
        sa.ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=True,
        default=None,
    )
    decision_summary: Mapped[str | None] = mapped_column(
        sa.Text,
        nullable=True,
        default=None,
    )
    decided_at: Mapped[datetime.datetime | None] = mapped_column(
        TimeZoneDateTime,
        nullable=True,
        default=None,
    )
    created_at: Mapped[datetime.datetime] = mapped_column(
        TimeZoneDateTime,
        init=False,
        nullable=False,
        server_default=sa.func.now(),
    )
    updated_at: Mapped[datetime.datetime] = mapped_column(
        TimeZoneDateTime,
        init=False,
        nullable=False,
        server_default=sa.func.now(),
        onupdate=sa.func.now(),
    )

    __table_args__ = (
        IX_STATUS_CREATED_AT,
        IX_AGENT_SESSION_ID,
        UQ_ROUTE_SOURCE_MESSAGE,
    )


class RDBExternalChannelAccessGrant(RDBModel):
    """Session- or Agent-scoped external principal invocation grant."""

    __tablename__ = "external_channel_access_grants"

    CK_SCOPE_SESSION = sa.CheckConstraint(
        "(scope = 'agent' AND agent_session_id IS NULL) OR "
        "(scope = 'session' AND agent_session_id IS NOT NULL)",
        name="ck_external_channel_access_grants_scope_session",
    )
    IX_AGENT_ID = sa.Index(
        "ix_external_channel_access_grants_agent_id",
        "agent_id",
    )
    IX_AGENT_SESSION_ID = sa.Index(
        "ix_external_channel_access_grants_agent_session_id",
        "agent_session_id",
    )
    UQ_ACTIVE_AGENT_GRANT = sa.Index(
        "uq_external_channel_access_grants_active_agent",
        "agent_id",
        "principal_id",
        unique=True,
        postgresql_where=sa.text("scope = 'agent' AND revoked_at IS NULL"),
    )
    UQ_ACTIVE_SESSION_GRANT = sa.Index(
        "uq_external_channel_access_grants_active_session",
        "agent_session_id",
        "principal_id",
        unique=True,
        postgresql_where=sa.text("scope = 'session' AND revoked_at IS NULL"),
    )

    id: Mapped[str] = mapped_column(
        sa.String(32),
        primary_key=True,
        init=False,
        default_factory=lambda: uuid7().hex,
    )
    agent_id: Mapped[str] = mapped_column(
        sa.String(32),
        sa.ForeignKey("agents.id", ondelete="RESTRICT"),
        nullable=False,
    )
    principal_id: Mapped[str] = mapped_column(
        sa.String(32),
        sa.ForeignKey("external_channel_principals.id", ondelete="RESTRICT"),
        nullable=False,
    )
    scope: Mapped[ExternalChannelAccessGrantScope] = mapped_column(
        external_channel_access_grant_scope_enum,
        nullable=False,
    )
    granted_by_user_id: Mapped[str] = mapped_column(
        sa.String(32),
        sa.ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=False,
    )
    agent_session_id: Mapped[str | None] = mapped_column(
        sa.String(32),
        sa.ForeignKey("agent_sessions.id", ondelete="RESTRICT"),
        nullable=True,
        default=None,
    )
    source_access_request_id: Mapped[str | None] = mapped_column(
        sa.String(32),
        sa.ForeignKey("external_channel_access_requests.id", ondelete="RESTRICT"),
        nullable=True,
        default=None,
    )
    revoked_by_user_id: Mapped[str | None] = mapped_column(
        sa.String(32),
        sa.ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=True,
        default=None,
    )
    revoked_at: Mapped[datetime.datetime | None] = mapped_column(
        TimeZoneDateTime,
        nullable=True,
        default=None,
    )
    created_at: Mapped[datetime.datetime] = mapped_column(
        TimeZoneDateTime,
        init=False,
        nullable=False,
        server_default=sa.func.now(),
    )
    updated_at: Mapped[datetime.datetime] = mapped_column(
        TimeZoneDateTime,
        init=False,
        nullable=False,
        server_default=sa.func.now(),
        onupdate=sa.func.now(),
    )

    __table_args__ = (
        CK_SCOPE_SESSION,
        IX_AGENT_ID,
        IX_AGENT_SESSION_ID,
        UQ_ACTIVE_AGENT_GRANT,
        UQ_ACTIVE_SESSION_GRANT,
    )


class RDBExternalChannelBlock(RDBModel):
    """Agent-level external principal block overriding invocation grants."""

    __tablename__ = "external_channel_blocks"

    UQ_AGENT_PRINCIPAL = sa.UniqueConstraint(
        "agent_id",
        "principal_id",
        name="uq_external_channel_blocks_agent_principal",
    )

    id: Mapped[str] = mapped_column(
        sa.String(32),
        primary_key=True,
        init=False,
        default_factory=lambda: uuid7().hex,
    )
    agent_id: Mapped[str] = mapped_column(
        sa.String(32),
        sa.ForeignKey("agents.id", ondelete="RESTRICT"),
        nullable=False,
    )
    principal_id: Mapped[str] = mapped_column(
        sa.String(32),
        sa.ForeignKey("external_channel_principals.id", ondelete="RESTRICT"),
        nullable=False,
    )
    blocked_by_user_id: Mapped[str] = mapped_column(
        sa.String(32),
        sa.ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=False,
    )
    reason: Mapped[str | None] = mapped_column(
        sa.Text,
        nullable=True,
        default=None,
    )
    removed_by_user_id: Mapped[str | None] = mapped_column(
        sa.String(32),
        sa.ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=True,
        default=None,
    )
    removed_at: Mapped[datetime.datetime | None] = mapped_column(
        TimeZoneDateTime,
        nullable=True,
        default=None,
    )
    created_at: Mapped[datetime.datetime] = mapped_column(
        TimeZoneDateTime,
        init=False,
        nullable=False,
        server_default=sa.func.now(),
    )
    updated_at: Mapped[datetime.datetime] = mapped_column(
        TimeZoneDateTime,
        init=False,
        nullable=False,
        server_default=sa.func.now(),
        onupdate=sa.func.now(),
    )

    __table_args__ = (UQ_AGENT_PRINCIPAL,)


class RDBExternalChannelWork(RDBModel):
    """Durable binding-scoped task state and desired progress projection."""

    __tablename__ = "external_channel_works"

    IX_BINDING_ID_STATUS = sa.Index(
        "ix_external_channel_works_binding_id_status",
        "binding_id",
        "status",
    )
    UQ_ACTIVE_BINDING = sa.Index(
        "uq_external_channel_works_active_binding",
        "binding_id",
        unique=True,
        postgresql_where=sa.text("status = 'active'"),
    )

    id: Mapped[str] = mapped_column(
        sa.String(32),
        primary_key=True,
        init=False,
        default_factory=lambda: uuid7().hex,
    )
    binding_id: Mapped[str] = mapped_column(
        sa.String(32),
        sa.ForeignKey("external_channel_bindings.id", ondelete="RESTRICT"),
        nullable=False,
    )
    status: Mapped[ExternalChannelWorkStatus] = mapped_column(
        external_channel_work_status_enum,
        nullable=False,
        server_default=ExternalChannelWorkStatus.ACTIVE.value,
    )
    schema_version: Mapped[int] = mapped_column(
        sa.Integer,
        nullable=False,
        server_default="1",
    )
    tasks: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, nullable=False)
    state_revision: Mapped[int] = mapped_column(
        sa.Integer,
        nullable=False,
        server_default="1",
    )
    desired_progress_revision: Mapped[int] = mapped_column(
        sa.Integer,
        nullable=False,
        server_default="0",
    )
    desired_progress_payload: Mapped[dict[str, Any] | None] = mapped_column(
        JSONB,
        nullable=True,
        default=None,
    )
    progress_provider_message_key: Mapped[str | None] = mapped_column(
        sa.String(255),
        nullable=True,
        default=None,
    )
    finished_at: Mapped[datetime.datetime | None] = mapped_column(
        TimeZoneDateTime,
        nullable=True,
        default=None,
    )
    created_at: Mapped[datetime.datetime] = mapped_column(
        TimeZoneDateTime,
        init=False,
        nullable=False,
        server_default=sa.func.now(),
    )
    updated_at: Mapped[datetime.datetime] = mapped_column(
        TimeZoneDateTime,
        init=False,
        nullable=False,
        server_default=sa.func.now(),
        onupdate=sa.func.now(),
    )

    __table_args__ = (IX_BINDING_ID_STATUS, UQ_ACTIVE_BINDING)


class RDBExternalChannelAction(RDBModel):
    """One idempotent atomic Channel Action accepted from an Agent run."""

    __tablename__ = "external_channel_actions"

    IX_BINDING_ID_CREATED_AT = sa.Index(
        "ix_external_channel_actions_binding_id_created_at",
        "binding_id",
        "created_at",
    )
    UQ_SESSION_CLIENT_TOOL_CALL = sa.UniqueConstraint(
        "agent_session_id",
        "client_tool_call_id",
        name="uq_external_channel_actions_session_client_tool_call",
    )

    id: Mapped[str] = mapped_column(
        sa.String(32),
        primary_key=True,
        init=False,
        default_factory=lambda: uuid7().hex,
    )
    agent_session_id: Mapped[str] = mapped_column(
        sa.String(32),
        sa.ForeignKey("agent_sessions.id", ondelete="RESTRICT"),
        nullable=False,
    )
    client_tool_call_id: Mapped[str] = mapped_column(sa.Text, nullable=False)
    binding_id: Mapped[str] = mapped_column(
        sa.String(32),
        sa.ForeignKey("external_channel_bindings.id", ondelete="RESTRICT"),
        nullable=False,
    )
    mode: Mapped[ExternalChannelActionMode] = mapped_column(
        external_channel_action_mode_enum,
        nullable=False,
    )
    state_revision: Mapped[int] = mapped_column(sa.Integer, nullable=False)
    request_payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    agent_run_id: Mapped[str | None] = mapped_column(
        sa.String(32),
        sa.ForeignKey("agent_runs.id", ondelete="SET NULL"),
        nullable=True,
        default=None,
    )
    work_id: Mapped[str | None] = mapped_column(
        sa.String(32),
        sa.ForeignKey("external_channel_works.id", ondelete="RESTRICT"),
        nullable=True,
        default=None,
    )
    accepted_at: Mapped[datetime.datetime] = mapped_column(
        TimeZoneDateTime,
        init=False,
        nullable=False,
        server_default=sa.func.now(),
    )
    completed_at: Mapped[datetime.datetime | None] = mapped_column(
        TimeZoneDateTime,
        nullable=True,
        default=None,
    )
    created_at: Mapped[datetime.datetime] = mapped_column(
        TimeZoneDateTime,
        init=False,
        nullable=False,
        server_default=sa.func.now(),
    )
    updated_at: Mapped[datetime.datetime] = mapped_column(
        TimeZoneDateTime,
        init=False,
        nullable=False,
        server_default=sa.func.now(),
        onupdate=sa.func.now(),
    )

    __table_args__ = (IX_BINDING_ID_CREATED_AT, UQ_SESSION_CLIENT_TOOL_CALL)


class RDBExternalChannelDeliveryAttempt(RDBModel):
    """One durable, at-most-once provider operation intent and outcome."""

    __tablename__ = "external_channel_delivery_attempts"

    IX_BINDING_ID_STATUS = sa.Index(
        "ix_external_channel_delivery_attempts_binding_id_status",
        "binding_id",
        "status",
    )
    IX_STATUS_CREATED_AT = sa.Index(
        "ix_external_channel_delivery_attempts_status_created_at",
        "status",
        "created_at",
    )
    UQ_OPERATION_WITH_BINDING = sa.Index(
        "uq_external_channel_delivery_attempts_operation_with_binding",
        "origin_type",
        "origin_id",
        "binding_id",
        "operation",
        unique=True,
        postgresql_where=sa.text("binding_id IS NOT NULL"),
    )
    UQ_OPERATION_WITHOUT_BINDING = sa.Index(
        "uq_external_channel_delivery_attempts_operation_without_binding",
        "origin_type",
        "origin_id",
        "operation",
        unique=True,
        postgresql_where=sa.text("binding_id IS NULL"),
    )

    id: Mapped[str] = mapped_column(
        sa.String(32),
        primary_key=True,
        init=False,
        default_factory=lambda: uuid7().hex,
    )
    origin_type: Mapped[ExternalChannelDeliveryOriginType] = mapped_column(
        external_channel_delivery_origin_type_enum,
        nullable=False,
    )
    origin_id: Mapped[str] = mapped_column(sa.String(32), nullable=False)
    operation: Mapped[ExternalChannelDeliveryOperation] = mapped_column(
        external_channel_delivery_operation_enum,
        nullable=False,
    )
    request_payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    status: Mapped[ExternalChannelDeliveryStatus] = mapped_column(
        external_channel_delivery_status_enum,
        nullable=False,
        server_default=ExternalChannelDeliveryStatus.PENDING.value,
    )
    channel_action_id: Mapped[str | None] = mapped_column(
        sa.String(32),
        sa.ForeignKey("external_channel_actions.id", ondelete="RESTRICT"),
        nullable=True,
        default=None,
    )
    binding_id: Mapped[str | None] = mapped_column(
        sa.String(32),
        sa.ForeignKey("external_channel_bindings.id", ondelete="RESTRICT"),
        nullable=True,
        default=None,
    )
    provider_message_key: Mapped[str | None] = mapped_column(
        sa.String(255),
        nullable=True,
        default=None,
    )
    error_kind: Mapped[str | None] = mapped_column(
        sa.String(120),
        nullable=True,
        default=None,
    )
    error_summary: Mapped[str | None] = mapped_column(
        sa.Text,
        nullable=True,
        default=None,
    )
    attempted_at: Mapped[datetime.datetime | None] = mapped_column(
        TimeZoneDateTime,
        nullable=True,
        default=None,
    )
    completed_at: Mapped[datetime.datetime | None] = mapped_column(
        TimeZoneDateTime,
        nullable=True,
        default=None,
    )
    created_at: Mapped[datetime.datetime] = mapped_column(
        TimeZoneDateTime,
        init=False,
        nullable=False,
        server_default=sa.func.now(),
    )
    updated_at: Mapped[datetime.datetime] = mapped_column(
        TimeZoneDateTime,
        init=False,
        nullable=False,
        server_default=sa.func.now(),
        onupdate=sa.func.now(),
    )

    __table_args__ = (
        IX_BINDING_ID_STATUS,
        IX_STATUS_CREATED_AT,
        UQ_OPERATION_WITH_BINDING,
        UQ_OPERATION_WITHOUT_BINDING,
    )
