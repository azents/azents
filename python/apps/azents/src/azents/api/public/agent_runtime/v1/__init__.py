"""Agent Runtime v1 Public API."""

from textwrap import dedent
from typing import Annotated, NoReturn, assert_never

from azcommon.result import Failure, Success
from fastapi import APIRouter, Depends, HTTPException, status

from azents.core.auth.deps import WorkspaceMember, get_workspace_member
from azents.services.agent_runtime.lifecycle_data import (
    AgentAccessDenied,
    AgentNotBelongToWorkspace,
    AgentNotFound,
    InvalidResetFinalDesiredState,
    ProviderDisconnected,
    RuntimeNotFound,
)
from azents.services.agent_runtime.service import AgentRuntimeService
from azents.utils.fastapi.route import RouteMounter

from .data import (
    AgentRuntimeLifecycleResponse,
    AgentRuntimeResponse,
    ResetAgentRuntimeRequest,
)

router = APIRouter()


@router.get("/workspaces/{handle}/agents/{agent_id}/runtime")
async def get_agent_runtime(
    member: Annotated[WorkspaceMember, Depends(get_workspace_member)],
    service: Annotated[AgentRuntimeService, Depends()],
    *,
    agent_id: str,
) -> AgentRuntimeResponse:
    """Get Agent Runtime status."""
    result = await service.get(
        agent_id,
        workspace_id=member.workspace_id,
        workspace_user_id=member.workspace_user_id,
        role=member.role,
    )
    match result:
        case Success(value):
            return AgentRuntimeResponse.convert_from(value)
        case Failure(error):
            _raise_access_error(error)
            assert_never(error)
        case _:
            assert_never(result)


@router.post("/workspaces/{handle}/agents/{agent_id}/runtime/start")
async def start_agent_runtime(
    member: Annotated[WorkspaceMember, Depends(get_workspace_member)],
    service: Annotated[AgentRuntimeService, Depends()],
    *,
    agent_id: str,
) -> AgentRuntimeLifecycleResponse:
    """Store Agent Runtime start desired state."""
    result = await service.start(
        agent_id,
        workspace_id=member.workspace_id,
        workspace_user_id=member.workspace_user_id,
        role=member.role,
    )
    match result:
        case Success(value):
            return AgentRuntimeLifecycleResponse.convert_from_lifecycle(value)
        case Failure(error):
            _raise_lifecycle_error(error)
            assert_never(error)
        case _:
            assert_never(result)


@router.post("/workspaces/{handle}/agents/{agent_id}/runtime/stop")
async def stop_agent_runtime(
    member: Annotated[WorkspaceMember, Depends(get_workspace_member)],
    service: Annotated[AgentRuntimeService, Depends()],
    *,
    agent_id: str,
) -> AgentRuntimeLifecycleResponse:
    """Store Agent Runtime stop desired state."""
    result = await service.stop(
        agent_id,
        workspace_id=member.workspace_id,
        workspace_user_id=member.workspace_user_id,
        role=member.role,
    )
    match result:
        case Success(value):
            return AgentRuntimeLifecycleResponse.convert_from_lifecycle(value)
        case Failure(error):
            _raise_lifecycle_error(error)
            assert_never(error)
        case _:
            assert_never(result)


@router.post("/workspaces/{handle}/agents/{agent_id}/runtime/restart")
async def restart_agent_runtime(
    member: Annotated[WorkspaceMember, Depends(get_workspace_member)],
    service: Annotated[AgentRuntimeService, Depends()],
    *,
    agent_id: str,
) -> AgentRuntimeLifecycleResponse:
    """Store Agent Runtime restart command."""
    result = await service.restart(
        agent_id,
        workspace_id=member.workspace_id,
        workspace_user_id=member.workspace_user_id,
        role=member.role,
    )
    match result:
        case Success(value):
            return AgentRuntimeLifecycleResponse.convert_from_lifecycle(value)
        case Failure(error):
            _raise_lifecycle_error(error)
            assert_never(error)
        case _:
            assert_never(result)


@router.post("/workspaces/{handle}/agents/{agent_id}/runtime/reset")
async def reset_agent_runtime(
    member: Annotated[WorkspaceMember, Depends(get_workspace_member)],
    service: Annotated[AgentRuntimeService, Depends()],
    *,
    agent_id: str,
    request_body: ResetAgentRuntimeRequest,
) -> AgentRuntimeLifecycleResponse:
    """Store Agent Runtime reset command."""
    result = await service.reset(
        agent_id,
        final_desired_state=request_body.final_desired_state,
        workspace_id=member.workspace_id,
        workspace_user_id=member.workspace_user_id,
        role=member.role,
    )
    match result:
        case Success(value):
            return AgentRuntimeLifecycleResponse.convert_from_lifecycle(value)
        case Failure(error):
            match error:
                case ProviderDisconnected():
                    raise HTTPException(
                        status_code=status.HTTP_409_CONFLICT,
                        detail="Runtime provider is disconnected.",
                    )
                case InvalidResetFinalDesiredState():
                    raise HTTPException(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        detail="Reset final desired state is invalid.",
                    )
                case _:
                    _raise_lifecycle_error(error)
                    assert_never(error)
        case _:
            assert_never(result)


@router.post("/workspaces/{handle}/agents/{agent_id}/runtime/observe")
async def observe_agent_runtime(
    member: Annotated[WorkspaceMember, Depends(get_workspace_member)],
    service: Annotated[AgentRuntimeService, Depends()],
    *,
    agent_id: str,
) -> AgentRuntimeResponse:
    """Return the Agent Runtime observe read model."""
    result = await service.observe(
        agent_id,
        workspace_id=member.workspace_id,
        workspace_user_id=member.workspace_user_id,
        role=member.role,
    )
    match result:
        case Success(value):
            return AgentRuntimeResponse.convert_from(value)
        case Failure(error):
            _raise_access_error(error)
            assert_never(error)
        case _:
            assert_never(result)


def _raise_lifecycle_error(
    error: (
        AgentNotFound | AgentNotBelongToWorkspace | AgentAccessDenied | RuntimeNotFound
    ),
) -> NoReturn:
    """Convert lifecycle service errors to HTTP errors."""
    match error:
        case RuntimeNotFound():
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Agent runtime was not found.",
            )
        case AgentNotFound() | AgentNotBelongToWorkspace() | AgentAccessDenied():
            _raise_access_error(error)
        case _:
            assert_never(error)


def _raise_access_error(
    error: AgentNotFound | AgentNotBelongToWorkspace | AgentAccessDenied,
) -> NoReturn:
    """Convert agent access service errors to HTTP errors."""
    match error:
        case AgentNotFound() | AgentNotBelongToWorkspace() | AgentAccessDenied():
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Agent was not found.",
            )
        case _:
            assert_never(error)


def mount(mounter: RouteMounter) -> None:
    """Mount Agent Runtime v1 routes."""
    mounter(
        router,
        prefix="/agent-runtime/v1",
        tag="Agent Runtime v1",
        description=dedent(
            """
            Agent Runtime API (Public)

            Agent-scoped Runtime lifecycle state and server-computed summaries.
            """
        ),
    )
