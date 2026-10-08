"""Scheduler orchestration over typed completed operations and real Job Runtime."""

import asyncio
import dataclasses
import datetime
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import pytest
from azcommon import di

from azents.core.enums import ScheduledTaskStatus
from azents.job_runtime.local import LocalJobRuntime
from azents.job_runtime.types import (
    JobHandle,
    JobHandlerDefinition,
    JobHandlerRegistry,
    JobOutcome,
    JobRequest,
    JobRuntime,
)
from azents.rdb.session import SessionManager
from azents.rdb.session_capabilities import WriteSession
from azents.repos.scheduled_task_state import ScheduledTaskStateRepository
from azents.repos.scheduled_task_state.data import ScheduledTaskState
from azents.repos.scheduler_state_operations import SchedulerStateOperationRepository
from azents.scheduler.executor import (
    SCHEDULER_JOB_HANDLER_KEY,
    execute_scheduled_task_job,
)
from azents.scheduler.service import SchedulerService, compute_failure_next_run_at
from azents.scheduler.types import (
    RetryPolicy,
    ScheduledTaskDefinition,
    TaskContext,
    TaskResult,
)


class CompletedOperations(SchedulerStateOperationRepository):
    """Typed completed-operation double; it never creates or accepts a Session."""

    def __init__(self, trace: list[str], errors: dict[str, BaseException]) -> None:
        self.trace = trace
        self.errors = errors
        self.claim_times: list[datetime.datetime] = []
        self.lease_times: list[datetime.datetime] = []
        self.ensured_keys: list[tuple[str, ...]] = []
        self.success_summaries: list[dict[str, object] | None] = []
        self.failure_codes: list[str] = []
        self.states: dict[str, ScheduledTaskState] = {}
        self.noops: set[str] = set()

    def completed(self, operation: str) -> None:
        self.trace.append(operation)
        error = self.errors.get(operation)
        if error is not None:
            raise error

    async def ensure_registered_states(
        self, *, task_keys: tuple[str, ...], now: datetime.datetime
    ) -> None:
        self.completed("ensure")
        self.ensured_keys.append(task_keys)
        for key in task_keys:
            self.states.setdefault(
                key, _state(task_key=key, last_started_at=now, manual_requested_at=None)
            )

    async def list_states(self) -> list[ScheduledTaskState]:
        self.completed("list")
        return [self.states[key] for key in sorted(self.states)]

    async def get_state(self, task_key: str) -> ScheduledTaskState | None:
        self.completed("get")
        return self.states.get(task_key)

    async def trigger(
        self, *, task_key: str, now: datetime.datetime
    ) -> ScheduledTaskState | None:
        self.completed("trigger")
        return self.states.get(task_key)

    async def claim_due(
        self,
        *,
        task_key: str,
        now: datetime.datetime,
        lease_owner: str,
        lease_until: datetime.datetime,
    ) -> ScheduledTaskState | None:
        self.completed(f"claim:{task_key}")
        self.claim_times.append(now)
        self.lease_times.append(lease_until)
        if task_key in self.noops:
            return None
        return _state(task_key=task_key, last_started_at=now, manual_requested_at=None)

    async def mark_success(
        self,
        *,
        task_key: str,
        lease_owner: str,
        finished_at: datetime.datetime,
        next_run_at: datetime.datetime,
        result_summary: dict[str, object] | None,
    ) -> ScheduledTaskState | None:
        self.completed(f"success:{task_key}")
        self.success_summaries.append(result_summary)
        return None

    async def mark_failure(
        self,
        *,
        task_key: str,
        lease_owner: str,
        finished_at: datetime.datetime,
        next_run_at: datetime.datetime,
        error_code: str,
        error_message: str,
    ) -> ScheduledTaskState | None:
        self.completed(f"failure:{task_key}")
        self.failure_codes.append(error_code)
        return None


class CompletedHandle(JobHandle):
    def __init__(
        self,
        trace: list[str],
        key: str,
        outcome: JobOutcome,
        error: BaseException | None,
    ) -> None:
        self.trace = trace
        self.key = key
        self.outcome = outcome
        self.error = error
        self.waited = 0

    async def wait(self) -> JobOutcome:
        self.trace.append(f"wait:{self.key}")
        self.waited += 1
        if self.error is not None:
            raise self.error
        return self.outcome


