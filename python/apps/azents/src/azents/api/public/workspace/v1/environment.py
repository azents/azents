"""Workspace common environment and per-Agent selection HTTP endpoints."""

from typing import Annotated, TypeVar, assert_never

from azcommon.result import Failure, Result, Success
from fastapi import APIRouter, Depends, HTTPException

from azents.api.public.agent_runtime.v1.environment import RuntimeEnvironmentRoute
from azents.core.auth.deps import WorkspaceMember, get_workspace_member
from azents.core.runtime_environment import (
    InvalidRuntimeEnvironment,
    RuntimeEnvironmentAccessError,
)
from azents.core.workspace_environment import (
    AgentWorkspaceEnvironmentReplace,
    AgentWorkspaceEnvironmentSettings,
    WorkspaceEnvironmentReplace,
    WorkspaceEnvironmentSettings,
)
from azents.services.workspace_environment import WorkspaceEnvironmentService

router = APIRouter(route_class=RuntimeEnvironmentRoute)
T = TypeVar("T")


def _output(result: Result[T, RuntimeEnvironmentAccessError]) -> T:
    match result:
        case Success(value):
            return value
        case Failure(error):
            match error:
                case RuntimeEnvironmentAccessError.NOT_FOUND:
                    raise HTTPException(404, "Settings not found.")
                case RuntimeEnvironmentAccessError.DENIED:
                    raise HTTPException(403, "Settings management access denied.")
                case _:
                    assert_never(error)
        case _:
            assert_never(result)


@router.get("/workspaces/{handle}/environment")
async def get_workspace_environment(
    member: Annotated[WorkspaceMember, Depends(get_workspace_member)],
    service: Annotated[WorkspaceEnvironmentService, Depends()],
) -> WorkspaceEnvironmentSettings:
    """List shared variable names without revealing values."""
    return await service.get(member.workspace_id, role=member.role)


@router.put("/workspaces/{handle}/environment")
async def replace_workspace_environment(
    member: Annotated[WorkspaceMember, Depends(get_workspace_member)],
    service: Annotated[WorkspaceEnvironmentService, Depends()],
    request_body: WorkspaceEnvironmentReplace,
) -> WorkspaceEnvironmentSettings:
    """Atomically replace the Workspace catalog under Owner/Manager authority."""
    try:
        return _output(
            await service.replace(
                member.workspace_id, edits=request_body.entries, role=member.role
            )
        )
    except InvalidRuntimeEnvironment as error:
        raise HTTPException(422, str(error)) from None


@router.get("/workspaces/{handle}/agents/{agent_id}/environment-selection")
async def get_agent_environment_selection(
    member: Annotated[WorkspaceMember, Depends(get_workspace_member)],
    service: Annotated[WorkspaceEnvironmentService, Depends()],
    *,
    agent_id: str,
) -> AgentWorkspaceEnvironmentSettings:
    """Get opt-in metadata for an accessible Agent in this Workspace."""
    return _output(
        await service.agent_settings(
            agent_id,
            workspace_id=member.workspace_id,
            workspace_user_id=member.workspace_user_id,
            role=member.role,
            selected_ids=None,
        )
    )


@router.put("/workspaces/{handle}/agents/{agent_id}/environment-selection")
async def replace_agent_environment_selection(
    member: Annotated[WorkspaceMember, Depends(get_workspace_member)],
    service: Annotated[WorkspaceEnvironmentService, Depends()],
    request_body: AgentWorkspaceEnvironmentReplace,
    *,
    agent_id: str,
) -> AgentWorkspaceEnvironmentSettings:
    """Choose exact shared identities; never implicitly opt in to new keys."""
    try:
        return _output(
            await service.agent_settings(
                agent_id,
                workspace_id=member.workspace_id,
                workspace_user_id=member.workspace_user_id,
                role=member.role,
                selected_ids=request_body.selected_ids,
            )
        )
    except InvalidRuntimeEnvironment as error:
        raise HTTPException(422, str(error)) from None
