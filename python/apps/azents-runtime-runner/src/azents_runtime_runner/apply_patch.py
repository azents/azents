"""Strict V4A patch parsing and filesystem execution."""

from __future__ import annotations

import dataclasses
import hashlib
import os
import stat
import threading
import uuid
from collections.abc import Callable, Sequence
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from typing import Literal, NamedTuple, TypeAlias

from azents_runtime_control import v4a
from azents_runtime_control.runner import JsonValue
from azents_runtime_control.v4a import (
    ApplyPatchLimits,
    PatchAction,
    PatchOperation,
    PatchOperationSummary,
    PatchPlan,
)
from azents_runtime_control.v4a import (
    PatchUpdate as _PatchUpdate,
)
from azents_runtime_control.v4a import (
    SourceText as _SourceText,
)

PatchPhase: TypeAlias = Literal["parse", "preflight", "stage", "revalidate", "commit"]
FaultPoint: TypeAlias = Literal["stage", "commit"]
PATCH_SCHEMA_VERSION = 1


@dataclasses.dataclass(frozen=True)
class PatchChange:
    """One committed patch change."""

    path: str
    action: PatchAction
    added_lines: int
    removed_lines: int
    content_sha256: str | None

    def payload(self) -> dict[str, JsonValue]:
        """Return the Runtime protocol payload shape."""
        payload: dict[str, JsonValue] = {
            "path": self.path,
            "action": self.action,
            "added_lines": self.added_lines,
            "removed_lines": self.removed_lines,
        }
        if self.content_sha256 is not None:
            payload["content_sha256"] = self.content_sha256
        return payload


@dataclasses.dataclass(frozen=True)
class ApplyPatchFailure:
    """Typed terminal patch failure."""

    phase: PatchPhase
    reason: str
    message: str
    applied: tuple[PatchChange, ...]
    failed: PatchOperationSummary | None
    not_attempted: tuple[PatchOperationSummary, ...]
    exact: bool

    def detail_payload(self) -> dict[str, JsonValue]:
        """Return the typed Runtime protocol detail payload."""
        payload: dict[str, JsonValue] = {
            "phase": self.phase,
            "reason": self.reason,
            "applied": [change.payload() for change in self.applied],
            "not_attempted": [item.payload() for item in self.not_attempted],
            "exact": self.exact,
        }
        if self.failed is not None:
            payload["failed"] = self.failed.payload()
        return payload


@dataclasses.dataclass(frozen=True)
class ApplyPatchSuccess:
    """Typed terminal patch success."""

    changes: tuple[PatchChange, ...]

    def payload(self) -> dict[str, JsonValue]:
        """Return the Runtime protocol success payload."""
        return {"changes": [change.payload() for change in self.changes]}


ApplyPatchResult: TypeAlias = ApplyPatchSuccess | ApplyPatchFailure
ApplyPatchFaultInjector: TypeAlias = Callable[[FaultPoint, int, PatchOperation], None]


@dataclasses.dataclass(frozen=True)
class _PathFingerprint:
    resolved_path: Path
    stat_signature: tuple[int, int, int, int, int] | None
    content_sha256: str | None


class _PathObservation(NamedTuple):
    """Observed target path and its filesystem fingerprint."""

    target_path: Path
    fingerprint: _PathFingerprint


@dataclasses.dataclass(frozen=True)
class _PreparedOperation:
    operation: PatchOperation
    target_path: Path
    fingerprint: _PathFingerprint
    source: _SourceText | None
    staged_path: Path | None
    output: bytes | None
    change: PatchChange


class _PatchFailureError(Exception):
    def __init__(
        self,
        *,
        phase: PatchPhase,
        reason: str,
        message: str,
        failed: PatchOperation | None,
        not_attempted: Sequence[PatchOperation],
        applied: Sequence[PatchChange] = (),
        exact: bool = True,
    ) -> None:
        super().__init__(message)
        self.failure = ApplyPatchFailure(
            phase=phase,
            reason=reason,
            message=message,
            applied=tuple(applied),
            failed=failed.summary() if failed is not None else None,
            not_attempted=tuple(item.summary() for item in not_attempted),
            exact=exact,
        )


