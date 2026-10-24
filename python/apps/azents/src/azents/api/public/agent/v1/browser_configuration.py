"""Per-Agent browser selection and exact-current application evidence."""

from typing import Annotated, NoReturn, assert_never

from azents_runtime_control.browser_configuration import BrowserImplementation
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from azents.core.auth.deps import WorkspaceMember, get_workspace_member
from azents.core.browser_configuration import (
    AgentBrowserConfiguration,
    BrowserConfigurationDenial,
)
from azents.services.browser_configuration import AgentBrowserConfigurationService

router = APIRouter()


class BrowserConfigurationReplaceRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_intent_id: str = Field(min_length=32, max_length=32, pattern="^[0-9a-f]+$")
    implementation: BrowserImplementation
    retry: bool


def _deny(denial: BrowserConfigurationDenial) -> NoReturn:
    match denial:
        case BrowserConfigurationDenial.NOT_FOUND:
            raise HTTPException(404, "Agent not found.")
        case BrowserConfigurationDenial.ADMIN_REQUIRED:
            raise HTTPException(403, "Not allowed to manage this Agent.")
        case BrowserConfigurationDenial.STALE_INTENT:
            raise HTTPException(
                409,
                {
                    "code": "browser_configuration_stale",
                    "message": "Browser settings changed elsewhere. Refresh and retry.",
                },
            )
        case BrowserConfigurationDenial.AGENT_INACTIVE:
            raise HTTPException(
                409, {"code": "agent_inactive", "message": "Agent is not active."}
            )
        case _:
            assert_never(denial)


@router.get("/workspaces/{handle}/agents/{agent_id}/browser-configuration")
async def get_browser_configuration(
    member: Annotated[WorkspaceMember, Depends(get_workspace_member)],
    service: Annotated[AgentBrowserConfigurationService, Depends()],
    *,
    agent_id: str,
) -> AgentBrowserConfiguration:
    """Read requested choice and current-Runner application evidence."""
    result = await service.read(
        agent_id=agent_id,
        workspace_id=member.workspace_id,
        workspace_user_id=member.workspace_user_id,
        role=member.role,
    )
    if result.success:
        return result.value
    _deny(result.error)


@router.put("/workspaces/{handle}/agents/{agent_id}/browser-configuration")
async def replace_browser_configuration(
    member: Annotated[WorkspaceMember, Depends(get_workspace_member)],
    service: Annotated[AgentBrowserConfigurationService, Depends()],
    *,
    agent_id: str,
    request_body: BrowserConfigurationReplaceRequest,
) -> AgentBrowserConfiguration:
    """Save confirmed selection and immediately start browser-only application."""
    result = await service.replace(
        agent_id=agent_id,
        workspace_id=member.workspace_id,
        workspace_user_id=member.workspace_user_id,
        expected_intent_id=request_body.expected_intent_id,
        implementation=request_body.implementation,
        retry=request_body.retry,
    )
    if result.success:
        return result.value
    _deny(result.error)
