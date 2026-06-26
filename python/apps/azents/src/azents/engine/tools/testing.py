"""Common utilities for tool tests.

Provides helpers reused in tests, such as fake storage.
"""

import fnmatch
import re

from azents.engine.io.attachments import RuntimeAttachment
from azents.services.file_storage import GrepFileMatch, GrepLineMatch, GrepResult
from azents.services.session_storage import guess_media_type


class FakeSharedStorage:
    """Storage for tests. Simulates absolute path based file access.

    Files are stored by runtime absolute path key, e.g. ``/workspace/agent/file.txt``.
    """

    def __init__(
        self,
        files: dict[str, bytes] | None = None,
        *,
        raise_permission_on_put: bool = False,
    ) -> None:
        self._files = dict(files) if files else {}
        self._raise_permission_on_put = raise_permission_on_put
        self.put_calls: list[tuple[str, bytes]] = []

    def add_file(self, path: str, data: bytes) -> None:
        """Add test data."""
        self._files[path] = data

    async def get(
        self,
        path: str,
        *,
        agent_id: str = "",
        user_id: str = "",
        limit: int = 0,
    ) -> bytes:
        """Return file."""
        if path not in self._files:
            raise FileNotFoundError(f"File not found: {path}")
        data = self._files[path]
        if limit > 0:
            # Truncate text files by character count and return
            text = data.decode("utf-8", errors="replace")[:limit]
            return text.encode("utf-8")
        return data

    async def put(
        self,
        path: str,
        data: bytes,
        media_type: str = "",
        *,
        agent_id: str = "",
        user_id: str = "",
    ) -> RuntimeAttachment:
        """Simulate file storage."""
        if self._raise_permission_on_put:
            raise PermissionError(f"Cannot write to read-only path: {path}")
        self._files[path] = data
        self.put_calls.append((path, data))
        name = path.rsplit("/", 1)[-1]
        if not media_type:
            media_type = guess_media_type(path)
        return RuntimeAttachment(
            uri=path,
            media_type=media_type,
            size=len(data),
            name=name,
            text_preview=None,
        )

    async def exists(
        self,
        path: str,
        *,
        agent_id: str = "",
        user_id: str = "",
    ) -> bool:
        """Check whether file exists."""
        return path in self._files

    async def list(
        self,
        path: str,
        *,
        agent_id: str = "",
        user_id: str = "",
        recursive: bool = False,
        exclude_patterns: list[str] | None = None,
        include_directories: bool = False,
    ) -> list[RuntimeAttachment]:
        """Return the file list."""
        del agent_id, user_id
        if path in self._files:
            return [_file_attachment(path, self._files[path])]
        prefix = path.rstrip("/") + "/"
        exclude_values = exclude_patterns if exclude_patterns is not None else []
        by_uri: dict[str, RuntimeAttachment] = {}
        for key, data in sorted(self._files.items()):
            if not key.startswith(prefix):
                continue
            remainder = key[len(prefix) :]
            if _excluded(remainder, exclude_values):
                continue
            parts = remainder.split("/")
            if include_directories:
                directory_count = (
                    len(parts) - 1 if recursive else min(len(parts) - 1, 1)
                )
                for index in range(1, directory_count + 1):
                    relative_dir = "/".join(parts[:index])
                    if _excluded(relative_dir, exclude_values):
                        continue
                    uri = prefix + relative_dir
                    by_uri[uri] = _directory_attachment(uri)
            if recursive or "/" not in remainder:
                by_uri[key] = _file_attachment(key, data)
        return [by_uri[uri] for uri in sorted(by_uri)]

    async def list_dirs(
        self,
        path: str,
        *,
        agent_id: str = "",
        user_id: str = "",
    ) -> list[str]:
        """Return subdirectory name list."""
        prefix = path.rstrip("/") + "/"
        dirs: set[str] = set()
        for key in self._files:
            if not key.startswith(prefix):
                continue
            # First segment after prefix is directory name
            remainder = key[len(prefix) :]
            parts = remainder.split("/")
            if len(parts) > 1:
                dirs.add(parts[0])
        return sorted(dirs)

    async def grep(
        self,
        path: str,
        *,
        agent_id: str = "",
        pattern: str,
        recursive: bool = True,
        exclude_patterns: list[str] | None = None,
        max_matching_files: int = 50,
        max_lines_per_file: int = 10,
        max_searched_files: int | None = None,
        max_scanned_bytes: int | None = None,
    ) -> GrepResult:
        """Simulate grep inside storage."""
        attachments = await self.list(
            path,
            agent_id=agent_id,
            recursive=recursive,
            exclude_patterns=exclude_patterns,
        )
        regex = re.compile(pattern)
        files: list[GrepFileMatch] = []
        searched_file_count = 0
        scanned_bytes = 0
        stopped_reason: str | None = None
        for attachment in attachments:
            if len(files) >= max_matching_files:
                stopped_reason = "matching_file_limit"
                break
            if (
                max_searched_files is not None
                and searched_file_count >= max_searched_files
            ):
                stopped_reason = "searched_file_limit"
                break
            data = await self.get(attachment.uri, agent_id=agent_id)
            searched_file_count += 1
            scanned_bytes += len(data)
            if max_scanned_bytes is not None and scanned_bytes > max_scanned_bytes:
                stopped_reason = "scanned_byte_limit"
                break
            try:
                text = data.decode("utf-8")
            except UnicodeDecodeError:
                continue
            lines: list[GrepLineMatch] = []
            file_truncated = False
            for line_number, line in enumerate(text.splitlines(), start=1):
                if not regex.search(line):
                    continue
                if len(lines) >= max_lines_per_file:
                    file_truncated = True
                    break
                lines.append(GrepLineMatch(line_number=line_number, text=line))
            if lines:
                files.append(
                    GrepFileMatch(
                        path=attachment.uri,
                        lines=tuple(lines),
                        truncated=file_truncated,
                    )
                )
        return GrepResult(
            files=tuple(files),
            searched_file_count=searched_file_count,
            matched_file_count=len(files),
            truncated=stopped_reason is not None,
            stopped_reason=stopped_reason,
        )

    async def stat(
        self,
        path: str,
        *,
        agent_id: str = "",
        user_id: str = "",
    ) -> dict[str, object]:
        """Return file metadata."""
        if path not in self._files:
            raise FileNotFoundError(f"File not found: {path}")
        return {
            "size": len(self._files[path]),
            "modified_at": "0",
            "is_file": True,
        }

    async def delete(
        self,
        path: str,
        *,
        agent_id: str = "",
        user_id: str = "",
    ) -> None:
        """Delete file."""
        if path in self._files:
            del self._files[path]


def _excluded(relative_path: str, patterns: list[str]) -> bool:
    """Check whether relative path matches exclude pattern."""
    parts = relative_path.split("/")
    for pattern in patterns:
        if fnmatch.fnmatch(relative_path, pattern):
            return True
        if any(fnmatch.fnmatch(part, pattern) for part in parts):
            return True
    return False


def _file_attachment(path: str, data: bytes) -> RuntimeAttachment:
    """Build a file RuntimeAttachment."""
    name = path.rsplit("/", 1)[-1]
    return RuntimeAttachment(
        uri=path,
        media_type=guess_media_type(path),
        size=len(data),
        name=name,
        text_preview=None,
    )


def _directory_attachment(path: str) -> RuntimeAttachment:
    """Build a directory RuntimeAttachment."""
    return RuntimeAttachment(
        uri=path,
        media_type="inode/directory",
        size=0,
        name=path.rstrip("/").rsplit("/", 1)[-1],
        text_preview=None,
    )
