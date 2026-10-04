"""Context-free strict V4A parsing and exact UTF-8 text applicability."""

import dataclasses
from collections.abc import Sequence
from pathlib import PurePosixPath
from typing import Literal, NamedTuple, TypeAlias

from azents_runtime_control.apply_patch import (
    MAX_APPLY_PATCH_BASE_PATH_BYTES,
    MAX_APPLY_PATCH_BYTES,
)
from azents_runtime_control.runner import JsonValue

PatchAction: TypeAlias = Literal["add", "update", "delete"]
PatchLineKind: TypeAlias = Literal["context", "add", "remove"]


@dataclasses.dataclass(frozen=True)
class ApplyPatchLimits:
    """Bounded resource limits shared by native patch adapters."""

    max_patch_bytes: int = MAX_APPLY_PATCH_BYTES
    max_operations: int = 100
    max_hunks: int = 500
    max_path_bytes: int = MAX_APPLY_PATCH_BASE_PATH_BYTES
    max_file_bytes: int = 8 * 1024 * 1024
    max_aggregate_bytes: int = 32 * 1024 * 1024


@dataclasses.dataclass(frozen=True)
class PatchLine:
    """One parsed update-hunk line."""

    kind: PatchLineKind
    text: str


@dataclasses.dataclass(frozen=True)
class PatchHunk:
    """One parsed update hunk."""

    anchor: str | None
    lines: tuple[PatchLine, ...]
    end_of_file: bool


@dataclasses.dataclass(frozen=True)
class PatchOperationSummary:
    """One patch operation identity."""

    path: str
    action: PatchAction

    def payload(self) -> dict[str, JsonValue]:
        """Return the existing native protocol metadata shape."""
        return {"path": self.path, "action": self.action}


@dataclasses.dataclass(frozen=True)
class PatchOperation:
    """One immutable patch file operation."""

    path: str
    action: PatchAction
    add_lines: tuple[str, ...] = ()
    hunks: tuple[PatchHunk, ...] = ()

    def summary(self) -> PatchOperationSummary:
        """Return the operation identity used by terminal results."""
        return PatchOperationSummary(path=self.path, action=self.action)


@dataclasses.dataclass(frozen=True)
class PatchPlan:
    """One complete parsed patch."""

    operations: tuple[PatchOperation, ...]
    hunk_count: int


@dataclasses.dataclass(frozen=True)
class SourceText:
    """Decoded current bytes with original newline and final-newline semantics."""

    data: bytes
    lines: tuple[str, ...]
    newline: Literal["\n", "\r\n"]
    final_newline: bool


class PatchUpdate(NamedTuple):
    """Updated file bytes and line-count changes."""

    output: bytes
    added_lines: int
    removed_lines: int


@dataclasses.dataclass(frozen=True)
class _MatchedHunk:
    start: int
    end: int
    replacement: tuple[str, ...]


class V4aPatchError(Exception):
    """Pure parse/applicability failure without filesystem or commit effects."""

    def __init__(
        self,
        *,
        phase: Literal["parse", "preflight"],
        reason: str,
        message: str,
        failed: PatchOperation | None,
        remaining: Sequence[PatchOperation],
    ) -> None:
        super().__init__(message)
        self.phase = phase
        self.reason = reason
        self.message = message
        self.failed = failed
        self.remaining = tuple(remaining)


