"""Runner-local bounded transfer execution and filesystem publication."""

from __future__ import annotations

import asyncio
import contextlib
import hashlib
import logging
import os
import secrets
import ssl
import stat
from collections.abc import AsyncIterator, Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import PurePath
from typing import Protocol, TypeVar
from urllib.parse import urlsplit

import aiohttp
import grpc
from azents_runtime_control.grpc_runner_transfer_client import (
    RunnerDirectObjectTicket,
    RunnerDownloadChunk,
    RunnerDownloadComplete,
    RunnerUploadComplete,
    RunnerUploadResult,
    runner_transfer_failure_from_grpc,
)
from azents_runtime_control.runner_transfer import (
    RunnerTransferCancel,
    RunnerTransferDestinationConflictEvidence,
    RunnerTransferDirection,
    RunnerTransferFailure,
    RunnerTransferIdentity,
    RunnerTransferIntent,
    RunnerTransferOutcome,
    RunnerTransferResult,
    RunnerTransferSourceTransport,
)
from azents_runtime_control.transfer import (
    MAX_TRANSFER_CHUNK_BYTES,
    RUNNER_TRANSFER_CAPABILITY,
    RUNNER_TRANSFER_PROTOCOL_VERSION,
    STREAM_OWNER_RENEWAL_SECONDS,
)

from azents_runtime_runner.workspace import Workspace

_BUFFER_BYTES = MAX_TRANSFER_CHUNK_BYTES
_DEFAULT_MAX_ACTIVE_TRANSFERS = 4
_DEFAULT_MAX_TOMBSTONES = 256
_MAX_CONFLICT_PRECONDITIONS = 256
_MAX_DIRECT_TICKET_REACQUISITIONS = 1
_LOGGER = logging.getLogger(__name__)
_AwaitableResult = TypeVar("_AwaitableResult")


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

    async def claim_direct_object(
        self,
        identity: RunnerTransferIdentity,
        *,
        dispatch_id: str,
        claim_id: str,
        timeout: float,
    ) -> RunnerDirectObjectTicket:
        """Claim one exact direct-object source and return its transient GET ticket."""
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


@dataclass(frozen=True)
class _OpenedFile:
    """Opened directory-relative file identity."""

    descriptor: int
    name: str


@dataclass(frozen=True)
class _DestinationObservation:
    """Filesystem evidence captured while holding the transfer commit lock."""

    evidence: RunnerTransferDestinationConflictEvidence
    identity: _FileIdentity | None


@dataclass(frozen=True)
class _ConflictPrecondition:
    """Runner-local overwrite authority for one observed destination identity.

    The evidence is intentionally independent from one delivery operation. A
    public Workspace upload retry creates a new Runtime Transfer operation but
    must be able to consume the token captured by the failed no-overwrite
    attempt.
    """

    identity: RunnerTransferIdentity
    runtime_path: str
    destination_identity: _FileIdentity | None
    expires_at: datetime


@dataclass
class _ActiveTransfer:
    intent: RunnerTransferIntent
    cancelled: asyncio.Event
    task: asyncio.Task[None]


@dataclass(frozen=True)
class _TransferTombstone:
    intent: RunnerTransferIntent
    result: RunnerTransferResult


@dataclass
class _PendingRunnerTransferResult:
    """One queued result and its optional delivery acknowledgement."""

    result: RunnerTransferResult
    delivered: asyncio.Future[bool] | None = None


