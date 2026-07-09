"""Agent v1 Public API.

Workspace-scoped Agent CRUD and Admin management endpoints.
"""

from textwrap import dedent
from typing import Annotated, NoReturn, assert_never

from azcommon.result import Failure, Success
from fastapi import APIRouter, Depends, HTTPException, Query, status

from azents.core.auth.deps import WorkspaceMember, get_workspace_member
from azents.repos.agent.data import NotFound
from azents.repos.memory.data import MemoryScope
from azents.services.agent import AgentService
from azents.services.agent.data import (
    AdminNotFound,
    AgentCreateInput,
    AgentUpdateInput,
    AvatarUploadRejected,
    BuiltinToolValidationFailed,
    DuplicateAdmin,
    InvalidModelParameters,
    LastAdminCannotBeRemoved,
    ModelRequired,
    ModelSelectionNotFound,
    NotAdmin,
    NotBelongToWorkspace,
    PrivateAgentAccessDenied,
    WorkspaceUserNotFound,
)
from azents.services.memory import MemoryService
from azents.services.memory.data import (
    DuplicateMemory,
    MemoryCreateInput,
    MemoryNotFound,
    MemoryUpdateInput,
)
from azents.utils.fastapi.route import RouteMounter

from .data import (
    AgentAdminAddRequest,
    AgentAdminListResponse,
    AgentAdminResponse,
    AgentCreateRequest,
    AgentListResponse,
    AgentResponse,
    AgentUpdateRequest,
    AvatarFinalizeRequest,
    AvatarUploadRequest,
    AvatarUploadTicketResponse,
    MemoryCreateRequest,
    MemoryListResponse,
    MemoryResponse,
    MemoryUpdateRequest,
)

router = APIRouter()


# --- Agent CRUD ---


@router.post(
    "/workspaces/{handle}/agents",
    status_code=status.HTTP_201_CREATED,
)
async def create_agent(
    member: Annotated[WorkspaceMember, Depends(get_workspace_member)],
    service: Annotated[AgentService, Depends()],
    *,
    request_body: AgentCreateRequest,
) -> AgentResponse:
    """Create an Agent.

    Any workspace member can create one.
    The creator is automatically registered as the first administrator.
    """
    create_input = AgentCreateInput(
        workspace_id=member.workspace_id,
        name=request_body.name,
        model_selection=request_body.model_selection,
        lightweight_model_selection=request_body.lightweight_model_selection,
        description=request_body.description,
        model_parameters=request_body.model_parameters,
        system_prompt=request_body.system_prompt,
        enabled=request_body.enabled,
        type=request_body.type,
        runtime_provider_id=request_body.runtime_provider_id,
        shell_enabled=request_body.shell_enabled,
        memory_enabled=request_body.memory_enabled,
        max_turns=request_body.max_turns,
        subagent_settings=request_body.subagent_settings,
    )
    result = await service.create(
        create_input, creator_workspace_user_id=member.workspace_user_id
    )
    match result:
        case Success(value):
            return AgentResponse.convert_from(value)
        case Failure(error):
            match error:
                case BuiltinToolValidationFailed(errors=bt_errors):
                    raise HTTPException(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        detail={
                            "message": "Built-in tool validation failed",
                            "builtin_tool_errors": bt_errors,
                        },
                    )
                case ModelRequired():
                    raise HTTPException(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        detail="Select a model before saving this agent.",
                    )
                case ModelSelectionNotFound():
                    raise HTTPException(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        detail="Selected model was not found.",
                    )
                case InvalidModelParameters(errors=errors):
                    raise HTTPException(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        detail={
                            "message": "Invalid model parameters.",
                            "errors": errors,
                        },
                    )
                case _:
                    assert_never(error)
        case _:
            assert_never(result)


@router.get("/workspaces/{handle}/agents")
async def list_agents(
    member: Annotated[WorkspaceMember, Depends(get_workspace_member)],
    service: Annotated[AgentService, Depends()],
) -> AgentListResponse:
    """List Agents in a workspace.

    Any workspace member can list Agents.
    Public Agents are visible to everyone; private Agents are visible only to
    administrators and owners.
    """
    result = await service.list_by_workspace(
        member.workspace_id,
        workspace_user_id=member.workspace_user_id,
        role=member.role,
    )
    return AgentListResponse(
        items=[AgentResponse.convert_from(a) for a in result.items]
    )


