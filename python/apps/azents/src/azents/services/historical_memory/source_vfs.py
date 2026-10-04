"""Closed exact-corpus summary surface for an independent consolidation job."""

import dataclasses
import fnmatch
import re
from collections.abc import Sequence

from azents.core.historical_memory_consolidation import ConsolidationJobPrincipal
from azents.core.vfs import VfsLocation
from azents.repos.historical_memory_consolidation.authority import (
    ConsolidationAuthorityError,
)
from azents.repos.historical_memory_consolidation.ownership import (
    ConsolidationOwnershipRepository,
)
from azents.repos.historical_memory_consolidation.sources import (
    ConsolidationSourceRepository,
)
from azents.repos.historical_memory_consolidation.work import (
    ConsolidationWorkRepository,
)
from azents.services.file_storage import GrepResult, TextReadResult
from azents.services.historical_memory.draft_vfs import ConsolidationVfsObservations
from azents.services.vfs_read import (
    VfsGlobResult,
    VfsReadBackendCapabilities,
    VfsReadError,
)
from azents.services.vfs_text import (
    VfsTextFile,
    bounded_vfs_regex_search,
    vfs_location_contains,
    vfs_pattern_matches,
)


@dataclasses.dataclass(frozen=True)
class ConsolidationVfsAuthorityValidator:
    """Completed repository admission, independent of all foreground identities."""

    repository: ConsolidationOwnershipRepository

    async def validate(self, context: ConsolidationJobPrincipal) -> None:
        try:
            await self.repository.validate(context)
        except ConsolidationAuthorityError:
            raise VfsReadError("not_found", "VFS location is unavailable.") from None


