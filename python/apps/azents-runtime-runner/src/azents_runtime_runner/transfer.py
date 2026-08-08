"""Runner-local bounded transfer execution and filesystem publication."""

import asyncio
import contextlib
import hashlib
import logging
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path, PurePath
from typing import Protocol, assert_never

import grpc
from azents_runtime_control.grpc_runner_transfer_client import (
    RunnerDownloadChunk,
    RunnerDownloadComplete,
    RunnerUploadComplete,
    RunnerUploadResult,
    runner_transfer_failure_from_grpc,
)
from azents_runtime_control.runner_transfer import (
    RunnerTransferCancel,
    RunnerTransferDirection,
    RunnerTransferFailure,
    RunnerTransferIdentity,
    RunnerTransferIntent,
    RunnerTransferOutcome,
    RunnerTransferResult,
)
from azents_runtime_control.transfer import (
    MAX_TRANSFER_CHUNK_BYTES,
    RUNNER_TRANSFER_CAPABILITY,
    RUNNER_TRANSFER_PROTOCOL_VERSION,
)

from azents_runtime_runner.contained_client import (
    ContainedOperationClient,
    ContainedOperationEvent,
)
from azents_runtime_runner.containment import ExecutionBackend

_BUFFER_BYTES = MAX_TRANSFER_CHUNK_BYTES
_DEFAULT_MAX_ACTIVE_TRANSFERS = 4
_DEFAULT_MAX_TOMBSTONES = 256
_LOGGER = logging.getLogger(__name__)


class RunnerTransferResultSink(Protocol):
    """Control stream subset used by local transfer tasks."""

    async def append_runner_transfer_result(
        self,
        result: RunnerTransferResult,
    ) -> None:
        """Append one bounded result."""
        ...


class RunnerTransferClient(Protocol):
    """Dedicated data-channel operations required by local transfer tasks."""

    def download(
        self,
        identity: RunnerTransferIdentity,
        *,
        timeout: float,
    ) -> AsyncIterator[RunnerDownloadChunk | RunnerDownloadComplete]:
        """Open one bounded server-streaming download."""
        ...

    async def upload(
        self,
        identity: RunnerTransferIdentity,
        frames: AsyncIterator[RunnerDownloadChunk | RunnerUploadComplete],
        *,
        timeout: float,
    ) -> RunnerUploadResult:
        """Open one bounded client-streaming upload."""
        ...


@dataclass
class _ActiveTransfer:
    intent: RunnerTransferIntent
    cancelled: asyncio.Event
    task: asyncio.Task[None]


@dataclass(frozen=True)
class _TransferTombstone:
    intent: RunnerTransferIntent
    result: RunnerTransferResult


@dataclass(frozen=True)
class _ContainedTransferChunk:
    offset: int
    data: bytes


@dataclass(frozen=True)
class _ContainedTransferSuccess:
    actual_size: int
    sha256: str
    destination_committed: bool


@dataclass(frozen=True)
class _ContainedTransferError:
    failure: RunnerTransferFailure
    reason: str


type _ContainedTransferResult = (
    _ContainedTransferChunk | _ContainedTransferSuccess | _ContainedTransferError
)


