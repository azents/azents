"""Agent Runtime v1 Public API."""

from textwrap import dedent
from typing import Annotated, NoReturn, assert_never

from azcommon.result import Failure, Success
from fastapi import APIRouter, Depends, HTTPException, status

from azents.core.auth.deps import WorkspaceMember, get_workspace_member
from azents.services.agent_runtime.lifecycle_data import (
    AgentAccessDenied,
    AgentManagementAccessDenied,
    AgentNotBelongToWorkspace,
    AgentNotFound,
    AgentRuntimeActionUnavailable,
    InvalidResetFinalDesiredState,
    ProviderDisconnected,
    RuntimeNotFound,
    RuntimeProviderUnavailable,
)
from azents.services.agent_runtime.service import AgentRuntimeService
from azents.utils.fastapi.route import RouteMounter

from .data import (
    AddAgentRuntimeRequest,
    AgentRuntimeActionErrorResponse,
    AgentRuntimeAdditionResponse,
    AgentRuntimeLifecycleResponse,
    AgentRuntimeRemovalResponse,
    AgentRuntimeResponse,
    RemoveAgentRuntimeRequest,
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


@router.post(
    "/workspaces/{handle}/agents/{agent_id}/runtime/add",
    responses={
        status.HTTP_403_FORBIDDEN: {
            "model": AgentRuntimeActionErrorResponse,
            "description": "The caller cannot manage this Agent.",
        },
        status.HTTP_409_CONFLICT: {
            "model": AgentRuntimeActionErrorResponse,
            "description": "The Runtime addition cannot be committed.",
        },
    },
)
async def add_agent_runtime(
    member: Annotated[WorkspaceMember, Depends(get_workspace_member)],
    service: Annotated[AgentRuntimeService, Depends()],
    *,
    agent_id: str,
    request_body: AddAgentRuntimeRequest,
) -> AgentRuntimeAdditionResponse:
    """Add a stopped managed Runtime through the dedicated transition."""
    result = await service.add(
        agent_id,
        workspace_runtime_profile_id=request_body.workspace_runtime_profile_id,
        expected_capability_version=request_body.expected_capability_version,
        expected_runtime_profile_selection_version=(
            request_body.expected_runtime_profile_selection_version
        ),
        idempotency_key=request_body.idempotency_key,
        workspace_id=member.workspace_id,
        workspace_user_id=member.workspace_user_id,
        role=member.role,
    )
    match result:
        case Success(value):
            return AgentRuntimeAdditionResponse.convert_from(value)
        case Failure(error):
            _raise_action_error(error)
        case _:
            assert_never(result)


@router.post(
    "/workspaces/{handle}/agents/{agent_id}/runtime/remove",
    responses={
        status.HTTP_403_FORBIDDEN: {
            "model": AgentRuntimeActionErrorResponse,
            "description": "The caller cannot manage this Agent.",
        },
        status.HTTP_409_CONFLICT: {
            "model": AgentRuntimeActionErrorResponse,
            "description": "The irreversible Runtime removal cannot be committed.",
        },
    },
)
async def remove_agent_runtime(
    member: Annotated[WorkspaceMember, Depends(get_workspace_member)],
    service: Annotated[AgentRuntimeService, Depends()],
    *,
    agent_id: str,
    request_body: RemoveAgentRuntimeRequest,
) -> AgentRuntimeRemovalResponse:
    """Commit final irreversible managed Runtime removal."""
    result = await service.remove(
        agent_id,
        expected_capability_version=request_body.expected_capability_version,
        expected_runtime_profile_selection_version=(
            request_body.expected_runtime_profile_selection_version
        ),
        idempotency_key=request_body.idempotency_key,
        confirmed=request_body.confirmed,
        workspace_id=member.workspace_id,
        workspace_user_id=member.workspace_user_id,
        role=member.role,
    )
    match result:
        case Success(value):
            return AgentRuntimeRemovalResponse.convert_from(value)
        case Failure(error):
            _raise_action_error(error)
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
                case RuntimeProviderUnavailable():
                    _raise_provider_unavailable()
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


def _raise_action_error(
    error: (
        AgentNotFound
        | AgentNotBelongToWorkspace
        | AgentAccessDenied
        | AgentManagementAccessDenied
        | AgentRuntimeActionUnavailable
    ),
) -> NoReturn:
    """Convert dedicated Runtime transition errors to HTTP errors."""
    match error:
        case AgentNotFound() | AgentNotBelongToWorkspace() | AgentAccessDenied():
            _raise_access_error(error)
        case AgentManagementAccessDenied():
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail={
                    "code": "agent_runtime_management_denied",
                    "message": "Not allowed to manage this Agent Runtime.",
                },
            )
        case AgentRuntimeActionUnavailable(code=code, message=message):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail={"code": code, "message": message},
            )
        case _:
            assert_never(error)


def _raise_lifecycle_error(
    error: (
        AgentNotFound
        | AgentNotBelongToWorkspace
        | AgentAccessDenied
        | RuntimeNotFound
        | RuntimeProviderUnavailable
    ),
) -> NoReturn:
    """Convert lifecycle service errors to HTTP errors."""
    match error:
        case RuntimeNotFound():
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Agent runtime was not found.",
            )
        case RuntimeProviderUnavailable():
            _raise_provider_unavailable()
        case AgentNotFound() | AgentNotBelongToWorkspace() | AgentAccessDenied():
            _raise_access_error(error)
        case _:
            assert_never(error)


def _raise_access_error(
    error: (
        AgentNotFound
        | AgentNotBelongToWorkspace
        | AgentAccessDenied
        | RuntimeProviderUnavailable
    ),
) -> NoReturn:
    """Convert agent access service errors to HTTP errors."""
    match error:
        case AgentNotFound() | AgentNotBelongToWorkspace() | AgentAccessDenied():
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Agent was not found.",
            )
        case RuntimeProviderUnavailable():
            _raise_provider_unavailable()
        case _:
            assert_never(error)


def _raise_provider_unavailable() -> NoReturn:
    """Return a stable conflict when no Provider can provision a Runtime."""
    raise HTTPException(
        status_code=status.HTTP_409_CONFLICT,
        detail="No eligible Runtime Provider is available.",
    )


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
