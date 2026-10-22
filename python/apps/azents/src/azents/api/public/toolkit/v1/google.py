"""Ownership-symmetric Google setup; credentials never reach response projections."""

import contextlib
from collections.abc import Callable, Coroutine, Iterator
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.routing import APIRoute
from pydantic import BaseModel, ConfigDict, Field

from azents.core.auth.deps import WorkspaceMember, get_workspace_member
from azents.core.google_oauth import (
    GoogleFinalSettings,
    GoogleOAuthError,
    GoogleReconnectSettings,
    GoogleSubject,
)
from azents.core.google_system_setting import GooglePreparation
from azents.services.google_oauth.data import (
    GoogleCancelOutput,
    GoogleConnectInput,
    GoogleConnectionOutput,
    GoogleConnectOutput,
    GooglePickerTokenInput,
    GooglePickerTokenOutput,
    GooglePublishedOutput,
    GoogleReview,
    GoogleServicesUpdateInput,
)
from azents.services.google_oauth.picker import GooglePickerService
from azents.services.google_oauth.service import GoogleOAuthService


class GoogleRoute(APIRoute):
    """Remove authorization code/state/body values from validation diagnostics."""

    def get_route_handler(self) -> Callable[[Request], Coroutine[Any, Any, Response]]:
        handler = super().get_route_handler()

        async def safe(request: Request) -> Response:
            try:
                return await handler(request)
            except RequestValidationError:
                raise HTTPException(
                    422,
                    detail=[
                        {
                            "type": "value_error",
                            "loc": ["body"],
                            "msg": "Invalid Google authorization request.",
                        }
                    ],
                ) from None

        return safe


router = APIRouter(route_class=GoogleRoute)
Member = Annotated[WorkspaceMember, Depends(get_workspace_member)]
Service = Annotated[GoogleOAuthService, Depends()]
Picker = Annotated[GooglePickerService, Depends()]


class GoogleExchangeRequest(BaseModel):
    """Transient code and encrypted state, not caller-selected target identity."""

    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)
    code: str = Field(min_length=1, max_length=8192, repr=False)
    state: str = Field(min_length=1, max_length=16384, repr=False)


class GoogleConfirmRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)
    settings: GoogleFinalSettings


class GoogleReconnectConfirmRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)
    settings: GoogleReconnectSettings


@contextlib.contextmanager
def _errors() -> Iterator[None]:
    try:
        yield
    except GoogleOAuthError as error:
        status = (
            401
            if error.code == "not_authenticated"
            else 403
            if error.code == "forbidden"
            else 404
            if error.code == "not_found"
            else 409
            if error.code in {"stale", "expired"}
            else 422
        )
        raise HTTPException(
            status_code=status,
            detail={"code": error.code, "message": str(error)},
            headers={"WWW-Authenticate": "Bearer"} if status == 401 else None,
        ) from None


def _subject(member: WorkspaceMember, agent_id: str | None) -> GoogleSubject:
    return GoogleSubject(
        member.user_id, member.session_id, member.workspace_id, agent_id
    )


@router.get("/workspaces/{handle}/google/preparation")
async def shared_google_preparation(
    member: Member, service: Service
) -> GooglePreparation:
    with _errors():
        return await service.preparation(_subject(member, None))


@router.get("/workspaces/{handle}/agents/{agent_id}/google/preparation")
async def agent_google_preparation(
    member: Member,
    service: Service,
    agent_id: str,
) -> GooglePreparation:
    with _errors():
        return await service.preparation(_subject(member, agent_id))


@router.post("/workspaces/{handle}/google/connect")
async def shared_google_connect(
    member: Member,
    service: Service,
    body: GoogleConnectInput,
) -> GoogleConnectOutput:
    with _errors():
        return await service.connect(
            _subject(member, None), body, target_toolkit_id=None
        )


@router.post("/workspaces/{handle}/agents/{agent_id}/google/connect")
async def agent_google_connect(
    member: Member,
    service: Service,
    body: GoogleConnectInput,
    agent_id: str,
) -> GoogleConnectOutput:
    with _errors():
        return await service.connect(
            _subject(member, agent_id), body, target_toolkit_id=None
        )


