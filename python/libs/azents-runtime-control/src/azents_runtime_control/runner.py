"""Runner-side Agent Runtime Control contracts and run loop."""

import asyncio
import dataclasses
import enum
import logging
import time
from collections import Counter, deque
from collections.abc import Awaitable, Callable, Mapping, Sequence
from datetime import UTC, datetime
from typing import Protocol, TypeAlias

JsonValue: TypeAlias = (
    None | bool | int | float | str | list["JsonValue"] | dict[str, "JsonValue"]
)
_LOGGER = logging.getLogger(__name__)


class RuntimeRunnerState(enum.StrEnum):
    """Runner state values reported to Control."""

    UNKNOWN = "unknown"
    STARTING = "starting"
    READY = "ready"
    BUSY = "busy"
    DEGRADED = "degraded"
    STOPPING = "stopping"
    FAILED = "failed"


class RuntimeRunnerEventType(enum.StrEnum):
    """Runner operation event types."""

    ACCEPTED = "accepted"
    PROGRESS = "progress"
    STDOUT = "stdout"
    STDERR = "stderr"
    FILE_CHUNK = "file_chunk"
    PROCESS_OUTPUT = "process_output"
    HEARTBEAT = "heartbeat"
    FINAL_SUCCESS = "final_success"
    FINAL_ERROR = "final_error"
    OPERATION_NOT_FOUND = "operation_not_found"


@dataclasses.dataclass(frozen=True)
class RunnerRegistration:
    """Runner registration payload sent to Control."""

    runtime_id: str
    runner_id: str
    protocol_version: str
    capabilities: Sequence[str]
    health: str
    workspace_path: str
    metadata: Mapping[str, JsonValue]
    auth_credential_id: str


@dataclasses.dataclass(frozen=True)
class RunnerRegistrationAccepted:
    """Runner registration result issued by Control."""

    runtime_id: str
    runner_id: str
    connection_id: str
    generation: int
    heartbeat_interval_seconds: int


@dataclasses.dataclass(frozen=True)
class RunnerStateReport:
    """Runner state report sent to Control."""

    runtime_id: str
    runner_id: str
    runner_generation: int
    runner_state: RuntimeRunnerState
    capabilities: Sequence[str]
    active_operation_ids: Sequence[str]
    health: str
    diagnostic: Mapping[str, JsonValue]
    workspace_path: str
    reported_at: datetime


@dataclasses.dataclass(frozen=True)
class RunnerBodyChunk:
    """One request body chunk delivered to the Runner."""

    chunk_id: int
    data: bytes
    final: bool


@dataclasses.dataclass(frozen=True)
class RunnerOperationEnvelope:
    """Control request carrying one Runner operation."""

    request_id: str
    runtime_id: str
    runner_generation: int
    operation_type: str
    payload: Mapping[str, JsonValue]
    reply_stream_id: str
    body_stream_id: str | None
    body_chunks: Sequence[RunnerBodyChunk]
    background: bool
    deadline_at: datetime | None
    owner_session_id: str | None


@dataclasses.dataclass(frozen=True)
class RunnerOperationEvent:
    """Runner operation event delivered back to Control."""

    request_id: str
    runtime_id: str
    generation: int
    event_type: RuntimeRunnerEventType
    payload: Mapping[str, JsonValue]
    created_at: datetime
    final: bool


class RunnerConnectionRejected(RuntimeError):
    """Control rejected a heartbeat or generation fence."""


RunnerOperationHandler: TypeAlias = Callable[[RunnerOperationEnvelope], Awaitable[None]]


