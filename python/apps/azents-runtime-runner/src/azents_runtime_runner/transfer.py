"""Runner-local bounded transfer execution and filesystem publication."""

import asyncio
import contextlib
import hashlib
import logging
import os
import secrets
import stat
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import PurePath
from typing import Protocol

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


@dataclass(frozen=True)
class _FileIdentity:
    device: int
    inode: int
    size: int
    mtime_ns: int
    ctime_ns: int


@dataclass
class _ActiveTransfer:
    intent: RunnerTransferIntent
    cancelled: asyncio.Event
    task: asyncio.Task[None]


@dataclass(frozen=True)
class _TransferTombstone:
    intent: RunnerTransferIntent
    result: RunnerTransferResult


class RunnerTransferManager:
    """Isolate bounded transfer tasks from ordinary Runner operation scheduling."""

    def __init__(
        self,
        *,
        control: RunnerTransferResultSink,
        transfer: RunnerTransferClient,
        accepted_generation: Callable[[], int | None],
        max_active_transfers: int = _DEFAULT_MAX_ACTIVE_TRANSFERS,
        max_tombstones: int = _DEFAULT_MAX_TOMBSTONES,
    ) -> None:
        """Initialize independent data-task admission and result ownership."""
        if max_active_transfers <= 0 or max_tombstones <= 0:
            raise ValueError("Runner transfer limits must be positive")
        self._control = control
        self._transfer = transfer
        self._accepted_generation = accepted_generation
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
        self._commit_lock = asyncio.Lock()
        self._closed = False

    async def start(self) -> None:
        """Start bounded transfer-result publishing."""
        self._ensure_result_task()

    async def handle_intent(self, intent: RunnerTransferIntent) -> None:
        """Validate and admit one intent without awaiting its transfer task."""
        key = _key(intent)
        identity_key = _identity_key(intent)
        invalid = _validate_intent(intent, self._accepted_generation())
        result: RunnerTransferResult | None = None
        async with self._lock:
            active_key = self._active_by_identity.get(identity_key)
            completed_key = self._completed_by_identity.get(identity_key)
            if active_key is not None:
                active = self._active[active_key]
                if active_key != key or active.intent != intent:
                    result = _failed(intent, RunnerTransferFailure.PROTOCOL_VIOLATION)
            elif completed_key is not None:
                prior = self._tombstones[completed_key]
                if completed_key == key and prior.intent == intent:
                    result = prior.result
                else:
                    result = _failed(intent, RunnerTransferFailure.PROTOCOL_VIOLATION)
            elif invalid is not None:
                result = _failed(intent, invalid)
                self._remember(intent, result)
            elif self._closed or len(self._active) >= self._max_active_transfers:
                result = _failed(intent, RunnerTransferFailure.RESOURCE_EXHAUSTED)
                self._remember(intent, result)
            else:
                cancelled = asyncio.Event()
                task = asyncio.create_task(self._run(intent, cancelled))
                self._active[key] = _ActiveTransfer(intent, cancelled, task)
                self._active_by_identity[identity_key] = key
                task.add_done_callback(lambda _: asyncio.create_task(self._reap(key)))
        if result is not None:
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
            except _TransferFailure as exc:
                result = _failed(intent, exc.failure)
            except OSError:
                result = _failed(intent, _local_io_failure(intent))
            except ValueError:
                result = _failed(intent, RunnerTransferFailure.PROTOCOL_VIOLATION)
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
            raise _TransferFailure(RunnerTransferFailure.PROTOCOL_VIOLATION)
        parent_fd, destination_name = _open_parent(intent.runtime_path, create=True)
        stage_fd: int | None = None
        stage_name: str | None = None
        try:
            stage_fd, stage_name = _open_temporary_file(parent_fd)
            offset = 0
            digest = hashlib.sha256()
            complete: RunnerDownloadComplete | None = None
            async for frame in self._transfer.download(
                intent.identity,
                timeout=_remaining_timeout(intent),
            ):
                _check_stop(intent, cancelled)
                if isinstance(frame, RunnerDownloadComplete):
                    if complete is not None:
                        raise _TransferFailure(RunnerTransferFailure.PROTOCOL_VIOLATION)
                    complete = frame
                    continue
                if (
                    complete is not None
                    or not frame.data
                    or len(frame.data) > _BUFFER_BYTES
                ):
                    raise _TransferFailure(RunnerTransferFailure.PROTOCOL_VIOLATION)
                if frame.offset != offset or offset + len(frame.data) > expected_size:
                    raise _TransferFailure(RunnerTransferFailure.INTEGRITY_FAILED)
                await asyncio.to_thread(_write_all, stage_fd, frame.data)
                digest.update(frame.data)
                offset += len(frame.data)
            if (
                complete is None
                or offset != expected_size
                or complete.actual_size != offset
                or complete.sha256 != digest.hexdigest()
                or digest.hexdigest() != expected_sha256
            ):
                raise _TransferFailure(RunnerTransferFailure.INTEGRITY_FAILED)
            await asyncio.to_thread(os.fsync, stage_fd)
            assert stage_fd is not None
            async with self._commit_lock:
                _check_stop(intent, cancelled)
                if overwrite:
                    assert stage_name is not None
                    os.replace(
                        stage_name,
                        destination_name,
                        src_dir_fd=parent_fd,
                        dst_dir_fd=parent_fd,
                    )
                    stage_name = None
                else:
                    assert stage_name is not None
                    _assert_empty_destination(parent_fd, destination_name)
                    os.link(
                        stage_name,
                        destination_name,
                        src_dir_fd=parent_fd,
                        dst_dir_fd=parent_fd,
                        follow_symlinks=False,
                    )
                    os.unlink(stage_name, dir_fd=parent_fd)
                    stage_name = None
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
        finally:
            if stage_name is not None:
                with contextlib.suppress(FileNotFoundError):
                    os.unlink(stage_name, dir_fd=parent_fd)
            if stage_fd is not None:
                os.close(stage_fd)
            os.close(parent_fd)

    async def _upload(
        self,
        intent: RunnerTransferIntent,
        cancelled: asyncio.Event,
    ) -> RunnerTransferResult:
        expected_size = intent.expected_size
        if expected_size is None:
            raise _TransferFailure(RunnerTransferFailure.PROTOCOL_VIOLATION)
        parent_fd, source_name = _open_parent(intent.runtime_path, create=False)
        source_fd: int | None = None
        snapshot_fd: int | None = None
        snapshot_name: str | None = None
        try:
            source_fd = os.open(
                source_name,
                os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK,
                dir_fd=parent_fd,
            )
            before = _regular_identity(os.fstat(source_fd))
            if before.size != expected_size:
                raise _TransferFailure(RunnerTransferFailure.INTEGRITY_FAILED)
            snapshot_fd, snapshot_name = _open_temporary_file(parent_fd)
            digest = hashlib.sha256()
            copied = 0
            while True:
                _check_stop(intent, cancelled)
                chunk = await asyncio.to_thread(os.read, source_fd, _BUFFER_BYTES)
                if not chunk:
                    break
                copied += len(chunk)
                if copied > expected_size:
                    raise _TransferFailure(RunnerTransferFailure.INTEGRITY_FAILED)
                await asyncio.to_thread(_write_all, snapshot_fd, chunk)
                digest.update(chunk)
            await asyncio.to_thread(os.fsync, snapshot_fd)
            after_fd = _regular_identity(os.fstat(source_fd))
            after_path = _regular_identity(
                os.stat(source_name, dir_fd=parent_fd, follow_symlinks=False)
            )
            if before != after_fd or before != after_path or copied != expected_size:
                raise _TransferFailure(RunnerTransferFailure.INTEGRITY_FAILED)
            actual_sha256 = digest.hexdigest()
            if (
                intent.expected_sha256 is not None
                and actual_sha256 != intent.expected_sha256
            ):
                raise _TransferFailure(RunnerTransferFailure.INTEGRITY_FAILED)
            assert snapshot_fd is not None

            async def frames() -> AsyncIterator[
                RunnerDownloadChunk | RunnerUploadComplete
            ]:
                snapshot_read = os.dup(snapshot_fd)
                try:
                    os.lseek(snapshot_read, 0, os.SEEK_SET)
                    offset = 0
                    while True:
                        _check_stop(intent, cancelled)
                        chunk = await asyncio.to_thread(
                            os.read,
                            snapshot_read,
                            _BUFFER_BYTES,
                        )
                        if not chunk:
                            break
                        yield RunnerDownloadChunk(offset=offset, data=chunk)
                        offset += len(chunk)
                    yield RunnerUploadComplete(actual_size=offset, sha256=actual_sha256)
                finally:
                    os.close(snapshot_read)

            authoritative = await self._transfer.upload(
                intent.identity,
                frames(),
                timeout=_remaining_timeout(intent),
            )
            if (
                authoritative.actual_size != copied
                or authoritative.sha256 != actual_sha256
            ):
                raise _TransferFailure(RunnerTransferFailure.INTEGRITY_FAILED)
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
        finally:
            if snapshot_name is not None:
                with contextlib.suppress(FileNotFoundError):
                    os.unlink(snapshot_name, dir_fd=parent_fd)
            if source_fd is not None:
                os.close(source_fd)
            if snapshot_fd is not None:
                os.close(snapshot_fd)
            os.close(parent_fd)

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
    def __init__(self, failure: RunnerTransferFailure) -> None:
        self.failure = failure


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


