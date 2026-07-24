"""import_file URI resolver."""

import dataclasses
from collections.abc import Mapping
from typing import Protocol, assert_never

from azents.services.artifact import (
    ArtifactAccessDenied,
    ArtifactExpired,
    ArtifactNotFound,
    ArtifactService,
    ArtifactSessionNotFound,
    ArtifactUnavailable,
)
from azents.services.exchange_file import (
    ExchangeFileService,
    FileAccessDenied,
    FileExpired,
    FileNotFound,
    FileUnavailable,
    SessionNotFound,
)
from azents.services.session_resource_authority import SessionResourceAuthority
from azents.services.vfs import VfsFileResolutionError, VfsProjectionService


@dataclasses.dataclass(frozen=True)
class ImportResolvedFile:
    """import_file resolver result."""

    body: bytes
    name: str
    media_type: str
    size: int
    source_uri: str
    source_kind: str


class ImportResolveError(Exception):
    """import_file resolver error."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


class ImportFileResolver(Protocol):
    """import_file URI resolver protocol."""

    async def resolve(self, uri: str) -> ImportResolvedFile:
        """Resolve URI to file copyable into runtime."""
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
        """Resolve Exchange URI to file bytes."""
        result = await self.exchange_file_service.resolve_for_authority(
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
        file = result.value.file
        return ImportResolvedFile(
            body=result.value.body,
            name=file.filename,
            media_type=file.media_type,
            size=file.size_bytes,
            source_uri=uri,
            source_kind="exchange",
        )


@dataclasses.dataclass(frozen=True)
class ArtifactImportResolver:
    """Artifact URI resolver."""

    artifact_service: ArtifactService
    authority: SessionResourceAuthority

    async def resolve(self, uri: str) -> ImportResolvedFile:
        """Resolve Artifact URI to file bytes."""
        result = await self.artifact_service.resolve_for_authority(
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
        artifact = result.value.artifact
        return ImportResolvedFile(
            body=result.value.body,
            name=artifact.name,
            media_type=artifact.media_type,
            size=artifact.size_bytes,
            source_uri=uri,
            source_kind="artifact",
        )


@dataclasses.dataclass(frozen=True)
class AzentsImportResolver:
    """Current-run Azents VFS URI resolver."""

    vfs_projection_service: VfsProjectionService
    authority: SessionResourceAuthority

    async def resolve(self, uri: str) -> ImportResolvedFile:
        """Resolve an authorized VFS entry to verified file bytes."""
        try:
            resolved = await self.vfs_projection_service.resolve_file(
                run_id=self.authority.run_id,
                agent_id=self.authority.agent_id,
                session_id=self.authority.session_id,
                workspace_id=self.authority.workspace_id,
                uri=uri,
            )
        except VfsFileResolutionError as exc:
            raise ImportResolveError(exc.code, exc.message) from None
        entry = resolved.entry
        try:
            body = entry.decode_body()
        except ValueError as exc:
            raise ImportResolveError(
                "storage_unavailable",
                f"VFS file content is unavailable: {entry.canonical_uri}",
            ) from exc
        return ImportResolvedFile(
            body=body,
            name=entry.canonical_uri.rsplit("/", 1)[-1],
            media_type=entry.media_type,
            size=entry.size_bytes,
            source_uri=entry.canonical_uri,
            source_kind="azents",
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