class RunnerTransferManager:
    """Isolate bounded transfer tasks from ordinary Runner operation scheduling."""

    def __init__(
        self,
        *,
        control: RunnerTransferResultSink,
        transfer: RunnerTransferClient,
        accepted_generation: Callable[[], int | None],
        execution_backend: ExecutionBackend,
        workspace_path: Path,
        max_active_transfers: int = _DEFAULT_MAX_ACTIVE_TRANSFERS,
        max_tombstones: int = _DEFAULT_MAX_TOMBSTONES,
    ) -> None:
        """Initialize independent data-task admission and result ownership."""
        if max_active_transfers <= 0 or max_tombstones <= 0:
            raise ValueError("Runner transfer limits must be positive")
        self._control = control
        self._transfer = transfer
        self._accepted_generation = accepted_generation
        self._contained_operations = ContainedOperationClient(
            backend=execution_backend,
            workspace_path=workspace_path,
        )
        self._max_active_transfers = max_active_transfers
        self._max_tombstones = max_tombstones
        self._active: dict[_TransferKey, _ActiveTransfer] = {}
        self._active_by_identity: dict[_TransferIdentityKey, _TransferKey] = {}
        self._tombstones: dict[_TransferKey, _TransferTombstone] = {}
        self._completed_by_identity: dict[_TransferIdentityKey, _TransferKey] = {}
        self._results: asyncio.Queue[RunnerTransferResult] = asyncio.Queue(
            maxsize=max_tombstones
        )
        self._result_task: asyncio.Task[None] | None = None
        self._lock = asyncio.Lock()
        self._closed = False

    async def start(self) -> None:
        """Start bounded transfer-result publishing."""
        self._ensure_result_task()

    async def handle_intent(self, intent: RunnerTransferIntent) -> None:
        """Validate and admit one intent without awaiting its transfer task."""
        key = _key(intent)
        identity_key = _identity_key(intent)
        invalid_reason = _validate_intent_reason(
            intent,
            self._accepted_generation(),
        )
        result: RunnerTransferResult | None = None
        failure_reason: str | None = None
        async with self._lock:
            active_key = self._active_by_identity.get(identity_key)
            completed_key = self._completed_by_identity.get(identity_key)
            if active_key is not None:
                active = self._active[active_key]
                if active_key != key or active.intent != intent:
                    result = _failed(intent, RunnerTransferFailure.PROTOCOL_VIOLATION)
                    failure_reason = "active_identity_conflict"
            elif completed_key is not None:
                prior = self._tombstones[completed_key]
                if completed_key == key and prior.intent == intent:
                    result = prior.result
                else:
                    result = _failed(intent, RunnerTransferFailure.PROTOCOL_VIOLATION)
                    failure_reason = "completed_identity_conflict"
            elif invalid_reason is not None:
                result = _failed(intent, RunnerTransferFailure.PROTOCOL_VIOLATION)
                failure_reason = invalid_reason
                self._remember(intent, result)
            elif self._closed or len(self._active) >= self._max_active_transfers:
                result = _failed(intent, RunnerTransferFailure.RESOURCE_EXHAUSTED)
                failure_reason = (
                    "transfer_manager_closed"
                    if self._closed
                    else "active_transfer_capacity_exhausted"
                )
                self._remember(intent, result)
            else:
                cancelled = asyncio.Event()
                task = asyncio.create_task(self._run(intent, cancelled))
                self._active[key] = _ActiveTransfer(intent, cancelled, task)
                self._active_by_identity[identity_key] = key
                task.add_done_callback(lambda _: asyncio.create_task(self._reap(key)))
        if result is not None:
            if failure_reason is not None:
                _log_failure(
                    intent,
                    result,
                    source="intent_admission",
                    reason=failure_reason,
                    grpc_status=None,
                )
            await self._enqueue_result(result)

    async def handle_cancel(self, cancel: RunnerTransferCancel) -> None:
        """Cancel only the exact active transfer identity and dispatch."""
        async with self._lock:
            for active in self._active.values():
                if (
                    active.intent.operation_id == cancel.operation_id
                    and active.intent.dispatch_id == cancel.dispatch_id
                    and active.intent.identity == cancel.identity
                ):
                    active.cancelled.set()
                    active.task.cancel()
                    return

    async def close(self) -> None:
        """Cancel active tasks before the separately owned data client closes."""
        async with self._lock:
            self._closed = True
            active = tuple(self._active.values())
            result_task = self._result_task
            self._result_task = None
            for item in active:
                item.cancelled.set()
                item.task.cancel()
            if result_task is not None:
                result_task.cancel()
        for item in active:
            with contextlib.suppress(asyncio.CancelledError):
                await item.task
        if result_task is not None:
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await result_task

    async def _reap(self, key: "_TransferKey") -> None:
        async with self._lock:
            active = self._active.pop(key, None)
            if active is not None:
                self._active_by_identity.pop(_identity_key(active.intent), None)

    async def _run(
        self, intent: RunnerTransferIntent, cancelled: asyncio.Event
    ) -> None:
        result: RunnerTransferResult | None = None
        try:
            try:
                if intent.direction is RunnerTransferDirection.DOWNLOAD:
                    result = await self._download(intent, cancelled)
                else:
                    result = await self._upload(intent, cancelled)
            except grpc.aio.AioRpcError as exc:
                result = _failed(intent, runner_transfer_failure_from_grpc(exc))
                _log_failure(
                    intent,
                    result,
                    source="grpc",
                    reason=exc.details() or "gRPC error without details",
                    grpc_status=exc.code().name,
                )
            except _TransferFailure as exc:
                result = _failed(intent, exc.failure)
                _log_failure(
                    intent,
                    result,
                    source="runner",
                    reason=exc.reason,
                    grpc_status=None,
                )
            except OSError:
                result = _failed(intent, _local_io_failure(intent))
                _log_failure(
                    intent,
                    result,
                    source="local_io",
                    reason="os_error",
                    grpc_status=None,
                )
            except ValueError:
                result = _failed(intent, RunnerTransferFailure.PROTOCOL_VIOLATION)
                _log_failure(
                    intent,
                    result,
                    source="runner",
                    reason="unexpected_value_error",
                    grpc_status=None,
                )
            self._remember(intent, result)
            await self._enqueue_terminal_result(result)
        except asyncio.CancelledError:
            if result is None:
                result = _cancelled(intent)
                self._remember(intent, result)
                if not self._closed:
                    await self._enqueue_terminal_result(result)
            raise

    async def _download(
        self,
        intent: RunnerTransferIntent,
        cancelled: asyncio.Event,
    ) -> RunnerTransferResult:
        expected_sha256 = intent.expected_sha256
        overwrite = intent.overwrite
        expected_size = intent.expected_size
        if expected_sha256 is None or overwrite is None or expected_size is None:
            raise _TransferFailure(
                RunnerTransferFailure.PROTOCOL_VIOLATION,
                reason="download_manifest_missing",
            )
        offset = 0
        digest = hashlib.sha256()
        complete: RunnerDownloadComplete | None = None
        terminal: _ContainedTransferSuccess | None = None

        async def chunks() -> AsyncIterator[bytes]:
            nonlocal offset, complete
            async for frame in self._transfer.download(
                intent.identity,
                timeout=_remaining_timeout(intent),
            ):
                _check_stop(intent, cancelled)
                if isinstance(frame, RunnerDownloadComplete):
                    if complete is not None:
                        raise _TransferFailure(
                            RunnerTransferFailure.PROTOCOL_VIOLATION,
                            reason="download_duplicate_completion",
                        )
                    complete = frame
                    continue
                if (
                    complete is not None
                    or not frame.data
                    or len(frame.data) > _BUFFER_BYTES
                ):
                    raise _TransferFailure(
                        RunnerTransferFailure.PROTOCOL_VIOLATION,
                        reason="download_chunk_invalid",
                    )
                if frame.offset != offset or offset + len(frame.data) > expected_size:
                    raise _TransferFailure(
                        RunnerTransferFailure.INTEGRITY_FAILED,
                        reason="download_chunk_integrity_mismatch",
                    )
                digest.update(frame.data)
                offset += len(frame.data)
                yield frame.data
            if (
                complete is None
                or offset != expected_size
                or complete.actual_size != offset
                or complete.sha256 != digest.hexdigest()
                or digest.hexdigest() != expected_sha256
            ):
                raise _TransferFailure(
                    RunnerTransferFailure.INTEGRITY_FAILED,
                    reason="download_manifest_mismatch",
                )

        async def handle_event(event: ContainedOperationEvent) -> None:
            nonlocal terminal
            result = _decode_contained_transfer_result(event)
            if isinstance(result, _ContainedTransferError):
                raise _TransferFailure(result.failure, reason=result.reason)
            if not isinstance(result, _ContainedTransferSuccess):
                raise _TransferFailure(
                    RunnerTransferFailure.PROTOCOL_VIOLATION,
                    reason="download_helper_event_invalid",
                )
            terminal = result

        await self._contained_operations.run_streaming_input(
            operation="transfer.download",
            payload={
                "runtime_path": intent.runtime_path,
                "expected_size": expected_size,
                "expected_sha256": expected_sha256,
                "overwrite": overwrite,
            },
            input_chunks=chunks(),
            completion_factory=lambda: {
                "actual_size": offset,
                "sha256": digest.hexdigest(),
            },
            deadline_at=intent.deadline_at,
            event_handler=handle_event,
        )
        if (
            terminal is None
            or terminal.actual_size != offset
            or terminal.sha256 != digest.hexdigest()
            or terminal.destination_committed is not True
        ):
            raise _TransferFailure(
                RunnerTransferFailure.INTEGRITY_FAILED,
                reason="download_helper_manifest_mismatch",
            )
        return RunnerTransferResult(
            identity=intent.identity,
            operation_id=intent.operation_id,
            dispatch_id=intent.dispatch_id,
            direction=intent.direction,
            outcome=RunnerTransferOutcome.SUCCEEDED,
            actual_size=offset,
            sha256=digest.hexdigest(),
            destination_committed=True,
            failure=None,
        )

    async def _upload(
        self,
        intent: RunnerTransferIntent,
        cancelled: asyncio.Event,
    ) -> RunnerTransferResult:
        expected_size = intent.expected_size
        if expected_size is None:
            raise _TransferFailure(
                RunnerTransferFailure.PROTOCOL_VIOLATION,
                reason="upload_expected_size_missing",
            )
        events: asyncio.Queue[_ContainedTransferResult] = asyncio.Queue(maxsize=2)

        async def handle_event(event: ContainedOperationEvent) -> None:
            await events.put(_decode_contained_transfer_result(event))

        helper_task = asyncio.create_task(
            self._contained_operations.run(
                operation="transfer.upload",
                payload={
                    "runtime_path": intent.runtime_path,
                    "expected_size": expected_size,
                    "expected_sha256": intent.expected_sha256,
                },
                body_chunks=(),
                deadline_at=intent.deadline_at,
                event_handler=handle_event,
            )
        )
        helper_manifest: _ContainedTransferSuccess | None = None

        async def frames() -> AsyncIterator[RunnerDownloadChunk | RunnerUploadComplete]:
            nonlocal helper_manifest
            offset = 0
            while True:
                _check_stop(intent, cancelled)
                event = await events.get()
                try:
                    match event:
                        case _ContainedTransferChunk():
                            if (
                                event.offset != offset
                                or not event.data
                                or len(event.data) > _BUFFER_BYTES
                            ):
                                raise _TransferFailure(
                                    RunnerTransferFailure.PROTOCOL_VIOLATION,
                                    reason="upload_helper_chunk_invalid",
                                )
                            yield RunnerDownloadChunk(offset=offset, data=event.data)
                            offset += len(event.data)
                            continue
                        case _ContainedTransferError():
                            raise _TransferFailure(
                                event.failure,
                                reason=event.reason,
                            )
                        case _ContainedTransferSuccess():
                            helper_manifest = event
                            if (
                                event.actual_size != offset
                                or event.actual_size != expected_size
                                or event.destination_committed
                            ):
                                raise _TransferFailure(
                                    RunnerTransferFailure.INTEGRITY_FAILED,
                                    reason="upload_helper_manifest_mismatch",
                                )
                            yield RunnerUploadComplete(
                                actual_size=event.actual_size,
                                sha256=event.sha256,
                            )
                            return
                        case _ as unreachable:
                            assert_never(unreachable)
                finally:
                    events.task_done()

        try:
            authoritative = await self._transfer.upload(
                intent.identity,
                frames(),
                timeout=_remaining_timeout(intent),
            )
            await helper_task
        except BaseException:
            if not helper_task.done():
                helper_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await helper_task
            raise
        if (
            helper_manifest is None
            or authoritative.actual_size != helper_manifest.actual_size
            or authoritative.sha256 != helper_manifest.sha256
        ):
            raise _TransferFailure(
                RunnerTransferFailure.INTEGRITY_FAILED,
                reason="upload_authoritative_manifest_mismatch",
            )
        return RunnerTransferResult(
            identity=intent.identity,
            operation_id=intent.operation_id,
            dispatch_id=intent.dispatch_id,
            direction=intent.direction,
            outcome=RunnerTransferOutcome.SUCCEEDED,
            actual_size=authoritative.actual_size,
            sha256=authoritative.sha256,
            destination_committed=False,
            failure=None,
        )

    async def _enqueue_result(self, result: RunnerTransferResult) -> None:
        if self._closed:
            return
        self._ensure_result_task()
        await self._results.put(result)

    async def _enqueue_terminal_result(self, result: RunnerTransferResult) -> None:
        enqueue = asyncio.create_task(self._enqueue_result(result))
        cancelled = False
        try:
            while True:
                try:
                    await asyncio.shield(enqueue)
                    break
                except asyncio.CancelledError:
                    if self._closed:
                        enqueue.cancel()
                        with contextlib.suppress(asyncio.CancelledError):
                            await enqueue
                        raise
                    cancelled = True
        finally:
            if not enqueue.done():
                enqueue.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await enqueue
        if cancelled:
            raise asyncio.CancelledError

    def _ensure_result_task(self) -> None:
        if self._result_task is None:
            self._result_task = asyncio.create_task(self._emit_results())

    async def _emit_results(self) -> None:
        while True:
            result = await self._results.get()
            try:
                await self._control.append_runner_transfer_result(result)
            except Exception:
                _LOGGER.warning(
                    "Runner transfer result delivery became unavailable",
                    exc_info=True,
                )
            finally:
                self._results.task_done()

    def _remember(
        self,
        intent: RunnerTransferIntent,
        result: RunnerTransferResult,
    ) -> None:
        key = _key(intent)
        identity_key = _identity_key(intent)
        self._tombstones[key] = _TransferTombstone(intent, result)
        self._completed_by_identity[identity_key] = key
        while len(self._tombstones) > self._max_tombstones:
            evicted_key = next(iter(self._tombstones))
            self._tombstones.pop(evicted_key)
            evicted_identity = _identity_key_from_key(evicted_key)
            if self._completed_by_identity.get(evicted_identity) == evicted_key:
                self._completed_by_identity.pop(evicted_identity)


