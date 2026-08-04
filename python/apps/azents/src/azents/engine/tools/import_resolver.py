"""import_file URI resolver."""

import dataclasses
from collections.abc import Awaitable, Callable, Mapping
from typing import Protocol, assert_never

from azcommon.result import Success

from azents.services.artifact import (
    ArtifactAccessDenied,
    ArtifactExpired,
    ArtifactNotFound,
    ArtifactService,
    ArtifactSessionNotFound,
    ArtifactTransferSource,
    ArtifactUnavailable,
)
from azents.services.exchange_file import (
    ExchangeFileService,
    ExchangeFileTransferSource,
    FileAccessDenied,
    FileExpired,
    FileNotFound,
    FileUnavailable,
    SessionNotFound,
)
from azents.services.session_resource_authority import SessionResourceAuthority
from azents.services.vfs import VfsFileResolutionError, VfsResolvedFile


@dataclasses.dataclass(frozen=True)
class ResolvedExchangeImportSource:
    """Authorized metadata-only Exchange import source."""

    source: ExchangeFileTransferSource
    name: str
    media_type: str
    size: int
    source_uri: str
    source_kind: str
    revalidate: Callable[[], Awaitable[bool]]


@dataclasses.dataclass(frozen=True)
class ResolvedArtifactImportSource:
    """Authorized metadata-only Artifact import source."""

    source: ArtifactTransferSource
    name: str
    media_type: str
    size: int
    source_uri: str
    source_kind: str
    revalidate: Callable[[], Awaitable[bool]]


@dataclasses.dataclass(frozen=True)
class ResolvedVfsImportSource:
    """Authorized current-run VFS import source without eager decode."""

    source: VfsResolvedFile
    name: str
    media_type: str
    size: int
    source_uri: str
    source_kind: str
    revalidate: Callable[[], Awaitable[bool]]


ImportResolvedFile = (
    ResolvedExchangeImportSource
    | ResolvedArtifactImportSource
    | ResolvedVfsImportSource
)


