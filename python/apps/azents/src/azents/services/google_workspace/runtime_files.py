"""Canonical Runner uploads consumed as bounded verified Google input snapshots."""

import dataclasses
import datetime
import hashlib
from collections.abc import Awaitable, Callable
from pathlib import PurePosixPath

from azcommon.infra.s3.service import S3Service
from azcommon.uuid import uuid7
from pydantic import BaseModel, ConfigDict, Field

from azents.core.file_transfer import GENERAL_FILE_MAXIMUM_BYTES
from azents.core.session_resource_authority import SessionResourceAuthority
from azents.runtime.transfer.present_file_publication import (
    OpaqueTransferObjectResolver,
)
from azents.runtime.transfer.runtime_to_server import (
    RuntimeToServerConsumerRequest,
    RuntimeToServerTransferService,
)
from azents.runtime.transfer.server_to_runtime import ServerToRuntimeTarget
from azents.services.file_storage import FileStorage
from azents.services.google_workspace.file_models import (
    GoogleFileInput,
    GooglePreparedFile,
    safe_file_name,
)
from azents.services.google_workspace.transport import GoogleSdkError


class _FileStat(BaseModel):
    model_config = ConfigDict(extra="ignore", hide_input_in_errors=True)
    is_file: bool = Field(strict=True)
    size: int = Field(ge=0, strict=True)


@dataclasses.dataclass(frozen=True)
class GoogleResolvedInput:
    file: GooglePreparedFile
    revalidate: Callable[[], Awaitable[None]] = dataclasses.field(repr=False)


@dataclasses.dataclass(frozen=True)
class GoogleRuntimeFileReader:
    """Reuse opaque Runtime transfer leases; no backend-local path interpretation."""

    storage: FileStorage
    transfers: RuntimeToServerTransferService
    objects: OpaqueTransferObjectResolver
    s3: S3Service
    resolve_target: Callable[[], Awaitable[ServerToRuntimeTarget]]
    authority: SessionResourceAuthority
    maximum_bytes: int

    def __post_init__(self) -> None:
        if not 0 < self.maximum_bytes <= GENERAL_FILE_MAXIMUM_BYTES:
            raise ValueError("Google Runtime input limit is outside the file policy.")

    async def read(
        self,
        value: GoogleFileInput,
        *,
        admit: Callable[[], Awaitable[None]],
    ) -> GoogleResolvedInput:
        if not PurePosixPath(value.source).is_absolute() or "://" in value.source:
            raise GoogleSdkError("invalid_runtime_path", dispatched=False, status=None)
        await admit()
        target = await self.resolve_target()
        metadata = _FileStat.model_validate(
            await self.storage.stat(value.source, agent_id=self.authority.agent_id)
        )
        if not metadata.is_file or metadata.size > self.maximum_bytes:
            raise GoogleSdkError(
                "file_unavailable_or_oversized", dispatched=False, status=None
            )
        consumer = await self.transfers.prepare_consumer(
            RuntimeToServerConsumerRequest(
                target=target,
                agent_id=self.authority.agent_id,
                session_id=self.authority.session_id,
                operation_id=f"{self.authority.run_id}:google-input:{uuid7().hex}",
                runtime_path=value.source,
                expected_size=metadata.size,
                expected_sha256=None,
                product_maximum_size=self.maximum_bytes,
                provider_maximum_size=self.maximum_bytes,
                deadline_at=datetime.datetime.now(datetime.UTC)
                + datetime.timedelta(seconds=60),
                resource_class="google-input",
                publication_id=uuid7().hex,
            )
        )
        try:
            await consumer.start_lease_renewal()
            upload = consumer.upload
            if upload.size != metadata.size or upload.size > self.maximum_bytes:
                raise GoogleSdkError(
                    "file_integrity_mismatch", dispatched=False, status=None
                )
            content = bytearray()
            digest = hashlib.sha256()
            async with self.s3.iter_chunks(
                self.objects.resolve(upload.object_handle.value),
                maximum_chunk_size=65536,
            ) as chunks:
                async for chunk in chunks:
                    await consumer.ensure_active()
                    await admit()
                    if len(content) + len(chunk) > upload.size:
                        raise GoogleSdkError(
                            "file_integrity_mismatch", dispatched=False, status=None
                        )
                    content.extend(chunk)
                    digest.update(chunk)
            if len(content) != upload.size or digest.hexdigest() != upload.sha256:
                raise GoogleSdkError(
                    "file_integrity_mismatch", dispatched=False, status=None
                )
            await admit()
            if await self.resolve_target() != target:
                raise GoogleSdkError(
                    "runtime_source_changed", dispatched=False, status=None
                )
            await consumer.complete()
            file = GooglePreparedFile(
                value.filename or safe_file_name(value.source, fallback="runtime-file"),
                value.media_type or "application/octet-stream",
                bytes(content),
                (),
            )
        finally:
            await consumer.close()

        async def revalidate() -> None:
            await admit()
            if await self.resolve_target() != target:
                raise GoogleSdkError(
                    "runtime_source_changed", dispatched=False, status=None
                )

        return GoogleResolvedInput(file, revalidate)
