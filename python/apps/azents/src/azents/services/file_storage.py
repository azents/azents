"""File storage protocol."""

import dataclasses
from typing import Protocol

from azents.engine.io.attachments import RuntimeAttachment


@dataclasses.dataclass(frozen=True)
class GrepLineMatch:
    """grep line match."""

    line_number: int
    text: str


@dataclasses.dataclass(frozen=True)
class GrepFileMatch:
    """grep file match."""

    path: str
    lines: tuple[GrepLineMatch, ...]
    truncated: bool


@dataclasses.dataclass(frozen=True)
class GrepResult:
    """grep result."""

    files: tuple[GrepFileMatch, ...]
    searched_file_count: int
    matched_file_count: int
    truncated: bool


class FileStorage(Protocol):
    """Common file storage interface used by Runtime file tool."""

    async def get(self, path: str, *, agent_id: str) -> bytes: ...

    async def stat(
        self,
        path: str,
        *,
        agent_id: str,
    ) -> dict[str, object]:
        """Return file metadata."""
        ...

    async def put(
        self,
        path: str,
        data: bytes,
        media_type: str = "",
        *,
        agent_id: str,
    ) -> RuntimeAttachment: ...

    async def delete(self, path: str, *, agent_id: str) -> None: ...

    async def exists(self, path: str, *, agent_id: str) -> bool: ...

    async def list(
        self,
        path: str,
        *,
        agent_id: str,
        recursive: bool = False,
        exclude_patterns: list[str] | None = None,
    ) -> list[RuntimeAttachment]: ...

    async def list_dirs(self, path: str, *, agent_id: str) -> list[str]: ...

    async def grep(
        self,
        path: str,
        *,
        agent_id: str,
        pattern: str,
        recursive: bool = True,
        exclude_patterns: list[str] | None = None,
        max_matching_files: int = 50,
        max_lines_per_file: int = 10,
    ) -> GrepResult: ...
