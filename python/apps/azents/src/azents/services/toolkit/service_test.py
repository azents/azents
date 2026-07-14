"""ToolkitService transaction-boundary tests."""

import datetime
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from typing import Any, cast

import pytest
from azcommon.result import Success
from sqlalchemy.ext.asyncio import AsyncSession

from azents.core.tools import McpToolkitConfig
from azents.rdb.session import SessionManager
from azents.repos.toolkit.data import ToolkitConfig, ToolkitCreate, ToolkitUpdate

from . import ToolkitService
from .data import ToolkitCreateInput


class _TrackingSessionManager:
    """Track concurrent service-owned DB sessions."""

    def __init__(self) -> None:
        self.active_sessions = 0
        self.max_active_sessions = 0

    @asynccontextmanager
    async def __call__(self) -> AsyncGenerator[AsyncSession, None]:
        """Yield a fake DB session while tracking its lifetime."""
        self.active_sessions += 1
        self.max_active_sessions = max(
            self.max_active_sessions,
            self.active_sessions,
        )
        try:
            yield cast(AsyncSession, object())
        finally:
            self.active_sessions -= 1


class _McpProvider:
    """Minimal OAuth-capable Toolkit provider."""

    def __init__(self, tracker: _TrackingSessionManager) -> None:
        self.tracker = tracker

    @classmethod
    def validate_config(cls, config: dict[str, object]) -> McpToolkitConfig:
        """Validate test MCP config."""
        return McpToolkitConfig.model_validate(config)

    def to_mcp_config(self, config: McpToolkitConfig) -> McpToolkitConfig:
        """Return the validated MCP config."""
        return config

    async def validate_credentials(
        self,
        session: AsyncSession,
        user_id: str,
        credentials: dict[str, object] | None,
    ) -> str | None:
        """Accept credentials within one short DB session."""
        del session, user_id, credentials
        assert self.tracker.active_sessions == 1
        return None


class _FakeToolkitRepository:
    """In-memory Toolkit repository."""

    def __init__(self, events: list[str]) -> None:
        self.events = events
        self.toolkit: ToolkitConfig | None = None
        self.update_calls = 0

    async def create(
        self,
        session: AsyncSession,
        create: ToolkitCreate,
    ) -> Success[ToolkitConfig]:
        """Create one Toolkit projection."""
        del session
        now = datetime.datetime.now(datetime.UTC)
        self.toolkit = ToolkitConfig(
            id="toolkit-1",
            workspace_id=create.workspace_id,
            toolkit_type=create.toolkit_type,
            slug=create.slug,
            name=create.name,
            description=create.description,
            config=create.config,
            prompt=create.prompt,
            credentials=create.credentials,
            enabled=create.enabled,
            created_at=now,
            updated_at=now,
        )
        return Success(self.toolkit)

    async def get_by_id(
        self,
        session: AsyncSession,
        toolkit_id: str,
    ) -> ToolkitConfig | None:
        """Fetch the current Toolkit."""
        del session
        if self.toolkit is None or self.toolkit.id != toolkit_id:
            return None
        return self.toolkit

    async def update_by_id(
        self,
        session: AsyncSession,
        toolkit_id: str,
        update: ToolkitUpdate,
    ) -> Success[ToolkitConfig]:
        """Apply an update to the current Toolkit."""
        del session
        assert self.toolkit is not None
        assert self.toolkit.id == toolkit_id
        self.events.append("update")
        self.update_calls += 1
        self.toolkit = self.toolkit.model_copy(update=dict(update))
        return Success(self.toolkit)


class _FakeScopeRepository:
    """Record automatic workspace scope creation."""

    def __init__(self) -> None:
        self.create_calls = 0

    async def create(self, session: AsyncSession, create: object) -> None:
        """Record one scope creation."""
        del session, create
        self.create_calls += 1


