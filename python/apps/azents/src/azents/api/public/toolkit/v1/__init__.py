"""Toolkit v1 Public API.

Workspace-scoped Toolkit CRUD, scope management, and Agent Toolkit endpoints.
"""

from textwrap import dedent
from typing import Annotated, Any, assert_never

from azcommon.result import Failure, Success
from fastapi import APIRouter, Depends, HTTPException, status

from azents.core.auth.deps import WorkspaceMember, get_workspace_member
from azents.core.auth.permissions import Permissions
from azents.core.tools import ToolkitProvider
from azents.engine.tools.deps import get_toolkit_registry
from azents.repos.toolkit.data import (
    DuplicateAgentToolkit,
    DuplicateScope,
    NotFound,
    ScopeNotFound,
)
from azents.services.toolkit import ToolkitService
from azents.services.toolkit.data import (
    AgentNotBelongToWorkspace,
    AgentToolkitNotBelongToAgent,
    DuplicateSlug,
    InvalidConfig,
    InvalidCredentials,
    InvalidToolkitType,
    NotBelongToWorkspace,
    ScopeNotBelongToToolkit,
    ToolkitCreateInput,
    ToolkitNotAvailable,
    ToolkitScopeCreateInput,
)
from azents.utils.fastapi.route import RouteMounter

from .data import (
    AgentToolkitAttachRequest,
    AgentToolkitListResponse,
    AgentToolkitResponse,
    ToolkitConfigCreateRequest,
    ToolkitConfigListResponse,
    ToolkitConfigResponse,
    ToolkitConfigUpdateRequest,
    ToolkitListResponse,
    ToolkitResponse,
    ToolkitScopeListResponse,
    ToolkitScopeResponse,
)
from .oauth import router as oauth_router

router = APIRouter()


# ------------------------------------------------------------------ #
# Toolkit Config CRUD (Manager+)
# ------------------------------------------------------------------ #


@router.post(
    "/workspaces/{handle}/toolkit-configs",
    status_code=status.HTTP_201_CREATED,
)
async def create_toolkit_config(
    member: Annotated[WorkspaceMember, Depends(get_workspace_member)],
    service: Annotated[ToolkitService, Depends()],
    *,
    request_body: ToolkitConfigCreateRequest,
) -> ToolkitConfigResponse:
    """Create a Toolkit Config.

    Requires Toolkit write permission.
    """
    if not member.has_permission(Permissions.TOOLKITS_WRITE):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Toolkit management permission required.",
        )

    # Shell is controlled by the Agent Runtime settings.
    if request_body.toolkit_type == "shell":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Shell is managed via Agent Runtime settings, not toolkit configs.",
        )

    create_input = ToolkitCreateInput(
        workspace_id=member.workspace_id,
        toolkit_type=request_body.toolkit_type,
        slug=request_body.slug,
        name=request_body.name,
        description=request_body.description,
        config=request_body.config,
        prompt=request_body.prompt,
        credentials=request_body.credentials,
        enabled=request_body.enabled,
    )
    result = await service.create(create_input, user_id=member.user_id)
    match result:
        case Success(value):
            return ToolkitConfigResponse.model_validate(value, from_attributes=True)
        case Failure(error):
            match error:
                case InvalidToolkitType():
                    raise HTTPException(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        detail="Unknown toolkit type.",
                    )
                case InvalidConfig():
                    raise HTTPException(
                        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                        detail="Invalid tool config.",
                    )
                case DuplicateSlug():
                    raise HTTPException(
                        status_code=status.HTTP_409_CONFLICT,
                        detail="Duplicate toolkit slug in workspace.",
                    )
                case InvalidCredentials(detail=detail):
                    raise HTTPException(
                        status_code=status.HTTP_403_FORBIDDEN,
                        detail=detail,
                    )
                case _:
                    assert_never(error)
        case _:
            assert_never(result)


@router.get("/workspaces/{handle}/toolkit-configs/available")
async def list_available_toolkit_configs(
    member: Annotated[WorkspaceMember, Depends(get_workspace_member)],
    service: Annotated[ToolkitService, Depends()],
) -> ToolkitConfigListResponse:
    """List Toolkit Configs available to the current user.

    Requires Toolkit read permission.
    """
    if not member.has_permission(Permissions.TOOLKITS_READ):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Toolkit read permission required.",
        )

    result = await service.list_available(member.workspace_id, member.user_id)
    return ToolkitConfigListResponse(
        items=[
            ToolkitConfigResponse.model_validate(t, from_attributes=True)
            for t in result.items
        ]
    )