class _StageFailure(Exception):
    def __init__(self, operation: PatchOperation) -> None:
        super().__init__(operation.path)
        self.operation = operation


def execute_apply_patch(
    *,
    base_path: str,
    patch: bytes,
    declared_patch_bytes: int,
    schema_version: int,
    cancellation: threading.Event,
    deadline_at: datetime | None,
    limits: ApplyPatchLimits | None = None,
    fault_injector: ApplyPatchFaultInjector | None = None,
) -> ApplyPatchResult:
    """Parse, preflight, stage, revalidate, and commit one patch."""
    effective_limits = limits or ApplyPatchLimits()
    try:
        _check_deadline(deadline_at, phase="parse")
        if schema_version != PATCH_SCHEMA_VERSION:
            raise _failure(
                phase="parse",
                reason="unsupported_schema_version",
                message=f"Unsupported patch schema version: {schema_version}",
            )
        if declared_patch_bytes != len(patch):
            raise _failure(
                phase="parse",
                reason="patch_size_mismatch",
                message="Declared patch byte count does not match the body",
            )
        if len(patch) > effective_limits.max_patch_bytes:
            raise _failure(
                phase="parse",
                reason="patch_too_large",
                message="Patch exceeds the maximum allowed byte count",
            )
        plan = parse_patch(patch, limits=effective_limits)
        canonical_base = _canonical_base_path(base_path)
        if cancellation.is_set():
            raise _failure(
                phase="preflight",
                reason="cancelled",
                message="Patch was cancelled before preflight",
                not_attempted=plan.operations,
            )
        prepared = _prepare_operations(
            canonical_base,
            plan,
            limits=effective_limits,
            cancellation=cancellation,
            deadline_at=deadline_at,
        )
        return _stage_and_commit(
            canonical_base,
            plan,
            prepared,
            cancellation=cancellation,
            deadline_at=deadline_at,
            fault_injector=fault_injector,
        )
    except _PatchFailureError as exc:
        return exc.failure


def parse_patch(patch: bytes, *, limits: ApplyPatchLimits | None = None) -> PatchPlan:
    """Adapt the shared strict parser's failures to native operation metadata."""
    try:
        return v4a.parse_patch(patch, limits=limits)
    except v4a.V4aPatchError as exc:
        raise _pure_failure(exc) from exc


def _prepare_operations(
    base: Path,
    plan: PatchPlan,
    *,
    limits: ApplyPatchLimits,
    cancellation: threading.Event,
    deadline_at: datetime | None,
) -> tuple[_PreparedOperation, ...]:
    prepared: list[_PreparedOperation] = []
    aggregate_bytes = 0
    resolved_paths: set[Path] = set()
    for index, operation in enumerate(plan.operations):
        remaining = plan.operations[index + 1 :]
        _check_precommit_stop(
            cancellation,
            deadline_at,
            phase="preflight",
            failed=operation,
            not_attempted=remaining,
        )
        try:
            target_path, fingerprint = _observe_path(base, operation)
        except _PatchFailureError as exc:
            raise _PatchFailureError(
                phase=exc.failure.phase,
                reason=exc.failure.reason,
                message=exc.failure.message,
                failed=operation,
                not_attempted=remaining,
            ) from exc
        if fingerprint.resolved_path in resolved_paths:
            raise _failure(
                phase="preflight",
                reason="duplicate_resolved_path",
                message=(
                    f"Multiple patch paths resolve to the same file: {operation.path}"
                ),
                failed=operation,
                not_attempted=remaining,
            )
        resolved_paths.add(fingerprint.resolved_path)
        source: _SourceText | None = None
        output: bytes | None = None
        if operation.action == "add":
            if fingerprint.stat_signature is not None:
                raise _failure(
                    phase="preflight",
                    reason="destination_exists",
                    message=f"Add destination already exists: {operation.path}",
                    failed=operation,
                    not_attempted=remaining,
                )
            output = ("\n".join(operation.add_lines) + "\n").encode()
            if len(output) > limits.max_file_bytes:
                raise _file_size_failure(operation, remaining)
            aggregate_bytes += len(output)
            change = PatchChange(
                operation.path, "add", len(operation.add_lines), 0, _sha256(output)
            )
        else:
            source = _read_source_text(
                target_path,
                operation=operation,
                max_bytes=limits.max_file_bytes,
                remaining=remaining,
            )
            aggregate_bytes += len(source.data)
            if operation.action == "update":
                output, added_lines, removed_lines = _apply_update(operation, source)
                if len(output) > limits.max_file_bytes:
                    raise _file_size_failure(operation, remaining)
                aggregate_bytes += len(output)
                change = PatchChange(
                    operation.path,
                    "update",
                    added_lines,
                    removed_lines,
                    _sha256(output),
                )
            else:
                change = PatchChange(
                    operation.path, "delete", 0, len(source.lines), None
                )
        if aggregate_bytes > limits.max_aggregate_bytes:
            raise _failure(
                phase="preflight",
                reason="aggregate_bytes_exceeded",
                message="Patch source and output exceed the aggregate byte limit",
                failed=operation,
                not_attempted=remaining,
            )
        prepared.append(
            _PreparedOperation(
                operation, target_path, fingerprint, source, None, output, change
            )
        )
    return tuple(prepared)


