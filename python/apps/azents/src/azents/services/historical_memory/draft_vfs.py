"""Private Runtime-free files bound to exactly one internal consolidation attempt."""

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

from azents.core.historical_memory_consolidation import ConsolidationJobPrincipal
from azents.core.vfs import VfsLocation, parse_vfs_exact_uri
from azents.repos.historical_memory_consolidation.authority import (
    ConsolidationAuthorityError,
)
from azents.repos.historical_memory_consolidation.drafts import (
    ConsolidationDraftConflict,
    ConsolidationDraftRepository,
    DraftFileChange,
    DraftFileObservation,
    DraftMutationResult,
    DraftObservedFile,
    require_draft_path,
)
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

_DRAFT_MOUNT = "memory-draft"
_TEXT_CONTENT_BYTES = 11000  # Reserve framing within the 12k tool-result limit.
_PATCH_LIMITS = ApplyPatchLimits(
    max_operations=16,
    max_path_bytes=512,
    max_file_bytes=262144,
    max_aggregate_bytes=262144,
)


@dataclasses.dataclass(frozen=True)
class _DraftPatchTarget:
    operation: PatchOperation
    location: VfsLocation
    path: str


@dataclasses.dataclass
class ConsolidationVfsObservations:
    """RAM-only observations for one isolated internal execution."""

    principal: ConsolidationJobPrincipal
    evidence_epoch: int = dataclasses.field(init=False, default=0)
    files: dict[str, DraftFileObservation] = dataclasses.field(
        init=False, default_factory=dict
    )
    read_generations: dict[str, int] = dataclasses.field(
        init=False, default_factory=dict
    )
    invalidated_files: set[str] = dataclasses.field(init=False, default_factory=set)

    def require_principal(self, principal: ConsolidationJobPrincipal) -> None:
        if principal != self.principal:
            raise VfsReadError("not_found", "VFS location is unavailable.")

    def begin_file_read(self, uri: str, *, offset: int) -> int:
        """Fence delayed completions and require an explicit restart after conflict."""
        generation = self.read_generations.setdefault(uri, 0)
        if offset == 0:
            generation += 1
            self.read_generations[uri] = generation
            self.files.pop(uri, None)
            self.invalidated_files.discard(uri)
        elif uri in self.invalidated_files:
            raise VfsReadError(
                "conflict", "Draft read changed; restart the read at offset 0."
            )
        return generation

    def record_file(
        self,
        uri: str,
        observation: DraftFileObservation,
        *,
        generation: int,
    ) -> None:
        """Install only one consistent read identity, never a mixed-version suffix."""
        self.evidence_epoch = max(self.evidence_epoch, observation.observation_epoch)
        if generation != self.read_generations[uri]:
            raise VfsReadError(
                "conflict", "Draft read was superseded; restart the read at offset 0."
            )
        previous = self.files.get(uri)
        if uri in self.invalidated_files or (
            previous is not None and previous != observation
        ):
            self.files.pop(uri, None)
            self.invalidated_files.add(uri)
            raise VfsReadError(
                "conflict", "Draft read changed; restart the read at offset 0."
            )
        self.files[uri] = observation

    def record_source_epoch(self, epoch: int) -> None:
        self.evidence_epoch = max(self.evidence_epoch, epoch)

    def snapshot(self) -> "ConsolidationVfsObservations":
        """Freeze sibling mutation reads before parallel execution begins."""
        frozen = ConsolidationVfsObservations(self.principal)
        frozen.evidence_epoch = self.evidence_epoch
        frozen.files = dict(self.files)
        frozen.read_generations = dict(self.read_generations)
        frozen.invalidated_files = set(self.invalidated_files)
        return frozen

    def merge_mutations(
        self,
        before: "ConsolidationVfsObservations",
        after: "ConsolidationVfsObservations",
    ) -> None:
        """Advance changed observations without undoing a later independent read."""
        for uri, observation in after.files.items():
            if before.files.get(uri) == observation:
                continue
            if (
                self.read_generations.get(uri, 0) == before.read_generations.get(uri, 0)
                and self.files.get(uri) == before.files.get(uri)
                and uri not in self.invalidated_files
            ):
                self.files[uri] = observation
                self.read_generations.setdefault(uri, 0)
                self.evidence_epoch = max(
                    self.evidence_epoch, observation.observation_epoch
                )