class RunnerControlClient(Protocol):
    """Transport implementation used by the Runtime Runner process."""

    def set_operation_handler(self, handler: RunnerOperationHandler) -> None:
        """Set the direct operation admission handler."""
        ...

    async def register_runner(
        self,
        registration: RunnerRegistration,
        *,
        connection_id: str,
        registered_at: datetime,
    ) -> RunnerRegistrationAccepted:
        """Register the Runner connection and receive a generation."""
        ...

    async def heartbeat_runner(
        self,
        *,
        runtime_id: str,
        generation: int,
        heartbeat_at: datetime,
    ) -> bool:
        """Refresh Runner connection TTL for the accepted generation."""
        ...

    async def report_runner_state(self, report: RunnerStateReport) -> None:
        """Persist one Runner state report."""
        ...

    async def claim_next_runner_operation(
        self,
        *,
        runtime_id: str,
        generation: int,
        consumer_id: str,
        block_ms: int,
    ) -> RunnerOperationEnvelope | None:
        """Claim the next operation assigned to this Runner generation."""
        ...

    async def start_runner_operation(
        self,
        operation: RunnerOperationEnvelope,
    ) -> bool:
        """Authorize a pending operation immediately before execution."""
        ...

    async def append_runner_event(self, event: RunnerOperationEvent) -> None:
        """Append one Runner operation event."""
        ...


class RuntimeRunnerOperations(Protocol):
    """Runtime-internal operation implementation owned by the Runner."""

    async def handle(self, operation: RunnerOperationEnvelope) -> None:
        """Handle one operation and publish events through the operation envelope."""
        ...


Clock: TypeAlias = Callable[[], datetime]
Monotonic: TypeAlias = Callable[[], float]
OwnerKey: TypeAlias = str | None
_DEFAULT_MAX_CONCURRENT_OPERATIONS_PER_SESSION = 10
_DEFAULT_MAX_CONCURRENT_SYSTEM_OPERATIONS = 10
_DEFAULT_MAX_CONCURRENT_OPERATIONS = 50
_DEFAULT_MAX_PENDING_OPERATIONS_PER_OWNER = 100
_DEFAULT_MAX_PENDING_OPERATIONS = 1000
_DEFAULT_MAX_CONCURRENT_CONTROL_OPERATIONS = 4
_CONTROL_OPERATION_TYPES = frozenset({"process.terminate_session"})


@dataclasses.dataclass(frozen=True)
class _PendingOperation:
    operation: RunnerOperationEnvelope
    enqueued_at: float


@dataclasses.dataclass(frozen=True)
class _ActiveOperation:
    operation: RunnerOperationEnvelope
    owner: OwnerKey
    started_at: float


