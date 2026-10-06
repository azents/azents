"""Public Saved Memory paging contract and safe cursor errors."""

from unittest.mock import AsyncMock

import pytest
from azcommon.result import Failure, Success
from fastapi import FastAPI
from fastapi.testclient import TestClient

from azents.core.auth.deps import WorkspaceMember, get_workspace_member
from azents.core.enums import WorkspaceUserRole
from azents.core.memory_scope import MemoryScope
from azents.services.memory import MemoryService
from azents.services.memory.data import MemoryCursorInvalid, MemoryListOutput

from . import router


def _create_app() -> FastAPI:
    app = FastAPI()
    app.include_router(router, prefix="/agent/v1")
    return app


_APP = _create_app()


@pytest.fixture(autouse=True)
def _clear_overrides() -> None:
    _APP.dependency_overrides.clear()


def _client(service: AsyncMock) -> TestClient:
    _APP.dependency_overrides[MemoryService] = lambda: service
    _APP.dependency_overrides[get_workspace_member] = lambda: WorkspaceMember(
        user_id="user-1",
        workspace_id="workspace-1",
        workspace_user_id="member-1",
        role=WorkspaceUserRole.MEMBER,
        permissions=set(),
        session_id="auth-1",
    )
    return TestClient(_APP)


def test_saved_page_forwards_cursor_and_exact_scope() -> None:
    service = AsyncMock(spec=MemoryService)
    service.list_by_agent.return_value = Success(
        MemoryListOutput(items=[], next_cursor="next-page")
    )
    response = _client(service).get(
        "/agent/v1/workspaces/workspace/agents/agent-1/memories",
        params={"scope": "user", "cursor": "page", "limit": 7, "query": "delivery"},
    )
    assert response.status_code == 200
    assert response.json() == {"items": [], "next_cursor": "next-page"}
    service.list_by_agent.assert_awaited_once_with(
        "agent-1",
        workspace_id="workspace-1",
        workspace_user_id="member-1",
        user_id="user-1",
        role=WorkspaceUserRole.MEMBER,
        scope=MemoryScope.USER,
        type=None,
        query="delivery",
        cursor="page",
        limit=7,
    )


def test_saved_page_defaults_to_bounded_first_page() -> None:
    service = AsyncMock(spec=MemoryService)
    service.list_by_agent.return_value = Success(
        MemoryListOutput(items=[], next_cursor=None)
    )
    response = _client(service).get(
        "/agent/v1/workspaces/workspace/agents/agent-1/memories",
        params={"scope": "agent"},
    )
    assert response.status_code == 200
    assert response.json() == {"items": [], "next_cursor": None}
    assert service.list_by_agent.await_args is not None
    assert service.list_by_agent.await_args.kwargs["cursor"] is None
    assert service.list_by_agent.await_args.kwargs["limit"] == 20


def test_saved_cursor_error_does_not_echo_payload() -> None:
    service = AsyncMock(spec=MemoryService)
    service.list_by_agent.return_value = Failure(
        MemoryCursorInvalid(message="private cursor detail")
    )
    response = _client(service).get(
        "/agent/v1/workspaces/workspace/agents/agent-1/memories",
        params={"scope": "agent", "cursor": "private"},
    )
    assert response.status_code == 422
    assert response.json() == {"detail": "Memory cursor is invalid."}
    assert "private" not in response.text


@pytest.mark.parametrize("limit", [0, -1, 101])
def test_saved_page_rejects_invalid_http_limit(limit: int) -> None:
    service = AsyncMock(spec=MemoryService)
    response = _client(service).get(
        "/agent/v1/workspaces/workspace/agents/agent-1/memories",
        params={"scope": "agent", "limit": limit},
    )
    assert response.status_code == 422
    service.list_by_agent.assert_not_awaited()