@router.get("/workspaces/{handle}/toolkit-configs")
async def list_toolkit_configs(
    member: Annotated[WorkspaceMember, Depends(get_workspace_member)],
    service: Annotated[ToolkitService, Depends()],
) -> ToolkitConfigListResponse:
    """List Toolkit Configs in a workspace.

    Requires Toolkit write permission.
    """
    if not member.has_permission(Permissions.TOOLKITS_WRITE):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Toolkit management permission required.",
        )

    result = await service.list_by_workspace(member.workspace_id)
    return ToolkitConfigListResponse(
        items=[
            ToolkitConfigResponse.model_validate(t, from_attributes=True)
            for t in result.items
        ]
    )


@router.get("/workspaces/{handle}/toolkit-configs/{toolkit_config_id}")
async def get_toolkit_config(
    member: Annotated[WorkspaceMember, Depends(get_workspace_member)],
    service: Annotated[ToolkitService, Depends()],
    *,
    toolkit_config_id: str,
) -> ToolkitConfigResponse:
    """Get Toolkit Config details.

    Requires Toolkit write permission.
    """
    if not member.has_permission(Permissions.TOOLKITS_WRITE):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Toolkit management permission required.",
        )

    result = await service.get_by_id(
        toolkit_config_id, workspace_id=member.workspace_id
    )
    match result:
        case Success(value):
            return ToolkitConfigResponse.model_validate(value, from_attributes=True)
        case Failure(error):
            match error:
                case NotFound() | NotBelongToWorkspace():
                    raise HTTPException(
                        status_code=status.HTTP_404_NOT_FOUND,
                        detail="Toolkit config not found.",
                    )
                case _:
                    assert_never(error)
        case _:
            assert_never(result)


@router.patch("/workspaces/{handle}/toolkit-configs/{toolkit_config_id}")
async def update_toolkit_config(
    member: Annotated[WorkspaceMember, Depends(get_workspace_member)],
    service: Annotated[ToolkitService, Depends()],
    *,
    toolkit_config_id: str,
    request_body: ToolkitConfigUpdateRequest,
) -> ToolkitConfigResponse:
    """Update a Toolkit Config.

    Requires Toolkit write permission.
    """
    if not member.has_permission(Permissions.TOOLKITS_WRITE):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Toolkit management permission required.",
        )

    result = await service.update_by_id(
        toolkit_config_id,
        request_body,
        workspace_id=member.workspace_id,
        user_id=member.user_id,
    )
    match result:
        case Success(value):
            return ToolkitConfigResponse.model_validate(value, from_attributes=True)
        case Failure(error):
            match error:
                case NotFound() | NotBelongToWorkspace():
                    raise HTTPException(
                        status_code=status.HTTP_404_NOT_FOUND,
                        detail="Toolkit config not found.",
                    )
                case InvalidConfig():
                    raise HTTPException(
                        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                        detail="Invalid tool config.",
                    )
                case DuplicateSlug():
                    raise HTTPException(
                        status_code=status.HTTP_409_CONFLICT,
                        detail="Duplicate toolkit slug in workspace.",
                    )
                case InvalidCredentials(detail=detail):
                    raise HTTPException(
                        status_code=status.HTTP_403_FORBIDDEN,
                        detail=detail,
                    )
                case _:
                    assert_never(error)
        case _:
            assert_never(result)


@router.delete(
    "/workspaces/{handle}/toolkit-configs/{toolkit_config_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_toolkit_config(
    member: Annotated[WorkspaceMember, Depends(get_workspace_member)],
    service: Annotated[ToolkitService, Depends()],
    *,
    toolkit_config_id: str,
) -> None:
    """Delete a Toolkit Config.

    Requires Toolkit write permission.
    """
    if not member.has_permission(Permissions.TOOLKITS_WRITE):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Toolkit management permission required.",
        )

    result = await service.delete_by_id(
        toolkit_config_id, workspace_id=member.workspace_id
    )
    match result:
        case Success():
            return
        case Failure(error):
            match error:
                case NotFound() | NotBelongToWorkspace():
                    raise HTTPException(
                        status_code=status.HTTP_404_NOT_FOUND,
                        detail="Toolkit config not found.",
                    )
                case _:
                    assert_never(error)
        case _:
            assert_never(result)


# ------------------------------------------------------------------ #
# Scope management (Manager+)
# ------------------------------------------------------------------ #


