"""Agent-owned Toolkit Public API authorization tests."""

from typing import Any, cast
from unittest.mock import AsyncMock, MagicMock

import pytest
from azcommon.result import Failure
from fastapi import HTTPException

from azents.api.public.toolkit.v1 import (
    create_agent_toolkit_config,
    get_agent_toolkit_config,
    list_agent_toolkit_management,
)
from azents.api.public.toolkit.v1.data import AgentToolkitConfigCreateRequest
from azents.core.auth.deps import WorkspaceMember
from azents.core.enums import WorkspaceUserRole
from azents.services.agent.data import NotAdmin
from azents.services.toolkit import ToolkitService
from azents.services.toolkit.data import AgentNotBelongToWorkspace


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
    service = cast(Any, MagicMock(spec=ToolkitService))
    service.list_agent_management = AsyncMock(
        return_value=Failure(NotAdmin(agent_id="agent-1"))
    )

    with pytest.raises(HTTPException) as raised:
        await list_agent_toolkit_management(
            _member(),
            cast(ToolkitService, service),
            agent_id="agent-1",
        )

    assert raised.value.status_code == 403
    assert raised.value.detail == (
        "Agent administrator or workspace owner access required."
    )


async def test_management_collection_returns_404_for_cross_workspace_agent() -> None:
    """A collection request does not expose an Agent in another Workspace."""
    service = cast(Any, MagicMock(spec=ToolkitService))
    service.list_agent_management = AsyncMock(
        return_value=Failure(AgentNotBelongToWorkspace(agent_id="agent-1"))
    )

    with pytest.raises(HTTPException) as raised:
        await list_agent_toolkit_management(
            _member(role=WorkspaceUserRole.OWNER),
            cast(ToolkitService, service),
            agent_id="agent-1",
        )

    assert raised.value.status_code == 404
    assert raised.value.detail == "Agent not found."


async def test_create_returns_403_without_agent_authority() -> None:
    """Workspace Manager status alone cannot create an Agent-owned Toolkit."""
    service = cast(Any, MagicMock(spec=ToolkitService))
    service.create_agent_owned = AsyncMock(
        return_value=Failure(NotAdmin(agent_id="agent-1"))
    )

    with pytest.raises(HTTPException) as raised:
        await create_agent_toolkit_config(
            _member(),
            cast(ToolkitService, service),
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
    service = cast(Any, MagicMock(spec=ToolkitService))
    service.get_agent_owned = AsyncMock(
        return_value=Failure(NotAdmin(agent_id="agent-1"))
    )

    with pytest.raises(HTTPException) as raised:
        await get_agent_toolkit_config(
            _member(),
            cast(ToolkitService, service),
            agent_id="agent-1",
            toolkit_config_id="toolkit-secret",
        )

    assert raised.value.status_code == 404
    assert raised.value.detail == "Toolkit config not found."
