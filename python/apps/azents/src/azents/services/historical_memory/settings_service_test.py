"""Historical Memory settings service tests."""

import dataclasses
import datetime
from unittest.mock import AsyncMock

from azcommon.result import Failure, Success

from azents.core.enums import WorkspaceUserRole
from azents.core.historical_memory_settings import HistoricalMemorySettingsScope
from azents.repos.historical_memory.settings import (
    HistoricalMemorySettingsRepository,
)
from azents.repos.historical_memory.settings_data import (
    HistoricalMemorySettingsCursorError,
    HistoricalMemorySettingsPage,
    HistoricalMemorySettingsRecord,
)
from azents.services.agent.data import PrivateAgentAccessDenied
from azents.services.historical_memory.settings import (
    HistoricalMemorySettingsService,
)
from azents.services.historical_memory.settings_data import (
    HistoricalMemorySettingsCursorInvalid,
    HistoricalMemorySettingsNotFound,
)
from azents.services.memory import MemoryService

_NOW = datetime.datetime(2026, 10, 1, 12, 0, tzinfo=datetime.UTC)
_SOURCE_ID = "s" * 32


def _record() -> HistoricalMemorySettingsRecord:
    """Build one repository record."""
    return HistoricalMemorySettingsRecord(
        source_session_id=_SOURCE_ID,
        scope=HistoricalMemorySettingsScope.TEAM,
        source_title="Delivery",
        source_activity_through=_NOW,
        prepared_at=_NOW,
        summary="Prepared result",
    )


@dataclasses.dataclass(frozen=True)
class _ServiceFixture:
    """Service and its independently configurable async mocks."""

    service: HistoricalMemorySettingsService
    repository: AsyncMock
    memory_service: AsyncMock


def _service() -> _ServiceFixture:
    """Create the service with typed async mocks."""
    repository = AsyncMock(spec=HistoricalMemorySettingsRepository)
    memory_service = AsyncMock(spec=MemoryService)
    service = HistoricalMemorySettingsService(
        repository=repository,
        memory_service=memory_service,
    )
    return _ServiceFixture(
        service=service,
        repository=repository,
        memory_service=memory_service,
    )


async def test_list_checks_agent_visibility_then_returns_repository_page() -> None:
    """Settings list reuses current Agent visibility before the source query."""
    fixture = _service()
    fixture.memory_service.get_visible_agent.return_value = Success(object())
    fixture.repository.list.return_value = HistoricalMemorySettingsPage(
        items=(_record(),),
        next_cursor="next",
    )

    result = await fixture.service.list(
        "agent-1",
        workspace_id="workspace-1",
        workspace_user_id="workspace-user-1",
        user_id="user-1",
        role=WorkspaceUserRole.MEMBER,
        scope=HistoricalMemorySettingsScope.TEAM,
        query="delivery",
        cursor=None,
        limit=20,
    )

    assert isinstance(result, Success)
    assert result.value.items[0].source_session_id == _SOURCE_ID
    assert result.value.next_cursor == "next"
    fixture.memory_service.get_visible_agent.assert_awaited_once()
    fixture.repository.list.assert_awaited_once_with(
        workspace_id="workspace-1",
        agent_id="agent-1",
        user_id="user-1",
        scope=HistoricalMemorySettingsScope.TEAM,
        query="delivery",
        cursor=None,
        limit=20,
    )


async def test_list_propagates_private_agent_denial_without_querying_sources() -> None:
    """A private Agent remains non-enumerating at the settings boundary."""
    fixture = _service()
    fixture.memory_service.get_visible_agent.return_value = Failure(
        PrivateAgentAccessDenied(agent_id="agent-1")
    )

    result = await fixture.service.list(
        "agent-1",
        workspace_id="workspace-1",
        workspace_user_id="workspace-user-1",
        user_id="user-1",
        role=WorkspaceUserRole.MEMBER,
        scope=HistoricalMemorySettingsScope.TEAM,
        query=None,
        cursor=None,
        limit=20,
    )

    assert isinstance(result, Failure)
    assert isinstance(result.error, PrivateAgentAccessDenied)
    fixture.repository.list.assert_not_awaited()


async def test_list_normalizes_malformed_cursor() -> None:
    """Repository cursor errors become one safe service failure."""
    fixture = _service()
    fixture.memory_service.get_visible_agent.return_value = Success(object())
    fixture.repository.list.side_effect = HistoricalMemorySettingsCursorError("invalid")

    result = await fixture.service.list(
        "agent-1",
        workspace_id="workspace-1",
        workspace_user_id="workspace-user-1",
        user_id="user-1",
        role=WorkspaceUserRole.OWNER,
        scope=HistoricalMemorySettingsScope.USER,
        query=None,
        cursor="bad",
        limit=20,
    )

    assert isinstance(result, Failure)
    assert isinstance(result.error, HistoricalMemorySettingsCursorInvalid)


async def test_get_normalizes_invisible_source() -> None:
    """Every invisible source detail becomes the same settings not-found error."""
    fixture = _service()
    fixture.memory_service.get_visible_agent.return_value = Success(object())
    fixture.repository.get.return_value = None

    result = await fixture.service.get(
        "agent-1",
        _SOURCE_ID,
        workspace_id="workspace-1",
        workspace_user_id="workspace-user-1",
        user_id="user-1",
        role=WorkspaceUserRole.MEMBER,
    )

    assert isinstance(result, Failure)
    assert isinstance(result.error, HistoricalMemorySettingsNotFound)