@dataclass(frozen=True)
class _TransferKey:
    transfer_id: str
    attempt_id: str
    runtime_id: str
    generation: int
    operation_id: str
    dispatch_id: str
    direction: RunnerTransferDirection


@dataclass(frozen=True)
class _TransferIdentityKey:
    transfer_id: str
    attempt_id: str
    runtime_id: str
    generation: int


class _TransferFailure(Exception):
    def __init__(self, failure: RunnerTransferFailure, *, reason: str) -> None:
        self.failure = failure
        self.reason = reason


def _decode_contained_transfer_result(
    event: ContainedOperationEvent,
) -> _ContainedTransferResult:
    payload = event.payload
    if event.event_type == "file_chunk":
        offset = payload.get("offset")
        if (
            event.final
            or event.binary is None
            or set(payload) != {"offset"}
            or not isinstance(offset, int)
            or isinstance(offset, bool)
            or offset < 0
        ):
            return _invalid_contained_transfer_result("upload_helper_chunk_invalid")
        return _ContainedTransferChunk(offset=offset, data=event.binary)
    if event.event_type == "final_success":
        actual_size = payload.get("actual_size")
        sha256 = payload.get("sha256")
        destination_committed = payload.get("destination_committed")
        if (
            not event.final
            or event.binary is not None
            or set(payload) != {"actual_size", "sha256", "destination_committed"}
            or not isinstance(actual_size, int)
            or isinstance(actual_size, bool)
            or actual_size < 0
            or not isinstance(sha256, str)
            or not isinstance(destination_committed, bool)
        ):
            return _invalid_contained_transfer_result(
                "contained_transfer_success_invalid"
            )
        return _ContainedTransferSuccess(
            actual_size=actual_size,
            sha256=sha256,
            destination_committed=destination_committed,
        )
    if event.event_type == "final_error":
        error_code = payload.get("error_code")
        value = payload.get("transfer_failure")
        reason = payload.get("error_message")
        if (
            not event.final
            or event.binary is not None
            or set(payload) != {"error_code", "error_message", "transfer_failure"}
            or error_code != "TRANSFER_FAILED"
            or not isinstance(value, str)
            or not isinstance(reason, str)
        ):
            return _invalid_contained_transfer_result(
                "contained_transfer_failure_invalid"
            )
        try:
            failure = RunnerTransferFailure(value)
        except ValueError:
            return _invalid_contained_transfer_result(
                "contained_transfer_failure_invalid"
            )
        return _ContainedTransferError(failure=failure, reason=reason)
    return _invalid_contained_transfer_result("contained_transfer_event_invalid")


