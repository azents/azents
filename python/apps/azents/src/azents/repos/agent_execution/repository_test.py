"""Event agent execution repository tests."""

import asyncio
import datetime

import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from azents.core.enums import (
    AgentRunPhase,
    AgentRunStatus,
    AgentSessionEndReason,
    EventKind,
    LLMProvider,
)
from azents.engine.events.types import ActiveToolCall, UserMessagePayload
from azents.rdb.models.agent import RDBAgent
from azents.rdb.models.agent_runtime import RDBAgentRuntime
from azents.rdb.models.agent_session import RDBAgentSession
from azents.rdb.models.event import RDBEvent
from azents.rdb.models.llm_provider_integration import RDBLLMProviderIntegration
from azents.repos.agent_execution import AgentRunRepository, EventTranscriptRepository
from azents.repos.agent_execution.data import AgentRunCreate, EventCreate
from azents.repos.agent_session import AgentSessionRepository
from azents.repos.agent_session.data import AgentSessionCreate
from azents.repos.workspace import WorkspaceRepository
from azents.repos.workspace.data import WorkspaceCreate
from azents.testing.model_selection import make_test_model_selection_dict


async def _create_workspace(session: AsyncSession, handle: str) -> str:
    """Create Workspace for tests."""
    await WorkspaceRepository().create(
        session,
        WorkspaceCreate(name="Event Runtime test", handle=handle),
    )
    workspace_id = await WorkspaceRepository().resolve_id(session, handle)
    assert workspace_id is not None
    return workspace_id


async def _create_agent_runtime(
    session: AsyncSession,
    handle: str = "event-runtime-ws",
) -> tuple[str, str, str]:
    """Create AgentRuntime for tests."""
    workspace_id = await _create_workspace(session, handle)
    integration = RDBLLMProviderIntegration(
        workspace_id=workspace_id,
        provider=LLMProvider.ANTHROPIC,
        name=f"{handle}-integration",
        encrypted_credentials="encrypted-test-value",
        config=None,
    )
    session.add(integration)
    await session.flush()

    agent = RDBAgent(
        workspace_id=workspace_id,
        name="Event Runtime test agent",
        model_selection=make_test_model_selection_dict(
            integration_id=integration.id,
            provider=LLMProvider.ANTHROPIC,
            model_identifier=f"{handle}-model-id",
        ),
        lightweight_model_selection=make_test_model_selection_dict(
            integration_id=integration.id,
            provider=LLMProvider.ANTHROPIC,
            model_identifier=f"{handle}-model-id",
        ),
    )
    session.add(agent)
    await session.flush()

    runtime = RDBAgentRuntime(workspace_id=workspace_id, agent_id=agent.id)
    session.add(runtime)
    await session.flush()
    return workspace_id, agent.id, runtime.id


def _agent_session_repository() -> AgentSessionRepository:
    """Create AgentSessionRepository for tests."""
    return AgentSessionRepository()


