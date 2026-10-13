"""Agent-only Runtime environment API with sanitized secret-input errors."""

from collections.abc import Callable, Coroutine
from typing import Annotated, Any, NoReturn, assert_never

from azcommon.result import Failure, Success
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.routing import APIRoute
from pydantic import BaseModel, ConfigDict

from azents.core.auth.deps import WorkspaceMember, get_workspace_member
from azents.core.runtime_environment import (
    InvalidRuntimeEnvironment,
    RuntimeEnvironmentAccessError,
    RuntimeEnvironmentEntryEdit,
)
from azents.services.agent_runtime_environment import (
    AgentRuntimeEnvironmentService,
    RuntimeEnvironmentSettings,
)


class RuntimeEnvironmentRoute(APIRoute):
    """Prevent FastAPI validation from echoing raw credential inputs."""

    def get_route_handler(self) -> Callable[[Request], Coroutine[Any, Any, Response]]:
        handler = super().get_route_handler()

        async def safe_handler(request: Request) -> Response:
            try:
                return await handler(request)
            except RequestValidationError:
                raise HTTPException(
                    status_code=422, detail="Invalid Runtime environment request."
                ) from None

        return safe_handler


class ReplaceRuntimeEnvironmentRequest(BaseModel):
    """Complete desired list; omission deletes, stored references retain values."""

    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)
    entries: list[RuntimeEnvironmentEntryEdit]


router = APIRouter(route_class=RuntimeEnvironmentRoute)


def _raise_access_error(error: RuntimeEnvironmentAccessError) -> NoReturn:
    match error:
        case RuntimeEnvironmentAccessError.NOT_FOUND:
            raise HTTPException(status_code=404, detail="Agent not found.")
        case RuntimeEnvironmentAccessError.DENIED:
            raise HTTPException(status_code=403, detail="Agent settings access denied.")
        case _:
            assert_never(error)


@router.get("/workspaces/{handle}/agents/{agent_id}/runtime/environment")
async def get_runtime_environment(
    member: Annotated[WorkspaceMember, Depends(get_workspace_member)],
    service: Annotated[
        AgentRuntimeEnvironmentService, Depends(AgentRuntimeEnvironmentService)
    ],
    *,
    agent_id: str,
) -> RuntimeEnvironmentSettings:
    """Get environment names for this Agent without exposing values."""
    result = await service.get(
        agent_id,
        workspace_id=member.workspace_id,
        workspace_user_id=member.workspace_user_id,
        role=member.role,
    )
    match result:
        case Success(settings):
            return settings
        case Failure(error):
            _raise_access_error(error)
        case _:
            assert_never(result)


@router.put("/workspaces/{handle}/agents/{agent_id}/runtime/environment")
async def replace_runtime_environment(
    member: Annotated[WorkspaceMember, Depends(get_workspace_member)],
    service: Annotated[
        AgentRuntimeEnvironmentService, Depends(AgentRuntimeEnvironmentService)
    ],
    *,
    agent_id: str,
    request_body: ReplaceRuntimeEnvironmentRequest,
) -> RuntimeEnvironmentSettings:
    """Replace environment variables under Agent management authorization."""
    try:
        result = await service.replace(
            agent_id,
            edits=request_body.entries,
            workspace_id=member.workspace_id,
            workspace_user_id=member.workspace_user_id,
            role=member.role,
        )
    except InvalidRuntimeEnvironment as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from None
    match result:
        case Success(settings):
            return settings
        case Failure(error):
            _raise_access_error(error)
        case _:
            assert_never(result)