@router.get("/workspaces/{handle}/agents/{agent_id}")
async def get_agent(
    member: Annotated[WorkspaceMember, Depends(get_workspace_member)],
    service: Annotated[AgentService, Depends()],
    *,
    agent_id: str,
) -> AgentResponse:
    """Get Agent details.

    Any workspace member can view them.
    Private Agents are visible only to administrators and owners.
    """
    result = await service.get_by_id(
        agent_id,
        workspace_id=member.workspace_id,
        workspace_user_id=member.workspace_user_id,
        role=member.role,
    )
    match result:
        case Success(value):
            return AgentResponse.convert_from(value)
        case Failure(error):
            match error:
                case NotFound() | NotBelongToWorkspace() | PrivateAgentAccessDenied():
                    raise HTTPException(
                        status_code=status.HTTP_404_NOT_FOUND,
                        detail="Agent not found.",
                    )
                case _:
                    assert_never(error)
        case _:
            assert_never(result)


def _build_agent_update_input(
    request_body: AgentUpdateRequest,
) -> AgentUpdateInput:
    """Convert an API request to the service input model.

    Distinguish missing fields from null values by TypedDict key presence.

    :param request_body: Request body
    :return: AgentUpdateInput containing only explicit fields
    """
    result = AgentUpdateInput()

    # Simple one-to-one mapping fields
    if "name" in request_body:
        result["name"] = request_body["name"]
    if "description" in request_body:
        result["description"] = request_body["description"]
    if "model_selection" in request_body:
        result["model_selection"] = request_body["model_selection"]
    if "lightweight_model_selection" in request_body:
        result["lightweight_model_selection"] = request_body[
            "lightweight_model_selection"
        ]
    if "model_parameters" in request_body:
        result["model_parameters"] = request_body["model_parameters"]
    if "system_prompt" in request_body:
        result["system_prompt"] = request_body["system_prompt"]
    if "enabled" in request_body:
        result["enabled"] = request_body["enabled"]
    if "type" in request_body:
        result["type"] = request_body["type"]

    if "runtime_provider_id" in request_body:
        result["runtime_provider_id"] = request_body["runtime_provider_id"]
    if "shell_enabled" in request_body:
        result["shell_enabled"] = request_body["shell_enabled"]

    # Memory
    if "memory_enabled" in request_body:
        result["memory_enabled"] = request_body["memory_enabled"]
    if "max_turns" in request_body:
        result["max_turns"] = request_body["max_turns"]
    if "subagent_settings" in request_body:
        result["subagent_settings"] = request_body["subagent_settings"]

    return result


@router.patch("/workspaces/{handle}/agents/{agent_id}")
async def update_agent(
    member: Annotated[WorkspaceMember, Depends(get_workspace_member)],
    service: Annotated[AgentService, Depends()],
    *,
    agent_id: str,
    request_body: AgentUpdateRequest,
) -> AgentResponse:
    """Update an Agent.

    Only administrators or workspace owners can update it.
    """
    # PATCH rule: distinguish missing fields from null values by TypedDict key presence.
    # Missing keys are not updated; None values update fields to null.
    update_input = _build_agent_update_input(request_body)
    result = await service.update_by_id(
        agent_id,
        update_input,
        workspace_id=member.workspace_id,
        workspace_user_id=member.workspace_user_id,
        role=member.role,
    )
    match result:
        case Success(value):
            return AgentResponse.convert_from(value)
        case Failure(error):
            match error:
                case NotFound() | NotBelongToWorkspace():
                    raise HTTPException(
                        status_code=status.HTTP_404_NOT_FOUND,
                        detail="Agent not found.",
                    )
                case NotAdmin():
                    raise HTTPException(
                        status_code=status.HTTP_403_FORBIDDEN,
                        detail="Not allowed to manage this agent.",
                    )
                case BuiltinToolValidationFailed(errors=bt_errors):
                    raise HTTPException(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        detail={
                            "message": "Built-in tool validation failed",
                            "builtin_tool_errors": bt_errors,
                        },
                    )
                case ModelRequired():
                    raise HTTPException(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        detail="Select a model before saving this agent.",
                    )
                case ModelSelectionNotFound():
                    raise HTTPException(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        detail="Selected model was not found.",
                    )
                case InvalidModelParameters(errors=errors):
                    raise HTTPException(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        detail={
                            "message": "Invalid model parameters.",
                            "errors": errors,
                        },
                    )
                case _:
                    assert_never(error)
        case _:
            assert_never(result)


