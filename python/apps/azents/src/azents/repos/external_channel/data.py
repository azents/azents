"""Provider-generic External Channel repository data records."""

import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict

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
    ExternalChannelRouteStatus,
    ExternalChannelTransport,
    ExternalChannelWorkStatus,
)


class _Record(BaseModel):
    """Immutable repository data base with ORM attribute support."""

    model_config = ConfigDict(frozen=True, from_attributes=True)


class ExternalChannelConnection(_Record):
    """Workspace-owned provider installation and credential boundary."""

    id: str
    workspace_id: str
    provider: ExternalChannelProvider
    transport: ExternalChannelTransport
    status: ExternalChannelConnectionStatus
    provider_app_id: str | None
    provider_tenant_id: str | None
    provider_bot_user_id: str | None
    http_callback_selector_hash: str | None
    capabilities: dict[str, Any] | None
    provider_config: dict[str, Any] | None
    last_verified_at: datetime.datetime | None
    last_health_at: datetime.datetime | None
    disconnected_at: datetime.datetime | None
    socket_lease_owner: str | None
    socket_lease_until: datetime.datetime | None
    socket_heartbeat_at: datetime.datetime | None
    socket_gap_detected_at: datetime.datetime | None
    socket_gap_reason: str | None
    created_at: datetime.datetime
    updated_at: datetime.datetime


class ExternalChannelConnectionCreate(_Record):
    """Connection creation payload with encrypted credentials."""

    workspace_id: str
    provider: ExternalChannelProvider
    transport: ExternalChannelTransport
    status: ExternalChannelConnectionStatus
    provider_app_id: str | None
    provider_tenant_id: str | None
    provider_bot_user_id: str | None
    http_callback_selector_hash: str | None
    encrypted_credentials: str | None
    capabilities: dict[str, Any] | None
    provider_config: dict[str, Any] | None
    last_verified_at: datetime.datetime | None
    last_health_at: datetime.datetime | None
    disconnected_at: datetime.datetime | None
    socket_lease_owner: str | None
    socket_lease_until: datetime.datetime | None
    socket_heartbeat_at: datetime.datetime | None
    socket_gap_detected_at: datetime.datetime | None
    socket_gap_reason: str | None


class ExternalChannelConnectionConfiguration(_Record):
    """Internal connection configuration including encrypted credentials."""

    id: str
    workspace_id: str
    provider: ExternalChannelProvider
    transport: ExternalChannelTransport
    status: ExternalChannelConnectionStatus
    provider_app_id: str | None
    provider_tenant_id: str | None
    provider_bot_user_id: str | None
    http_callback_selector_hash: str | None
    encrypted_credentials: str | None
    capabilities: dict[str, Any] | None
    provider_config: dict[str, Any] | None
    last_verified_at: datetime.datetime | None
    last_health_at: datetime.datetime | None
    disconnected_at: datetime.datetime | None
    socket_lease_owner: str | None
    socket_lease_until: datetime.datetime | None
    socket_heartbeat_at: datetime.datetime | None
    socket_gap_detected_at: datetime.datetime | None
    socket_gap_reason: str | None
    created_at: datetime.datetime
    updated_at: datetime.datetime


class ExternalChannelAgentRoute(_Record):
    """Connection-to-Agent route independent from provider credentials."""

    id: str
    connection_id: str
    agent_id: str
    status: ExternalChannelRouteStatus
    route_mode: ExternalChannelRouteMode
    created_at: datetime.datetime
    updated_at: datetime.datetime
    deactivated_at: datetime.datetime | None


class ExternalChannelAgentRouteCreate(_Record):
    """Agent route creation payload."""

    connection_id: str
    agent_id: str
    status: ExternalChannelRouteStatus
    route_mode: ExternalChannelRouteMode


