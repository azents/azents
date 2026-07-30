"""Tests for trusted Runtime Workspace download materialization."""

import datetime
from dataclasses import dataclass, field
from unittest.mock import AsyncMock

import pytest
from azcommon.infra.s3.service import S3ObjectIdentity
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


class _Resolver:
    """Resolve one opaque object only in trusted test code."""

    def resolve(self, opaque_handle: str) -> S3ObjectIdentity:
        return S3ObjectIdentity(bucket="transfer-bucket", key=opaque_handle)


@dataclass
class _Transfer:
    """Invoke the feature callback with a verified upload."""

    requests: list[RuntimeToServerTransferRequest] = field(default_factory=list)

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
    s3_service: AsyncMock,
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
