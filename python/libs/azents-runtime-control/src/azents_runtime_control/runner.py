"""Runner-side Agent Runtime Control contracts and run loop."""

import asyncio
import dataclasses
import enum
import logging
import time
from collections.abc import Callable, Mapping, Sequence
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


class RunnerControlClient(Protocol):
    """Transport implementation used by the Runtime Runner process."""

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
_DEFAULT_MAX_CONCURRENT_OPERATIONS = 4


class RunnerRunLoop:
    """Runner process loop over explicit Control client and operation handler."""

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
        max_concurrent_operations: int = _DEFAULT_MAX_CONCURRENT_OPERATIONS,
    ) -> None:
        """Initialize the Runner run loop."""
        if max_concurrent_operations <= 0:
            raise ValueError("max_concurrent_operations must be positive")
        self._client = client
        self._operations = operations
        self._registration = registration
        self._connection_id = connection_id
        self._consumer_id = consumer_id
        self._clock = clock or _utc_now
        self._monotonic = monotonic or time.monotonic
        self._accepted: RunnerRegistrationAccepted | None = None
        self._last_heartbeat_at: float | None = None
        self._max_concurrent_operations = max_concurrent_operations
        self._active_operation_tasks: dict[
            asyncio.Task[None], RunnerOperationEnvelope
        ] = {}

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
        """필요하면 heartbeat 하고 operation 하나를 schedule 합니다."""
        accepted = self._require_accepted()
        await self._heartbeat_if_due(accepted)
        self._reap_finished_operations()
        if len(self._active_operation_tasks) >= self._max_concurrent_operations:
            await self._wait_for_operation_capacity(block_ms=block_ms)
            return False
        operation = await self._client.claim_next_runner_operation(
            runtime_id=accepted.runtime_id,
            generation=accepted.generation,
            consumer_id=self._consumer_id,
            block_ms=block_ms,
        )
        if operation is None:
            return False
        _LOGGER.info(
            "Runtime Runner operation claimed",
            extra={
                "runtime_id": operation.runtime_id,
                "runner_generation": operation.runner_generation,
                "request_id": operation.request_id,
                "operation_type": operation.operation_type,
            },
        )
        task = asyncio.create_task(self._operations.handle(operation))
        self._active_operation_tasks[task] = operation
        return True

    async def run_forever(self, *, block_ms: int = 500) -> None:
        """취소될 때까지 Runner loop 를 실행합니다."""
        if self._accepted is None:
            await self.start()
        try:
            while True:
                await self.run_once(block_ms=block_ms)
                await asyncio.sleep(0)
        finally:
            await self._cancel_active_operations()

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
        for task in tuple(self._active_operation_tasks):
            if not task.done():
                continue
            operation = self._active_operation_tasks.pop(task)
            task.result()
            _LOGGER.info(
                "Runtime Runner operation finished",
                extra={
                    "runtime_id": operation.runtime_id,
                    "runner_generation": operation.runner_generation,
                    "request_id": operation.request_id,
                    "operation_type": operation.operation_type,
                },
            )

    async def _wait_for_operation_capacity(self, *, block_ms: int) -> None:
        if not self._active_operation_tasks:
            return
        timeout = max(block_ms, 1) / 1000
        await asyncio.wait(
            self._active_operation_tasks.keys(),
            timeout=timeout,
            return_when=asyncio.FIRST_COMPLETED,
        )
        self._reap_finished_operations()

    async def _cancel_active_operations(self) -> None:
        tasks = tuple(self._active_operation_tasks)
        if not tasks:
            return
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        self._active_operation_tasks.clear()

    def _require_accepted(self) -> RunnerRegistrationAccepted:
        if self._accepted is None:
            raise RuntimeError("RunnerRunLoop.start() must be called first")
        return self._accepted


def _utc_now() -> datetime:
    return datetime.now(UTC)