def _validate_intent(
    intent: RunnerTransferIntent,
    accepted_generation: int | None,
) -> RunnerTransferFailure | None:
    if (
        accepted_generation != intent.identity.runner_generation
        or intent.protocol_version != RUNNER_TRANSFER_PROTOCOL_VERSION
        or intent.capability != RUNNER_TRANSFER_CAPABILITY
        or intent.overwrite is None
        or intent.expected_size is None
        or intent.expected_size < 0
        or intent.deadline_at <= datetime.now(UTC)
        or not PurePath(intent.runtime_path).is_absolute()
        or not all(
            _valid_identifier(value)
            for value in (
                intent.identity.transfer_id,
                intent.identity.attempt_id,
                intent.identity.runtime_id,
                intent.operation_id,
                intent.dispatch_id,
            )
        )
    ):
        return RunnerTransferFailure.PROTOCOL_VIOLATION
    if (
        intent.direction is RunnerTransferDirection.DOWNLOAD
        and intent.expected_sha256 is None
    ):
        return RunnerTransferFailure.PROTOCOL_VIOLATION
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
        raise _TransferFailure(RunnerTransferFailure.CANCELLED)
    if datetime.now(UTC) >= intent.deadline_at:
        raise _TransferFailure(RunnerTransferFailure.DEADLINE_EXCEEDED)