@router.delete(
    "/workspaces/{handle}/agents/{agent_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_agent(
    member: Annotated[WorkspaceMember, Depends(get_workspace_member)],
    service: Annotated[AgentService, Depends()],
    *,
    agent_id: str,
) -> None:
    """Delete an Agent.

    Only administrators or workspace owners can delete it.
    """
    result = await service.delete_by_id(
        agent_id,
        workspace_id=member.workspace_id,
        workspace_user_id=member.workspace_user_id,
        role=member.role,
    )
    match result:
        case Success():
            return
        case Failure(error):
            match error:
                case NotFound() | NotBelongToWorkspace():
                    raise HTTPException(
                        status_code=status.HTTP_404_NOT_FOUND,
                        detail="Agent not found.",
                    )
                case NotAdmin():
                    raise HTTPException(
                        status_code=status.HTTP_403_FORBIDDEN,
                        detail="Not allowed to manage this agent.",
                    )
                case _:
                    assert_never(error)
        case _:
            assert_never(result)


# --- Agent Memory ---


def _raise_memory_agent_not_found() -> NoReturn:
    """Raise a consistent Memory agent visibility error."""
    raise HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail="Agent not found.",
    )


def _raise_memory_not_found() -> NoReturn:
    """Raise a consistent Memory visibility error."""
    raise HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail="Memory not found.",
    )


def _build_memory_update_input(
    request_body: MemoryUpdateRequest,
) -> MemoryUpdateInput:
    """Convert an API request to the service input model."""
    result = MemoryUpdateInput()
    if "type" in request_body:
        result["type"] = request_body["type"]
    if "name" in request_body:
        result["name"] = request_body["name"]
    if "description" in request_body:
        result["description"] = request_body["description"]
    if "content" in request_body:
        result["content"] = request_body["content"]
    return result


@router.get("/workspaces/{handle}/agents/{agent_id}/memories")
async def list_agent_memories(
    member: Annotated[WorkspaceMember, Depends(get_workspace_member)],
    service: Annotated[MemoryService, Depends()],
    *,
    agent_id: str,
    scope: Annotated[MemoryScope, Query(description="Memory scope")],
    type: Annotated[str | None, Query(description="Memory type filter")] = None,
    query: Annotated[str | None, Query(description="Search query")] = None,
) -> MemoryListResponse:
    """List memories for one Agent and scope.

    Agent-scope Memory is readable by users who can view the Agent. User-scope
    Memory lists only the current user's entries.
    """
    result = await service.list_by_agent(
        agent_id,
        workspace_id=member.workspace_id,
        workspace_user_id=member.workspace_user_id,
        user_id=member.user_id,
        role=member.role,
        scope=scope,
        type=type,
        query=query,
    )
    match result:
        case Success(value):
            return MemoryListResponse(
                items=[MemoryResponse.convert_from(a) for a in value.items]
            )
        case Failure(error):
            match error:
                case NotFound() | NotBelongToWorkspace() | PrivateAgentAccessDenied():
                    _raise_memory_agent_not_found()
                case _:
                    assert_never(error)
        case _:
            assert_never(result)


@router.post(
    "/workspaces/{handle}/agents/{agent_id}/memories",
    status_code=status.HTTP_201_CREATED,
)
async def create_agent_memory(
    member: Annotated[WorkspaceMember, Depends(get_workspace_member)],
    service: Annotated[MemoryService, Depends()],
    *,
    agent_id: str,
    request_body: MemoryCreateRequest,
) -> MemoryResponse:
    """Create Memory with strict conflict semantics."""
    result = await service.create(
        agent_id,
        MemoryCreateInput(
            scope=request_body.scope,
            type=request_body.type,
            name=request_body.name,
            description=request_body.description,
            content=request_body.content,
        ),
        workspace_id=member.workspace_id,
        workspace_user_id=member.workspace_user_id,
        user_id=member.user_id,
        role=member.role,
    )
    match result:
        case Success(value):
            return MemoryResponse.convert_from(value)
        case Failure(error):
            match error:
                case NotFound() | NotBelongToWorkspace() | PrivateAgentAccessDenied():
                    _raise_memory_agent_not_found()
                case NotAdmin():
                    raise HTTPException(
                        status_code=status.HTTP_403_FORBIDDEN,
                        detail="Not allowed to manage agent-scope memory.",
                    )
                case DuplicateMemory():
                    raise HTTPException(
                        status_code=status.HTTP_409_CONFLICT,
                        detail="Memory name already exists in this scope.",
                    )
                case _:
                    assert_never(error)
        case _:
            assert_never(result)


