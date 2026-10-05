"""Agent-owned Toolkit Public API authorization tests."""

import pytest
from azcommon.result import Failure, Result
from fastapi import HTTPException

from azents.api.public.toolkit.v1 import (
    create_agent_toolkit_config,
    get_agent_toolkit_config,
    list_agent_toolkit_management,
)
from azents.api.public.toolkit.v1.data import AgentToolkitConfigCreateRequest
from azents.core.auth.deps import WorkspaceMember
from azents.core.enums import WorkspaceUserRole
from azents.core.toolkit_errors import NotFound
from azents.services.agent.data import NotAdmin
from azents.services.toolkit import ToolkitService
from azents.services.toolkit.data import (
    AgentNotBelongToWorkspace,
    AgentToolkitManagementOutput,
    InvalidConfig,
    InvalidCredentials,
    InvalidIdentifier,
    InvalidToolkitType,
    ToolkitCreateInput,
    ToolkitOutput,
)


class _ToolkitAuthorizationServiceFake(ToolkitService):
    """Return typed authorization failures through the real service contract."""

    def __init__(self, error: NotAdmin | AgentNotBelongToWorkspace) -> None:
        self.error = error

    async def list_agent_management(
        self,
        agent_id: str,
        *,
        workspace_id: str,
        workspace_user_id: str,
        user_id: str,
        role: WorkspaceUserRole,
    ) -> Result[AgentToolkitManagementOutput, AgentNotBelongToWorkspace | NotAdmin]:
        return Failure(self.error)

    async def create_agent_owned(
        self,
        agent_id: str,
        create: ToolkitCreateInput,
        *,
        workspace_id: str,
        workspace_user_id: str,
        user_id: str,
        role: WorkspaceUserRole,
    ) -> Result[
        ToolkitOutput,
        AgentNotBelongToWorkspace
        | NotAdmin
        | InvalidToolkitType
        | InvalidConfig
        | InvalidIdentifier
        | InvalidCredentials,
    ]:
        return Failure(self.error)

    async def get_agent_owned(
        self,
        agent_id: str,
        toolkit_id: str,
        *,
        workspace_id: str,
        workspace_user_id: str,
        role: WorkspaceUserRole,
    ) -> Result[ToolkitOutput, AgentNotBelongToWorkspace | NotAdmin | NotFound]:
        return Failure(self.error)


def _member(*, role: WorkspaceUserRole = WorkspaceUserRole.MANAGER) -> WorkspaceMember:
    """Build a Workspace member context for direct route tests."""
    return WorkspaceMember(
        user_id="user-1",
        workspace_id="workspace-1",
        workspace_user_id="workspace-user-1",
        role=role,
        permissions=set(),
        session_id="session-1",
    )


async def test_management_collection_returns_403_without_agent_authority() -> None:
    """Collection authorization denial identifies the required authority."""
    service = _ToolkitAuthorizationServiceFake(NotAdmin(agent_id="agent-1"))

    with pytest.raises(HTTPException) as raised:
        await list_agent_toolkit_management(
            _member(),
            service,
            agent_id="agent-1",
        )

    assert raised.value.status_code == 403
    assert raised.value.detail == (
        "Agent administrator or workspace owner access required."
    )


async def test_management_collection_returns_404_for_cross_workspace_agent() -> None:
    """A collection request does not expose an Agent in another Workspace."""
    service = _ToolkitAuthorizationServiceFake(
        AgentNotBelongToWorkspace(agent_id="agent-1")
    )

    with pytest.raises(HTTPException) as raised:
        await list_agent_toolkit_management(
            _member(role=WorkspaceUserRole.OWNER),
            service,
            agent_id="agent-1",
        )

    assert raised.value.status_code == 404
    assert raised.value.detail == "Agent not found."


async def test_create_returns_403_without_agent_authority() -> None:
    """Workspace Manager status alone cannot create an Agent-owned Toolkit."""
    service = _ToolkitAuthorizationServiceFake(NotAdmin(agent_id="agent-1"))

    with pytest.raises(HTTPException) as raised:
        await create_agent_toolkit_config(
            _member(),
            service,
            agent_id="agent-1",
            request_body=AgentToolkitConfigCreateRequest(
                toolkit_type="mcp",
                name="Private MCP",
                config={"server_url": "https://mcp.test", "auth_type": "none"},
                always_expose_tools=False,
            ),
        )

    assert raised.value.status_code == 403


async def test_item_authority_denial_uses_nondisclosing_404() -> None:
    """Unauthorized item reads share the missing-item response boundary."""
    service = _ToolkitAuthorizationServiceFake(NotAdmin(agent_id="agent-1"))

    with pytest.raises(HTTPException) as raised:
        await get_agent_toolkit_config(
            _member(),
            service,
            agent_id="agent-1",
            toolkit_config_id="toolkit-secret",
        )

    assert raised.value.status_code == 404
    assert raised.value.detail == "Toolkit config not found."
