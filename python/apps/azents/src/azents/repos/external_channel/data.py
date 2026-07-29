"""Provider-generic External Channel repository data records."""

import datetime
from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel, ConfigDict

from azents.core.enums import (
    ExternalChannelAccessGrantScope,
    ExternalChannelAccessRequestStatus,
    ExternalChannelActionMode,
    ExternalChannelAppMode,
    ExternalChannelBindingActivationStatus,
    ExternalChannelBindingStatus,
    ExternalChannelChannelDefaultStatus,
    ExternalChannelConnectionStatus,
    ExternalChannelConversationAdmissionOrigin,
    ExternalChannelConversationAdmissionStatus,
    ExternalChannelConversationScopeKind,
    ExternalChannelDeliveryOperation,
    ExternalChannelDeliveryOriginType,
    ExternalChannelDeliveryStatus,
    ExternalChannelEventEligibilityState,
    ExternalChannelEventStatus,
    ExternalChannelHydrationStatus,
    ExternalChannelIngressProfile,
    ExternalChannelInteractionStatus,
    ExternalChannelInteractionType,
    ExternalChannelInvocationWakeDispatchStatus,
    ExternalChannelMessageLifecycle,
    ExternalChannelMessageRevisionKind,
    ExternalChannelPrincipalAuthorType,
    ExternalChannelProvider,
    ExternalChannelResourceProvisioningOperation,
    ExternalChannelResourceProvisioningStatus,
    ExternalChannelResourceStatus,
    ExternalChannelResourceType,
    ExternalChannelRouteCatalogStatus,
    ExternalChannelRouteMode,
    ExternalChannelTransport,
    ExternalChannelWorkProjectionStatus,
    ExternalChannelWorkStatus,
)


class _Record(BaseModel):
    """Immutable repository data base with ORM attribute support."""

    model_config = ConfigDict(frozen=True, from_attributes=True)


@dataclass(frozen=True)
class ExternalChannelCutoverPreflightCounts:
    """Content-free aggregate counts required before legacy cutover."""

    undrained_events: int
    unactivated_bindings: int
    incomplete_hydrations: int
    pending_contexts: int
    open_conversation_admissions: int
    pending_access_requests: int
    inflight_resource_provisionings: int
    active_bindings_without_delivery_target: int
    active_bindings_without_session: int
    active_bindings_without_route: int
    active_bindings_without_latest_batch: int
    active_bindings_without_thread_position: int
    active_bindings_with_ambiguous_thread_position: int

    def __post_init__(self) -> None:
        """Reject invalid negative aggregate counts."""
        if any(value < 0 for value in self.__dict__.values()):
            raise ValueError("Cutover preflight counts must be non-negative.")


class ExternalChannelConnection(_Record):
    """Workspace-owned provider installation and credential boundary."""

    id: str
    workspace_id: str
    provider: ExternalChannelProvider
    transport: ExternalChannelTransport
    ingress_profile: ExternalChannelIngressProfile = (
        ExternalChannelIngressProfile.SLACK_HTTP
    )
    configuration_generation: int = 1
    status: ExternalChannelConnectionStatus
    app_mode: ExternalChannelAppMode
    provider_app_id: str | None
    provider_tenant_id: str | None
    provider_bot_user_id: str | None
    http_callback_selector_hash: str | None
    capabilities: dict[str, Any] | None
    provider_config: dict[str, Any] | None
    last_verified_at: datetime.datetime | None
    last_health_at: datetime.datetime | None
    last_health_code: str | None = None
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
    ingress_profile: ExternalChannelIngressProfile = (
        ExternalChannelIngressProfile.SLACK_HTTP
    )
    configuration_generation: int = 1
    status: ExternalChannelConnectionStatus
    app_mode: ExternalChannelAppMode
    provider_app_id: str | None
    provider_tenant_id: str | None
    provider_bot_user_id: str | None
    http_callback_selector_hash: str | None
    encrypted_credentials: str | None
    capabilities: dict[str, Any] | None
    provider_config: dict[str, Any] | None
    last_verified_at: datetime.datetime | None
    last_health_at: datetime.datetime | None
    last_health_code: str | None = None
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
    ingress_profile: ExternalChannelIngressProfile = (
        ExternalChannelIngressProfile.SLACK_HTTP
    )
    configuration_generation: int = 1
    status: ExternalChannelConnectionStatus
    app_mode: ExternalChannelAppMode
    provider_app_id: str | None
    provider_tenant_id: str | None
    provider_bot_user_id: str | None
    http_callback_selector_hash: str | None
    encrypted_credentials: str | None
    capabilities: dict[str, Any] | None
    provider_config: dict[str, Any] | None
    last_verified_at: datetime.datetime | None
    last_health_at: datetime.datetime | None
    last_health_code: str | None = None
    disconnected_at: datetime.datetime | None
    socket_lease_owner: str | None
    socket_lease_until: datetime.datetime | None
    socket_heartbeat_at: datetime.datetime | None
    socket_gap_detected_at: datetime.datetime | None
    socket_gap_reason: str | None
    created_at: datetime.datetime
    updated_at: datetime.datetime