def _stage_and_commit(
    base: Path,
    plan: PatchPlan,
    prepared: tuple[_PreparedOperation, ...],
    *,
    cancellation: threading.Event,
    deadline_at: datetime | None,
    fault_injector: ApplyPatchFaultInjector | None,
) -> ApplyPatchResult:
    staged: list[_PreparedOperation] = []
    try:
        for index, item in enumerate(prepared):
            if item.output is None:
                staged.append(item)
                continue
            remaining = plan.operations[index + 1 :]
            _check_precommit_stop(
                cancellation,
                deadline_at,
                phase="stage",
                failed=item.operation,
                not_attempted=remaining,
            )
            try:
                if fault_injector is not None:
                    fault_injector("stage", index, item.operation)
                staged_path = _stage_output(base, item)
            except OSError as exc:
                raise _StageFailure(item.operation) from exc
            staged.append(dataclasses.replace(item, staged_path=staged_path))
        _verify_add_publication_support(staged)
        _revalidate_all(
            base,
            staged,
            cancellation=cancellation,
            deadline_at=deadline_at,
        )
        return _commit(
            base,
            staged,
            deadline_at=deadline_at,
            fault_injector=fault_injector,
        )
    except _StageFailure as exc:
        failed_index = _operation_index(plan.operations, exc.operation)
        return ApplyPatchFailure(
            phase="stage",
            reason="stage_failed",
            message=f"Failed to stage patch output: {exc.operation.path}",
            applied=(),
            failed=exc.operation.summary(),
            not_attempted=tuple(
                item.summary() for item in plan.operations[failed_index + 1 :]
            ),
            exact=True,
        )
    except _PatchFailureError as exc:
        return exc.failure
    finally:
        for item in staged:
            if item.staged_path is not None:
                item.staged_path.unlink(missing_ok=True)


def _revalidate_all(
    base: Path,
    prepared: Sequence[_PreparedOperation],
    *,
    cancellation: threading.Event,
    deadline_at: datetime | None,
) -> None:
    for index, item in enumerate(prepared):
        remaining = tuple(value.operation for value in prepared[index + 1 :])
        _check_precommit_stop(
            cancellation,
            deadline_at,
            phase="revalidate",
            failed=item.operation,
            not_attempted=remaining,
        )
        _revalidate_item(
            base,
            item,
            phase="revalidate",
            not_attempted=remaining,
        )


def _commit(
    base: Path,
    prepared: Sequence[_PreparedOperation],
    *,
    deadline_at: datetime | None,
    fault_injector: ApplyPatchFaultInjector | None,
) -> ApplyPatchResult:
    ordered = [item for item in prepared if item.operation.action != "delete"]
    ordered.extend(item for item in prepared if item.operation.action == "delete")
    applied: list[PatchChange] = []
    for index, item in enumerate(ordered):
        remaining = tuple(value.operation for value in ordered[index + 1 :])
        try:
            _check_deadline(
                deadline_at,
                phase="commit",
                failed=item.operation,
                not_attempted=remaining,
                applied=applied,
            )
            _revalidate_item(
                base,
                item,
                phase="commit",
                not_attempted=remaining,
                applied=applied,
            )
            if fault_injector is not None:
                fault_injector("commit", index, item.operation)
            _commit_item(base, item)
        except _PatchFailureError as exc:
            return exc.failure
        except OSError:
            return ApplyPatchFailure(
                phase="commit",
                reason="filesystem_error",
                message=f"Filesystem commit failed: {item.operation.path}",
                applied=tuple(applied),
                failed=item.operation.summary(),
                not_attempted=tuple(operation.summary() for operation in remaining),
                exact=True,
            )
        applied.append(item.change)
    return ApplyPatchSuccess(changes=tuple(applied))


