"""External account link public API routes."""

import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Response

from azents.core.auth.deps import CurrentUser, get_current_user, get_elevated_user
from azents.core.enums import ExternalChannelProvider
from azents.core.external_account_link import (
    ExternalAccountLinkBusy,
    ExternalAccountLinkConflict,
    ExternalAccountLinkError,
    ExternalAccountLinkNotFound,
    ExternalAccountLinkUnavailable,
    ExternalAccountOAuthAlreadyConsumed,
    ExternalAccountOAuthAuthSessionMismatch,
    ExternalAccountOAuthConfigurationChanged,
    ExternalAccountOAuthExpired,
    ExternalAccountOAuthInvalidAttempt,
    ExternalAccountOAuthInvalidCallback,
    ExternalAccountOAuthProviderMismatch,
    ExternalAccountOAuthProviderRejected,
    ExternalAccountOAuthProviderUnavailable,
)
from azents.services.external_account_link import ExternalAccountLinkService
from azents.services.external_account_oauth.link_service import (
    ExternalAccountOAuthService,
)
from azents.services.external_account_oauth_system_setting.service import (
    ExternalAccountOAuthSystemSettingService,
)

from .account_link_data import (
    AccountLinkOAuthExchangeRequest,
    AccountLinkOAuthStartResponse,
    AccountLinkProviderAvailabilityListResponse,
    AccountLinkProviderAvailabilityResponse,
    GlobalAccountLinkListResponse,
    GlobalAccountLinkResponse,
    GlobalAccountLinkUnlinkResponse,
)

router = APIRouter()


@router.get("/account-links")
async def list_account_links(
    current_user: Annotated[CurrentUser, Depends(get_current_user)],
    service: Annotated[ExternalAccountLinkService, Depends()],
) -> GlobalAccountLinkListResponse:
    """List the current User's active global provider identities."""
    try:
        links = await service.list_links(
            user_id=current_user.user_id,
            now=_utcnow(),
        )
    except ExternalAccountLinkError as error:
        _translate_error(error)
    return GlobalAccountLinkListResponse(
        items=[GlobalAccountLinkResponse.from_view(link) for link in links]
    )


@router.get("/account-links/providers")
async def list_account_link_providers(
    current_user: Annotated[CurrentUser, Depends(get_current_user)],
    settings: Annotated[ExternalAccountOAuthSystemSettingService, Depends()],
) -> AccountLinkProviderAvailabilityListResponse:
    """List redacted provider availability for authenticated account linking."""
    del current_user
    details = [
        await settings.get_detail(provider.value)
        for provider in ExternalChannelProvider
    ]
    return AccountLinkProviderAvailabilityListResponse(
        items=[
            AccountLinkProviderAvailabilityResponse.from_detail(detail)
            for detail in details
        ]
    )


@router.post("/account-links/oauth/{provider}/start")
async def start_account_link_oauth(
    current_user: Annotated[CurrentUser, Depends(get_current_user)],
    service: Annotated[ExternalAccountOAuthService, Depends()],
    response: Response,
    *,
    provider: ExternalChannelProvider,
) -> AccountLinkOAuthStartResponse:
    """Start one authenticated provider identity OAuth attempt."""
    try:
        result = await service.start(
            user_id=current_user.user_id,
            auth_session_id=current_user.session_id,
            provider=provider,
        )
    except ExternalAccountLinkError as error:
        _translate_error(error)
    response.headers["Cache-Control"] = "no-store"
    return AccountLinkOAuthStartResponse(
        authorization_url=result.authorization_url,
    )