class ExternalChannelConversationPosition(_Record):
    """Durable provider-history read position for one conversation scope."""

    id: str
    connection_id: str
    scope_kind: ExternalChannelConversationScopeKind
    provider_channel_id: str
    provider_thread_key: str | None
    read_through_position: str | None
    created_at: datetime.datetime
    updated_at: datetime.datetime


class ExternalChannelConversationPositionCreate(_Record):
    """Conversation-position creation payload."""

    connection_id: str
    scope_kind: ExternalChannelConversationScopeKind
    provider_channel_id: str
    provider_thread_key: str | None
    read_through_position: str | None


class ExternalChannelAgentRoute(_Record):
    """Persistent connection-to-Agent relationship."""

    id: str
    connection_id: str
    agent_id: str | None
    agent_id_snapshot: str
    route_mode: ExternalChannelRouteMode
    connection_app_mode: ExternalChannelAppMode
    catalog_status: ExternalChannelRouteCatalogStatus
    catalog_removed_at: datetime.datetime | None
    catalog_removed_by_user_id: str | None
    open_access_enabled: bool = True
    allow_bot_messages: bool = False
    created_at: datetime.datetime
    updated_at: datetime.datetime

    def require_active_agent_id(self) -> str:
        """Return the active Agent association or reject historical use."""
        if self.agent_id is None:
            raise RuntimeError(
                "External Channel route has no active Agent association."
            )
        return self.agent_id


class ExternalChannelAgentRouteCreate(_Record):
    """Agent route creation payload."""

    connection_id: str
    agent_id: str
    agent_id_snapshot: str
    route_mode: ExternalChannelRouteMode
    connection_app_mode: ExternalChannelAppMode
    catalog_status: ExternalChannelRouteCatalogStatus
    catalog_removed_at: datetime.datetime | None
    catalog_removed_by_user_id: str | None
    open_access_enabled: bool = True
    allow_bot_messages: bool = False


class ExternalChannelCatalogRoute(_Record):
    """One current selector candidate with its canonical Agent display name."""

    route: ExternalChannelAgentRoute
    agent_name: str


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


class ExternalChannelInteraction(_Record):
    """Durable, bounded provider interaction admission."""

    id: str
    connection_id: str
    transport: ExternalChannelTransport
    provider_interaction_key: str
    interaction_type: ExternalChannelInteractionType
    callback_id: str | None
    action_id: str | None
    principal_id: str | None
    resource_correlation_key: str | None
    projection: dict[str, Any]
    status: ExternalChannelInteractionStatus
    expires_at: datetime.datetime
    error_kind: str | None
    error_summary: str | None
    created_at: datetime.datetime
    updated_at: datetime.datetime


class ExternalChannelInteractionCreate(_Record):
    """Provider interaction admission payload without raw provider content."""

    connection_id: str
    transport: ExternalChannelTransport
    provider_interaction_key: str
    interaction_type: ExternalChannelInteractionType
    callback_id: str | None
    action_id: str | None
    principal_id: str | None
    resource_correlation_key: str | None
    projection: dict[str, Any]
    status: ExternalChannelInteractionStatus
    expires_at: datetime.datetime
    error_kind: str | None
    error_summary: str | None


class ExternalChannelInteractionAdmission(_Record):
    """Idempotent interaction-admission result."""

    interaction: ExternalChannelInteraction
    created: bool


class ExternalChannelConversationAdmission(_Record):
    """Route-neutral admission for an unbound provider conversation."""

    id: str
    connection_id: str
    resource_id: str
    source_message_id: str
    initiating_principal_id: str | None
    origin: ExternalChannelConversationAdmissionOrigin
    status: ExternalChannelConversationAdmissionStatus
    selected_route_id: str | None
    interaction_id: str | None
    conversation_position_id: str | None = None
    range_start_position: str | None = None
    trigger_position: str | None = None
    expires_at: datetime.datetime
    created_at: datetime.datetime
    updated_at: datetime.datetime