class ImportResolveError(Exception):
    """import_file resolver error."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


class ImportFileResolver(Protocol):
    """import_file URI resolver protocol."""

    async def resolve(self, uri: str) -> ImportResolvedFile:
        """Resolve URI to one authorized metadata-only source."""
        ...


class VfsTransferFileResolver(Protocol):
    """Resolve one current-run VFS file for an authorized transfer."""

    async def resolve_transfer_file(
        self,
        *,
        run_id: str,
        agent_id: str,
        session_id: str,
        workspace_id: str,
        uri: str,
    ) -> VfsResolvedFile:
        """Resolve one VFS entry without eager body decoding."""
        ...


class ImportFileResolverRegistry:
    """import_file resolver registry by scheme."""

    def __init__(self, resolvers: Mapping[str, ImportFileResolver]) -> None:
        self._resolvers = dict(resolvers)

    async def resolve(self, uri: str) -> ImportResolvedFile:
        """Resolve file with resolver matching URI scheme."""
        scheme = _scheme(uri)
        if scheme is None:
            raise ImportResolveError("invalid_uri", f"Invalid file URI: {uri}")
        resolver = self._resolvers.get(scheme)
        if resolver is None:
            raise ImportResolveError(
                "unsupported_scheme",
                f"Unsupported file URI scheme: {scheme}",
            )
        return await resolver.resolve(uri)


@dataclasses.dataclass(frozen=True)
class ExchangeImportResolver:
    """Exchange URI resolver."""

    exchange_file_service: ExchangeFileService
    authority: SessionResourceAuthority

    async def resolve(self, uri: str) -> ImportResolvedFile:
        """Resolve Exchange URI to metadata without downloading its body."""
        result = await self.exchange_file_service.resolve_transfer_source_for_authority(
            uri=uri,
            authority=self.authority,
        )
        if result.failure:
            match result.error:
                case SessionNotFound() | FileNotFound():
                    raise ImportResolveError("not_found", f"File not found: {uri}")
                case FileAccessDenied():
                    raise ImportResolveError(
                        "permission_denied", f"File access denied: {uri}"
                    )
                case FileExpired():
                    raise ImportResolveError(
                        "expired", f"File is no longer available: {uri}"
                    )
                case FileUnavailable():
                    raise ImportResolveError(
                        "storage_unavailable", f"File content is unavailable: {uri}"
                    )
                case _:
                    assert_never(result.error)
        source = result.value
        file = source.file

        async def revalidate() -> bool:
            current = (
                await self.exchange_file_service.resolve_transfer_source_for_authority(
                    uri=uri,
                    authority=self.authority,
                )
            )
            return (
                isinstance(current, Success)
                and current.value.file.id == file.id
                and current.value.file.sha256 == file.sha256
                and current.value.file.size_bytes == file.size_bytes
            )

        return ResolvedExchangeImportSource(
            source=source,
            name=file.filename,
            media_type=file.media_type,
            size=file.size_bytes,
            source_uri=uri,
            source_kind="exchange",
            revalidate=revalidate,
        )


@dataclasses.dataclass(frozen=True)
class ArtifactImportResolver:
    """Artifact URI resolver."""

    artifact_service: ArtifactService
    authority: SessionResourceAuthority

    async def resolve(self, uri: str) -> ImportResolvedFile:
        """Resolve Artifact URI to metadata without downloading its body."""
        result = await self.artifact_service.resolve_transfer_source_for_authority(
            uri=uri,
            authority=self.authority,
        )
        if result.failure:
            match result.error:
                case ArtifactSessionNotFound() | ArtifactNotFound():
                    raise ImportResolveError("not_found", f"Artifact not found: {uri}")
                case ArtifactAccessDenied():
                    raise ImportResolveError(
                        "permission_denied", f"Artifact access denied: {uri}"
                    )
                case ArtifactExpired():
                    raise ImportResolveError(
                        "expired", f"Artifact is no longer available: {uri}"
                    )
                case ArtifactUnavailable():
                    raise ImportResolveError(
                        "storage_unavailable", f"Artifact content is unavailable: {uri}"
                    )
                case _:
                    assert_never(result.error)
        source = result.value
        artifact = source.artifact

        async def revalidate() -> bool:
            current = await self.artifact_service.resolve_transfer_source_for_authority(
                uri=uri,
                authority=self.authority,
            )
            return (
                isinstance(current, Success)
                and current.value.artifact.id == artifact.id
                and current.value.artifact.sha256 == artifact.sha256
                and current.value.artifact.size_bytes == artifact.size_bytes
            )

        return ResolvedArtifactImportSource(
            source=source,
            name=artifact.name,
            media_type=artifact.media_type,
            size=artifact.size_bytes,
            source_uri=uri,
            source_kind="artifact",
            revalidate=revalidate,
        )


@dataclasses.dataclass(frozen=True)
class AzentsImportResolver:
    """Current-run Azents VFS URI resolver."""

    vfs_projection_service: VfsTransferFileResolver
    authority: SessionResourceAuthority

    async def resolve(self, uri: str) -> ImportResolvedFile:
        """Resolve one authorized VFS entry without eager body decoding."""
        try:
            resolved = await self.vfs_projection_service.resolve_transfer_file(
                run_id=self.authority.run_id,
                agent_id=self.authority.agent_id,
                session_id=self.authority.session_id,
                workspace_id=self.authority.workspace_id,
                uri=uri,
            )
        except VfsFileResolutionError as exc:
            raise ImportResolveError(exc.code, exc.message) from None
        entry = resolved.entry

        async def revalidate() -> bool:
            try:
                current = await self.vfs_projection_service.resolve_transfer_file(
                    run_id=self.authority.run_id,
                    agent_id=self.authority.agent_id,
                    session_id=self.authority.session_id,
                    workspace_id=self.authority.workspace_id,
                    uri=uri,
                )
            except VfsFileResolutionError:
                return False
            return (
                current.projection_revision_id == resolved.projection_revision_id
                and current.projection_hash == resolved.projection_hash
                and current.entry.canonical_uri == entry.canonical_uri
                and current.entry.content_hash == entry.content_hash
                and current.entry.size_bytes == entry.size_bytes
            )

        return ResolvedVfsImportSource(
            source=resolved,
            name=entry.canonical_uri.rsplit("/", 1)[-1],
            media_type=entry.media_type,
            size=entry.size_bytes,
            source_uri=entry.canonical_uri,
            source_kind="azents",
            revalidate=revalidate,
        )


def _scheme(uri: str) -> str | None:
    """Return URI scheme."""
    marker = "://"
    if marker not in uri:
        return None
    scheme, _ = uri.split(marker, 1)
    if not scheme:
        return None
    return scheme