@router.post(
    "/workspaces/{handle}/toolkit-configs/{toolkit_config_id}/scopes",
    status_code=status.HTTP_201_CREATED,
)
async def create_toolkit_scope(
    member: Annotated[WorkspaceMember, Depends(get_workspace_member)],
    service: Annotated[ToolkitService, Depends()],
    *,
    toolkit_config_id: str,
) -> ToolkitScopeResponse:
    """Create a Toolkit Scope.

    Requires Toolkit write permission.
    """
    if not member.has_permission(Permissions.TOOLKITS_WRITE):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Toolkit management permission required.",
        )

    create_input = ToolkitScopeCreateInput(toolkit_id=toolkit_config_id)
    result = await service.create_scope(create_input, workspace_id=member.workspace_id)
    match result:
        case Success(value):
            return ToolkitScopeResponse.model_validate(value, from_attributes=True)
        case Failure(error):
            match error:
                case NotFound() | NotBelongToWorkspace():
                    raise HTTPException(
                        status_code=status.HTTP_404_NOT_FOUND,
                        detail="Toolkit not found.",
                    )
                case DuplicateScope():
                    raise HTTPException(
                        status_code=status.HTTP_409_CONFLICT,
                        detail="Scope already exists.",
                    )
                case _:
                    assert_never(error)
        case _:
            assert_never(result)


@router.get("/workspaces/{handle}/toolkit-configs/{toolkit_config_id}/scopes")
async def list_toolkit_scopes(
    member: Annotated[WorkspaceMember, Depends(get_workspace_member)],
    service: Annotated[ToolkitService, Depends()],
    *,
    toolkit_config_id: str,
) -> ToolkitScopeListResponse:
    """List Scopes for a Toolkit.

    Requires Toolkit write permission.
    """
    if not member.has_permission(Permissions.TOOLKITS_WRITE):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Toolkit management permission required.",
        )

    result = await service.list_scopes(
        toolkit_config_id, workspace_id=member.workspace_id
    )
    match result:
        case Success(value):
            return ToolkitScopeListResponse(
                items=[
                    ToolkitScopeResponse.model_validate(s, from_attributes=True)
                    for s in value.items
                ]
            )
        case Failure(error):
            match error:
                case NotFound() | NotBelongToWorkspace():
                    raise HTTPException(
                        status_code=status.HTTP_404_NOT_FOUND,
                        detail="Toolkit not found.",
                    )
                case _:
                    assert_never(error)
        case _:
            assert_never(result)


@router.delete(
    "/workspaces/{handle}/toolkit-configs/{toolkit_config_id}/scopes/{scope_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_toolkit_scope(
    member: Annotated[WorkspaceMember, Depends(get_workspace_member)],
    service: Annotated[ToolkitService, Depends()],
    *,
    toolkit_config_id: str,
    scope_id: str,
) -> None:
    """Delete a Toolkit Scope.

    Requires Toolkit write permission.
    """
    if not member.has_permission(Permissions.TOOLKITS_WRITE):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Toolkit management permission required.",
        )

    result = await service.delete_scope(
        scope_id, toolkit_id=toolkit_config_id, workspace_id=member.workspace_id
    )
    match result:
        case Success():
            return
        case Failure(error):
            match error:
                case (
                    NotFound()
                    | NotBelongToWorkspace()
                    | ScopeNotFound()
                    | ScopeNotBelongToToolkit()
                ):
                    raise HTTPException(
                        status_code=status.HTTP_404_NOT_FOUND,
                        detail="Toolkit or scope not found.",
                    )
                case _:
                    assert_never(error)
        case _:
            assert_never(result)


# ------------------------------------------------------------------ #
# Agent Toolkit (Member+)
# ------------------------------------------------------------------ #


@router.get("/workspaces/{handle}/agents/{agent_id}/toolkits")
async def list_agent_toolkits(
    member: Annotated[WorkspaceMember, Depends(get_workspace_member)],
    service: Annotated[ToolkitService, Depends()],
    *,
    agent_id: str,
) -> AgentToolkitListResponse:
    """List Toolkits attached to an Agent.

    Requires Toolkit read permission.
    """
    if not member.has_permission(Permissions.TOOLKITS_READ):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Toolkit read permission required.",
        )

    result = await service.list_agent_toolkits(
        agent_id, workspace_id=member.workspace_id
    )
    match result:
        case Success(value):
            return AgentToolkitListResponse(
                items=[
                    AgentToolkitResponse.model_validate(at, from_attributes=True)
                    for at in value.items
                ]
            )
        case Failure(error):
            match error:
                case AgentNotBelongToWorkspace():
                    raise HTTPException(
                        status_code=status.HTTP_404_NOT_FOUND,
                        detail="Agent not found.",
                    )
                case _:
                    assert_never(error)
        case _:
            assert_never(result)