@dataclasses.dataclass(frozen=True)
class ConsolidationDraftVfsBackend:
    """Native private files isolated by a server-owned job principal."""

    repository: ConsolidationDraftRepository
    observations: ConsolidationVfsObservations

    @property
    def mount(self) -> str:
        return _DRAFT_MOUNT

    @property
    def capabilities(self) -> VfsReadBackendCapabilities:
        return VfsReadBackendCapabilities(
            read_text=True, grep=True, glob=True, transfer_read=False
        )

    def _path(self, principal: ConsolidationJobPrincipal, location: VfsLocation) -> str:
        self.observations.require_principal(principal)
        if location.mount != self.mount:
            raise VfsReadError("not_found", "VFS location is unavailable.")
        path = location.path.removeprefix("/")
        require_draft_path(path)
        if parse_vfs_exact_uri(location.canonical) != location:
            raise VfsReadError("invalid_path", "VFS location is not canonical.")
        return path

    async def read_text(
        self,
        context: ConsolidationJobPrincipal,
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
            raise ValueError("Private draft reads require positive bounds and UTF-8.")
        path = self._path(context, location)
        generation = self.observations.begin_file_read(
            location.canonical, offset=offset
        )
        try:
            observed = await self.repository.observe(context, path=path)
        except ConsolidationAuthorityError:
            raise VfsReadError("not_found", "VFS location is unavailable.") from None
        self.observations.record_file(
            location.canonical,
            observed,
            generation=generation,
        )
        if observed.content is None:
            raise VfsReadError("not_found", "VFS file is absent.")
        text = (
            observed.content[offset : offset + limit]
            .encode("utf-8")[:_TEXT_CONTENT_BYTES]
            .decode("utf-8", errors="ignore")
        )
        end = offset + len(text)
        return TextReadResult(text, offset, end, end < len(observed.content))

    async def glob(
        self,
        context: ConsolidationJobPrincipal,
        location: VfsLocation,
        *,
        exclude_patterns: Sequence[str],
    ) -> VfsGlobResult:
        self.observations.require_principal(context)
        if location.mount != self.mount:
            raise VfsReadError("not_found", "VFS location is unavailable.")
        files = await self._inventory(context)
        uris = tuple(
            f"azents://{self.mount}/{file.path}"
            for file in files
            if vfs_pattern_matches(location.path, file.path)
            and not any(
                fnmatch.fnmatchcase(file.path, pattern) for pattern in exclude_patterns
            )
        )
        return VfsGlobResult(uris, False)

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
        self.observations.require_principal(context)
        if location.mount != self.mount:
            raise VfsReadError("not_found", "VFS location is unavailable.")
        files = await self._inventory(context)
        eligible = tuple(
            VfsTextFile(
                f"azents://{self.mount}/{file.path}", file.observation.content or ""
            )
            for file in files
            if vfs_location_contains(
                location, f"azents://{self.mount}/{file.path}", recursive=recursive
            )
            and not any(
                fnmatch.fnmatchcase(file.path, item) for item in exclude_patterns
            )
        )
        return await bounded_vfs_regex_search(
            files=eligible,
            pattern=pattern,
            max_matching_files=max_matching_files,
            max_lines_per_file=max_lines_per_file,
            max_searched_files=max_searched_files,
            max_scanned_bytes=max_scanned_bytes,
        )

    async def _inventory(
        self, principal: ConsolidationJobPrincipal
    ) -> tuple[DraftObservedFile, ...]:
        try:
            return await self.repository.inventory(principal)
        except ConsolidationAuthorityError:
            raise VfsReadError("not_found", "VFS location is unavailable.") from None

    def freeze_mutation(
        self, principal: ConsolidationJobPrincipal, request: VfsMutationRequest
    ) -> VfsMutationPreconditions:
        self._path(principal, request.location)
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
        observed = self.observations.files.get(request.location.canonical)
        if observed is None:
            return VfsMutationPreconditions(None, self.observations.evidence_epoch, ())
        return VfsMutationPreconditions(
            observed.draft_revision_id,
            observed.observation_epoch,
            (
                VfsFileObservation(
                    request.location.canonical,
                    observed.file_revision_id,
                    observed.content,
                ),
            ),
        )

    def _patch_targets(
        self, principal: ConsolidationJobPrincipal, request: VfsAtomicPatchRequest
    ) -> tuple[_DraftPatchTarget, ...]:
        self.observations.require_principal(principal)
        if request.base.mount != self.mount:
            raise VfsMutationError("not_found", "VFS patch domain is unavailable.")
        try:
            plan = parse_patch(_text_bytes(request.patch), limits=_PATCH_LIMITS)
            targets: list[_DraftPatchTarget] = []
            for operation in plan.operations:
                location = parse_vfs_exact_uri(
                    f"{request.base.canonical.rstrip('/')}/{operation.path}"
                )
                targets.append(
                    _DraftPatchTarget(
                        operation, location, self._path(principal, location)
                    )
                )
        except V4aPatchError as error:
            raise VfsMutationError(error.reason, error.message) from None
        return tuple(targets)

    def freeze_patch(
        self, principal: ConsolidationJobPrincipal, request: VfsAtomicPatchRequest
    ) -> VfsMutationPreconditions:
        """Validate the entire domain before I/O and freeze all known file reads."""
        targets = self._patch_targets(principal, request)
        reads = [
            (
                target.location.canonical,
                self.observations.files[target.location.canonical],
            )
            for target in targets
            if target.location.canonical in self.observations.files
        ]
        revisions = {read.draft_revision_id for _, read in reads}
        epochs = {read.observation_epoch for _, read in reads}
        if len(revisions) > 1 or len(epochs) > 1:
            raise VfsMutationError(
                "conflict", "Read all patch targets at one draft revision."
            )
        return VfsMutationPreconditions(
            group_revision_id=next(iter(revisions)) if revisions else None,
            evidence_epoch=next(iter(epochs))
            if epochs
            else self.observations.evidence_epoch,
            files=tuple(
                VfsFileObservation(uri, read.file_revision_id, read.content)
                for uri, read in reads
            ),
        )

    async def atomic_patch(
        self,
        principal: ConsolidationJobPrincipal,
        request: VfsAtomicPatchRequest,
        preconditions: VfsMutationPreconditions,
        invocation: VfsMutationInvocation,
    ) -> VfsMutationResult:
        """Preflight every hunk, then commit files/manifests/receipt all-or-none."""
        targets = self._patch_targets(principal, request)
        try:
            replay = await self.repository.replay_receipt(
                principal,
                tool_call_id=invocation.tool_call_id,
                request_digest=invocation.request_digest,
            )
            if replay is not None:
                return await self._result(principal, replay)
            observed = {file.uri: file for file in preconditions.files}
            group = preconditions.group_revision_id
            changes: list[DraftFileChange] = []
            for target in targets:
                operation = target.operation
                file = observed.get(target.location.canonical)
                if operation.action == "add":
                    absence = await self.repository.observe(principal, path=target.path)
                    if absence.content is not None:
                        raise VfsMutationError(
                            "already_exists", "VFS patch destination exists."
                        )
                    if absence.observation_epoch != preconditions.evidence_epoch:
                        raise VfsMutationError(
                            "conflict", "VFS source read evidence changed."
                        )
                    if group is not None and group != absence.draft_revision_id:
                        raise VfsMutationError(
                            "conflict", "VFS draft revision changed."
                        )
                    group = absence.draft_revision_id
                    content = "\n".join(operation.add_lines) + "\n"
                    changes.append(DraftFileChange(target.path, None, content))
                    continue
                if file is None or file.content is None:
                    raise VfsMutationError(
                        "read_required", "Read every existing VFS patch target first."
                    )
                if operation.action == "delete":
                    changes.append(DraftFileChange(target.path, file.revision_id, None))
                else:
                    decoded = decode_source_text(
                        _text_bytes(file.content),
                        operation=operation,
                        max_bytes=_PATCH_LIMITS.max_file_bytes,
                        remaining=(),
                    )
                    updated = apply_update(operation, decoded)
                    changes.append(
                        DraftFileChange(
                            target.path,
                            file.revision_id,
                            updated.output.decode("utf-8"),
                        )
                    )
            if group is None:
                raise VfsMutationError(
                    "read_required", "VFS patch read evidence is absent."
                )
            result = await self.repository.mutate(
                principal,
                tool_call_id=invocation.tool_call_id,
                request_digest=invocation.request_digest,
                expected_draft_revision_id=group,
                expected_observation_epoch=preconditions.evidence_epoch,
                changes=changes,
            )
        except V4aPatchError as error:
            raise VfsMutationError(error.reason, error.message) from None
        except ConsolidationAuthorityError:
            raise VfsMutationError(
                "not_found", "VFS location is unavailable."
            ) from None
        except ConsolidationDraftConflict as error:
            raise VfsMutationError("conflict", str(error)) from None
        except VfsMutationError:
            raise
        except ValueError as error:
            raise VfsMutationError("invalid_mutation", str(error)) from None
        return await self._result(principal, result)

    async def mutate(
        self,
        principal: ConsolidationJobPrincipal,
        request: VfsMutationRequest,
        preconditions: VfsMutationPreconditions,
        invocation: VfsMutationInvocation,
    ) -> VfsMutationResult:
        path = self._path(principal, request.location)
        try:
            replay = await self.repository.replay_receipt(
                principal,
                tool_call_id=invocation.tool_call_id,
                request_digest=invocation.request_digest,
            )
            if replay is not None:
                return await self._result(principal, replay)
            observed = preconditions.files[0] if preconditions.files else None
            group_revision = preconditions.group_revision_id
            match request:
                case VfsWriteRequest():
                    if not request.overwrite:
                        current = await self.repository.observe(principal, path=path)
                        if current.content is not None:
                            raise VfsMutationError(
                                "already_exists", "VFS file already exists."
                            )
                        if current.observation_epoch != preconditions.evidence_epoch:
                            raise VfsMutationError(
                                "conflict", "VFS source read evidence changed."
                            )
                        if (
                            group_revision is not None
                            and group_revision != current.draft_revision_id
                        ):
                            raise VfsMutationError(
                                "conflict", "VFS draft revision changed."
                            )
                        group_revision = current.draft_revision_id
                        observed = VfsFileObservation(
                            request.location.canonical, None, None
                        )
                    elif observed is None or observed.content is None:
                        raise VfsMutationError(
                            "read_required",
                            "Read the existing VFS file before overwrite.",
                        )
                    content = request.content
                case VfsEditRequest():
                    if observed is None or observed.content is None:
                        raise VfsMutationError(
                            "read_required", "Read the existing VFS file before edit."
                        )
                    matches = observed.content.count(request.old_string)
                    if (
                        not request.old_string
                        or matches == 0
                        or (not request.replace_all and matches != 1)
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
                case VfsDeleteRequest():
                    if observed is None or observed.content is None:
                        raise VfsMutationError(
                            "read_required", "Read the existing VFS file before delete."
                        )
                    content = None
                case _:
                    assert_never(request)
            if group_revision is None or observed is None:
                raise VfsMutationError(
                    "read_required", "VFS mutation read evidence is absent."
                )
            result = await self.repository.mutate(
                principal,
                tool_call_id=invocation.tool_call_id,
                request_digest=invocation.request_digest,
                expected_draft_revision_id=group_revision,
                expected_observation_epoch=preconditions.evidence_epoch,
                changes=[DraftFileChange(path, observed.revision_id, content)],
            )
        except ConsolidationAuthorityError:
            raise VfsMutationError(
                "not_found", "VFS location is unavailable."
            ) from None
        except ConsolidationDraftConflict as error:
            raise VfsMutationError("conflict", str(error)) from None
        except VfsMutationError:
            raise
        except ValueError as error:
            raise VfsMutationError("invalid_mutation", str(error)) from None
        return await self._result(principal, result)

    async def _result(
        self, principal: ConsolidationJobPrincipal, result: DraftMutationResult
    ) -> VfsMutationResult:
        observations = await self.repository.inventory(principal)
        by_path = {file.path: file.observation for file in observations}
        # Replay metadata cannot install a stale revision as a current observation.
        for path in result.changed_paths:
            observation = by_path.get(path)
            if observation is None:
                observation = await self.repository.observe(principal, path=path)
            if observation.draft_revision_id == result.draft_revision_id:
                uri = f"azents://{self.mount}/{path}"
                self.observations.files[uri] = observation
                self.observations.read_generations.setdefault(uri, 0)
                self.observations.invalidated_files.discard(uri)
                self.observations.evidence_epoch = max(
                    self.observations.evidence_epoch, observation.observation_epoch
                )
        return VfsMutationResult(
            revision_id=result.draft_revision_id,
            uris=tuple(
                f"azents://{self.mount}/{path}" for path in result.changed_paths
            ),
            file_count=result.file_count,
            byte_count=result.byte_count,
        )


def _text_bytes(text: str) -> bytes:
    """Reject text that cannot enter a native UTF-8 database file."""
    if "\x00" in text:
        raise VfsMutationError("invalid_encoding", "VFS text must not contain NUL.")
    try:
        return text.encode("utf-8")
    except UnicodeEncodeError:
        raise VfsMutationError(
            "invalid_encoding", "VFS text must be valid UTF-8."
        ) from None
