"""Tests for trusted Runtime image transfer materialization."""

import datetime
from dataclasses import dataclass, field
from unittest.mock import AsyncMock

import pytest
from azcommon.infra.s3.service import S3ObjectIdentity
from azcommon.result import Failure, Success
from azents_runtime_control.grpc_transfer_coordinator_client import (
    CoordinatorOpaqueObjectHandle,
)
from azents_runtime_control.transfer import CoordinatorTransferIdentity

from azents.core.enums import ModelFileStatus
from azents.repos.model_file.data import ModelFile
from azents.runtime.transfer.runtime_image_read import (
    RuntimeImageReadError,
    RuntimeImageReadModelFileOversized,
    RuntimeImageReadRequest,
    RuntimeImageReadService,
)
from azents.runtime.transfer.runtime_to_server import (
    RuntimeToServerTransferRequest,
    VerifiedRuntimeUpload,
)
from azents.runtime.transfer.server_to_runtime import ServerToRuntimeTarget
from azents.services.model_file import ModelFileOversized
from azents.services.session_resource_authority import SessionResourceAuthority


class _Resolver:
    """Resolve only the fake verified opaque object."""

    def __init__(self) -> None:
        self.handles: list[str] = []

    def resolve(self, opaque_handle: str) -> S3ObjectIdentity:
        self.handles.append(opaque_handle)
        return S3ObjectIdentity(bucket="runtime-transfer", key=opaque_handle)


@dataclass
class _Transfer:
    """Drive feature callbacks with one verified opaque object."""

    requests: list[RuntimeToServerTransferRequest] = field(default_factory=list)

    async def transfer(self, request: RuntimeToServerTransferRequest) -> None:
        """Publish a verified object through the feature callback."""
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
                    session_id="session",
                    agent_id="agent",
                ),
                publication_id=request.publication_id,
                object_handle=CoordinatorOpaqueObjectHandle("opaque-image"),
                size=4,
                sha256="a" * 64,
            )
        )


def _authority() -> SessionResourceAuthority:
    """Return one canonical image-read authority."""
    return SessionResourceAuthority(
        workspace_id="workspace",
        agent_id="agent",
        session_id="session",
        root_session_id="root-session",
        run_id="run",
        run_index=1,
        owner_generation=1,
    )


def _request() -> RuntimeImageReadRequest:
    """Return one image materialization request."""
    return RuntimeImageReadRequest(
        runtime_path="/workspace/agent/image.png",
        filename="image.png",
        media_type="image/png",
        expected_size=4,
        authority=_authority(),
        target=ServerToRuntimeTarget(runtime_id="runtime", desired_generation=1),
    )


def _model_file() -> ModelFile:
    """Return one normalized image model file."""
    return ModelFile(
        id="m" * 32,
        workspace_id="workspace",
        session_id="session",
        agent_id="agent",
        name="image.png",
        media_type="image/jpeg",
        kind="image",
        size_bytes=4,
        created_run_id="run",
        created_run_index=1,
        storage_key="model-files/workspace/session/m",
        status=ModelFileStatus.AVAILABLE,
        normalized_format="jpeg",
        sha256="b" * 64,
        metadata={},
        created_at=datetime.datetime.now(datetime.UTC),
        deleted_at=None,
    )


def _service(
    transfer: _Transfer,
    resolver: _Resolver,
    s3_service: AsyncMock,
    model_file_service: AsyncMock,
) -> RuntimeImageReadService:
    """Create the trusted image consumer under test."""
    return RuntimeImageReadService(
        transfer_service=transfer,
        resolver=resolver,
        s3_service=s3_service,
        model_file_service=model_file_service,
        product_maximum_size=10,
        deadline=datetime.timedelta(minutes=1),
    )


@pytest.mark.asyncio
async def test_materializes_verified_object_as_model_file() -> None:
    """The Worker resolves and downloads only the verified opaque object."""
    transfer = _Transfer()
    resolver = _Resolver()
    s3_service = AsyncMock()
    s3_service.download_bytes.return_value = b"data"
    model_file_service = AsyncMock()
    model_file_service.create.return_value = Success(_model_file())

    result = await _service(transfer, resolver, s3_service, model_file_service).read(
        _request()
    )

    assert result.id == "m" * 32
    assert resolver.handles == ["opaque-image"]
    s3_service.download_bytes.assert_awaited_once_with(
        bucket="runtime-transfer",
        key="opaque-image",
    )
    model_file_service.create.assert_awaited_once_with(
        authority=_authority(),
        filename="image.png",
        media_type="image/png",
        body=b"data",
        metadata={
            "source_kind": "runtime_path",
            "source_path": "/workspace/agent/image.png",
            "tool": "read_image",
        },
    )
    assert transfer.requests[0].resource_class == "read_image"
    assert transfer.requests[0].expected_size == 4
    assert transfer.requests[0].operation_id == transfer.requests[0].publication_id


@pytest.mark.asyncio
async def test_missing_verified_object_fails_before_model_file_creation() -> None:
    """An unavailable transfer object fails the callback and is not normalized."""
    transfer = _Transfer()
    s3_service = AsyncMock()
    s3_service.download_bytes.return_value = None
    model_file_service = AsyncMock()

    with pytest.raises(RuntimeImageReadError, match="unavailable"):
        await _service(transfer, _Resolver(), s3_service, model_file_service).read(
            _request()
        )

    model_file_service.create.assert_not_awaited()


@pytest.mark.asyncio
async def test_model_file_size_failure_preserves_typed_result() -> None:
    """The tool layer can retain the existing oversized-file user message."""
    transfer = _Transfer()
    s3_service = AsyncMock()
    s3_service.download_bytes.return_value = b"data"
    model_file_service = AsyncMock()
    model_file_service.create.return_value = Failure(
        ModelFileOversized(max_bytes=3, actual_bytes=4)
    )

    with pytest.raises(RuntimeImageReadModelFileOversized) as exc_info:
        await _service(transfer, _Resolver(), s3_service, model_file_service).read(
            _request()
        )

    assert exc_info.value.error == ModelFileOversized(max_bytes=3, actual_bytes=4)


@pytest.mark.asyncio
async def test_each_read_uses_an_independent_operation_identity() -> None:
    """Concurrent-capable reads must not reuse one coordinator operation ID."""
    transfer = _Transfer()
    s3_service = AsyncMock()
    s3_service.download_bytes.return_value = b"data"
    model_file_service = AsyncMock()
    model_file_service.create.return_value = Success(_model_file())
    service = _service(transfer, _Resolver(), s3_service, model_file_service)

    await service.read(_request())
    await service.read(_request())

    assert transfer.requests[0].operation_id != transfer.requests[1].operation_id