def _commit_item(base: Path, item: _PreparedOperation) -> None:
    if item.operation.action == "delete":
        item.target_path.unlink()
        return
    if item.staged_path is None:
        raise OSError("Staged patch output is missing")
    if item.operation.action == "add":
        created_directories = _create_parent_directories(base, item.target_path.parent)
        try:
            if (
                _resolved_missing_path(base, item.target_path)
                != item.fingerprint.resolved_path
            ):
                raise OSError("Add destination changed before publication")
            os.link(item.staged_path, item.target_path)
        except OSError:
            _remove_empty_directories(created_directories)
            raise
        item.staged_path.unlink()
        return
    os.replace(item.staged_path, item.target_path)


def _apply_update(
    operation: PatchOperation,
    source: _SourceText,
) -> _PatchUpdate:
    try:
        return v4a.apply_update(operation, source)
    except v4a.V4aPatchError as exc:
        raise _pure_failure(exc) from exc


def _read_source_text(
    path: Path,
    *,
    operation: PatchOperation,
    max_bytes: int,
    remaining: Sequence[PatchOperation],
) -> _SourceText:
    try:
        data = path.read_bytes()
    except FileNotFoundError as exc:
        raise _failure(
            phase="preflight",
            reason="source_missing",
            message=f"Patch source does not exist: {operation.path}",
            failed=operation,
            not_attempted=remaining,
        ) from exc
    except OSError as exc:
        raise _failure(
            phase="preflight",
            reason="source_read_failed",
            message=f"Patch source could not be read: {operation.path}",
            failed=operation,
            not_attempted=remaining,
        ) from exc
    try:
        return v4a.decode_source_text(
            data, operation=operation, max_bytes=max_bytes, remaining=remaining
        )
    except v4a.V4aPatchError as exc:
        raise _pure_failure(exc) from exc


def _observe_path(
    base: Path,
    operation: PatchOperation,
) -> _PathObservation:
    target_path = base.joinpath(*PurePosixPath(operation.path).parts)
    try:
        stat_result = target_path.lstat()
    except FileNotFoundError as exc:
        if operation.action != "add":
            raise _failure(
                phase="preflight",
                reason="source_missing",
                message=f"Patch source does not exist: {operation.path}",
                failed=operation,
            ) from exc
        return _PathObservation(
            target_path=target_path,
            fingerprint=_PathFingerprint(
                _resolved_missing_path(base, target_path),
                None,
                None,
            ),
        )
    except OSError as exc:
        raise _failure(
            phase="preflight",
            reason="path_stat_failed",
            message=f"Patch path could not be inspected: {operation.path}",
            failed=operation,
        ) from exc
    if stat.S_ISLNK(stat_result.st_mode):
        raise _failure(
            phase="preflight",
            reason="final_symlink",
            message=f"Patch final path must not be a symlink: {operation.path}",
            failed=operation,
        )
    if not stat.S_ISREG(stat_result.st_mode):
        raise _failure(
            phase="preflight",
            reason="unsupported_file_type",
            message=f"Patch path must be a regular file: {operation.path}",
            failed=operation,
        )
    resolved_path = target_path.resolve(strict=True)
    _require_below_base(base, resolved_path)
    return _PathObservation(
        target_path=target_path,
        fingerprint=_PathFingerprint(
            resolved_path,
            _stat_signature(stat_result),
            _sha256(target_path.read_bytes()),
        ),
    )