def _remaining_timeout(intent: RunnerTransferIntent) -> float:
    remaining = (intent.deadline_at - datetime.now(UTC)).total_seconds()
    if remaining <= 0:
        raise _TransferFailure(RunnerTransferFailure.DEADLINE_EXCEEDED)
    return remaining


def _open_parent(path: str, *, create: bool) -> tuple[int, str]:
    candidate = PurePath(path)
    if (
        not candidate.is_absolute()
        or not candidate.name
        or candidate.name in {".", ".."}
    ):
        raise _TransferFailure(RunnerTransferFailure.PROTOCOL_VIOLATION)
    parent_fd = os.open("/", os.O_RDONLY | os.O_DIRECTORY)
    try:
        components = candidate.parts[1:-1]
        for component in components:
            if component in {".", ".."}:
                raise _TransferFailure(RunnerTransferFailure.PROTOCOL_VIOLATION)
            try:
                next_fd = os.open(
                    component,
                    os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
                    dir_fd=parent_fd,
                )
            except FileNotFoundError:
                if not create:
                    raise
                try:
                    os.mkdir(component, 0o700, dir_fd=parent_fd)
                except FileExistsError:
                    pass
                next_fd = os.open(
                    component,
                    os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
                    dir_fd=parent_fd,
                )
            os.close(parent_fd)
            parent_fd = next_fd
        return parent_fd, candidate.name
    except BaseException:
        os.close(parent_fd)
        raise


def _assert_empty_destination(parent_fd: int, name: str) -> None:
    try:
        os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
    except FileNotFoundError:
        return
    raise _TransferFailure(RunnerTransferFailure.DESTINATION_FAILED)


def _regular_identity(value: os.stat_result) -> _FileIdentity:
    if not stat.S_ISREG(value.st_mode):
        raise _TransferFailure(RunnerTransferFailure.PROTOCOL_VIOLATION)
    return _FileIdentity(
        value.st_dev, value.st_ino, value.st_size, value.st_mtime_ns, value.st_ctime_ns
    )


def _write_all(fd: int, data: bytes) -> None:
    view = memoryview(data)
    while view:
        written = os.write(fd, view)
        view = view[written:]


def _open_temporary_file(parent_fd: int) -> tuple[int, str]:
    for _ in range(16):
        name = f".azents-transfer-{secrets.token_hex(16)}"
        try:
            descriptor = os.open(
                name,
                os.O_RDWR | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                0o600,
                dir_fd=parent_fd,
            )
        except FileExistsError:
            continue
        return descriptor, name
    raise OSError("could not allocate a unique Runtime transfer staging file")


def _local_io_failure(intent: RunnerTransferIntent) -> RunnerTransferFailure:
    if intent.direction is RunnerTransferDirection.DOWNLOAD:
        return RunnerTransferFailure.DESTINATION_FAILED
    return RunnerTransferFailure.INTEGRITY_FAILED
