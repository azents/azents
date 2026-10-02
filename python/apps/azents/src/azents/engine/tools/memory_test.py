"""Saved Memory mutation tool tests."""

import json
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import cast
from unittest.mock import AsyncMock

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from azents.engine.run.types import FunctionToolError
from azents.engine.tools.memory import make_delete_memory_tool, make_save_memory_tool
from azents.rdb.session import SessionManager
from azents.repos.memory import MemoryRepository
from azents.repos.memory.data import MemoryCreate, MemoryScope


@asynccontextmanager
async def _session_manager() -> AsyncIterator[AsyncSession]:
    yield cast(AsyncSession, AsyncMock())


def _repo() -> AsyncMock:
    return AsyncMock(spec=MemoryRepository)


async def test_save_memory_retains_agent_scope_upsert() -> None:
    """The cutover preserves shared Agent Saved Memory upsert semantics."""
    repository = _repo()
    tool = make_save_memory_tool(
        cast(MemoryRepository, repository),
        "agent-1",
        cast(SessionManager[AsyncSession], _session_manager),
    )

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

    assert json.loads(cast(str, output)) == {
        "status": "saved",
        "name": "concise",
        "scope": "agent",
        "type": "feedback",
    }
    repository.upsert.assert_awaited_once()
    call = repository.upsert.await_args
    assert call.kwargs["agent_id"] == "agent-1"
    assert call.kwargs["user_id"] is None
    assert call.kwargs["create"] == MemoryCreate(
        scope=MemoryScope.AGENT,
        type="feedback",
        name="concise",
        description="Prefer concise updates",
        content="Lead with the result.",
    )


async def test_save_memory_rejects_user_scope_in_team_session() -> None:
    """Team execution cannot widen Saved Memory mutation to User scope."""
    repository = _repo()
    tool = make_save_memory_tool(
        cast(MemoryRepository, repository),
        "agent-1",
        cast(SessionManager[AsyncSession], _session_manager),
    )

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

    repository.upsert.assert_not_awaited()


async def test_delete_memory_retains_associated_user_scope() -> None:
    """User Sessions keep exact associated-User Saved Memory deletion."""
    repository = _repo()
    repository.delete_by_name.return_value = True
    tool = make_delete_memory_tool(
        cast(MemoryRepository, repository),
        "agent-1",
        cast(SessionManager[AsyncSession], _session_manager),
        associated_user_id="user-1",
    )

    output = await tool.handler(json.dumps({"scope": "user", "name": "private"}))

    assert json.loads(cast(str, output)) == {
        "status": "deleted",
        "name": "private",
        "scope": "user",
    }
    repository.delete_by_name.assert_awaited_once()
    call = repository.delete_by_name.await_args
    assert call.kwargs == {
        "agent_id": "agent-1",
        "user_id": "user-1",
        "name": "private",
    }


async def test_delete_memory_missing_entry_is_not_reported_as_success() -> None:
    """A missing Saved Memory remains an explicit domain-tool error."""
    repository = _repo()
    repository.delete_by_name.return_value = False
    tool = make_delete_memory_tool(
        cast(MemoryRepository, repository),
        "agent-1",
        cast(SessionManager[AsyncSession], _session_manager),
    )

    with pytest.raises(FunctionToolError, match="not found in agent scope"):
        await tool.handler(json.dumps({"scope": "agent", "name": "missing"}))
