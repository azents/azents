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
    ExternalChannelAppMode,
    ExternalChannelChannelDefaultStatus,
    ExternalChannelConnectionStatus,
    ExternalChannelConversationLocation,
    ExternalChannelConversationScopeKind,
    ExternalChannelIngressProfile,
    ExternalChannelInteractionStatus,
    ExternalChannelInteractionType,
    ExternalChannelParticipationSettingStatus,
    ExternalChannelPrincipalAuthorType,
    ExternalChannelProvider,
    ExternalChannelResourceStatus,
    ExternalChannelResourceType,
    ExternalChannelResponseMode,
    ExternalChannelRouteCatalogStatus,
    ExternalChannelRouteMode,
    ExternalChannelSetupClaimStatus,
    ExternalChannelTransport,
    ExternalChannelWorkProjectionStatus,
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
external_channel_ingress_profile_enum = ENUM(
    ExternalChannelIngressProfile,
    name="external_channel_ingress_profile",
    create_type=False,
    values_callable=_enum_values,
)
external_channel_connection_status_enum = ENUM(
    ExternalChannelConnectionStatus,
    name="external_channel_connection_status",
    create_type=False,
    values_callable=_enum_values,
)
external_channel_conversation_scope_kind_enum = ENUM(
    ExternalChannelConversationScopeKind,
    name="external_channel_conversation_scope_kind",
    create_type=False,
    values_callable=_enum_values,
)
external_channel_app_mode_enum = ENUM(
    ExternalChannelAppMode,
    name="external_channel_app_mode",
    create_type=False,
    values_callable=_enum_values,
)
external_channel_route_mode_enum = ENUM(
    ExternalChannelRouteMode,
    name="external_channel_route_mode",
    create_type=False,
    values_callable=_enum_values,
)
external_channel_response_mode_enum = ENUM(
    ExternalChannelResponseMode,
    name="external_channel_response_mode",
    create_type=False,
    values_callable=_enum_values,
)
external_channel_conversation_location_enum = ENUM(
    ExternalChannelConversationLocation,
    name="external_channel_conversation_location",
    create_type=False,
    values_callable=_enum_values,
)
external_channel_route_catalog_status_enum = ENUM(
    ExternalChannelRouteCatalogStatus,
    name="external_channel_route_catalog_status",
    create_type=False,
    values_callable=_enum_values,
)
external_channel_interaction_type_enum = ENUM(
    ExternalChannelInteractionType,
    name="external_channel_interaction_type",
    create_type=False,
    values_callable=_enum_values,
)
external_channel_interaction_status_enum = ENUM(
    ExternalChannelInteractionStatus,
    name="external_channel_interaction_status",
    create_type=False,
    values_callable=_enum_values,
)
external_channel_channel_default_status_enum = ENUM(
    ExternalChannelChannelDefaultStatus,
    name="external_channel_channel_default_status",
    create_type=False,
    values_callable=_enum_values,
)
external_channel_participation_setting_status_enum = ENUM(
    ExternalChannelParticipationSettingStatus,
    name="external_channel_participation_setting_status",
    create_type=False,
    values_callable=_enum_values,
)
external_channel_setup_claim_status_enum = ENUM(
    ExternalChannelSetupClaimStatus,
    name="external_channel_setup_claim_status",
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
external_channel_principal_author_type_enum = ENUM(
    ExternalChannelPrincipalAuthorType,
    name="external_channel_principal_author_type",
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
external_channel_work_projection_status_enum = ENUM(
    ExternalChannelWorkProjectionStatus,
    name="external_channel_work_projection_status",
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
    UQ_ID_APP_MODE = sa.UniqueConstraint(
        "id",
        "app_mode",
        name="uq_external_channel_connections_id_app_mode",
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
    app_mode: Mapped[ExternalChannelAppMode] = mapped_column(
        external_channel_app_mode_enum,
        nullable=False,
        server_default=ExternalChannelAppMode.SINGLE.value,
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
    last_health_code: Mapped[str | None] = mapped_column(
        sa.String(64),
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
    ingress_profile: Mapped[ExternalChannelIngressProfile] = mapped_column(
        external_channel_ingress_profile_enum,
        nullable=False,
        default=ExternalChannelIngressProfile.SLACK_HTTP,
        server_default=ExternalChannelIngressProfile.SLACK_HTTP.value,
    )
    configuration_generation: Mapped[int] = mapped_column(
        sa.Integer,
        nullable=False,
        default=1,
        server_default="1",
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
        UQ_ID_APP_MODE,
    )


class RDBExternalChannelAppClaim(RDBModel):
    """Current provider App ownership independent from disconnected history."""

    __tablename__ = "external_channel_app_claims"

    UQ_PROVIDER_APP_ID = sa.UniqueConstraint(
        "provider",
        "provider_app_id",
        name="uq_external_channel_app_claims_provider_app_id",
    )
    IX_CONNECTION_ID = sa.Index(
        "ix_external_channel_app_claims_connection_id",
        "connection_id",
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
    provider_app_id: Mapped[str] = mapped_column(sa.String(255), nullable=False)
    connection_id: Mapped[str] = mapped_column(
        sa.String(32),
        sa.ForeignKey("external_channel_connections.id", ondelete="RESTRICT"),
        nullable=False,
    )
    claim_generation: Mapped[int] = mapped_column(
        sa.Integer,
        nullable=False,
        default=1,
        server_default="1",
    )
    acquired_at: Mapped[datetime.datetime] = mapped_column(
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

    __table_args__ = (UQ_PROVIDER_APP_ID, IX_CONNECTION_ID)


class RDBExternalChannelIngressLease(RDBModel):
    """Provider-neutral leased ingress ownership and resumable checkpoint."""

    __tablename__ = "external_channel_ingress_leases"

    UQ_CONNECTION_ID = sa.UniqueConstraint(
        "connection_id",
        name="uq_external_channel_ingress_leases_connection_id",
    )
    IX_LEASE_UNTIL = sa.Index(
        "ix_external_channel_ingress_leases_lease_until",
        "lease_until",
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
    lease_owner: Mapped[str | None] = mapped_column(
        sa.String(255),
        nullable=True,
        default=None,
    )
    lease_generation: Mapped[int] = mapped_column(
        sa.Integer,
        nullable=False,
        default=0,
        server_default="0",
    )
    lease_until: Mapped[datetime.datetime | None] = mapped_column(
        TimeZoneDateTime,
        nullable=True,
        default=None,
    )
    heartbeat_at: Mapped[datetime.datetime | None] = mapped_column(
        TimeZoneDateTime,
        nullable=True,
        default=None,
    )
    required_configuration_generation: Mapped[int | None] = mapped_column(
        sa.Integer,
        nullable=True,
        default=None,
    )
    required_app_claim_generation: Mapped[int | None] = mapped_column(
        sa.Integer,
        nullable=True,
        default=None,
    )
    gap_detected_at: Mapped[datetime.datetime | None] = mapped_column(
        TimeZoneDateTime,
        nullable=True,
        default=None,
    )
    gap_reason: Mapped[str | None] = mapped_column(
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

    __table_args__ = (UQ_CONNECTION_ID, IX_LEASE_UNTIL)


class RDBExternalChannelConversationPosition(RDBModel):
    """Durable provider-history read position for one conversation scope."""

    __tablename__ = "external_channel_conversation_positions"

    UQ_CONNECTION_ID_ID = sa.UniqueConstraint(
        "connection_id",
        "id",
        name="uq_external_channel_conversation_positions_connection_id_id",
    )
    UQ_CONNECTION_PARENT = sa.Index(
        "uq_external_channel_conversation_positions_parent",
        "connection_id",
        "provider_channel_id",
        unique=True,
        postgresql_where=sa.text("scope_kind = 'parent_channel'"),
    )
    UQ_CONNECTION_THREAD = sa.Index(
        "uq_external_channel_conversation_positions_thread",
        "connection_id",
        "provider_channel_id",
        "provider_thread_key",
        unique=True,
        postgresql_where=sa.text("scope_kind = 'thread'"),
    )
    CK_SCOPE_KEY = sa.CheckConstraint(
        "(scope_kind = 'parent_channel' AND provider_thread_key IS NULL) OR "
        "(scope_kind = 'thread' AND provider_thread_key IS NOT NULL)",
        name="ck_external_channel_conversation_positions_scope_key",
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
    scope_kind: Mapped[ExternalChannelConversationScopeKind] = mapped_column(
        external_channel_conversation_scope_kind_enum,
        nullable=False,
    )
    provider_channel_id: Mapped[str] = mapped_column(sa.Text, nullable=False)
    provider_thread_key: Mapped[str | None] = mapped_column(
        sa.Text,
        nullable=True,
        default=None,
    )
    read_through_position: Mapped[str | None] = mapped_column(
        sa.Text,
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
        UQ_CONNECTION_ID_ID,
        UQ_CONNECTION_PARENT,
        UQ_CONNECTION_THREAD,
        CK_SCOPE_KEY,
    )


class RDBExternalChannelAgentRoute(RDBModel):
    """Persistent relationship between one Agent and provider connection."""

    __tablename__ = "external_channel_agent_routes"

    IX_AGENT_ID = sa.Index("ix_external_channel_agent_routes_agent_id", "agent_id")
    IX_CONNECTION_ID = sa.Index(
        "ix_external_channel_agent_routes_connection_id",
        "connection_id",
    )
    UQ_CONNECTION_AGENT = sa.UniqueConstraint(
        "connection_id",
        "agent_id_snapshot",
        name="uq_external_channel_agent_routes_connection_agent",
    )
    UQ_CONNECTION_ID_ID = sa.UniqueConstraint(
        "connection_id",
        "id",
        name="uq_external_channel_agent_routes_connection_id_id",
    )
    UQ_SINGLE_CONNECTION = sa.Index(
        "uq_external_channel_agent_routes_single_connection",
        "connection_id",
        unique=True,
        postgresql_where=sa.text("connection_app_mode = 'single'"),
    )
    FK_CONNECTION_APP_MODE = sa.ForeignKeyConstraint(
        ["connection_id", "connection_app_mode"],
        ["external_channel_connections.id", "external_channel_connections.app_mode"],
        name="fk_external_channel_agent_routes_connection_app_mode",
        ondelete="RESTRICT",
    )
    CK_AVAILABLE_AGENT = sa.CheckConstraint(
        "catalog_status = 'removed' OR agent_id IS NOT NULL",
        name="ck_external_channel_agent_routes_available_agent",
    )
    CK_AGENT_SNAPSHOT = sa.CheckConstraint(
        "agent_id IS NULL OR agent_id = agent_id_snapshot",
        name="ck_external_channel_agent_routes_agent_snapshot",
    )

    id: Mapped[str] = mapped_column(
        sa.String(32),
        primary_key=True,
        init=False,
        default_factory=lambda: uuid7().hex,
    )
    connection_id: Mapped[str] = mapped_column(sa.String(32), nullable=False)
    agent_id: Mapped[str | None] = mapped_column(
        sa.String(32),
        sa.ForeignKey(
            "agents.id",
            name="external_channel_agent_routes_agent_id_fkey",
            ondelete="SET NULL",
        ),
        nullable=True,
    )
    agent_id_snapshot: Mapped[str] = mapped_column(sa.String(32), nullable=False)
    route_mode: Mapped[ExternalChannelRouteMode] = mapped_column(
        external_channel_route_mode_enum,
        nullable=False,
        server_default=ExternalChannelRouteMode.DEDICATED.value,
    )
    connection_app_mode: Mapped[ExternalChannelAppMode] = mapped_column(
        external_channel_app_mode_enum,
        nullable=False,
        server_default=ExternalChannelAppMode.SINGLE.value,
    )
    catalog_status: Mapped[ExternalChannelRouteCatalogStatus] = mapped_column(
        external_channel_route_catalog_status_enum,
        nullable=False,
        server_default=ExternalChannelRouteCatalogStatus.AVAILABLE.value,
    )
    catalog_removed_at: Mapped[datetime.datetime | None] = mapped_column(
        TimeZoneDateTime,
        nullable=True,
        default=None,
    )
    catalog_removed_by_user_id: Mapped[str | None] = mapped_column(
        sa.String(32),
        sa.ForeignKey(
            "users.id",
            name="external_channel_agent_routes_catalog_removed_by_user_id_fkey",
            ondelete="RESTRICT",
        ),
        nullable=True,
        default=None,
    )
    open_access_enabled: Mapped[bool] = mapped_column(
        sa.Boolean,
        nullable=False,
        default=True,
        server_default=sa.true(),
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
        UQ_CONNECTION_AGENT,
        UQ_CONNECTION_ID_ID,
        UQ_SINGLE_CONNECTION,
        FK_CONNECTION_APP_MODE,
        CK_AVAILABLE_AGENT,
        CK_AGENT_SNAPSHOT,
    )


class RDBExternalChannelInteraction(RDBModel):
    """Durable, bounded provider interaction admission."""

    __tablename__ = "external_channel_interactions"

    UQ_CONNECTION_PROVIDER_INTERACTION_KEY = sa.UniqueConstraint(
        "connection_id",
        "provider_interaction_key",
        name="uq_external_channel_interactions_connection_provider_key",
    )
    UQ_CONNECTION_ID_ID = sa.UniqueConstraint(
        "connection_id",
        "id",
        name="uq_external_channel_interactions_connection_id_id",
    )
    IX_EXPIRES_AT = sa.Index(
        "ix_external_channel_interactions_expires_at",
        "expires_at",
    )
    IX_SETUP_CLAIM_ID = sa.Index(
        "ix_external_channel_interactions_setup_claim_id",
        "setup_claim_id",
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
    transport: Mapped[ExternalChannelTransport] = mapped_column(
        external_channel_transport_enum,
        nullable=False,
    )
    provider_interaction_key: Mapped[str] = mapped_column(
        sa.String(128), nullable=False
    )
    interaction_type: Mapped[ExternalChannelInteractionType] = mapped_column(
        external_channel_interaction_type_enum,
        nullable=False,
    )
    projection: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    status: Mapped[ExternalChannelInteractionStatus] = mapped_column(
        external_channel_interaction_status_enum,
        nullable=False,
        server_default=ExternalChannelInteractionStatus.ACCEPTED.value,
    )
    expires_at: Mapped[datetime.datetime] = mapped_column(
        TimeZoneDateTime, nullable=False
    )
    callback_id: Mapped[str | None] = mapped_column(
        sa.String(255),
        nullable=True,
        default=None,
    )
    action_id: Mapped[str | None] = mapped_column(
        sa.String(255),
        nullable=True,
        default=None,
    )
    principal_id: Mapped[str | None] = mapped_column(
        sa.String(32),
        sa.ForeignKey("external_channel_principals.id", ondelete="RESTRICT"),
        nullable=True,
        default=None,
    )
    setup_claim_id: Mapped[str | None] = mapped_column(
        sa.String(32),
        sa.ForeignKey("external_channel_setup_claims.id", ondelete="RESTRICT"),
        nullable=True,
        default=None,
    )
    resource_correlation_key: Mapped[str | None] = mapped_column(
        sa.String(512),
        nullable=True,
        default=None,
    )
    error_kind: Mapped[str | None] = mapped_column(
        sa.String(120),
        nullable=True,
        default=None,
    )
    error_summary: Mapped[str | None] = mapped_column(
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
        UQ_CONNECTION_PROVIDER_INTERACTION_KEY,
        UQ_CONNECTION_ID_ID,
        IX_EXPIRES_AT,
        IX_SETUP_CLAIM_ID,
    )


class RDBExternalChannelChannelDefault(RDBModel):
    """Durable route default for one provider channel in a Multi App."""

    __tablename__ = "external_channel_channel_defaults"

    UQ_ACTIVE_CONNECTION_CHANNEL = sa.Index(
        "uq_external_channel_channel_defaults_active_connection_channel",
        "connection_id",
        "provider_channel_id",
        unique=True,
        postgresql_where=sa.text("status = 'active'"),
    )
    IX_ROUTE_ID_STATUS = sa.Index(
        "ix_external_channel_channel_defaults_route_id_status",
        "route_id",
        "status",
    )
    FK_CONNECTION_ROUTE = sa.ForeignKeyConstraint(
        ["connection_id", "route_id"],
        [
            "external_channel_agent_routes.connection_id",
            "external_channel_agent_routes.id",
        ],
        name="fk_external_channel_channel_defaults_connection_route",
        ondelete="RESTRICT",
    )
    CK_CONFIGURED_ACTOR = sa.CheckConstraint(
        "num_nonnulls(configured_by_user_id, configured_by_principal_id) = 1",
        name="ck_external_channel_channel_defaults_configured_actor",
    )

    id: Mapped[str] = mapped_column(
        sa.String(32),
        primary_key=True,
        init=False,
        default_factory=lambda: uuid7().hex,
    )
    connection_id: Mapped[str] = mapped_column(sa.String(32), nullable=False)
    provider_channel_id: Mapped[str] = mapped_column(sa.String(255), nullable=False)
    route_id: Mapped[str] = mapped_column(sa.String(32), nullable=False)
    status: Mapped[ExternalChannelChannelDefaultStatus] = mapped_column(
        external_channel_channel_default_status_enum,
        nullable=False,
        server_default=ExternalChannelChannelDefaultStatus.ACTIVE.value,
    )
    configured_by_user_id: Mapped[str | None] = mapped_column(
        sa.String(32),
        sa.ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=True,
        default=None,
    )
    configured_by_principal_id: Mapped[str | None] = mapped_column(
        sa.String(32),
        sa.ForeignKey("external_channel_principals.id", ondelete="RESTRICT"),
        nullable=True,
        default=None,
    )
    invalidated_at: Mapped[datetime.datetime | None] = mapped_column(
        TimeZoneDateTime,
        nullable=True,
        default=None,
    )
    invalidation_reason: Mapped[str | None] = mapped_column(
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
        UQ_ACTIVE_CONNECTION_CHANNEL,
        IX_ROUTE_ID_STATUS,
        FK_CONNECTION_ROUTE,
        CK_CONFIGURED_ACTOR,
    )


class RDBExternalChannelParticipationSetting(RDBModel):
    """Selected parent-channel conversation behavior for one connection."""

    __tablename__ = "external_channel_participation_settings"

    UQ_CONNECTION_ID_ID = sa.UniqueConstraint(
        "connection_id",
        "id",
        name="uq_external_channel_participation_settings_connection_id_id",
    )
    UQ_ACTIVE_CONNECTION_CHANNEL = sa.Index(
        "uq_external_channel_participation_active_channel",
        "connection_id",
        "provider_parent_channel_id",
        unique=True,
        postgresql_where=sa.text("status = 'active'"),
    )
    IX_ROUTE_ID_STATUS = sa.Index(
        "ix_external_channel_participation_settings_route_id_status",
        "route_id",
        "status",
    )
    FK_CONNECTION_ROUTE = sa.ForeignKeyConstraint(
        ["connection_id", "route_id"],
        [
            "external_channel_agent_routes.connection_id",
            "external_channel_agent_routes.id",
        ],
        name="fk_external_channel_participation_settings_connection_route",
        ondelete="RESTRICT",
    )
    CK_CONFIGURED_ACTOR = sa.CheckConstraint(
        "num_nonnulls(configured_by_user_id, configured_by_principal_id) = 1",
        name="ck_external_channel_participation_settings_configured_actor",
    )
    CK_POSITIVE_GENERATION = sa.CheckConstraint(
        "settings_generation > 0",
        name="ck_external_channel_participation_settings_positive_generation",
    )
    CK_INVALIDATION_METADATA = sa.CheckConstraint(
        "(status = 'active' AND invalidated_at IS NULL "
        "AND invalidation_reason IS NULL) OR "
        "(status = 'invalidated' AND invalidated_at IS NOT NULL "
        "AND invalidation_reason IS NOT NULL)",
        name="ck_external_channel_participation_invalidation_metadata",
    )

    id: Mapped[str] = mapped_column(
        sa.String(32),
        primary_key=True,
        init=False,
        default_factory=lambda: uuid7().hex,
    )
    connection_id: Mapped[str] = mapped_column(sa.String(32), nullable=False)
    provider_parent_channel_id: Mapped[str] = mapped_column(
        sa.String(255),
        nullable=False,
    )
    route_id: Mapped[str] = mapped_column(sa.String(32), nullable=False)
    location: Mapped[ExternalChannelConversationLocation] = mapped_column(
        external_channel_conversation_location_enum,
        nullable=False,
    )
    response_mode: Mapped[ExternalChannelResponseMode] = mapped_column(
        external_channel_response_mode_enum,
        nullable=False,
    )
    settings_generation: Mapped[int] = mapped_column(sa.Integer, nullable=False)
    status: Mapped[ExternalChannelParticipationSettingStatus] = mapped_column(
        external_channel_participation_setting_status_enum,
        nullable=False,
    )
    configured_by_user_id: Mapped[str | None] = mapped_column(
        sa.String(32),
        sa.ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=True,
        default=None,
    )
    configured_by_principal_id: Mapped[str | None] = mapped_column(
        sa.String(32),
        sa.ForeignKey("external_channel_principals.id", ondelete="RESTRICT"),
        nullable=True,
        default=None,
    )
    invalidated_at: Mapped[datetime.datetime | None] = mapped_column(
        TimeZoneDateTime,
        nullable=True,
        default=None,
    )
    invalidation_reason: Mapped[str | None] = mapped_column(
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
        UQ_CONNECTION_ID_ID,
        UQ_ACTIVE_CONNECTION_CHANNEL,
        IX_ROUTE_ID_STATUS,
        FK_CONNECTION_ROUTE,
        CK_CONFIGURED_ACTOR,
        CK_POSITIVE_GENERATION,
        CK_INVALIDATION_METADATA,
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
    UQ_CONNECTION_ID_ID = sa.UniqueConstraint(
        "connection_id",
        "id",
        name="uq_external_channel_resources_connection_id_id",
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
        UQ_CONNECTION_ID_ID,
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


class RDBExternalChannelSetupClaim(RDBModel):
    """Latest eligible setup continuation before canonical Session admission."""

    __tablename__ = "external_channel_setup_claims"

    UQ_CONNECTION_ID_ID = sa.UniqueConstraint(
        "connection_id",
        "id",
        name="uq_external_channel_setup_claims_connection_id_id",
    )
    UQ_NONTERMINAL_CONNECTION_CHANNEL = sa.Index(
        "uq_external_channel_setup_claims_nonterminal_connection_channel",
        "connection_id",
        "provider_parent_channel_id",
        unique=True,
        postgresql_where=sa.text(
            "status IN ('pending_agent', 'pending_location', 'selected')"
        ),
    )
    IX_ROUTE_ID_STATUS = sa.Index(
        "ix_external_channel_setup_claims_route_id_status",
        "route_id",
        "status",
    )
    IX_STATUS_EXPIRES_AT = sa.Index(
        "ix_external_channel_setup_claims_status_expires_at",
        "status",
        "expires_at",
    )
    FK_CONNECTION_ROUTE = sa.ForeignKeyConstraint(
        ["connection_id", "route_id"],
        [
            "external_channel_agent_routes.connection_id",
            "external_channel_agent_routes.id",
        ],
        name="fk_external_channel_setup_claims_connection_route",
        ondelete="RESTRICT",
    )
    FK_CONNECTION_POSITION = sa.ForeignKeyConstraint(
        ["connection_id", "conversation_position_id"],
        [
            "external_channel_conversation_positions.connection_id",
            "external_channel_conversation_positions.id",
        ],
        name="fk_external_channel_setup_claims_connection_position",
        ondelete="RESTRICT",
    )
    FK_CONNECTION_SOURCE_RESOURCE = sa.ForeignKeyConstraint(
        ["connection_id", "source_resource_id"],
        [
            "external_channel_resources.connection_id",
            "external_channel_resources.id",
        ],
        name="fk_external_channel_setup_claims_connection_source_resource",
        ondelete="RESTRICT",
    )
    FK_CONNECTION_SELECTED_SETTING = sa.ForeignKeyConstraint(
        ["connection_id", "selected_setting_id"],
        [
            "external_channel_participation_settings.connection_id",
            "external_channel_participation_settings.id",
        ],
        name="fk_external_channel_setup_claims_connection_selected_setting",
        ondelete="RESTRICT",
    )
    FK_CONNECTION_SELECTED_RESOURCE = sa.ForeignKeyConstraint(
        ["connection_id", "selected_resource_id"],
        [
            "external_channel_resources.connection_id",
            "external_channel_resources.id",
        ],
        name="fk_external_channel_setup_claims_connection_selected_resource",
        ondelete="RESTRICT",
    )
    CK_POSITIVE_REVISIONS = sa.CheckConstraint(
        "source_revision > 0 AND claim_generation > 0",
        name="ck_external_channel_setup_claims_positive_revisions",
    )
    CK_SELECTED_SOURCE_REVISION = sa.CheckConstraint(
        "selected_source_revision IS NULL "
        "OR (selected_source_revision > 0 "
        "AND selected_source_revision <= source_revision)",
        name="ck_external_channel_setup_claims_selected_source_revision",
    )
    CK_SELECTION_METADATA = sa.CheckConstraint(
        "(status IN ('pending_agent', 'pending_location') "
        "AND selected_setting_id IS NULL "
        "AND selected_resource_id IS NULL "
        "AND selected_source_revision IS NULL "
        "AND selected_at IS NULL) OR "
        "(status IN ('selected', 'completed') "
        "AND selected_setting_id IS NOT NULL "
        "AND selected_resource_id IS NOT NULL "
        "AND selected_source_revision IS NOT NULL "
        "AND selected_at IS NOT NULL) OR "
        "status IN ('expired', 'invalidated')",
        name="ck_external_channel_setup_claims_selection_metadata",
    )
    CK_COMPLETED_AT = sa.CheckConstraint(
        "(status = 'completed' AND completed_at IS NOT NULL) OR status <> 'completed'",
        name="ck_external_channel_setup_claims_completed_at",
    )

    id: Mapped[str] = mapped_column(
        sa.String(32),
        primary_key=True,
        init=False,
        default_factory=lambda: uuid7().hex,
    )
    connection_id: Mapped[str] = mapped_column(sa.String(32), nullable=False)
    provider_parent_channel_id: Mapped[str] = mapped_column(
        sa.String(255),
        nullable=False,
    )
    route_id: Mapped[str | None] = mapped_column(sa.String(32), nullable=True)
    conversation_position_id: Mapped[str] = mapped_column(
        sa.String(32),
        nullable=False,
    )
    source_resource_id: Mapped[str] = mapped_column(sa.String(32), nullable=False)
    principal_id: Mapped[str] = mapped_column(
        sa.String(32),
        sa.ForeignKey("external_channel_principals.id", ondelete="RESTRICT"),
        nullable=False,
    )
    source_projection: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    source_revision: Mapped[int] = mapped_column(sa.Integer, nullable=False)
    claim_generation: Mapped[int] = mapped_column(sa.Integer, nullable=False)
    status: Mapped[ExternalChannelSetupClaimStatus] = mapped_column(
        external_channel_setup_claim_status_enum,
        nullable=False,
    )
    selected_setting_id: Mapped[str | None] = mapped_column(
        sa.String(32),
        nullable=True,
    )
    selected_resource_id: Mapped[str | None] = mapped_column(
        sa.String(32),
        nullable=True,
    )
    selected_source_revision: Mapped[int | None] = mapped_column(
        sa.Integer,
        nullable=True,
    )
    expires_at: Mapped[datetime.datetime] = mapped_column(
        TimeZoneDateTime,
        nullable=False,
    )
    selected_at: Mapped[datetime.datetime | None] = mapped_column(
        TimeZoneDateTime,
        nullable=True,
    )
    completed_at: Mapped[datetime.datetime | None] = mapped_column(
        TimeZoneDateTime,
        nullable=True,
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
        UQ_CONNECTION_ID_ID,
        UQ_NONTERMINAL_CONNECTION_CHANNEL,
        IX_ROUTE_ID_STATUS,
        IX_STATUS_EXPIRES_AT,
        FK_CONNECTION_ROUTE,
        FK_CONNECTION_POSITION,
        FK_CONNECTION_SOURCE_RESOURCE,
        FK_CONNECTION_SELECTED_SETTING,
        FK_CONNECTION_SELECTED_RESOURCE,
        CK_POSITIVE_REVISIONS,
        CK_SELECTED_SOURCE_REVISION,
        CK_SELECTION_METADATA,
        CK_COMPLETED_AT,
    )


class RDBExternalChannelBinding(RDBModel):
    """Lifecycle-owned link between one external resource and AgentSession."""

    __tablename__ = "external_channel_bindings"

    IX_AGENT_SESSION_ID = sa.Index(
        "ix_external_channel_bindings_agent_session_id",
        "agent_session_id",
    )
    IX_ROUTE_ID = sa.Index(
        "ix_external_channel_bindings_route_id",
        "route_id",
    )
    UQ_CONNECTED_RESOURCE = sa.Index(
        "uq_external_channel_bindings_connected_resource",
        "resource_id",
        unique=True,
        postgresql_where=sa.text("disconnected_at IS NULL"),
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
    response_mode: Mapped[ExternalChannelResponseMode] = mapped_column(
        external_channel_response_mode_enum,
        nullable=False,
        server_default=ExternalChannelResponseMode.ALL_MESSAGES.value,
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
        IX_AGENT_SESSION_ID,
        IX_ROUTE_ID,
        UQ_CONNECTED_RESOURCE,
    )


class RDBExternalChannelAccessRequest(RDBModel):
    """Durable request to authorize one external principal invocation."""

    __tablename__ = "external_channel_access_requests"

    CK_PENDING_BOUNDARY = sa.CheckConstraint(
        "status <> 'pending' OR "
        "(connection_id IS NOT NULL AND conversation_position_id IS NOT NULL "
        "AND trigger_position IS NOT NULL)",
        name="ck_external_channel_access_requests_pending_boundary",
    )
    IX_STATUS_CREATED_AT = sa.Index(
        "ix_external_channel_access_requests_status_created_at",
        "status",
        "created_at",
    )
    IX_AGENT_SESSION_ID = sa.Index(
        "ix_external_channel_access_requests_agent_session_id",
        "agent_session_id",
    )
    IX_SETUP_CLAIM_ID = sa.Index(
        "ix_external_channel_access_requests_setup_claim_id",
        "setup_claim_id",
    )
    UQ_ROUTE_TRIGGER_MESSAGE = sa.UniqueConstraint(
        "route_id",
        "trigger_provider_message_key",
        name="uq_external_channel_access_requests_route_trigger_message",
    )
    FK_CONNECTION_RESOURCE = sa.ForeignKeyConstraint(
        ["connection_id", "resource_id"],
        [
            "external_channel_resources.connection_id",
            "external_channel_resources.id",
        ],
        name="fk_external_channel_access_requests_connection_resource",
        ondelete="RESTRICT",
    )
    FK_CONNECTION_POSITION = sa.ForeignKeyConstraint(
        ["connection_id", "conversation_position_id"],
        [
            "external_channel_conversation_positions.connection_id",
            "external_channel_conversation_positions.id",
        ],
        name="fk_external_channel_access_requests_connection_position",
        ondelete="RESTRICT",
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
    trigger_provider_message_key: Mapped[str] = mapped_column(
        sa.Text,
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
    connection_id: Mapped[str | None] = mapped_column(
        sa.String(32),
        nullable=True,
        default=None,
    )
    conversation_position_id: Mapped[str | None] = mapped_column(
        sa.String(32),
        nullable=True,
        default=None,
    )
    range_start_position: Mapped[str | None] = mapped_column(
        sa.Text,
        nullable=True,
        default=None,
    )
    trigger_position: Mapped[str | None] = mapped_column(
        sa.Text,
        nullable=True,
        default=None,
    )
    agent_session_id: Mapped[str | None] = mapped_column(
        sa.String(32),
        sa.ForeignKey("agent_sessions.id", ondelete="RESTRICT"),
        nullable=True,
        default=None,
    )
    setup_claim_id: Mapped[str | None] = mapped_column(
        sa.String(32),
        sa.ForeignKey("external_channel_setup_claims.id", ondelete="RESTRICT"),
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
    control_provider_message_key: Mapped[str | None] = mapped_column(
        sa.String(255),
        nullable=True,
        default=None,
    )
    control_projection_status: Mapped[ExternalChannelWorkProjectionStatus | None] = (
        mapped_column(
            external_channel_work_projection_status_enum,
            nullable=True,
            default=None,
        )
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
        CK_PENDING_BOUNDARY,
        IX_STATUS_CREATED_AT,
        IX_AGENT_SESSION_ID,
        IX_SETUP_CLAIM_ID,
        UQ_ROUTE_TRIGGER_MESSAGE,
        FK_CONNECTION_RESOURCE,
        FK_CONNECTION_POSITION,
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
