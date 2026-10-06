"""PostgreSQL recovery scan boundaries, routing and transparent cancellation."""

import asyncio
import dataclasses
import datetime
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Literal

import pytest
import sqlalchemy as sa
from azcommon.uuid import uuid7

from azents.broker.types import BrokerMessage, SessionBroker, SessionWakeUp
from azents.core.enums import (
    AgentLifecycleStatus,
    AgentSessionRunState,
    AgentSessionStatus,
)
from azents.rdb.models.agent import RDBAgent
from azents.rdb.models.agent_session import RDBAgentSession
from azents.rdb.models.conversation import RDBConversation
from azents.rdb.models.session_agent import RDBSessionAgent
from azents.rdb.session import SessionManager
from azents.rdb.session_capabilities import ReadSession, WriteSession
from azents.repos.agent_execution import AgentRunRepository
from azents.repos.agent_mailbox import AgentMailboxRepository
from azents.repos.agent_session import AgentSessionRepository
from azents.repos.mailbox import MailboxRepository
from azents.repos.mailbox.admission import MailboxAdmissionRepository
from azents.repos.session_execution.repository_test import _create_execution_subject
from azents.repos.session_execution_record import SessionExecutionRecordRepository
from azents.repos.terminal_finalization import TerminalRunFinalizationRepository
from azents.repos.worker_session import WorkerSessionOperationRepository
from azents.repos.worker_session_data import StuckWorkerSession
from azents.repos.worker_session_recovery import (
    WorkerSessionRecoveryOperationRepository,
    WorkerSessionRecoveryQueryRepository,
)
from azents.worker.session.lifecycle import SessionLifecycleService
from azents.worker.session.recovery import StuckSessionRecovery


class ObservedReadManager:
    """Track genuine Session scopes and transaction resolution on every exit."""

    def __init__(self, manager: SessionManager[WriteSession]) -> None:
        self.manager = manager
        self.active = False
        self.sessions: list[WriteSession] = []
        self.resolved: list[bool] = []

    @asynccontextmanager
    async def __call__(self) -> AsyncIterator[WriteSession]:
        assert not self.active, "A completed operation retained or nested its Session"
        self.active = True
        current: WriteSession | None = None
        try:
            async with self.manager() as session:
                current = session
                self.sessions.append(session)
                yield session
        finally:
            self.active = False
            if current is not None:
                self.resolved.append(not current.write_session.in_transaction())

    def assert_closed(self) -> None:
        assert not self.active
        assert all(self.resolved)
        assert all(
            not session.write_session.in_transaction() for session in self.sessions
        )


class _ScanningSessions(WorkerSessionRecoveryQueryRepository):
    """Observe the exact primitive arguments and Session while running real SQL."""

    def __init__(
        self, observed: ObservedReadManager, error: BaseException | None
    ) -> None:
        self.observed = observed
        self.error = error
        self.calls: list[tuple[ReadSession, datetime.timedelta, int]] = []

    async def find_stuck_running(
        self, session: ReadSession, *, stale_threshold: datetime.timedelta, limit: int
    ) -> list[StuckWorkerSession]:
        assert self.observed.active and session is self.observed.sessions[-1]
        self.calls.append((session, stale_threshold, limit))
        records = await super().find_stuck_running(
            session, stale_threshold=stale_threshold, limit=limit
        )
        assert session.read_session.in_transaction()
        if self.error is not None:
            raise self.error
        return records


@dataclasses.dataclass(frozen=True)
class _RecoverySubject:
    root_id: str
    child_id: str
    agent_id: str
    heartbeat: datetime.datetime


