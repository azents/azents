"""Tests for transfer-owned Workspace browser GET capabilities."""

import base64
import datetime
from dataclasses import dataclass, field
from unittest.mock import AsyncMock, Mock

import pytest
from azcommon.infra.s3.service import (
    S3ObjectIdentity,
    S3ObjectMetadata,
    S3PresignedRequest,
    S3Service,
)
from azents_runtime_control.grpc_transfer_coordinator_client import (
    CoordinatorOpaqueObjectHandle,
)
from azents_runtime_control.transfer import CoordinatorTransferIdentity

from azents.runtime.transfer.runtime_to_server import (
    RuntimeToServerTransferRequest,
    VerifiedRuntimeUpload,
)
from azents.runtime.transfer.server_to_runtime import ServerToRuntimeTarget
from azents.runtime.transfer.workspace_download import (
    RuntimeWorkspaceDownloadService,
    WorkspaceDownloadError,
    WorkspaceDownloadRequest,
)

_NOW = datetime.datetime(2026, 9, 29, tzinfo=datetime.UTC)
_SOURCE = S3ObjectIdentity(bucket="transfer-bucket", key="opaque-source")
_URL = "https://objects.test/source?signature=redacted"


class _Resolver:
    """Resolve one trusted opaque source without exposing its identity."""

    def resolve(self, opaque_handle: str) -> S3ObjectIdentity:
        assert opaque_handle == "opaque-source"
        return _SOURCE


@dataclass
class _Clock:
    now: datetime.datetime = _NOW

    def __call__(self) -> datetime.datetime:
        return self.now


@dataclass
class _Transfer:
    """Execute the verified feature callback, never a browser body consumer."""

    requests: list[RuntimeToServerTransferRequest] = field(default_factory=list)
    clock: _Clock = field(default_factory=_Clock)
    advance: datetime.timedelta = datetime.timedelta()
    publish: bool = True

    async def transfer(self, request: RuntimeToServerTransferRequest) -> None:
        self.requests.append(request)
        self.clock.now += self.advance
        if self.publish:
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
                    object_handle=CoordinatorOpaqueObjectHandle("opaque-source"),
                    size=4,
                    sha256="a" * 64,
                )
            )


def _request() -> WorkspaceDownloadRequest:
    return WorkspaceDownloadRequest(
        agent_id="agent",
        runtime_path="/workspace/agent/report.bin",
        expected_size=4,
        target=ServerToRuntimeTarget(runtime_id="runtime", desired_generation=1),
        filename="report ü.bin",
        media_type="application/octet-stream",
    )


def _metadata(*, size: int = 4, checksum: str = "a" * 64) -> S3ObjectMetadata:
    return S3ObjectMetadata(
        identity=_SOURCE,
        content_length=size,
        content_type="application/octet-stream",
        etag='"etag"',
        checksum_sha256=checksum,
        user_metadata={},
        last_modified_at=_NOW,
    )


def _s3() -> Mock:
    service = Mock(spec=S3Service)
    service.head_with_checksum = AsyncMock(return_value=_metadata())
    service.get_download_request = AsyncMock(
        return_value=S3PresignedRequest(
            method="GET",
            url=_URL,
            expires_at=_NOW + datetime.timedelta(seconds=60),
            headers={},
        )
    )
    return service


def _service(
    transfer: _Transfer, s3_service: S3Service
) -> RuntimeWorkspaceDownloadService:
    return RuntimeWorkspaceDownloadService(
        transfer_service=transfer,
        resolver=_Resolver(),
        s3_service=s3_service,
        product_maximum_size=128 * 1024 * 1024,
        deadline=datetime.timedelta(minutes=5),
        clock=transfer.clock,
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "checksum", ["a" * 64, base64.b64encode(bytes.fromhex("a" * 64)).decode()]
)
async def test_ticket_handoff_signs_metadata_without_reading_body(
    checksum: str,
) -> None:
    transfer = _Transfer()
    s3_service = _s3()
    s3_service.head_with_checksum.return_value = _metadata(checksum=checksum)

    ticket = await _service(transfer, s3_service).create_download_ticket(_request())

    assert ticket.url == _URL
    assert _URL not in repr(ticket)
    s3_service.head_with_checksum.assert_awaited_once_with(_SOURCE)
    s3_service.get_download_request.assert_awaited_once_with(
        identity=_SOURCE,
        expires_in=datetime.timedelta(seconds=60),
        now=_NOW,
        filename="report ü.bin",
        content_type="application/octet-stream",
        inline=False,
    )
    s3_service.download_bytes.assert_not_called()
    s3_service.iter_chunks.assert_not_called()
    s3_service.delete.assert_not_called()
    request = transfer.requests[0]
    assert request.session_id is None
    assert request.resource_class == "workspace_download"
    assert request.operation_id == request.publication_id
    assert ticket.expires_at <= request.deadline_at


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "metadata",
    [
        None,
        _metadata(size=5),
        _metadata(checksum="b" * 64),
        _metadata(checksum=base64.b64encode(bytes.fromhex("b" * 64)).decode()),
    ],
)
async def test_missing_or_changed_source_issues_no_capability(
    metadata: S3ObjectMetadata | None,
) -> None:
    s3_service = _s3()
    s3_service.head_with_checksum.return_value = metadata

    with pytest.raises(WorkspaceDownloadError, match="unavailable"):
        await _service(_Transfer(), s3_service).create_download_ticket(_request())

    s3_service.get_download_request.assert_not_called()
    s3_service.download_bytes.assert_not_called()


@pytest.mark.asyncio
async def test_get_expiry_never_exceeds_operation_owned_retention_window() -> None:
    transfer = _Transfer(advance=datetime.timedelta(minutes=4, seconds=50))
    s3_service = _s3()

    await _service(transfer, s3_service).create_download_ticket(_request())

    call = s3_service.get_download_request.await_args
    assert call is not None
    assert call.kwargs["expires_in"] == datetime.timedelta(seconds=10)
    assert call.kwargs["now"] == _NOW + transfer.advance


@pytest.mark.asyncio
async def test_expired_operation_never_issues_get() -> None:
    transfer = _Transfer(advance=datetime.timedelta(minutes=5))
    s3_service = _s3()

    with pytest.raises(WorkspaceDownloadError, match="deadline expired"):
        await _service(transfer, s3_service).create_download_ticket(_request())

    s3_service.get_download_request.assert_not_called()


@pytest.mark.asyncio
async def test_missing_feature_handoff_cannot_be_reported_as_ticket_success() -> None:
    s3_service = _s3()

    with pytest.raises(WorkspaceDownloadError, match="without a download ticket"):
        await _service(_Transfer(publish=False), s3_service).create_download_ticket(
            _request()
        )

    s3_service.get_download_request.assert_not_called()