@router.get("/workspaces/{handle}/agents/{agent_id}/memories/{memory_id}")
async def get_agent_memory(
    member: Annotated[WorkspaceMember, Depends(get_workspace_member)],
    service: Annotated[MemoryService, Depends()],
    *,
    agent_id: str,
    memory_id: str,
) -> MemoryResponse:
    """Get one visible Memory by ID."""
    result = await service.get_by_id(
        agent_id,
        memory_id,
        workspace_id=member.workspace_id,
        workspace_user_id=member.workspace_user_id,
        user_id=member.user_id,
        role=member.role,
    )
    match result:
        case Success(value):
            return MemoryResponse.convert_from(value)
        case Failure(error):
            match error:
                case NotFound() | NotBelongToWorkspace() | PrivateAgentAccessDenied():
                    _raise_memory_agent_not_found()
                case MemoryNotFound():
                    _raise_memory_not_found()
                case _:
                    assert_never(error)
        case _:
            assert_never(result)


@router.patch("/workspaces/{handle}/agents/{agent_id}/memories/{memory_id}")
async def update_agent_memory(
    member: Annotated[WorkspaceMember, Depends(get_workspace_member)],
    service: Annotated[MemoryService, Depends()],
    *,
    agent_id: str,
    memory_id: str,
    request_body: MemoryUpdateRequest,
) -> MemoryResponse:
    """Update one Memory by ID."""
    result = await service.update_by_id(
        agent_id,
        memory_id,
        _build_memory_update_input(request_body),
        workspace_id=member.workspace_id,
        workspace_user_id=member.workspace_user_id,
        user_id=member.user_id,
        role=member.role,
    )
    match result:
        case Success(value):
            return MemoryResponse.convert_from(value)
        case Failure(error):
            match error:
                case NotFound() | NotBelongToWorkspace() | PrivateAgentAccessDenied():
                    _raise_memory_agent_not_found()
                case MemoryNotFound():
                    _raise_memory_not_found()
                case NotAdmin():
                    raise HTTPException(
                        status_code=status.HTTP_403_FORBIDDEN,
                        detail="Not allowed to manage agent-scope memory.",
                    )
                case DuplicateMemory():
                    raise HTTPException(
                        status_code=status.HTTP_409_CONFLICT,
                        detail="Memory name already exists in this scope.",
                    )
                case _:
                    assert_never(error)
        case _:
            assert_never(result)


@router.delete(
    "/workspaces/{handle}/agents/{agent_id}/memories/{memory_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_agent_memory(
    member: Annotated[WorkspaceMember, Depends(get_workspace_member)],
    service: Annotated[MemoryService, Depends()],
    *,
    agent_id: str,
    memory_id: str,
) -> None:
    """Delete one Memory by ID."""
    result = await service.delete_by_id(
        agent_id,
        memory_id,
        workspace_id=member.workspace_id,
        workspace_user_id=member.workspace_user_id,
        user_id=member.user_id,
        role=member.role,
    )
    match result:
        case Success():
            return
        case Failure(error):
            match error:
                case NotFound() | NotBelongToWorkspace() | PrivateAgentAccessDenied():
                    _raise_memory_agent_not_found()
                case MemoryNotFound():
                    _raise_memory_not_found()
                case NotAdmin():
                    raise HTTPException(
                        status_code=status.HTTP_403_FORBIDDEN,
                        detail="Not allowed to manage agent-scope memory.",
                    )
                case _:
                    assert_never(error)
        case _:
            assert_never(result)


# --- Avatar ---


