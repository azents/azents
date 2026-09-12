"""External account link public API routes."""

import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Response

from azents.core.auth.deps import CurrentUser, get_current_user, get_elevated_user
from azents.core.external_account_link import (
    ExternalAccountLinkBusy,
    ExternalAccountLinkCandidateNotReady,
    ExternalAccountLinkCandidateTerminal,
    ExternalAccountLinkConflict,
    ExternalAccountLinkError,
    ExternalAccountLinkExpired,
    ExternalAccountLinkMembershipRequired,
    ExternalAccountLinkNotFound,
    ExternalAccountLinkUnavailable,
)
from azents.services.external_account_link import ExternalAccountLinkService

from .account_link_data import (
    AccountLinkCandidateCreatedResponse,
    AccountLinkCandidateResponse,
    AccountLinkListResponse,
    AccountLinkOriginResponse,
    AccountLinkResponse,
)

router = APIRouter()


@router.get("/account-links")
async def list_account_links(
    current_user: Annotated[CurrentUser, Depends(get_current_user)],
    service: Annotated[ExternalAccountLinkService, Depends()],
) -> AccountLinkListResponse:
    """List the current User's own Workspace external account links."""
    try:
        links = await service.list_links(
            user_id=current_user.user_id,
            now=_utcnow(),
        )
    except ExternalAccountLinkError as error:
        _translate_error(error)
    return AccountLinkListResponse(
        items=[AccountLinkResponse.from_view(link) for link in links]
    )


@router.delete("/account-links/{link_id}")
async def unlink_account_link(
    current_user: Annotated[CurrentUser, Depends(get_elevated_user)],
    service: Annotated[ExternalAccountLinkService, Depends()],
    *,
    link_id: str,
) -> AccountLinkResponse:
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
    return AccountLinkResponse.from_view(link)


@router.get("/account-link-origins/{origin_id}")
async def get_account_link_origin(
    current_user: Annotated[CurrentUser, Depends(get_current_user)],
    service: Annotated[ExternalAccountLinkService, Depends()],
    *,
    origin_id: str,
) -> AccountLinkOriginResponse:
    """Load bounded provider identity and Workspace confirmation context."""
    try:
        origin = await service.get_origin(
            user_id=current_user.user_id,
            origin_id=origin_id,
            now=_utcnow(),
        )
    except ExternalAccountLinkError as error:
        _translate_error(error)
    return AccountLinkOriginResponse.from_view(origin)


@router.post("/account-link-origins/{origin_id}/candidates")
async def create_account_link_candidate(
    current_user: Annotated[CurrentUser, Depends(get_elevated_user)],
    service: Annotated[ExternalAccountLinkService, Depends()],
    response: Response,
    *,
    origin_id: str,
) -> AccountLinkCandidateCreatedResponse:
    """Create one immutable elevated browser candidate and return its code once."""
    try:
        candidate = await service.create_candidate(
            user_id=current_user.user_id,
            auth_session_id=current_user.session_id,
            origin_id=origin_id,
            now=_utcnow(),
        )
    except ExternalAccountLinkError as error:
        _translate_error(error)
    response.headers["Cache-Control"] = "no-store"
    return AccountLinkCandidateCreatedResponse.from_view(candidate)


@router.get("/account-link-candidates/{candidate_id}")
async def get_account_link_candidate(
    current_user: Annotated[CurrentUser, Depends(get_current_user)],
    service: Annotated[ExternalAccountLinkService, Depends()],
    *,
    candidate_id: str,
) -> AccountLinkCandidateResponse:
    """Get status for an exact current User/auth-Session candidate."""
    try:
        candidate = await service.get_candidate(
            user_id=current_user.user_id,
            auth_session_id=current_user.session_id,
            candidate_id=candidate_id,
            now=_utcnow(),
        )
    except ExternalAccountLinkError as error:
        _translate_error(error)
    return AccountLinkCandidateResponse.from_view(candidate)


@router.post("/account-link-candidates/{candidate_id}/confirm")
async def confirm_account_link_candidate(
    current_user: Annotated[CurrentUser, Depends(get_elevated_user)],
    service: Annotated[ExternalAccountLinkService, Depends()],
    *,
    candidate_id: str,
) -> AccountLinkResponse:
    """Atomically finalize an exact elevated browser candidate."""
    try:
        link = await service.confirm_candidate(
            user_id=current_user.user_id,
            auth_session_id=current_user.session_id,
            candidate_id=candidate_id,
            now=_utcnow(),
        )
    except ExternalAccountLinkError as error:
        _translate_error(error)
    return AccountLinkResponse.from_view(link)


@router.delete("/account-link-candidates/{candidate_id}")
async def cancel_account_link_candidate(
    current_user: Annotated[CurrentUser, Depends(get_current_user)],
    service: Annotated[ExternalAccountLinkService, Depends()],
    *,
    candidate_id: str,
) -> AccountLinkCandidateResponse:
    """Cancel one exact current User/auth-Session candidate."""
    try:
        candidate = await service.cancel_candidate(
            user_id=current_user.user_id,
            auth_session_id=current_user.session_id,
            candidate_id=candidate_id,
            now=_utcnow(),
        )
    except ExternalAccountLinkError as error:
        _translate_error(error)
    return AccountLinkCandidateResponse.from_view(candidate)


def _translate_error(error: Exception) -> None:
    """Translate expected service failures to stable safe HTTP details."""
    if isinstance(error, ExternalAccountLinkNotFound):
        raise _http_error(404, "resource_not_found", "Account link resource not found.")
    if isinstance(error, ExternalAccountLinkMembershipRequired):
        raise _http_error(
            403,
            "membership_required",
            "Workspace membership is required to connect this account.",
        )
    if isinstance(error, ExternalAccountLinkExpired):
        raise _http_error(410, "expired", "This account link flow has expired.")
    if isinstance(error, ExternalAccountLinkCandidateNotReady):
        raise _http_error(
            409,
            "candidate_not_ready",
            "Complete the original provider account proof first.",
        )
    if isinstance(error, ExternalAccountLinkCandidateTerminal):
        raise _http_error(
            409,
            "candidate_terminal",
            "This account link candidate can no longer be used.",
        )
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