class ExternalChannelConversationAdmissionCreate(_Record):
    """Conversation-admission creation payload."""

    connection_id: str
    resource_id: str
    source_message_id: str
    initiating_principal_id: str | None
    origin: ExternalChannelConversationAdmissionOrigin
    status: ExternalChannelConversationAdmissionStatus
    selected_route_id: str | None
    interaction_id: str | None
    conversation_position_id: str | None = None
    range_start_position: str | None = None
    trigger_position: str | None = None
    expires_at: datetime.datetime


class ExternalChannelChannelDefault(_Record):
    """Durable route default for one provider channel."""

    id: str
    connection_id: str
    provider_channel_id: str
    route_id: str
    status: ExternalChannelChannelDefaultStatus
    configured_by_user_id: str
    invalidated_at: datetime.datetime | None
    invalidation_reason: str | None
    created_at: datetime.datetime
    updated_at: datetime.datetime


class ExternalChannelChannelDefaultCreate(_Record):
    """Channel-default creation payload."""

    connection_id: str
    provider_channel_id: str
    route_id: str
    status: ExternalChannelChannelDefaultStatus
    configured_by_user_id: str
    invalidated_at: datetime.datetime | None
    invalidation_reason: str | None


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
    reference_mappings: dict[str, Any] | None
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
    reference_mappings: dict[str, Any] | None
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
    activation_wake_claimed_at: datetime.datetime | None = None
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
    activation_wake_claimed_at: datetime.datetime | None = None
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
    conversation_position_id: str | None = None
    range_start_position: str | None = None
    trigger_position: str | None = None
    context_omitted: bool = False
    wake_dispatch_status: ExternalChannelInvocationWakeDispatchStatus = (
        ExternalChannelInvocationWakeDispatchStatus.DISPATCHED
    )
    wake_dispatch_claimed_at: datetime.datetime | None = None
    truncation_message_count: int
    truncation_size: int
    mailbox_item_id: str | None
    connection_id: str | None = None
    created_at: datetime.datetime


class ExternalChannelInvocationBatchCreate(_Record):
    """Invocation-batch creation payload."""

    binding_id: str
    trigger_message_id: str
    first_provider_position: str
    last_provider_position: str
    conversation_position_id: str | None = None
    range_start_position: str | None = None
    trigger_position: str | None = None
    context_omitted: bool = False
    wake_dispatch_status: ExternalChannelInvocationWakeDispatchStatus = (
        ExternalChannelInvocationWakeDispatchStatus.DISPATCHED
    )
    wake_dispatch_claimed_at: datetime.datetime | None = None
    truncation_message_count: int
    truncation_size: int
    mailbox_item_id: str | None
    connection_id: str | None = None


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


class ExternalChannelInvocationProjectionItem(_Record):
    """Joined immutable data needed to project one invocation event."""

    batch_id: str
    binding_id: str
    trigger_message_id: str
    context_omitted: bool
    truncation_message_count: int
    truncation_size: int
    sequence: int
    message_id: str
    revision_id: str
    revision_kind: ExternalChannelMessageRevisionKind
    revision_body: str | None
    attachment_metadata: dict[str, Any] | None
    reference_mappings: dict[str, Any] | None
    provider_occurred_at: datetime.datetime | None
    resource_id: str
    provider_resource_key: str
    resource_type: ExternalChannelResourceType
    resource_labels: dict[str, Any] | None
    provider: ExternalChannelProvider
    provider_tenant_id: str | None
    provider_message_key: str
    provider_position: str
    principal_id: str | None
    provider_user_id: str | None
    sender_display_name: str | None
    author_type: ExternalChannelPrincipalAuthorType
    provider_created_at: datetime.datetime | None
    provider_updated_at: datetime.datetime | None
    original_url: str | None
    correction_of_revision_id: str | None


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
    connection_id: str | None = None
    conversation_position_id: str | None = None
    range_start_position: str | None = None
    trigger_position: str | None = None


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
    connection_id: str | None = None
    conversation_position_id: str | None = None
    range_start_position: str | None = None
    trigger_position: str | None = None


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
    title: str | None
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
    title: str | None
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
    part_ordinal: int = 0
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
    part_ordinal: int = 0
    request_payload: dict[str, Any]
    status: ExternalChannelDeliveryStatus
    provider_message_key: str | None
    error_kind: str | None
    error_summary: str | None
    attempted_at: datetime.datetime | None
    completed_at: datetime.datetime | None


