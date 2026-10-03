"""Historical Memory settings Public API route tests."""

import datetime
from unittest.mock import AsyncMock

import pytest
from azcommon.result import Failure, Success
from fastapi import FastAPI
from fastapi.testclient import TestClient

from azents.core.auth.deps import WorkspaceMember, get_workspace_member
from azents.core.enums import WorkspaceUserRole
from azents.core.historical_memory_settings import (
    HistoricalMemorySettingsScope,
)
from azents.repos.historical_memory.settings import (
    HistoricalMemorySettingsRepository,
)
from azents.services.historical_memory.settings import (
    HistoricalMemorySettingsService,
)
from azents.services.historical_memory.settings_data import (
    HistoricalMemorySettingsCursorInvalid,
    HistoricalMemorySettingsListOutput,
    HistoricalMemorySettingsNotFound,
    HistoricalMemorySettingsOutput,
)
from azents.services.memory import MemoryService

from . import router

_NOW = datetime.datetime(2026, 10, 1, 12, 0, tzinfo=datetime.UTC)
_SOURCE_ID = "s" * 32


def _create_route_app() -> FastAPI:
    """Create the Agent route app once for this test module."""
    app = FastAPI()
    app.include_router(router, prefix="/agent/v1")
    return app


_ROUTE_APP = _create_route_app()


@pytest.fixture(autouse=True)
def _reset_dependency_overrides() -> None:
    """Prevent dependency overrides from leaking between tests."""
    _ROUTE_APP.dependency_overrides.clear()


def _record() -> HistoricalMemorySettingsOutput:
    """Build one visible Historical Memory service output."""
    return HistoricalMemorySettingsOutput(
        source_session_id=_SOURCE_ID,
        scope=HistoricalMemorySettingsScope.TEAM,
        source_title="Delivery",
        source_activity_through=_NOW,
        prepared_at=_NOW,
        summary="Prepared delivery result",
    )


def _client(service: AsyncMock | HistoricalMemorySettingsService) -> TestClient:
    """Create a public API client with service and member overrides."""
    _ROUTE_APP.dependency_overrides[HistoricalMemorySettingsService] = lambda: service
    _ROUTE_APP.dependency_overrides[get_workspace_member] = lambda: WorkspaceMember(
        user_id="user-1",
        workspace_id="workspace-1",
        workspace_user_id="workspace-user-1",
        role=WorkspaceUserRole.MEMBER,
        permissions=set(),
        session_id="auth-session-1",
    )
    return TestClient(_ROUTE_APP)


def test_list_returns_page_and_authorized_source_path() -> None:
    """List maps exact scope, cursor, and source navigation fields."""
    service = AsyncMock(spec=HistoricalMemorySettingsService)
    service.list.return_value = Success(
        HistoricalMemorySettingsListOutput(
            items=(_record(),),
            next_cursor="next",
        )
    )

    response = _client(service).get(
        "/agent/v1/workspaces/workspace/agents/agent-1/historical-memories",
        params={
            "scope": "team",
            "query": "delivery",
            "cursor": "cursor",
            "limit": 10,
        },
    )

    assert response.status_code == 200
    assert response.json() == {
        "items": [
            {
                "source_session_id": _SOURCE_ID,
                "scope": "team",
                "source_title": "Delivery",
                "source_activity_through": "2026-10-01T12:00:00Z",
                "prepared_at": "2026-10-01T12:00:00Z",
                "summary": "Prepared delivery result",
                "source_path": (f"/w/workspace/agents/agent-1/sessions/{_SOURCE_ID}"),
            }
        ],
        "next_cursor": "next",
    }
    service.list.assert_awaited_once_with(
        "agent-1",
        workspace_id="workspace-1",
        workspace_user_id="workspace-user-1",
        user_id="user-1",
        role=WorkspaceUserRole.MEMBER,
        scope=HistoricalMemorySettingsScope.TEAM,
        query="delivery",
        cursor="cursor",
        limit=10,
    )


def test_list_maps_malformed_cursor_to_safe_422() -> None:
    """Malformed cursor details do not echo cursor contents."""
    service = AsyncMock(spec=HistoricalMemorySettingsService)
    service.list.return_value = Failure(
        HistoricalMemorySettingsCursorInvalid(message="secret cursor detail")
    )

    response = _client(service).get(
        "/agent/v1/workspaces/workspace/agents/agent-1/historical-memories",
        params={"scope": "team", "cursor": "secret"},
    )

    assert response.status_code == 422
    assert response.json() == {"detail": "Historical Memory cursor is invalid."}
    assert "secret" not in response.text


@pytest.mark.parametrize("cursor", ["\ud55c\uae00", "\U0001f680"])
def test_unicode_cursor_uses_real_service_and_decoder_for_safe_422(cursor: str) -> None:
    """Unicode query input is normalized through the real decoding boundary."""
    memory_service = AsyncMock(spec=MemoryService)
    memory_service.get_visible_agent.return_value = Success(object())
    session_manager = AsyncMock()
    service = HistoricalMemorySettingsService(
        repository=HistoricalMemorySettingsRepository(
            session_manager=session_manager,
        ),
        memory_service=memory_service,
    )

    response = _client(service).get(
        "/agent/v1/workspaces/workspace/agents/agent-1/historical-memories",
        params={"scope": "team", "cursor": cursor},
    )

    assert response.status_code == 422
    assert response.json() == {"detail": "Historical Memory cursor is invalid."}
    assert cursor not in response.text
    memory_service.get_visible_agent.assert_awaited_once()
    session_manager.assert_not_called()


def test_detail_maps_every_invisible_source_to_memory_not_found() -> None:
    """Historical source visibility failures use the Memory non-enumerating error."""
    service = AsyncMock(spec=HistoricalMemorySettingsService)
    service.get.return_value = Failure(
        HistoricalMemorySettingsNotFound(source_session_id=_SOURCE_ID)
    )

    response = _client(service).get(
        f"/agent/v1/workspaces/workspace/agents/agent-1/"
        f"historical-memories/{_SOURCE_ID}"
    )

    assert response.status_code == 404
    assert response.json() == {"detail": "Memory not found."}


def test_openapi_exposes_read_only_historical_operations() -> None:
    """The Historical Memory resource publishes GET operations only."""
    openapi = _ROUTE_APP.openapi()
    collection = openapi["paths"][
        "/agent/v1/workspaces/{handle}/agents/{agent_id}/historical-memories"
    ]
    detail = openapi["paths"][
        "/agent/v1/workspaces/{handle}/agents/{agent_id}/historical-memories/"
        "{source_session_id}"
    ]

    assert set(collection) == {"get"}
    assert set(detail) == {"get"}
