"""ChatGPT OAuth v1 Public API routes."""

from textwrap import dedent
from typing import Annotated, assert_never

from azcommon.result import Failure, Success
from fastapi import APIRouter, Depends, HTTPException, status

from azents.core.auth.deps import WorkspaceMember, get_workspace_member
from azents.core.auth.permissions import Permissions
from azents.services.chatgpt_oauth import ChatGPTOAuthService
from azents.services.chatgpt_oauth.data import (
    InvalidSession,
    ProviderPending,
    ProviderRejected,
    ProviderUnavailable,
    SessionNotFound,
    SessionTransitionFailed,
)
from azents.utils.fastapi.route import RouteMounter

from .data import (
    ChatGPTOAuthDeviceStartResponse,
    ChatGPTOAuthDeviceStatusResponse,
)

router = APIRouter()


def _require_write_permission(member: WorkspaceMember) -> None:
    """Check LLM integration write permission."""
    if not member.has_permission(Permissions.LLM_INTEGRATIONS_WRITE):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="LLM integration write permission is required.",
        )


@router.post("/workspaces/{handle}/chatgpt-oauth/device/start")
async def start_device(
    member: Annotated[WorkspaceMember, Depends(get_workspace_member)],
    service: Annotated[ChatGPTOAuthService, Depends()],
) -> ChatGPTOAuthDeviceStartResponse:
    """Start ChatGPT OAuth device flow."""
    _require_write_permission(member)
    result = await service.start_device(
        workspace_id=member.workspace_id,
        user_id=member.user_id,
    )
    match result:
        case Success(value):
            return ChatGPTOAuthDeviceStartResponse.convert_from(value)
        case Failure(error):
            _raise_oauth_error(error)
            raise AssertionError("unreachable")
        case _:
            assert_never(result)


@router.get("/workspaces/{handle}/chatgpt-oauth/device/{session_id}")
async def poll_device(
    member: Annotated[WorkspaceMember, Depends(get_workspace_member)],
    service: Annotated[ChatGPTOAuthService, Depends()],
    *,
    session_id: str,
) -> ChatGPTOAuthDeviceStatusResponse:
    """Poll ChatGPT OAuth device flow status once."""
    _require_write_permission(member)
    result = await service.poll_device(
        workspace_id=member.workspace_id,
        user_id=member.user_id,
        session_id=session_id,
    )
    match result:
        case Success(value):
            return ChatGPTOAuthDeviceStatusResponse.convert_from(value)
        case Failure(error):
            _raise_oauth_error(error)
            raise AssertionError("unreachable")
        case _:
            assert_never(result)


@router.delete("/workspaces/{handle}/chatgpt-oauth/device/{session_id}")
async def cancel_device(
    member: Annotated[WorkspaceMember, Depends(get_workspace_member)],
    service: Annotated[ChatGPTOAuthService, Depends()],
    *,
    session_id: str,
) -> ChatGPTOAuthDeviceStatusResponse:
    """Cancel ChatGPT OAuth device flow."""
    _require_write_permission(member)
    result = await service.cancel_device(
        workspace_id=member.workspace_id,
        user_id=member.user_id,
        session_id=session_id,
    )
    match result:
        case Success(value):
            return ChatGPTOAuthDeviceStatusResponse.convert_from(value)
        case Failure(error):
            _raise_oauth_error(error)
            raise AssertionError("unreachable")
        case _:
            assert_never(result)


def _raise_oauth_error(error: object) -> None:
    """Convert service errors to HTTPException."""
    match error:
        case SessionNotFound():
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="OAuth session was not found.",
            )
        case InvalidSession():
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="OAuth session is invalid or expired.",
            )
        case ProviderPending():
            raise HTTPException(
                status_code=status.HTTP_202_ACCEPTED,
                detail="ChatGPT authorization is still pending.",
            )
        case ProviderRejected():
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="ChatGPT OAuth provider rejected the request.",
            )
        case ProviderUnavailable():
            raise RuntimeError("ChatGPT OAuth provider is temporarily unavailable.")
        case SessionTransitionFailed():
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="OAuth session state could not be updated.",
            )
        case _:
            raise RuntimeError("Unexpected OAuth error.")


def mount(mounter: RouteMounter) -> None:
    """Mount ChatGPT OAuth v1 routes."""
    mounter(
        router,
        prefix="/llm-provider-integration/v1",
        tag="ChatGPT OAuth v1",
        description=dedent(
            """
            ChatGPT OAuth API (Public)

            Starts and completes ChatGPT OAuth device-code connections.
            Tokens and authorization codes are never returned in API responses.
            """
        ),
    )