@router.post(
    "/workspaces/{handle}/agents/{agent_id}/avatar/upload-url",
)
async def request_avatar_upload(
    member: Annotated[WorkspaceMember, Depends(get_workspace_member)],
    service: Annotated[AgentService, Depends()],
    *,
    agent_id: str,
    request_body: AvatarUploadRequest,
) -> AvatarUploadTicketResponse:
    """Issue a presigned PUT ticket for avatar upload.

    Only administrators or workspace owners can do this. The ticket TTL is the
    server constant of 10 minutes. The client uploads the file directly with a
    PUT request to the issued `upload_url`, then calls the `finalize` endpoint.
    """
    result = await service.request_avatar_upload(
        agent_id,
        workspace_id=member.workspace_id,
        workspace_user_id=member.workspace_user_id,
        role=member.role,
        content_type=request_body.content_type,
        content_length=request_body.content_length,
    )
    match result:
        case Success(value):
            return AvatarUploadTicketResponse.convert_from(value)
        case Failure(error):
            match error:
                case NotFound() | NotBelongToWorkspace():
                    raise HTTPException(
                        status_code=status.HTTP_404_NOT_FOUND,
                        detail="Agent not found.",
                    )
                case NotAdmin():
                    raise HTTPException(
                        status_code=status.HTTP_403_FORBIDDEN,
                        detail="Not allowed to manage avatar.",
                    )
                case AvatarUploadRejected(message=message):
                    raise HTTPException(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        detail=message,
                    )
                case _:
                    assert_never(error)
        case _:
            assert_never(result)


@router.post(
    "/workspaces/{handle}/agents/{agent_id}/avatar/finalize",
)
async def finalize_avatar(
    member: Annotated[WorkspaceMember, Depends(get_workspace_member)],
    service: Annotated[AgentService, Depends()],
    *,
    agent_id: str,
    request_body: AvatarFinalizeRequest,
) -> AgentResponse:
    """Validate and resize the uploaded file, then apply it to the Agent.

    The server downloads the actual bytes from S3 and reruns handler validation,
    so it does not trust the client-reported size/type. On success, returns an
    `AgentResponse` containing the new thumbnail URL.
    """
    result = await service.finalize_avatar(
        agent_id,
        workspace_id=member.workspace_id,
        workspace_user_id=member.workspace_user_id,
        role=member.role,
        upload_key=request_body.upload_key,
        filename=request_body.filename,
    )
    match result:
        case Success(value):
            return AgentResponse.convert_from(value)
        case Failure(error):
            match error:
                case NotFound() | NotBelongToWorkspace():
                    raise HTTPException(
                        status_code=status.HTTP_404_NOT_FOUND,
                        detail="Agent not found.",
                    )
                case NotAdmin():
                    raise HTTPException(
                        status_code=status.HTTP_403_FORBIDDEN,
                        detail="Not allowed to manage avatar.",
                    )
                case AvatarUploadRejected(message=message):
                    raise HTTPException(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        detail=message,
                    )
                case _:
                    assert_never(error)
        case _:
            assert_never(result)


@router.delete(
    "/workspaces/{handle}/agents/{agent_id}/avatar",
)
async def remove_avatar(
    member: Annotated[WorkspaceMember, Depends(get_workspace_member)],
    service: Annotated[AgentService, Depends()],
    *,
    agent_id: str,
) -> AgentResponse:
    """Remove an Agent avatar.

    Only administrators or workspace owners can do this. Existing thumbnails in
    S3 are deleted best-effort, and garbage-collected by Lifecycle on failure.
    """
    result = await service.remove_avatar(
        agent_id,
        workspace_id=member.workspace_id,
        workspace_user_id=member.workspace_user_id,
        role=member.role,
    )
    match result:
        case Success(value):
            return AgentResponse.convert_from(value)
        case Failure(error):
            match error:
                case NotFound() | NotBelongToWorkspace():
                    raise HTTPException(
                        status_code=status.HTTP_404_NOT_FOUND,
                        detail="Agent not found.",
                    )
                case NotAdmin():
                    raise HTTPException(
                        status_code=status.HTTP_403_FORBIDDEN,
                        detail="Not allowed to manage avatar.",
                    )
                case _:
                    assert_never(error)
        case _:
            assert_never(result)


