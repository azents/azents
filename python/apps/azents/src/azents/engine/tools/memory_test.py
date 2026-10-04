"""Saved Memory mutation tool tests."""

import datetime
import json
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import NamedTuple

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from azents.core.memory_scope import MemoryScope
from azents.engine.run.types import FunctionToolError
from azents.engine.tools.memory import make_delete_memory_tool, make_save_memory_tool
from azents.rdb.session_capabilities import ReadSession, ReadWriteSession, WriteSession
from azents.repos.agent_session import AgentSessionRepository
from azents.repos.memory import MemoryRepository
from azents.repos.memory.data import Memory, MemoryCreate
from azents.repos.memory.operations import MemoryOperationRepository


@asynccontextmanager
async def _session_manager() -> AsyncIterator[WriteSession]:
    async with AsyncSession() as raw_session:
        session = ReadWriteSession(raw_session)
        yield session


class _SaveCall(NamedTuple):
    agent_id: str
    user_id: str | None
    create: MemoryCreate


class _DeleteCall(NamedTuple):
    agent_id: str
    user_id: str | None
    name: str


class _MemoryRepository(MemoryRepository):
    """Typed in-memory collaborator recording the exact mutation scope."""

    def __init__(self, *, deleted: bool) -> None:
        self.deleted = deleted
        self.save_calls: list[_SaveCall] = []
        self.delete_calls: list[_DeleteCall] = []

    async def upsert(
        self,
        session: ReadSession,
        *,
        agent_id: str,
        user_id: str | None,
        create: MemoryCreate,
    ) -> Memory:
        del session
        self.save_calls.append(_SaveCall(agent_id, user_id, create))
        now = datetime.datetime(2026, 1, 1, tzinfo=datetime.UTC)
        return Memory(
            id="memory-1",
            agent_id=agent_id,
            user_id=user_id,
            scope=create.scope,
            type=create.type,
            name=create.name,
            description=create.description,
            content=create.content,
            created_at=now,
            updated_at=now,
        )

    async def delete_by_name(
        self,
        session: ReadSession,
        *,
        agent_id: str,
        user_id: str | None,
        name: str,
    ) -> bool:
        del session
        self.delete_calls.append(_DeleteCall(agent_id, user_id, name))
        return self.deleted


def _operations(repository: MemoryRepository) -> MemoryOperationRepository:
    return MemoryOperationRepository(
        session_manager=_session_manager,
        memory_repository=repository,
        agent_session_repository=AgentSessionRepository(),
    )


async def test_save_memory_retains_agent_scope_upsert() -> None:
    """The cutover preserves shared Agent Saved Memory upsert semantics."""
    repository = _MemoryRepository(deleted=False)
    tool = make_save_memory_tool(_operations(repository), "agent-1")

    output = await tool.handler(
        json.dumps(
            {
                "scope": "agent",
                "type": "feedback",
                "name": "concise",
                "description": "Prefer concise updates",
                "content": "Lead with the result.",
            }
        )
    )

    assert isinstance(output, str)
    assert json.loads(output) == {
        "status": "saved",
        "name": "concise",
        "scope": "agent",
        "type": "feedback",
    }
    assert repository.save_calls == [
        _SaveCall(
            agent_id="agent-1",
            user_id=None,
            create=MemoryCreate(
                scope=MemoryScope.AGENT,
                type="feedback",
                name="concise",
                description="Prefer concise updates",
                content="Lead with the result.",
            ),
        )
    ]


async def test_save_memory_rejects_user_scope_in_team_session() -> None:
    """Team execution cannot widen Saved Memory mutation to User scope."""
    repository = _MemoryRepository(deleted=False)
    tool = make_save_memory_tool(_operations(repository), "agent-1")

    with pytest.raises(FunctionToolError, match="User-scope memories are unavailable"):
        await tool.handler(
            json.dumps(
                {
                    "scope": "user",
                    "type": "user",
                    "name": "private",
                    "description": "Private",
                    "content": "Private body",
                }
            )
        )

    assert repository.save_calls == []


async def test_delete_memory_retains_associated_user_scope() -> None:
    """User Sessions keep exact associated-User Saved Memory deletion."""
    repository = _MemoryRepository(deleted=True)
    tool = make_delete_memory_tool(
        _operations(repository),
        "agent-1",
        associated_user_id="user-1",
    )

    output = await tool.handler(json.dumps({"scope": "user", "name": "private"}))

    assert isinstance(output, str)
    assert json.loads(output) == {
        "status": "deleted",
        "name": "private",
        "scope": "user",
    }
    assert repository.delete_calls == [
        _DeleteCall(agent_id="agent-1", user_id="user-1", name="private")
    ]


async def test_delete_memory_missing_entry_is_not_reported_as_success() -> None:
    """A missing Saved Memory remains an explicit domain-tool error."""
    repository = _MemoryRepository(deleted=False)
    tool = make_delete_memory_tool(_operations(repository), "agent-1")

    with pytest.raises(FunctionToolError, match="not found in agent scope"):
        await tool.handler(json.dumps({"scope": "agent", "name": "missing"}))
    assert repository.delete_calls == [
        _DeleteCall(agent_id="agent-1", user_id=None, name="missing")
    ]
