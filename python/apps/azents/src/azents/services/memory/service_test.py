"""MemoryService tests."""

import datetime
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from typing import Any, cast
from unittest.mock import AsyncMock

from azcommon.result import Failure, Success
from sqlalchemy.ext.asyncio import AsyncSession

from azents.core.enums import AgentLifecycleStatus, AgentType, WorkspaceUserRole
from azents.repos.agent.data import Agent
from azents.repos.memory.data import Memory, MemoryScope
from azents.testing.model_selection import (
    make_test_model_selection,
    make_test_selectable_model_options,
)

from . import MemoryService
from .data import DuplicateMemory, MemoryCreateInput, MemoryUpdateInput

_NOW = datetime.datetime.now(datetime.timezone.utc)


def _make_agent(agent_id: str = "agent-1") -> Agent:
    """Create Agent for tests."""
    selection = make_test_model_selection()
    return Agent(
        id=agent_id,
        workspace_id="ws-1",
        name="Test agent",
        description=None,
        model_selection=selection,
        lightweight_model_selection=selection,
        selectable_model_options=make_test_selectable_model_options(selection),
        main_model_label="default",
        lightweight_model_label="default",
        model_parameters=None,
        system_prompt=None,
        enabled=True,
        lifecycle_status=AgentLifecycleStatus.ACTIVE,
        type=AgentType.PUBLIC,
        runtime_provider_id=None,
        shell_enabled=True,
        memory_enabled=True,
        tool_search_enabled=False,
        max_turns=None,
        avatar=None,
        created_at=_NOW,
        updated_at=_NOW,
    )


def _make_memory(
    *,
    memory_id: str = "mem-1",
    agent_id: str = "agent-1",
    user_id: str | None = None,
    scope: MemoryScope = MemoryScope.AGENT,
    name: str = "memory-1",
) -> Memory:
    """Create Memory for tests."""
    return Memory(
        id=memory_id,
        agent_id=agent_id,
        user_id=user_id,
        scope=scope,
        type="project",
        name=name,
        description="Memory description",
        content="Memory content",
        created_at=_NOW,
        updated_at=_NOW,
    )


def _make_service() -> MemoryService:
    """Create MemoryService with mock dependencies."""
    repository = AsyncMock()
    agent_repository = AsyncMock()
    admin_repository = AsyncMock()

    @asynccontextmanager
    async def session_manager() -> AsyncGenerator[AsyncSession, None]:
        yield AsyncMock(spec=AsyncSession)

    return MemoryService(
        repository=repository,
        agent_repository=agent_repository,
        admin_repository=admin_repository,
        session_manager=session_manager,
    )


class TestMemoryService:
    """MemoryService behavior tests."""

    async def test_create_rejects_duplicate_name_in_scope(self) -> None:
        """Human create uses strict conflict semantics instead of upsert."""
        service = _make_service()
        agent_repo = cast(Any, service.agent_repository)
        memory_repo = cast(Any, service.repository)
        agent_repo.get_by_id.return_value = _make_agent()
        memory_repo.get_by_name.return_value = _make_memory(name="dupe")

        result = await service.create(
            "agent-1",
            MemoryCreateInput(
                scope=MemoryScope.USER,
                type="project",
                name="dupe",
                description="Duplicate",
                content="Duplicate content",
            ),
            workspace_id="ws-1",
            workspace_user_id="wu-1",
            user_id="user-1",
            role=WorkspaceUserRole.MEMBER,
        )

        assert isinstance(result, Failure)
        assert isinstance(result.error, DuplicateMemory)
        memory_repo.create.assert_not_awaited()

    async def test_member_cannot_update_agent_scope_memory(self) -> None:
        """Agent-scope writes require Agent admin or workspace owner."""
        service = _make_service()
        agent_repo = cast(Any, service.agent_repository)
        memory_repo = cast(Any, service.repository)
        admin_repo = cast(Any, service.admin_repository)
        agent_repo.get_by_id.return_value = _make_agent()
        memory_repo.get_by_id.return_value = _make_memory(scope=MemoryScope.AGENT)
        admin_repo.is_admin.return_value = False

        result = await service.update_by_id(
            "agent-1",
            "mem-1",
            MemoryUpdateInput(description="Updated description"),
            workspace_id="ws-1",
            workspace_user_id="wu-1",
            user_id="user-1",
            role=WorkspaceUserRole.MEMBER,
        )

        assert isinstance(result, Failure)
        memory_repo.update_by_id.assert_not_awaited()

    async def test_member_updates_own_user_scope_memory(self) -> None:
        """User-scope writes are allowed for the current authenticated user."""
        service = _make_service()
        agent_repo = cast(Any, service.agent_repository)
        memory_repo = cast(Any, service.repository)
        existing = _make_memory(
            scope=MemoryScope.USER,
            user_id="user-1",
            name="own-memory",
        )
        updated = existing.model_copy(update={"description": "Updated"})
        agent_repo.get_by_id.return_value = _make_agent()
        memory_repo.get_by_id.return_value = existing
        memory_repo.update_by_id.return_value = updated

        result = await service.update_by_id(
            "agent-1",
            "mem-1",
            MemoryUpdateInput(description="Updated"),
            workspace_id="ws-1",
            workspace_user_id="wu-1",
            user_id="user-1",
            role=WorkspaceUserRole.MEMBER,
        )

        assert isinstance(result, Success)
        assert result.value.description == "Updated"
        memory_repo.update_by_id.assert_awaited_once()

    async def test_list_user_scope_uses_current_user_id(self) -> None:
        """User-scope list never exposes another user's Memory rows."""
        service = _make_service()
        agent_repo = cast(Any, service.agent_repository)
        memory_repo = cast(Any, service.repository)
        agent_repo.get_by_id.return_value = _make_agent()
        memory_repo.list.return_value = []

        result = await service.list_by_agent(
            "agent-1",
            workspace_id="ws-1",
            workspace_user_id="wu-1",
            user_id="user-1",
            role=WorkspaceUserRole.MEMBER,
            scope=MemoryScope.USER,
            type=None,
            query=None,
        )

        assert isinstance(result, Success)
        memory_repo.list.assert_awaited_once()
        _, kwargs = memory_repo.list.await_args
        assert kwargs["user_id"] == "user-1"
