"""Authorized Agent Vault settings routes."""

from collections.abc import Callable, Coroutine
from typing import Annotated, Any, assert_never

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.routing import APIRoute
from pydantic import BaseModel, ConfigDict, Field, SecretStr

from azents.core.auth.deps import WorkspaceMember, get_workspace_member
from azents.services.agent_vault import (
    AgentVaultService,
    AgentVaultSettings,
    VaultSettingsDenial,
    VaultSettingsError,
)


class VaultRoute(APIRoute):
    """Prevent secret-bearing request validation from echoing input."""

    def get_route_handler(self) -> Callable[[Request], Coroutine[Any, Any, Response]]:
        handler = super().get_route_handler()

        async def safe_handler(request: Request) -> Response:
            try:
                response = await handler(request)
            except RequestValidationError:
                raise HTTPException(
                    422,
                    "Invalid Vault request.",
                    headers={"Cache-Control": "no-store"},
                ) from None
            except VaultSettingsError as error:
                match error.reason:
                    case VaultSettingsDenial.NOT_FOUND:
                        status, message = 404, "Vault entry or Agent not found."
                    case VaultSettingsDenial.CONFLICT:
                        status, message = 409, "Vault entry already exists."
                    case VaultSettingsDenial.INVALID:
                        status, message = 422, "Invalid Vault entry."
                    case _:
                        assert_never(error.reason)
                raise HTTPException(
                    status, message, headers={"Cache-Control": "no-store"}
                ) from None
            response.headers["Cache-Control"] = "no-store"
            return response

        return safe_handler


class VaultEntryWriteRequest(BaseModel):
    """Explicit write of one named Vault value."""

    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)
    name: str = Field(strict=True, min_length=1, max_length=255)
    value: SecretStr = Field(max_length=32768)


router = APIRouter(route_class=VaultRoute)
_ENTRIES = "/workspaces/{handle}/agents/{agent_id}/vault/entries"


@router.get(_ENTRIES)
async def list_agent_vault_entries(
    member: Annotated[WorkspaceMember, Depends(get_workspace_member)],
    service: Annotated[AgentVaultService, Depends(AgentVaultService)],
    *,
    agent_id: str,
) -> AgentVaultSettings:
    """List Vault entry metadata for the exact Agent."""
    return await service.list_entries(
        agent_id, workspace_id=member.workspace_id, user_id=member.user_id
    )


@router.post(_ENTRIES, status_code=204, response_class=Response)
async def create_agent_vault_entry(
    member: Annotated[WorkspaceMember, Depends(get_workspace_member)],
    service: Annotated[AgentVaultService, Depends(AgentVaultService)],
    *,
    agent_id: str,
    request_body: VaultEntryWriteRequest,
) -> None:
    """Create an entry; an existing exact name is a conflict."""
    await service.create_entry(
        agent_id,
        request_body.name,
        request_body.value,
        workspace_id=member.workspace_id,
        user_id=member.user_id,
    )


@router.put(_ENTRIES, status_code=204, response_class=Response)
async def replace_agent_vault_entry(
    member: Annotated[WorkspaceMember, Depends(get_workspace_member)],
    service: Annotated[AgentVaultService, Depends(AgentVaultService)],
    *,
    agent_id: str,
    request_body: VaultEntryWriteRequest,
) -> None:
    """Replace an existing entry's value without returning it."""
    await service.replace_entry(
        agent_id,
        request_body.name,
        request_body.value,
        workspace_id=member.workspace_id,
        user_id=member.user_id,
    )


@router.delete(_ENTRIES, status_code=204, response_class=Response)
async def delete_agent_vault_entry(
    member: Annotated[WorkspaceMember, Depends(get_workspace_member)],
    service: Annotated[AgentVaultService, Depends(AgentVaultService)],
    *,
    agent_id: str,
    name: Annotated[str, Query(min_length=1, max_length=255)],
) -> None:
    """Delete an exact existing entry name."""
    await service.delete_entry(
        agent_id, name, workspace_id=member.workspace_id, user_id=member.user_id
    )
