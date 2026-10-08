"""Private DB execution and real broker ownership across common Runner lifetimes."""

import asyncio
import dataclasses
from unittest.mock import Mock

from sqlalchemy.ext.asyncio import AsyncEngine

from azents.broker.memory import InMemoryBroker, InMemoryBrokerState
from azents.broker.types import SessionWakeUp
from azents.rdb.models.base import RDBModel
from azents.rdb.session import SessionManager
from azents.rdb.session_capabilities import (
    WriteSession,
    create_read_write_session_manager,
)
from azents.repos.agent_execution import AgentRunRepository
from azents.repos.agent_session import AgentSessionRepository
from azents.repos.mailbox import MailboxRepository
from azents.repos.session_execution_record import SessionExecutionRecordRepository
from azents.repos.terminal_finalization import TerminalRunFinalizationRepository
from azents.repos.worker_session import WorkerSessionOperationRepository
from azents.testing.committed_fixture_cleanup import committed_fixture_graph
from azents.testing.types import require_instance
from azents.worker.run.memory_execution_test import _executor
from azents.worker.session.lifecycle import SessionLifecycleService
from azents.worker.worker_test import _Host, _make_session_runner


def _lifecycle(
    manager: SessionManager[WriteSession], broker: InMemoryBroker
) -> SessionLifecycleService:
    repository = WorkerSessionOperationRepository(
        manager,
        AgentSessionRepository(),
        AgentRunRepository(),
        MailboxRepository(),
        require_instance(
            Mock(spec=TerminalRunFinalizationRepository),
            TerminalRunFinalizationRepository,
        ),
        SessionExecutionRecordRepository(),
    )
    return SessionLifecycleService(broker, repository)


async def test_real_runner_takeover_releases_broker_and_executes_clean_successor(
    rdb_engine: AsyncEngine,
    latest_db_schema: None,
) -> None:
    """A recovered predecessor cannot keep a broker lease after owner fencing."""
    del latest_db_schema
    manager = create_read_write_session_manager(rdb_engine)
    async with committed_fixture_graph(rdb_engine, RDBModel.metadata):
        await _exercise_takeover(manager)


async def _exercise_takeover(
    rdb_session_manager: SessionManager[WriteSession],
) -> None:
    executor, principal = await _executor(
        rdb_session_manager, quotas=False, deadline_seconds=None, block_after_turns=0
    )
    state = InMemoryBrokerState(clock=asyncio.get_running_loop().time)
    broker = InMemoryBroker(state, worker_id="private-memory-worker")
    lifecycle = _lifecycle(rdb_session_manager, broker)
    executor = dataclasses.replace(executor, lifecycle=lifecycle)
    host = _Host()
    runner = _make_session_runner(host)
    runner.session_lifecycle = lifecycle
    runner.memory_execution_repository = executor.executions
    runner.memory_run_executor = executor
    predecessor_id = principal.owner.session_id
    await broker.send_message(SessionWakeUp(session_id=predecessor_id))
    async with asyncio.timeout(8):
        for signal in await broker.receive_messages():
            assert isinstance(signal, SessionWakeUp)
            runner.enqueue(signal)
        await runner.run()
    assert runner.terminated and runner.internal_execution
    assert predecessor_id not in state.owners
    assert not executor.host_models
    assert host.processed_messages == host.idle_continuation_calls == []
    async with asyncio.timeout(8):
        signals = await broker.receive_messages()
        assert len(signals) == 1 and isinstance(signals[0], SessionWakeUp)
        successor_id = signals[0].session_id
        assert successor_id != predecessor_id
        successor = _make_session_runner(host)
        successor.session_lifecycle = lifecycle
        successor.memory_execution_repository = executor.executions
        successor.memory_run_executor = executor
        successor.enqueue(signals[0])
        await successor.run()
    assert successor.terminated and successor.internal_execution
    assert successor_id not in state.owners
    final = await executor.executions.load_binding(successor_id)
    assert final is not None and final.accepted is not None
    assert final.deadline_at == principal.binding.deadline_at
    assert final.started_turns == 1
    assert len(executor.host_models) == 1 and executor.host_models[0].closed
    assert host.processed_messages == host.idle_continuation_calls == []
    assert host.finalize_unhandled_calls == host.parent_result_activity_run_ids == []
    await state.aclose()


async def test_private_runner_cleanup_preserves_another_worker_broker_owner() -> None:
    """Durable domain fencing never grants release of another Worker's lease."""
    state = InMemoryBrokerState(clock=asyncio.get_running_loop().time)
    old_broker = InMemoryBroker(state, worker_id="former-worker")
    new_broker = InMemoryBroker(state, worker_id="replacement-worker")
    session_id = "former-private-session"
    await old_broker.send_message(SessionWakeUp(session_id=session_id))
    async with asyncio.timeout(3):
        await old_broker.receive_messages()
    assert state.owners[session_id].worker_id == "former-worker"
    await old_broker.release_session_lock(session_id)
    await new_broker.send_message(SessionWakeUp(session_id=session_id))
    async with asyncio.timeout(3):
        await new_broker.receive_messages()
    assert state.owners[session_id].worker_id == "replacement-worker"
    runner = _make_session_runner(_Host())
    runner.session_lifecycle = SessionLifecycleService(
        old_broker,
        require_instance(
            Mock(spec=WorkerSessionOperationRepository),
            WorkerSessionOperationRepository,
        ),
    )
    runner.running_session_id = session_id
    runner.owner_generation = 1
    runner.internal_execution = True
    await runner._release_current_session()
    assert state.owners[session_id].worker_id == "replacement-worker"
    await state.aclose()
