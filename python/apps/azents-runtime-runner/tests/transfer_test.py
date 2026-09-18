"""Runtime Runner transfer manager and filesystem safety tests."""

import asyncio
import contextlib
import dataclasses
import errno
import hashlib
import os
import threading
from collections.abc import AsyncIterator, Callable, Mapping
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import cast

import grpc
import pytest
from aiohttp import web
from aiohttp.test_utils import TestServer
from azents_runtime_control.grpc_runner_transfer_client import (
    RunnerDirectObjectTicket,
    RunnerDownloadChunk,
    RunnerDownloadComplete,
    RunnerUploadComplete,
    RunnerUploadResult,
)
from azents_runtime_control.runner_transfer import (
    RunnerTransferCancel,
    RunnerTransferCancelReason,
    RunnerTransferDirection,
    RunnerTransferFailure,
    RunnerTransferIdentity,
    RunnerTransferIntent,
    RunnerTransferOutcome,
    RunnerTransferResult,
    RunnerTransferSourceTransport,
)
from azents_runtime_control.transfer import (
    RUNNER_TRANSFER_CAPABILITY,
    RUNNER_TRANSFER_PROTOCOL_VERSION,
)

import azents_runtime_runner.transfer as transfer_module
from azents_runtime_runner.transfer import (
    RunnerTransferManager,
    _OpenedFile,
    _TransferKey,
)
from azents_runtime_runner.workspace import Workspace

_UNRESTRICTED_WORKSPACE = Workspace("/tmp")


@pytest.fixture
def tmpfs_path(tmp_path: Path) -> Path:
    """Provide an ordinary writable parent filesystem for transfer tests."""
    return tmp_path


class _Control:
    def __init__(self) -> None:
        self.results: list[RunnerTransferResult] = []
        self.result_ready = asyncio.Event()

    async def append_runner_transfer_result(self, result: RunnerTransferResult) -> None:
        self.results.append(result)
        self.result_ready.set()


class _BlockingControl(_Control):
    def __init__(self) -> None:
        super().__init__()
        self.entered = asyncio.Event()
        self.release = asyncio.Event()

    async def append_runner_transfer_result(self, result: RunnerTransferResult) -> None:
        self.entered.set()
        await self.release.wait()
        await super().append_runner_transfer_result(result)


class _FailingBlockingControl(_Control):
    def __init__(self) -> None:
        super().__init__()
        self.entered = asyncio.Event()
        self.release = asyncio.Event()

    async def append_runner_transfer_result(self, result: RunnerTransferResult) -> None:
        del result
        self.entered.set()
        await self.release.wait()
        raise RuntimeError("injected result sink failure")


class _Transfer:
    def __init__(
        self,
        frames: tuple[RunnerDownloadChunk | RunnerDownloadComplete, ...] = (),
    ) -> None:
        self.frames = frames
        self.download_calls = 0
        self.upload_calls = 0

    async def download(
        self,
        identity: RunnerTransferIdentity,
        *,
        timeout: float,
    ) -> AsyncIterator[RunnerDownloadChunk | RunnerDownloadComplete]:
        del identity, timeout
        self.download_calls += 1
        for frame in self.frames:
            yield frame

    async def claim_direct_object(
        self,
        identity: RunnerTransferIdentity,
        *,
        dispatch_id: str,
        claim_id: str,
        timeout: float,
    ) -> RunnerDirectObjectTicket:
        del identity, dispatch_id, claim_id, timeout
        raise AssertionError("direct object claim is not configured")

    async def upload(
        self,
        identity: RunnerTransferIdentity,
        frames: AsyncIterator[RunnerDownloadChunk | RunnerUploadComplete],
        *,
        timeout: float,
    ) -> RunnerUploadResult:
        del identity, timeout
        self.upload_calls += 1
        actual_size = 0
        digest = hashlib.sha256()
        async for frame in frames:
            if isinstance(frame, RunnerDownloadChunk):
                actual_size += len(frame.data)
                digest.update(frame.data)
        return RunnerUploadResult(actual_size=actual_size, sha256=digest.hexdigest())


class _DirectTransfer(_Transfer):
    def __init__(self, ticket: RunnerDirectObjectTicket) -> None:
        super().__init__()
        self.ticket = ticket
        self.claim_calls = 0
        self.claim_arguments: tuple[str, str] | None = None

    async def claim_direct_object(
        self,
        identity: RunnerTransferIdentity,
        *,
        dispatch_id: str,
        claim_id: str,
        timeout: float,
    ) -> RunnerDirectObjectTicket:
        del identity, timeout
        self.claim_calls += 1
        self.claim_arguments = (dispatch_id, claim_id)
        return self.ticket


async def _result(control: _Control) -> RunnerTransferResult:
    await asyncio.wait_for(control.result_ready.wait(), timeout=1)
    assert control.results
    return control.results[-1]


def _intent(
    path: Path,
    *,
    direction: RunnerTransferDirection = RunnerTransferDirection.DOWNLOAD,
    data: bytes = b"transfer bytes",
    deadline_at: datetime | None = None,
    transfer_id: str = "transfer-1",
    attempt_id: str = "attempt-1",
    overwrite: bool = False,
    conflict_precondition: bytes | None = None,
    source_transport: RunnerTransferSourceTransport = (
        RunnerTransferSourceTransport.TRANSFER_OBJECT
    ),
) -> RunnerTransferIntent:
    return RunnerTransferIntent(
        identity=RunnerTransferIdentity(
            transfer_id=transfer_id,
            attempt_id=attempt_id,
            runtime_id="runtime-1",
            runner_generation=1,
        ),
        direction=direction,
        operation_id="operation-1",
        owner_session_id="session-1",
        runtime_path=str(path),
        overwrite=overwrite,
        expected_size=len(data),
        expected_sha256=(
            hashlib.sha256(data).hexdigest()
            if direction is RunnerTransferDirection.DOWNLOAD
            else None
        ),
        deadline_at=deadline_at or datetime.now(UTC) + timedelta(minutes=1),
        protocol_version=RUNNER_TRANSFER_PROTOCOL_VERSION,
        capability=RUNNER_TRANSFER_CAPABILITY,
        dispatch_id="dispatch-1",
        conflict_precondition=conflict_precondition,
        source_transport=source_transport,
    )


@pytest.mark.asyncio
async def test_invalid_intent_does_not_block_control_receiver() -> None:
    """Admission returns before a blocked metadata result can be delivered."""
    control = _BlockingControl()
    transfer = _Transfer()
    manager = RunnerTransferManager(
        control=control,
        transfer=transfer,
        accepted_generation=lambda: 1,
        workspace=_UNRESTRICTED_WORKSPACE,
        http_proxy=None,
    )
    intent = _intent(Path("/tmp/unused"), deadline_at=datetime.now(UTC))

    await asyncio.wait_for(manager.handle_intent(intent), timeout=0.1)
    await asyncio.wait_for(control.entered.wait(), timeout=1)

    assert transfer.download_calls == 0
    control.release.set()
    assert (await _result(control)).failure is RunnerTransferFailure.PROTOCOL_VIOLATION
    await manager.close()


