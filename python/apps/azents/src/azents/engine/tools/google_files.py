"""Bridge current product/Runner file authority to direct Google operation bytes."""

import dataclasses
import hashlib
from collections.abc import Awaitable, Callable
from pathlib import PurePosixPath
from typing import assert_never

from azcommon.infra.s3.service import S3ObjectIdentity, S3Service
from azcommon.result import Failure
from pydantic import BaseModel, ConfigDict

from azents.core.file_transfer import GENERAL_FILE_MAXIMUM_BYTES
from azents.core.google_oauth import GoogleOAuthError
from azents.core.session_resource_authority import SessionResourceAuthority
from azents.engine.tools.import_resolver import (
    ImportFileResolverRegistry,
    ResolvedArtifactImportSource,
    ResolvedExchangeImportSource,
    ResolvedVfsImportSource,
)
from azents.services.artifact import ArtifactService
from azents.services.google_workspace.errors import (
    GoogleCompletedStep,
    GoogleWorkspacePartialError,
)
from azents.services.google_workspace.file_models import (
    GoogleFileInput,
    GooglePreparedFile,
    safe_file_name,
)
from azents.services.google_workspace.runtime_files import (
    GoogleResolvedInput,
    GoogleRuntimeFileReader,
)
from azents.services.google_workspace.transport import GoogleSdkError


class GooglePublishedFile(BaseModel):
    model_config = ConfigDict(extra="forbid")
    artifact_id: str
    status: str
    expires_at: str
    uri: str
    filename: str
    media_type: str
    size: int
    sha256: str


@dataclasses.dataclass(frozen=True)
class GoogleFileBridge:
    """No borrowed user identity, provider URLs, or Worker-local path access."""

    resolver: ImportFileResolverRegistry
    runtime: GoogleRuntimeFileReader | None
    s3: S3Service
    bucket: str
    artifacts: ArtifactService
    authority: SessionResourceAuthority
    maximum_bytes: int

    def __post_init__(self) -> None:
        if not 0 < self.maximum_bytes <= GENERAL_FILE_MAXIMUM_BYTES:
            raise ValueError("Google file limit is outside the general file policy.")
        if self.runtime is not None and self.runtime.authority != self.authority:
            raise ValueError("Google file adapters must share exact Session authority.")

    async def resolve(
        self,
        value: GoogleFileInput,
        *,
        admit: Callable[[], Awaitable[None]],
    ) -> GoogleResolvedInput:
        await admit()
        if "://" not in value.source:
            if self.runtime is None or not PurePosixPath(value.source).is_absolute():
                raise GoogleSdkError(
                    "runtime_source_unavailable", dispatched=False, status=None
                )
            return await self.runtime.read(value, admit=admit)
        resolved = await self.resolver.resolve(value.source)
        if resolved.size < 0 or resolved.size > self.maximum_bytes:
            raise GoogleSdkError("file_input_limit", dispatched=False, status=None)
        expected_hash: str | None
        object_identity: S3ObjectIdentity | None
        match resolved:
            case ResolvedExchangeImportSource():
                expected_hash = resolved.source.file.sha256
                object_identity = S3ObjectIdentity(
                    bucket=self.bucket, key=resolved.source.file.object_key
                )
            case ResolvedArtifactImportSource():
                expected_hash = resolved.source.artifact.sha256
                object_identity = S3ObjectIdentity(
                    bucket=self.bucket, key=resolved.source.artifact.storage_key
                )
            case ResolvedVfsImportSource():
                expected_hash = resolved.source.entry.content_hash
                object_identity = None
            case _:
                assert_never(resolved)
        if not await resolved.revalidate():
            raise GoogleSdkError("file_source_changed", dispatched=False, status=None)
        if isinstance(resolved, ResolvedVfsImportSource):
            content = resolved.source.entry.decode_body()
        elif object_identity is not None:
            buffer = bytearray()
            async with self.s3.iter_chunks(
                object_identity, maximum_chunk_size=65536
            ) as chunks:
                async for chunk in chunks:
                    await admit()
                    if len(buffer) + len(chunk) > resolved.size:
                        raise GoogleSdkError(
                            "file_integrity_mismatch", dispatched=False, status=None
                        )
                    buffer.extend(chunk)
            content = bytes(buffer)
        else:
            raise AssertionError("Authorized Google source has no backing bytes.")
        if (
            len(content) != resolved.size
            or expected_hash is not None
            and hashlib.sha256(content).hexdigest() != expected_hash
        ):
            raise GoogleSdkError(
                "file_integrity_mismatch", dispatched=False, status=None
            )

        async def revalidate() -> None:
            await admit()
            if not await resolved.revalidate():
                raise GoogleSdkError(
                    "file_source_changed", dispatched=False, status=None
                )

        await revalidate()
        return GoogleResolvedInput(
            GooglePreparedFile(
                value.filename
                or safe_file_name(resolved.name, fallback="google-input"),
                value.media_type or resolved.media_type,
                content,
                (),
            ),
            revalidate,
        )

    async def publish(
        self,
        files: tuple[GooglePreparedFile, ...],
        *,
        tool_name: str,
        call_id: str,
        admit: Callable[[], Awaitable[None]],
    ) -> tuple[GooglePublishedFile, ...]:
        # One result can contain multiple body parts; validate all of them before
        # publishing a prefix. Publication is not a replay of any Google effect.
        if len(files) > 100 or sum(file.size for file in files) > self.maximum_bytes:
            raise GoogleSdkError("file_publication_limit", dispatched=True, status=None)
        published: list[GooglePublishedFile] = []
        for index, file in enumerate(files):
            try:
                await admit()
                result = await self.artifacts.create_for_authority(
                    authority=self.authority,
                    filename=file.filename,
                    media_type=file.media_type,
                    body=file.content,
                    source_tool_name=tool_name,
                    source_call_id=call_id,
                    source_part_index=index,
                    metadata={"google_source_ids": list(file.source_ids)},
                )
                if isinstance(result, Failure):
                    raise GoogleSdkError(
                        "file_publication_denied", dispatched=True, status=None
                    )
                artifact = result.value
                if artifact.size_bytes != file.size or artifact.sha256 != file.sha256:
                    raise GoogleSdkError(
                        "file_publication_integrity", dispatched=True, status=None
                    )
                published.append(
                    GooglePublishedFile(
                        artifact_id=artifact.id,
                        status=artifact.status.value,
                        expires_at=artifact.expires_at.isoformat(),
                        uri=artifact.uri,
                        filename=artifact.name,
                        media_type=artifact.media_type,
                        size=artifact.size_bytes,
                        sha256=file.sha256,
                    )
                )
                await admit()
            except (GoogleSdkError, GoogleOAuthError) as error:
                if not published:
                    raise
                raise GoogleWorkspacePartialError(
                    completed=tuple(
                        GoogleCompletedStep(
                            action="publish_file",
                            resource_ids=(item.uri,),
                        )
                        for item in published
                    ),
                    unconfirmed_action="publish_file",
                    remaining_ids=tuple(str(item) for item in range(index, len(files))),
                    cause_code=error.code,
                    status=error.status if isinstance(error, GoogleSdkError) else None,
                    dispatched=True,
                ) from None
        return tuple(published)
