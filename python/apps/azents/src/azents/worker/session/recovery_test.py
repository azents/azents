"""Recovery orchestration over typed completed database operations."""

import datetime

import pytest

from azents.broker.types import BrokerMessage, SessionBroker, SessionWakeUp
from azents.repos.worker_session_data import StuckWorkerSession
from azents.repos.worker_session_recovery import (
    WorkerSessionRecoveryOperationRepository,
)
from azents.worker.session.lifecycle import SessionLifecycleService
from azents.worker.session.recovery import StuckSessionRecovery


class _RecoveryRepository(WorkerSessionRecoveryOperationRepository):
    """Return completed routing data without exposing a SQL session to callers."""

    def __init__(self, records: list[StuckWorkerSession], trace: list[str]) -> None:
        self.records = records
        self.trace = trace
        self.find_calls: list[tuple[datetime.timedelta, int]] = []

    async def find_stuck_running(
        self, *, stale_threshold: datetime.timedelta, limit: int
    ) -> list[StuckWorkerSession]:
        self.find_calls.append((stale_threshold, limit))
        self.trace.append("scan-complete")
        return list(self.records)


class _Broker(SessionBroker):
    """Record the routing-only wake-up after the matching completed mutation."""

    def __init__(self, trace: list[str]) -> None:
        self.trace = trace
        self.sent_messages: list[SessionWakeUp] = []

    async def send_message(self, message: BrokerMessage) -> None:
        assert isinstance(message, SessionWakeUp)
        assert self.trace[-1] == f"mark:{message.session_id}"
        self.sent_messages.append(message)
        self.trace.append(f"send:{message.session_id}")


class _SessionLifecycle(SessionLifecycleService):
    """Record the completed durable transition without a Session adapter."""

    def __init__(self, trace: list[str], fail_for: str | None) -> None:
        self.trace = trace
        self.fail_for = fail_for
        self.running_session_ids: list[str] = []

    async def mark_session_running(self, session_id: str) -> None:
        assert "scan-complete" in self.trace
        if session_id == self.fail_for:
            self.trace.append(f"failed:{session_id}")
            raise RuntimeError("mark failed")
        self.running_session_ids.append(session_id)
        self.trace.append(f"mark:{session_id}")


def _recovery(
    repository: _RecoveryRepository,
    broker: _Broker,
    lifecycle: _SessionLifecycle,
) -> StuckSessionRecovery:
    return StuckSessionRecovery(
        broker=broker,
        repository=repository,
        session_lifecycle=lifecycle,
        stale_threshold=datetime.timedelta(seconds=5),
        limit=7,
        interval=datetime.timedelta(seconds=60),
    )


@pytest.mark.asyncio
async def test_recover_once_enqueues_resume_for_stuck_sessions() -> None:
    """A completed scan precedes mark-running and then routing-only wake-up."""
    trace: list[str] = []
    repository = _RecoveryRepository(
        [StuckWorkerSession(id="session-001", agent_id="agent-001")], trace
    )
    broker = _Broker(trace)
    lifecycle = _SessionLifecycle(trace, None)
    await _recovery(repository, broker, lifecycle).recover_once()
    assert repository.find_calls == [(datetime.timedelta(seconds=5), 7)]
    assert lifecycle.running_session_ids == ["session-001"]
    assert broker.sent_messages == [SessionWakeUp(session_id="session-001")]
    assert trace == ["scan-complete", "mark:session-001", "send:session-001"]


@pytest.mark.asyncio
async def test_recover_once_continues_after_record_failure() -> None:
    """One failed durable mutation skips that send but not the next record."""
    trace: list[str] = []
    repository = _RecoveryRepository(
        [
            StuckWorkerSession(id="session-bad", agent_id="agent-bad"),
            StuckWorkerSession(id="session-002", agent_id="agent-002"),
        ],
        trace,
    )
    broker = _Broker(trace)
    lifecycle = _SessionLifecycle(trace, "session-bad")
    await _recovery(repository, broker, lifecycle).recover_once()
    assert lifecycle.running_session_ids == ["session-002"]
    assert [message.session_id for message in broker.sent_messages] == ["session-002"]
    assert trace == [
        "scan-complete",
        "failed:session-bad",
        "mark:session-002",
        "send:session-002",
    ]


@pytest.mark.asyncio
async def test_recover_once_treats_root_and_subagent_sessions_independently() -> None:
    """Root and child retain separate routing IDs even when their Agent matches."""
    trace: list[str] = []
    repository = _RecoveryRepository(
        [
            StuckWorkerSession(id="root-session", agent_id="agent-001"),
            StuckWorkerSession(id="child-session", agent_id="agent-001"),
        ],
        trace,
    )
    broker = _Broker(trace)
    lifecycle = _SessionLifecycle(trace, None)
    await _recovery(repository, broker, lifecycle).recover_once()
    assert lifecycle.running_session_ids == ["root-session", "child-session"]
    assert [message.session_id for message in broker.sent_messages] == [
        "root-session",
        "child-session",
    ]
    assert trace == [
        "scan-complete",
        "mark:root-session",
        "send:root-session",
        "mark:child-session",
        "send:child-session",
    ]