def parse_patch(patch: bytes, *, limits: ApplyPatchLimits | None = None) -> PatchPlan:
    """Parse one complete strict V4A patch into an immutable plan."""
    effective_limits = limits or ApplyPatchLimits()
    if len(patch) > effective_limits.max_patch_bytes:
        raise _parse_failure(
            "patch_too_large", "Patch exceeds the maximum allowed byte count"
        )
    if b"\x00" in patch:
        raise _parse_failure("invalid_encoding", "Patch contains a NUL byte")
    try:
        text = patch.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise _parse_failure("invalid_encoding", "Patch must be valid UTF-8") from exc
    if "\r" in text:
        raise _parse_failure("invalid_newline", "Patch syntax must use LF newlines")
    lines = text.split("\n")
    if not lines or lines[0] != "*** Begin Patch":
        raise _parse_failure(
            "missing_begin_marker", "Patch must begin with *** Begin Patch"
        )
    operations: list[PatchOperation] = []
    seen_paths: set[str] = set()
    hunk_count = 0
    index = 1
    found_end = False
    while index < len(lines):
        line = lines[index]
        if line == "*** End Patch":
            found_end = True
            index += 1
            break
        if line.startswith("*** Add File: "):
            path = line.removeprefix("*** Add File: ")
            _validate_patch_path(path, limits=effective_limits)
            _record_unique_path(path, seen_paths)
            index += 1
            add_lines: list[str] = []
            while index < len(lines) and not _starts_structural_line(lines[index]):
                add_line = lines[index]
                if not add_line.startswith("+"):
                    raise _parse_failure(
                        "invalid_add_line", f"Add file line must begin with +: {path}"
                    )
                add_lines.append(add_line[1:])
                index += 1
            if not add_lines:
                raise _parse_failure(
                    "empty_add_operation",
                    f"Add file operation must contain at least one line: {path}",
                )
            operations.append(
                PatchOperation(path=path, action="add", add_lines=tuple(add_lines))
            )
        elif line.startswith("*** Update File: "):
            path = line.removeprefix("*** Update File: ")
            _validate_patch_path(path, limits=effective_limits)
            _record_unique_path(path, seen_paths)
            index += 1
            hunks: list[PatchHunk] = []
            while index < len(lines):
                current = lines[index]
                if _starts_operation_or_end(current):
                    break
                if current == "@@":
                    anchor = None
                elif current.startswith("@@ ") and len(current) > 3:
                    anchor = current[3:]
                else:
                    raise _parse_failure(
                        "invalid_hunk_header", f"Update hunk must begin with @@: {path}"
                    )
                index += 1
                patch_lines: list[PatchLine] = []
                end_of_file = False
                while index < len(lines):
                    current = lines[index]
                    if current == "*** End of File":
                        if not patch_lines:
                            raise _parse_failure(
                                "empty_hunk",
                                f"Update hunk must contain patch lines: {path}",
                            )
                        end_of_file = True
                        index += 1
                        break
                    if (
                        current == "@@"
                        or current.startswith("@@ ")
                        or _starts_operation_or_end(current)
                    ):
                        break
                    if current.startswith(" "):
                        patch_lines.append(PatchLine("context", current[1:]))
                    elif current.startswith("+"):
                        patch_lines.append(PatchLine("add", current[1:]))
                    elif current.startswith("-"):
                        patch_lines.append(PatchLine("remove", current[1:]))
                    else:
                        raise _parse_failure(
                            "invalid_hunk_line",
                            f"Update hunk line has an invalid prefix: {path}",
                        )
                    index += 1
                if not patch_lines:
                    raise _parse_failure(
                        "empty_hunk", f"Update hunk must contain patch lines: {path}"
                    )
                hunks.append(
                    PatchHunk(
                        anchor=anchor, lines=tuple(patch_lines), end_of_file=end_of_file
                    )
                )
                hunk_count += 1
                if hunk_count > effective_limits.max_hunks:
                    raise _parse_failure(
                        "too_many_hunks", "Patch exceeds the maximum hunk count"
                    )
                if (
                    end_of_file
                    and index < len(lines)
                    and not _starts_operation_or_end(lines[index])
                ):
                    raise _parse_failure(
                        "content_after_end_of_file",
                        f"Unexpected content after *** End of File: {path}",
                    )
            if not hunks:
                raise _parse_failure(
                    "empty_update_operation",
                    f"Update file operation must contain at least one hunk: {path}",
                )
            operations.append(
                PatchOperation(path=path, action="update", hunks=tuple(hunks))
            )
        elif line.startswith("*** Delete File: "):
            path = line.removeprefix("*** Delete File: ")
            _validate_patch_path(path, limits=effective_limits)
            _record_unique_path(path, seen_paths)
            operations.append(PatchOperation(path=path, action="delete"))
            index += 1
        elif line.startswith("*** Move to:") or line.startswith("*** Move File:"):
            raise _parse_failure(
                "unsupported_move", "Move and rename operations are not supported"
            )
        else:
            raise _parse_failure(
                "invalid_operation_marker",
                f"Unexpected patch line at operation boundary: line {index + 1}",
            )
        if len(operations) > effective_limits.max_operations:
            raise _parse_failure(
                "too_many_operations", "Patch exceeds the maximum file operation count"
            )
    if not found_end:
        raise _parse_failure("missing_end_marker", "Patch must end with *** End Patch")
    if not operations:
        raise _parse_failure(
            "empty_patch", "Patch must contain at least one file operation"
        )
    if any(line.strip() for line in lines[index:]):
        raise _parse_failure(
            "trailing_content",
            "Patch contains non-whitespace content after *** End Patch",
        )
    return PatchPlan(operations=tuple(operations), hunk_count=hunk_count)