@dataclasses.dataclass(frozen=True)
class ConsolidationSourceVfsBackend:
    """Only this principal's prepared summaries and bounded metadata inventory."""

    repository: ConsolidationSourceRepository
    observations: ConsolidationVfsObservations
    work_repository: ConsolidationWorkRepository

    @property
    def mount(self) -> str:
        return "memory"

    @property
    def capabilities(self) -> VfsReadBackendCapabilities:
        return VfsReadBackendCapabilities(
            read_text=True, grep=True, glob=True, transfer_read=False
        )

    def source_uri(self, source_id: str) -> str:
        return (
            f"azents://memory/historical/{self.observations.principal.unit.scope.value}/"
            f"{source_id}/summary.md"
        )

    def _require(
        self, context: ConsolidationJobPrincipal, location: VfsLocation
    ) -> None:
        self.observations.require_principal(context)
        if location.mount != self.mount:
            raise VfsReadError("not_found", "VFS location is unavailable.")

    def _source_id(self, location: VfsLocation) -> str:
        parts = location.path.removeprefix("/").split("/")
        scope = self.observations.principal.unit.scope.value
        if (
            len(parts) != 4
            or parts[0] != "historical"
            or parts[1] != scope
            or parts[3] != "summary.md"
            or len(parts[2]) != 32
        ):
            raise VfsReadError("not_found", "VFS location is unavailable.")
        return parts[2]

    def _source_prefix(self, location: VfsLocation) -> str | None:
        """Narrow exact IDs and literal ID prefixes before inventory page limits."""
        parts = location.path.removeprefix("/").split("/")
        if (
            len(parts) < 2
            or parts[0] != "historical"
            or any(character in parts[1] for character in "*?[]{}")
        ):
            return None
        if parts[1] != self.observations.principal.unit.scope.value:
            raise VfsReadError("not_found", "VFS location is unavailable.")
        if len(parts) < 3:
            return None
        prefix = re.split(r"[*?\[{}]", parts[2], maxsplit=1)[0]
        if not prefix:
            return None
        if len(prefix) > 32 or any(
            character not in "0123456789abcdef" for character in prefix
        ):
            raise VfsReadError("not_found", "VFS location is unavailable.")
        return prefix

    async def read_text(
        self,
        context: ConsolidationJobPrincipal,
        location: VfsLocation,
        *,
        offset: int,
        limit: int,
        encoding: str,
    ) -> TextReadResult:
        self._require(context, location)
        if (
            offset < 0
            or limit < 1
            or encoding.lower().replace("_", "-") not in {"utf-8", "utf8"}
        ):
            raise ValueError("Scoped summary reads require positive bounds and UTF-8.")
        try:
            path = location.path.removeprefix("/")
            if path.startswith("inventory/work/") and path.endswith("/README.md"):
                parts = path.split("/")
                if len(parts) == 3:
                    after_sequence = None
                elif len(parts) == 4 and parts[2].isascii() and parts[2].isdigit():
                    after_sequence = int(parts[2])
                else:
                    raise VfsReadError("not_found", "VFS location is unavailable.")
                work = await self.work_repository.page(
                    context, after_sequence=after_sequence, limit=10
                )
                self.observations.record_source_epoch(work.observation_epoch)
                lines = ["# Pending source changes", ""]
                for entry in work.entries:
                    lines.append(
                        f"- Work {entry.work_id}; {entry.kind.value}; "
                        f"{self.source_uri(entry.version.source_session_id)} "
                        f"— {(entry.title or 'Untitled source')[:120]}"
                    )
                if work.next_after_sequence is not None:
                    lines.extend(
                        [
                            "",
                            "Next page: azents://memory/inventory/work/"
                            f"{work.next_after_sequence}/README.md",
                        ]
                    )
                full = "\n".join(lines) + "\n"
                text = full[offset : offset + limit]
                end = offset + len(text)
                return TextReadResult(text, offset, end, end < len(full))
            if path == "inventory/README.md" or (
                path.startswith("inventory/") and path.endswith("/README.md")
            ):
                parts = path.split("/")
                if len(parts) == 2:
                    after = None
                elif len(parts) == 3 and len(parts[1]) == 32:
                    after = parts[1]
                else:
                    raise VfsReadError("not_found", "VFS location is unavailable.")
                page = await self.repository.inventory(
                    context, after=after, limit=10, source_id_prefix=None
                )
                self.observations.record_source_epoch(page.observation_epoch)
                lines = ["# Prepared source inventory", ""]
                for entry in page.entries:
                    title = entry.title_snippet or "Untitled source"
                    lines.append(
                        f"- {self.source_uri(entry.version.source_session_id)} "
                        f"— {title}"
                    )
                if page.next_after is not None:
                    lines.extend(
                        [
                            "",
                            f"Next page: azents://memory/inventory/{page.next_after}/README.md",
                        ]
                    )
                full = "\n".join(lines) + "\n"
                text = full[offset : offset + limit]
                end = offset + len(text)
                return TextReadResult(text, offset, end, end < len(full))
            read = await self.repository.read(
                context,
                source_session_id=self._source_id(location),
                offset=offset,
                max_bytes=limit * 4,
            )
        except ConsolidationAuthorityError:
            raise VfsReadError("not_found", "VFS location is unavailable.") from None
        self.observations.record_source_epoch(read.observation_epoch)
        text = read.text[:limit]
        end = offset + len(text)
        return TextReadResult(
            text,
            offset,
            end,
            len(text) < len(read.text) or read.next_offset is not None,
        )

    async def glob(
        self,
        context: ConsolidationJobPrincipal,
        location: VfsLocation,
        *,
        exclude_patterns: Sequence[str],
    ) -> VfsGlobResult:
        self._require(context, location)
        page = await self.repository.inventory(
            context,
            after=None,
            limit=50,
            source_id_prefix=self._source_prefix(location),
        )
        self.observations.record_source_epoch(page.observation_epoch)
        uris = tuple(
            self.source_uri(entry.version.source_session_id)
            for entry in page.entries
            if vfs_pattern_matches(
                location.path,
                self.source_uri(entry.version.source_session_id).split(
                    "azents://memory/", 1
                )[1],
            )
            and not any(
                fnmatch.fnmatchcase(
                    self.source_uri(entry.version.source_session_id), pattern
                )
                for pattern in exclude_patterns
            )
        )
        return VfsGlobResult(
            uris,
            page.next_after is not None,
            "inventory_page_limit" if page.next_after is not None else None,
        )

    async def grep(
        self,
        context: ConsolidationJobPrincipal,
        location: VfsLocation,
        *,
        pattern: re.Pattern[str],
        recursive: bool,
        exclude_patterns: Sequence[str],
        max_matching_files: int,
        max_lines_per_file: int,
        max_searched_files: int,
        max_scanned_bytes: int,
    ) -> GrepResult:
        self._require(context, location)
        if (
            min(
                max_matching_files,
                max_lines_per_file,
                max_searched_files,
                max_scanned_bytes,
            )
            < 1
        ):
            raise ValueError("Scoped summary search bounds must be positive.")
        page = await self.repository.inventory(
            context,
            after=None,
            limit=min(50, max_searched_files),
            source_id_prefix=self._source_prefix(location),
        )
        self.observations.record_source_epoch(page.observation_epoch)
        files: list[VfsTextFile] = []
        scanned = 0
        scan_stop: str | None = None
        for entry in page.entries:
            uri = self.source_uri(entry.version.source_session_id)
            if not vfs_location_contains(location, uri, recursive=recursive):
                continue
            if any(fnmatch.fnmatchcase(uri, item) for item in exclude_patterns):
                continue
            if max_scanned_bytes - scanned < 4:
                scan_stop = "scanned_byte_limit"
                break
            offset = 0
            version = None
            chunks: list[str] = []
            while True:
                read = await self.repository.read(
                    context,
                    source_session_id=entry.version.source_session_id,
                    offset=offset,
                    max_bytes=max_scanned_bytes - scanned,
                )
                self.observations.record_source_epoch(read.observation_epoch)
                if version is not None and version != read.version:
                    raise VfsReadError(
                        "conflict", "Summary changed during search; read it again."
                    )
                version = read.version
                chunks.append(read.text)
                scanned += len(read.text.encode("utf-8"))
                if read.next_offset is None:
                    break
                if max_scanned_bytes - scanned < 4:
                    scan_stop = "scanned_byte_limit"
                    break
                offset = read.next_offset
            files.append(VfsTextFile(uri, "".join(chunks)))
            if scan_stop is not None:
                break
        result = await bounded_vfs_regex_search(
            files=files,
            pattern=pattern,
            max_matching_files=max_matching_files,
            max_lines_per_file=max_lines_per_file,
            max_searched_files=max_searched_files,
            max_scanned_bytes=max_scanned_bytes,
        )
        if scan_stop is not None and not result.truncated:
            return dataclasses.replace(result, truncated=True, stopped_reason=scan_stop)
        if page.next_after is not None and not result.truncated:
            return dataclasses.replace(
                result, truncated=True, stopped_reason="inventory_page_limit"
            )
        return result
