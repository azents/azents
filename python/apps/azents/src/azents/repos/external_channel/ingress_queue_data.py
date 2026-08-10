"""Typed data contracts for durable External Channel ingress queues."""

import datetime

from pydantic import BaseModel, ConfigDict

from azents.core.enums import (
    ExternalChannelConversationScopeKind,
    ExternalChannelIngressAuthorityKind,
    ExternalChannelIngressItemState,
    ExternalChannelIngressProfile,
    ExternalChannelProvider,
    ExternalChannelResponseMode,
)


class _Record(BaseModel):
    """Immutable repository record with ORM attribute support."""

    model_config = ConfigDict(frozen=True, from_attributes=True)


class ExternalChannelIngressOwner(_Record):
    """One active effective-conversation drain lifecycle."""

    id: str
    connection_id: str
    target_resource_id: str
    route_id: str
    participation_setting_id: str | None
    participation_settings_generation: int | None
    response_mode: ExternalChannelResponseMode
    binding_id: str | None
    session_id: str | None
    preparation_attempt_count: int
    preparation_next_attempt_at: datetime.datetime | None
    lease_owner: str | None
    lease_generation: int
    lease_acquired_at: datetime.datetime | None
    lease_expires_at: datetime.datetime | None
    first_batch_pending: bool
    current_batch_id: str | None
    current_batch_started_at: datetime.datetime | None
    created_at: datetime.datetime
    updated_at: datetime.datetime

    @property
    def ready(self) -> bool:
        """Return whether the owner has an immutable Binding and Session."""
        return self.binding_id is not None and self.session_id is not None


class ExternalChannelIngressOwnerCreate(_Record):
    """Immutable effective-conversation owner admission payload."""

    connection_id: str
    target_resource_id: str
    route_id: str
    participation_setting_id: str | None
    participation_settings_generation: int | None
    response_mode: ExternalChannelResponseMode
    binding_id: str | None
    session_id: str | None


class ExternalChannelIngressItem(_Record):
    """One active content-free provider trigger."""

    id: str
    owner_id: str
    queue_key: str
    deduplication_key: str
    provider_event_id: str
    connection_id: str
    provider: ExternalChannelProvider
    ingress_profile: ExternalChannelIngressProfile
    configuration_generation: int
    authority_kind: ExternalChannelIngressAuthorityKind
    authority_lease_owner: str | None
    authority_lease_generation: int | None
    provider_event_type: str
    provider_tenant_id: str
    scope_kind: ExternalChannelConversationScopeKind
    provider_channel_id: str
    provider_parent_channel_id: str | None
    provider_thread_key: str | None
    delivery_thread_key: str | None
    provider_resource_key: str
    source_resource_id: str
    conversation_position_id: str
    principal_id: str
    trigger_provider_message_key: str
    trigger_provider_message_id: str
    trigger_position: str
    provider_user_id: str | None
    invocation: bool
    invocation_id: str
    initial_title_eligible: bool
    state: ExternalChannelIngressItemState
    attempt_count: int
    next_attempt_at: datetime.datetime | None
    processing_owner: str | None
    processing_generation: int | None
    batch_id: str | None
    created_at: datetime.datetime
    updated_at: datetime.datetime


class ExternalChannelIngressItemCreate(_Record):
    """Content-free queue item admission payload."""

    deduplication_key: str
    provider_event_id: str
    connection_id: str
    provider: ExternalChannelProvider
    ingress_profile: ExternalChannelIngressProfile
    configuration_generation: int
    authority_kind: ExternalChannelIngressAuthorityKind
    authority_lease_owner: str | None
    authority_lease_generation: int | None
    provider_event_type: str
    provider_tenant_id: str
    scope_kind: ExternalChannelConversationScopeKind
    provider_channel_id: str
    provider_parent_channel_id: str | None
    provider_thread_key: str | None
    delivery_thread_key: str | None
    provider_resource_key: str
    source_resource_id: str
    conversation_position_id: str
    principal_id: str
    trigger_provider_message_key: str
    trigger_provider_message_id: str
    trigger_position: str
    provider_user_id: str | None
    invocation: bool
    invocation_id: str
    initial_title_eligible: bool


class ExternalChannelIngressAdmission(_Record):
    """Idempotent queue admission result."""

    owner: ExternalChannelIngressOwner
    item: ExternalChannelIngressItem
    created: bool
    replaced_stale_owner: bool


class ExternalChannelIngressLeaseClaim(_Record):
    """One fenced conversation-owner drain lease."""

    owner: ExternalChannelIngressOwner


class ExternalChannelIngressBatch(_Record):
    """One ordered processing claim under a fenced owner lease."""

    owner_id: str
    target_resource_id: str
    binding_id: str
    session_id: str
    batch_id: str
    lease_owner: str
    lease_generation: int
    items: tuple[ExternalChannelIngressItem, ...]


class ExternalChannelIngressCorrelation(_Record):
    """Active trigger identity used to authorize one provider message."""

    invocation_id: str
    principal_id: str


class ExternalChannelIngressDiagnosticCounts(_Record):
    """Bounded active-item counts by queue state."""

    pending: int
    processing: int
    retry_waiting: int

    @property
    def total(self) -> int:
        """Return the total active backlog."""
        return self.pending + self.processing + self.retry_waiting


class ExternalChannelIngressDiagnosticItem(_Record):
    """Content-free diagnostic projection for one active ingress item."""

    id: str
    owner_id: str
    session_id: str | None
    provider: ExternalChannelProvider
    connection_id: str
    owner_ready: bool
    preparation_attempt_count: int
    preparation_next_attempt_at: datetime.datetime | None
    state: ExternalChannelIngressItemState
    attempt_count: int
    batch_id: str | None
    next_attempt_at: datetime.datetime | None
    processing_owner: str | None
    processing_generation: int | None
    item_age_seconds: int
    owner_age_seconds: int
    lease_owner: str | None
    lease_generation: int
    lease_expires_at: datetime.datetime | None
    current_batch_id: str | None
    current_batch_started_at: datetime.datetime | None


class ExternalChannelIngressDiagnosticSnapshot(_Record):
    """Read-only active queue snapshot with no provider content."""

    observed_at: datetime.datetime
    owner_count: int
    counts: ExternalChannelIngressDiagnosticCounts
    oldest_queue_age_seconds: int | None
    items: tuple[ExternalChannelIngressDiagnosticItem, ...]
    truncated: bool