class RecordingRuntime(JobRuntime):
    def __init__(
        self,
        trace: list[str],
        outcomes: dict[str, JobOutcome],
        errors: dict[str, BaseException],
    ) -> None:
        self.trace = trace
        self.outcomes = outcomes
        self.errors = errors
        self.requests: list[JobRequest] = []
        self.handles: list[CompletedHandle] = []

    @property
    def active_count(self) -> int:
        return 0

    @property
    def shutdown_drain_seconds(self) -> float | None:
        return None

    async def submit(self, request: JobRequest) -> JobHandle:
        key = request.payload["task_key"]
        assert isinstance(key, str)
        self.trace.append(f"submit:{key}")
        self.requests.append(request)
        error = self.errors.get(f"submit:{key}")
        if error is not None:
            raise error
        handle = CompletedHandle(
            self.trace,
            key,
            self.outcomes.get(key, JobOutcome.succeeded({"deleted": 3})),
            self.errors.get(f"wait:{key}"),
        )
        self.handles.append(handle)
        return handle


async def _handler(context: TaskContext) -> TaskResult:
    return TaskResult(summary={"task_key": context.task_key})


def _definition(key: str, *, enabled: bool) -> ScheduledTaskDefinition:
    return ScheduledTaskDefinition(
        key=key,
        description=key,
        interval=datetime.timedelta(hours=1),
        timeout=datetime.timedelta(minutes=2),
        retry_policy=RetryPolicy(kind="next_interval"),
        handler=_handler,
        enabled_by_default=enabled,
    )


def test_compute_failure_next_run_at_uses_next_interval() -> None:
    """next_interval retry waits for regular interval."""
    now = datetime.datetime(2026, 1, 1, tzinfo=datetime.UTC)
    result = compute_failure_next_run_at(
        RetryPolicy(kind="next_interval"), datetime.timedelta(hours=1), 3, now
    )
    assert result == now + datetime.timedelta(hours=1)


def test_compute_failure_next_run_at_bounds_backoff() -> None:
    """bounded_backoff is capped by max_delay."""
    now = datetime.datetime(2026, 1, 1, tzinfo=datetime.UTC)
    result = compute_failure_next_run_at(
        RetryPolicy(
            kind="bounded_backoff",
            min_delay=datetime.timedelta(minutes=5),
            max_delay=datetime.timedelta(minutes=30),
        ),
        datetime.timedelta(hours=1),
        5,
        now,
    )
    assert result == now + datetime.timedelta(minutes=30)


@pytest.mark.asyncio
async def test_run_once_continues_when_task_lifecycle_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A failure-recording exception leaves later definitions eligible to run."""
    trace: list[str] = []
    repository = CompletedOperations(
        trace, {"failure:failing": RuntimeError("task-state recording failed")}
    )
    runtime = RecordingRuntime(
        trace, {"failing": JobOutcome.failed(ValueError("handler failed"))}, {}
    )
    scheduler = SchedulerService(
        repository=repository, job_runtime=runtime, scheduler_id="scheduler"
    )
    monkeypatch.setattr(
        "azents.scheduler.service.get_task_definitions",
        lambda: (
            _definition("failing", enabled=True),
            _definition("succeeding", enabled=True),
        ),
    )
    await scheduler.run_once()
    assert [request.payload["task_key"] for request in runtime.requests] == [
        "failing",
        "succeeding",
    ]
    assert trace == [
        "claim:failing",
        "submit:failing",
        "wait:failing",
        "failure:failing",
        "claim:succeeding",
        "submit:succeeding",
        "wait:succeeding",
        "success:succeeding",
    ]
    assert repository.claim_times[0] is repository.claim_times[1]


@pytest.mark.asyncio
async def test_run_once_propagates_task_cancellation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Task cancellation stops the pass instead of recording a failure."""
    trace: list[str] = []
    repository = CompletedOperations(trace, {})
    runtime = RecordingRuntime(trace, {}, {"wait:cancelling": asyncio.CancelledError()})
    scheduler = SchedulerService(
        repository=repository, job_runtime=runtime, scheduler_id="scheduler"
    )
    monkeypatch.setattr(
        "azents.scheduler.service.get_task_definitions",
        lambda: (
            _definition("cancelling", enabled=True),
            _definition("later", enabled=True),
        ),
    )
    with pytest.raises(asyncio.CancelledError):
        await scheduler.run_once()
    assert trace == ["claim:cancelling", "submit:cancelling", "wait:cancelling"]


