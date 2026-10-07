"""Current execution files behind ordinary native text and mutation tools."""

import dataclasses
import fnmatch
import re
from collections.abc import Sequence
from typing import assert_never

from azents_runtime_control.v4a import (
    ApplyPatchLimits,
    PatchOperation,
    V4aPatchError,
    apply_update,
    decode_source_text,
    parse_patch,
)

from azents.core.historical_memory_consolidation import MemoryExecutionPrincipal
from azents.core.session_execution_file import (
    ExecutionFileChange,
    ExecutionFileConflict,
    require_execution_path,
)
from azents.core.session_resource_authority import SessionExecutionOwner
from azents.core.vfs import VfsLocation, parse_vfs_exact_uri
from azents.repos.session_execution_file import SessionExecutionFileRepository
from azents.services.file_storage import GrepResult, TextReadResult
from azents.services.vfs_mutation import (
    VfsAtomicPatchRequest,
    VfsDeleteRequest,
    VfsEditRequest,
    VfsFileObservation,
    VfsMutationError,
    VfsMutationInvocation,
    VfsMutationPreconditions,
    VfsMutationRequest,
    VfsMutationResult,
    VfsWriteRequest,
)
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

_PATCH_LIMITS = ApplyPatchLimits()


@dataclasses.dataclass
class ExecutionFileObservations:
    """Per-target actual read buffers; not a persisted authoring ledger."""

    owner: SessionExecutionOwner
    files: dict[str, str | None] = dataclasses.field(init=False, default_factory=dict)

    def snapshot(self) -> "ExecutionFileObservations":
        result = ExecutionFileObservations(self.owner)
        result.files.update(self.files)
        return result

    def merge_mutations(
        self, before: "ExecutionFileObservations", writer: "ExecutionFileObservations"
    ) -> None:
        for uri, content in writer.files.items():
            if uri not in before.files or content != before.files[uri]:
                self.files[uri] = content


@dataclasses.dataclass(frozen=True)
class _PatchTarget:
    operation: PatchOperation
    location: VfsLocation
    path: str


