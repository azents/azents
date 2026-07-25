"""Bounded Runner download transfer servicer tests."""

# pyright: reportAttributeAccessIssue=false, reportArgumentType=false
# ruff: noqa: E501

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta

import grpc
import pytest
from azcommon.infra.s3.service import S3ObjectIdentity, S3VerifiedObject
from azents_runtime_control.proto import runtime_runner_transfer_pb2 as pb

from azents.core.runtime_runner_credential import (
    RuntimeRunnerCredential,
    RuntimeRunnerCredentialInvalid,
)
from azents.runtime.control_protocol.grpc.runner_transfer_server import (
    RuntimeRunnerTransferGrpcServicer,
)
from azents.runtime.coordination.data import RuntimeConnectionKind
from azents.runtime.coordination.memory import InMemoryRuntimeCoordinationStore
from azents.runtime.transfer.data import (
    RuntimeTransferAdmission,
    RuntimeTransferConfig,
    RuntimeTransferDirection,
    RuntimeTransferObject,
)
from azents.runtime.transfer.memory import InMemoryRuntimeTransferStateStore

_NOW = datetime(2026, 7, 25, 12, 0, tzinfo=UTC)
_DIGEST = "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad"


class _Abort(RuntimeError):
    def __init__(self, code: grpc.StatusCode) -> None:
        self.code = code


class _Context:
    def __init__(self, *, token: str | None = "token") -> None:
        self.token = token
        self.is_cancelled = False

    def invocation_metadata(self) -> tuple[tuple[str, str], ...]:
        return (
            () if self.token is None else (("authorization", f"Bearer {self.token}"),)
        )

    async def abort(self, code: grpc.StatusCode, details: str) -> None:
        del details
        raise _Abort(code)

    def cancelled(self) -> bool:
        return self.is_cancelled


class _Authenticator:
    def __init__(self, *, authorized: bool = True) -> None:
        self.credential = RuntimeRunnerCredential("credential-1", "runtime-1", 1)
        self.authorized = authorized

    async def authenticate_runner(self, secret: str) -> RuntimeRunnerCredential:
        if secret != "token":
            raise RuntimeRunnerCredentialInvalid("invalid")
        return self.credential

    async def authorize_runner(self, credential: RuntimeRunnerCredential) -> bool:
        return self.authorized and credential == self.credential


class _ObjectStore:
    def __init__(self, chunks: list[bytes]) -> None:
        self.chunks = chunks
        self.verify_calls = 0
        self.closed = False

    async def verify_transfer_object(
        self,
        *,
        identity: S3ObjectIdentity,
        expected_size: int,
        expected_sha256: str,
    ) -> S3VerifiedObject:
        del identity, expected_size, expected_sha256
        self.verify_calls += 1
        return object()  # type: ignore[return-value]

    @asynccontextmanager
    async def iter_chunks(
        self,
        identity: S3ObjectIdentity,
        *,
        maximum_chunk_size: int,
    ) -> AsyncIterator[AsyncIterator[bytes]]:
        del identity

        async def _chunks() -> AsyncIterator[bytes]:
            for chunk in self.chunks:
                assert len(chunk) <= maximum_chunk_size
                yield chunk

        try:
            yield _chunks()
        finally:
            self.closed = True


@pytest.mark.asyncio
async def test_download_streams_offsets_completion_and_closes_body() -> None:
    harness = await _harness(chunks=[b"a", b"bc"])

    frames = [
        frame
        async for frame in harness.servicer.DownloadTransfer(_request(), _Context())
    ]

    assert [frame.chunk.offset for frame in frames[:-1]] == [0, 1]
    assert [frame.chunk.data for frame in frames[:-1]] == [b"a", b"bc"]
    assert frames[-1].complete.actual_size == 3
    assert frames[-1].complete.sha256 == _DIGEST
    assert harness.object_store.verify_calls == 1
    assert harness.object_store.closed is True


@pytest.mark.asyncio
async def test_zero_byte_download_emits_only_completion() -> None:
    harness = await _harness(
        chunks=[],
        size=0,
        sha256="e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
    )

    frames = [
        frame
        async for frame in harness.servicer.DownloadTransfer(_request(), _Context())
    ]

    assert len(frames) == 1
    assert frames[0].complete.actual_size == 0
    assert harness.object_store.closed is True


@pytest.mark.asyncio
async def test_missing_or_stale_auth_fails_before_s3() -> None:
    harness = await _harness(chunks=[b"abc"])

    with pytest.raises(_Abort) as error:
        _ = [
            frame
            async for frame in harness.servicer.DownloadTransfer(
                _request(), _Context(token=None)
            )
        ]

    assert error.value.code is grpc.StatusCode.UNAUTHENTICATED
    assert harness.object_store.verify_calls == 0


