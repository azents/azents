"""Safe External Channel management repository projections."""

import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict

from azents.core.enums import (
    ExternalChannelAccessGrantScope,
    ExternalChannelAccessRequestStatus,
    ExternalChannelAppMode,
    ExternalChannelChannelDefaultStatus,
    ExternalChannelConnectionStatus,
    ExternalChannelConversationLocation,
    ExternalChannelProvider,
    ExternalChannelResourceType,
    ExternalChannelResponseMode,
    ExternalChannelRouteCatalogStatus,
    ExternalChannelTransport,
    ExternalChannelWorkStatus,
    ExternalChannelWorkTaskStatus,
)


class _Projection(BaseModel):
    model_config = ConfigDict(frozen=True)


class ManagedConnection(_Projection):
    id: str
    route_id: str
    agent_id: str
    provider: ExternalChannelProvider
    transport: ExternalChannelTransport
    status: ExternalChannelConnectionStatus
    provider_app_id: str | None
    provider_tenant_id: str | None
    provider_bot_user_id: str | None
    open_access_enabled: bool
    credentials_configured: bool
    capabilities: dict[str, Any] | None
    provider_config: dict[str, Any] | None
    last_verified_at: datetime.datetime | None
    last_health_at: datetime.datetime | None
    last_health_code: str | None = None
    socket_gap_detected_at: datetime.datetime | None
    socket_gap_reason: str | None
    disconnected_at: datetime.datetime | None


class ManagedMultiConnection(_Projection):
    """Redacted Workspace-owned Multi App connection projection."""

    id: str
    provider: ExternalChannelProvider
    transport: ExternalChannelTransport
    app_mode: ExternalChannelAppMode
    status: ExternalChannelConnectionStatus
    provider_app_id: str | None
    provider_tenant_id: str | None
    provider_bot_user_id: str | None
    credentials_configured: bool
    capabilities: dict[str, Any] | None
    provider_config: dict[str, Any] | None
    last_verified_at: datetime.datetime | None
    last_health_at: datetime.datetime | None
    last_health_code: str | None = None
    socket_gap_detected_at: datetime.datetime | None
    socket_gap_reason: str | None
    disconnected_at: datetime.datetime | None
    generation: datetime.datetime
    active_agent_count: int
    configured_default_count: int


class ManagedMultiRoute(_Projection):
    """One Multi App Agent catalog relationship."""

    id: str
    agent_id: str | None
    agent_id_snapshot: str
    agent_name: str | None
    catalog_status: ExternalChannelRouteCatalogStatus
    catalog_removed_at: datetime.datetime | None
    created_at: datetime.datetime
    updated_at: datetime.datetime


class ManagedChannelDefault(_Projection):
    """One redacted Multi App channel default."""

    id: str
    provider_channel_id: str
    route_id: str
    agent_id: str | None
    agent_name: str | None
    status: ExternalChannelChannelDefaultStatus
    configured_by_user_id: str | None
    configured_by_principal_id: str | None
    invalidated_at: datetime.datetime | None
    invalidation_reason: str | None
    created_at: datetime.datetime
    updated_at: datetime.datetime


class ManagedChannelDefaultMutation(_Projection):
    """Sanitized selected-Agent mutation result and terminal lifecycle impact."""

    channel_default: ManagedChannelDefault | None
    changed: bool
    invalidated_participation_setting_count: int
    terminated_setup_claim_count: int
    expired_interaction_count: int
    disconnected_parent_binding_count: int
    direct_cleanup_count: int


class ManagedSlackManagementHandoff(_Projection):
    """Authenticated resolution of an opaque Slack management callback."""

    interaction_id: str
    connection_id: str
    provider: ExternalChannelProvider
    provider_app_id: str | None
    provider_channel_id: str
    provider_thread_id: str | None
    expires_at: datetime.datetime


class ManagedMultiConnectionDisconnect(_Projection):
    """Sanitized terminal Multi App disconnect summary."""

    disconnected_route_count: int
    invalidated_default_count: int
    invalidated_participation_setting_count: int
    terminated_setup_claim_count: int
    expired_admission_count: int
    expired_access_request_count: int
    unavailable_resource_count: int
    disconnected_binding_count: int


class ManagedWorkSource(_Projection):
    url: str
    label: str


class ManagedWorkTask(_Projection):
    id: str
    title: str
    status: ExternalChannelWorkTaskStatus
    details: str | None
    output: str | None
    sources: list[ManagedWorkSource]


class ManagedWork(_Projection):
    id: str
    status: ExternalChannelWorkStatus
    title: str | None
    tasks: list[ManagedWorkTask]
    state_revision: int
    desired_progress_revision: int
    progress_projected: bool
    projection_state: Literal[
        "synchronized",
        "missing",
        "stale",
        "delete_failed",
        "unknown",
        "none",
    ]
    finished_at: datetime.datetime | None


class ManagedBinding(_Projection):
    id: str
    agent_session_id: str
    provider: ExternalChannelProvider
    response_mode: ExternalChannelResponseMode
    resource_type: ExternalChannelResourceType
    conversation_location: ExternalChannelConversationLocation
    resource_label: str
    connected_at: datetime.datetime
    disconnected_at: datetime.datetime | None
    disconnect_reason: str | None
    latest_activity_at: datetime.datetime | None
    work: ManagedWork | None


class ManagedGrant(_Projection):
    id: str
    agent_id: str
    principal_id: str
    principal_label: str
    principal_provider_user_id: str
    scope: ExternalChannelAccessGrantScope
    agent_session_id: str | None
    created_at: datetime.datetime
    revoked_at: datetime.datetime | None


class ManagedBlock(_Projection):
    id: str
    agent_id: str
    principal_id: str
    principal_label: str
    principal_provider_user_id: str
    reason: str | None
    created_at: datetime.datetime
    removed_at: datetime.datetime | None


class ManagedApprovalRequest(_Projection):
    id: str
    agent_id: str
    workspace_id: str
    agent_session_id: str | None
    provider: ExternalChannelProvider
    status: ExternalChannelAccessRequestStatus
    principal_id: str
    principal_label: str
    principal_provider_user_id: str
    resource_label: str
    expires_at: datetime.datetime
    decided_at: datetime.datetime | None
    decision_summary: str | None
