"""Detached data for external account link persistence."""

import dataclasses
import datetime

from azents.core.enums import ExternalChannelProvider
from azents.core.external_account_link import (
    ExternalAccountLinkCandidateStatus,
    ExternalAccountLinkOriginState,
    ExternalAccountLinkState,
)


@dataclasses.dataclass(frozen=True)
class ExternalAccountLink:
    """Persisted external account link."""

    id: str
    workspace_id: str
    user_id: str
    provider: ExternalChannelProvider
    identity_scope: str
    provider_user_id: str
    provider_tenant_display_label: str
    provider_display_label: str
    linked_at: datetime.datetime
    revoked_at: datetime.datetime | None


@dataclasses.dataclass(frozen=True)
class ExternalAccountLinkProjection:
    """Personal link projection joined with Workspace membership."""

    link: ExternalAccountLink
    workspace_name: str
    workspace_handle: str
    state: ExternalAccountLinkState


@dataclasses.dataclass(frozen=True)
class ExternalAccountLinkOrigin:
    """Persisted provider origin projection."""

    id: str
    workspace_id: str
    workspace_name: str
    workspace_handle: str
    connection_id: str
    connection_configuration_generation: int
    principal_id: str
    provider: ExternalChannelProvider
    identity_scope: str
    provider_tenant_id: str
    provider_tenant_display_label: str
    provider_user_id: str
    provider_display_label: str
    provider_channel_id: str
    provider_thread_id: str | None
    expires_at: datetime.datetime
    state: ExternalAccountLinkOriginState
    candidate_count: int
    invalid_code_count: int


@dataclasses.dataclass(frozen=True)
class ExternalAccountLinkCandidate:
    """Persisted immutable candidate projection."""

    id: str
    origin_id: str
    user_id: str
    auth_session_id: str
    expires_at: datetime.datetime
    status: ExternalAccountLinkCandidateStatus
    link_id: str | None