class _FakeOAuthConnectionRepository:
    """Track OAuth summary reads and injectable failures."""

    def __init__(
        self,
        tracker: _TrackingSessionManager,
        events: list[str],
    ) -> None:
        self.tracker = tracker
        self.events = events
        self.calls = 0
        self.fail = False

    async def get_summary_by_toolkit_id(
        self,
        session: AsyncSession,
        toolkit_id: str,
    ) -> None:
        """Read a disconnected OAuth summary in its own short session."""
        del session, toolkit_id
        assert self.tracker.active_sessions == 1
        self.events.append("oauth")
        self.calls += 1
        if self.fail:
            msg = "oauth summary failed"
            raise RuntimeError(msg)
        return None


def _make_service() -> tuple[
    ToolkitService,
    _TrackingSessionManager,
    _FakeToolkitRepository,
    _FakeScopeRepository,
    _FakeOAuthConnectionRepository,
]:
    """Create ToolkitService with transaction-aware fakes."""
    events: list[str] = []
    tracker = _TrackingSessionManager()
    toolkit_repository = _FakeToolkitRepository(events)
    scope_repository = _FakeScopeRepository()
    oauth_repository = _FakeOAuthConnectionRepository(tracker, events)
    provider = _McpProvider(tracker)
    service = ToolkitService(
        toolkit_repo=cast(Any, toolkit_repository),
        mcp_oauth_connection_repo=cast(Any, oauth_repository),
        scope_repo=cast(Any, scope_repository),
        agent_toolkit_repo=cast(Any, object()),
        agent_repo=cast(Any, object()),
        session_manager=cast(SessionManager[AsyncSession], tracker),
        toolkit_registry=cast(Any, {"mcp": provider}),
    )
    return (
        service,
        tracker,
        toolkit_repository,
        scope_repository,
        oauth_repository,
    )


def _create_input() -> ToolkitCreateInput:
    """Return a valid OAuth MCP Toolkit input."""
    return ToolkitCreateInput(
        workspace_id="workspace-1",
        toolkit_type="mcp",
        slug="test_mcp",
        name="Test MCP",
        config={
            "server_url": "https://example.com/mcp",
            "auth_type": "oauth2",
        },
        credentials=None,
    )


async def test_create_returns_disconnected_projection_without_nested_oauth_read() -> (
    None
):
    """Fresh create commits atomically without an impossible OAuth summary read."""
    service, tracker, repository, scope_repository, oauth_repository = _make_service()
    oauth_repository.fail = True

    result = await service.create(_create_input(), user_id="user-1")

    assert isinstance(result, Success)
    assert result.value.oauth_connection is None
    assert repository.toolkit is not None
    assert scope_repository.create_calls == 1
    assert oauth_repository.calls == 0
    assert tracker.active_sessions == 0
    assert tracker.max_active_sessions == 1


async def test_update_snapshots_oauth_before_write_without_nested_sessions() -> None:
    """Update reads OAuth state before its write transaction and reuses the snapshot."""
    service, tracker, repository, _scope_repository, oauth_repository = _make_service()
    created = await service.create(_create_input(), user_id="user-1")
    assert isinstance(created, Success)

    result = await service.update_by_id(
        "toolkit-1",
        {"name": "Updated MCP"},
        workspace_id="workspace-1",
        user_id="user-1",
    )

    assert isinstance(result, Success)
    assert result.value.name == "Updated MCP"
    assert oauth_repository.events == ["oauth", "update"]
    assert oauth_repository.calls == 1
    assert repository.update_calls == 1
    assert tracker.active_sessions == 0
    assert tracker.max_active_sessions == 1


async def test_update_does_not_write_when_oauth_snapshot_fails() -> None:
    """OAuth projection failure happens before, never after, the durable update."""
    service, tracker, repository, _scope_repository, oauth_repository = _make_service()
    created = await service.create(_create_input(), user_id="user-1")
    assert isinstance(created, Success)
    oauth_repository.fail = True

    with pytest.raises(RuntimeError, match="oauth summary failed"):
        await service.update_by_id(
            "toolkit-1",
            {"name": "Must Not Persist"},
            workspace_id="workspace-1",
            user_id="user-1",
        )

    assert repository.toolkit is not None
    assert repository.toolkit.name == "Test MCP"
    assert repository.update_calls == 0
    assert tracker.active_sessions == 0
    assert tracker.max_active_sessions == 1
