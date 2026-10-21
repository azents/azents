"""Runner file reads consume verified upload leases with hash and owner fences."""

import dataclasses
import hashlib
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import NamedTuple
from unittest.mock import AsyncMock, Mock, create_autospec

import pytest
from azcommon.infra.s3.service import S3ObjectIdentity, S3Service
from azents_runtime_control.grpc_transfer_coordinator_client import (
    CoordinatorOpaqueObjectHandle,
)
from azents_runtime_control.transfer import CoordinatorTransferIdentity

from azents.core.google_oauth import GoogleOAuthError
from azents.core.session_resource_authority import SessionResourceAuthority
from azents.runtime.transfer.present_file_publication import (
    RuntimeTransferObjectResolver,
)
from azents.runtime.transfer.runtime_to_server import (
    RuntimeToServerConsumer,
    RuntimeToServerTransferService,
    VerifiedRuntimeUpload,
)
from azents.runtime.transfer.server_to_runtime import ServerToRuntimeTarget
from azents.services.file_storage import FileStorage
from azents.services.google_workspace.file_models import GoogleFileInput
from azents.services.google_workspace.runtime_files import GoogleRuntimeFileReader
from azents.services.google_workspace.transport import GoogleSdkError


class Harness(NamedTuple):
    reader: GoogleRuntimeFileReader
    storage: Mock
    transfer: Mock
    consumer: Mock
    target: AsyncMock
    s3: Mock
    closed: list[bool]


def _harness(content: bytes) -> Harness:
    storage = create_autospec(FileStorage, instance=True)
    storage.stat.return_value = {"is_file": True, "size": len(content)}
    transfer = create_autospec(RuntimeToServerTransferService, instance=True)
    consumer = create_autospec(RuntimeToServerConsumer, instance=True)
    consumer.upload = VerifiedRuntimeUpload(
        identity=CoordinatorTransferIdentity(
            "transfer",
            "attempt",
            "runtime",
            1,
            "upload",
            "operation",
            "session",
            "agent",
        ),
        publication_id="publication",
        object_handle=CoordinatorOpaqueObjectHandle("object"),
        size=len(content),
        sha256=hashlib.sha256(content).hexdigest(),
    )
    transfer.prepare_consumer.return_value = consumer
    s3 = create_autospec(S3Service, instance=True)
    closed: list[bool] = []

    @asynccontextmanager
    async def stream(
        identity: S3ObjectIdentity, *, maximum_chunk_size: int
    ) -> AsyncIterator[AsyncIterator[bytes]]:
        assert identity.bucket == "bucket"

        async def chunks() -> AsyncIterator[bytes]:
            yield content

        try:
            yield chunks()
        finally:
            closed.append(True)

    s3.iter_chunks.side_effect = stream
    target = AsyncMock(return_value=ServerToRuntimeTarget("runtime", 1))
    reader = GoogleRuntimeFileReader(
        storage=storage,
        transfers=transfer,
        objects=RuntimeTransferObjectResolver("bucket", "runtime-transfer"),
        s3=s3,
        resolve_target=target,
        authority=SessionResourceAuthority(
            "workspace", "agent", "session", "session", "run", 1, 7
        ),
        maximum_bytes=1024,
    )
    return Harness(reader, storage, transfer, consumer, target, s3, closed)


def _source() -> GoogleFileInput:
    return GoogleFileInput(
        source="/workspace/source.bin",
        filename=None,
        media_type="application/octet-stream",
    )


async def test_runtime_consumer_completes_after_integrity_check() -> None:
    h = _harness(b"\x00\xfforiginal")
    result = await h.reader.read(_source(), admit=AsyncMock())
    assert result.file.content == b"\x00\xfforiginal"
    assert result.file.filename == "source.bin"
    assert h.closed == [True]
    h.consumer.start_lease_renewal.assert_awaited_once()
    h.consumer.complete.assert_awaited_once()
    h.consumer.close.assert_awaited_once()
    request = h.transfer.prepare_consumer.call_args.args[0]
    assert request.runtime_path == "/workspace/source.bin"
    assert request.session_id == "session" and request.agent_id == "agent"
    assert request.target == ServerToRuntimeTarget("runtime", 1)
    h.storage.get.assert_not_awaited()


async def test_runtime_generation_change_after_read_defeats_reuse() -> None:
    h = _harness(b"original")
    result = await h.reader.read(_source(), admit=AsyncMock())
    h.target.return_value = ServerToRuntimeTarget("runtime", 2)
    with pytest.raises(GoogleSdkError) as error:
        await result.revalidate()
    assert error.value.code == "runtime_source_changed"


async def test_runtime_generation_change_during_read_does_not_acknowledge() -> None:
    h = _harness(b"original")
    h.target.side_effect = [
        ServerToRuntimeTarget("runtime", 1),
        ServerToRuntimeTarget("runtime", 2),
    ]
    with pytest.raises(GoogleSdkError):
        await h.reader.read(_source(), admit=AsyncMock())
    h.consumer.complete.assert_not_awaited()
    h.consumer.close.assert_awaited_once()


async def test_runtime_hash_mismatch_closes_unconsumed_claim() -> None:
    h = _harness(b"original")
    h.consumer.upload = dataclasses.replace(h.consumer.upload, sha256="0" * 64)
    with pytest.raises(GoogleSdkError) as error:
        await h.reader.read(_source(), admit=AsyncMock())
    assert error.value.code == "file_integrity_mismatch"
    h.consumer.complete.assert_not_awaited()
    h.consumer.close.assert_awaited_once()
    assert h.closed == [True]


async def test_revoked_session_during_read_closes_claim_without_google_effect() -> None:
    h = _harness(b"original")
    admit = AsyncMock(
        side_effect=[
            None,
            GoogleOAuthError("authorization_unavailable", "Owner changed."),
        ]
    )
    with pytest.raises(GoogleOAuthError):
        await h.reader.read(_source(), admit=admit)
    h.consumer.complete.assert_not_awaited()
    h.consumer.close.assert_awaited_once()
    assert h.closed == [True]


async def test_announced_oversize_rejects_before_transfer_admission() -> None:
    h = _harness(b"original")
    h.storage.stat.return_value = {"is_file": True, "size": 1025}
    with pytest.raises(GoogleSdkError) as error:
        await h.reader.read(_source(), admit=AsyncMock())
    assert error.value.code == "file_unavailable_or_oversized"
    h.transfer.prepare_consumer.assert_not_awaited()


@pytest.mark.parametrize(
    "source", ["relative", "artifact://object", "https://attacker.invalid/file"]
)
async def test_runtime_reader_accepts_only_explicit_runtime_paths(source: str) -> None:
    h = _harness(b"original")
    if source.startswith("https://"):
        # Management input validation precedes this private Runtime adapter.
        with pytest.raises(ValueError):
            GoogleFileInput(source=source, filename=None, media_type=None)
    else:
        with pytest.raises(GoogleSdkError):
            await h.reader.read(
                GoogleFileInput(source=source, filename=None, media_type=None),
                admit=AsyncMock(),
            )
    h.storage.stat.assert_not_awaited()
