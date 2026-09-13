"""External account link public API schemas."""

import datetime

from pydantic import BaseModel

from azents.core.enums import ExternalChannelProvider
from azents.core.external_account_link import (
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


class GlobalAccountLinkUnlinkResponse(BaseModel):
    """Terminal result for disconnecting one global provider identity."""

    id: str
    state: ExternalAccountLinkState

    @classmethod
    def from_view(
        cls,
        view: ExternalAccountLinkView,
    ) -> "GlobalAccountLinkUnlinkResponse":
        """Build a sanitized terminal disconnect response."""
        return cls(id=view.id, state=view.state)


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


class AccountLinkErrorDetail(BaseModel):
    """Stable expected account-link error detail."""

    code: str
    message: str
