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
from azents.services.external_account_oauth_system_setting.data import (
    ExternalAccountOAuthDetail,
    ExternalAccountOAuthEffectiveStatus,
)


class GlobalAccountLinkResponse(BaseModel):
    """Active global provider identity owned by the current User."""

    id: str
    provider: ExternalChannelProvider
    identity_scope: str
    provider_user_id: str
    provider_tenant_display_label: str | None
    provider_display_label: str
    linked_at: datetime.datetime

    @classmethod
    def from_view(cls, view: ExternalAccountLinkView) -> "GlobalAccountLinkResponse":
        """Build a Workspace-free global link response."""
        return cls(
            id=view.id,
            provider=view.provider,
            identity_scope=view.identity_scope,
            provider_user_id=view.provider_user_id,
            provider_tenant_display_label=view.provider_tenant_display_label,
            provider_display_label=view.provider_display_label,
            linked_at=view.linked_at,
        )


class GlobalAccountLinkListResponse(BaseModel):
    """Active global provider identities owned by the current User."""

    items: list[GlobalAccountLinkResponse]


class AccountLinkProviderAvailabilityResponse(BaseModel):
    """Redacted availability of one provider identity OAuth Section."""

    provider: ExternalChannelProvider
    status: ExternalAccountOAuthEffectiveStatus
    available: bool
    callback_url: str | None

    @classmethod
    def from_detail(
        cls,
        detail: ExternalAccountOAuthDetail,
    ) -> "AccountLinkProviderAvailabilityResponse":
        """Build a redacted provider availability response."""
        return cls(
            provider=ExternalChannelProvider(detail.provider),
            status=detail.effective_status,
            available=detail.effective_status
            is ExternalAccountOAuthEffectiveStatus.READY,
            callback_url=detail.callback_url,
        )


class AccountLinkProviderAvailabilityListResponse(BaseModel):
    """Redacted provider availability list."""

    items: list[AccountLinkProviderAvailabilityResponse]


class AccountLinkOAuthStartResponse(BaseModel):
    """Fixed-provider authorization URL for one durable OAuth attempt."""

    authorization_url: str


class AccountLinkOAuthExchangeRequest(BaseModel):
    """Authenticated callback exchange payload."""

    code: str
    state: str


class AccountLinkResponse(BaseModel):
    """Personal Workspace external account link."""

    id: str
    workspace_id: str | None
    workspace_name: str | None
    workspace_handle: str | None
    provider: ExternalChannelProvider
    identity_scope: str
    provider_tenant_display_label: str | None
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
