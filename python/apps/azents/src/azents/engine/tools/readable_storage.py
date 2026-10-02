"""Runtime-independent routing adapter for generic read, grep, and glob tools."""

from __future__ import annotations

import dataclasses
import re
from collections.abc import Callable
from typing import Protocol

from azents.core.runtime_capabilities import (
    RuntimeCapability,
    RuntimeCapabilityDeniedError,
    RuntimeCapabilityResolver,
)
from azents.engine.io.attachments import RuntimeAttachment
from azents.engine.run.types import FunctionToolError
from azents.services.file_storage import (
    FileStorage,
    GlobResult,
    GrepResult,
    TextReadResult,
)
from azents.services.session_storage import guess_media_type
from azents.services.vfs_read import VfsReadContext, VfsReadError, VfsReadRouter

_DEFAULT_MAX_MATCHING_FILES = 50
_DEFAULT_MAX_LINES_PER_FILE = 10
_DEFAULT_MAX_SEARCHED_FILES = 10_000
_DEFAULT_MAX_SCANNED_BYTES = 128 * 1024 * 1024


class RuntimeReadableStorageProvider(Protocol):
    """Runtime Toolkit bridge for lazy absolute-path storage operations."""

    def make_readable_storage(self) -> FileStorage:
        """Return an operation-local Runtime file storage adapter."""
        ...


@dataclasses.dataclass(frozen=True)
class RoutedReadableStorage:
    """Route absolute Runtime paths and canonical VFS locations lazily."""

    agent_id: str
    vfs_router: VfsReadRouter
    vfs_context: VfsReadContext
    runtime_storage_factory: Callable[[], FileStorage] | None
    runtime_capability_resolver: RuntimeCapabilityResolver

    async def get_text(
        self,
        path: str,
        *,
        agent_id: str,
        offset: int,
        limit: int,
        encoding: str,
    ) -> TextReadResult:
        """Read one Runtime or VFS text range without materializing a mount."""
        self._require_agent(agent_id)
        if path.startswith("azents://"):
            try:
                return await self.vfs_router.read_text(
                    self.vfs_context,
                    path,
                    offset=offset,
                    limit=limit,
                    encoding=encoding,
                )
            except VfsReadError as exc:
                if exc.code == "not_found":
                    raise FileNotFoundError(path) from None
                raise ValueError(exc.message) from None
        storage = await self._runtime_storage(path)
        return await storage.get_text(
            path,
            agent_id=agent_id,
            offset=offset,
            limit=limit,
            encoding=encoding,
        )

    async def glob(
        self,
        pattern: str,
        *,
        agent_id: str,
        exclude_patterns: list[str] | None,
    ) -> GlobResult:
        """Glob one Runtime path pattern or canonical VFS pattern."""
        self._require_agent(agent_id)
        if pattern.startswith("azents://"):
            try:
                result = await self.vfs_router.glob(
                    self.vfs_context,
                    pattern,
                    exclude_patterns=exclude_patterns or (),
                )
            except VfsReadError as exc:
                raise ValueError(exc.message) from None
            return GlobResult(
                files=tuple(
                    RuntimeAttachment(
                        uri=uri,
                        media_type=guess_media_type(uri),
                        size=0,
                        name=uri.rsplit("/", 1)[-1],
                        text_preview=None,
                    )
                    for uri in result.uris
                ),
                truncated=result.truncated,
                stopped_reason=result.stopped_reason,
            )
        storage = await self._runtime_storage(pattern)
        return await storage.glob(
            pattern,
            agent_id=agent_id,
            exclude_patterns=exclude_patterns,
        )

    async def grep(
        self,
        path: str,
        *,
        agent_id: str,
        pattern: str,
        recursive: bool = True,
        exclude_patterns: list[str] | None = None,
        max_matching_files: int = _DEFAULT_MAX_MATCHING_FILES,
        max_lines_per_file: int = _DEFAULT_MAX_LINES_PER_FILE,
        max_searched_files: int | None = None,
        max_scanned_bytes: int | None = None,
    ) -> GrepResult:
        """Search one Runtime or VFS file/directory location."""
        self._require_agent(agent_id)
        if path.startswith("azents://"):
            try:
                compiled = re.compile(pattern)
                return await self.vfs_router.grep(
                    self.vfs_context,
                    path,
                    pattern=compiled,
                    recursive=recursive,
                    exclude_patterns=exclude_patterns or (),
                    max_matching_files=max_matching_files,
                    max_lines_per_file=max_lines_per_file,
                    max_searched_files=(
                        max_searched_files or _DEFAULT_MAX_SEARCHED_FILES
                    ),
                    max_scanned_bytes=(max_scanned_bytes or _DEFAULT_MAX_SCANNED_BYTES),
                )
            except VfsReadError as exc:
                raise ValueError(exc.message) from None
        storage = await self._runtime_storage(path)
        return await storage.grep(
            path,
            agent_id=agent_id,
            pattern=pattern,
            recursive=recursive,
            exclude_patterns=exclude_patterns,
            max_matching_files=max_matching_files,
            max_lines_per_file=max_lines_per_file,
            max_searched_files=max_searched_files,
            max_scanned_bytes=max_scanned_bytes,
        )

    async def _runtime_storage(self, location: str) -> FileStorage:
        if not location.startswith("/"):
            raise ValueError(
                "Storage location must be an absolute Runtime path or canonical "
                "azents:// URI."
            )
        try:
            await self.runtime_capability_resolver.require(
                RuntimeCapability.RUNTIME_FILESYSTEM
            )
        except RuntimeCapabilityDeniedError as exc:
            raise FunctionToolError(
                "Runtime capability is unavailable.",
                metadata={
                    "kind": "runtime_capability_denied",
                    "capability": RuntimeCapability.RUNTIME_FILESYSTEM.value,
                    "reason_code": exc.reason_code,
                },
            ) from None
        if self.runtime_storage_factory is None:
            raise FunctionToolError(
                "Runtime capability context is unavailable.",
                metadata={
                    "kind": "runtime_capability_denied",
                    "capability": RuntimeCapability.RUNTIME_FILESYSTEM.value,
                    "reason_code": "runtime_capability_context_missing",
                },
            )
        return self.runtime_storage_factory()

    def _require_agent(self, agent_id: str) -> None:
        if agent_id != self.agent_id:
            raise ValueError("Readable storage Agent does not match the Toolkit")