# --- Agent Admin ---


@router.get("/workspaces/{handle}/agents/{agent_id}/admins")
async def list_agent_admins(
    member: Annotated[WorkspaceMember, Depends(get_workspace_member)],
    service: Annotated[AgentService, Depends()],
    *,
    agent_id: str,
) -> AgentAdminListResponse:
    """List Agent administrators.

    Any workspace member can view them.
    """
    result = await service.list_admins(agent_id, workspace_id=member.workspace_id)
    match result:
        case Success(value):
            return AgentAdminListResponse(
                items=[AgentAdminResponse.convert_from(a) for a in value.items]
            )
        case Failure(error):
            match error:
                case NotFound() | NotBelongToWorkspace():
                    raise HTTPException(
                        status_code=status.HTTP_404_NOT_FOUND,
                        detail="Agent not found.",
                    )
                case _:
                    assert_never(error)
        case _:
            assert_never(result)


@router.post(
    "/workspaces/{handle}/agents/{agent_id}/admins",
    status_code=status.HTTP_201_CREATED,
)
async def add_agent_admin(
    member: Annotated[WorkspaceMember, Depends(get_workspace_member)],
    service: Annotated[AgentService, Depends()],
    *,
    agent_id: str,
    request_body: AgentAdminAddRequest,
) -> AgentAdminResponse:
    """Add an administrator to an Agent.

    Only existing administrators or workspace owners can add one.
    """
    result = await service.add_admin(
        agent_id,
        request_body.workspace_user_id,
        workspace_id=member.workspace_id,
        workspace_user_id=member.workspace_user_id,
        role=member.role,
    )
    match result:
        case Success(value):
            return AgentAdminResponse.convert_from(value)
        case Failure(error):
            match error:
                case NotFound() | NotBelongToWorkspace():
                    raise HTTPException(
                        status_code=status.HTTP_404_NOT_FOUND,
                        detail="Agent not found.",
                    )
                case NotAdmin():
                    raise HTTPException(
                        status_code=status.HTTP_403_FORBIDDEN,
                        detail="Not allowed to manage this agent.",
                    )
                case DuplicateAdmin():
                    raise HTTPException(
                        status_code=status.HTTP_409_CONFLICT,
                        detail="Already registered as an administrator.",
                    )
                case WorkspaceUserNotFound():
                    raise HTTPException(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        detail="Workspace member not found.",
                    )
                case _:
                    assert_never(error)
        case _:
            assert_never(result)


@router.delete(
    "/workspaces/{handle}/agents/{agent_id}/admins/{admin_workspace_user_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def remove_agent_admin(
    member: Annotated[WorkspaceMember, Depends(get_workspace_member)],
    service: Annotated[AgentService, Depends()],
    *,
    agent_id: str,
    admin_workspace_user_id: str,
) -> None:
    """Remove an administrator from an Agent.

    Only existing administrators or workspace owners can remove one.
    The last administrator cannot be removed.
    """
    result = await service.remove_admin(
        agent_id,
        admin_workspace_user_id,
        workspace_id=member.workspace_id,
        workspace_user_id=member.workspace_user_id,
        role=member.role,
    )
    match result:
        case Success():
            return
        case Failure(error):
            match error:
                case NotFound() | NotBelongToWorkspace():
                    raise HTTPException(
                        status_code=status.HTTP_404_NOT_FOUND,
                        detail="Agent not found.",
                    )
                case NotAdmin():
                    raise HTTPException(
                        status_code=status.HTTP_403_FORBIDDEN,
                        detail="Not allowed to manage this agent.",
                    )
                case LastAdminCannotBeRemoved():
                    raise HTTPException(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        detail="The last administrator cannot be removed.",
                    )
                case AdminNotFound():
                    raise HTTPException(
                        status_code=status.HTTP_404_NOT_FOUND,
                        detail="That member is not an administrator.",
                    )
                case _:
                    assert_never(error)
        case _:
            assert_never(result)


def mount(mounter: RouteMounter) -> None:
    """Mount Agent v1 routes."""
    mounter(
        router,
        prefix="/agent/v1",
        tag="Agent v1",
        description=dedent(
            """
            Agent API (Public)

            Workspace-scoped Agent CRUD and administrator management endpoints.
            """
        ),
    )
