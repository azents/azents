"""Authorized Agent Vault settings routes."""

from collections.abc import Callable, Coroutine
from typing import Annotated, Any, assert_never

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.routing import APIRoute
from pydantic import BaseModel, ConfigDict, Field, SecretStr

from azents.core.auth.deps import (
    CurrentUser,
    WorkspaceMember,
    get_current_user,
    get_workspace_member,
)
from azents.core.vault_request import VaultRequestId, VaultRequestSubmission
from azents.repos.agent_vault import InvalidVaultEntry, VaultAccessDenied, VaultManager
from azents.repos.agent_vault_requests import (
    VaultRequestClosed,
    VaultRequestScope,
    VaultRequestView,
)
from azents.services.account_access import AccountAccessService
from azents.services.agent_vault import (
    AgentVaultService,
    AgentVaultSettings,
    VaultSettingsDenial,
    VaultSettingsError,
)
from azents.services.agent_vault_requests import AgentVaultRequestService


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
            except VaultAccessDenied:
                raise HTTPException(
                    404,
                    "Vault request not found.",
                    headers={"Cache-Control": "no-store"},
                ) from None
            except VaultRequestClosed:
                raise HTTPException(
                    409,
                    "Vault request is not open.",
                    headers={"Cache-Control": "no-store"},
                ) from None
            except InvalidVaultEntry:
                raise HTTPException(
                    422,
                    "Invalid Vault request values.",
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
_REQUEST = (
    "/workspaces/{handle}/agents/{agent_id}/sessions/{session_id}"
    "/vault/requests/{request_id}"
)


async def _request_scope(
    current_user: Annotated[CurrentUser, Depends(get_current_user)],
    access_service: Annotated[AccountAccessService, Depends(AccountAccessService)],
    *,
    handle: str,
    session_id: str,
    agent_id: str,
) -> VaultRequestScope:
    access = await access_service.read_workspace_membership(
        handle=handle, user_id=current_user.user_id
    )
    if access.workspace_id is None or access.membership is None:
        raise VaultAccessDenied("Vault request not found.")
    return VaultRequestScope(
        session_id=session_id,
        agent_id=agent_id,
        manager=VaultManager(access.workspace_id, current_user.user_id),
    )


@router.get(_REQUEST)
async def read_vault_request(
    scope: Annotated[VaultRequestScope, Depends(_request_scope)],
    service: Annotated[AgentVaultRequestService, Depends(AgentVaultRequestService)],
    *,
    request_id: VaultRequestId,
) -> VaultRequestView:
    """Read value-free metadata and current status for an exact chat card."""
    return await service.read(scope, request_id)


@router.post(_REQUEST, status_code=204, response_class=Response)
async def submit_vault_request(
    scope: Annotated[VaultRequestScope, Depends(_request_scope)],
    service: Annotated[AgentVaultRequestService, Depends(AgentVaultRequestService)],
    *,
    request_id: VaultRequestId,
    request_body: VaultRequestSubmission,
) -> None:
    """Submit all requested values at once without echoing them."""
    await service.submit(scope, request_id, request_body)


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