@pytest.mark.asyncio
async def test_execute_claimed_submits_json_safe_per_claim_request() -> None:
    """Scheduler delegates the unchanged claim identity through Job Runtime."""
    attempt_started_at = datetime.datetime(2026, 8, 10, tzinfo=datetime.UTC)
    definition = _definition("cleanup", enabled=True)
    state = _state(
        task_key=definition.key,
        last_started_at=attempt_started_at,
        manual_requested_at=attempt_started_at,
    )
    trace: list[str] = []
    repository = CompletedOperations(trace, {})
    runtime = RecordingRuntime(trace, {}, {})
    scheduler = SchedulerService(
        repository=repository, job_runtime=runtime, scheduler_id="scheduler-1"
    )
    await scheduler._execute_claimed(definition, state)
    assert len(runtime.requests) == 1
    submitted = runtime.requests[0]
    assert submitted.handler_key == "scheduler.task"
    assert (
        submitted.execution_key
        == "scheduler:cleanup:scheduler-1:2026-08-10T00:00:00+00:00"
    )
    assert submitted.deadline == attempt_started_at + definition.timeout
    assert submitted.payload == {
        "task_key": "cleanup",
        "attempt_started_at": "2026-08-10T00:00:00Z",
        "lease_owner": "scheduler-1",
        "manual_triggered": True,
    }
    assert runtime.handles[0].waited == 1
    assert repository.success_summaries == [{"deleted": 3}]


@pytest.mark.parametrize("action", ["list", "get", "trigger", "unknown"])
async def test_public_reads_keep_separate_ensure_and_disabled_key_tuple(
    monkeypatch: pytest.MonkeyPatch, action: str
) -> None:
    trace: list[str] = []
    repository = CompletedOperations(trace, {})
    scheduler = SchedulerService(
        repository, RecordingRuntime(trace, {}, {}), scheduler_id="scheduler"
    )
    monkeypatch.setattr(
        "azents.scheduler.service.get_task_definitions",
        lambda: (
            _definition("enabled", enabled=True),
            _definition("disabled", enabled=False),
        ),
    )
    if action == "list":
        assert [row.task_key for row in await scheduler.list_states()] == [
            "disabled",
            "enabled",
        ]
    elif action == "get":
        assert await scheduler.get_state("enabled") is not None
    else:
        state = await scheduler.trigger("enabled" if action == "trigger" else "missing")
        assert (state is None) == (action == "unknown")
    assert repository.ensured_keys == [("enabled", "disabled")]
    assert trace == (["ensure"] if action == "unknown" else ["ensure", action])


async def test_one_loop_now_disabled_and_noop_claims_do_not_submit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    trace: list[str] = []
    repository = CompletedOperations(trace, {})
    repository.noops.add("idle")
    runtime = RecordingRuntime(trace, {}, {})
    scheduler = SchedulerService(repository, runtime, scheduler_id="scheduler")
    monkeypatch.setattr(
        "azents.scheduler.service.get_task_definitions",
        lambda: (
            _definition("idle", enabled=True),
            _definition("disabled", enabled=False),
            _definition("active", enabled=True),
        ),
    )
    await scheduler.run_once()
    assert repository.claim_times[0] is repository.claim_times[1]
    assert repository.lease_times[0] == repository.claim_times[0] + datetime.timedelta(
        minutes=2, seconds=30
    )
    assert [request.payload["task_key"] for request in runtime.requests] == ["active"]
    assert trace == [
        "claim:idle",
        "claim:active",
        "submit:active",
        "wait:active",
        "success:active",
    ]