@pytest.mark.asyncio
async def test_invalid_intent_logs_bounded_validation_reason(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Intent rejection identifies the failed check without logging its path."""
    control = _Control()
    manager = RunnerTransferManager(
        control=control,
        transfer=_Transfer(),
        accepted_generation=lambda: 2,
        workspace=_UNRESTRICTED_WORKSPACE,
        http_proxy=None,
    )
    intent = _intent(Path("/workspace/agent/private-name.txt"))

    await manager.handle_intent(intent)

    assert (await _result(control)).failure is RunnerTransferFailure.PROTOCOL_VIOLATION
    failure = next(
        record
        for record in caplog.records
        if record.getMessage() == "Runtime Runner transfer failed"
    )
    assert failure.__dict__["failure_source"] == "intent_admission"
    assert failure.__dict__["failure_reason"] == "runner_generation_mismatch"
    assert failure.__dict__["grpc_status"] is None
    assert "private-name.txt" not in str(failure.__dict__)
    await manager.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("grpc_detail", ["Transfer is unavailable", "Upload failed"])
async def test_upload_logs_server_grpc_rejection_reason(
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
    grpc_detail: str,
) -> None:
    """Data-RPC rejection logs the server-owned reason and status."""
    source = tmp_path / "source.bin"
    data = b"upload bytes"
    source.write_bytes(data)

    class _RejectedTransfer(_Transfer):
        async def upload(
            self,
            identity: RunnerTransferIdentity,
            frames: AsyncIterator[RunnerDownloadChunk | RunnerUploadComplete],
            *,
            timeout: float,
        ) -> RunnerUploadResult:
            del identity, frames, timeout
            metadata = grpc.aio.Metadata()
            raise grpc.aio.AioRpcError(
                grpc.StatusCode.FAILED_PRECONDITION,
                metadata,
                metadata,
                grpc_detail,
                None,
            )

    control = _Control()
    manager = RunnerTransferManager(
        control=control,
        transfer=_RejectedTransfer(),
        accepted_generation=lambda: 1,
        workspace=_UNRESTRICTED_WORKSPACE,
        http_proxy=None,
    )

    await manager.handle_intent(
        _intent(
            source,
            direction=RunnerTransferDirection.UPLOAD,
            data=data,
        )
    )

    assert (await _result(control)).failure is RunnerTransferFailure.PROTOCOL_VIOLATION
    failure = next(
        record
        for record in caplog.records
        if record.getMessage() == "Runtime Runner transfer failed"
    )
    assert failure.__dict__["failure_source"] == "grpc"
    assert failure.__dict__["failure_reason"] == grpc_detail
    assert failure.__dict__["grpc_status"] == "FAILED_PRECONDITION"
    await manager.close()


@pytest.mark.asyncio
async def test_direct_download_claims_http_source_and_publishes_atomically(
    tmpfs_path: Path,
) -> None:
    """Direct-object downloads use the exact claim and never invoke gRPC bytes."""
    data = b"direct object bytes"
    app = web.Application()

    async def source(request: web.Request) -> web.Response:
        del request
        return web.Response(body=data)

    app.router.add_get("/source", source)
    server = TestServer(app)
    await server.start_server()
    try:
        ticket = RunnerDirectObjectTicket(
            method="GET",
            url=str(server.make_url("/source")),
            expires_at=datetime.now(UTC) + timedelta(minutes=1),
            headers={},
            expected_size=len(data),
            expected_sha256=hashlib.sha256(data).hexdigest(),
        )
        transfer = _DirectTransfer(ticket)
        control = _Control()
        manager = RunnerTransferManager(
            control=control,
            transfer=transfer,
            accepted_generation=lambda: 1,
            workspace=_UNRESTRICTED_WORKSPACE,
            http_proxy=None,
        )

        intent = _intent(
            tmpfs_path / "destination.bin",
            data=data,
            source_transport=RunnerTransferSourceTransport.DIRECT_OBJECT,
        )
        await manager.handle_intent(intent)

        result = await _result(control)
        assert result.outcome is RunnerTransferOutcome.SUCCEEDED
        assert result.destination_committed is True
        assert result.actual_size == len(data)
        assert result.sha256 == hashlib.sha256(data).hexdigest()
        assert (tmpfs_path / "destination.bin").read_bytes() == data
        assert transfer.claim_calls == 1
        assert transfer.claim_arguments is not None
        assert transfer.claim_arguments[0] == intent.dispatch_id
        assert transfer.download_calls == 0
        assert not list(tmpfs_path.glob(".azents-transfer-*"))
        await manager.close()
    finally:
        await server.close()


@pytest.mark.asyncio
async def test_direct_download_passes_provider_proxy_explicitly(
    tmpfs_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Direct HTTP downloads use the canonical Provider proxy explicitly."""
    data = b"direct object bytes"
    app = web.Application()

    async def source(request: web.Request) -> web.Response:
        del request
        return web.Response(body=data)

    app.router.add_get("/source", source)
    server = TestServer(app)
    await server.start_server()
    try:
        observed_proxies: list[str | None] = []
        original_request = cast(
            Callable[..., object],
            transfer_module.aiohttp.ClientSession.request,
        )

        def request(
            session: transfer_module.aiohttp.ClientSession,
            method: str,
            url: str,
            *,
            headers: Mapping[str, str] | None = None,
            allow_redirects: bool = True,
            proxy: str | None = None,
        ) -> object:
            observed_proxies.append(proxy)
            return original_request(
                session,
                method,
                url,
                headers=headers,
                allow_redirects=allow_redirects,
                proxy=None,
            )

        monkeypatch.setattr(
            transfer_module.aiohttp.ClientSession,
            "request",
            request,
        )
        ticket = RunnerDirectObjectTicket(
            method="GET",
            url=str(server.make_url("/source")),
            expires_at=datetime.now(UTC) + timedelta(minutes=1),
            headers={},
            expected_size=len(data),
            expected_sha256=hashlib.sha256(data).hexdigest(),
        )
        control = _Control()
        manager = RunnerTransferManager(
            control=control,
            transfer=_DirectTransfer(ticket),
            accepted_generation=lambda: 1,
            workspace=_UNRESTRICTED_WORKSPACE,
            http_proxy="http://runtime-proxy.azents-runtime.svc:8080",
        )

        await manager.handle_intent(
            _intent(
                tmpfs_path / "destination.bin",
                data=data,
                source_transport=RunnerTransferSourceTransport.DIRECT_OBJECT,
            )
        )

        result = await _result(control)
        assert result.outcome is RunnerTransferOutcome.SUCCEEDED
        assert observed_proxies == ["http://runtime-proxy.azents-runtime.svc:8080"]
        assert (tmpfs_path / "destination.bin").read_bytes() == data
        await manager.close()
    finally:
        await server.close()


@pytest.mark.asyncio
async def test_direct_download_reacquires_expired_ticket_at_byte_zero(
    tmpfs_path: Path,
) -> None:
    """An expired presigned GET is reacquired once without retaining body bytes."""
    data = b"direct object bytes"
    requests = 0
    app = web.Application()

    async def source(request: web.Request) -> web.Response:
        del request
        nonlocal requests
        requests += 1
        if requests == 1:
            return web.Response(status=403)
        return web.Response(body=data)

    app.router.add_get("/source", source)
    server = TestServer(app)
    await server.start_server()
    try:
        expires_at = datetime.now(UTC) + timedelta(minutes=1)
        tickets = (
            RunnerDirectObjectTicket(
                method="GET",
                url=str(server.make_url("/source")),
                expires_at=expires_at,
                headers={},
                expected_size=len(data),
                expected_sha256=hashlib.sha256(data).hexdigest(),
            ),
            RunnerDirectObjectTicket(
                method="GET",
                url=str(server.make_url("/source")),
                expires_at=expires_at,
                headers={},
                expected_size=len(data),
                expected_sha256=hashlib.sha256(data).hexdigest(),
            ),
        )

        class _ReacquiringDirectTransfer(_DirectTransfer):
            def __init__(self) -> None:
                super().__init__(tickets[0])
                self._tickets = iter(tickets)
                self.claim_ids: list[str] = []

            async def claim_direct_object(
                self,
                identity: RunnerTransferIdentity,
                *,
                dispatch_id: str,
                claim_id: str,
                timeout: float,
            ) -> RunnerDirectObjectTicket:
                del identity, timeout
                self.claim_calls += 1
                self.claim_arguments = (dispatch_id, claim_id)
                self.claim_ids.append(claim_id)
                return next(self._tickets, tickets[-1])

        transfer = _ReacquiringDirectTransfer()
        control = _Control()
        manager = RunnerTransferManager(
            control=control,
            transfer=transfer,
            accepted_generation=lambda: 1,
            workspace=_UNRESTRICTED_WORKSPACE,
            http_proxy=None,
        )
        intent = _intent(
            tmpfs_path / "destination.bin",
            data=data,
            source_transport=RunnerTransferSourceTransport.DIRECT_OBJECT,
        )

        await manager.handle_intent(intent)
        result = await _result(control)

        assert result.outcome is RunnerTransferOutcome.SUCCEEDED
        assert result.destination_committed is True
        assert (tmpfs_path / "destination.bin").read_bytes() == data
        assert requests == 2
        assert transfer.claim_calls == 2
        assert len(set(transfer.claim_ids)) == 1
        await manager.close()
    finally:
        await server.close()


@pytest.mark.asyncio
async def test_direct_download_renews_exact_claim_while_http_body_is_open(
    tmpfs_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An open direct HTTP body renews the same exact claim before commit."""
    data = b"direct object bytes"
    first_chunk_sent = asyncio.Event()
    release_body = asyncio.Event()
    app = web.Application()

    async def source(request: web.Request) -> web.StreamResponse:
        response = web.StreamResponse(status=200)
        await response.prepare(request)
        try:
            await response.write(data)
            first_chunk_sent.set()
            await release_body.wait()
            await response.write_eof()
        finally:
            release_body.set()
        return response

    app.router.add_get("/source", source)
    server = TestServer(app)
    await server.start_server()
    try:
        ticket = RunnerDirectObjectTicket(
            method="GET",
            url=str(server.make_url("/source")),
            expires_at=datetime.now(UTC) + timedelta(minutes=1),
            headers={},
            expected_size=len(data),
            expected_sha256=hashlib.sha256(data).hexdigest(),
        )

        class _RenewingDirectTransfer(_DirectTransfer):
            def __init__(self) -> None:
                super().__init__(ticket)
                self.claim_ids: list[str] = []
                self.renewed = asyncio.Event()

            async def claim_direct_object(
                self,
                identity: RunnerTransferIdentity,
                *,
                dispatch_id: str,
                claim_id: str,
                timeout: float,
            ) -> RunnerDirectObjectTicket:
                self.claim_ids.append(claim_id)
                result = await super().claim_direct_object(
                    identity,
                    dispatch_id=dispatch_id,
                    claim_id=claim_id,
                    timeout=timeout,
                )
                if len(self.claim_ids) == 2:
                    self.renewed.set()
                return result

        monkeypatch.setattr(transfer_module, "STREAM_OWNER_RENEWAL_SECONDS", 0.01)
        transfer = _RenewingDirectTransfer()
        control = _Control()
        manager = RunnerTransferManager(
            control=control,
            transfer=transfer,
            accepted_generation=lambda: 1,
            workspace=_UNRESTRICTED_WORKSPACE,
            http_proxy=None,
        )
        intent = _intent(
            tmpfs_path / "destination.bin",
            data=data,
            source_transport=RunnerTransferSourceTransport.DIRECT_OBJECT,
        )

        await manager.handle_intent(intent)
        await asyncio.wait_for(first_chunk_sent.wait(), timeout=1)
        await asyncio.wait_for(transfer.renewed.wait(), timeout=1)

        assert len(transfer.claim_ids) >= 2
        assert len(set(transfer.claim_ids)) == 1
        assert transfer.claim_arguments == (intent.dispatch_id, transfer.claim_ids[0])

        release_body.set()
        result = await _result(control)
        assert result.outcome is RunnerTransferOutcome.SUCCEEDED
        assert result.destination_committed is True
        assert (tmpfs_path / "destination.bin").read_bytes() == data
        await manager.close()
    finally:
        release_body.set()
        with contextlib.suppress(Exception):
            await server.close()


@pytest.mark.asyncio
async def test_direct_download_renews_exact_claim_before_http_response_headers(
    tmpfs_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A slow HTTP response still renews its claim before headers arrive."""
    data = b"direct object bytes"
    request_started = asyncio.Event()
    release_headers = asyncio.Event()
    app = web.Application()

    async def source(request: web.Request) -> web.Response:
        request_started.set()
        await release_headers.wait()
        return web.Response(body=data)

    app.router.add_get("/source", source)
    server = TestServer(app)
    await server.start_server()
    try:
        ticket = RunnerDirectObjectTicket(
            method="GET",
            url=str(server.make_url("/source")),
            expires_at=datetime.now(UTC) + timedelta(minutes=1),
            headers={},
            expected_size=len(data),
            expected_sha256=hashlib.sha256(data).hexdigest(),
        )

        class _RenewingDirectTransfer(_DirectTransfer):
            def __init__(self) -> None:
                super().__init__(ticket)
                self.renewed = asyncio.Event()

            async def claim_direct_object(
                self,
                identity: RunnerTransferIdentity,
                *,
                dispatch_id: str,
                claim_id: str,
                timeout: float,
            ) -> RunnerDirectObjectTicket:
                result = await super().claim_direct_object(
                    identity,
                    dispatch_id=dispatch_id,
                    claim_id=claim_id,
                    timeout=timeout,
                )
                if self.claim_calls >= 2:
                    self.renewed.set()
                return result

        monkeypatch.setattr(transfer_module, "STREAM_OWNER_RENEWAL_SECONDS", 0.01)
        transfer = _RenewingDirectTransfer()
        control = _Control()
        manager = RunnerTransferManager(
            control=control,
            transfer=transfer,
            accepted_generation=lambda: 1,
            workspace=_UNRESTRICTED_WORKSPACE,
            http_proxy=None,
        )
        intent = _intent(
            tmpfs_path / "destination.bin",
            data=data,
            source_transport=RunnerTransferSourceTransport.DIRECT_OBJECT,
        )

        await manager.handle_intent(intent)
        await asyncio.wait_for(request_started.wait(), timeout=1)
        await asyncio.wait_for(transfer.renewed.wait(), timeout=1)
        assert transfer.claim_calls >= 2

        release_headers.set()
        result = await _result(control)
        assert result.outcome is RunnerTransferOutcome.SUCCEEDED
        assert result.destination_committed is True
        assert (tmpfs_path / "destination.bin").read_bytes() == data
        await manager.close()
    finally:
        release_headers.set()
        with contextlib.suppress(Exception):
            await server.close()


@pytest.mark.asyncio
async def test_direct_download_keeps_claim_renewal_through_staging_fsync(
    tmpfs_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Claim renewal remains active after EOF while staging is fsynced."""
    data = b"direct object bytes"
    fsync_started = threading.Event()
    release_fsync = threading.Event()
    app = web.Application()

    async def source(request: web.Request) -> web.Response:
        del request
        return web.Response(body=data)

    app.router.add_get("/source", source)
    server = TestServer(app)
    await server.start_server()
    try:
        ticket = RunnerDirectObjectTicket(
            method="GET",
            url=str(server.make_url("/source")),
            expires_at=datetime.now(UTC) + timedelta(minutes=1),
            headers={},
            expected_size=len(data),
            expected_sha256=hashlib.sha256(data).hexdigest(),
        )

        class _RenewingDirectTransfer(_DirectTransfer):
            def __init__(self) -> None:
                super().__init__(ticket)
                self.renewed = asyncio.Event()

            async def claim_direct_object(
                self,
                identity: RunnerTransferIdentity,
                *,
                dispatch_id: str,
                claim_id: str,
                timeout: float,
            ) -> RunnerDirectObjectTicket:
                result = await super().claim_direct_object(
                    identity,
                    dispatch_id=dispatch_id,
                    claim_id=claim_id,
                    timeout=timeout,
                )
                if self.claim_calls >= 2:
                    self.renewed.set()
                return result

        original_fsync = transfer_module.os.fsync

        def blocking_fsync(fd: int) -> None:
            fsync_started.set()
            if not release_fsync.wait(timeout=1):
                raise TimeoutError("test fsync release timed out")
            original_fsync(fd)

        monkeypatch.setattr(transfer_module.os, "fsync", blocking_fsync)
        monkeypatch.setattr(transfer_module, "STREAM_OWNER_RENEWAL_SECONDS", 0.01)
        transfer = _RenewingDirectTransfer()
        control = _Control()
        manager = RunnerTransferManager(
            control=control,
            transfer=transfer,
            accepted_generation=lambda: 1,
            workspace=_UNRESTRICTED_WORKSPACE,
            http_proxy=None,
        )
        intent = _intent(
            tmpfs_path / "destination.bin",
            data=data,
            source_transport=RunnerTransferSourceTransport.DIRECT_OBJECT,
        )

        await manager.handle_intent(intent)
        assert await asyncio.to_thread(fsync_started.wait, 1)
        await asyncio.wait_for(transfer.renewed.wait(), timeout=1)
        assert transfer.claim_calls >= 2

        release_fsync.set()
        result = await _result(control)
        assert result.outcome is RunnerTransferOutcome.SUCCEEDED
        assert result.destination_committed is True
        assert (tmpfs_path / "destination.bin").read_bytes() == data
        await manager.close()
    finally:
        release_fsync.set()
        with contextlib.suppress(Exception):
            await server.close()


@pytest.mark.asyncio
async def test_direct_download_stops_without_publication_when_claim_renewal_fails(
    tmpfs_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A failed direct claim renewal fences the HTTP download and staging file."""
    data = b"direct object bytes"
    first_chunk_sent = asyncio.Event()
    release_body = asyncio.Event()
    app = web.Application()

    async def source(request: web.Request) -> web.StreamResponse:
        response = web.StreamResponse(status=200)
        await response.prepare(request)
        try:
            await response.write(data)
            first_chunk_sent.set()
            await release_body.wait()
            await response.write_eof()
        finally:
            release_body.set()
        return response

    app.router.add_get("/source", source)
    server = TestServer(app)
    await server.start_server()
    try:
        ticket = RunnerDirectObjectTicket(
            method="GET",
            url=str(server.make_url("/source")),
            expires_at=datetime.now(UTC) + timedelta(minutes=1),
            headers={},
            expected_size=len(data),
            expected_sha256=hashlib.sha256(data).hexdigest(),
        )

        class _FailingRenewalTransfer(_DirectTransfer):
            async def claim_direct_object(
                self,
                identity: RunnerTransferIdentity,
                *,
                dispatch_id: str,
                claim_id: str,
                timeout: float,
            ) -> RunnerDirectObjectTicket:
                if self.claim_calls == 1:
                    raise RuntimeError("renewal failed")
                return await super().claim_direct_object(
                    identity,
                    dispatch_id=dispatch_id,
                    claim_id=claim_id,
                    timeout=timeout,
                )

        monkeypatch.setattr(transfer_module, "STREAM_OWNER_RENEWAL_SECONDS", 0.01)
        transfer = _FailingRenewalTransfer(ticket)
        control = _Control()
        manager = RunnerTransferManager(
            control=control,
            transfer=transfer,
            accepted_generation=lambda: 1,
            workspace=_UNRESTRICTED_WORKSPACE,
            http_proxy=None,
        )
        intent = _intent(
            tmpfs_path / "destination.bin",
            data=data,
            source_transport=RunnerTransferSourceTransport.DIRECT_OBJECT,
        )

        await manager.handle_intent(intent)
        await asyncio.wait_for(first_chunk_sent.wait(), timeout=1)
        result = await _result(control)

        assert result.outcome is RunnerTransferOutcome.FAILED
        assert result.failure is RunnerTransferFailure.STREAM_FAILED
        assert transfer.claim_calls == 1
        assert not (tmpfs_path / "destination.bin").exists()
        assert not list(tmpfs_path.glob(".azents-transfer-*"))
        release_body.set()
        await manager.close()
    finally:
        release_body.set()
        with contextlib.suppress(Exception):
            await server.close()


@pytest.mark.asyncio
async def test_direct_download_cancellation_closes_http_body_without_publication(
    tmpfs_path: Path,
) -> None:
    """Cancellation closes a direct HTTP response and removes local staging."""
    data = b"direct object bytes"
    first_chunk_sent = asyncio.Event()
    release_body = asyncio.Event()
    app = web.Application()

    async def source(request: web.Request) -> web.StreamResponse:
        response = web.StreamResponse(status=200)
        await response.prepare(request)
        try:
            await response.write(data)
            first_chunk_sent.set()
            await release_body.wait()
            await response.write_eof()
        finally:
            release_body.set()
        return response

    app.router.add_get("/source", source)
    server = TestServer(app)
    await server.start_server()
    try:
        ticket = RunnerDirectObjectTicket(
            method="GET",
            url=str(server.make_url("/source")),
            expires_at=datetime.now(UTC) + timedelta(minutes=1),
            headers={},
            expected_size=len(data),
            expected_sha256=hashlib.sha256(data).hexdigest(),
        )
        control = _Control()
        manager = RunnerTransferManager(
            control=control,
            transfer=_DirectTransfer(ticket),
            accepted_generation=lambda: 1,
            workspace=_UNRESTRICTED_WORKSPACE,
            http_proxy=None,
        )
        intent = _intent(
            tmpfs_path / "destination.bin",
            data=data,
            source_transport=RunnerTransferSourceTransport.DIRECT_OBJECT,
        )

        await manager.handle_intent(intent)
        await asyncio.wait_for(first_chunk_sent.wait(), timeout=1)
        await manager.handle_cancel(
            RunnerTransferCancel(
                identity=intent.identity,
                operation_id=intent.operation_id,
                dispatch_id=intent.dispatch_id,
                reason=RunnerTransferCancelReason.CALLER,
            )
        )

        result = await _result(control)
        assert result.outcome is RunnerTransferOutcome.CANCELLED
        assert result.failure is RunnerTransferFailure.CANCELLED
        assert not (tmpfs_path / "destination.bin").exists()
        assert not list(tmpfs_path.glob(".azents-transfer-*"))
        release_body.set()
        await manager.close()
    finally:
        release_body.set()
        with contextlib.suppress(Exception):
            await server.close()


@pytest.mark.asyncio
async def test_direct_download_rejects_ticket_manifest_without_destination(
    tmpfs_path: Path,
) -> None:
    """A direct ticket that changes the manifest cannot publish bytes."""
    data = b"direct object bytes"
    ticket = RunnerDirectObjectTicket(
        method="GET",
        url="http://127.0.0.1:1/source",
        expires_at=datetime.now(UTC) + timedelta(minutes=1),
        headers={},
        expected_size=len(data) + 1,
        expected_sha256=hashlib.sha256(data).hexdigest(),
    )
    control = _Control()
    manager = RunnerTransferManager(
        control=control,
        transfer=_DirectTransfer(ticket),
        accepted_generation=lambda: 1,
        workspace=_UNRESTRICTED_WORKSPACE,
        http_proxy=None,
    )

    await manager.handle_intent(
        _intent(
            tmpfs_path / "destination.bin",
            data=data,
            source_transport=RunnerTransferSourceTransport.DIRECT_OBJECT,
        )
    )

    result = await _result(control)
    assert result.failure is RunnerTransferFailure.PROTOCOL_VIOLATION
    assert not (tmpfs_path / "destination.bin").exists()
    assert not list(tmpfs_path.glob(".azents-transfer-*"))
    await manager.close()


@pytest.mark.asyncio
async def test_download_rejects_symlink_parent_without_touching_target(
    tmpfs_path: Path,
) -> None:
    """Download traversal never follows a substituted destination parent."""
    outside = tmpfs_path / "outside"
    outside.mkdir()
    link = tmpfs_path / "link"
    link.symlink_to(outside, target_is_directory=True)
    data = b"safe"
    control = _Control()
    manager = RunnerTransferManager(
        control=control,
        transfer=_Transfer(
            (
                RunnerDownloadChunk(offset=0, data=data),
                RunnerDownloadComplete(
                    actual_size=len(data), sha256=hashlib.sha256(data).hexdigest()
                ),
            )
        ),
        accepted_generation=lambda: 1,
        workspace=_UNRESTRICTED_WORKSPACE,
        http_proxy=None,
    )

    await manager.handle_intent(_intent(link / "destination.bin", data=data))

    result = await _result(control)
    assert result.outcome is RunnerTransferOutcome.FAILED
    assert result.failure is RunnerTransferFailure.DESTINATION_FAILED
    assert not (outside / "destination.bin").exists()
    await manager.close()


@pytest.mark.asyncio
async def test_upload_local_io_failure_emits_valid_integrity_result(
    tmp_path: Path,
) -> None:
    """An unreadable upload source cannot suppress a bounded transfer result."""
    control = _Control()
    manager = RunnerTransferManager(
        control=control,
        transfer=_Transfer(),
        accepted_generation=lambda: 1,
        workspace=_UNRESTRICTED_WORKSPACE,
        http_proxy=None,
    )

    await manager.handle_intent(
        _intent(
            tmp_path / "missing.bin",
            direction=RunnerTransferDirection.UPLOAD,
        )
    )

    result = await _result(control)
    assert result.outcome is RunnerTransferOutcome.FAILED
    assert result.failure is RunnerTransferFailure.INTEGRITY_FAILED
    assert result.destination_committed is False
    await manager.close()


@pytest.mark.asyncio
async def test_download_atomically_replaces_existing_destination(
    tmpfs_path: Path,
) -> None:
    """Explicit current conflict evidence permits one atomic replacement."""
    destination = tmpfs_path / "destination.bin"
    destination.write_bytes(b"old")
    data = b"new verified content"
    control = _Control()
    transfer = _Transfer(
        (
            RunnerDownloadChunk(offset=0, data=data),
            RunnerDownloadComplete(
                actual_size=len(data), sha256=hashlib.sha256(data).hexdigest()
            ),
        )
    )
    manager = RunnerTransferManager(
        control=control,
        transfer=transfer,
        accepted_generation=lambda: 1,
        workspace=_UNRESTRICTED_WORKSPACE,
        http_proxy=None,
    )

    first = _intent(destination, data=data)
    await manager.handle_intent(first)
    conflict = await _result(control)

    assert conflict.failure is RunnerTransferFailure.DESTINATION_CONFLICT
    assert conflict.destination_conflict is not None
    assert conflict.destination_conflict.kind == "file"
    assert conflict.destination_conflict.size == len(b"old")
    assert conflict.conflict_precondition is not None
    retry = _intent(
        destination,
        data=data,
        transfer_id="transfer-2",
        attempt_id="attempt-2",
        overwrite=True,
        conflict_precondition=conflict.conflict_precondition,
    )
    await manager.handle_intent(retry)
    await asyncio.wait_for(_wait_for_result_count(control, expected=2), timeout=1)

    result = control.results[-1]
    assert result.outcome is RunnerTransferOutcome.SUCCEEDED
    assert result.destination_committed is True
    assert destination.read_bytes() == data
    assert not list(tmpfs_path.glob(".azents-transfer-*"))
    await manager.close()


@pytest.mark.asyncio
async def test_overwrite_rejects_changed_destination_and_preserves_newer_file(
    tmpfs_path: Path,
) -> None:
    """A token from one destination identity cannot replace a newer identity."""
    destination = tmpfs_path / "destination.bin"
    destination.write_bytes(b"old")
    newer = tmpfs_path / "newer.bin"
    newer.write_bytes(b"newer")
    data = b"replacement"
    control = _Control()
    manager = RunnerTransferManager(
        control=control,
        transfer=_Transfer(
            (
                RunnerDownloadChunk(offset=0, data=data),
                RunnerDownloadComplete(
                    actual_size=len(data), sha256=hashlib.sha256(data).hexdigest()
                ),
            )
        ),
        accepted_generation=lambda: 1,
        workspace=_UNRESTRICTED_WORKSPACE,
        http_proxy=None,
    )
    first = _intent(destination, data=data)
    await manager.handle_intent(first)
    conflict = await _result(control)
    assert conflict.conflict_precondition is not None
    os.replace(newer, destination)

    await manager.handle_intent(
        _intent(
            destination,
            data=data,
            transfer_id="transfer-2",
            attempt_id="attempt-2",
            overwrite=True,
            conflict_precondition=conflict.conflict_precondition,
        )
    )
    await asyncio.wait_for(_wait_for_result_count(control, expected=2), timeout=1)

    retry = control.results[-1]
    assert retry.failure is RunnerTransferFailure.DESTINATION_CONFLICT
    assert retry.destination_conflict is not None
    assert retry.destination_conflict.kind == "file"
    assert destination.read_bytes() == b"newer"
    await manager.close()


@pytest.mark.asyncio
async def test_overwrite_rejects_cross_path_precondition(
    tmpfs_path: Path,
) -> None:
    """A path-bound token never authorizes replacement of another destination."""
    original = tmpfs_path / "original.bin"
    original.write_bytes(b"original")
    other = tmpfs_path / "other.bin"
    other.write_bytes(b"other")
    data = b"replacement"
    control = _Control()
    manager = RunnerTransferManager(
        control=control,
        transfer=_Transfer(
            (
                RunnerDownloadChunk(offset=0, data=data),
                RunnerDownloadComplete(
                    actual_size=len(data), sha256=hashlib.sha256(data).hexdigest()
                ),
            )
        ),
        accepted_generation=lambda: 1,
        workspace=_UNRESTRICTED_WORKSPACE,
        http_proxy=None,
    )
    await manager.handle_intent(_intent(original, data=data))
    conflict = await _result(control)
    assert conflict.conflict_precondition is not None

    await manager.handle_intent(
        _intent(
            other,
            data=data,
            transfer_id="transfer-2",
            attempt_id="attempt-2",
            overwrite=True,
            conflict_precondition=conflict.conflict_precondition,
        )
    )
    await asyncio.wait_for(_wait_for_result_count(control, expected=2), timeout=1)

    retry = control.results[-1]
    assert retry.failure is RunnerTransferFailure.DESTINATION_CONFLICT
    assert other.read_bytes() == b"other"
    await manager.close()


@pytest.mark.asyncio
async def test_overwrite_rejects_symlink_destination(
    tmpfs_path: Path,
) -> None:
    """A symlink substituted after conflict is never atomically replaced."""
    destination = tmpfs_path / "destination.bin"
    destination.write_bytes(b"old")
    outside = tmpfs_path / "outside.bin"
    outside.write_bytes(b"outside")
    data = b"replacement"
    control = _Control()
    manager = RunnerTransferManager(
        control=control,
        transfer=_Transfer(
            (
                RunnerDownloadChunk(offset=0, data=data),
                RunnerDownloadComplete(
                    actual_size=len(data), sha256=hashlib.sha256(data).hexdigest()
                ),
            )
        ),
        accepted_generation=lambda: 1,
        workspace=_UNRESTRICTED_WORKSPACE,
        http_proxy=None,
    )
    await manager.handle_intent(_intent(destination, data=data))
    conflict = await _result(control)
    assert conflict.conflict_precondition is not None
    destination.unlink()
    destination.symlink_to(outside)

    await manager.handle_intent(
        _intent(
            destination,
            data=data,
            transfer_id="transfer-2",
            attempt_id="attempt-2",
            overwrite=True,
            conflict_precondition=conflict.conflict_precondition,
        )
    )
    await asyncio.wait_for(_wait_for_result_count(control, expected=2), timeout=1)

    retry = control.results[-1]
    assert retry.failure is RunnerTransferFailure.DESTINATION_CONFLICT
    assert retry.destination_conflict is not None
    assert retry.destination_conflict.kind == "symlink"
    assert outside.read_bytes() == b"outside"
    await manager.close()


@pytest.mark.asyncio
async def test_untrusted_transfer_identifiers_cannot_escape_staging_directory(
    tmpfs_path: Path,
) -> None:
    """Random staging names ignore untrusted transfer identifiers."""
    destination = tmpfs_path / "destination.bin"
    data = b"staged safely"
    control = _Control()
    manager = RunnerTransferManager(
        control=control,
        transfer=_Transfer(
            (
                RunnerDownloadChunk(offset=0, data=data),
                RunnerDownloadComplete(
                    actual_size=len(data), sha256=hashlib.sha256(data).hexdigest()
                ),
            )
        ),
        accepted_generation=lambda: 1,
        workspace=_UNRESTRICTED_WORKSPACE,
        http_proxy=None,
    )
    intent = _intent(
        destination,
        data=data,
        transfer_id="../../attacker-controlled/path",
    )

    await manager.handle_intent(intent)

    assert (await _result(control)).outcome is RunnerTransferOutcome.SUCCEEDED
    assert destination.read_bytes() == data
    assert not list(tmpfs_path.parent.glob("attacker-controlled"))
    await manager.close()


@pytest.mark.asyncio
async def test_exact_duplicate_intent_reuses_one_completed_result(
    tmpfs_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An exact repeated instruction cannot publish the destination twice."""
    destination = tmpfs_path / "destination.bin"
    data = b"deduplicated"
    control = _Control()
    manager = RunnerTransferManager(
        control=control,
        transfer=_Transfer(
            (
                RunnerDownloadChunk(offset=0, data=data),
                RunnerDownloadComplete(
                    actual_size=len(data), sha256=hashlib.sha256(data).hexdigest()
                ),
            )
        ),
        accepted_generation=lambda: 1,
        workspace=_UNRESTRICTED_WORKSPACE,
        http_proxy=None,
    )
    intent = _intent(destination, data=data)

    reaped = asyncio.Event()
    original_reap = manager._reap

    async def reap(key: _TransferKey) -> None:
        await original_reap(key)
        reaped.set()

    monkeypatch.setattr(manager, "_reap", reap)
    await manager.handle_intent(intent)
    assert (await _result(control)).outcome is RunnerTransferOutcome.SUCCEEDED
    await reaped.wait()
    await manager.handle_intent(intent)
    await asyncio.wait_for(
        _wait_for_result_count(control, expected=2),
        timeout=1,
    )

    assert len(control.results) == 2
    assert control.results[0] == control.results[1]
    assert destination.read_bytes() == data
    await manager.close()


@pytest.mark.asyncio
async def test_exact_cancel_emits_cancelled_result_without_publication(
    tmpfs_path: Path,
) -> None:
    """Cancellation targets the matching active task and cleans its staging file."""
    data = b"pending"
    started = asyncio.Event()
    release = asyncio.Event()

    class _BlockingTransfer(_Transfer):
        async def download(
            self,
            identity: RunnerTransferIdentity,
            *,
            timeout: float,
        ) -> AsyncIterator[RunnerDownloadChunk | RunnerDownloadComplete]:
            del identity, timeout
            started.set()
            await release.wait()
            yield RunnerDownloadChunk(offset=0, data=data)
            yield RunnerDownloadComplete(
                actual_size=len(data), sha256=hashlib.sha256(data).hexdigest()
            )

    destination = tmpfs_path / "destination.bin"
    control = _Control()
    manager = RunnerTransferManager(
        control=control,
        transfer=_BlockingTransfer(),
        accepted_generation=lambda: 1,
        workspace=_UNRESTRICTED_WORKSPACE,
        http_proxy=None,
    )
    intent = _intent(destination, data=data)

    await manager.handle_intent(intent)
    await asyncio.wait_for(started.wait(), timeout=1)
    await manager.handle_cancel(
        RunnerTransferCancel(
            identity=intent.identity,
            operation_id=intent.operation_id,
            dispatch_id=intent.dispatch_id,
            reason=RunnerTransferCancelReason.CALLER,
        )
    )

    result = await _result(control)
    assert result.outcome is RunnerTransferOutcome.CANCELLED
    assert result.failure is RunnerTransferFailure.CANCELLED
    assert not destination.exists()
    assert not list(tmpfs_path.glob(".azents-transfer-*"))
    release.set()
    await manager.close()


@pytest.mark.asyncio
async def test_conflicting_intent_for_active_identity_is_rejected_without_second_rpc(
    tmpfs_path: Path,
) -> None:
    """One transfer attempt cannot be repurposed with another dispatch identity."""
    data = b"pending"
    started = asyncio.Event()
    release = asyncio.Event()

    class _BlockingTransfer(_Transfer):
        async def download(
            self,
            identity: RunnerTransferIdentity,
            *,
            timeout: float,
        ) -> AsyncIterator[RunnerDownloadChunk | RunnerDownloadComplete]:
            del identity, timeout
            self.download_calls += 1
            started.set()
            await release.wait()
            yield RunnerDownloadChunk(offset=0, data=data)
            yield RunnerDownloadComplete(
                actual_size=len(data), sha256=hashlib.sha256(data).hexdigest()
            )

    control = _Control()
    transfer = _BlockingTransfer()
    manager = RunnerTransferManager(
        control=control,
        transfer=transfer,
        accepted_generation=lambda: 1,
        workspace=_UNRESTRICTED_WORKSPACE,
        http_proxy=None,
    )
    intent = _intent(tmpfs_path / "destination.bin", data=data)

    await manager.handle_intent(intent)
    await asyncio.wait_for(started.wait(), timeout=1)
    await manager.handle_intent(dataclasses.replace(intent, dispatch_id="dispatch-2"))

    result = await _result(control)
    assert result.failure is RunnerTransferFailure.PROTOCOL_VIOLATION
    assert transfer.download_calls == 1
    release.set()
    await manager.handle_cancel(
        RunnerTransferCancel(
            identity=intent.identity,
            operation_id=intent.operation_id,
            dispatch_id=intent.dispatch_id,
            reason=RunnerTransferCancelReason.CALLER,
        )
    )
    await manager.close()


@pytest.mark.asyncio
async def test_upload_snapshot_keeps_control_work_and_cancellation_responsive(
    tmpfs_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Slow snapshot I/O yields the event loop for Control work and cancellation."""
    source = tmpfs_path / "source.bin"
    source.write_bytes(b"x" * (2 * 1024 * 1024))
    entered_read = threading.Event()
    release_read = threading.Event()
    original_read = os.read

    def block_first_read(fd: int, size: int) -> bytes:
        if not entered_read.is_set():
            entered_read.set()
            release_read.wait(timeout=1)
        return original_read(fd, size)

    monkeypatch.setattr("azents_runtime_runner.transfer.os.read", block_first_read)
    control = _Control()
    manager = RunnerTransferManager(
        control=control,
        transfer=_Transfer(),
        accepted_generation=lambda: 1,
        workspace=_UNRESTRICTED_WORKSPACE,
        http_proxy=None,
    )
    intent = _intent(
        source,
        direction=RunnerTransferDirection.UPLOAD,
        data=b"x" * (2 * 1024 * 1024),
    )

    await manager.handle_intent(intent)
    assert await asyncio.to_thread(entered_read.wait, 1)
    heartbeat_completed = asyncio.Event()
    ordinary_control_completed = asyncio.Event()

    async def heartbeat() -> None:
        heartbeat_completed.set()

    async def ordinary_control_operation() -> None:
        ordinary_control_completed.set()

    await asyncio.wait_for(
        asyncio.gather(
            heartbeat(),
            ordinary_control_operation(),
            manager.handle_cancel(
                RunnerTransferCancel(
                    identity=intent.identity,
                    operation_id=intent.operation_id,
                    dispatch_id=intent.dispatch_id,
                    reason=RunnerTransferCancelReason.CALLER,
                )
            ),
        ),
        timeout=0.1,
    )
    assert heartbeat_completed.is_set()
    assert ordinary_control_completed.is_set()
    release_read.set()

    result = await _result(control)
    assert result.outcome is RunnerTransferOutcome.CANCELLED
    assert not list(tmpfs_path.glob(".azents-transfer-*"))
    await manager.close()


@pytest.mark.asyncio
async def test_successful_upload_leaves_no_mutable_snapshot_path(
    tmpfs_path: Path,
) -> None:
    """A completed upload removes its same-directory snapshot."""
    source = tmpfs_path / "source.bin"
    data = b"upload bytes"
    source.write_bytes(data)
    control = _Control()
    manager = RunnerTransferManager(
        control=control,
        transfer=_Transfer(),
        accepted_generation=lambda: 1,
        workspace=_UNRESTRICTED_WORKSPACE,
        http_proxy=None,
    )

    await manager.handle_intent(
        _intent(
            source,
            direction=RunnerTransferDirection.UPLOAD,
            data=data,
        )
    )

    assert (await _result(control)).outcome is RunnerTransferOutcome.SUCCEEDED
    assert not list(tmpfs_path.glob(".azents-transfer-*"))
    assert not list(tmpfs_path.glob(".azents-transfer-orphans"))
    await manager.close()


@pytest.mark.asyncio
async def test_upload_rejects_fifo_without_blocking_control(tmpfs_path: Path) -> None:
    """A FIFO source is rejected without synchronously blocking the event loop."""
    fifo = tmpfs_path / "source.fifo"
    os.mkfifo(fifo)
    control = _Control()
    manager = RunnerTransferManager(
        control=control,
        transfer=_Transfer(),
        accepted_generation=lambda: 1,
        workspace=_UNRESTRICTED_WORKSPACE,
        http_proxy=None,
    )
    heartbeat_completed = asyncio.Event()

    async def heartbeat() -> None:
        heartbeat_completed.set()

    await manager.handle_intent(
        _intent(
            fifo,
            direction=RunnerTransferDirection.UPLOAD,
            data=b"",
        )
    )
    await asyncio.wait_for(heartbeat(), timeout=0.1)

    result = await _result(control)
    assert heartbeat_completed.is_set()
    assert result.outcome is RunnerTransferOutcome.FAILED
    assert result.failure is RunnerTransferFailure.PROTOCOL_VIOLATION
    await manager.close()


@pytest.mark.asyncio
async def test_download_cleans_same_directory_stage_after_cancellation(
    tmpfs_path: Path,
) -> None:
    """An interrupted download removes its randomly named staging file."""
    started = asyncio.Event()
    release = asyncio.Event()
    data = b"pending"

    class _BlockingTransfer(_Transfer):
        async def download(
            self,
            identity: RunnerTransferIdentity,
            *,
            timeout: float,
        ) -> AsyncIterator[RunnerDownloadChunk | RunnerDownloadComplete]:
            del identity, timeout
            started.set()
            await release.wait()
            yield RunnerDownloadChunk(offset=0, data=data)
            yield RunnerDownloadComplete(
                actual_size=len(data), sha256=hashlib.sha256(data).hexdigest()
            )

    control = _Control()
    manager = RunnerTransferManager(
        control=control,
        transfer=_BlockingTransfer(),
        accepted_generation=lambda: 1,
        workspace=_UNRESTRICTED_WORKSPACE,
        http_proxy=None,
    )
    intent = _intent(tmpfs_path / "destination.bin", data=data)

    await manager.handle_intent(intent)
    await asyncio.wait_for(started.wait(), timeout=1)

    assert len(list(tmpfs_path.glob(".azents-transfer-*"))) == 1
    await manager.handle_cancel(
        RunnerTransferCancel(
            identity=intent.identity,
            operation_id=intent.operation_id,
            dispatch_id=intent.dispatch_id,
            reason=RunnerTransferCancelReason.CALLER,
        )
    )
    assert (await _result(control)).outcome is RunnerTransferOutcome.CANCELLED
    assert not list(tmpfs_path.glob(".azents-transfer-*"))
    release.set()
    await manager.close()


@pytest.mark.asyncio
async def test_download_fails_closed_when_staging_file_cannot_be_created(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A staging allocation failure leaves the destination unchanged."""
    destination = tmp_path / "destination.bin"
    data = b"safe"
    control = _Control()
    transfer = _Transfer(
        (
            RunnerDownloadChunk(offset=0, data=data),
            RunnerDownloadComplete(
                actual_size=len(data), sha256=hashlib.sha256(data).hexdigest()
            ),
        )
    )

    def fail_temporary_file_creation(parent_fd: int) -> _OpenedFile:
        del parent_fd
        raise OSError(errno.EOPNOTSUPP, "Operation not supported")

    monkeypatch.setattr(
        "azents_runtime_runner.transfer._open_temporary_file",
        fail_temporary_file_creation,
    )
    manager = RunnerTransferManager(
        control=control,
        transfer=transfer,
        accepted_generation=lambda: 1,
        workspace=_UNRESTRICTED_WORKSPACE,
        http_proxy=None,
    )

    await manager.handle_intent(_intent(destination, data=data))

    result = await _result(control)
    assert result.outcome is RunnerTransferOutcome.FAILED
    assert result.failure is RunnerTransferFailure.DESTINATION_FAILED
    assert transfer.download_calls == 0
    assert not destination.exists()
    await manager.close()


@pytest.mark.asyncio
async def test_close_does_not_wait_for_blocked_result_sink(tmpfs_path: Path) -> None:
    """Control result backpressure cannot prevent transfer-manager shutdown."""
    data = b"verified"
    control = _BlockingControl()
    manager = RunnerTransferManager(
        control=control,
        transfer=_Transfer(
            (
                RunnerDownloadChunk(offset=0, data=data),
                RunnerDownloadComplete(
                    actual_size=len(data), sha256=hashlib.sha256(data).hexdigest()
                ),
            )
        ),
        accepted_generation=lambda: 1,
        workspace=_UNRESTRICTED_WORKSPACE,
        http_proxy=None,
    )

    await manager.handle_intent(_intent(tmpfs_path / "destination.bin", data=data))
    await asyncio.wait_for(control.entered.wait(), timeout=1)

    await asyncio.wait_for(manager.close(), timeout=0.1)


@pytest.mark.asyncio
async def test_direct_claim_lease_closes_after_result_delivery(
    tmpfs_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A direct-object claim remains owned until Control observes the result."""
    control = _BlockingControl()
    manager = RunnerTransferManager(
        control=control,
        transfer=_Transfer(),
        accepted_generation=lambda: 1,
        workspace=_UNRESTRICTED_WORKSPACE,
        http_proxy=None,
    )
    lease_closed = asyncio.Event()

    class _Lease:
        async def close(self) -> None:
            lease_closed.set()

    async def download(
        intent: RunnerTransferIntent,
        cancelled: asyncio.Event,
        *,
        direct_claim_lease: list[object | None],
    ) -> RunnerTransferResult:
        del cancelled
        direct_claim_lease[0] = _Lease()  # type: ignore[assignment]
        return transfer_module._failed(
            intent,
            RunnerTransferFailure.STREAM_FAILED,
        )

    monkeypatch.setattr(manager, "_download", download)
    intent = _intent(
        tmpfs_path / "destination.bin",
        source_transport=RunnerTransferSourceTransport.DIRECT_OBJECT,
    )

    await manager.handle_intent(intent)
    await asyncio.wait_for(control.entered.wait(), timeout=1)
    assert not lease_closed.is_set()

    control.release.set()
    result = await _result(control)
    assert result.failure is RunnerTransferFailure.STREAM_FAILED
    await asyncio.wait_for(lease_closed.wait(), timeout=1)
    await manager.close()


@pytest.mark.asyncio
async def test_bounded_result_queue_backpressures_without_dropping_terminal_results(
    tmpfs_path: Path,
) -> None:
    """A full result queue delays admission instead of losing a terminal result."""
    control = _BlockingControl()
    manager = RunnerTransferManager(
        control=control,
        transfer=_Transfer(),
        accepted_generation=lambda: 1,
        workspace=_UNRESTRICTED_WORKSPACE,
        http_proxy=None,
        max_tombstones=1,
    )
    expired_at = datetime.now(UTC)
    first = _intent(
        tmpfs_path / "first.bin",
        deadline_at=expired_at,
        transfer_id="transfer-1",
    )
    second = _intent(
        tmpfs_path / "second.bin",
        deadline_at=expired_at,
        transfer_id="transfer-2",
    )
    third = _intent(
        tmpfs_path / "third.bin",
        deadline_at=expired_at,
        transfer_id="transfer-3",
    )

    await manager.handle_intent(first)
    await asyncio.wait_for(control.entered.wait(), timeout=1)
    await manager.handle_intent(second)
    third_admission = asyncio.create_task(manager.handle_intent(third))
    with pytest.raises(TimeoutError):
        await asyncio.wait_for(
            asyncio.shield(third_admission),
            timeout=0.01,
        )
    control.release.set()
    await asyncio.wait_for(third_admission, timeout=1)
    await asyncio.wait_for(
        _wait_for_result_count(control, expected=3),
        timeout=1,
    )

    assert [result.identity.transfer_id for result in control.results] == [
        "transfer-1",
        "transfer-2",
        "transfer-3",
    ]
    assert all(
        result.failure is RunnerTransferFailure.PROTOCOL_VIOLATION
        for result in control.results
    )
    await manager.close()


async def _wait_for_result_count(control: _Control, *, expected: int) -> None:
    while len(control.results) < expected:
        control.result_ready.clear()
        if len(control.results) >= expected:
            return
        await control.result_ready.wait()


@pytest.mark.asyncio
async def test_failed_result_sink_unblocks_queue_and_shutdown(
    tmpfs_path: Path,
) -> None:
    """A disconnected result sink cannot wedge later admission or close."""
    control = _FailingBlockingControl()
    manager = RunnerTransferManager(
        control=control,
        transfer=_Transfer(),
        accepted_generation=lambda: 1,
        workspace=_UNRESTRICTED_WORKSPACE,
        http_proxy=None,
        max_tombstones=1,
    )
    expired_at = datetime.now(UTC)
    first = _intent(
        tmpfs_path / "first.bin",
        deadline_at=expired_at,
        transfer_id="transfer-1",
    )
    second = _intent(
        tmpfs_path / "second.bin",
        deadline_at=expired_at,
        transfer_id="transfer-2",
    )
    third = _intent(
        tmpfs_path / "third.bin",
        deadline_at=expired_at,
        transfer_id="transfer-3",
    )
    fourth = _intent(
        tmpfs_path / "fourth.bin",
        deadline_at=expired_at,
        transfer_id="transfer-4",
    )

    await manager.handle_intent(first)
    await asyncio.wait_for(control.entered.wait(), timeout=1)
    await manager.handle_intent(second)
    third_admission = asyncio.create_task(manager.handle_intent(third))
    fourth_admission = asyncio.create_task(manager.handle_intent(fourth))
    pending_admissions = asyncio.gather(third_admission, fourth_admission)
    with pytest.raises(TimeoutError):
        await asyncio.wait_for(
            asyncio.shield(pending_admissions),
            timeout=0.01,
        )

    control.release.set()
    await asyncio.wait_for(
        pending_admissions,
        timeout=1,
    )
    await asyncio.wait_for(manager.close(), timeout=0.1)


@pytest.mark.asyncio
async def test_post_publication_cancellation_waits_for_successful_result_enqueue(
    tmpfs_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A cancellation after publication cannot erase the committed success result."""
    control = _BlockingControl()
    data = b"committed"
    manager = RunnerTransferManager(
        control=control,
        transfer=_Transfer(
            (
                RunnerDownloadChunk(offset=0, data=data),
                RunnerDownloadComplete(
                    actual_size=len(data), sha256=hashlib.sha256(data).hexdigest()
                ),
            )
        ),
        accepted_generation=lambda: 1,
        workspace=_UNRESTRICTED_WORKSPACE,
        http_proxy=None,
        max_tombstones=1,
    )
    expired_at = datetime.now(UTC)
    first = _intent(
        tmpfs_path / "first.bin",
        deadline_at=expired_at,
        transfer_id="transfer-1",
    )
    second = _intent(
        tmpfs_path / "second.bin",
        deadline_at=expired_at,
        transfer_id="transfer-2",
    )
    destination = tmpfs_path / "destination.bin"
    committed = _intent(destination, data=data, transfer_id="transfer-3")
    destination_committed = asyncio.Event()
    original_link = transfer_module.os.link

    def link(
        src: str,
        dst: str,
        *,
        src_dir_fd: int,
        dst_dir_fd: int,
        follow_symlinks: bool,
    ) -> None:
        original_link(
            src,
            dst,
            src_dir_fd=src_dir_fd,
            dst_dir_fd=dst_dir_fd,
            follow_symlinks=follow_symlinks,
        )
        destination_committed.set()

    monkeypatch.setattr(transfer_module.os, "link", link)

    await manager.handle_intent(first)
    await asyncio.wait_for(control.entered.wait(), timeout=1)
    await manager.handle_intent(second)
    await manager.handle_intent(committed)
    await destination_committed.wait()

    await manager.handle_cancel(
        RunnerTransferCancel(
            identity=committed.identity,
            operation_id=committed.operation_id,
            dispatch_id=committed.dispatch_id,
            reason=RunnerTransferCancelReason.CALLER,
        )
    )
    control.release.set()
    await asyncio.wait_for(
        _wait_for_result_count(control, expected=3),
        timeout=1,
    )

    committed_result = control.results[-1]
    assert destination.read_bytes() == data
    assert committed_result.identity == committed.identity
    assert committed_result.outcome is RunnerTransferOutcome.SUCCEEDED
    assert committed_result.destination_committed is True
    await manager.close()