class ExternalChannelResource(_Record):
    """Canonical provider conversation or external work resource."""

    id: str
    connection_id: str
    resource_type: ExternalChannelResourceType
    provider_resource_key: str
    labels: dict[str, Any] | None
    status: ExternalChannelResourceStatus
    hydration_status: ExternalChannelHydrationStatus
    hydration_cursor: str | None
    hydration_high_watermark_position: str | None
    reconciliation_boundary_received_at: datetime.datetime | None
    reconciliation_boundary_event_id: str | None
    hydration_error_kind: str | None
    hydration_error_summary: str | None
    hydration_started_at: datetime.datetime | None
    hydration_completed_at: datetime.datetime | None
    discovered_at: datetime.datetime
    latest_activity_at: datetime.datetime | None
    unavailable_at: datetime.datetime | None
    deleted_at: datetime.datetime | None
    created_at: datetime.datetime
    updated_at: datetime.datetime


class ExternalChannelResourceCreate(_Record):
    """Canonical resource creation payload."""

    connection_id: str
    resource_type: ExternalChannelResourceType
    provider_resource_key: str
    labels: dict[str, Any] | None
    status: ExternalChannelResourceStatus
    hydration_status: ExternalChannelHydrationStatus
    hydration_cursor: str | None
    hydration_high_watermark_position: str | None
    reconciliation_boundary_received_at: datetime.datetime | None
    reconciliation_boundary_event_id: str | None
    hydration_error_kind: str | None
    hydration_error_summary: str | None
    hydration_started_at: datetime.datetime | None
    hydration_completed_at: datetime.datetime | None
    latest_activity_at: datetime.datetime | None
    unavailable_at: datetime.datetime | None
    deleted_at: datetime.datetime | None


class ExternalChannelEvent(_Record):
    """Durably admitted provider event awaiting idempotent processing."""

    id: str
    connection_id: str
    provider_event_id: str
    transport_envelope_id: str | None
    event_type: str
    provider_app_id: str | None
    provider_tenant_id: str | None
    provider_enterprise_id: str | None
    resource_correlation_key: str | None
    eligibility_state: ExternalChannelEventEligibilityState
    envelope: dict[str, Any]
    status: ExternalChannelEventStatus
    attempt_count: int
    claim_owner: str | None
    claim_until: datetime.datetime | None
    error_kind: str | None
    error_summary: str | None
    provider_occurred_at: datetime.datetime | None
    received_at: datetime.datetime
    processing_started_at: datetime.datetime | None
    processed_at: datetime.datetime | None
    created_at: datetime.datetime
    updated_at: datetime.datetime


class ExternalChannelEventCreate(_Record):
    """Provider-event admission payload."""

    connection_id: str
    provider_event_id: str
    transport_envelope_id: str | None
    event_type: str
    provider_app_id: str | None
    provider_tenant_id: str | None
    provider_enterprise_id: str | None
    resource_correlation_key: str | None
    eligibility_state: ExternalChannelEventEligibilityState
    envelope: dict[str, Any]
    status: ExternalChannelEventStatus
    provider_occurred_at: datetime.datetime | None
    received_at: datetime.datetime


class ExternalChannelEventAdmission(_Record):
    """Idempotent event-admission result."""

    event: ExternalChannelEvent
    created: bool


class ExternalChannelPrincipal(_Record):
    """Canonical provider participant identity independent from Azents users."""

    id: str
    provider: ExternalChannelProvider
    provider_tenant_id: str
    provider_user_id: str
    author_type: ExternalChannelPrincipalAuthorType
    display_name: str | None
    avatar_url: str | None
    profile: dict[str, Any] | None
    first_observed_at: datetime.datetime
    last_observed_at: datetime.datetime
    created_at: datetime.datetime
    updated_at: datetime.datetime


class ExternalChannelPrincipalCreate(_Record):
    """Canonical principal creation payload."""

    provider: ExternalChannelProvider
    provider_tenant_id: str
    provider_user_id: str
    author_type: ExternalChannelPrincipalAuthorType
    display_name: str | None
    avatar_url: str | None
    profile: dict[str, Any] | None


