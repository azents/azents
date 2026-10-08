"""Real PostgreSQL read completion and adjacent facade effect ordering."""

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock

import pytest
import sqlalchemy as sa

from azents.core.enums import AgentSessionRunState, EventKind, LLMProvider
from azents.engine.events.types import UserMessagePayload
from azents.rdb.models.agent_session import RDBAgentSession
from azents.rdb.models.event import RDBEvent
from azents.rdb.session import SessionManager
from azents.rdb.session_capabilities import ReadSession, WriteSession
from azents.repos.action_execution import ActionExecutionRepository
from azents.repos.agent import AgentRepository
from azents.repos.agent.data import Agent
from azents.repos.agent_execution import AgentRunRepository, EventTranscriptRepository
from azents.repos.agent_execution.data import EventCreate
from azents.repos.agent_session import AgentSessionRepository
from azents.repos.agent_wait_read import AgentWaitReadRepository
from azents.repos.live_projection_authority_test import _create_session
from azents.repos.model_metadata_read import ModelMetadataReadRepository
from azents.repos.model_metadata_source import ModelMetadataSourceRepository
from azents.repos.model_metadata_source_data import ContextModelRequest
from azents.repos.worker_executor_read import WorkerExecutorReadRepository
from azents.services.agent_wait import AgentWaitService
from azents.services.mailbox import MailboxService
from azents.services.model_metadata import ModelMetadataService
from azents.testing.types import require_instance


class _Boundary:
    """Track each real Session until its completed operation has exited."""

    def __init__(self, manager: SessionManager[WriteSession]) -> None:
        self.manager = manager
        self.opened: list[WriteSession] = []
        self.active: list[WriteSession] = []

    @asynccontextmanager
    async def session_manager(self) -> AsyncIterator[WriteSession]:
        async with self.manager() as session:
            self.opened.append(session)
            self.active.append(session)
            try:
                yield session
            finally:
                self.active.remove(session)

    def closed(self) -> None:
        assert not self.active
        assert all(
            not session.write_session.in_transaction() for session in self.opened
        )


def _reads(
    boundary: _Boundary, *, agents: AgentRepository
) -> WorkerExecutorReadRepository:
    return WorkerExecutorReadRepository(
        session_manager=boundary.session_manager,
        agent_repository=agents,
        agent_session_repository=AgentSessionRepository(),
        event_transcript_repository=EventTranscriptRepository(),
        action_execution_repository=ActionExecutionRepository(),
    )


async def test_missing_read_results_remain_detached_without_stronger_policy(
    rdb_session_manager: SessionManager[WriteSession],
) -> None:
    boundary = _Boundary(rdb_session_manager)
    reads = _reads(boundary, agents=AgentRepository())
    missing = "0" * 32
    assert await reads.get_agent(missing) is None
    boundary.closed()
    assert await reads.get_session(missing) is None
    boundary.closed()
    assert await reads.get_session_agent(missing) is None
    snapshot = await reads.model_configuration_snapshot(
        agent_id=missing, session_id=missing
    )
    assert snapshot.agent is None and snapshot.session is None
    assert await reads.list_tree_session_ids(root_session_agent_id=missing) == ()
    assert await reads.tree_change_routes([missing, missing]) == ()
    assert await reads.action_execution_projections(missing) == []
    transcript = await reads.model_input_transcript(missing)
    assert transcript.head_event_id is None and transcript.events == ()
    boundary.closed()
    count = len(boundary.opened)
    assert await reads.tree_change_routes([]) == ()
    assert len(boundary.opened) == count


