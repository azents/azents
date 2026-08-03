"""Trusted Runtime image transfer consumer."""

from __future__ import annotations

import datetime
from dataclasses import dataclass
from typing import Protocol

from azcommon.infra.s3.service import S3Service
from azcommon.result import Failure
from azcommon.uuid import uuid7

from azents.repos.model_file.data import ModelFile
from azents.runtime.transfer.present_file_publication import (
    OpaqueTransferObjectResolver,
)
from azents.runtime.transfer.runtime_to_server import (
    RuntimeToServerPublicationCallback,
    RuntimeToServerTransferError,
    RuntimeToServerTransferRequest,
    VerifiedRuntimeUpload,
)
from azents.runtime.transfer.server_to_runtime import ServerToRuntimeTarget
from azents.services.model_file import (
    ModelFileCreateError,
    ModelFileOversized,
    ModelFileService,
)
from azents.services.session_resource_authority import SessionResourceAuthority


class RuntimeImageReadError(RuntimeError):
    """Raised when one Runtime image cannot become model input."""


class RuntimeImageReadModelFileOversized(RuntimeImageReadError):
    """ModelFile admission rejected the verified image because it is too large."""

    def __init__(self, error: ModelFileOversized) -> None:
        super().__init__("Model input size limit exceeded")
        self.error = error


class RuntimeToServerTransferExecutor(Protocol):
    """Execute one opaque Runtime-to-server transfer."""

    async def transfer(self, request: RuntimeToServerTransferRequest) -> None:
        """Complete the requested Runtime upload consumer."""
        ...


@dataclass(frozen=True)
class RuntimeImageReadRequest:
    """One Runtime image materialization request."""

    runtime_path: str
    filename: str
    media_type: str
    expected_size: int
    authority: SessionResourceAuthority
    target: ServerToRuntimeTarget


class _ModelFileCallback(RuntimeToServerPublicationCallback):
    """Create a normalized ModelFile from one verified transfer object."""

    def __init__(
        self,
        *,
        resolver: OpaqueTransferObjectResolver,
        s3_service: S3Service,
        model_file_service: ModelFileService,
        request: RuntimeImageReadRequest,
    ) -> None:
        self.resolver = resolver
        self.s3_service = s3_service
        self.model_file_service = model_file_service
        self.request = request
        self.model_file: ModelFile | None = None

    async def publish(self, upload: VerifiedRuntimeUpload) -> None:
        """Download verified transfer bytes and normalize them as ModelFile."""
        source = self.resolver.resolve(upload.object_handle.value)
        body = await self.s3_service.download_bytes(
            bucket=source.bucket, key=source.key
        )
        if body is None:
            raise RuntimeImageReadError("Verified Runtime image object is unavailable")
        created = await self.model_file_service.create(
            authority=self.request.authority,
            filename=self.request.filename,
            media_type=self.request.media_type,
            body=body,
            metadata={
                "source_kind": "runtime_path",
                "source_path": self.request.runtime_path,
                "tool": "read_image",
            },
        )
        if isinstance(created, Failure):
            if isinstance(created.error, ModelFileOversized):
                raise RuntimeImageReadModelFileOversized(created.error)
            raise RuntimeImageReadError(_model_file_error(created.error))
        self.model_file = created.value


class RuntimeImageReadService:
    """Materialize one Runtime image through the verified transfer data plane."""

    def __init__(
        self,
        *,
        transfer_service: RuntimeToServerTransferExecutor,
        resolver: OpaqueTransferObjectResolver,
        s3_service: S3Service,
        model_file_service: ModelFileService,
        product_maximum_size: int,
        deadline: datetime.timedelta,
    ) -> None:
        self.transfer_service = transfer_service
        self.resolver = resolver
        self.s3_service = s3_service
        self.model_file_service = model_file_service
        self.product_maximum_size = product_maximum_size
        self.deadline = deadline

    async def read(self, request: RuntimeImageReadRequest) -> ModelFile:
        """Transfer and normalize one Runtime image."""
        operation_id = f"read-image-{uuid7().hex}"
        callback = _ModelFileCallback(
            resolver=self.resolver,
            s3_service=self.s3_service,
            model_file_service=self.model_file_service,
            request=request,
        )
        try:
            await self.transfer_service.transfer(
                RuntimeToServerTransferRequest(
                    target=request.target,
                    agent_id=request.authority.agent_id,
                    session_id=request.authority.session_id,
                    operation_id=operation_id,
                    runtime_path=request.runtime_path,
                    expected_size=request.expected_size,
                    expected_sha256=None,
                    product_maximum_size=self.product_maximum_size,
                    provider_maximum_size=self.product_maximum_size,
                    deadline_at=datetime.datetime.now(datetime.UTC) + self.deadline,
                    resource_class="read_image",
                    publication_id=operation_id,
                    callback=callback,
                )
            )
        except RuntimeToServerTransferError as exc:
            raise RuntimeImageReadError(str(exc)) from exc
        if callback.model_file is None:
            raise RuntimeImageReadError(
                "Runtime image transfer completed without model input"
            )
        return callback.model_file


def _model_file_error(error: ModelFileCreateError) -> str:
    """Return a safe model-file admission failure summary."""
    return error.__class__.__name__