@router.post("/account-links/oauth/{provider}/exchange")
async def exchange_account_link_oauth(
    current_user: Annotated[CurrentUser, Depends(get_current_user)],
    service: Annotated[ExternalAccountOAuthService, Depends()],
    body: AccountLinkOAuthExchangeRequest,
    response: Response,
    *,
    provider: ExternalChannelProvider,
) -> GlobalAccountLinkResponse:
    """Exchange one authenticated callback and finalize its global link."""
    try:
        link = await service.exchange(
            user_id=current_user.user_id,
            auth_session_id=current_user.session_id,
            provider=provider,
            code=body.code,
            state=body.state,
        )
    except ExternalAccountLinkError as error:
        _translate_error(error)
    response.headers["Cache-Control"] = "no-store"
    return GlobalAccountLinkResponse.from_view(link)


@router.delete("/account-links/{link_id}")
async def unlink_account_link(
    current_user: Annotated[CurrentUser, Depends(get_elevated_user)],
    service: Annotated[ExternalAccountLinkService, Depends()],
    *,
    link_id: str,
) -> GlobalAccountLinkUnlinkResponse:
    """Terminally disconnect one elevated owner's link."""
    try:
        link = await service.unlink(
            user_id=current_user.user_id,
            auth_session_id=current_user.session_id,
            link_id=link_id,
            now=_utcnow(),
        )
    except ExternalAccountLinkError as error:
        _translate_error(error)
    return GlobalAccountLinkUnlinkResponse.from_view(link)


def _translate_error(error: Exception) -> None:
    """Translate expected service failures to stable safe HTTP details."""
    if isinstance(error, ExternalAccountOAuthProviderUnavailable):
        raise _http_error(
            409,
            "provider_unavailable",
            "This provider is not currently available for account connection.",
        )
    if isinstance(error, ExternalAccountOAuthExpired):
        raise _http_error(
            410,
            "expired",
            "This account connection attempt has expired. Start again.",
        )
    if isinstance(error, ExternalAccountOAuthAlreadyConsumed):
        raise _http_error(
            409,
            "already_consumed",
            "This account connection attempt can no longer be used.",
        )
    if isinstance(error, ExternalAccountOAuthAuthSessionMismatch):
        raise _http_error(
            409,
            "auth_session_mismatch",
            "Sign in again and restart account connection.",
        )
    if isinstance(error, ExternalAccountOAuthProviderMismatch):
        raise _http_error(
            400,
            "provider_mismatch",
            "This account connection attempt belongs to another provider.",
        )
    if isinstance(error, ExternalAccountOAuthInvalidCallback):
        raise _http_error(
            400,
            "invalid_callback",
            "The provider callback does not match this account connection.",
        )
    if isinstance(error, ExternalAccountOAuthInvalidAttempt):
        raise _http_error(
            400,
            "invalid_attempt",
            "This account connection attempt is invalid or must be restarted.",
        )
    if isinstance(error, ExternalAccountOAuthConfigurationChanged):
        raise _http_error(
            409,
            "configuration_changed",
            "Provider OAuth settings changed. Restart account connection.",
        )
    if isinstance(error, ExternalAccountOAuthProviderRejected):
        raise _http_error(
            400,
            "provider_rejected",
            "The provider could not verify this account. Restart account connection.",
        )
    if isinstance(error, ExternalAccountLinkNotFound):
        raise _http_error(404, "resource_not_found", "Account link resource not found.")
    if isinstance(error, ExternalAccountLinkBusy):
        raise _http_error(
            409,
            "busy",
            "Account linking is busy. Please try again.",
        )
    if isinstance(error, ExternalAccountLinkUnavailable):
        raise _http_error(
            409,
            "unavailable",
            "The account link scope is no longer available.",
        )
    if isinstance(error, ExternalAccountLinkConflict):
        raise _http_error(
            409,
            "conflict",
            "This external account cannot be connected.",
        )
    raise RuntimeError("Unhandled external account link error.") from error


def _http_error(status_code: int, code: str, message: str) -> HTTPException:
    """Build one structured expected API error."""
    return HTTPException(
        status_code=status_code,
        detail={"code": code, "message": message},
    )


def _utcnow() -> datetime.datetime:
    """Return a timezone-aware current timestamp."""
    return datetime.datetime.now(datetime.UTC)
