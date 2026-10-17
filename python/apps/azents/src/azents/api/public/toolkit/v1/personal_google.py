"""User-global Google setup retaining the common reviewed publication lifecycle."""

from typing import Annotated

from fastapi import APIRouter, Depends, Response

from azents.core.auth.deps import CurrentUser, get_current_user
from azents.core.google_oauth import GooglePersonalSubject
from azents.core.google_system_setting import GooglePreparation
from azents.core.toolkit_ownership import ToolkitOwnerKind, UserToolkitOwner
from azents.services.google_oauth.data import (
    GoogleCancelOutput,
    GoogleConnectInput,
    GoogleConnectionOutput,
    GoogleConnectOutput,
    GooglePublishedOutput,
    GoogleReview,
)
from azents.services.google_oauth.service import GoogleOAuthService

from .google import (
    GoogleConfirmRequest,
    GoogleExchangeRequest,
    GoogleReconnectConfirmRequest,
    GoogleRoute,
    _errors,
)

router = APIRouter(route_class=GoogleRoute)
Account = Annotated[CurrentUser, Depends(get_current_user)]
Service = Annotated[GoogleOAuthService, Depends(GoogleOAuthService)]


def _subject(account: CurrentUser) -> GooglePersonalSubject:
    return GooglePersonalSubject(
        user_id=account.user_id,
        session_id=account.session_id,
        owner=UserToolkitOwner(kind=ToolkitOwnerKind.USER, user_id=account.user_id),
    )


@router.get("/personal/google/preparation")
async def personal_google_preparation(
    account: Account, service: Service
) -> GooglePreparation:
    """Expose common operator registration readiness to the exact active account."""
    with _errors():
        return await service.preparation(_subject(account))


@router.post("/personal/google/connect")
async def personal_google_connect(
    account: Account, service: Service, body: GoogleConnectInput
) -> GoogleConnectOutput:
    """Stage a personal setup without publishing a Toolkit or credential."""
    with _errors():
        return await service.connect(_subject(account), body, target_toolkit_id=None)


@router.post("/personal-toolkit-configs/{toolkit_id}/google/reconnect")
async def personal_google_reconnect(
    account: Account, service: Service, toolkit_id: str, body: GoogleConnectInput
) -> GoogleConnectOutput:
    """Reconnect the exact User-owned target with common reviewed identity flow."""
    with _errors():
        return await service.connect(
            _subject(account), body, target_toolkit_id=toolkit_id
        )


@router.post("/personal/google/exchange")
async def personal_google_exchange(
    account: Account, service: Service, body: GoogleExchangeRequest
) -> GoogleReview:
    """Verify exact personal callback state before exchanging or staging credentials."""
    with _errors():
        return await service.exchange(
            _subject(account), code=body.code, state=body.state
        )


@router.get("/personal/google/attempts/{attempt_id}")
async def personal_google_review(
    account: Account, service: Service, attempt_id: str
) -> GoogleReview:
    """Review verified grant evidence without exposing candidate credentials."""
    with _errors():
        return await service.review(_subject(account), attempt_id)


@router.post("/personal/google/attempts/{attempt_id}/confirm")
async def personal_google_confirm(
    account: Account, service: Service, attempt_id: str, body: GoogleConfirmRequest
) -> GooglePublishedOutput:
    """Publish a canonical User-owned Toolkit after reviewed confirmation."""
    with _errors():
        return await service.confirm(
            _subject(account), attempt_id=attempt_id, settings=body.settings
        )


@router.post("/personal/google/attempts/{attempt_id}/reconnect-confirm")
async def personal_google_reconnect_confirm(
    account: Account,
    service: Service,
    attempt_id: str,
    body: GoogleReconnectConfirmRequest,
) -> GooglePublishedOutput:
    """Replace the grant while preserving personal allowance and other settings."""
    with _errors():
        return await service.confirm(
            _subject(account), attempt_id=attempt_id, settings=body.settings
        )


@router.get("/personal/google/attempts/{attempt_id}/outcome")
async def personal_google_outcome(
    account: Account, service: Service, attempt_id: str
) -> GooglePublishedOutput:
    """Recover uncertain publication under its exact original owner context."""
    with _errors():
        return await service.outcome(_subject(account), attempt_id)


@router.delete("/personal/google/attempts/{attempt_id}")
async def personal_google_cancel(
    account: Account, service: Service, attempt_id: str
) -> GoogleCancelOutput:
    """Abandon unpublished secrets while retaining committed publication evidence."""
    with _errors():
        return await service.cancel(_subject(account), attempt_id)


@router.get("/personal-toolkit-configs/{toolkit_id}/google/connection")
async def personal_google_status(
    account: Account, service: Service, toolkit_id: str
) -> GoogleConnectionOutput:
    """Return the same redacted grant/readiness information as other owners."""
    with _errors():
        return await service.status(_subject(account), toolkit_id)


@router.delete("/personal-toolkit-configs/{toolkit_id}/google/connection")
async def personal_google_disconnect(
    account: Account, service: Service, toolkit_id: str
) -> Response:
    """Delete personal Google credentials and defeat pending stale reconnects."""
    with _errors():
        await service.disconnect(_subject(account), toolkit_id)
    return Response(status_code=204)
