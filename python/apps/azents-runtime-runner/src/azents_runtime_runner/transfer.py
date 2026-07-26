"""Runner-local bounded transfer execution and filesystem publication."""

import asyncio
import contextlib
import hashlib
import os
import stat
import uuid
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import PurePath
from typing import Protocol

import grpc
from azents_runtime_control.grpc_runner_transfer_client import (
    GrpcRunnerTransferClient,
    RunnerDownloadChunk,
    RunnerDownloadComplete,
    RunnerUploadComplete,
    runner_transfer_failure_from_grpc,
)
from azents_runtime_control.runner_transfer import (
    RunnerTransferCancel,
    RunnerTransferDirection,
    RunnerTransferFailure,
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


class RunnerTransferResultSink(Protocol):
    """Control stream subset used by local transfer tasks."""

    async def append_runner_transfer_result(
        self,
        result: RunnerTransferResult,
    ) -> None:
        """Append one bounded result."""
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


class RunnerTransferManager:
    """Isolate bounded transfer tasks from ordinary Runner operation scheduling."""

    def __init__(
        self,
        *,
        control: RunnerTransferResultSink,
        transfer: GrpcRunnerTransferClient,
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
        self._tombstones: dict[_TransferKey, RunnerTransferResult] = {}
        self._lock = asyncio.Lock()
        self._commit_lock = asyncio.Lock()
        self._closed = False

    async def handle_intent(self, intent: RunnerTransferIntent) -> None:
        """Validate and admit one intent without awaiting its transfer task."""
        key = _key(intent)
        invalid = _validate_intent(intent, self._accepted_generation())
        async with self._lock:
            prior = self._tombstones.get(key)
            if prior is not None:
                await self._emit(prior)
                return
            active = self._active.get(key)
            if active is not None:
                if active.intent != intent:
                    await self._emit(
                        _failed(intent, RunnerTransferFailure.PROTOCOL_VIOLATION)
                    )
                return
            if invalid is not None:
                result = _failed(intent, invalid)
                self._remember(key, result)
                await self._emit(result)
                return
            if self._closed or len(self._active) >= self._max_active_transfers:
                result = _failed(intent, RunnerTransferFailure.RESOURCE_EXHAUSTED)
                self._remember(key, result)
                await self._emit(result)
                return
            cancelled = asyncio.Event()
            task = asyncio.create_task(self._run(intent, cancelled))
            self._active[key] = _ActiveTransfer(intent, cancelled, task)
            task.add_done_callback(lambda _: asyncio.create_task(self._reap(key)))

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
            for item in active:
                item.cancelled.set()
                item.task.cancel()
        for item in active:
            with contextlib.suppress(asyncio.CancelledError):
                await item.task

    async def _reap(self, key: "_TransferKey") -> None:
        async with self._lock:
            self._active.pop(key, None)

    async def _run(
        self, intent: RunnerTransferIntent, cancelled: asyncio.Event
    ) -> None:
        try:
            if intent.direction is RunnerTransferDirection.DOWNLOAD:
                result = await self._download(intent, cancelled)
            else:
                result = await self._upload(intent, cancelled)
        except asyncio.CancelledError:
            result = _cancelled(intent)
            await asyncio.shield(self._emit(result))
            self._remember(_key(intent), result)
            raise
        except grpc.aio.AioRpcError as exc:
            result = _failed(intent, runner_transfer_failure_from_grpc(exc))
        except _TransferFailure as exc:
            result = _failed(intent, exc.failure)
        except OSError:
            result = _failed(intent, RunnerTransferFailure.DESTINATION_FAILED)
        except ValueError:
            result = _failed(intent, RunnerTransferFailure.PROTOCOL_VIOLATION)
        self._remember(_key(intent), result)
        await self._emit(result)

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
        stage_name = _temporary_name(intent, "download")
        stage_fd: int | None = None
        published = False
        try:
            stage_fd = os.open(
                stage_name,
                os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                0o600,
                dir_fd=parent_fd,
            )
            offset = 0
            digest = hashlib.sha256()
            complete: RunnerDownloadComplete | None = None
            async for frame in self._transfer.download(intent.identity):
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
                _write_all(stage_fd, frame.data)
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
            os.fsync(stage_fd)
            os.close(stage_fd)
            stage_fd = None
            async with self._commit_lock:
                _check_stop(intent, cancelled)
                _assert_destination(parent_fd, destination_name, overwrite)
                if overwrite:
                    os.replace(
                        stage_name,
                        destination_name,
                        src_dir_fd=parent_fd,
                        dst_dir_fd=parent_fd,
                    )
                else:
                    os.link(
                        stage_name,
                        destination_name,
                        src_dir_fd=parent_fd,
                        dst_dir_fd=parent_fd,
                    )
                    os.unlink(stage_name, dir_fd=parent_fd)
                os.fsync(parent_fd)
                published = True
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
            if stage_fd is not None:
                os.close(stage_fd)
            if not published:
                with contextlib.suppress(FileNotFoundError):
                    os.unlink(stage_name, dir_fd=parent_fd)
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
        snapshot_name = _temporary_name(intent, "upload")
        source_fd: int | None = None
        snapshot_fd: int | None = None
        try:
            source_fd = os.open(
                source_name, os.O_RDONLY | os.O_NOFOLLOW, dir_fd=parent_fd
            )
            before = _regular_identity(os.fstat(source_fd))
            if before.size != expected_size:
                raise _TransferFailure(RunnerTransferFailure.INTEGRITY_FAILED)
            snapshot_fd = os.open(
                snapshot_name,
                os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                0o600,
                dir_fd=parent_fd,
            )
            digest = hashlib.sha256()
            copied = 0
            while True:
                _check_stop(intent, cancelled)
                chunk = os.read(source_fd, _BUFFER_BYTES)
                if not chunk:
                    break
                copied += len(chunk)
                if copied > expected_size:
                    raise _TransferFailure(RunnerTransferFailure.INTEGRITY_FAILED)
                _write_all(snapshot_fd, chunk)
                digest.update(chunk)
            os.fsync(snapshot_fd)
            os.close(snapshot_fd)
            snapshot_fd = None
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

            async def frames() -> AsyncIterator[
                RunnerDownloadChunk | RunnerUploadComplete
            ]:
                snapshot_read = os.open(
                    snapshot_name, os.O_RDONLY | os.O_NOFOLLOW, dir_fd=parent_fd
                )
                try:
                    offset = 0
                    while True:
                        _check_stop(intent, cancelled)
                        chunk = os.read(snapshot_read, _BUFFER_BYTES)
                        if not chunk:
                            break
                        yield RunnerDownloadChunk(offset=offset, data=chunk)
                        offset += len(chunk)
                    yield RunnerUploadComplete(actual_size=offset, sha256=actual_sha256)
                finally:
                    os.close(snapshot_read)

            authoritative = await self._transfer.upload(intent.identity, frames())
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
            if source_fd is not None:
                os.close(source_fd)
            if snapshot_fd is not None:
                os.close(snapshot_fd)
            with contextlib.suppress(FileNotFoundError):
                os.unlink(snapshot_name, dir_fd=parent_fd)
            os.close(parent_fd)

    async def _emit(self, result: RunnerTransferResult) -> None:
        await self._control.append_runner_transfer_result(result)

    def _remember(self, key: "_TransferKey", result: RunnerTransferResult) -> None:
        self._tombstones[key] = result
        while len(self._tombstones) > self._max_tombstones:
            self._tombstones.pop(next(iter(self._tombstones)))


@dataclass(frozen=True)
class _TransferKey:
    transfer_id: str
    attempt_id: str
    runtime_id: str
    generation: int
    operation_id: str
    dispatch_id: str
    direction: RunnerTransferDirection


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
    ):
        return RunnerTransferFailure.PROTOCOL_VIOLATION
    if (
        intent.direction is RunnerTransferDirection.DOWNLOAD
        and intent.expected_sha256 is None
    ):
        return RunnerTransferFailure.PROTOCOL_VIOLATION
    return None


def _failed(
    intent: RunnerTransferIntent, failure: RunnerTransferFailure
) -> RunnerTransferResult:
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
                os.mkdir(component, 0o700, dir_fd=parent_fd)
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


def _assert_destination(parent_fd: int, name: str, overwrite: bool) -> None:
    try:
        observed = os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
    except FileNotFoundError:
        return
    if (
        stat.S_ISLNK(observed.st_mode)
        or not stat.S_ISREG(observed.st_mode)
        or not overwrite
    ):
        raise _TransferFailure(RunnerTransferFailure.DESTINATION_FAILED)


def _regular_identity(value: os.stat_result) -> _FileIdentity:
    if not stat.S_ISREG(value.st_mode):
        raise _TransferFailure(RunnerTransferFailure.PROTOCOL_VIOLATION)
    return _FileIdentity(
        value.st_dev, value.st_ino, value.st_size, value.st_mtime_ns, value.st_ctime_ns
    )


def _temporary_name(intent: RunnerTransferIntent, direction: str) -> str:
    return "-".join(
        (
            ".azents-transfer",
            direction,
            intent.identity.transfer_id,
            intent.identity.attempt_id,
            uuid.uuid4().hex,
        )
    )


def _write_all(fd: int, data: bytes) -> None:
    view = memoryview(data)
    while view:
        written = os.write(fd, view)
        view = view[written:]
