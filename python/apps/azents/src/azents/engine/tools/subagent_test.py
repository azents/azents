"""Subagent session selection/rotation logic tests."""

import datetime
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import AsyncMock, MagicMock

from azents.core.enums import AgentSessionEndReason, AgentSessionStartReason
from azents.engine.tools.subagent import (
    _resolve_subagent_session_id,  # pyright: ignore[reportPrivateUsage]
)


class _SessionManagerContext:
    """Async context manager for tests that returns single session."""

    def __init__(self, session: object) -> None:
        self._session = session

    async def __aenter__(self) -> object:
        return self._session

    async def __aexit__(self, exc_type: object, exc: object, tb: object) -> None:
        return None


def _make_ctx(*, existing: object | None) -> tuple[Any, object, AsyncMock, AsyncMock]:
    """Create context for session resolution helper tests."""
    session = MagicMock()
    session.commit = AsyncMock()
    runtime = SimpleNamespace(id="runtime-1")
    rotated = SimpleNamespace(id="session-new")

    agent_runtime_repository = MagicMock()
    agent_runtime_repository.ensure_for_agent = AsyncMock(return_value=runtime)

    agent_session_repository = MagicMock()
    agent_session_repository.get_by_id = AsyncMock(return_value=existing)
    agent_session_repository.rotate_active = AsyncMock(return_value=rotated)

    ctx = cast(
        Any,
        SimpleNamespace(
            session_manager=lambda: _SessionManagerContext(session),
            agent_runtime_repository=agent_runtime_repository,
            agent_session_repository=agent_session_repository,
        ),
    )
    return (
        ctx,
        session,
        agent_runtime_repository.ensure_for_agent,
        agent_session_repository.rotate_active,
    )


class TestResolveSubagentSessionId:
    """``_resolve_subagent_session_id`` tests."""

    async def test_reuses_existing_session_when_present(self) -> None:
        """Reuse existing session_id as-is when valid."""
        ctx, _session, ensure_for_agent, rotate_active = _make_ctx(existing=object())

        result = await _resolve_subagent_session_id(
            ctx=ctx,
            subagent_id="subagent-1",
            existing_session_id="session-existing",
        )

        assert result == "session-existing"
        ensure_for_agent.assert_not_awaited()
        rotate_active.assert_not_awaited()

    async def test_rotates_to_new_active_session_when_session_missing(self) -> None:
        """Replace stale session_id with new active session rotation."""
        ctx, session, ensure_for_agent, rotate_active = _make_ctx(existing=None)
        now = datetime.datetime(2026, 5, 10, tzinfo=datetime.timezone.utc)

        result = await _resolve_subagent_session_id(
            ctx=ctx,
            subagent_id="subagent-1",
            existing_session_id="session-missing",
            now=now,
        )

        assert result == "session-new"
        ensure_for_agent.assert_awaited_once_with(session, "subagent-1")
        rotate_active.assert_awaited_once_with(
            session,
            "runtime-1",
            start_reason=AgentSessionStartReason.MANUAL_NEW,
            end_reason=AgentSessionEndReason.MANUAL_NEW,
            now=now,
        )

    async def test_rotates_when_creating_fresh_subagent_session(self) -> None:
        """Without session_id, archive active session and open new one."""
        ctx, session, ensure_for_agent, rotate_active = _make_ctx(existing=None)
        now = datetime.datetime(2026, 5, 10, 1, tzinfo=datetime.timezone.utc)

        result = await _resolve_subagent_session_id(
            ctx=ctx,
            subagent_id="subagent-1",
            existing_session_id=None,
            now=now,
        )

        assert result == "session-new"
        ensure_for_agent.assert_awaited_once_with(session, "subagent-1")
        rotate_active.assert_awaited_once_with(
            session,
            "runtime-1",
            start_reason=AgentSessionStartReason.MANUAL_NEW,
            end_reason=AgentSessionEndReason.MANUAL_NEW,
            now=now,
        )
