"""External account link public API schemas."""

import datetime

from pydantic import BaseModel

from azents.core.enums import ExternalChannelProvider
from azents.core.external_account_link import (
    EXTERNAL_ACCOUNT_LINK_MAX_CANDIDATES,
    EXTERNAL_ACCOUNT_LINK_MAX_INVALID_CODES,
    ExternalAccountLinkCandidateCreated,
    ExternalAccountLinkCandidateStatus,
    ExternalAccountLinkCandidateView,
    ExternalAccountLinkOriginState,
    ExternalAccountLinkOriginView,
    ExternalAccountLinkReturnContext,
    ExternalAccountLinkReturnKind,
    ExternalAccountLinkState,
    ExternalAccountLinkView,
)


class AccountLinkResponse(BaseModel):
    """Personal Workspace external account link."""

    id: str
    workspace_id: str
    workspace_name: str
    workspace_handle: str
    provider: ExternalChannelProvider
    identity_scope: str
    provider_tenant_display_label: str
    provider_display_label: str
    linked_at: datetime.datetime
    state: ExternalAccountLinkState

    @classmethod
    def from_view(cls, view: ExternalAccountLinkView) -> "AccountLinkResponse":
        """Build an API response from a detached service projection."""
        return cls(
            id=view.id,
            workspace_id=view.workspace_id,
            workspace_name=view.workspace_name,
            workspace_handle=view.workspace_handle,
            provider=view.provider,
            identity_scope=view.identity_scope,
            provider_tenant_display_label=view.provider_tenant_display_label,
            provider_display_label=view.provider_display_label,
            linked_at=view.linked_at,
            state=view.state,
        )


class AccountLinkListResponse(BaseModel):
    """Current User's Workspace external account links."""

    items: list[AccountLinkResponse]


class AccountLinkReturnContextResponse(BaseModel):
    """Sanitized provider-native return navigation."""

    kind: ExternalAccountLinkReturnKind
    provider_tenant_display_label: str
    provider_url: str | None

    @classmethod
    def from_view(
        cls,
        view: ExternalAccountLinkReturnContext,
    ) -> "AccountLinkReturnContextResponse":
        """Build a provider return response."""
        return cls(
            kind=view.kind,
            provider_tenant_display_label=view.provider_tenant_display_label,
            provider_url=view.provider_url,
        )


class AccountLinkOriginResponse(BaseModel):
    """Browser-safe original provider confirmation context."""

    id: str
    workspace_id: str
    workspace_name: str
    workspace_handle: str
    provider: ExternalChannelProvider
    identity_scope: str
    provider_tenant_id: str
    provider_tenant_display_label: str
    provider_display_label: str
    expires_at: datetime.datetime
    state: ExternalAccountLinkOriginState
    candidate_count: int
    candidate_limit: int
    invalid_code_count: int
    invalid_code_limit: int
    return_context: AccountLinkReturnContextResponse

    @classmethod
    def from_view(
        cls,
        view: ExternalAccountLinkOriginView,
    ) -> "AccountLinkOriginResponse":
        """Build an API response from a detached origin projection."""
        return cls(
            id=view.id,
            workspace_id=view.workspace_id,
            workspace_name=view.workspace_name,
            workspace_handle=view.workspace_handle,
            provider=view.provider,
            identity_scope=view.identity_scope,
            provider_tenant_id=view.provider_tenant_id,
            provider_tenant_display_label=view.provider_tenant_display_label,
            provider_display_label=view.provider_display_label,
            expires_at=view.expires_at,
            state=view.state,
            candidate_count=view.candidate_count,
            candidate_limit=EXTERNAL_ACCOUNT_LINK_MAX_CANDIDATES,
            invalid_code_count=view.invalid_code_count,
            invalid_code_limit=EXTERNAL_ACCOUNT_LINK_MAX_INVALID_CODES,
            return_context=AccountLinkReturnContextResponse.from_view(
                view.return_context
            ),
        )


class AccountLinkCandidateResponse(BaseModel):
    """Status-only immutable candidate response."""

    id: str
    origin_id: str
    expires_at: datetime.datetime
    status: ExternalAccountLinkCandidateStatus
    link_id: str | None

    @classmethod
    def from_view(
        cls,
        view: ExternalAccountLinkCandidateView,
    ) -> "AccountLinkCandidateResponse":
        """Build a status-only response."""
        return cls(
            id=view.id,
            origin_id=view.origin_id,
            expires_at=view.expires_at,
            status=view.status,
            link_id=view.link_id,
        )


class AccountLinkCandidateCreatedResponse(BaseModel):
    """One-time candidate response containing the plaintext code."""

    id: str
    origin_id: str
    code: str
    expires_at: datetime.datetime
    status: ExternalAccountLinkCandidateStatus

    @classmethod
    def from_view(
        cls,
        view: ExternalAccountLinkCandidateCreated,
    ) -> "AccountLinkCandidateCreatedResponse":
        """Build the one-time candidate response."""
        return cls(
            id=view.id,
            origin_id=view.origin_id,
            code=view.code,
            expires_at=view.expires_at,
            status=view.status,
        )


class AccountLinkErrorDetail(BaseModel):
    """Stable expected account-link error detail."""

    code: str
    message: str