@router.post(
    "/workspaces/{handle}/agents/{agent_id}/toolkits",
    status_code=status.HTTP_201_CREATED,
)
async def attach_toolkit_to_agent(
    member: Annotated[WorkspaceMember, Depends(get_workspace_member)],
    service: Annotated[ToolkitService, Depends()],
    *,
    agent_id: str,
    request_body: AgentToolkitAttachRequest,
) -> AgentToolkitResponse:
    """Attach a Toolkit to an Agent.

    Requires Toolkit read permission.
    """
    if not member.has_permission(Permissions.TOOLKITS_READ):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Toolkit read permission required.",
        )

    result = await service.attach_to_agent(
        agent_id,
        request_body.toolkit_id,
        workspace_id=member.workspace_id,
        user_id=member.user_id,
    )
    match result:
        case Success(value):
            return AgentToolkitResponse.model_validate(value, from_attributes=True)
        case Failure(error):
            match error:
                case NotFound() | NotBelongToWorkspace() | AgentNotBelongToWorkspace():
                    raise HTTPException(
                        status_code=status.HTTP_404_NOT_FOUND,
                        detail="Toolkit or agent not found.",
                    )
                case ToolkitNotAvailable():
                    raise HTTPException(
                        status_code=status.HTTP_403_FORBIDDEN,
                        detail="This toolkit is not available to you.",
                    )
                case DuplicateAgentToolkit():
                    raise HTTPException(
                        status_code=status.HTTP_409_CONFLICT,
                        detail="Agent already has this toolkit attached.",
                    )
                case _:
                    assert_never(error)
        case _:
            assert_never(result)


@router.delete(
    "/workspaces/{handle}/agents/{agent_id}/toolkits/{agent_toolkit_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def detach_toolkit_from_agent(
    member: Annotated[WorkspaceMember, Depends(get_workspace_member)],
    service: Annotated[ToolkitService, Depends()],
    *,
    agent_id: str,
    agent_toolkit_id: str,
) -> None:
    """Detach a Toolkit from an Agent.

    Requires Toolkit read permission.
    """
    if not member.has_permission(Permissions.TOOLKITS_READ):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Toolkit read permission required.",
        )

    result = await service.detach_from_agent(
        agent_toolkit_id, agent_id=agent_id, workspace_id=member.workspace_id
    )
    match result:
        case Success():
            return
        case Failure(error):
            match error:
                case (
                    ScopeNotFound()
                    | AgentToolkitNotBelongToAgent()
                    | AgentNotBelongToWorkspace()
                ):
                    raise HTTPException(
                        status_code=status.HTTP_404_NOT_FOUND,
                        detail="Agent toolkit not found.",
                    )
                case _:
                    assert_never(error)
        case _:
            assert_never(result)


# ------------------------------------------------------------------ #
# Toolkits, no authentication required
# ------------------------------------------------------------------ #


@router.get("/toolkits")
async def list_toolkits(
    toolkit_registry: Annotated[
        dict[str, ToolkitProvider[Any]], Depends(get_toolkit_registry)
    ],
) -> ToolkitListResponse:
    """Return the list of Toolkits provided by the platform.

    Returns metadata for every tool registered in toolkit_registry.
    Accessible without authentication.
    """
    items = [
        ToolkitResponse(
            slug=provider.slug,
            name=provider.name,
            description=provider.description,
            config_schema=type(provider).config_schema(),
            system_prompt=provider.system_prompt,
        )
        for provider in toolkit_registry.values()
    ]
    return ToolkitListResponse(items=items)


def mount(mounter: RouteMounter) -> None:
    """Mount Toolkit v1 routes."""
    mounter(
        router,
        prefix="/toolkit/v1",
        tag="Toolkit v1",
        description=dedent(
            """
            Toolkit API (Public)

            Manager: Toolkit CRUD and scope management.
            Member: available Toolkit lookup and Agent Toolkit attach/detach.
            """
        ),
    )
    mounter(
        oauth_router,
        prefix="/toolkit/v1",
        tag="Toolkit OAuth v1",
        description="Toolkit OAuth2 connection flow.",
    )