def _invalid_contained_transfer_result(reason: str) -> _ContainedTransferError:
    return _ContainedTransferError(
        failure=RunnerTransferFailure.PROTOCOL_VIOLATION,
        reason=reason,
    )


def _key(intent: RunnerTransferIntent) -> _TransferKey:
    return _TransferKey(
        intent.identity.transfer_id,
        intent.identity.attempt_id,
        intent.identity.runtime_id,
        intent.identity.runner_generation,
        intent.operation_id,
        intent.dispatch_id,
        intent.direction,
    )


def _identity_key(intent: RunnerTransferIntent) -> _TransferIdentityKey:
    return _TransferIdentityKey(
        intent.identity.transfer_id,
        intent.identity.attempt_id,
        intent.identity.runtime_id,
        intent.identity.runner_generation,
    )


def _identity_key_from_key(key: _TransferKey) -> _TransferIdentityKey:
    return _TransferIdentityKey(
        key.transfer_id,
        key.attempt_id,
        key.runtime_id,
        key.generation,
    )


def _validate_intent_reason(
    intent: RunnerTransferIntent,
    accepted_generation: int | None,
) -> str | None:
    if accepted_generation != intent.identity.runner_generation:
        return "runner_generation_mismatch"
    if intent.protocol_version != RUNNER_TRANSFER_PROTOCOL_VERSION:
        return "protocol_version_mismatch"
    if intent.capability != RUNNER_TRANSFER_CAPABILITY:
        return "capability_mismatch"
    if intent.overwrite is None:
        return "overwrite_missing"
    if intent.expected_size is None:
        return "expected_size_missing"
    if intent.expected_size < 0:
        return "expected_size_negative"
    if intent.deadline_at <= datetime.now(UTC):
        return "deadline_expired"
    if not PurePath(intent.runtime_path).is_absolute():
        return "runtime_path_not_absolute"
    if not all(
        _valid_identifier(value)
        for value in (
            intent.identity.transfer_id,
            intent.identity.attempt_id,
            intent.identity.runtime_id,
            intent.operation_id,
            intent.dispatch_id,
        )
    ):
        return "identifier_invalid"
    if (
        intent.direction is RunnerTransferDirection.DOWNLOAD
        and intent.expected_sha256 is None
    ):
        return "download_sha256_missing"
    return None


