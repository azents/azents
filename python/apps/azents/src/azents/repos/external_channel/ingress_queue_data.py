"""Typed data contracts for durable External Channel ingress queues."""

import datetime

from pydantic import BaseModel, ConfigDict

from azents.core.enums import (
    ExternalChannelConversationScopeKind,
    ExternalChannelIngressAuthorityKind,
    ExternalChannelIngressItemState,
    ExternalChannelIngressProfile,
    ExternalChannelProvider,
)


class _Record(BaseModel):
    """Immutable repository record with ORM attribute support."""

    model_config = ConfigDict(frozen=True, from_attributes=True)


class ExternalChannelIngressSession(_Record):
    """One active Session-scoped drain lifecycle."""

    session_id: str
    lease_owner: str | None
    lease_generation: int
    lease_acquired_at: datetime.datetime | None
    lease_expires_at: datetime.datetime | None
    first_batch_pending: bool
    current_batch_id: str | None
    current_batch_started_at: datetime.datetime | None
    created_at: datetime.datetime
    updated_at: datetime.datetime


class ExternalChannelIngressItem(_Record):
    """One active content-free provider trigger."""

    id: str
    session_id: str
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
    resource_id: str
    binding_id: str
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
    """Content-free queue admission payload."""

    session_id: str
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
    resource_id: str
    binding_id: str
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

    session: ExternalChannelIngressSession
    item: ExternalChannelIngressItem
    created: bool


class ExternalChannelIngressLeaseClaim(_Record):
    """One fenced Session drain lease."""

    session: ExternalChannelIngressSession


class ExternalChannelIngressBatch(_Record):
    """One ordered processing claim under a fenced drain lease."""

    session_id: str
    batch_id: str
    lease_owner: str
    lease_generation: int
    items: tuple[ExternalChannelIngressItem, ...]


class ExternalChannelIngressCorrelation(_Record):
    """Active trigger identity used to authorize one provider message."""

    invocation_id: str
    principal_id: str