async def test_agent_session_tree_and_drift_snapshots_preserve_order_and_identity(
    rdb_session_manager: SessionManager[WriteSession],
) -> None:
    session_id = await _create_session(rdb_session_manager, handle="executor-read-tree")
    sessions = AgentSessionRepository()
    async with rdb_session_manager() as session:
        current = await sessions.get_by_id(session, session_id)
        root = await sessions.get_session_agent_by_session_id(session, session_id)
        assert current is not None and root is not None
        first = await sessions.create_child_session_agent(
            session,
            parent_session_agent_id=root.id,
            name="a-child",
            agent_type="default",
            title=None,
            last_task_message=None,
        )
        second = await sessions.create_child_session_agent(
            session,
            parent_session_agent_id=root.id,
            name="b-child",
            agent_type="default",
            title=None,
            last_task_message=None,
        )
    boundary = _Boundary(rdb_session_manager)
    reads = _reads(boundary, agents=AgentRepository())
    agent = await reads.get_agent(current.agent_id)
    assert agent is not None and agent.id == current.agent_id
    assert (await reads.get_session(session_id)) == current
    assert (await reads.get_session_agent(session_id)) == root
    snapshot = await reads.model_configuration_snapshot(
        agent_id=current.agent_id, session_id=session_id
    )
    assert snapshot.agent == agent and snapshot.session == current
    targets = tuple(
        sorted((session_id, first.agent_session_id, second.agent_session_id))
    )
    assert await reads.list_tree_session_ids(root_session_agent_id=root.id) == targets
    routes = await reads.tree_change_routes([second.id, "0" * 32, first.id, second.id])
    assert [route.changed_session_agent_id for route in routes] == [second.id, first.id]
    assert all(
        route.root_session_agent_id == root.id and route.target_session_ids == targets
        for route in routes
    )
    boundary.closed()


async def test_head_and_non_reverted_transcript_are_read_in_one_completed_session(
    rdb_session_manager: SessionManager[WriteSession],
) -> None:
    session_id = await _create_session(rdb_session_manager, handle="executor-read-head")
    transcript = EventTranscriptRepository()
    async with rdb_session_manager() as session:
        events = []
        for text in ["old", "head", "reverted", "after"]:
            events.append(
                await transcript.append(
                    session,
                    EventCreate(
                        session_id=session_id,
                        kind=EventKind.USER_MESSAGE,
                        payload=UserMessagePayload(
                            sender_user_id=None, content=text
                        ).model_dump(mode="json"),
                    ),
                )
            )
        await session.write_session.execute(
            sa.update(RDBAgentSession)
            .where(RDBAgentSession.id == session_id)
            .values(model_input_head_event_id=events[1].id)
        )
        await session.write_session.execute(
            sa.update(RDBEvent).where(RDBEvent.id == events[2].id).values(reverted=True)
        )
    boundary = _Boundary(rdb_session_manager)
    result = await _reads(boundary, agents=AgentRepository()).model_input_transcript(
        session_id
    )
    assert result.head_event_id == events[1].id
    assert [event.id for event in result.events] == [events[1].id, events[3].id]
    assert len(boundary.opened) == 1
    boundary.closed()


@pytest.mark.parametrize("failure", ["error", "cancel"])
async def test_read_failure_or_cancellation_closes_sql_and_never_calls_effect(
    rdb_session_manager: SessionManager[WriteSession],
    failure: str,
) -> None:
    session_id = await _create_session(
        rdb_session_manager, handle=f"executor-read-{failure}"
    )
    async with rdb_session_manager() as session:
        current = await AgentSessionRepository().get_by_id(session, session_id)
        assert current is not None

    class FailingAgents(AgentRepository):
        async def get_by_id(self, session: ReadSession, agent_id: str) -> Agent | None:
            await super().get_by_id(session, agent_id)
            if failure == "cancel":
                raise asyncio.CancelledError()
            raise ValueError("Injected durable read failure.")

    boundary = _Boundary(rdb_session_manager)
    effect = AsyncMock()
    with pytest.raises(asyncio.CancelledError if failure == "cancel" else ValueError):
        await _reads(boundary, agents=FailingAgents()).get_agent(current.agent_id)
        await effect()
    effect.assert_not_awaited()
    assert len(boundary.opened) == 1
    boundary.closed()