class TestEventExecutionRepositories:
    """Event execution repository tests."""

    async def test_append_read_and_move_head(
        self,
        rdb_session: AsyncSession,
    ) -> None:
        """Validate transcript append/read and model input head move."""
        workspace_id, agent_id, __runtime_id = await _create_agent_runtime(rdb_session)
        session_repo = _agent_session_repository()
        transcript_repo = EventTranscriptRepository()
        event_session = await session_repo.create(
            rdb_session,
            AgentSessionCreate(
                workspace_id=workspace_id,
                agent_id=agent_id,
            ),
        )

        first = await transcript_repo.append(
            rdb_session,
            EventCreate(
                session_id=event_session.id,
                kind=EventKind.USER_MESSAGE,
                payload=UserMessagePayload(content="first").model_dump(mode="json"),
                external_id="first-user-input",
            ),
        )
        second = await transcript_repo.append(
            rdb_session,
            EventCreate(
                session_id=event_session.id,
                kind=EventKind.USER_MESSAGE,
                payload=UserMessagePayload(content="second").model_dump(mode="json"),
            ),
        )

        events = await transcript_repo.list_for_model_input(
            rdb_session,
            event_session.id,
        )
        assert [event.id for event in events] == [first.id, second.id]
        assert [event.model_order for event in events] == [1000, 2000]

        updated = await transcript_repo.update_payload(
            rdb_session,
            first.id,
            UserMessagePayload(content="updated first"),
        )
        assert isinstance(updated.payload, UserMessagePayload)
        assert updated.payload.content == "updated first"

        moved = await session_repo.move_model_input_head(
            rdb_session,
            event_session.id,
            second.id,
        )
        assert moved.model_input_head_event_id == second.id

        from_head = await transcript_repo.list_for_model_input(
            rdb_session,
            event_session.id,
            head_event_id=second.id,
        )
        assert [event.id for event in from_head] == [second.id]

    async def test_append_with_external_id_returns_existing_event(
        self,
        rdb_session: AsyncSession,
    ) -> None:
        """Append with same External ID returns existing event."""
        workspace_id, agent_id, __runtime_id = await _create_agent_runtime(rdb_session)
        event_session = await _agent_session_repository().create(
            rdb_session,
            AgentSessionCreate(
                workspace_id=workspace_id,
                agent_id=agent_id,
            ),
        )
        transcript_repo = EventTranscriptRepository()
        create = EventCreate(
            session_id=event_session.id,
            kind=EventKind.USER_MESSAGE,
            payload=UserMessagePayload(content="first").model_dump(mode="json"),
            external_id="dedup-user-input",
        )

        first = await transcript_repo.append(rdb_session, create)
        second = await transcript_repo.append(
            rdb_session,
            create.model_copy(
                update={
                    "payload": UserMessagePayload(content="second").model_dump(
                        mode="json"
                    )
                }
            ),
        )

        assert second.id == first.id
        assert isinstance(second.payload, UserMessagePayload)
        assert second.payload.content == "first"
        result = await rdb_session.execute(
            sa.select(sa.func.count())
            .select_from(RDBEvent)
            .where(
                RDBEvent.session_id == event_session.id,
                RDBEvent.external_id == "dedup-user-input",
            )
        )
        assert result.scalar_one() == 1

    async def test_append_auto_model_order_waits_for_session_lock(
        self,
        rdb_engine: AsyncEngine,
        latest_db_schema: None,
    ) -> None:
        """Automatic model_order assignment runs after session row lock."""
        session_factory = async_sessionmaker(rdb_engine, expire_on_commit=False)
        async with session_factory() as setup_session:
            workspace_id, agent_id, __runtime_id = await _create_agent_runtime(
                setup_session,
                "event-runtime-lock-ws",
            )
            event_session = await _agent_session_repository().create(
                setup_session,
                AgentSessionCreate(
                    workspace_id=workspace_id,
                    agent_id=agent_id,
                ),
            )
            await setup_session.commit()

        transcript_repo = EventTranscriptRepository()
        async with (
            session_factory() as lock_session,
            session_factory() as append_session,
        ):
            lock_tx = await lock_session.begin()
            await lock_session.execute(
                sa.select(RDBAgentSession.id)
                .where(RDBAgentSession.id == event_session.id)
                .with_for_update()
            )

            append_task = asyncio.create_task(
                transcript_repo.append(
                    append_session,
                    EventCreate(
                        session_id=event_session.id,
                        kind=EventKind.USER_MESSAGE,
                        payload=UserMessagePayload(content="blocked").model_dump(
                            mode="json"
                        ),
                        external_id="blocked-user-input",
                    ),
                )
            )
            try:
                with pytest.raises(asyncio.TimeoutError):
                    await asyncio.wait_for(asyncio.shield(append_task), timeout=0.2)

                await lock_tx.commit()
                event = await asyncio.wait_for(append_task, timeout=2)
                await append_session.commit()

                assert event.model_order == 1000
            finally:
                if lock_tx.is_active:
                    await lock_tx.rollback()
                if not append_task.done():
                    append_task.cancel()
                    with pytest.raises(asyncio.CancelledError):
                        await append_task

    async def test_model_input_uses_logical_order(
        self,
        rdb_session: AsyncSession,
    ) -> None:
        """Model input is fetched by model_order, not physical id."""
        workspace_id, agent_id, __runtime_id = await _create_agent_runtime(rdb_session)
        event_session = await _agent_session_repository().create(
            rdb_session,
            AgentSessionCreate(
                workspace_id=workspace_id,
                agent_id=agent_id,
            ),
        )
        transcript_repo = EventTranscriptRepository()
        first = await transcript_repo.append(
            rdb_session,
            EventCreate(
                session_id=event_session.id,
                kind=EventKind.USER_MESSAGE,
                payload=UserMessagePayload(content="first").model_dump(mode="json"),
                model_order=2000,
            ),
        )
        second = await transcript_repo.append(
            rdb_session,
            EventCreate(
                session_id=event_session.id,
                kind=EventKind.USER_MESSAGE,
                payload=UserMessagePayload(content="second").model_dump(mode="json"),
                model_order=1000,
            ),
        )

        events = await transcript_repo.list_for_model_input(
            rdb_session,
            event_session.id,
        )
        assert [event.id for event in events] == [second.id, first.id]

        recent = await transcript_repo.list_recent_by_session_id(
            rdb_session,
            event_session.id,
            limit=10,
        )
        assert [event.id for event in recent] == [first.id, second.id]

        await transcript_repo.update_model_orders(
            rdb_session,
            event_session.id,
            {first.id: 500, second.id: 1500},
        )
        reordered = await transcript_repo.list_for_model_input(
            rdb_session,
            event_session.id,
        )
        assert [event.id for event in reordered] == [first.id, second.id]

    async def test_agent_run_phase_and_terminal_update(
        self,
        rdb_session: AsyncSession,
    ) -> None:
        """Validate Agent run phase and terminal state updates."""
        workspace_id, agent_id, __runtime_id = await _create_agent_runtime(rdb_session)
        event_session = await _agent_session_repository().create(
            rdb_session,
            AgentSessionCreate(
                workspace_id=workspace_id,
                agent_id=agent_id,
            ),
        )
        repo = AgentRunRepository()
        run = await repo.create(
            rdb_session,
            AgentRunCreate(session_id=event_session.id),
        )
        assert run.run_index == 1

        active_call = ActiveToolCall(
            call_id="call-1",
            name="read_text",
            arguments='{"path":"README.md"}',
            started_at=datetime.datetime.now(datetime.UTC),
            background=False,
        )
        executing = await repo.update_phase(
            rdb_session,
            run.id,
            AgentRunPhase.EXECUTING_TOOLS,
            active_tool_calls=[active_call],
        )
        assert executing.phase == AgentRunPhase.EXECUTING_TOOLS
        assert executing.active_tool_calls == [active_call]

        running = await repo.get_running_by_session_id(
            rdb_session,
            session_id=event_session.id,
        )
        assert running is not None
        assert running.id == run.id

        completed = await repo.mark_terminal(
            rdb_session,
            run.id,
            AgentRunStatus.COMPLETED,
            ended_at=datetime.datetime.now(datetime.UTC),
        )
        assert completed.status == AgentRunStatus.COMPLETED
        assert completed.phase == AgentRunPhase.IDLE
        assert completed.active_tool_calls == []
        assert (
            await repo.get_running_by_session_id(
                rdb_session,
                session_id=event_session.id,
            )
            is None
        )

    async def test_agent_run_create_closes_stale_running_runs(
        self,
        rdb_session: AsyncSession,
    ) -> None:
        """Creating a new run closes remaining running projection in same session."""
        workspace_id, agent_id, __runtime_id = await _create_agent_runtime(rdb_session)
        event_session = await _agent_session_repository().create(
            rdb_session,
            AgentSessionCreate(
                workspace_id=workspace_id,
                agent_id=agent_id,
            ),
        )
        repo = AgentRunRepository()
        stale = await repo.create(
            rdb_session,
            AgentRunCreate(
                session_id=event_session.id,
                phase=AgentRunPhase.WAITING_FOR_MODEL,
            ),
        )
        current = await repo.create(
            rdb_session,
            AgentRunCreate(session_id=event_session.id),
        )

        closed = await repo.get_by_id(rdb_session, stale.id)
        assert closed is not None
        assert closed.status == AgentRunStatus.CANCELLED
        assert closed.phase == AgentRunPhase.IDLE
        running = await repo.get_running_by_session_id(
            rdb_session,
            session_id=event_session.id,
        )
        assert running is not None
        assert running.id == current.id

    async def test_mark_terminal_if_running_does_not_overwrite_terminal_run(
        self,
        rdb_session: AsyncSession,
    ) -> None:
        """Worker fallback does not overwrite terminal run state."""
        workspace_id, agent_id, __runtime_id = await _create_agent_runtime(rdb_session)
        event_session = await _agent_session_repository().create(
            rdb_session,
            AgentSessionCreate(
                workspace_id=workspace_id,
                agent_id=agent_id,
            ),
        )
        repo = AgentRunRepository()
        run = await repo.create(
            rdb_session,
            AgentRunCreate(session_id=event_session.id),
        )
        await repo.mark_terminal(
            rdb_session,
            run.id,
            AgentRunStatus.INTERRUPTED,
            ended_at=datetime.datetime.now(datetime.UTC),
        )

        after_fallback = await repo.mark_terminal_if_running(
            rdb_session,
            run.id,
            AgentRunStatus.COMPLETED,
            ended_at=datetime.datetime.now(datetime.UTC),
        )

        assert after_fallback is not None
        assert after_fallback.status == AgentRunStatus.INTERRUPTED

    async def test_agent_run_index_increments_per_session(
        self,
        rdb_session: AsyncSession,
    ) -> None:
        """Agent run index increments within session scope."""
        workspace_id, agent_id, __runtime_id = await _create_agent_runtime(rdb_session)
        first_session = await _agent_session_repository().create(
            rdb_session,
            AgentSessionCreate(
                workspace_id=workspace_id,
                agent_id=agent_id,
            ),
        )
        second_session = await _agent_session_repository().create(
            rdb_session,
            AgentSessionCreate(
                workspace_id=workspace_id,
                agent_id=agent_id,
                primary_kind=None,
            ),
        )
        await _agent_session_repository().archive(
            rdb_session,
            second_session.id,
            ended_at=datetime.datetime.now(datetime.UTC),
            end_reason=AgentSessionEndReason.DELETED,
        )
        repo = AgentRunRepository()

        first = await repo.create(
            rdb_session, AgentRunCreate(session_id=first_session.id)
        )
        second = await repo.create(
            rdb_session,
            AgentRunCreate(session_id=first_session.id),
        )
        other = await repo.create(
            rdb_session,
            AgentRunCreate(session_id=second_session.id),
        )

        assert first.run_index == 1
        assert second.run_index == 2
        assert other.run_index == 1