@router.post("/workspaces/{handle}/toolkit-configs/{toolkit_id}/google/reconnect")
async def shared_google_reconnect(
    member: Member,
    service: Service,
    body: GoogleConnectInput,
    toolkit_id: str,
) -> GoogleConnectOutput:
    with _errors():
        return await service.connect(
            _subject(member, None), body, target_toolkit_id=toolkit_id
        )


@router.post(
    "/workspaces/{handle}/agents/{agent_id}/toolkit-configs/{toolkit_id}/google/reconnect"
)
async def agent_google_reconnect(
    member: Member,
    service: Service,
    body: GoogleConnectInput,
    agent_id: str,
    toolkit_id: str,
) -> GoogleConnectOutput:
    with _errors():
        return await service.connect(
            _subject(member, agent_id), body, target_toolkit_id=toolkit_id
        )


@router.post("/workspaces/{handle}/google/exchange")
async def shared_google_exchange(
    member: Member,
    service: Service,
    body: GoogleExchangeRequest,
) -> GoogleReview:
    with _errors():
        return await service.exchange(
            _subject(member, None), code=body.code, state=body.state
        )


@router.post("/workspaces/{handle}/agents/{agent_id}/google/exchange")
async def agent_google_exchange(
    member: Member,
    service: Service,
    body: GoogleExchangeRequest,
    agent_id: str,
) -> GoogleReview:
    with _errors():
        return await service.exchange(
            _subject(member, agent_id), code=body.code, state=body.state
        )


@router.get("/workspaces/{handle}/google/attempts/{attempt_id}")
async def shared_google_review(
    member: Member,
    service: Service,
    attempt_id: str,
) -> GoogleReview:
    with _errors():
        return await service.review(_subject(member, None), attempt_id)


@router.get("/workspaces/{handle}/agents/{agent_id}/google/attempts/{attempt_id}")
async def agent_google_review(
    member: Member,
    service: Service,
    attempt_id: str,
    agent_id: str,
) -> GoogleReview:
    with _errors():
        return await service.review(_subject(member, agent_id), attempt_id)


@router.post("/workspaces/{handle}/google/attempts/{attempt_id}/confirm")
async def shared_google_confirm(
    member: Member,
    service: Service,
    attempt_id: str,
    body: GoogleConfirmRequest,
) -> GooglePublishedOutput:
    with _errors():
        return await service.confirm(
            _subject(member, None), attempt_id=attempt_id, settings=body.settings
        )


@router.post(
    "/workspaces/{handle}/agents/{agent_id}/google/attempts/{attempt_id}/confirm"
)
async def agent_google_confirm(
    member: Member,
    service: Service,
    attempt_id: str,
    body: GoogleConfirmRequest,
    agent_id: str,
) -> GooglePublishedOutput:
    with _errors():
        return await service.confirm(
            _subject(member, agent_id), attempt_id=attempt_id, settings=body.settings
        )


@router.post("/workspaces/{handle}/google/attempts/{attempt_id}/reconnect-confirm")
async def shared_google_reconnect_confirm(
    member: Member,
    service: Service,
    attempt_id: str,
    body: GoogleReconnectConfirmRequest,
) -> GooglePublishedOutput:
    with _errors():
        return await service.confirm(
            _subject(member, None), attempt_id=attempt_id, settings=body.settings
        )


@router.post(
    "/workspaces/{handle}/agents/{agent_id}/google/attempts/{attempt_id}/reconnect-confirm"
)
async def agent_google_reconnect_confirm(
    member: Member,
    service: Service,
    attempt_id: str,
    body: GoogleReconnectConfirmRequest,
    agent_id: str,
) -> GooglePublishedOutput:
    with _errors():
        return await service.confirm(
            _subject(member, agent_id), attempt_id=attempt_id, settings=body.settings
        )


@router.get("/workspaces/{handle}/google/attempts/{attempt_id}/outcome")
async def shared_google_outcome(
    member: Member,
    service: Service,
    attempt_id: str,
) -> GooglePublishedOutput:
    with _errors():
        return await service.outcome(_subject(member, None), attempt_id)


