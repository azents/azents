"""Tests for trusted Runtime Workspace download materialization."""

import datetime
import hashlib
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from unittest.mock import AsyncMock

import pytest
from azcommon.infra.s3.service import S3ObjectIdentity, S3Service
from azents_runtime_control.grpc_transfer_coordinator_client import (
    CoordinatorOpaqueObjectHandle,
)
from azents_runtime_control.transfer import CoordinatorTransferIdentity

from azents.runtime.transfer.runtime_to_server import (
    RuntimeToServerConsumer,
    RuntimeToServerConsumerRequest,
    RuntimeToServerTransferRequest,
    VerifiedRuntimeUpload,
)
from azents.runtime.transfer.server_to_runtime import ServerToRuntimeTarget
from azents.runtime.transfer.workspace_download import (
    RuntimeWorkspaceDownloadService,
    WorkspaceDownloadError,
    WorkspaceDownloadRequest,
)


class _Resolver:
    """Resolve one opaque object only in trusted test code."""

    def resolve(self, opaque_handle: str) -> S3ObjectIdentity:
        return S3ObjectIdentity(bucket="transfer-bucket", key=opaque_handle)


class _FakeConsumer(RuntimeToServerConsumer):
    """Response consumer double with observable terminal lifecycle."""

    def __init__(self, body: bytes) -> None:
        self.upload = VerifiedRuntimeUpload(
            identity=CoordinatorTransferIdentity(
                transfer_id="transfer",
                attempt_id="attempt",
                runtime_id="runtime",
                desired_generation=1,
                direction="upload",
                operation_id="operation",
                session_id=None,
                agent_id="agent",
            ),
            publication_id="publication",
            object_handle=CoordinatorOpaqueObjectHandle("opaque-file"),
            size=len(body),
            sha256=hashlib.sha256(body).hexdigest(),
        )
        self.lease_started = False
        self.complete_calls = 0
        self.abandon_calls = 0

    async def start_lease_renewal(self) -> None:
        """Record that body consumption keeps the claim alive."""
        self.lease_started = True

    async def ensure_active(self) -> None:
        """Allow the configured source to be consumed."""

    async def complete(self) -> None:
        """Record successful response completion."""
        self.complete_calls += 1

    async def abandon(self) -> None:
        """Record unsuccessful response cleanup."""
        self.abandon_calls += 1


class _StreamingS3(S3Service):
    """Bounded source double for the response-scoped Workspace path."""

    def __init__(self, body: bytes) -> None:
        self.body = body
        self.chunk_sizes: list[int] = []
        self.close_calls = 0

    @asynccontextmanager
    async def iter_chunks(
        self,
        identity: S3ObjectIdentity,
        *,
        maximum_chunk_size: int,
    ) -> AsyncGenerator[AsyncGenerator[bytes, None], None]:
        """Yield one source body and record context closure."""
        del identity
        self.chunk_sizes.append(maximum_chunk_size)

        async def chunks() -> AsyncGenerator[bytes, None]:
            """Yield the configured source bytes."""
            if self.body:
                yield self.body

        try:
            yield chunks()
        finally:
            self.close_calls += 1


@dataclass
class _Transfer:
    """Invoke the feature callback with a verified upload."""

    requests: list[RuntimeToServerTransferRequest] = field(default_factory=list)
    consumer: _FakeConsumer | None = None

    async def transfer(self, request: RuntimeToServerTransferRequest) -> None:
        """Complete one verified transfer callback."""
        self.requests.append(request)
        await request.callback.publish(
            VerifiedRuntimeUpload(
                identity=CoordinatorTransferIdentity(
                    transfer_id="transfer",
                    attempt_id="attempt",
                    runtime_id="runtime",
                    desired_generation=1,
                    direction="upload",
                    operation_id=request.operation_id,
                    session_id=None,
                    agent_id="agent",
                ),
                publication_id=request.publication_id,
                object_handle=CoordinatorOpaqueObjectHandle("opaque-file"),
                size=4,
                sha256="a" * 64,
            )
        )

    async def prepare_consumer(
        self,
        request: RuntimeToServerConsumerRequest,
    ) -> RuntimeToServerConsumer:
        """Return a response consumer for the configured source body."""
        del request
        self.consumer = _FakeConsumer(b"data")
        return self.consumer


def _request() -> WorkspaceDownloadRequest:
    """Return one authorized Agent Workspace download request."""
    return WorkspaceDownloadRequest(
        agent_id="agent",
        runtime_path="/workspace/agent/report.bin",
        expected_size=4,
        target=ServerToRuntimeTarget(runtime_id="runtime", desired_generation=1),
    )


def _service(
    transfer: _Transfer,
    s3_service: AsyncMock | S3Service,
) -> RuntimeWorkspaceDownloadService:
    """Build a trusted Workspace download consumer."""
    return RuntimeWorkspaceDownloadService(
        transfer_service=transfer,
        resolver=_Resolver(),
        s3_service=s3_service,
        product_maximum_size=10,
        deadline=datetime.timedelta(minutes=1),
    )


@pytest.mark.asyncio
async def test_downloads_only_verified_runtime_object() -> None:
    """Authorized download resolves no Runner body through Control events."""
    transfer = _Transfer()
    s3_service = AsyncMock()
    s3_service.download_bytes.return_value = b"data"

    result = await _service(transfer, s3_service).download(_request())

    assert result == b"data"
    s3_service.download_bytes.assert_awaited_once_with(
        bucket="transfer-bucket",
        key="opaque-file",
    )
    assert transfer.requests[0].session_id is None
    assert transfer.requests[0].resource_class == "workspace_download"
    assert transfer.requests[0].operation_id == transfer.requests[0].publication_id


@pytest.mark.asyncio
async def test_missing_verified_object_fails_download() -> None:
    """Unavailable verified object never becomes an HTTP response body."""
    s3_service = AsyncMock()
    s3_service.download_bytes.return_value = None

    with pytest.raises(WorkspaceDownloadError, match="unavailable"):
        await _service(_Transfer(), s3_service).download(_request())


@pytest.mark.asyncio
async def test_open_download_settles_consumer_after_verified_eof() -> None:
    """Response-scoped Workspace streams settle only after exact EOF."""
    transfer = _Transfer()
    s3_service = _StreamingS3(b"data")

    stream = await _service(transfer, s3_service).open_download(_request())

    assert transfer.consumer is not None
    assert transfer.consumer.lease_started
    assert [chunk async for chunk in stream] == [b"data"]
    assert transfer.consumer.complete_calls == 0
    await stream.complete()

    assert transfer.consumer.complete_calls == 1
    assert transfer.consumer.abandon_calls == 0
    assert s3_service.chunk_sizes == [256 * 1024]
    assert s3_service.close_calls == 1