@pytest.mark.asyncio
async def test_wrong_direction_or_duplicate_claim_fails_before_s3() -> None:
    upload = await _harness(chunks=[b"abc"], direction=RuntimeTransferDirection.UPLOAD)
    with pytest.raises(_Abort):
        _ = [
            frame
            async for frame in upload.servicer.DownloadTransfer(_request(), _Context())
        ]
    assert upload.object_store.verify_calls == 0

    duplicate = await _harness(chunks=[b"abc"])
    await duplicate.claim()
    with pytest.raises(_Abort):
        _ = [
            frame
            async for frame in duplicate.servicer.DownloadTransfer(
                _request(), _Context()
            )
        ]
    assert duplicate.object_store.verify_calls == 0


class _Harness:
    def __init__(
        self,
        *,
        state: InMemoryRuntimeTransferStateStore,
        servicer: RuntimeRunnerTransferGrpcServicer,
        object_store: _ObjectStore,
    ) -> None:
        self.state = state
        self.servicer = servicer
        self.object_store = object_store

    async def claim(self) -> None:
        record = await self.state.get("transfer-1")
        assert record is not None
        claimed = await self.state.claim_stream(
            "transfer-1",
            attempt_id="attempt-1",
            runtime_id="runtime-1",
            desired_generation=1,
            accepted_runner_generation=1,
            expected_revision=record.revision,
            claim_id="existing-claim",
            owner_replica_id="other",
        )
        assert claimed is not None


async def _harness(
    *,
    chunks: list[bytes],
    size: int = 3,
    sha256: str = _DIGEST,
    direction: RuntimeTransferDirection = RuntimeTransferDirection.DOWNLOAD,
) -> _Harness:
    state = InMemoryRuntimeTransferStateStore(config=_config(), clock=lambda: _NOW)
    admitted = await state.admit(
        _admission(direction, size, sha256), lease_id="lease-1"
    )
    assert admitted is not None
    ready = await state.mark_ready(
        "transfer-1",
        attempt_id="attempt-1",
        runtime_id="runtime-1",
        desired_generation=1,
        expected_revision=admitted.revision,
        object=RuntimeTransferObject("object-1", size, sha256),
    )
    assert ready is not None
    bound = await state.bind_dispatch(
        "transfer-1",
        attempt_id="attempt-1",
        runtime_id="runtime-1",
        desired_generation=1,
        accepted_runner_generation=1,
        expected_revision=ready.revision,
        dispatch_id="dispatch-1",
        dispatch_request_id="request-1",
    )
    assert bound is not None
    deliverable = await state.mark_dispatch_deliverable(
        "transfer-1",
        attempt_id="attempt-1",
        expected_revision=bound.revision,
        dispatch_id="dispatch-1",
        dispatch_request_id="request-1",
    )
    assert deliverable is not None
    coordination = InMemoryRuntimeCoordinationStore()
    await coordination.register_connection(
        kind=RuntimeConnectionKind.RUNNER,
        subject_id="runtime-1",
        connection_id="connection-1",
        owner_replica_id="replica-1",
        connected_at=_NOW,
        heartbeat_at=datetime.now(UTC),
        ttl_seconds=60,
        metadata={},
    )
    object_store = _ObjectStore(chunks)
    return _Harness(
        state=state,
        object_store=object_store,
        servicer=RuntimeRunnerTransferGrpcServicer(
            state_store=state,
            coordination_store=coordination,
            object_store=object_store,
            bucket="transfer-bucket",
            owner_replica_id="replica-1",
            runner_authenticator=_Authenticator(),
            clock=lambda: _NOW,
        ),
    )


def _request() -> pb.DownloadTransferRequest:
    return pb.DownloadTransferRequest(
        identity=pb.TransferIdentity(
            transfer_id="transfer-1",
            attempt_id="attempt-1",
            runtime_id="runtime-1",
            runner_generation=1,
        )
    )


def _admission(
    direction: RuntimeTransferDirection,
    size: int,
    sha256: str,
) -> RuntimeTransferAdmission:
    return RuntimeTransferAdmission(
        transfer_id="transfer-1",
        attempt_id="attempt-1",
        direction=direction,
        runtime_id="runtime-1",
        desired_generation=1,
        operation_id="operation-1",
        session_id=None,
        agent_id=None,
        runtime_path="/workspace/file",
        overwrite=False,
        expected_size=size,
        expected_sha256=sha256,
        product_maximum_size=10,
        provider_maximum_size=10,
        deadline_at=_NOW + timedelta(minutes=5),
        source_expires_at=None,
        resource_class="file",
    )


def _config() -> RuntimeTransferConfig:
    return RuntimeTransferConfig(
        per_runtime_attempts=4,
        per_runtime_bytes=100,
        deployment_attempts=4,
        deployment_bytes=100,
        admission_lease=timedelta(minutes=5),
        consumer_lease=timedelta(minutes=1),
        stream_lease=timedelta(seconds=30),
        terminal_ttl=timedelta(minutes=5),
        list_page_size=10,
    )