@router.get(
    "/workspaces/{handle}/agents/{agent_id}/google/attempts/{attempt_id}/outcome"
)
async def agent_google_outcome(
    member: Member,
    service: Service,
    attempt_id: str,
    agent_id: str,
) -> GooglePublishedOutput:
    with _errors():
        return await service.outcome(_subject(member, agent_id), attempt_id)


@router.delete("/workspaces/{handle}/google/attempts/{attempt_id}")
async def shared_google_cancel(
    member: Member,
    service: Service,
    attempt_id: str,
) -> GoogleCancelOutput:
    with _errors():
        return await service.cancel(_subject(member, None), attempt_id)


@router.delete("/workspaces/{handle}/agents/{agent_id}/google/attempts/{attempt_id}")
async def agent_google_cancel(
    member: Member,
    service: Service,
    attempt_id: str,
    agent_id: str,
) -> GoogleCancelOutput:
    with _errors():
        return await service.cancel(_subject(member, agent_id), attempt_id)


@router.get("/workspaces/{handle}/toolkit-configs/{toolkit_id}/google/connection")
async def shared_google_status(
    member: Member,
    service: Service,
    toolkit_id: str,
) -> GoogleConnectionOutput:
    with _errors():
        return await service.status(_subject(member, None), toolkit_id)


@router.get(
    "/workspaces/{handle}/agents/{agent_id}/toolkit-configs/{toolkit_id}/google/connection"
)
async def agent_google_status(
    member: Member,
    service: Service,
    toolkit_id: str,
    agent_id: str,
) -> GoogleConnectionOutput:
    with _errors():
        return await service.status(_subject(member, agent_id), toolkit_id)


@router.post("/workspaces/{handle}/toolkit-configs/{toolkit_id}/google/picker-token")
async def shared_google_picker_token(
    member: Member,
    picker: Picker,
    toolkit_id: str,
    expected: GooglePickerTokenInput,
    response: Response,
) -> GooglePickerTokenOutput:
    response.headers["Cache-Control"] = "no-store"
    response.headers["Pragma"] = "no-cache"
    with _errors():
        return await picker.issue(_subject(member, None), toolkit_id, expected)


@router.post(
    "/workspaces/{handle}/agents/{agent_id}/toolkit-configs/{toolkit_id}/google/picker-token"
)
async def agent_google_picker_token(
    member: Member,
    picker: Picker,
    toolkit_id: str,
    agent_id: str,
    expected: GooglePickerTokenInput,
    response: Response,
) -> GooglePickerTokenOutput:
    response.headers["Cache-Control"] = "no-store"
    response.headers["Pragma"] = "no-cache"
    with _errors():
        return await picker.issue(_subject(member, agent_id), toolkit_id, expected)


@router.patch("/workspaces/{handle}/toolkit-configs/{toolkit_id}/google/services")
async def shared_google_services(
    member: Member,
    service: Service,
    toolkit_id: str,
    desired: GoogleServicesUpdateInput,
) -> GoogleConnectionOutput:
    with _errors():
        return await service.update_services(
            _subject(member, None), toolkit_id, desired
        )


@router.patch(
    "/workspaces/{handle}/agents/{agent_id}/toolkit-configs/{toolkit_id}/google/services"
)
async def agent_google_services(
    member: Member,
    service: Service,
    toolkit_id: str,
    agent_id: str,
    desired: GoogleServicesUpdateInput,
) -> GoogleConnectionOutput:
    with _errors():
        return await service.update_services(
            _subject(member, agent_id), toolkit_id, desired
        )


@router.delete("/workspaces/{handle}/toolkit-configs/{toolkit_id}/google/connection")
async def shared_google_disconnect(
    member: Member,
    service: Service,
    toolkit_id: str,
) -> Response:
    with _errors():
        await service.disconnect(_subject(member, None), toolkit_id)
    return Response(status_code=204)


@router.delete(
    "/workspaces/{handle}/agents/{agent_id}/toolkit-configs/{toolkit_id}/google/connection"
)
async def agent_google_disconnect(
    member: Member,
    service: Service,
    toolkit_id: str,
    agent_id: str,
) -> Response:
    with _errors():
        await service.disconnect(_subject(member, agent_id), toolkit_id)
    return Response(status_code=204)
