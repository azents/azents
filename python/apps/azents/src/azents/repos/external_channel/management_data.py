"""Safe External Channel management repository projections."""

import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict

from azents.core.enums import (
    ExternalChannelAccessGrantScope,
    ExternalChannelAccessRequestStatus,
    ExternalChannelBindingActivationStatus,
    ExternalChannelBindingStatus,
    ExternalChannelConnectionStatus,
    ExternalChannelDeliveryOperation,
    ExternalChannelDeliveryStatus,
    ExternalChannelProvider,
    ExternalChannelTransport,
    ExternalChannelWorkStatus,
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
    credentials_configured: bool
    capabilities: dict[str, Any] | None
    last_verified_at: datetime.datetime | None
    last_health_at: datetime.datetime | None
    socket_gap_detected_at: datetime.datetime | None
    socket_gap_reason: str | None
    disconnected_at: datetime.datetime | None


class ManagedDelivery(_Projection):
    id: str
    operation: ExternalChannelDeliveryOperation
    status: ExternalChannelDeliveryStatus
    error_kind: str | None
    error_summary: str | None
    attempted_at: datetime.datetime | None
    completed_at: datetime.datetime | None
    created_at: datetime.datetime


class ManagedWork(_Projection):
    id: str
    status: ExternalChannelWorkStatus
    tasks: list[dict[str, Any]]
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
    resource_type: str
    resource_label: str
    status: ExternalChannelBindingStatus
    activation_status: ExternalChannelBindingActivationStatus
    truncated_message_count: int
    truncated_size: int
    connected_at: datetime.datetime
    disconnected_at: datetime.datetime | None
    disconnect_reason: str | None
    latest_activity_at: datetime.datetime | None
    work: ManagedWork | None
    deliveries: list[ManagedDelivery]


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
    source_text: str | None
    original_url: str | None
    expires_at: datetime.datetime
    decided_at: datetime.datetime | None
    decision_summary: str | None