def _valid_identifier(value: str) -> bool:
    try:
        size = len(value.encode())
    except UnicodeEncodeError:
        return False
    return 1 <= size <= 128


def _failed(
    intent: RunnerTransferIntent, failure: RunnerTransferFailure
) -> RunnerTransferResult:
    if failure is RunnerTransferFailure.CANCELLED:
        return _cancelled(intent)
    return RunnerTransferResult(
        identity=intent.identity,
        operation_id=intent.operation_id,
        dispatch_id=intent.dispatch_id,
        direction=intent.direction,
        outcome=RunnerTransferOutcome.FAILED,
        actual_size=None,
        sha256=None,
        destination_committed=False,
        failure=failure,
    )


def _cancelled(intent: RunnerTransferIntent) -> RunnerTransferResult:
    return RunnerTransferResult(
        identity=intent.identity,
        operation_id=intent.operation_id,
        dispatch_id=intent.dispatch_id,
        direction=intent.direction,
        outcome=RunnerTransferOutcome.CANCELLED,
        actual_size=None,
        sha256=None,
        destination_committed=False,
        failure=RunnerTransferFailure.CANCELLED,
    )


def _check_stop(intent: RunnerTransferIntent, cancelled: asyncio.Event) -> None:
    if cancelled.is_set():
        raise _TransferFailure(
            RunnerTransferFailure.CANCELLED,
            reason="cancellation_requested",
        )
    if datetime.now(UTC) >= intent.deadline_at:
        raise _TransferFailure(
            RunnerTransferFailure.DEADLINE_EXCEEDED,
            reason="deadline_exceeded",
        )