async def test_success_recording_error_is_not_reclassified_as_failure() -> None:
    trace: list[str] = []
    repository = CompletedOperations(
        trace, {"success:task": RuntimeError("success write failed")}
    )
    scheduler = SchedulerService(
        repository, RecordingRuntime(trace, {}, {}), scheduler_id="scheduler"
    )
    with pytest.raises(RuntimeError, match="success write failed"):
        await scheduler._execute_claimed(
            _definition("task", enabled=True),
            _state(
                task_key="task",
                last_started_at=datetime.datetime.now(datetime.UTC),
                manual_requested_at=None,
            ),
        )
    assert "failure:task" not in trace


async def test_missing_attempt_start_raises_before_submit_or_settlement() -> None:
    trace: list[str] = []
    scheduler = SchedulerService(
        CompletedOperations(trace, {}),
        RecordingRuntime(trace, {}, {}),
        scheduler_id="scheduler",
    )
    with pytest.raises(RuntimeError, match="missing its start timestamp"):
        await scheduler._execute_claimed(
            _definition("task", enabled=True),
            _state(task_key="task", last_started_at=None, manual_requested_at=None),
        )
    assert trace == []


async def test_startup_ensure_failure_propagates_without_job_submission(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    trace: list[str] = []
    repository = CompletedOperations(
        trace, {"ensure": RuntimeError("registration failed")}
    )
    scheduler = SchedulerService(
        repository, RecordingRuntime(trace, {}, {}), scheduler_id="scheduler"
    )
    monkeypatch.setattr(
        "azents.scheduler.service.get_task_definitions",
        lambda: (_definition("task", enabled=True),),
    )
    with pytest.raises(RuntimeError, match="registration failed"):
        await scheduler.run(asyncio.Event())
    assert trace == ["ensure"]


async def test_normal_stale_settlement_none_keeps_existing_success_log(
    caplog: pytest.LogCaptureFixture,
) -> None:
    trace: list[str] = []
    repository = CompletedOperations(trace, {})
    scheduler = SchedulerService(
        repository, RecordingRuntime(trace, {}, {}), scheduler_id="scheduler"
    )
    with caplog.at_level(logging.INFO, logger="azents.scheduler.service"):
        await scheduler._execute_claimed(
            _definition("task", enabled=True),
            _state(
                task_key="task",
                last_started_at=datetime.datetime.now(datetime.UTC),
                manual_requested_at=None,
            ),
        )
    assert "Scheduled task succeeded" in caplog.text
    assert repository.success_summaries == [{"deleted": 3}]


class RealBoundary:
    """Delegate every SQL scope to genuine PostgreSQL and observe its completion."""

    def __init__(self, manager: SessionManager[WriteSession]) -> None:
        self.manager = manager
        self.active: list[WriteSession] = []
        self.sessions: list[WriteSession] = []

    @asynccontextmanager
    async def __call__(self) -> AsyncIterator[WriteSession]:
        async with self.manager() as session:
            self.active.append(session)
            self.sessions.append(session)
            try:
                yield session
            finally:
                self.active.remove(session)

    def assert_closed(self) -> None:
        assert not self.active
        assert all(
            not session.write_session.in_transaction() for session in self.sessions
        )


class BoundaryHandle(JobHandle):
    def __init__(self, handle: JobHandle, boundary: RealBoundary) -> None:
        self.handle = handle
        self.boundary = boundary

    async def wait(self) -> JobOutcome:
        self.boundary.assert_closed()
        result = await self.handle.wait()
        self.boundary.assert_closed()
        return result


class BoundaryLocalRuntime(LocalJobRuntime):
    def __init__(self, boundary: RealBoundary) -> None:
        super().__init__(
            handlers=JobHandlerRegistry(
                (
                    JobHandlerDefinition(
                        key=SCHEDULER_JOB_HANDLER_KEY,
                        handler=execute_scheduled_task_job,
                    ),
                )
            ),
            container_factory=di.Container,
            max_concurrency=1,
            cancellation_grace_seconds=0.1,
        )
        self.boundary = boundary
        self.requests: list[JobRequest] = []

    async def submit(self, request: JobRequest) -> JobHandle:
        self.boundary.assert_closed()
        self.requests.append(request)
        return BoundaryHandle(await super().submit(request), self.boundary)


class BoundaryLogs(logging.Handler):
    def __init__(self, boundary: RealBoundary) -> None:
        super().__init__()
        self.boundary = boundary
        self.messages: list[str] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.boundary.assert_closed()
        self.messages.append(record.getMessage())


@pytest.mark.parametrize("fail", [False, True])
async def test_real_scheduler_job_runtime_and_logs_follow_completed_pg_operations(
    rdb_session_manager: SessionManager[WriteSession],
    monkeypatch: pytest.MonkeyPatch,
    fail: bool,
) -> None:
    boundary = RealBoundary(rdb_session_manager)
    repository = SchedulerStateOperationRepository(
        boundary, ScheduledTaskStateRepository()
    )
    now = datetime.datetime.now(datetime.UTC)
    key = "scheduler-real-job"
    handler_calls: list[str] = []

    async def handler(context: TaskContext) -> TaskResult:
        boundary.assert_closed()
        handler_calls.append(context.task_key)
        if fail:
            raise ValueError("handler failure")
        return TaskResult(summary={"deleted": 3})

    definition = dataclasses.replace(_definition(key, enabled=True), handler=handler)
    monkeypatch.setattr(
        "azents.scheduler.service.get_task_definitions", lambda: (definition,)
    )
    monkeypatch.setattr(
        "azents.scheduler.executor.get_task_definitions", lambda: (definition,)
    )
    await repository.ensure_registered_states(task_keys=(key,), now=now)
    runtime = BoundaryLocalRuntime(boundary)
    scheduler = SchedulerService(repository, runtime, scheduler_id="real-owner")
    logs = BoundaryLogs(boundary)
    logger = logging.getLogger("azents.scheduler.service")
    old_level = logger.level
    logger.setLevel(logging.INFO)
    logger.addHandler(logs)
    try:
        await scheduler.run_once()
        async with rdb_session_manager() as session:
            state = await ScheduledTaskStateRepository().get(session, key)
        assert state is not None and state.lease_owner is None
        assert state.latest_status is (
            ScheduledTaskStatus.FAILED if fail else ScheduledTaskStatus.SUCCEEDED
        )
        assert state.failure_streak == (1 if fail else 0)
        assert state.latest_result_summary == (None if fail else {"deleted": 3})
        assert handler_calls == [key]
        assert len(runtime.requests) == 1
        assert (
            "Scheduled task failed" if fail else "Scheduled task succeeded"
        ) in logs.messages
        assert len(boundary.sessions) == 3
        boundary.assert_closed()
    finally:
        logger.removeHandler(logs)
        logger.setLevel(old_level)
        await runtime.close()


async def test_cancelled_real_scheduler_waiter_keeps_committed_lease_and_shielded_job(
    rdb_session_manager: SessionManager[WriteSession], monkeypatch: pytest.MonkeyPatch
) -> None:
    boundary = RealBoundary(rdb_session_manager)
    repository = SchedulerStateOperationRepository(
        boundary, ScheduledTaskStateRepository()
    )
    key = "scheduler-real-cancel"
    started, release, finished = asyncio.Event(), asyncio.Event(), asyncio.Event()

    async def handler(_context: TaskContext) -> TaskResult:
        boundary.assert_closed()
        started.set()
        await release.wait()
        finished.set()
        return TaskResult(summary={"finished": True})

    definition = dataclasses.replace(_definition(key, enabled=True), handler=handler)
    monkeypatch.setattr(
        "azents.scheduler.service.get_task_definitions", lambda: (definition,)
    )
    monkeypatch.setattr(
        "azents.scheduler.executor.get_task_definitions", lambda: (definition,)
    )
    await repository.ensure_registered_states(
        task_keys=(key,), now=datetime.datetime.now(datetime.UTC)
    )
    runtime = BoundaryLocalRuntime(boundary)
    scheduler = SchedulerService(repository, runtime, scheduler_id="real-owner")
    task = asyncio.create_task(scheduler.run_once())
    try:
        await asyncio.wait_for(started.wait(), timeout=5)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        boundary.assert_closed()
        assert not finished.is_set()
        async with rdb_session_manager() as session:
            state = await ScheduledTaskStateRepository().get(session, key)
        assert state is not None
        assert (
            state.lease_owner == "real-owner"
            and state.latest_status is ScheduledTaskStatus.RUNNING
        )
        assert state.last_finished_at is None
        assert len(boundary.sessions) == 2
    finally:
        release.set()
        if not task.done():
            task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        await runtime.close()
    assert finished.is_set()


@pytest.mark.parametrize("stage", ["submit", "wait"])
async def test_external_runtime_error_keeps_existing_failure_settlement(
    stage: str,
) -> None:
    trace: list[str] = []
    repository = CompletedOperations(trace, {})
    runtime = RecordingRuntime(
        trace, {}, {f"{stage}:task": RuntimeError("runtime failed")}
    )
    scheduler = SchedulerService(repository, runtime, scheduler_id="scheduler")
    await scheduler._execute_claimed(
        _definition("task", enabled=True),
        _state(
            task_key="task",
            last_started_at=datetime.datetime.now(datetime.UTC),
            manual_requested_at=None,
        ),
    )
    assert trace[-1] == "failure:task"
    assert repository.failure_codes == ["RuntimeError"]
    assert not repository.success_summaries


@pytest.mark.parametrize("closed", [False, True])
async def test_real_runtime_closed_submit_or_nullable_summary_preserves_settlement(
    rdb_session_manager: SessionManager[WriteSession],
    monkeypatch: pytest.MonkeyPatch,
    closed: bool,
) -> None:
    boundary = RealBoundary(rdb_session_manager)
    repository = SchedulerStateOperationRepository(
        boundary, ScheduledTaskStateRepository()
    )
    key = "scheduler-real-nullable"
    handler_calls: list[str] = []

    async def handler(context: TaskContext) -> TaskResult:
        boundary.assert_closed()
        handler_calls.append(context.task_key)
        return TaskResult(summary=None)

    definition = dataclasses.replace(_definition(key, enabled=True), handler=handler)
    monkeypatch.setattr(
        "azents.scheduler.service.get_task_definitions", lambda: (definition,)
    )
    monkeypatch.setattr(
        "azents.scheduler.executor.get_task_definitions", lambda: (definition,)
    )
    await repository.ensure_registered_states(
        task_keys=(key,), now=datetime.datetime.now(datetime.UTC)
    )
    runtime = BoundaryLocalRuntime(boundary)
    if closed:
        await runtime.close()
    scheduler = SchedulerService(repository, runtime, scheduler_id="real-owner")
    try:
        await scheduler.run_once()
        async with rdb_session_manager() as session:
            state = await ScheduledTaskStateRepository().get(session, key)
        assert state is not None and state.lease_owner is None
        assert state.latest_result_summary is None
        assert state.latest_status is (
            ScheduledTaskStatus.FAILED if closed else ScheduledTaskStatus.SUCCEEDED
        )
        assert state.latest_error_code == ("JobRuntimeClosedError" if closed else None)
        assert handler_calls == ([] if closed else [key])
        assert len(boundary.sessions) == 3
        boundary.assert_closed()
    finally:
        await runtime.close()


def _state(
    *,
    task_key: str,
    last_started_at: datetime.datetime | None,
    manual_requested_at: datetime.datetime | None,
) -> ScheduledTaskState:
    now = datetime.datetime(2026, 8, 10, tzinfo=datetime.UTC)
    return ScheduledTaskState(
        task_key=task_key,
        latest_status=ScheduledTaskStatus.RUNNING,
        next_run_at=now,
        last_started_at=last_started_at,
        last_finished_at=None,
        last_succeeded_at=None,
        last_failed_at=None,
        failure_streak=0,
        latest_error_code=None,
        latest_error_message=None,
        latest_result_summary=None,
        lease_owner="scheduler-1",
        leased_at=now,
        lease_until=now + datetime.timedelta(minutes=3),
        manual_requested_at=manual_requested_at,
        created_at=now,
        updated_at=now,
    )