async def _subject(
    manager: SessionManager[WriteSession], handle: str
) -> _RecoverySubject:
    sessions = AgentSessionRepository()
    async with manager() as session:
        root, agent_id = await _create_execution_subject(session, handle=handle)
        root_node = await sessions.get_session_agent_by_session_id(session, root.id)
        assert root_node is not None
        child = await sessions.create_child_session_agent(
            session,
            parent_session_agent_id=root_node.id,
            name="recovery-child",
            agent_type="default",
            title=None,
            last_task_message=None,
        )
        await sessions.mark_running(session, child.agent_session_id)
        heartbeat = await session.write_session.scalar(sa.select(sa.func.now()))
        assert isinstance(heartbeat, datetime.datetime)
        await session.write_session.execute(
            sa.update(RDBAgentSession)
            .where(RDBAgentSession.id == root.id)
            .values(run_heartbeat_at=heartbeat - datetime.timedelta(minutes=10))
        )
        await session.write_session.execute(
            sa.update(RDBAgentSession)
            .where(RDBAgentSession.id == child.agent_session_id)
            .values(run_heartbeat_at=heartbeat - datetime.timedelta(minutes=9))
        )
        return _RecoverySubject(root.id, child.agent_session_id, agent_id, heartbeat)


async def test_recovery_scan_preserves_strict_threshold_limit_order_and_routing(
    rdb_session_manager: SessionManager[WriteSession],
) -> None:
    """The database transaction clock gives deterministic exact cutoff boundaries."""
    subject = await _subject(rdb_session_manager, "recovery-threshold-order")
    threshold = datetime.timedelta(minutes=3)
    async with rdb_session_manager() as session:
        for name, offset, state, status, active_agent in [
            (
                "boundary",
                threshold,
                AgentSessionRunState.RUNNING,
                AgentSessionStatus.ACTIVE,
                True,
            ),
            (
                "fresh",
                threshold - datetime.timedelta(microseconds=1),
                AgentSessionRunState.RUNNING,
                AgentSessionStatus.ACTIVE,
                True,
            ),
            (
                "idle",
                datetime.timedelta(hours=1),
                AgentSessionRunState.IDLE,
                AgentSessionStatus.ACTIVE,
                True,
            ),
            (
                "archived",
                datetime.timedelta(hours=1),
                AgentSessionRunState.RUNNING,
                AgentSessionStatus.ARCHIVED,
                True,
            ),
            (
                "inactive-agent",
                datetime.timedelta(hours=1),
                AgentSessionRunState.RUNNING,
                AgentSessionStatus.ACTIVE,
                False,
            ),
        ]:
            row, agent_id = await _create_execution_subject(
                session, handle=f"recovery-exclude-{name}"
            )
            row.run_state = state
            row.status = status
            row.run_heartbeat_at = subject.heartbeat - offset
            if not active_agent:
                agent = await session.read_session.get(RDBAgent, agent_id)
                assert agent is not None
                agent.lifecycle_status = AgentLifecycleStatus.DECOMMISSIONING
        await session.write_session.flush()
    observed = ObservedReadManager(rdb_session_manager)
    sessions = _ScanningSessions(observed, None)
    repository = WorkerSessionRecoveryOperationRepository(observed, sessions)
    for limit, expected in [
        (0, []),
        (1, [subject.root_id]),
        (2, [subject.root_id, subject.child_id]),
        (20, [subject.root_id, subject.child_id]),
    ]:
        result = await repository.find_stuck_running(
            stale_threshold=threshold, limit=limit
        )
        assert result == [
            StuckWorkerSession(id=id, agent_id=subject.agent_id) for id in expected
        ]
        assert sessions.calls[-1][1:] == (threshold, limit)
        observed.assert_closed()
        assert all(dataclasses.is_dataclass(record) for record in result)
    assert len(observed.sessions) == 4


class _RecoveryBroker(SessionBroker):
    """Validate scan and mark closure and committed heartbeats before sending."""

    def __init__(
        self,
        scan: ObservedReadManager,
        marks: ObservedReadManager,
        subject: _RecoverySubject,
        trace: list[str],
        error_for: str | None,
        error: BaseException | None,
    ) -> None:
        self.scan = scan
        self.marks = marks
        self.subject = subject
        self.trace = trace
        self.error_for = error_for
        self.error = error
        self.sent: list[str] = []

    async def send_message(self, message: BrokerMessage) -> None:
        assert isinstance(message, SessionWakeUp)
        self.scan.assert_closed()
        self.marks.assert_closed()
        assert len(self.scan.sessions) == 1
        assert self.trace[-1] == f"mark:{message.session_id}"
        async with self.marks.manager() as session:
            row = await session.write_session.get(RDBAgentSession, message.session_id)
            assert row is not None
            assert row.run_state is AgentSessionRunState.RUNNING
            assert row.run_heartbeat_at is not None
            assert row.run_heartbeat_at > self.subject.heartbeat - datetime.timedelta(
                minutes=3
            )
        if message.session_id == self.error_for:
            assert self.error is not None
            self.trace.append(f"send-failed:{message.session_id}")
            raise self.error
        self.sent.append(message.session_id)
        self.trace.append(f"send:{message.session_id}")