def _revalidate_item(
    base: Path,
    item: _PreparedOperation,
    *,
    phase: PatchPhase,
    not_attempted: Sequence[PatchOperation],
    applied: Sequence[PatchChange] = (),
) -> None:
    try:
        target_path, current = _observe_path(base, item.operation)
    except _PatchFailureError as exc:
        raise _failure(
            phase=phase,
            reason="path_changed",
            message=f"Patch path changed before commit: {item.operation.path}",
            failed=item.operation,
            not_attempted=not_attempted,
            applied=applied,
        ) from exc
    if target_path != item.target_path or current != item.fingerprint:
        raise _failure(
            phase=phase,
            reason="source_changed",
            message=f"Patch source changed before commit: {item.operation.path}",
            failed=item.operation,
            not_attempted=not_attempted,
            applied=applied,
        )


def _canonical_base_path(raw_base_path: str) -> Path:
    path = Path(raw_base_path)
    if not path.is_absolute():
        raise _failure(
            phase="preflight",
            reason="base_path_not_absolute",
            message="Patch base_path must be absolute",
        )
    try:
        canonical = path.resolve(strict=True)
    except OSError as exc:
        raise _failure(
            phase="preflight",
            reason="base_path_missing",
            message="Patch base_path does not exist",
        ) from exc
    if not canonical.is_dir():
        raise _failure(
            phase="preflight",
            reason="base_path_not_directory",
            message="Patch base_path must be a directory",
        )
    return canonical


def _resolved_missing_path(base: Path, target_path: Path) -> Path:
    ancestor = target_path.parent
    while True:
        try:
            ancestor_stat = ancestor.stat()
            break
        except FileNotFoundError:
            if ancestor == base:
                raise
            ancestor = ancestor.parent
    if not stat.S_ISDIR(ancestor_stat.st_mode):
        raise _failure(
            phase="preflight",
            reason="parent_not_directory",
            message="Patch destination parent is not a directory",
        )
    resolved = target_path.resolve(strict=False)
    _require_below_base(base, resolved)
    return resolved


def _require_below_base(base: Path, path: Path) -> None:
    try:
        path.relative_to(base)
    except ValueError as exc:
        raise _failure(
            phase="preflight",
            reason="path_escape",
            message="Patch path resolves outside base_path",
        ) from exc


def _create_parent_directories(
    base: Path,
    parent: Path,
) -> tuple[Path, ...]:
    try:
        relative = parent.relative_to(base)
    except ValueError as exc:
        raise OSError("Patch parent is outside base_path") from exc
    created: list[Path] = []
    current = base
    for component in relative.parts:
        current = current / component
        try:
            current_stat = current.lstat()
        except FileNotFoundError:
            current.mkdir()
            created.append(current)
            continue
        if stat.S_ISLNK(current_stat.st_mode):
            resolved = current.resolve(strict=True)
            try:
                resolved.relative_to(base)
            except ValueError as exc:
                raise OSError("Patch parent symlink escapes base_path") from exc
            if not resolved.is_dir():
                raise OSError("Patch parent symlink is not a directory")
        elif not stat.S_ISDIR(current_stat.st_mode):
            raise OSError("Patch parent is not a directory")
    return tuple(created)


def _remove_empty_directories(paths: Sequence[Path]) -> None:
    for path in reversed(paths):
        try:
            path.rmdir()
        except OSError:
            return


def _stage_output(base: Path, item: _PreparedOperation) -> Path:
    if item.output is None:
        raise OSError("Patch output is missing")
    stage_parent = item.fingerprint.resolved_path.parent
    while not stage_parent.exists():
        if stage_parent == base:
            break
        stage_parent = stage_parent.parent
    try:
        canonical_parent = stage_parent.resolve(strict=True)
    except OSError as exc:
        raise OSError("Patch staging parent is unavailable") from exc
    _require_below_base(base, canonical_parent)
    if not canonical_parent.is_dir():
        raise OSError("Patch staging parent is not a directory")
    staged_path = _new_staged_path(canonical_parent)
    try:
        _write_staged_file(staged_path, item.output)
        if item.source is not None and item.fingerprint.stat_signature is not None:
            os.chmod(
                staged_path,
                stat.S_IMODE(item.fingerprint.stat_signature[2]),
            )
    except OSError:
        staged_path.unlink(missing_ok=True)
        raise
    return staged_path