class RunnerRunLoop:
    """Runner process loop with fair Session-scoped operation scheduling."""

    def __init__(
        self,
        *,
        client: RunnerControlClient,
        operations: RuntimeRunnerOperations,
        registration: RunnerRegistration,
        connection_id: str,
        consumer_id: str,
        clock: Clock | None = None,
        monotonic: Monotonic | None = None,
        max_concurrent_operations_per_session: int = (
            _DEFAULT_MAX_CONCURRENT_OPERATIONS_PER_SESSION
        ),
        max_concurrent_system_operations: int = (
            _DEFAULT_MAX_CONCURRENT_SYSTEM_OPERATIONS
        ),
        max_concurrent_operations: int = _DEFAULT_MAX_CONCURRENT_OPERATIONS,
        max_pending_operations_per_owner: int = (
            _DEFAULT_MAX_PENDING_OPERATIONS_PER_OWNER
        ),
        max_pending_operations: int = _DEFAULT_MAX_PENDING_OPERATIONS,
        max_concurrent_control_operations: int = (
            _DEFAULT_MAX_CONCURRENT_CONTROL_OPERATIONS
        ),
    ) -> None:
        """Initialize the Runner run loop."""
        _validate_limits(
            max_concurrent_operations_per_session=(
                max_concurrent_operations_per_session
            ),
            max_concurrent_system_operations=max_concurrent_system_operations,
            max_concurrent_operations=max_concurrent_operations,
            max_pending_operations_per_owner=max_pending_operations_per_owner,
            max_pending_operations=max_pending_operations,
            max_concurrent_control_operations=max_concurrent_control_operations,
        )
        self._client = client
        self._operations = operations
        self._registration = registration
        self._connection_id = connection_id
        self._consumer_id = consumer_id
        self._clock = clock or _utc_now
        self._monotonic = monotonic or time.monotonic
        self._accepted: RunnerRegistrationAccepted | None = None
        self._last_heartbeat_at: float | None = None
        self._max_concurrent_operations_per_session = (
            max_concurrent_operations_per_session
        )
        self._max_concurrent_system_operations = max_concurrent_system_operations
        self._max_concurrent_operations = max_concurrent_operations
        self._max_pending_operations_per_owner = max_pending_operations_per_owner
        self._max_pending_operations = max_pending_operations
        self._max_concurrent_control_operations = max_concurrent_control_operations
        self._pending_by_owner: dict[OwnerKey, deque[_PendingOperation]] = {}
        self._owner_rotation: deque[OwnerKey] = deque()
        self._owners_in_rotation: set[OwnerKey] = set()
        self._pending_operation_count = 0
        self._active_by_owner: Counter[OwnerKey] = Counter()
        self._active_operation_tasks: dict[asyncio.Task[None], _ActiveOperation] = {}
        self._pending_control_operations: deque[_PendingOperation] = deque()
        self._active_control_tasks: dict[asyncio.Task[None], _ActiveOperation] = {}
        self._scheduler_wake = asyncio.Event()
        self._client.set_operation_handler(self._receive_operation)

    @property
    def accepted(self) -> RunnerRegistrationAccepted | None:
        """Return the accepted Runner registration, if startup completed."""
        return self._accepted

    async def start(self) -> RunnerRegistrationAccepted:
        """Register the Runner and publish an initial ready report."""
        accepted = await self._client.register_runner(
            self._registration,
            connection_id=self._connection_id,
            registered_at=self._clock(),
        )
        self._accepted = accepted
        _LOGGER.info(
            "Runtime Runner registered",
            extra={
                "runtime_id": accepted.runtime_id,
                "runner_id": accepted.runner_id,
                "connection_id": accepted.connection_id,
                "runner_generation": accepted.generation,
            },
        )
        await self._client.report_runner_state(
            RunnerStateReport(
                runtime_id=accepted.runtime_id,
                runner_id=accepted.runner_id,
                runner_generation=accepted.generation,
                runner_state=RuntimeRunnerState.READY,
                capabilities=self._registration.capabilities,
                active_operation_ids=(),
                health=self._registration.health,
                diagnostic={},
                workspace_path=self._registration.workspace_path,
                reported_at=self._clock(),
            )
        )
        return accepted

    async def run_once(self, *, block_ms: int = 500) -> bool:
        """Receive, admit, or schedule one unit of Runner work."""
        accepted = self._require_accepted()
        await self._heartbeat_if_due(accepted)
        self._reap_finished_operations()
        has_pending = bool(
            self._pending_operation_count or self._pending_control_operations
        )
        operation = await self._client.claim_next_runner_operation(
            runtime_id=accepted.runtime_id,
            generation=accepted.generation,
            consumer_id=self._consumer_id,
            block_ms=0 if has_pending else block_ms,
        )
        if operation is not None:
            await self._receive_operation(operation)
        control_scheduled = await self._schedule_pending_control_operation()
        operation_scheduled = await self._schedule_pending_operation()
        return operation is not None or control_scheduled or operation_scheduled

    async def _receive_operation(self, operation: RunnerOperationEnvelope) -> None:
        """Admit one operation delivered directly by the transport."""
        _LOGGER.info(
            "Runtime Runner operation claimed",
            extra=self._operation_log_extra(operation),
        )
        if operation.operation_type in _CONTROL_OPERATION_TYPES:
            if (
                len(self._pending_control_operations)
                >= self._max_pending_operations_per_owner
            ):
                await self._append_final_error(
                    operation,
                    error_code="operation_queue_full",
                    error_message="Runner control operation queue is full",
                )
            else:
                self._pending_control_operations.append(
                    _PendingOperation(operation, self._monotonic())
                )
        else:
            await self._admit_operation(operation)
        self._scheduler_wake.set()

    async def run_forever(self, *, block_ms: int = 500) -> None:
        """Run until cancelled."""
        if self._accepted is None:
            await self.start()
        try:
            while True:
                self._scheduler_wake.clear()
                progressed = await self.run_once(block_ms=0)
                if progressed:
                    await asyncio.sleep(0)
                    continue
                await self._wait_for_scheduler_wake(block_ms=block_ms)
        finally:
            await self._cancel_operations()

    async def _admit_operation(self, operation: RunnerOperationEnvelope) -> None:
        owner = operation.owner_session_id
        pending = self._pending_by_owner.get(owner)
        owner_pending_count = len(pending) if pending is not None else 0
        if (
            owner_pending_count >= self._max_pending_operations_per_owner
            or self._pending_operation_count >= self._max_pending_operations
        ):
            await self._append_final_error(
                operation,
                error_code="operation_queue_full",
                error_message="Runner operation queue is full",
            )
            _LOGGER.warning(
                "Runtime Runner operation rejected",
                extra={
                    **self._operation_log_extra(operation),
                    "error_code": "operation_queue_full",
                    "owner_pending_operations": owner_pending_count,
                    "runtime_pending_operations": self._pending_operation_count,
                },
            )
            return
        if pending is None:
            pending = deque()
            self._pending_by_owner[owner] = pending
        pending.append(_PendingOperation(operation, self._monotonic()))
        self._pending_operation_count += 1
        self._add_owner_to_rotation(owner)
        _LOGGER.info(
            "Runtime Runner operation admitted",
            extra={
                **self._operation_log_extra(operation),
                "owner_pending_operations": len(pending),
                "runtime_pending_operations": self._pending_operation_count,
            },
        )

    async def _schedule_pending_operation(self) -> bool:
        if len(self._active_operation_tasks) >= self._max_concurrent_operations:
            return False
        owner_count = len(self._owner_rotation)
        for _ in range(owner_count):
            owner = self._owner_rotation.popleft()
            pending = self._pending_by_owner.get(owner)
            if not pending:
                self._remove_empty_owner(owner)
                continue
            if self._active_by_owner[owner] >= self._owner_active_limit(owner):
                self._owner_rotation.append(owner)
                continue
            queued = pending.popleft()
            self._pending_operation_count -= 1
            if pending:
                self._owner_rotation.append(owner)
            else:
                self._remove_empty_owner(owner)
            if self._deadline_expired(queued.operation):
                await self._append_final_error(
                    queued.operation,
                    error_code="operation_timeout",
                    error_message="Runner operation deadline expired before execution",
                )
                _LOGGER.info(
                    "Runtime Runner pending operation expired",
                    extra=self._operation_log_extra(queued.operation),
                )
                return True
            if not await self._client.start_runner_operation(queued.operation):
                _LOGGER.info(
                    "Runtime Runner pending operation canceled before execution",
                    extra=self._operation_log_extra(queued.operation),
                )
                return True
            started_at = self._monotonic()
            task = asyncio.create_task(self._operations.handle(queued.operation))
            self._active_operation_tasks[task] = _ActiveOperation(
                queued.operation,
                owner,
                started_at,
            )
            self._active_by_owner[owner] += 1
            _LOGGER.info(
                "Runtime Runner operation scheduled",
                extra={
                    **self._operation_log_extra(queued.operation),
                    "queue_wait_ms": round((started_at - queued.enqueued_at) * 1000, 3),
                    "owner_active_operations": self._active_by_owner[owner],
                    "runtime_active_operations": len(self._active_operation_tasks),
                },
            )
            return True
        return False

    async def _schedule_pending_control_operation(self) -> bool:
        if not self._pending_control_operations:
            return False
        if len(self._active_control_tasks) >= self._max_concurrent_control_operations:
            return False
        queued = self._pending_control_operations.popleft()
        if self._deadline_expired(queued.operation):
            await self._append_final_error(
                queued.operation,
                error_code="operation_timeout",
                error_message=(
                    "Runner control operation deadline expired before execution"
                ),
            )
            return True
        if not await self._client.start_runner_operation(queued.operation):
            _LOGGER.info(
                "Runtime Runner pending control operation canceled before execution",
                extra=self._operation_log_extra(queued.operation),
            )
            return True
        started_at = self._monotonic()
        task = asyncio.create_task(self._operations.handle(queued.operation))
        self._active_control_tasks[task] = _ActiveOperation(
            queued.operation,
            queued.operation.owner_session_id,
            started_at,
        )
        _LOGGER.info(
            "Runtime Runner control operation scheduled",
            extra={
                **self._operation_log_extra(queued.operation),
                "queue_wait_ms": round((started_at - queued.enqueued_at) * 1000, 3),
                "control_active_operations": len(self._active_control_tasks),
            },
        )
        return True

    async def _wait_for_scheduler_wake(self, *, block_ms: int) -> None:
        wake_task = asyncio.create_task(self._scheduler_wake.wait())
        active_tasks = tuple(self._active_operation_tasks) + tuple(
            self._active_control_tasks
        )
        try:
            await asyncio.wait(
                (wake_task, *active_tasks),
                timeout=max(block_ms, 1) / 1000,
                return_when=asyncio.FIRST_COMPLETED,
            )
        finally:
            if not wake_task.done():
                wake_task.cancel()
            await asyncio.gather(wake_task, return_exceptions=True)

    async def _heartbeat_if_due(self, accepted: RunnerRegistrationAccepted) -> None:
        now = self._monotonic()
        heartbeat_interval = max(accepted.heartbeat_interval_seconds / 2, 1.0)
        if (
            self._last_heartbeat_at is not None
            and now - self._last_heartbeat_at < heartbeat_interval
        ):
            return
        ok = await self._client.heartbeat_runner(
            runtime_id=accepted.runtime_id,
            generation=accepted.generation,
            heartbeat_at=self._clock(),
        )
        if not ok:
            _LOGGER.warning(
                "Runtime Runner heartbeat rejected",
                extra={
                    "runtime_id": accepted.runtime_id,
                    "runner_id": accepted.runner_id,
                    "runner_generation": accepted.generation,
                },
            )
            raise RunnerConnectionRejected(
                f"Runner generation is stale: runtime={accepted.runtime_id}"
            )
        self._last_heartbeat_at = now

    def _reap_finished_operations(self) -> None:
        self._reap_task_set(self._active_operation_tasks, control=False)
        self._reap_task_set(self._active_control_tasks, control=True)

    def _reap_task_set(
        self,
        tasks: dict[asyncio.Task[None], _ActiveOperation],
        *,
        control: bool,
    ) -> None:
        for task in tuple(tasks):
            if not task.done():
                continue
            active = tasks.pop(task)
            if not control:
                self._active_by_owner[active.owner] -= 1
                if self._active_by_owner[active.owner] == 0:
                    del self._active_by_owner[active.owner]
            task.result()
            _LOGGER.info(
                "Runtime Runner operation finished",
                extra={
                    **self._operation_log_extra(active.operation),
                    "execution_ms": round(
                        (self._monotonic() - active.started_at) * 1000,
                        3,
                    ),
                    "runtime_active_operations": len(self._active_operation_tasks),
                    "control_operation": control,
                },
            )

    async def _append_final_error(
        self,
        operation: RunnerOperationEnvelope,
        *,
        error_code: str,
        error_message: str,
    ) -> None:
        await self._client.append_runner_event(
            RunnerOperationEvent(
                request_id=operation.request_id,
                runtime_id=operation.runtime_id,
                generation=operation.runner_generation,
                event_type=RuntimeRunnerEventType.FINAL_ERROR,
                payload={
                    "error_code": error_code,
                    "error_message": error_message,
                },
                created_at=self._clock(),
                final=True,
            )
        )

    def _deadline_expired(self, operation: RunnerOperationEnvelope) -> bool:
        return (
            operation.deadline_at is not None and self._clock() >= operation.deadline_at
        )

    def _owner_active_limit(self, owner: OwnerKey) -> int:
        if owner is None:
            return self._max_concurrent_system_operations
        return self._max_concurrent_operations_per_session

    def _add_owner_to_rotation(self, owner: OwnerKey) -> None:
        if owner in self._owners_in_rotation:
            return
        self._owner_rotation.append(owner)
        self._owners_in_rotation.add(owner)

    def _remove_empty_owner(self, owner: OwnerKey) -> None:
        self._owners_in_rotation.discard(owner)
        pending = self._pending_by_owner.get(owner)
        if pending is not None and not pending:
            del self._pending_by_owner[owner]

    def _operation_log_extra(
        self,
        operation: RunnerOperationEnvelope,
    ) -> dict[str, JsonValue]:
        return {
            "runtime_id": operation.runtime_id,
            "runner_generation": operation.runner_generation,
            "request_id": operation.request_id,
            "operation_type": operation.operation_type,
            "owner_session_id": operation.owner_session_id,
            "owner_class": (
                "session" if operation.owner_session_id is not None else "system"
            ),
        }

    async def _cancel_operations(self) -> None:
        tasks = tuple(self._active_operation_tasks) + tuple(self._active_control_tasks)
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        self._active_operation_tasks.clear()
        self._active_control_tasks.clear()
        self._active_by_owner.clear()
        self._pending_by_owner.clear()
        self._owner_rotation.clear()
        self._owners_in_rotation.clear()
        self._pending_operation_count = 0
        self._pending_control_operations.clear()

    def _require_accepted(self) -> RunnerRegistrationAccepted:
        if self._accepted is None:
            raise RuntimeError("RunnerRunLoop.start() must be called first")
        return self._accepted


