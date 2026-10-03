"""Native optional mutation/patch interface declarations without throwing stubs."""

import dataclasses
import re
from collections.abc import Sequence

from sqlalchemy.ext.asyncio import AsyncSession

from azents.core.historical_memory_consolidation import ConsolidationJobPrincipal
from azents.core.vfs import VfsLocation
from azents.rdb.session import SessionManager
from azents.services.file_storage import GrepResult, TextReadResult
from azents.services.historical_memory.draft_vfs import ConsolidationDraftVfsBackend
from azents.services.vfs_mutation import (
    VfsBackendRegistration,
    VfsMutationCapabilities,
    VfsMutationInvocation,
    VfsMutationPreconditions,
    VfsMutationRequest,
    VfsMutationResult,
)
from azents.services.vfs_read import VfsGlobResult, VfsReadBackendCapabilities
from azents.testing.consolidation_vfs import bind_consolidation_test_vfs


@dataclasses.dataclass(frozen=True)
class _SingleFileWriter:
    """A functional read/writer delegating ordinary methods, with no patch interface."""

    backend: ConsolidationDraftVfsBackend

    @property
    def mount(self) -> str:
        return self.backend.mount

    @property
    def capabilities(self) -> VfsReadBackendCapabilities:
        return self.backend.capabilities

    async def read_text(
        self,
        context: ConsolidationJobPrincipal,
        location: VfsLocation,
        *,
        offset: int,
        limit: int,
        encoding: str,
    ) -> TextReadResult:
        return await self.backend.read_text(
            context, location, offset=offset, limit=limit, encoding=encoding
        )

    async def glob(
        self,
        context: ConsolidationJobPrincipal,
        location: VfsLocation,
        *,
        exclude_patterns: Sequence[str],
    ) -> VfsGlobResult:
        return await self.backend.glob(
            context, location, exclude_patterns=exclude_patterns
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
        return await self.backend.grep(
            context,
            location,
            pattern=pattern,
            recursive=recursive,
            exclude_patterns=exclude_patterns,
            max_matching_files=max_matching_files,
            max_lines_per_file=max_lines_per_file,
            max_searched_files=max_searched_files,
            max_scanned_bytes=max_scanned_bytes,
        )

    def freeze_mutation(
        self, principal: ConsolidationJobPrincipal, request: VfsMutationRequest
    ) -> VfsMutationPreconditions:
        return self.backend.freeze_mutation(principal, request)

    async def mutate(
        self,
        principal: ConsolidationJobPrincipal,
        request: VfsMutationRequest,
        preconditions: VfsMutationPreconditions,
        invocation: VfsMutationInvocation,
    ) -> VfsMutationResult:
        return await self.backend.mutate(principal, request, preconditions, invocation)


async def test_single_file_writer_is_complete_without_patch_members(
    rdb_session_manager: SessionManager[AsyncSession],
) -> None:
    binding = await bind_consolidation_test_vfs(rdb_session_manager)
    backend = _SingleFileWriter(binding.draft)
    registration = VfsBackendRegistration(
        backend, backend, None, VfsMutationCapabilities(True, False)
    )
    assert (
        registration.mutation_backend is backend and registration.patch_backend is None
    )
