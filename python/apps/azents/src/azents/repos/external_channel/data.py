"""Provider-generic External Channel repository data records."""

import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict

from azents.core.enums import (
    ExternalChannelAccessGrantScope,
    ExternalChannelAccessRequestStatus,
    ExternalChannelActionMode,
    ExternalChannelAppMode,
    ExternalChannelChannelDefaultStatus,
    ExternalChannelConnectionStatus,
    ExternalChannelConversationLocation,
    ExternalChannelConversationScopeKind,
    ExternalChannelDeliveryOperation,
    ExternalChannelDeliveryOriginType,
    ExternalChannelDeliveryStatus,
    ExternalChannelDiscordThreadObservationStatus,
    ExternalChannelDiscordThreadTitleProofKind,
    ExternalChannelDiscordThreadTitleProvisioningStatus,
    ExternalChannelDiscordThreadTitleStatus,
    ExternalChannelIngressProfile,
    ExternalChannelInteractionStatus,
    ExternalChannelInteractionType,
    ExternalChannelMessageRevisionKind,
    ExternalChannelParticipationSettingStatus,
    ExternalChannelPrincipalAuthorType,
    ExternalChannelProvider,
    ExternalChannelResourceStatus,
    ExternalChannelResourceType,
    ExternalChannelResponseMode,
    ExternalChannelRouteCatalogStatus,
    ExternalChannelRouteMode,
    ExternalChannelSessionTitleCandidateStatus,
    ExternalChannelSetupClaimStatus,
    ExternalChannelTransport,
    ExternalChannelWorkProjectionStatus,
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
    latest_activity_at: datetime.datetime | None
    unavailable_at: datetime.datetime | None
    deleted_at: datetime.datetime | None


class ExternalChannelTrigger(_Record):
    """Transient authenticated provider trigger used for typed ingestion."""

    connection_id: str
    provider_event_id: str
    transport_envelope_id: str | None
    event_type: str
    provider_app_id: str | None
    provider_tenant_id: str | None
    provider_enterprise_id: str | None
    resource_correlation_key: str | None
    envelope: dict[str, Any]
    provider_occurred_at: datetime.datetime | None
    received_at: datetime.datetime


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
    setup_claim_id: str | None
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
    setup_claim_id: str | None
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


class ExternalChannelChannelDefault(_Record):
    """Durable route default for one provider channel."""

    id: str
    connection_id: str
    provider_channel_id: str
    route_id: str
    status: ExternalChannelChannelDefaultStatus
    configured_by_user_id: str | None
    configured_by_principal_id: str | None
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
    configured_by_user_id: str | None
    configured_by_principal_id: str | None
    invalidated_at: datetime.datetime | None
    invalidation_reason: str | None


class ExternalChannelParticipationSetting(_Record):
    """Selected parent-channel conversation behavior."""

    id: str
    connection_id: str
    provider_parent_channel_id: str
    route_id: str
    location: ExternalChannelConversationLocation
    response_mode: ExternalChannelResponseMode
    settings_generation: int
    configured_by_user_id: str | None
    configured_by_principal_id: str | None
    status: ExternalChannelParticipationSettingStatus
    invalidated_at: datetime.datetime | None
    invalidation_reason: str | None
    created_at: datetime.datetime
    updated_at: datetime.datetime


class ExternalChannelParticipationSettingCreate(_Record):
    """Participation-setting creation payload."""

    connection_id: str
    provider_parent_channel_id: str
    route_id: str
    location: ExternalChannelConversationLocation
    response_mode: ExternalChannelResponseMode
    settings_generation: int
    configured_by_user_id: str | None
    configured_by_principal_id: str | None
    status: ExternalChannelParticipationSettingStatus
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


class ExternalChannelSetupClaim(_Record):
    """Latest eligible setup continuation for one provider parent channel."""

    id: str
    connection_id: str
    provider_parent_channel_id: str
    route_id: str | None
    conversation_position_id: str
    source_resource_id: str
    principal_id: str
    source_projection: dict[str, Any]
    source_revision: int
    claim_generation: int
    status: ExternalChannelSetupClaimStatus
    selected_setting_id: str | None
    selected_resource_id: str | None
    selected_source_revision: int | None
    expires_at: datetime.datetime
    selected_at: datetime.datetime | None
    completed_at: datetime.datetime | None
    created_at: datetime.datetime
    updated_at: datetime.datetime


class ExternalChannelSetupClaimCreate(_Record):
    """Setup-claim creation payload."""

    connection_id: str
    provider_parent_channel_id: str
    route_id: str | None
    conversation_position_id: str
    source_resource_id: str
    principal_id: str
    source_projection: dict[str, Any]
    source_revision: int
    claim_generation: int
    status: ExternalChannelSetupClaimStatus
    selected_setting_id: str | None
    selected_resource_id: str | None
    selected_source_revision: int | None
    expires_at: datetime.datetime
    selected_at: datetime.datetime | None
    completed_at: datetime.datetime | None


class ExternalChannelBinding(_Record):
    """Lifecycle-owned resource-to-Session relationship."""

    id: str
    resource_id: str
    route_id: str
    agent_session_id: str
    response_mode: ExternalChannelResponseMode
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
    response_mode: ExternalChannelResponseMode
    disconnected_at: datetime.datetime | None
    disconnect_reason: str | None


class ExternalChannelSessionTitleCandidate(_Record):
    """Durable exact-trigger authority for one External Channel Session title."""

    id: str
    agent_session_id: str
    binding_id: str
    trigger_provider_message_key: str
    status: ExternalChannelSessionTitleCandidateStatus
    consumed_event_id: str | None
    relinquished_reason: str | None
    created_at: datetime.datetime
    updated_at: datetime.datetime


class ExternalChannelSessionTitleCandidateCreate(_Record):
    """Idempotent creation payload for a new Session title candidate."""

    agent_session_id: str
    binding_id: str
    trigger_provider_message_key: str
    status: ExternalChannelSessionTitleCandidateStatus
    consumed_event_id: str | None
    relinquished_reason: str | None


class ExternalChannelDiscordThreadTitleProjection(_Record):
    """Resource-scoped desired state for one initial Discord thread title."""

    id: str
    resource_id: str
    binding_id: str
    agent_session_id: str
    session_title_candidate_id: str
    provisioning_protocol_version: int
    requested_provisional_title: str
    admission_connection_id: str
    admission_guild_id: str
    admission_parent_channel_id: str
    admission_root_message_id: str
    admission_trigger_provider_message_key: str
    admission_observation_status: ExternalChannelDiscordThreadObservationStatus
    admission_root_has_thread: bool | None
    admission_observed_thread_channel_id: str | None
    admission_observed_at: datetime.datetime
    provisioning_status: ExternalChannelDiscordThreadTitleProvisioningStatus
    preflight_absent_at: datetime.datetime | None
    thread_channel_id: str | None
    expected_provisional_title: str | None
    provisioning_proof_kind: ExternalChannelDiscordThreadTitleProofKind | None
    provision_attempt_count: int
    provision_next_attempt_at: datetime.datetime | None
    provision_claimed_at: datetime.datetime | None
    provision_failure_kind: str | None
    provision_failure_summary: str | None
    provision_completed_at: datetime.datetime | None
    desired_title: str | None
    title_generation_event_id: str | None
    title_status: ExternalChannelDiscordThreadTitleStatus
    title_attempt_count: int
    title_next_attempt_at: datetime.datetime | None
    title_claimed_at: datetime.datetime | None
    title_failure_kind: str | None
    title_failure_summary: str | None
    title_completed_at: datetime.datetime | None
    created_at: datetime.datetime
    updated_at: datetime.datetime


class ExternalChannelDiscordThreadTitleProjectionCreate(_Record):
    """Creation payload for one initial Discord thread title projection."""

    resource_id: str
    binding_id: str
    agent_session_id: str
    session_title_candidate_id: str
    provisioning_protocol_version: int
    requested_provisional_title: str
    admission_connection_id: str
    admission_guild_id: str
    admission_parent_channel_id: str
    admission_root_message_id: str
    admission_trigger_provider_message_key: str
    admission_observation_status: ExternalChannelDiscordThreadObservationStatus
    admission_root_has_thread: bool | None
    admission_observed_thread_channel_id: str | None
    admission_observed_at: datetime.datetime
    provisioning_status: ExternalChannelDiscordThreadTitleProvisioningStatus
    preflight_absent_at: datetime.datetime | None
    thread_channel_id: str | None
    expected_provisional_title: str | None
    provisioning_proof_kind: ExternalChannelDiscordThreadTitleProofKind | None
    provision_attempt_count: int
    provision_next_attempt_at: datetime.datetime | None
    provision_claimed_at: datetime.datetime | None
    provision_failure_kind: str | None
    provision_failure_summary: str | None
    provision_completed_at: datetime.datetime | None
    desired_title: str | None
    title_generation_event_id: str | None
    title_status: ExternalChannelDiscordThreadTitleStatus
    title_attempt_count: int
    title_next_attempt_at: datetime.datetime | None
    title_claimed_at: datetime.datetime | None
    title_failure_kind: str | None
    title_failure_summary: str | None
    title_completed_at: datetime.datetime | None


class ExternalChannelMailboxProjectionItem(_Record):
    """One provider-history message embedded in a canonical mailbox item."""

    invocation_id: str
    binding_id: str
    trigger_provider_message_key: str
    context_omitted: bool
    sequence: int
    revision_kind: ExternalChannelMessageRevisionKind
    body: str | None
    attachment_metadata: dict[str, Any] | None
    reference_mappings: dict[str, Any] | None
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


class ExternalChannelAccessRequest(_Record):
    """Durable request to authorize one external principal invocation."""

    id: str
    route_id: str
    resource_id: str
    trigger_provider_message_key: str
    principal_id: str
    agent_session_id: str | None
    setup_claim_id: str | None
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
    trigger_provider_message_key: str
    principal_id: str
    agent_session_id: str | None
    setup_claim_id: str | None
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
    created_cleanup_intent_count: int
    cleanup_intent_ids: tuple[str, ...]


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


class ExternalChannelAgentDecommissionCleanup(_Record):
    """Summary of direct Agent-owned External Channel state removal."""

    cleanup_intent_ids: tuple[str, ...]
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
    active_participation_setting_count: int
    nonterminal_setup_claim_count: int
    active_binding_count: int
    connected_parent_binding_count: int
    bound_resource_count: int
    open_admission_count: int
    pending_access_request_count: int
    affected_defaults: tuple[ExternalChannelMultiImpactDefault, ...]
    affected_bindings: tuple[ExternalChannelMultiImpactBinding, ...]


class ExternalChannelMultiConnectionImpact(_Record):
    """Sanitized deterministic impact projection for one whole Multi App."""

    connection_id: str
    generation: datetime.datetime
    active_route_count: int
    active_default_count: int
    active_participation_setting_count: int
    nonterminal_setup_claim_count: int
    active_binding_count: int
    connected_parent_binding_count: int
    bound_resource_count: int
    open_admission_count: int
    pending_access_request_count: int
    affected_defaults: tuple[ExternalChannelMultiImpactDefault, ...]
    affected_bindings: tuple[ExternalChannelMultiImpactBinding, ...]


class ExternalChannelMultiRouteRemoval(_Record):
    """Committed Multi route removal result without provider execution."""

    impact: ExternalChannelMultiRouteImpact
    cleanup_intent_ids: tuple[str, ...]


class ExternalChannelMultiConnectionDisconnect(_Record):
    """Committed whole-Multi-App disconnect result without provider execution."""

    disconnected_route_count: int
    invalidated_default_count: int
    invalidated_participation_setting_count: int
    terminated_setup_claim_count: int
    expired_admission_count: int
    expired_access_request_count: int
    unavailable_resource_count: int
    disconnected_binding_count: int
    cleanup_intent_ids: tuple[str, ...]