def _validate_limits(
    *,
    max_concurrent_operations_per_session: int,
    max_concurrent_system_operations: int,
    max_concurrent_operations: int,
    max_pending_operations_per_owner: int,
    max_pending_operations: int,
    max_concurrent_control_operations: int,
) -> None:
    limits = {
        "max_concurrent_operations_per_session": (
            max_concurrent_operations_per_session
        ),
        "max_concurrent_system_operations": max_concurrent_system_operations,
        "max_concurrent_operations": max_concurrent_operations,
        "max_pending_operations_per_owner": max_pending_operations_per_owner,
        "max_pending_operations": max_pending_operations,
        "max_concurrent_control_operations": max_concurrent_control_operations,
    }
    for name, value in limits.items():
        if value <= 0:
            raise ValueError(f"{name} must be positive")
    if max_concurrent_operations_per_session > max_concurrent_operations:
        raise ValueError(
            "max_concurrent_operations_per_session must not exceed "
            "max_concurrent_operations"
        )
    if max_concurrent_system_operations > max_concurrent_operations:
        raise ValueError(
            "max_concurrent_system_operations must not exceed max_concurrent_operations"
        )
    if max_pending_operations_per_owner < max(
        max_concurrent_operations_per_session,
        max_concurrent_system_operations,
    ):
        raise ValueError(
            "max_pending_operations_per_owner must not be smaller than an owner "
            "concurrency limit"
        )
    if max_pending_operations < max_concurrent_operations:
        raise ValueError(
            "max_pending_operations must not be smaller than max_concurrent_operations"
        )
    if max_pending_operations_per_owner > max_pending_operations:
        raise ValueError(
            "max_pending_operations_per_owner must not exceed max_pending_operations"
        )


def _utc_now() -> datetime:
    return datetime.now(UTC)