def _remaining_timeout(intent: RunnerTransferIntent) -> float:
    remaining = (intent.deadline_at - datetime.now(UTC)).total_seconds()
    if remaining <= 0:
        raise _TransferFailure(
            RunnerTransferFailure.DEADLINE_EXCEEDED,
            reason="deadline_exceeded",
        )
    return remaining


def _local_io_failure(intent: RunnerTransferIntent) -> RunnerTransferFailure:
    if intent.direction is RunnerTransferDirection.DOWNLOAD:
        return RunnerTransferFailure.DESTINATION_FAILED
    return RunnerTransferFailure.INTEGRITY_FAILED


def _log_failure(
    intent: RunnerTransferIntent,
    result: RunnerTransferResult,
    *,
    source: str,
    reason: str,
    grpc_status: str | None,
) -> None:
    _LOGGER.warning(
        "Runtime Runner transfer failed",
        extra={
            "transfer_id": intent.identity.transfer_id,
            "attempt_id": intent.identity.attempt_id,
            "runtime_id": intent.identity.runtime_id,
            "runner_generation": intent.identity.runner_generation,
            "operation_id": intent.operation_id,
            "dispatch_id": intent.dispatch_id,
            "direction": intent.direction.value,
            "runner_outcome": result.outcome.value,
            "runner_failure": (
                None if result.failure is None else result.failure.value
            ),
            "failure_source": source,
            "failure_reason": reason,
            "grpc_status": grpc_status,
        },
    )