@dataclasses.dataclass(frozen=True)
class SessionExecutionFileBackend:
    """One current private mount; no Runtime, Saved or original-source bridge."""

    repository: SessionExecutionFileRepository
    observations: ExecutionFileObservations

    @property
    def mount(self) -> str:
        return "execution"

    @property
    def capabilities(self) -> VfsReadBackendCapabilities:
        return VfsReadBackendCapabilities(True, True, True, False)

    def _require(self, principal: MemoryExecutionPrincipal) -> None:
        if principal.owner != self.observations.owner:
            raise VfsReadError("not_found", "Execution files are unavailable.")

    def _path(self, principal: MemoryExecutionPrincipal, location: VfsLocation) -> str:
        self._require(principal)
        if location.mount != self.mount:
            raise VfsReadError("not_found", "Execution files are unavailable.")
        path = location.path.removeprefix("/")
        require_execution_path(path)
        if parse_vfs_exact_uri(location.canonical) != location:
            raise VfsReadError("invalid_path", "Execution path is not canonical.")
        return path

    def _mutation_path(
        self, principal: MemoryExecutionPrincipal, location: VfsLocation
    ) -> str:
        path = self._path(principal, location)
        if path == "README.md" or path.startswith("inputs/"):
            raise VfsMutationError(
                "read_only", "Provided execution inputs are read-only."
            )
        return path

    async def read_text(
        self,
        context: MemoryExecutionPrincipal,
        location: VfsLocation,
        *,
        offset: int,
        limit: int,
        encoding: str,
    ) -> TextReadResult:
        if (
            offset < 0
            or limit < 1
            or encoding.lower().replace("_", "-") not in {"utf-8", "utf8"}
        ):
            raise ValueError("Execution file reads require positive bounds and UTF-8.")
        path = self._path(context, location)
        file = await self.repository.read(context.owner, path)
        self.observations.files[location.canonical] = (
            None if file is None else file.content
        )
        if file is None:
            raise VfsReadError("not_found", "Execution file is unavailable.")
        text = file.content[offset : offset + limit]
        end = offset + len(text)
        return TextReadResult(text, offset, end, end < len(file.content))

    async def glob(
        self,
        context: MemoryExecutionPrincipal,
        location: VfsLocation,
        *,
        exclude_patterns: Sequence[str],
    ) -> VfsGlobResult:
        self._require(context)
        if location.mount != self.mount:
            raise VfsReadError("not_found", "Execution files are unavailable.")
        files = await self.repository.list_files(context.owner)
        return VfsGlobResult(
            tuple(
                f"azents://execution/{file.path}"
                for file in files
                if vfs_pattern_matches(location.path, file.path)
                and not any(
                    fnmatch.fnmatchcase(f"azents://execution/{file.path}", pattern)
                    for pattern in exclude_patterns
                )
            ),
            False,
        )

    async def grep(
        self,
        context: MemoryExecutionPrincipal,
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
        self._require(context)
        if location.mount != self.mount:
            raise VfsReadError("not_found", "Execution files are unavailable.")
        files = await self.repository.list_files(context.owner)
        selected = [
            VfsTextFile(f"azents://execution/{file.path}", file.content)
            for file in files
            if vfs_location_contains(
                location, f"azents://execution/{file.path}", recursive=recursive
            )
            and not any(
                fnmatch.fnmatchcase(f"azents://execution/{file.path}", item)
                for item in exclude_patterns
            )
        ]
        return await bounded_vfs_regex_search(
            files=selected,
            pattern=pattern,
            max_matching_files=max_matching_files,
            max_lines_per_file=max_lines_per_file,
            max_searched_files=max_searched_files,
            max_scanned_bytes=max_scanned_bytes,
        )

    def freeze_mutation(
        self, principal: MemoryExecutionPrincipal, request: VfsMutationRequest
    ) -> VfsMutationPreconditions:
        self._mutation_path(principal, request.location)
        match request:
            case VfsWriteRequest():
                _text_bytes(request.content)
            case VfsEditRequest():
                _text_bytes(request.old_string)
                _text_bytes(request.new_string)
            case VfsDeleteRequest():
                pass
            case _:
                assert_never(request)
        uri = request.location.canonical
        return VfsMutationPreconditions(
            (VfsFileObservation(uri, self.observations.files[uri]),)
            if uri in self.observations.files
            else ()
        )

    async def mutate(
        self,
        principal: MemoryExecutionPrincipal,
        request: VfsMutationRequest,
        preconditions: VfsMutationPreconditions,
        invocation: VfsMutationInvocation,
    ) -> VfsMutationResult:
        path = self._mutation_path(principal, request.location)
        observed = preconditions.files[0] if preconditions.files else None
        try:
            match request:
                case VfsWriteRequest():
                    if request.overwrite and observed is None:
                        raise VfsMutationError(
                            "read_required", "Read the existing file before overwrite."
                        )
                    content = request.content
                    await self.repository.write(
                        principal.owner,
                        path,
                        content,
                        expected_content=(observed.content if observed else None),
                        require_observation=True,
                        overwrite=request.overwrite,
                    )
                case VfsEditRequest():
                    if observed is None or observed.content is None:
                        raise VfsMutationError(
                            "read_required", "Read the file before edit."
                        )
                    count = observed.content.count(request.old_string)
                    if (
                        not request.old_string
                        or count == 0
                        or (not request.replace_all and count != 1)
                    ):
                        raise VfsMutationError(
                            "applicability",
                            "VFS edit requires exact unambiguous context.",
                        )
                    content = observed.content.replace(
                        request.old_string,
                        request.new_string,
                        -1 if request.replace_all else 1,
                    )
                    await self.repository.write(
                        principal.owner,
                        path,
                        content,
                        expected_content=observed.content,
                        require_observation=True,
                        overwrite=True,
                    )
                case VfsDeleteRequest():
                    if observed is None or observed.content is None:
                        raise VfsMutationError(
                            "read_required", "Read the file before delete."
                        )
                    content = None
                    await self.repository.delete(
                        principal.owner, path, expected_content=observed.content
                    )
                case _:
                    assert_never(request)
        except FileExistsError as error:
            raise VfsMutationError("already_exists", str(error)) from None
        except PermissionError as error:
            raise VfsMutationError("unavailable", str(error)) from None
        except ExecutionFileConflict as error:
            raise VfsMutationError("conflict", str(error)) from None
        self.observations.files[request.location.canonical] = content
        return VfsMutationResult(
            (request.location.canonical,),
            0 if content is None else 1,
            0 if content is None else len(content.encode("utf-8")),
        )

    def _patch_targets(
        self, principal: MemoryExecutionPrincipal, request: VfsAtomicPatchRequest
    ) -> tuple[_PatchTarget, ...]:
        self._require(principal)
        if request.base.mount != self.mount:
            raise VfsMutationError(
                "not_found", "Execution patch domain is unavailable."
            )
        try:
            plan = parse_patch(_text_bytes(request.patch), limits=_PATCH_LIMITS)
            return tuple(
                _PatchTarget(
                    operation,
                    location := parse_vfs_exact_uri(
                        f"{request.base.canonical.rstrip('/')}/{operation.path}"
                    ),
                    self._mutation_path(principal, location),
                )
                for operation in plan.operations
            )
        except V4aPatchError as error:
            raise VfsMutationError(error.reason, error.message) from None

    def freeze_patch(
        self, principal: MemoryExecutionPrincipal, request: VfsAtomicPatchRequest
    ) -> VfsMutationPreconditions:
        targets = self._patch_targets(principal, request)
        return VfsMutationPreconditions(
            tuple(
                VfsFileObservation(
                    target.location.canonical,
                    self.observations.files[target.location.canonical],
                )
                for target in targets
                if target.location.canonical in self.observations.files
            )
        )

    async def atomic_patch(
        self,
        principal: MemoryExecutionPrincipal,
        request: VfsAtomicPatchRequest,
        preconditions: VfsMutationPreconditions,
        invocation: VfsMutationInvocation,
    ) -> VfsMutationResult:
        targets = self._patch_targets(principal, request)
        observed = {file.uri: file.content for file in preconditions.files}
        changes: list[ExecutionFileChange] = []
        try:
            for target in targets:
                operation = target.operation
                before = observed.get(target.location.canonical)
                if operation.action == "add":
                    before = None
                    after = "\n".join(operation.add_lines) + "\n"
                else:
                    if before is None:
                        raise VfsMutationError(
                            "read_required", "Read every existing patch target first."
                        )
                    if operation.action == "delete":
                        after = None
                    else:
                        source = decode_source_text(
                            _text_bytes(before),
                            operation=operation,
                            max_bytes=_PATCH_LIMITS.max_file_bytes,
                            remaining=(),
                        )
                        after = apply_update(operation, source).output.decode("utf-8")
                changes.append(ExecutionFileChange(target.path, before, after))
            await self.repository.atomic_patch(principal.owner, tuple(changes))
        except V4aPatchError as error:
            raise VfsMutationError(error.reason, error.message) from None
        except PermissionError as error:
            raise VfsMutationError("unavailable", str(error)) from None
        except ExecutionFileConflict as error:
            raise VfsMutationError("conflict", str(error)) from None
        for target, change in zip(targets, changes, strict=True):
            self.observations.files[target.location.canonical] = change.after
        return VfsMutationResult(
            tuple(target.location.canonical for target in targets),
            sum(change.after is not None for change in changes),
            sum(
                len(change.after.encode("utf-8"))
                for change in changes
                if change.after is not None
            ),
        )


def _text_bytes(text: str) -> bytes:
    if "\x00" in text:
        raise VfsMutationError("invalid_encoding", "VFS text must not contain NUL.")
    try:
        return text.encode("utf-8")
    except UnicodeEncodeError:
        raise VfsMutationError("invalid_encoding", "VFS text must be UTF-8.") from None