async def test_wait_mailbox_checks_precede_and_follow_completed_descendant_read(
    rdb_session_manager: SessionManager[WriteSession],
) -> None:
    session_id = await _create_session(
        rdb_session_manager, handle="executor-wait-order"
    )
    sessions = AgentSessionRepository()
    async with rdb_session_manager() as session:
        root = await sessions.get_session_agent_by_session_id(session, session_id)
        assert root is not None
        first = await sessions.create_child_session_agent(
            session,
            parent_session_agent_id=root.id,
            name="a-child",
            agent_type="default",
            title=None,
            last_task_message=None,
        )
        second = await sessions.create_child_session_agent(
            session,
            parent_session_agent_id=root.id,
            name="b-child",
            agent_type="default",
            title=None,
            last_task_message=None,
        )
        await session.write_session.execute(
            sa.update(RDBAgentSession)
            .where(RDBAgentSession.id == first.agent_session_id)
            .values(run_state=AgentSessionRunState.RUNNING)
        )
    boundary = _Boundary(rdb_session_manager)
    calls: list[str] = []

    async def all_kinds(target: str) -> bool:
        boundary.closed()
        assert not boundary.opened
        calls.append("all:" + target)
        return True

    async def wake(target: str) -> bool:
        boundary.closed()
        assert len(boundary.opened) == 1
        calls.append("wake:" + target)
        return target == second.agent_session_id

    mailbox = MagicMock(spec=MailboxService)
    mailbox.has_pending_session_mailbox_items = AsyncMock(side_effect=all_kinds)
    mailbox.has_pending_wake_session_mailbox_items = AsyncMock(side_effect=wake)
    service = AgentWaitService(
        repository=AgentWaitReadRepository(
            session_manager=boundary.session_manager,
            agent_session_repository=sessions,
            agent_run_repository=AgentRunRepository(),
        ),
        mailbox_item_service=require_instance(mailbox, MailboxService),
    )
    result = await service.observe(session_id)
    assert result.mailbox_updated and result.descendant_count == 2
    assert result.active_paths == (first.path, second.path)
    assert calls == ["all:" + session_id, "wake:" + second.agent_session_id]
    boundary.closed()


async def test_wait_missing_session_retains_initial_mailbox_result_and_empty_count(
    rdb_session_manager: SessionManager[WriteSession],
) -> None:
    boundary = _Boundary(rdb_session_manager)
    mailbox = MagicMock(spec=MailboxService)
    mailbox.has_pending_session_mailbox_items = AsyncMock(return_value=True)
    mailbox.has_pending_wake_session_mailbox_items = AsyncMock()
    service = AgentWaitService(
        repository=AgentWaitReadRepository(
            session_manager=boundary.session_manager,
            agent_session_repository=AgentSessionRepository(),
            agent_run_repository=AgentRunRepository(),
        ),
        mailbox_item_service=require_instance(mailbox, MailboxService),
    )
    result = await service.observe("0" * 32)
    assert (
        result.mailbox_updated
        and result.descendant_count == 0
        and result.active_paths == ()
    )
    mailbox.has_pending_wake_session_mailbox_items.assert_not_awaited()
    boundary.closed()


async def test_metadata_skip_and_missing_source_capture_have_no_provider_fetch(
    rdb_session_manager: SessionManager[WriteSession],
) -> None:
    boundary = _Boundary(rdb_session_manager)
    service = ModelMetadataService(
        repository=ModelMetadataReadRepository(
            session_manager=boundary.session_manager,
            source_repository=ModelMetadataSourceRepository(),
        )
    )
    assert (await service.capture_for_context(requests=[])).models == ()
    assert not boundary.opened
    captured = await service.capture_for_context(
        requests=[
            ContextModelRequest(
                provider=LLMProvider.OPENAI,
                model_identifier="exact-missing-model",
            )
        ]
    )
    assert len(captured.models) == 1
    assert captured.models[0].max_input_tokens is None
    assert len(boundary.opened) == 1
    boundary.closed()