@dataclasses.dataclass(frozen=True)
class _RecoveryLifecycle(SessionLifecycleService):
    scan: ObservedReadManager
    marks: ObservedReadManager
    trace: list[str]
    error_for: str | None
    error: BaseException | None

    async def mark_session_running(self, session_id: str) -> None:
        self.scan.assert_closed()
        assert len(self.scan.sessions) == 1
        if session_id == self.error_for:
            assert self.error is not None
            self.trace.append(f"mark-failed:{session_id}")
            raise self.error
        await super().mark_session_running(session_id)
        self.marks.assert_closed()
        self.trace.append(f"mark:{session_id}")


FailureStage = Literal["none", "mark", "send"]


@dataclasses.dataclass(frozen=True)
class _RecoveryFixture:
    recovery: StuckSessionRecovery
    scan: ObservedReadManager
    marks: ObservedReadManager
    subject: _RecoverySubject
    broker: _RecoveryBroker
    trace: list[str]


async def _recovery_fixture(
    manager: SessionManager[WriteSession], *, failure: FailureStage, cancel: bool
) -> _RecoveryFixture:
    subject = await _subject(manager, f"recovery-effects-{failure}-{cancel}")
    scan = ObservedReadManager(manager)
    marks = ObservedReadManager(manager)
    trace: list[str] = []
    error = asyncio.CancelledError() if cancel else RuntimeError("record failure")
    broker = _RecoveryBroker(
        scan,
        marks,
        subject,
        trace,
        subject.root_id if failure == "send" else None,
        error if failure == "send" else None,
    )
    sessions = AgentSessionRepository()
    runs = AgentRunRepository()
    mailbox = MailboxRepository()
    terminal = TerminalRunFinalizationRepository(
        marks,
        runs,
        sessions,
        AgentMailboxRepository(
            MailboxAdmissionRepository(marks, mailbox, sessions), sessions
        ),
    )
    worker = WorkerSessionOperationRepository(
        marks, sessions, runs, mailbox, terminal, SessionExecutionRecordRepository()
    )
    lifecycle = _RecoveryLifecycle(
        broker,
        worker,
        scan,
        marks,
        trace,
        subject.root_id if failure == "mark" else None,
        error if failure == "mark" else None,
    )
    recovery = StuckSessionRecovery(
        broker=broker,
        repository=WorkerSessionRecoveryOperationRepository(
            scan, WorkerSessionRecoveryQueryRepository()
        ),
        session_lifecycle=lifecycle,
        stale_threshold=datetime.timedelta(minutes=3),
        limit=20,
        interval=datetime.timedelta(minutes=1),
    )
    return _RecoveryFixture(recovery, scan, marks, subject, broker, trace)


@pytest.mark.parametrize("failure", ["none", "mark", "send"])
async def test_recovery_closes_scan_before_root_child_effects_and_record_failures(
    rdb_session_manager: SessionManager[WriteSession], failure: FailureStage
) -> None:
    fixture = await _recovery_fixture(
        rdb_session_manager, failure=failure, cancel=False
    )
    await fixture.recovery.recover_once()
    root, child = fixture.subject.root_id, fixture.subject.child_id
    if failure == "none":
        assert fixture.trace == [
            f"mark:{root}",
            f"send:{root}",
            f"mark:{child}",
            f"send:{child}",
        ]
        assert fixture.broker.sent == [root, child]
    elif failure == "mark":
        assert fixture.trace == [
            f"mark-failed:{root}",
            f"mark:{child}",
            f"send:{child}",
        ]
        assert fixture.broker.sent == [child]
    else:
        assert fixture.trace == [
            f"mark:{root}",
            f"send-failed:{root}",
            f"mark:{child}",
            f"send:{child}",
        ]
        assert fixture.broker.sent == [child]
    fixture.scan.assert_closed()
    fixture.marks.assert_closed()