class ExternalChannelMessage(_Record):
    """Canonical external message independent from provider deliveries."""

    id: str
    resource_id: str
    provider_message_key: str
    provider_position: str
    principal_id: str | None
    author_type: ExternalChannelPrincipalAuthorType
    current_revision_id: str | None
    original_url: str | None
    lifecycle: ExternalChannelMessageLifecycle
    pending_size: int
    provider_created_at: datetime.datetime | None
    provider_updated_at: datetime.datetime | None
    observed_at: datetime.datetime
    created_at: datetime.datetime
    updated_at: datetime.datetime


class ExternalChannelMessageCreate(_Record):
    """Canonical message creation payload."""

    resource_id: str
    provider_message_key: str
    provider_position: str
    principal_id: str | None
    author_type: ExternalChannelPrincipalAuthorType
    current_revision_id: str | None
    original_url: str | None
    lifecycle: ExternalChannelMessageLifecycle
    pending_size: int
    provider_created_at: datetime.datetime | None
    provider_updated_at: datetime.datetime | None


class ExternalChannelMessageRevision(_Record):
    """Immutable normalized provider message revision."""

    id: str
    message_id: str
    revision_key: str
    revision_kind: ExternalChannelMessageRevisionKind
    normalized_body: str | None
    attachment_metadata: dict[str, Any] | None
    source_event_id: str | None
    provider_occurred_at: datetime.datetime | None
    observed_at: datetime.datetime
    created_at: datetime.datetime


class ExternalChannelMessageRevisionCreate(_Record):
    """Normalized message revision creation payload."""

    message_id: str
    revision_key: str
    revision_kind: ExternalChannelMessageRevisionKind
    normalized_body: str | None
    attachment_metadata: dict[str, Any] | None
    source_event_id: str | None
    provider_occurred_at: datetime.datetime | None


class ExternalChannelPendingContext(_Record):
    """Bounded route-and-resource context not yet session-projected."""

    id: str
    route_id: str
    resource_id: str
    message_revision_id: str
    provider_position: str
    normalized_size: int
    expires_at: datetime.datetime
    created_at: datetime.datetime


class ExternalChannelPendingContextCreate(_Record):
    """Pending-context creation payload."""

    route_id: str
    resource_id: str
    message_revision_id: str
    provider_position: str
    normalized_size: int
    expires_at: datetime.datetime


class ExternalChannelPendingContextTrim(_Record):
    """Pending-context retention result for one route and resource."""

    deleted_message_count: int
    deleted_size: int
    retained_message_count: int
    retained_size: int


class ExternalChannelEventBoundary(_Record):
    """Stable received-order boundary for correlated provider events."""

    received_at: datetime.datetime
    event_id: str


class ExternalChannelBinding(_Record):
    """Lifecycle-owned resource-to-Session relationship."""

    id: str
    resource_id: str
    route_id: str
    agent_session_id: str
    status: ExternalChannelBindingStatus
    activation_status: ExternalChannelBindingActivationStatus
    activation_trigger_message_id: str | None
    activated_at: datetime.datetime | None
    projected_through_position: str | None
    truncated_message_count: int
    truncated_size: int
    connected_at: datetime.datetime
    disconnected_at: datetime.datetime | None
    disconnect_reason: str | None
    created_at: datetime.datetime
    updated_at: datetime.datetime


class ExternalChannelBindingCreate(_Record):
    """Binding creation payload."""

    resource_id: str
    route_id: str
    agent_session_id: str
    status: ExternalChannelBindingStatus
    activation_status: ExternalChannelBindingActivationStatus
    activation_trigger_message_id: str | None
    activated_at: datetime.datetime | None
    projected_through_position: str | None
    truncated_message_count: int
    truncated_size: int
    disconnected_at: datetime.datetime | None
    disconnect_reason: str | None


