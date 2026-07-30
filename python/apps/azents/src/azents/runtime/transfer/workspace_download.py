"""Trusted Runtime Workspace download transfer consumer."""

from __future__ import annotations

import datetime
from dataclasses import dataclass
from typing import Protocol

from azcommon.infra.s3.service import S3Service
from azcommon.uuid import uuid7

from azents.runtime.transfer.present_file_publication import (
    OpaqueTransferObjectResolver,
)
from azents.runtime.transfer.runtime_to_server import (
    RuntimeToServerPublicationCallback,
    RuntimeToServerTransferRequest,
    VerifiedRuntimeUpload,
)
from azents.runtime.transfer.server_to_runtime import ServerToRuntimeTarget


class WorkspaceDownloadError(RuntimeError):
    """Raised when a Runtime Workspace download cannot be materialized."""


class RuntimeToServerTransferExecutor(Protocol):
    """Execute one opaque Runtime-to-server transfer."""

    async def transfer(self, request: RuntimeToServerTransferRequest) -> None:
        """Complete one Runtime upload consumer."""
        ...


@dataclass(frozen=True)
class WorkspaceDownloadRequest:
    """One authorized Agent Workspace file download."""

    agent_id: str
    runtime_path: str
    expected_size: int
    target: ServerToRuntimeTarget


class _BytesCallback(RuntimeToServerPublicationCallback):
    """Resolve a verified temporary object only inside trusted server code."""

    def __init__(
        self,
        *,
        resolver: OpaqueTransferObjectResolver,
        s3_service: S3Service,
    ) -> None:
        self.resolver = resolver
        self.s3_service = s3_service
        self.body: bytes | None = None

    async def publish(self, upload: VerifiedRuntimeUpload) -> None:
        """Download the verified object for the REST response adapter."""
        source = self.resolver.resolve(upload.object_handle.value)
        body = await self.s3_service.download_bytes(
            bucket=source.bucket, key=source.key
        )
        if body is None:
            raise WorkspaceDownloadError("Verified Runtime file object is unavailable")
        self.body = body


class RuntimeWorkspaceDownloadService:
    """Materialize one authorized Workspace file through verified transfer."""

    def __init__(
        self,
        *,
        transfer_service: RuntimeToServerTransferExecutor,
        resolver: OpaqueTransferObjectResolver,
        s3_service: S3Service,
        product_maximum_size: int,
        deadline: datetime.timedelta,
    ) -> None:
        self.transfer_service = transfer_service
        self.resolver = resolver
        self.s3_service = s3_service
        self.product_maximum_size = product_maximum_size
        self.deadline = deadline

    async def download(self, request: WorkspaceDownloadRequest) -> bytes:
        """Return verified Runtime bytes after transfer lifecycle settlement."""
        operation_id = f"workspace-download-{uuid7().hex}"
        callback = _BytesCallback(resolver=self.resolver, s3_service=self.s3_service)
        await self.transfer_service.transfer(
            RuntimeToServerTransferRequest(
                target=request.target,
                agent_id=request.agent_id,
                session_id=None,
                operation_id=operation_id,
                runtime_path=request.runtime_path,
                expected_size=request.expected_size,
                expected_sha256=None,
                product_maximum_size=self.product_maximum_size,
                provider_maximum_size=self.product_maximum_size,
                deadline_at=datetime.datetime.now(datetime.UTC) + self.deadline,
                resource_class="workspace_download",
                publication_id=operation_id,
                callback=callback,
            )
        )
        if callback.body is None:
            raise WorkspaceDownloadError(
                "Runtime Workspace transfer completed without download data"
            )
        return callback.body
