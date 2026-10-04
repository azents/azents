"""Canonical shared external channel impact contracts."""

import datetime

from pydantic import BaseModel, ConfigDict


class _Record(BaseModel):
    """Immutable repository data base with ORM attribute support."""

    model_config = ConfigDict(frozen=True, from_attributes=True)


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