class ExternalChannelInvocationBatch(_Record):
    """One ordered external turn released through an authorized invocation."""

    id: str
    binding_id: str
    trigger_message_id: str
    first_provider_position: str
    last_provider_position: str
    truncation_message_count: int
    truncation_size: int
    input_buffer_id: str | None
    created_at: datetime.datetime


class ExternalChannelInvocationBatchCreate(_Record):
    """Invocation-batch creation payload."""

    binding_id: str
    trigger_message_id: str
    first_provider_position: str
    last_provider_position: str
    truncation_message_count: int
    truncation_size: int
    input_buffer_id: str | None


class ExternalChannelInvocationBatchItem(_Record):
    """Immutable message revision membership in an invocation batch."""

    id: str
    batch_id: str
    message_revision_id: str
    sequence: int
    provider_position: str
    created_at: datetime.datetime


class ExternalChannelInvocationBatchItemCreate(_Record):
    """Invocation-batch item creation payload."""

    batch_id: str
    message_revision_id: str
    sequence: int
    provider_position: str


class ExternalChannelAccessRequest(_Record):
    """Durable request to authorize one external principal invocation."""

    id: str
    route_id: str
    resource_id: str
    source_message_id: str
    principal_id: str
    agent_session_id: str | None
    status: ExternalChannelAccessRequestStatus
    decision_policy_snapshot: dict[str, Any]
    decided_by_user_id: str | None
    decision_summary: str | None
    expires_at: datetime.datetime
    decided_at: datetime.datetime | None
    created_at: datetime.datetime
    updated_at: datetime.datetime


class ExternalChannelAccessRequestCreate(_Record):
    """Access-request creation payload."""

    route_id: str
    resource_id: str
    source_message_id: str
    principal_id: str
    agent_session_id: str | None
    status: ExternalChannelAccessRequestStatus
    decision_policy_snapshot: dict[str, Any]
    decided_by_user_id: str | None
    decision_summary: str | None
    expires_at: datetime.datetime
    decided_at: datetime.datetime | None


class ExternalChannelAccessGrant(_Record):
    """Session- or Agent-scoped external principal invocation grant."""

    id: str
    agent_id: str
    principal_id: str
    scope: ExternalChannelAccessGrantScope
    agent_session_id: str | None
    granted_by_user_id: str
    source_access_request_id: str | None
    revoked_by_user_id: str | None
    revoked_at: datetime.datetime | None
    created_at: datetime.datetime
    updated_at: datetime.datetime


class ExternalChannelAccessGrantCreate(_Record):
    """Access-grant creation payload."""

    agent_id: str
    principal_id: str
    scope: ExternalChannelAccessGrantScope
    agent_session_id: str | None
    granted_by_user_id: str
    source_access_request_id: str | None
    revoked_by_user_id: str | None
    revoked_at: datetime.datetime | None


class ExternalChannelBlock(_Record):
    """Agent-level principal block overriding active invocation grants."""

    id: str
    agent_id: str
    principal_id: str
    blocked_by_user_id: str
    reason: str | None
    removed_by_user_id: str | None
    removed_at: datetime.datetime | None
    created_at: datetime.datetime
    updated_at: datetime.datetime


class ExternalChannelBlockCreate(_Record):
    """Block creation payload."""

    agent_id: str
    principal_id: str
    blocked_by_user_id: str
    reason: str | None
    removed_by_user_id: str | None
    removed_at: datetime.datetime | None


class ExternalChannelWork(_Record):
    """Binding-scoped task state and desired progress projection."""

    id: str
    binding_id: str
    status: ExternalChannelWorkStatus
    schema_version: int
    tasks: list[dict[str, Any]]
    state_revision: int
    desired_progress_revision: int
    desired_progress_payload: dict[str, Any] | None
    progress_provider_message_key: str | None
    finished_at: datetime.datetime | None
    created_at: datetime.datetime
    updated_at: datetime.datetime