async def test_recovery_scans_and_routes_profile_free_internal_singleton(
    rdb_session_manager: SessionManager[WriteSession],
) -> None:
    """An internal execution uses the same closed scan, durable mark and broker."""
    fixture = await _recovery_fixture(rdb_session_manager, failure="none", cancel=False)
    internal_id = uuid7().hex
    async with rdb_session_manager() as session:
        root = await session.read_session.get(RDBAgentSession, fixture.subject.root_id)
        assert root is not None
        await session.write_session.execute(
            sa.insert(RDBAgentSession).values(
                id=internal_id,
                agent_id=fixture.subject.agent_id,
                workspace_id=root.workspace_id,
                lifecycle_root_session_id=None,
                run_state=AgentSessionRunState.RUNNING,
                run_heartbeat_at=fixture.subject.heartbeat
                - datetime.timedelta(minutes=8),
            )
        )
        assert await session.read_session.get(RDBConversation, internal_id) is None
        assert (
            await session.read_session.scalar(
                sa.select(RDBSessionAgent).where(
                    RDBSessionAgent.agent_session_id == internal_id
                )
            )
            is None
        )
    await fixture.recovery.recover_once()
    expected = [
        fixture.subject.root_id,
        fixture.subject.child_id,
        internal_id,
    ]
    assert fixture.broker.sent == expected
    assert fixture.trace == [
        effect
        for session_id in expected
        for effect in (f"mark:{session_id}", f"send:{session_id}")
    ]
    fixture.scan.assert_closed()
    fixture.marks.assert_closed()


@pytest.mark.parametrize("failure", ["mark", "send"])
async def test_recovery_cancellation_stops_before_next_record_and_retains_closed_scopes(
    rdb_session_manager: SessionManager[WriteSession], failure: FailureStage
) -> None:
    fixture = await _recovery_fixture(rdb_session_manager, failure=failure, cancel=True)
    with pytest.raises(asyncio.CancelledError):
        await fixture.recovery.recover_once()
    assert fixture.broker.sent == []
    assert all(fixture.subject.child_id not in entry for entry in fixture.trace)
    fixture.scan.assert_closed()
    fixture.marks.assert_closed()


@pytest.mark.parametrize("cancel", [False, True])
async def test_recovery_scan_read_error_or_cancellation_closes_real_transaction(
    rdb_session_manager: SessionManager[WriteSession], cancel: bool
) -> None:
    await _subject(rdb_session_manager, "recovery-scan-failure")
    observed = ObservedReadManager(rdb_session_manager)
    error = asyncio.CancelledError() if cancel else RuntimeError("scan failure")
    repository = WorkerSessionRecoveryOperationRepository(
        observed, _ScanningSessions(observed, error)
    )
    with pytest.raises(type(error)):
        await repository.find_stuck_running(
            stale_threshold=datetime.timedelta(minutes=3), limit=7
        )
    observed.assert_closed()
    assert len(observed.sessions) == 1


class _PausedScan(_ScanningSessions):
    def __init__(self, observed: ObservedReadManager) -> None:
        super().__init__(observed, None)
        self.read = asyncio.Event()
        self.release = asyncio.Event()

    async def find_stuck_running(
        self, session: ReadSession, *, stale_threshold: datetime.timedelta, limit: int
    ) -> list[StuckWorkerSession]:
        result = await super().find_stuck_running(
            session, stale_threshold=stale_threshold, limit=limit
        )
        self.read.set()
        await self.release.wait()
        return result


async def test_actual_task_cancellation_after_recovery_scan_resolves_session(
    rdb_session_manager: SessionManager[WriteSession],
) -> None:
    await _subject(rdb_session_manager, "recovery-scan-task-cancel")
    observed = ObservedReadManager(rdb_session_manager)
    sessions = _PausedScan(observed)
    repository = WorkerSessionRecoveryOperationRepository(observed, sessions)
    task = asyncio.create_task(
        repository.find_stuck_running(
            stale_threshold=datetime.timedelta(minutes=3), limit=7
        )
    )
    try:
        await asyncio.wait_for(sessions.read.wait(), timeout=5)
    finally:
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
    assert task.cancelled()
    observed.assert_closed()