class RunnerTransferManager:
    """Isolate bounded transfer tasks from ordinary Runner operation scheduling."""

    def __init__(
        self,
        *,
        control: RunnerTransferResultSink,
        transfer: RunnerTransferClient,
        accepted_generation: Callable[[], int | None],
        workspace: Workspace,
        http_proxy: str | None,
        http_ssl_context: ssl.SSLContext | None = None,
        max_active_transfers: int = _DEFAULT_MAX_ACTIVE_TRANSFERS,
        max_tombstones: int = _DEFAULT_MAX_TOMBSTONES,
    ) -> None:
        """Initialize independent data-task admission and result ownership."""
        if max_active_transfers <= 0 or max_tombstones <= 0:
            raise ValueError("Runner transfer limits must be positive")
        self._control = control
        self._transfer = transfer
        self._accepted_generation = accepted_generation
        self._workspace = workspace
        self._http_proxy = http_proxy
        self._http_ssl_context = http_ssl_context
        self._max_active_transfers = max_active_transfers
        self._max_tombstones = max_tombstones
        self._active: dict[_TransferKey, _ActiveTransfer] = {}
        self._active_by_identity: dict[_TransferIdentityKey, _TransferKey] = {}
        self._tombstones: dict[_TransferKey, _TransferTombstone] = {}
        self._completed_by_identity: dict[_TransferIdentityKey, _TransferKey] = {}
        self._results: asyncio.Queue[_PendingRunnerTransferResult] = asyncio.Queue(
            maxsize=max_tombstones
        )
        self._result_task: asyncio.Task[None] | None = None
        self._lock = asyncio.Lock()
        self._commit_lock = asyncio.Lock()
        self._conflict_preconditions: dict[bytes, _ConflictPrecondition] = {}
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
        direct_claim_lease: list[_DirectClaimLease | None] = [None]
        try:
            try:
                if intent.direction is RunnerTransferDirection.DOWNLOAD:
                    result = await self._download(
                        intent,
                        cancelled,
                        direct_claim_lease=direct_claim_lease,
                    )
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
            except aiohttp.ClientError:
                result = _failed(intent, RunnerTransferFailure.STREAM_FAILED)
                _log_failure(
                    intent,
                    result,
                    source="direct_http",
                    reason="http_request_failed",
                    grpc_status=None,
                )
            except TimeoutError:
                result = _failed(
                    intent,
                    (
                        RunnerTransferFailure.DEADLINE_EXCEEDED
                        if datetime.now(UTC) >= intent.deadline_at
                        else RunnerTransferFailure.STREAM_FAILED
                    ),
                )
                _log_failure(
                    intent,
                    result,
                    source="direct_http",
                    reason="http_request_timeout",
                    grpc_status=None,
                )
            except _TransferFailure as exc:
                result = _failed(
                    intent,
                    exc.failure,
                    conflict_precondition=exc.conflict_precondition,
                    destination_conflict=exc.destination_conflict,
                )
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
            if not await self._enqueue_terminal_result(result):
                _LOGGER.warning(
                    "Runtime Runner transfer result was not delivered",
                    extra={
                        "transfer_id": result.identity.transfer_id,
                        "attempt_id": result.identity.attempt_id,
                        "runtime_id": result.identity.runtime_id,
                        "runner_generation": result.identity.runner_generation,
                        "operation_id": result.operation_id,
                        "dispatch_id": result.dispatch_id,
                    },
                )
        except asyncio.CancelledError:
            if result is None:
                result = _cancelled(intent)
                self._remember(intent, result)
                if not self._closed:
                    if not await self._enqueue_terminal_result(result):
                        _LOGGER.warning(
                            "Runtime Runner cancellation result was not delivered",
                            extra={
                                "transfer_id": result.identity.transfer_id,
                                "attempt_id": result.identity.attempt_id,
                                "runtime_id": result.identity.runtime_id,
                                "runner_generation": result.identity.runner_generation,
                                "operation_id": result.operation_id,
                                "dispatch_id": result.dispatch_id,
                            },
                        )
            raise
        finally:
            lease = direct_claim_lease[0]
            if lease is not None:
                await lease.close()

    async def _download(
        self,
        intent: RunnerTransferIntent,
        cancelled: asyncio.Event,
        *,
        direct_claim_lease: list[_DirectClaimLease | None],
    ) -> RunnerTransferResult:
        if intent.source_transport is RunnerTransferSourceTransport.DIRECT_OBJECT:
            return await self._download_direct(
                intent,
                cancelled,
                direct_claim_lease=direct_claim_lease,
            )
        expected_sha256 = intent.expected_sha256
        overwrite = intent.overwrite
        expected_size = intent.expected_size
        if expected_sha256 is None or overwrite is None or expected_size is None:
            raise _TransferFailure(
                RunnerTransferFailure.PROTOCOL_VIOLATION,
                reason="download_manifest_missing",
            )
        destination_path = self._workspace.resolve_lexical(
            intent.runtime_path,
            write=True,
        )
        parent = _open_parent(
            str(destination_path),
            create=True,
        )
        parent_fd = parent.descriptor
        destination_name = parent.name
        stage_fd: int | None = None
        stage_name: str | None = None
        try:
            stage = _open_temporary_file(parent_fd)
            stage_fd = stage.descriptor
            stage_name = stage.name
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
                raise _TransferFailure(
                    RunnerTransferFailure.INTEGRITY_FAILED,
                    reason="download_manifest_mismatch",
                )
            await asyncio.to_thread(os.fsync, stage_fd)
            assert stage_fd is not None
            async with self._commit_lock:
                _check_stop(intent, cancelled)
                if overwrite:
                    self._assert_overwrite_precondition(
                        intent,
                        parent_fd,
                        destination_name,
                    )
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
                    try:
                        os.link(
                            stage_name,
                            destination_name,
                            src_dir_fd=parent_fd,
                            dst_dir_fd=parent_fd,
                            follow_symlinks=False,
                        )
                    except FileExistsError:
                        self._raise_destination_conflict(
                            intent,
                            parent_fd,
                            destination_name,
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
                conflict_precondition=None,
                destination_conflict=None,
            )
        finally:
            if stage_name is not None:
                with contextlib.suppress(FileNotFoundError):
                    os.unlink(stage_name, dir_fd=parent_fd)
            if stage_fd is not None:
                os.close(stage_fd)
            os.close(parent_fd)

    async def _download_direct(
        self,
        intent: RunnerTransferIntent,
        cancelled: asyncio.Event,
        *,
        direct_claim_lease: list[_DirectClaimLease | None],
    ) -> RunnerTransferResult:
        """Claim and stream one verified direct-object source over HTTP."""
        expected_sha256 = intent.expected_sha256
        overwrite = intent.overwrite
        expected_size = intent.expected_size
        if expected_sha256 is None or overwrite is None or expected_size is None:
            raise _TransferFailure(
                RunnerTransferFailure.PROTOCOL_VIOLATION,
                reason="direct_download_manifest_missing",
            )
        destination_path = self._workspace.resolve_lexical(
            intent.runtime_path,
            write=True,
        )
        parent = _open_parent(
            str(destination_path),
            create=True,
        )
        parent_fd = parent.descriptor
        destination_name = parent.name
        stage_fd: int | None = None
        stage_name: str | None = None
        try:
            stage = _open_temporary_file(parent_fd)
            stage_fd = stage.descriptor
            stage_name = stage.name
            self._check_direct_stop(intent, cancelled)
            claim_id = _direct_claim_id(intent)
            reacquisitions = 0
            while True:
                ticket = await self._transfer.claim_direct_object(
                    intent.identity,
                    dispatch_id=intent.dispatch_id,
                    claim_id=claim_id,
                    timeout=_remaining_timeout(intent),
                )
                try:
                    _validate_direct_ticket(
                        ticket,
                        expected_size=expected_size,
                        expected_sha256=expected_sha256,
                        deadline_at=intent.deadline_at,
                    )
                except _TransferFailure as exc:
                    if (
                        reacquisitions < _MAX_DIRECT_TICKET_REACQUISITIONS
                        and _direct_ticket_expired(ticket, intent.deadline_at)
                        and exc.reason == "direct_ticket_expiry_invalid"
                    ):
                        reacquisitions += 1
                        continue
                    raise
                break
            lease = _DirectClaimLease(
                manager=self,
                intent=intent,
                cancelled=cancelled,
                claim_id=claim_id,
            )
            direct_claim_lease[0] = lease
            await lease.start()
            digest = hashlib.sha256()
            offset = 0
            body_started = False
            while True:
                self._check_direct_stop(intent, cancelled)
                lease.check()
                now = datetime.now(UTC)
                remaining = (intent.deadline_at - now).total_seconds()
                ticket_remaining = (ticket.expires_at - now).total_seconds()
                if remaining <= 0:
                    raise _TransferFailure(
                        RunnerTransferFailure.DEADLINE_EXCEEDED,
                        reason="deadline_exceeded",
                    )
                if ticket_remaining <= 0:
                    if (
                        not body_started
                        and reacquisitions < _MAX_DIRECT_TICKET_REACQUISITIONS
                    ):
                        reacquisitions += 1
                        ticket = await lease.wait_for(
                            self._transfer.claim_direct_object(
                                intent.identity,
                                dispatch_id=intent.dispatch_id,
                                claim_id=claim_id,
                                timeout=remaining,
                            )
                        )
                        _validate_direct_ticket(
                            ticket,
                            expected_size=expected_size,
                            expected_sha256=expected_sha256,
                            deadline_at=intent.deadline_at,
                        )
                        continue
                    raise _TransferFailure(
                        RunnerTransferFailure.DEADLINE_EXCEEDED,
                        reason="direct_ticket_expired",
                    )
                retry_ticket = False
                client_timeout = aiohttp.ClientTimeout(
                    total=min(remaining, ticket_remaining)
                )
                connector = (
                    aiohttp.TCPConnector(ssl=self._http_ssl_context)
                    if self._http_ssl_context is not None
                    else None
                )
                async with aiohttp.ClientSession(
                    timeout=client_timeout,
                    trust_env=False,
                    connector=connector,
                ) as session:
                    request = session.request(
                        ticket.method,
                        ticket.url,
                        headers=dict(ticket.headers),
                        allow_redirects=False,
                        proxy=self._http_proxy,
                    )
                    response: aiohttp.ClientResponse | None = None
                    try:
                        response = await lease.wait_for(request.__aenter__())
                        if response.status != 200:
                            if response.status in {401, 403} and not body_started:
                                retry_ticket = True
                            else:
                                raise _TransferFailure(
                                    RunnerTransferFailure.STREAM_FAILED,
                                    reason="direct_http_status_invalid",
                                )
                        if not retry_ticket and (
                            response.content_length is not None
                            and response.content_length != expected_size
                        ):
                            raise _TransferFailure(
                                RunnerTransferFailure.INTEGRITY_FAILED,
                                reason="direct_http_content_length_mismatch",
                            )
                        while not retry_ticket:
                            lease.check()
                            self._check_direct_stop(intent, cancelled)
                            chunk = await lease.wait_for(
                                response.content.read(_BUFFER_BYTES)
                            )
                            if not chunk:
                                break
                            body_started = True
                            self._check_direct_stop(intent, cancelled)
                            lease.check()
                            if len(chunk) > _BUFFER_BYTES:
                                raise _TransferFailure(
                                    RunnerTransferFailure.PROTOCOL_VIOLATION,
                                    reason="direct_http_chunk_invalid",
                                )
                            if offset + len(chunk) > expected_size:
                                raise _TransferFailure(
                                    RunnerTransferFailure.INTEGRITY_FAILED,
                                    reason="direct_http_body_exceeds_expected_size",
                                )
                            await asyncio.to_thread(_write_all, stage_fd, chunk)
                            lease.check()
                            digest.update(chunk)
                            offset += len(chunk)
                        lease.check()
                    except aiohttp.ClientError, TimeoutError:
                        if not body_started:
                            retry_ticket = True
                        else:
                            raise
                    finally:
                        if response is not None:
                            await request.__aexit__(None, None, None)
                        else:
                            request.close()
                if not retry_ticket:
                    break
                if body_started or reacquisitions >= _MAX_DIRECT_TICKET_REACQUISITIONS:
                    raise _TransferFailure(
                        RunnerTransferFailure.STREAM_FAILED,
                        reason="direct_http_request_failed",
                    )
                reacquisitions += 1
                ticket = await lease.wait_for(
                    self._transfer.claim_direct_object(
                        intent.identity,
                        dispatch_id=intent.dispatch_id,
                        claim_id=claim_id,
                        timeout=_remaining_timeout(intent),
                    )
                )
                _validate_direct_ticket(
                    ticket,
                    expected_size=expected_size,
                    expected_sha256=expected_sha256,
                    deadline_at=intent.deadline_at,
                )
            self._check_direct_stop(intent, cancelled)
            lease.check()
            actual_sha256 = digest.hexdigest()
            if offset != expected_size or actual_sha256 != expected_sha256:
                raise _TransferFailure(
                    RunnerTransferFailure.INTEGRITY_FAILED,
                    reason="direct_http_manifest_mismatch",
                )
            await asyncio.to_thread(os.fsync, stage_fd)
            lease.check()
            assert stage_fd is not None
            await self._commit_lock.acquire()
            try:
                self._check_direct_stop(intent, cancelled)
                lease.check()
                if overwrite:
                    self._assert_overwrite_precondition(
                        intent,
                        parent_fd,
                        destination_name,
                    )
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
                    try:
                        os.link(
                            stage_name,
                            destination_name,
                            src_dir_fd=parent_fd,
                            dst_dir_fd=parent_fd,
                            follow_symlinks=False,
                        )
                    except FileExistsError:
                        self._raise_destination_conflict(
                            intent,
                            parent_fd,
                            destination_name,
                        )
                    os.unlink(stage_name, dir_fd=parent_fd)
                    stage_name = None
            finally:
                self._commit_lock.release()
            return RunnerTransferResult(
                identity=intent.identity,
                operation_id=intent.operation_id,
                dispatch_id=intent.dispatch_id,
                direction=intent.direction,
                outcome=RunnerTransferOutcome.SUCCEEDED,
                actual_size=offset,
                sha256=actual_sha256,
                destination_committed=True,
                failure=None,
                conflict_precondition=None,
                destination_conflict=None,
            )
        finally:
            if stage_name is not None:
                with contextlib.suppress(FileNotFoundError):
                    os.unlink(stage_name, dir_fd=parent_fd)
            if stage_fd is not None:
                os.close(stage_fd)
            os.close(parent_fd)

    async def _renew_direct_claim(
        self,
        intent: RunnerTransferIntent,
        cancelled: asyncio.Event,
        *,
        claim_id: str,
        failed: asyncio.Event,
        error: list[_TransferFailure],
    ) -> None:
        """Renew one direct-object claim until the HTTP body finishes."""
        try:
            while True:
                remaining = _remaining_timeout(intent)
                await asyncio.sleep(min(STREAM_OWNER_RENEWAL_SECONDS, remaining))
                self._check_direct_stop(intent, cancelled)
                renewed = await self._transfer.claim_direct_object(
                    intent.identity,
                    dispatch_id=intent.dispatch_id,
                    claim_id=claim_id,
                    timeout=_remaining_timeout(intent),
                )
                _validate_direct_ticket(
                    renewed,
                    expected_size=intent.expected_size
                    if intent.expected_size is not None
                    else -1,
                    expected_sha256=intent.expected_sha256 or "",
                    deadline_at=intent.deadline_at,
                )
        except asyncio.CancelledError:
            raise
        except _TransferFailure as exc:
            error.append(exc)
            failed.set()
        except grpc.aio.AioRpcError as exc:
            error.append(
                _TransferFailure(
                    runner_transfer_failure_from_grpc(exc),
                    reason="direct_claim_renewal_grpc_failed",
                )
            )
            failed.set()
        except ValueError as exc:
            del exc
            error.append(
                _TransferFailure(
                    RunnerTransferFailure.PROTOCOL_VIOLATION,
                    reason="direct_claim_renewal_response_invalid",
                )
            )
            failed.set()
        except Exception as exc:
            del exc
            error.append(
                _TransferFailure(
                    RunnerTransferFailure.STREAM_FAILED,
                    reason="direct_claim_renewal_failed",
                )
            )
            failed.set()

    def _check_direct_stop(
        self,
        intent: RunnerTransferIntent,
        cancelled: asyncio.Event,
    ) -> None:
        """Check cancellation, deadline, and current Runner generation."""
        _check_stop(intent, cancelled)
        if self._accepted_generation() != intent.identity.runner_generation:
            raise _TransferFailure(
                RunnerTransferFailure.UNAVAILABLE,
                reason="runner_generation_fenced",
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
        source_path = self._workspace.resolve_lexical(
            intent.runtime_path,
            write=False,
        )
        parent = _open_parent(
            str(source_path),
            create=False,
        )
        parent_fd = parent.descriptor
        source_name = parent.name
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
                raise _TransferFailure(
                    RunnerTransferFailure.INTEGRITY_FAILED,
                    reason="upload_source_size_mismatch",
                )
            snapshot = _open_temporary_file(parent_fd)
            snapshot_fd = snapshot.descriptor
            snapshot_name = snapshot.name
            digest = hashlib.sha256()
            copied = 0
            while True:
                _check_stop(intent, cancelled)
                chunk = await asyncio.to_thread(os.read, source_fd, _BUFFER_BYTES)
                if not chunk:
                    break
                copied += len(chunk)
                if copied > expected_size:
                    raise _TransferFailure(
                        RunnerTransferFailure.INTEGRITY_FAILED,
                        reason="upload_source_exceeds_expected_size",
                    )
                await asyncio.to_thread(_write_all, snapshot_fd, chunk)
                digest.update(chunk)
            await asyncio.to_thread(os.fsync, snapshot_fd)
            after_fd = _regular_identity(os.fstat(source_fd))
            after_path = _regular_identity(
                os.stat(source_name, dir_fd=parent_fd, follow_symlinks=False)
            )
            if before != after_fd or before != after_path or copied != expected_size:
                raise _TransferFailure(
                    RunnerTransferFailure.INTEGRITY_FAILED,
                    reason="upload_source_changed",
                )
            actual_sha256 = digest.hexdigest()
            if (
                intent.expected_sha256 is not None
                and actual_sha256 != intent.expected_sha256
            ):
                raise _TransferFailure(
                    RunnerTransferFailure.INTEGRITY_FAILED,
                    reason="upload_source_digest_mismatch",
                )
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
                conflict_precondition=None,
                destination_conflict=None,
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
        await self._enqueue_pending_result(_PendingRunnerTransferResult(result=result))

    async def _enqueue_pending_result(
        self,
        pending: _PendingRunnerTransferResult,
    ) -> bool:
        if self._closed:
            return False
        self._ensure_result_task()
        await self._results.put(pending)
        return True

    async def _publish_terminal_result(
        self,
        pending: _PendingRunnerTransferResult,
    ) -> bool:
        """Queue one terminal result and await Control's delivery outcome."""
        if not await self._enqueue_pending_result(pending):
            return False
        assert pending.delivered is not None
        return await pending.delivered

    async def _enqueue_terminal_result(self, result: RunnerTransferResult) -> bool:
        delivered = asyncio.get_running_loop().create_future()
        pending = _PendingRunnerTransferResult(result=result, delivered=delivered)
        enqueue = asyncio.create_task(self._publish_terminal_result(pending))
        cancelled = False
        try:
            while True:
                try:
                    published = await asyncio.shield(enqueue)
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
        return published

    def _ensure_result_task(self) -> None:
        if self._result_task is None:
            self._result_task = asyncio.create_task(self._emit_results())

    async def _emit_results(self) -> None:
        while True:
            pending = await self._results.get()
            try:
                try:
                    await self._control.append_runner_transfer_result(pending.result)
                except asyncio.CancelledError:
                    _set_result_delivery(pending, delivered=False)
                    raise
                except Exception:
                    _LOGGER.warning(
                        "Runner transfer result delivery became unavailable",
                        exc_info=True,
                    )
                    _set_result_delivery(pending, delivered=False)
                else:
                    _set_result_delivery(pending, delivered=True)
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

    def _assert_overwrite_precondition(
        self,
        intent: RunnerTransferIntent,
        parent_fd: int,
        destination_name: str,
    ) -> None:
        """Require the exact Runner-issued record before replacement."""
        token = intent.conflict_precondition
        record = (
            self._conflict_preconditions.pop(token, None) if token is not None else None
        )
        observation = _destination_observation(parent_fd, destination_name)
        if (
            record is None
            or record.expires_at < datetime.now(UTC)
            or record.identity.runtime_id != intent.identity.runtime_id
            or record.identity.runner_generation != intent.identity.runner_generation
            or record.runtime_path != intent.runtime_path
            or observation.identity is None
            or observation.identity != record.destination_identity
        ):
            self._raise_destination_conflict(
                intent,
                parent_fd,
                destination_name,
                observation=observation,
            )

    def _raise_destination_conflict(
        self,
        intent: RunnerTransferIntent,
        parent_fd: int,
        destination_name: str,
        *,
        observation: _DestinationObservation | None = None,
    ) -> None:
        """Raise a conflict result with only safe evidence and opaque authority."""
        captured = observation or _destination_observation(parent_fd, destination_name)
        token = self._issue_conflict_precondition(intent, captured.identity)
        raise _TransferFailure(
            RunnerTransferFailure.DESTINATION_CONFLICT,
            reason="download_destination_conflict",
            conflict_precondition=token,
            destination_conflict=captured.evidence,
        )

    def _issue_conflict_precondition(
        self,
        intent: RunnerTransferIntent,
        destination_identity: _FileIdentity | None,
    ) -> bytes:
        """Create a bounded opaque record tied to the failed delivery attempt."""
        now = datetime.now(UTC)
        expired = tuple(
            token
            for token, record in self._conflict_preconditions.items()
            if record.expires_at < now
        )
        for token in expired:
            self._conflict_preconditions.pop(token)
        while len(self._conflict_preconditions) >= _MAX_CONFLICT_PRECONDITIONS:
            oldest = next(iter(self._conflict_preconditions))
            self._conflict_preconditions.pop(oldest)
        token = secrets.token_bytes(32)
        while token in self._conflict_preconditions:
            token = secrets.token_bytes(32)
        self._conflict_preconditions[token] = _ConflictPrecondition(
            identity=intent.identity,
            runtime_path=intent.runtime_path,
            destination_identity=destination_identity,
            expires_at=intent.deadline_at,
        )
        return token


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
    def __init__(
        self,
        failure: RunnerTransferFailure,
        *,
        reason: str,
        conflict_precondition: bytes | None = None,
        destination_conflict: RunnerTransferDestinationConflictEvidence | None = None,
    ) -> None:
        self.failure = failure
        self.reason = reason
        self.conflict_precondition = conflict_precondition
        self.destination_conflict = destination_conflict


class _DirectClaimLease:
    """Keep one direct-object claim alive for the whole local operation."""

    def __init__(
        self,
        *,
        manager: RunnerTransferManager,
        intent: RunnerTransferIntent,
        cancelled: asyncio.Event,
        claim_id: str,
    ) -> None:
        """Initialize one claim renewal task and its failure signal."""
        self.manager = manager
        self.intent = intent
        self.cancelled = cancelled
        self.claim_id = claim_id
        self.failed = asyncio.Event()
        self.error: list[_TransferFailure] = []
        self.task: asyncio.Task[None] | None = None

    async def start(self) -> None:
        """Start renewing the claim until the manager closes this lease."""
        self.task = asyncio.create_task(
            self.manager._renew_direct_claim(
                self.intent,
                self.cancelled,
                claim_id=self.claim_id,
                failed=self.failed,
                error=self.error,
            )
        )

    def check(self) -> None:
        """Raise the exact renewal failure, if claim ownership was lost."""
        if self.error:
            raise self.error[0]
        if self.failed.is_set():
            raise _TransferFailure(
                RunnerTransferFailure.STREAM_FAILED,
                reason="direct_claim_renewal_failed",
            )

    async def wait_for(
        self,
        awaitable: Awaitable[_AwaitableResult],
    ) -> _AwaitableResult:
        """Await one operation while fencing promptly on renewal failure."""
        operation = asyncio.ensure_future(awaitable)
        failed = asyncio.create_task(self.failed.wait())
        try:
            done, _ = await asyncio.wait(
                {operation, failed},
                return_when=asyncio.FIRST_COMPLETED,
            )
            if failed in done:
                operation.cancel()
                with contextlib.suppress(asyncio.CancelledError, Exception):
                    await operation
                self.check()
                raise _TransferFailure(
                    RunnerTransferFailure.STREAM_FAILED,
                    reason="direct_claim_renewal_failed",
                )
            return operation.result()
        except asyncio.CancelledError:
            operation.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await operation
            raise
        finally:
            if not failed.done():
                failed.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await failed

    async def close(self) -> None:
        """Stop renewal only after terminal result enqueue has returned."""
        if self.task is None or self.task.done():
            return
        self.task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await self.task


def _set_result_delivery(
    pending: _PendingRunnerTransferResult,
    *,
    delivered: bool,
) -> None:
    """Resolve one terminal-result delivery acknowledgement exactly once."""
    if pending.delivered is not None and not pending.delivered.done():
        pending.delivered.set_result(delivered)


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
    if (
        intent.direction is RunnerTransferDirection.UPLOAD
        and intent.conflict_precondition is not None
    ):
        return "upload_conflict_precondition_present"
    return None


def _valid_identifier(value: str) -> bool:
    try:
        size = len(value.encode())
    except UnicodeEncodeError:
        return False
    return 1 <= size <= 128


def _failed(
    intent: RunnerTransferIntent,
    failure: RunnerTransferFailure,
    *,
    conflict_precondition: bytes | None = None,
    destination_conflict: RunnerTransferDestinationConflictEvidence | None = None,
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
        conflict_precondition=conflict_precondition,
        destination_conflict=destination_conflict,
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
        conflict_precondition=None,
        destination_conflict=None,
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


def _direct_claim_id(intent: RunnerTransferIntent) -> str:
    """Return a stable opaque claim identity for one exact dispatch."""
    digest = hashlib.sha256(
        "\0".join(
            (
                intent.identity.transfer_id,
                intent.identity.attempt_id,
                intent.identity.runtime_id,
                str(intent.identity.runner_generation),
                intent.operation_id,
                intent.dispatch_id,
            )
        ).encode()
    ).hexdigest()
    return f"runner-direct-claim:{digest}"


def _validate_direct_ticket(
    ticket: RunnerDirectObjectTicket,
    *,
    expected_size: int,
    expected_sha256: str,
    deadline_at: datetime,
) -> None:
    """Validate one transient direct-object GET capability before use."""
    if ticket.method != "GET":
        raise _TransferFailure(
            RunnerTransferFailure.PROTOCOL_VIOLATION,
            reason="direct_ticket_method_invalid",
        )
    if not 1 <= len(ticket.url.encode()) <= 8192:
        raise _TransferFailure(
            RunnerTransferFailure.PROTOCOL_VIOLATION,
            reason="direct_ticket_url_invalid",
        )
    try:
        parsed = urlsplit(ticket.url)
        port = parsed.port
    except ValueError:
        raise _TransferFailure(
            RunnerTransferFailure.PROTOCOL_VIOLATION,
            reason="direct_ticket_url_invalid",
        ) from None
    if (
        parsed.scheme not in {"http", "https"}
        or parsed.hostname is None
        or parsed.username is not None
        or parsed.password is not None
        or parsed.fragment
        or (port is not None and not 1 <= port <= 65_535)
    ):
        raise _TransferFailure(
            RunnerTransferFailure.PROTOCOL_VIOLATION,
            reason="direct_ticket_url_invalid",
        )
    if (
        ticket.expires_at.tzinfo is None
        or ticket.expires_at.utcoffset() is None
        or ticket.expires_at <= datetime.now(UTC)
        or ticket.expires_at > deadline_at
    ):
        raise _TransferFailure(
            RunnerTransferFailure.DEADLINE_EXCEEDED,
            reason="direct_ticket_expiry_invalid",
        )
    if (
        ticket.expected_size != expected_size
        or ticket.expected_sha256 != expected_sha256
    ):
        raise _TransferFailure(
            RunnerTransferFailure.PROTOCOL_VIOLATION,
            reason="direct_ticket_manifest_mismatch",
        )
    if len(ticket.headers) > 64:
        raise _TransferFailure(
            RunnerTransferFailure.PROTOCOL_VIOLATION,
            reason="direct_ticket_headers_invalid",
        )
    for name, value in ticket.headers.items():
        if (
            not isinstance(name, str)
            or not isinstance(value, str)
            or not name
            or len(name.encode()) > 256
            or len(value.encode()) > 8192
            or any(character in name for character in "\r\n:")
            or any(ord(character) < 32 or ord(character) == 127 for character in value)
        ):
            raise _TransferFailure(
                RunnerTransferFailure.PROTOCOL_VIOLATION,
                reason="direct_ticket_headers_invalid",
            )


def _direct_ticket_expired(
    ticket: RunnerDirectObjectTicket,
    deadline_at: datetime,
) -> bool:
    """Return whether a ticket is expired and can be safely reacquired."""
    return (
        ticket.expires_at.tzinfo is not None
        and ticket.expires_at.utcoffset() is not None
        and ticket.expires_at <= datetime.now(UTC)
        and ticket.expires_at <= deadline_at
    )


def _open_parent(path: str, *, create: bool) -> _OpenedFile:
    candidate = PurePath(path)
    if (
        not candidate.is_absolute()
        or not candidate.name
        or candidate.name in {".", ".."}
    ):
        raise _TransferFailure(
            RunnerTransferFailure.PROTOCOL_VIOLATION,
            reason="runtime_path_invalid",
        )
    parent_fd = os.open("/", os.O_RDONLY | os.O_DIRECTORY)
    try:
        components = candidate.parts[1:-1]
        for component in components:
            if component in {".", ".."}:
                raise _TransferFailure(
                    RunnerTransferFailure.PROTOCOL_VIOLATION,
                    reason="runtime_path_traversal",
                )
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
        return _OpenedFile(descriptor=parent_fd, name=candidate.name)
    except BaseException:
        os.close(parent_fd)
        raise


def _destination_observation(
    parent_fd: int,
    name: str,
) -> _DestinationObservation:
    """Capture only safe type, size, and timestamp evidence for one entry."""
    try:
        value = os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
    except FileNotFoundError:
        return _DestinationObservation(
            evidence=RunnerTransferDestinationConflictEvidence(
                kind="missing",
                size=None,
                modified_at=datetime.now(UTC),
            ),
            identity=None,
        )
    if stat.S_ISREG(value.st_mode):
        kind = "file"
        size = value.st_size
        identity = _regular_identity(value)
    elif stat.S_ISLNK(value.st_mode):
        kind = "symlink"
        size = None
        identity = None
    elif stat.S_ISDIR(value.st_mode):
        kind = "directory"
        size = None
        identity = None
    else:
        kind = "other"
        size = None
        identity = None
    return _DestinationObservation(
        evidence=RunnerTransferDestinationConflictEvidence(
            kind=kind,
            size=size,
            modified_at=datetime.fromtimestamp(value.st_mtime, tz=UTC),
        ),
        identity=identity,
    )


def _regular_identity(value: os.stat_result) -> _FileIdentity:
    if not stat.S_ISREG(value.st_mode):
        raise _TransferFailure(
            RunnerTransferFailure.PROTOCOL_VIOLATION,
            reason="upload_source_not_regular",
        )
    return _FileIdentity(
        value.st_dev, value.st_ino, value.st_size, value.st_mtime_ns, value.st_ctime_ns
    )


def _write_all(fd: int, data: bytes) -> None:
    view = memoryview(data)
    while view:
        written = os.write(fd, view)
        view = view[written:]


def _open_temporary_file(parent_fd: int) -> _OpenedFile:
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
        return _OpenedFile(descriptor=descriptor, name=name)
    raise OSError("could not allocate a unique Runtime transfer staging file")


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