def _verify_add_publication_support(
    prepared: Sequence[_PreparedOperation],
) -> None:
    add_items = [item for item in prepared if item.operation.action == "add"]
    for item in add_items:
        if item.staged_path is None:
            raise OSError("Staged Add output is missing")
        destination = _new_staged_path(item.staged_path.parent)
        try:
            os.link(item.staged_path, destination)
        except OSError as exc:
            raise _failure(
                phase="stage",
                reason="atomic_add_unsupported",
                message="Runtime filesystem does not support atomic no-overwrite Add",
                not_attempted=tuple(value.operation for value in prepared),
            ) from exc
        finally:
            destination.unlink(missing_ok=True)


def _new_staged_path(parent: Path) -> Path:
    for _ in range(10):
        path = parent / f".azents-apply-patch-{uuid.uuid4().hex}"
        if not path.exists():
            return path
    raise OSError("Unable to allocate a unique patch staging path")


def _write_staged_file(path: Path, data: bytes) -> None:
    with path.open("xb") as file:
        file.write(data)
        file.flush()
        os.fsync(file.fileno())


def _check_precommit_stop(
    cancellation: threading.Event,
    deadline_at: datetime | None,
    *,
    phase: PatchPhase,
    failed: PatchOperation | None,
    not_attempted: Sequence[PatchOperation],
) -> None:
    if cancellation.is_set():
        raise _failure(
            phase=phase,
            reason="cancelled",
            message="Patch was cancelled before commit",
            failed=failed,
            not_attempted=not_attempted,
        )
    _check_deadline(
        deadline_at,
        phase=phase,
        failed=failed,
        not_attempted=not_attempted,
    )


def _check_deadline(
    deadline_at: datetime | None,
    *,
    phase: PatchPhase,
    failed: PatchOperation | None = None,
    not_attempted: Sequence[PatchOperation] = (),
    applied: Sequence[PatchChange] = (),
) -> None:
    if deadline_at is not None and datetime.now(UTC) >= deadline_at:
        raise _failure(
            phase=phase,
            reason="deadline_exceeded",
            message="Patch operation deadline expired",
            failed=failed,
            not_attempted=not_attempted,
            applied=applied,
        )


def _stat_signature(
    value: os.stat_result,
) -> tuple[int, int, int, int, int]:
    return (
        value.st_dev,
        value.st_ino,
        value.st_mode,
        value.st_size,
        value.st_mtime_ns,
    )


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _failure(
    *,
    phase: PatchPhase,
    reason: str,
    message: str,
    failed: PatchOperation | None = None,
    not_attempted: Sequence[PatchOperation] = (),
    applied: Sequence[PatchChange] = (),
    exact: bool = True,
) -> _PatchFailureError:
    return _PatchFailureError(
        phase=phase,
        reason=reason,
        message=message,
        failed=failed,
        not_attempted=not_attempted,
        applied=applied,
        exact=exact,
    )


def _pure_failure(error: v4a.V4aPatchError) -> _PatchFailureError:
    """Keep native result shape while shared primitives remain I/O-free."""
    return _failure(
        phase=error.phase,
        reason=error.reason,
        message=error.message,
        failed=error.failed,
        not_attempted=error.remaining,
    )


def _file_size_failure(
    operation: PatchOperation,
    remaining: Sequence[PatchOperation],
) -> _PatchFailureError:
    return _failure(
        phase="preflight",
        reason="file_too_large",
        message=(
            f"Patch source or result exceeds the file byte limit: {operation.path}"
        ),
        failed=operation,
        not_attempted=remaining,
    )


def _operation_index(
    operations: Sequence[PatchOperation],
    target: PatchOperation,
) -> int:
    for index, operation in enumerate(operations):
        if operation is target:
            return index
    raise AssertionError("Patch operation is not part of the plan")


__all__ = [
    "ApplyPatchFailure",
    "ApplyPatchFaultInjector",
    "ApplyPatchResult",
    "ApplyPatchSuccess",
    "PATCH_SCHEMA_VERSION",
    "PatchChange",
    "execute_apply_patch",
    "parse_patch",
]