class ExternalChannelWorkCreate(_Record):
    """Channel Work creation payload."""

    binding_id: str
    status: ExternalChannelWorkStatus
    schema_version: int
    tasks: list[dict[str, Any]]
    state_revision: int
    desired_progress_revision: int
    desired_progress_payload: dict[str, Any] | None
    progress_provider_message_key: str | None
    finished_at: datetime.datetime | None


class ExternalChannelAction(_Record):
    """Idempotent atomic Channel Action accepted from an Agent run."""

    id: str
    agent_session_id: str
    agent_run_id: str | None
    client_tool_call_id: str
    binding_id: str
    work_id: str | None
    mode: ExternalChannelActionMode
    state_revision: int
    request_payload: dict[str, Any]
    accepted_at: datetime.datetime
    completed_at: datetime.datetime | None
    created_at: datetime.datetime
    updated_at: datetime.datetime


class ExternalChannelActionCreate(_Record):
    """Channel Action creation payload."""

    agent_session_id: str
    agent_run_id: str | None
    client_tool_call_id: str
    binding_id: str
    work_id: str | None
    mode: ExternalChannelActionMode
    state_revision: int
    request_payload: dict[str, Any]
    completed_at: datetime.datetime | None


class ExternalChannelDeliveryAttempt(_Record):
    """One explicit, at-most-once provider delivery operation."""

    id: str
    origin_type: ExternalChannelDeliveryOriginType
    origin_id: str
    channel_action_id: str | None
    binding_id: str | None
    operation: ExternalChannelDeliveryOperation
    request_payload: dict[str, Any]
    status: ExternalChannelDeliveryStatus
    provider_message_key: str | None
    error_kind: str | None
    error_summary: str | None
    attempted_at: datetime.datetime | None
    completed_at: datetime.datetime | None
    created_at: datetime.datetime
    updated_at: datetime.datetime


class ExternalChannelDeliveryAttemptCreate(_Record):
    """Delivery intent creation payload."""

    origin_type: ExternalChannelDeliveryOriginType
    origin_id: str
    channel_action_id: str | None
    binding_id: str | None
    operation: ExternalChannelDeliveryOperation
    request_payload: dict[str, Any]
    status: ExternalChannelDeliveryStatus
    provider_message_key: str | None
    error_kind: str | None
    error_summary: str | None
    attempted_at: datetime.datetime | None
    completed_at: datetime.datetime | None


class ExternalChannelArchiveTermination(_Record):
    """Transaction-local summary of one terminated Session tree."""

    disconnected_binding_count: int
    finished_work_count: int
    deleted_pending_context_count: int
    created_progress_delete_intent_count: int


class ExternalChannelRestoreValidation(_Record):
    """Proof that a restored Session tree has no reactivated channel state."""

    disconnected_binding_count: int
    finished_work_count: int


class ExternalChannelPurgePreparation(_Record):
    """Summary of delivery attempts made terminal without provider execution."""

    not_attempted_delivery_count: int
    unknown_delivery_count: int


class ExternalChannelPurgeCleanup(_Record):
    """Summary of Session-owned External Channel records removed during purge."""

    deleted_delivery_attempt_count: int
    deleted_action_count: int
    deleted_session_grant_count: int
    preserved_agent_grant_reference_count: int
    deleted_access_request_count: int
    deleted_invocation_batch_item_count: int
    deleted_invocation_batch_count: int
    deleted_work_count: int
    deleted_binding_count: int


class ExternalChannelPurgeVerification(_Record):
    """Verified absence counts for one purged Session tree."""

    remaining_binding_count: int
    remaining_work_count: int
    remaining_action_count: int
    remaining_delivery_attempt_count: int
    remaining_access_request_count: int
    remaining_session_grant_count: int
    remaining_invocation_batch_count: int


class ExternalChannelAgentDecommissionCleanup(_Record):
    """Summary of direct Agent-owned External Channel state removal."""

    deleted_route_count: int
    deleted_access_request_count: int
    deleted_control_attempt_count: int
    deleted_agent_grant_count: int
    deleted_block_count: int