def apply_update(operation: PatchOperation, source: SourceText) -> PatchUpdate:
    """Apply all exact, nonambiguous hunks without filesystem or persistence I/O."""
    if not source.lines:
        if len(operation.hunks) != 1:
            raise _update_failure(
                operation,
                "ambiguous_empty_insertion",
                "An empty source file accepts exactly one pure-add hunk",
            )
        hunk = operation.hunks[0]
        if _existing_hunk_lines(hunk):
            raise _update_failure(
                operation,
                "missing_context",
                "Update context does not match the empty source file",
            )
        if hunk.anchor is not None:
            raise _update_failure(
                operation,
                "anchor_not_found",
                "Update anchor does not exist in the empty source file",
            )
        output_lines = tuple(line.text for line in hunk.lines if line.kind == "add")
        return PatchUpdate(
            output=_encode_source_lines(
                output_lines, newline=source.newline, final_newline=source.final_newline
            ),
            added_lines=len(output_lines),
            removed_lines=0,
        )
    matches: list[_MatchedHunk] = []
    cursor = 0
    added_lines = 0
    removed_lines = 0
    for hunk in operation.hunks:
        existing = _existing_hunk_lines(hunk)
        if not existing:
            raise _update_failure(
                operation,
                "pure_add_non_empty_source",
                "A non-empty source file requires exact context or removed lines",
            )
        search_start = cursor
        if hunk.anchor is not None:
            anchor_matches = [
                index
                for index in range(cursor, len(source.lines))
                if source.lines[index] == hunk.anchor
            ]
            if not anchor_matches:
                raise _update_failure(
                    operation,
                    "anchor_not_found",
                    f"Update anchor was not found: {operation.path}",
                )
            if len(anchor_matches) > 1:
                raise _update_failure(
                    operation,
                    "ambiguous_anchor",
                    f"Update anchor is ambiguous: {operation.path}",
                )
            search_start = anchor_matches[0] + 1
        occurrences = _find_occurrences(source.lines, existing, start=search_start)
        if hunk.end_of_file:
            occurrences = [
                start
                for start in occurrences
                if start + len(existing) == len(source.lines)
            ]
        if not occurrences:
            reason = "end_of_file_mismatch" if hunk.end_of_file else "missing_context"
            raise _update_failure(
                operation,
                reason,
                f"Update context was not found exactly: {operation.path}",
            )
        if len(occurrences) > 1:
            raise _update_failure(
                operation,
                "ambiguous_context",
                f"Update context occurs more than once: {operation.path}",
            )
        start = occurrences[0]
        end = start + len(existing)
        replacement = tuple(line.text for line in hunk.lines if line.kind != "remove")
        matches.append(_MatchedHunk(start, end, replacement))
        cursor = end
        added_lines += sum(line.kind == "add" for line in hunk.lines)
        removed_lines += sum(line.kind == "remove" for line in hunk.lines)
    output_lines = list(source.lines)
    for match in reversed(matches):
        output_lines[match.start : match.end] = match.replacement
    return PatchUpdate(
        output=_encode_source_lines(
            tuple(output_lines),
            newline=source.newline,
            final_newline=source.final_newline,
        ),
        added_lines=added_lines,
        removed_lines=removed_lines,
    )


