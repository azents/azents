"""Subagent session selection logic tests."""

import datetime
from contextlib import AbstractAsyncContextManager
from unittest.mock import AsyncMock, MagicMock

from sqlalchemy.ext.asyncio import AsyncSession

from azents.core.enums import AgentSessionStartReason, AgentSessionStatus
from azents.core.tools import SessionType
from azents.engine.tools.subagent import (
    SubagentToolContext,
    _resolve_subagent_session_id,  # pyright: ignore[reportPrivateUsage]  # Unit-test private session resolver behavior.
)
from azents.repos.agent_runtime import AgentRuntimeRepository
from azents.repos.agent_runtime.data import AgentRuntime
from azents.repos.agent_session import AgentSessionRepository
from azents.repos.agent_session.data import AgentSession


class _Session(AsyncSession):
    """Minimal async session fake for resolver tests."""

    def __init__(self) -> None:
        self.commit = AsyncMock()


class _SessionManagerContext(AbstractAsyncContextManager[AsyncSession, bool | None]):
    """Async context manager for tests that returns single session."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def __aenter__(self) -> AsyncSession:
        return self._session

    async def __aexit__(self, exc_type: object, exc: object, tb: object) -> None:
        return None


class _SessionManager:
    """Session manager fake for resolver tests."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    def __call__(self) -> AbstractAsyncContextManager[AsyncSession, bool | None]:
        return _SessionManagerContext(self._session)


class _AgentRuntimeRepository(AgentRuntimeRepository):
    """AgentRuntimeRepository fake for resolver tests."""

    def __init__(self) -> None:
        now = datetime.datetime.now(datetime.UTC)
        self.ensure_for_agent_mock = AsyncMock(
            return_value=AgentRuntime(
                id="runtime-1",
                workspace_id="workspace-1",
                agent_id="subagent-1",
                created_at=now,
                updated_at=now,
            )
        )

    async def ensure_for_agent(
        self,
        session: AsyncSession,
        agent_id: str,
        *,
        default_runtime_provider_id: str | None = None,
    ) -> AgentRuntime:
        del default_runtime_provider_id
        return await self.ensure_for_agent_mock(session, agent_id)


class _AgentSessionRepository(AgentSessionRepository):
    """AgentSessionRepository fake for resolver tests."""

    def __init__(self, existing: AgentSession | None) -> None:
        self.get_by_id_mock = AsyncMock(return_value=existing)
        now = datetime.datetime.now(datetime.UTC)
        self.ensure_team_primary_for_agent_mock = AsyncMock(
            return_value=AgentSession(
                id="session-primary",
                workspace_id="workspace-1",
                agent_id="subagent-1",
                status=AgentSessionStatus.ACTIVE,
                start_reason=AgentSessionStartReason.INITIAL,
                title=None,
                title_source=None,
                title_generated_at=None,
                title_generation_event_id=None,
                last_user_input_at=now,
                started_at=now,
                created_at=now,
                updated_at=now,
            )
        )

    async def get_by_id(
        self,
        session: AsyncSession,
        agent_session_id: str,
    ) -> AgentSession | None:
        return await self.get_by_id_mock(session, agent_session_id)

    async def ensure_team_primary_for_agent(
        self,
        session: AsyncSession,
        *,
        workspace_id: str,
        agent_id: str,
    ) -> AgentSession:
        return await self.ensure_team_primary_for_agent_mock(
            session,
            workspace_id=workspace_id,
            agent_id=agent_id,
        )


def _existing_session() -> AgentSession:
    """Create existing session record for tests."""
    now = datetime.datetime.now(datetime.UTC)
    return AgentSession(
        id="session-existing",
        workspace_id="workspace-1",
        agent_id="subagent-1",
        status=AgentSessionStatus.ACTIVE,
        start_reason=AgentSessionStartReason.INITIAL,
        title=None,
        title_source=None,
        title_generated_at=None,
        title_generation_event_id=None,
        last_user_input_at=now,
        started_at=now,
        created_at=now,
        updated_at=now,
    )


def _make_ctx(
    *, existing: AgentSession | None
) -> tuple[
    SubagentToolContext,
    AsyncSession,
    _AgentRuntimeRepository,
    _AgentSessionRepository,
]:
    """Create context for session resolution helper tests."""
    session = _Session()
    runtime_repository = _AgentRuntimeRepository()
    session_repository = _AgentSessionRepository(existing)

    ctx = SubagentToolContext(
        engine=MagicMock(),
        parent_session_id="parent-session",
        parent_agent_id="parent-agent",
        parent_runtime_domain_config=MagicMock(),
        workspace_id="workspace-1",
        user_id="user-1",
        agent_repository=MagicMock(),
        integration_repository=MagicMock(),
        exchange_file_service=MagicMock(),
        model_file_service=MagicMock(),
        session_manager=_SessionManager(session),
        toolkit_registry={},
        agent_toolkit_repository=MagicMock(),
        toolkit_repository=MagicMock(),
        agent_runtime_repository=runtime_repository,
        agent_session_repository=session_repository,
        publish_event=AsyncMock(),
        broker=MagicMock(),
        builtin_toolkit_provider=None,
        todo_toolkit_provider=None,
        goal_toolkit_provider=None,
        skill_toolkit_provider=None,
        web_url="https://example.test",
        oauth_secret_key="secret",
        mcp_proxy_url=None,
        session_type=SessionType.USER,
    )
    return ctx, session, runtime_repository, session_repository


class TestResolveSubagentSessionId:
    """``_resolve_subagent_session_id`` tests."""

    async def test_reuses_existing_session_when_present(self) -> None:
        """Reuse existing session_id as-is when valid."""
        ctx, _session, runtime_repo, session_repo = _make_ctx(
            existing=_existing_session()
        )

        result = await _resolve_subagent_session_id(
            ctx=ctx,
            subagent_id="subagent-1",
            existing_session_id="session-existing",
        )

        assert result == "session-existing"
        runtime_repo.ensure_for_agent_mock.assert_not_awaited()
        session_repo.ensure_team_primary_for_agent_mock.assert_not_awaited()

    async def test_uses_team_primary_when_session_missing(self) -> None:
        """Replace stale session_id with target subagent team primary session."""
        ctx, session, runtime_repo, session_repo = _make_ctx(existing=None)

        result = await _resolve_subagent_session_id(
            ctx=ctx,
            subagent_id="subagent-1",
            existing_session_id="session-missing",
        )

        assert result == "session-primary"
        runtime_repo.ensure_for_agent_mock.assert_awaited_once_with(
            session, "subagent-1"
        )
        session_repo.ensure_team_primary_for_agent_mock.assert_awaited_once_with(
            session,
            workspace_id="workspace-1",
            agent_id="subagent-1",
        )

    async def test_uses_team_primary_when_creating_fresh_subagent_session(self) -> None:
        """Without session_id, use target subagent team primary session."""
        ctx, session, runtime_repo, session_repo = _make_ctx(existing=None)

        result = await _resolve_subagent_session_id(
            ctx=ctx,
            subagent_id="subagent-1",
            existing_session_id=None,
        )

        assert result == "session-primary"
        runtime_repo.ensure_for_agent_mock.assert_awaited_once_with(
            session, "subagent-1"
        )
        session_repo.ensure_team_primary_for_agent_mock.assert_awaited_once_with(
            session,
            workspace_id="workspace-1",
            agent_id="subagent-1",
        )
