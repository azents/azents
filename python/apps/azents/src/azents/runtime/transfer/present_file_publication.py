"""Server-only Exchange publication adapter for verified Runtime uploads."""

import datetime
from dataclasses import dataclass
from typing import Protocol

from azcommon.infra.s3.service import S3ObjectIdentity
from azcommon.result import Failure, Success

from azents.core.enums import ExchangeFileProvenanceKind
from azents.repos.exchange_file.data import ExchangeFile
from azents.runtime.transfer.object_store import runtime_transfer_object_identity
from azents.runtime.transfer.runtime_to_server import (
    RuntimeToServerPublicationCallback,
    RuntimeToServerTransferRequest,
    VerifiedRuntimeUpload,
)
from azents.runtime.transfer.server_to_runtime import ServerToRuntimeTarget
from azents.services.exchange_file import ExchangeFileService
from azents.services.session_resource_authority import SessionResourceAuthority


class RuntimeToServerTransferExecutor(Protocol):
    """Execute one opaque Runtime-to-server transfer."""

    async def transfer(self, request: RuntimeToServerTransferRequest) -> None:
        """Complete the requested Runtime upload publication."""
        ...


class PresentFilePublicationError(RuntimeError):
    """Raised when a verified Runtime upload cannot publish to Exchange."""


class PresentFilePublicationAccessDenied(PresentFilePublicationError):
    """Raised when Exchange authority validation denies publication."""


class OpaqueTransferObjectResolver(Protocol):
    """Resolve opaque transfer handles only inside trusted server code."""

    def resolve(self, opaque_handle: str) -> S3ObjectIdentity:
        """Return the trusted internal object identity for one opaque handle."""
        ...


@dataclass(frozen=True)
class RuntimeTransferObjectResolver:
    """Resolve trusted opaque handles within the configured transfer namespace."""

    bucket: str
    object_prefix: str

    def resolve(self, opaque_handle: str) -> S3ObjectIdentity:
        """Resolve one opaque handle without exposing storage identity externally."""
        return runtime_transfer_object_identity(
            bucket=self.bucket,
            object_prefix=self.object_prefix,
            opaque_key=opaque_handle,
        )


@dataclass(frozen=True)
class PresentFilePublicationRequest:
    """Metadata-only request to publish one Runtime path as Exchange."""

    runtime_path: str
    filename: str
    media_type: str
    expected_size: int
    authority: SessionResourceAuthority
    target: ServerToRuntimeTarget
    publication_id: str


class _ExchangePublicationCallback(RuntimeToServerPublicationCallback):
    """Own Exchange publication after the opaque service verifies Runtime bytes."""

    def __init__(
        self,
        *,
        resolver: OpaqueTransferObjectResolver,
        exchange_file_service: ExchangeFileService,
        request: PresentFilePublicationRequest,
    ) -> None:
        self.resolver = resolver
        self.exchange_file_service = exchange_file_service
        self.request = request
        self.published: ExchangeFile | None = None

    async def publish(self, upload: VerifiedRuntimeUpload) -> None:
        """Resolve the opaque handle privately and commit Exchange metadata."""
        source = self.resolver.resolve(upload.object_handle.value)
        create_verified_object = (
            self.exchange_file_service.create_from_verified_object_for_authority
        )
        result = await create_verified_object(
            authority=self.request.authority,
            source=source,
            size_bytes=upload.size,
            sha256=upload.sha256,
            publication_id=upload.publication_id,
            provenance_kind=ExchangeFileProvenanceKind.TOOL,
            source_tool_name="present_file",
            source_provider=None,
            filename=self.request.filename,
            media_type=self.request.media_type,
        )
        if isinstance(result, Failure):
            raise PresentFilePublicationAccessDenied("Exchange publication was denied")
        if not isinstance(result, Success):
            raise PresentFilePublicationError("Unexpected Exchange publication result")
        self.published = result.value


class PresentFilePublicationService:
    """Compose opaque Runtime uploads with server-only Exchange publishing."""

    def __init__(
        self,
        *,
        transfer_service: RuntimeToServerTransferExecutor,
        resolver: OpaqueTransferObjectResolver,
        exchange_file_service: ExchangeFileService,
        product_maximum_size: int,
        provider_maximum_size: int,
        deadline: datetime.timedelta,
    ) -> None:
        self.transfer_service = transfer_service
        self.resolver = resolver
        self.exchange_file_service = exchange_file_service
        self.product_maximum_size = product_maximum_size
        self.provider_maximum_size = provider_maximum_size
        self.deadline = deadline

    async def publish(self, request: PresentFilePublicationRequest) -> ExchangeFile:
        """Return only after Exchange commit and opaque transfer settlement succeed."""
        callback = _ExchangePublicationCallback(
            resolver=self.resolver,
            exchange_file_service=self.exchange_file_service,
            request=request,
        )
        await self.transfer_service.transfer(
            RuntimeToServerTransferRequest(
                target=request.target,
                agent_id=request.authority.agent_id,
                session_id=request.authority.session_id,
                operation_id=f"present-file-{request.publication_id}",
                runtime_path=request.runtime_path,
                expected_size=request.expected_size,
                expected_sha256=None,
                product_maximum_size=self.product_maximum_size,
                provider_maximum_size=self.provider_maximum_size,
                deadline_at=datetime.datetime.now(datetime.UTC) + self.deadline,
                resource_class="present_file",
                publication_id=request.publication_id,
                callback=callback,
            )
        )
        if callback.published is None:
            raise PresentFilePublicationError(
                "Runtime upload completed without Exchange publication"
            )
        return callback.published