def decode_source_text(
    data: bytes,
    *,
    operation: PatchOperation,
    max_bytes: int,
    remaining: Sequence[PatchOperation],
) -> SourceText:
    """Decode exact current source bytes while retaining native newline semantics."""
    if len(data) > max_bytes:
        raise V4aPatchError(
            phase="preflight",
            reason="file_too_large",
            message=(
                f"Patch source or result exceeds the file byte limit: {operation.path}"
            ),
            failed=operation,
            remaining=remaining,
        )
    if b"\x00" in data:
        raise V4aPatchError(
            phase="preflight",
            reason="binary_file",
            message=f"Patch source is not a supported text file: {operation.path}",
            failed=operation,
            remaining=remaining,
        )
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise V4aPatchError(
            phase="preflight",
            reason="invalid_utf8",
            message=f"Patch source is not valid UTF-8: {operation.path}",
            failed=operation,
            remaining=remaining,
        ) from exc
    newline = _source_newline(text, operation, remaining)
    normalized = text.replace("\r\n", "\n")
    final_newline = normalized.endswith("\n")
    if not normalized:
        lines: tuple[str, ...] = ()
    elif final_newline:
        lines = tuple(normalized[:-1].split("\n"))
    else:
        lines = tuple(normalized.split("\n"))
    return SourceText(data, lines, newline, final_newline)


def _source_newline(
    text: str, operation: PatchOperation, remaining: Sequence[PatchOperation]
) -> Literal["\n", "\r\n"]:
    without_crlf = text.replace("\r\n", "")
    if "\r" in without_crlf or ("\r\n" in text and "\n" in without_crlf):
        raise V4aPatchError(
            phase="preflight",
            reason="mixed_newlines",
            message=f"Patch source mixes or has unsupported newlines: {operation.path}",
            failed=operation,
            remaining=remaining,
        )
    return "\r\n" if "\r\n" in text else "\n"


def _validate_patch_path(path: str, *, limits: ApplyPatchLimits) -> None:
    if not path:
        raise _parse_failure("empty_path", "Patch path must not be empty")
    if len(path.encode()) > limits.max_path_bytes:
        raise _parse_failure("path_too_long", "Patch path exceeds the byte limit")
    if PurePosixPath(path).is_absolute():
        raise _parse_failure("absolute_path", "Patch paths must be relative")
    if any(component in {"", ".", ".."} for component in path.split("/")):
        raise _parse_failure(
            "invalid_path_component",
            "Patch paths must not contain empty, current, or parent components",
        )


def _record_unique_path(path: str, seen_paths: set[str]) -> None:
    if path in seen_paths:
        raise _parse_failure(
            "duplicate_path", f"Each patch path may appear only once: {path}"
        )
    seen_paths.add(path)


def _starts_structural_line(line: str) -> bool:
    return line == "*** End Patch" or line.startswith("*** ")


def _starts_operation_or_end(line: str) -> bool:
    return line == "*** End Patch" or line.startswith(
        ("*** Add File: ", "*** Update File: ", "*** Delete File: ")
    )


def _existing_hunk_lines(hunk: PatchHunk) -> tuple[str, ...]:
    return tuple(line.text for line in hunk.lines if line.kind != "add")


def _find_occurrences(
    source: Sequence[str], needle: Sequence[str], *, start: int
) -> list[int]:
    if not needle:
        return []
    maximum = len(source) - len(needle)
    if maximum < start:
        return []
    return [
        index
        for index in range(start, maximum + 1)
        if tuple(source[index : index + len(needle)]) == tuple(needle)
    ]


def _encode_source_lines(
    lines: Sequence[str], *, newline: Literal["\n", "\r\n"], final_newline: bool
) -> bytes:
    text = newline.join(lines)
    if final_newline:
        text += newline
    return text.encode()


def _parse_failure(reason: str, message: str) -> V4aPatchError:
    return V4aPatchError(
        phase="parse", reason=reason, message=message, failed=None, remaining=()
    )


def _update_failure(
    operation: PatchOperation, reason: str, message: str
) -> V4aPatchError:
    return V4aPatchError(
        phase="preflight",
        reason=reason,
        message=message,
        failed=operation,
        remaining=(),
    )