class ExternalChannelAppClaim(_Record):
    """Current provider App claim independent from disconnected history."""

    id: str
    provider: ExternalChannelProvider
    provider_app_id: str
    connection_id: str
    claim_generation: int
    acquired_at: datetime.datetime
    updated_at: datetime.datetime


class ExternalChannelIngressLease(_Record):
    """Provider-neutral fenced lease for inbound ownership."""

    id: str
    connection_id: str
    lease_owner: str | None
    lease_generation: int
    lease_until: datetime.datetime | None
    heartbeat_at: datetime.datetime | None
    required_configuration_generation: int | None
    required_app_claim_generation: int | None
    gap_detected_at: datetime.datetime | None
    gap_reason: str | None
    created_at: datetime.datetime
    updated_at: datetime.datetime


class ExternalChannelIngressLeaseClaim(_Record):
    """One successful fenced ingress-lease claim."""

    lease: ExternalChannelIngressLease


class ExternalChannelResourceProvisioning(_Record):
    """Durable result state for a resource provisioning operation."""

    id: str
    resource_id: str
    conversation_admission_id: str
    operation: ExternalChannelResourceProvisioningOperation
    target_provider_resource_key: str
    status: ExternalChannelResourceProvisioningStatus
    confirmed_provider_resource_key: str | None
    error_kind: str | None
    error_summary: str | None
    attempted_at: datetime.datetime | None
    completed_at: datetime.datetime | None
    created_at: datetime.datetime
    updated_at: datetime.datetime


class ExternalChannelWorkProjectionPart(_Record):
    """Current provider projection for an ordered canonical Work part."""

    id: str
    work_id: str
    part_ordinal: int
    desired_progress_revision: int
    status: ExternalChannelWorkProjectionStatus
    provider_message_key: str | None
    latest_delivery_attempt_id: str | None
    deleted_at: datetime.datetime | None
    created_at: datetime.datetime
    updated_at: datetime.datetime


class ExternalChannelArchiveTermination(_Record):
    """Transaction-local summary of one terminated Session tree."""

    disconnected_binding_count: int
    finished_work_count: int
    deleted_pending_context_count: int
    created_progress_delete_intent_count: int
    progress_delete_intent_ids: tuple[str, ...]


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

    progress_delete_intent_ids: tuple[str, ...]
    provider_state_purge_connection_ids: tuple[str, ...]
    deleted_route_count: int
    deleted_access_request_count: int
    deleted_control_attempt_count: int
    deleted_agent_grant_count: int
    deleted_block_count: int


class ExternalChannelMultiImpactDefault(_Record):
    """Sanitized active channel default affected by one Multi mutation."""

    id: str
    provider_channel_id: str
    route_id: str
    agent_id: str | None
    agent_name: str | None


class ExternalChannelMultiImpactBinding(_Record):
    """Sanitized active binding and Agent Session affected by one Multi mutation."""

    id: str
    route_id: str
    agent_session_id: str
    resource_id: str
    channel_label: str
    thread_label: str | None


class ExternalChannelMultiRouteImpact(_Record):
    """Sanitized deterministic impact projection for one Multi App route."""

    route_id: str
    generation: datetime.datetime
    active_default_count: int
    active_binding_count: int
    bound_resource_count: int
    open_admission_count: int
    pending_access_request_count: int
    pending_context_count: int
    affected_defaults: tuple[ExternalChannelMultiImpactDefault, ...]
    affected_bindings: tuple[ExternalChannelMultiImpactBinding, ...]


class ExternalChannelMultiConnectionImpact(_Record):
    """Sanitized deterministic impact projection for one whole Multi App."""

    connection_id: str
    generation: datetime.datetime
    active_route_count: int
    active_default_count: int
    active_binding_count: int
    bound_resource_count: int
    open_admission_count: int
    pending_access_request_count: int
    pending_context_count: int
    affected_defaults: tuple[ExternalChannelMultiImpactDefault, ...]
    affected_bindings: tuple[ExternalChannelMultiImpactBinding, ...]


class ExternalChannelMultiRouteRemoval(_Record):
    """Committed Multi route removal result without provider execution."""

    impact: ExternalChannelMultiRouteImpact
    progress_delete_intent_ids: tuple[str, ...]


class ExternalChannelMultiConnectionDisconnect(_Record):
    """Committed whole-Multi-App disconnect result without provider execution."""

    disconnected_route_count: int
    invalidated_default_count: int
    expired_admission_count: int
    expired_access_request_count: int
    unavailable_resource_count: int
    disconnected_binding_count: int
    deleted_pending_context_count: int
    progress_delete_intent_ids: tuple[str, ...]
