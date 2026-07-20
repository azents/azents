"""Strict V4A patch parser and executor tests."""

import asyncio
import hashlib
import os
import threading
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from azents_runtime_control.runner import (
    JsonValue,
    RunnerBodyChunk,
    RunnerOperationEnvelope,
    RunnerOperationEvent,
    RuntimeRunnerEventType,
)

from azents_runtime_runner.apply_patch import (
    PATCH_SCHEMA_VERSION,
    ApplyPatchFailure,
    ApplyPatchFaultInjector,
    ApplyPatchLimits,
    ApplyPatchResult,
    ApplyPatchSuccess,
    PatchOperation,
    execute_apply_patch,
)
from azents_runtime_runner.operations import RunnerOperations
from azents_runtime_runner.workspace import Workspace


class _FakeClient:
    def __init__(self) -> None:
        self.events: list[RunnerOperationEvent] = []

    async def append_runner_event(self, event: RunnerOperationEvent) -> None:
        self.events.append(event)


def _execute(
    base_path: Path,
    patch: str | bytes,
    *,
    cancellation: threading.Event | None = None,
    deadline_at: datetime | None = None,
    limits: ApplyPatchLimits | None = None,
    fault_injector: ApplyPatchFaultInjector | None = None,
    declared_patch_bytes: int | None = None,
    schema_version: int = PATCH_SCHEMA_VERSION,
) -> ApplyPatchResult:
    patch_bytes = patch.encode() if isinstance(patch, str) else patch
    return execute_apply_patch(
        base_path=str(base_path),
        patch=patch_bytes,
        declared_patch_bytes=(
            len(patch_bytes) if declared_patch_bytes is None else declared_patch_bytes
        ),
        schema_version=schema_version,
        cancellation=cancellation or threading.Event(),
        deadline_at=deadline_at,
        limits=limits,
        fault_injector=fault_injector,
    )


def _failure(result: ApplyPatchResult) -> ApplyPatchFailure:
    assert isinstance(result, ApplyPatchFailure)
    return result


def _success(result: ApplyPatchResult) -> ApplyPatchSuccess:
    assert isinstance(result, ApplyPatchSuccess)
    return result


def _stage_directories(base_path: Path) -> list[Path]:
    return list(base_path.glob(".azents-apply-patch-*"))


def test_multi_file_patch_commits_content_before_deletes(tmp_path: Path) -> None:
    (tmp_path / "service.py").write_text("before\nkeep\n")
    (tmp_path / "legacy.py").write_text("old\n")
    patch = """*** Begin Patch
*** Delete File: legacy.py
*** Update File: service.py
@@
-before
+after
 keep
*** Add File: errors.py
+class PatchError(Exception):
+    pass
*** End Patch"""

    result = _success(_execute(tmp_path, patch))

    assert (tmp_path / "service.py").read_text() == "after\nkeep\n"
    assert (tmp_path / "errors.py").read_text() == (
        "class PatchError(Exception):\n    pass\n"
    )
    assert not (tmp_path / "legacy.py").exists()
    assert [(change.action, change.path) for change in result.changes] == [
        ("update", "service.py"),
        ("add", "errors.py"),
        ("delete", "legacy.py"),
    ]
    assert (
        result.changes[0].content_sha256 == hashlib.sha256(b"after\nkeep\n").hexdigest()
    )
    assert result.changes[0].added_lines == 1
    assert result.changes[0].removed_lines == 1
    assert result.changes[1].added_lines == 2
    assert result.changes[2].removed_lines == 1
    assert _stage_directories(tmp_path) == []


@pytest.mark.parametrize(
    ("patch", "reason"),
    [
        (b"", "missing_begin_marker"),
        (b"*** Begin Patch", "missing_end_marker"),
        (b"*** Begin Patch\n*** End Patch", "empty_patch"),
        (
            b"*** Begin Patch\n*** Delete File: a.txt\n*** End Patch\ntrailing",
            "trailing_content",
        ),
        (
            b" *** Begin Patch\n*** Delete File: a.txt\n*** End Patch",
            "missing_begin_marker",
        ),
        (
            b"*** Begin Patch\n*** Delete File: /a.txt\n*** End Patch",
            "absolute_path",
        ),
        (
            b"*** Begin Patch\n*** Delete File: a/../b.txt\n*** End Patch",
            "invalid_path_component",
        ),
        (
            b"*** Begin Patch\n*** Delete File: a.txt\n"
            b"*** Delete File: a.txt\n*** End Patch",
            "duplicate_path",
        ),
        (
            b"*** Begin Patch\n*** Move File: a.txt\n*** End Patch",
            "unsupported_move",
        ),
        (
            b"*** Begin Patch\n*** Add File: a.txt\n*** End Patch",
            "empty_add_operation",
        ),
        (
            b"*** Begin Patch\n*** Add File: a.txt\nplain\n*** End Patch",
            "invalid_add_line",
        ),
        (
            b"*** Begin Patch\n*** Update File: a.txt\n*** End Patch",
            "empty_update_operation",
        ),
        (
            b"*** Begin Patch\n*** Update File: a.txt\nnot-a-hunk\n*** End Patch",
            "invalid_hunk_header",
        ),
        (
            b"*** Begin Patch\n*** Update File: a.txt\n@@\n*** End Patch",
            "empty_hunk",
        ),
        (
            b"*** Begin Patch\n*** Update File: a.txt\n@@\ninvalid\n*** End Patch",
            "invalid_hunk_line",
        ),
        (
            b"*** Begin Patch\n*** Update File: a.txt\n@@\n old\n"
            b"*** End of File\n@@\n old\n*** End Patch",
            "content_after_end_of_file",
        ),
        (
            b"*** Begin Patch\r\n*** Delete File: a.txt\r\n*** End Patch",
            "invalid_newline",
        ),
        (
            b"*** Begin Patch\n*** Add File: a.txt\n+\x00\n*** End Patch",
            "invalid_encoding",
        ),
        (b"\xff", "invalid_encoding"),
    ],
)
def test_malformed_patch_boundaries_fail_without_mutation(
    tmp_path: Path,
    patch: bytes,
    reason: str,
) -> None:
    original = tmp_path / "a.txt"
    original.write_text("original\n")

    failure = _failure(_execute(tmp_path, patch))

    assert failure.phase == "parse"
    assert failure.reason == reason
    assert failure.applied == ()
    assert original.read_text() == "original\n"
    assert _stage_directories(tmp_path) == []


def test_parser_limits_fail_without_mutation(tmp_path: Path) -> None:
    (tmp_path / "a.txt").write_text("a\n")
    patch = """*** Begin Patch
*** Update File: a.txt
@@
-a
+b
*** End Patch"""

    too_large = _failure(
        _execute(
            tmp_path,
            patch,
            limits=ApplyPatchLimits(max_patch_bytes=len(patch.encode()) - 1),
        )
    )
    wrong_size = _failure(
        _execute(tmp_path, patch, declared_patch_bytes=len(patch.encode()) + 1)
    )
    wrong_version = _failure(_execute(tmp_path, patch, schema_version=99))

    assert too_large.reason == "patch_too_large"
    assert wrong_size.reason == "patch_size_mismatch"
    assert wrong_version.reason == "unsupported_schema_version"
    assert (tmp_path / "a.txt").read_text() == "a\n"


def test_operation_hunk_and_path_limits_are_enforced(tmp_path: Path) -> None:
    operation_patch = """*** Begin Patch
*** Add File: a.txt
+a
*** Add File: b.txt
+b
*** End Patch"""
    hunk_patch = """*** Begin Patch
*** Update File: source.txt
@@
-a
+b
@@
-c
+d
*** End Patch"""
    path_patch = """*** Begin Patch
*** Add File: long-name.txt
+a
*** End Patch"""
    (tmp_path / "source.txt").write_text("a\nc\n")

    operation_failure = _failure(
        _execute(
            tmp_path,
            operation_patch,
            limits=ApplyPatchLimits(max_operations=1),
        )
    )
    hunk_failure = _failure(
        _execute(
            tmp_path,
            hunk_patch,
            limits=ApplyPatchLimits(max_hunks=1),
        )
    )
    path_failure = _failure(
        _execute(
            tmp_path,
            path_patch,
            limits=ApplyPatchLimits(max_path_bytes=4),
        )
    )

    assert operation_failure.reason == "too_many_operations"
    assert hunk_failure.reason == "too_many_hunks"
    assert path_failure.reason == "path_too_long"
    assert not (tmp_path / "a.txt").exists()
    assert not (tmp_path / "b.txt").exists()
    assert (tmp_path / "source.txt").read_text() == "a\nc\n"


def test_multiple_ordered_hunks_use_the_original_snapshot(tmp_path: Path) -> None:
    source = tmp_path / "source.txt"
    source.write_text("first\nkeep\nsecond\nlast\n")
    patch = """*** Begin Patch
*** Update File: source.txt
@@
-first
+FIRST
 keep
@@
-second
+SECOND
 last
*** End Patch"""

    result = _success(_execute(tmp_path, patch))

    assert source.read_text() == "FIRST\nkeep\nSECOND\nlast\n"
    assert result.changes[0].added_lines == 2
    assert result.changes[0].removed_lines == 2


@pytest.mark.parametrize(
    ("source_text", "patch_body", "reason"),
    [
        (
            "same\nvalue\nsame\nvalue\n",
            "@@\n same\n-value\n+changed",
            "ambiguous_context",
        ),
        ("actual\n", "@@\n-missing\n+changed", "missing_context"),
        ("anchor\nanchor\nvalue\n", "@@ anchor\n-value\n+changed", "ambiguous_anchor"),
        ("value\n", "@@ missing\n-value\n+changed", "anchor_not_found"),
        (
            "value\nend\n",
            "@@\n-value\n+changed\n*** End of File",
            "end_of_file_mismatch",
        ),
        ("value\n", "@@\n+added", "pure_add_non_empty_source"),
    ],
)
def test_inapplicable_updates_do_not_mutate_any_operation(
    tmp_path: Path,
    source_text: str,
    patch_body: str,
    reason: str,
) -> None:
    source = tmp_path / "source.txt"
    source.write_text(source_text)
    patch = f"""*** Begin Patch
*** Add File: earlier.txt
+must not be created
*** Update File: source.txt
{patch_body}
*** End Patch"""

    failure = _failure(_execute(tmp_path, patch))

    assert failure.phase == "preflight"
    assert failure.reason == reason
    assert failure.applied == ()
    assert failure.failed is not None
    assert failure.failed.path == "source.txt"
    assert source.read_text() == source_text
    assert not (tmp_path / "earlier.txt").exists()
    assert _stage_directories(tmp_path) == []


def test_anchor_and_end_of_file_select_exact_positions(tmp_path: Path) -> None:
    source = tmp_path / "source.txt"
    source.write_text("section one\nvalue\nsection two\nvalue\n")
    patch = """*** Begin Patch
*** Update File: source.txt
@@ section two
-value
+changed
*** End of File
*** End Patch"""

    _success(_execute(tmp_path, patch))

    assert source.read_text() == "section one\nvalue\nsection two\nchanged\n"


@pytest.mark.parametrize(
    ("initial", "expected"),
    [
        (b"one\r\ntwo", b"one\r\nthree"),
        (b"one\r\ntwo\r\n", b"one\r\nthree\r\n"),
        (b"one\ntwo", b"one\nthree"),
        (b"one\ntwo\n", b"one\nthree\n"),
    ],
)
def test_update_preserves_newline_style_and_final_newline(
    tmp_path: Path,
    initial: bytes,
    expected: bytes,
) -> None:
    source = tmp_path / "source.txt"
    source.write_bytes(initial)
    patch = """*** Begin Patch
*** Update File: source.txt
@@
-two
+three
*** End Patch"""

    _success(_execute(tmp_path, patch))

    assert source.read_bytes() == expected


def test_empty_source_allows_one_pure_add_hunk_without_adding_final_newline(
    tmp_path: Path,
) -> None:
    source = tmp_path / "source.txt"
    source.write_bytes(b"")
    patch = """*** Begin Patch
*** Update File: source.txt
@@
+first
+second
*** End Patch"""

    _success(_execute(tmp_path, patch))

    assert source.read_bytes() == b"first\nsecond"


@pytest.mark.parametrize(
    ("data", "reason"),
    [
        (b"left\r\nright\n", "mixed_newlines"),
        (b"binary\x00data", "binary_file"),
        (b"\xff\xfe", "invalid_utf8"),
    ],
)
def test_unsupported_source_text_is_rejected(
    tmp_path: Path,
    data: bytes,
    reason: str,
) -> None:
    source = tmp_path / "source.txt"
    source.write_bytes(data)
    patch = """*** Begin Patch
*** Update File: source.txt
@@
-left
+changed
*** End Patch"""

    failure = _failure(_execute(tmp_path, patch))

    assert failure.reason == reason
    assert source.read_bytes() == data


def test_add_existing_and_missing_source_preconditions_are_destructive_safe(
    tmp_path: Path,
) -> None:
    existing = tmp_path / "existing.txt"
    existing.write_text("original\n")
    add_patch = """*** Begin Patch
*** Add File: existing.txt
+replacement
*** End Patch"""
    update_patch = """*** Begin Patch
*** Update File: missing.txt
@@
-old
+new
*** End Patch"""

    add_failure = _failure(_execute(tmp_path, add_patch))
    update_failure = _failure(_execute(tmp_path, update_patch))

    assert add_failure.reason == "destination_exists"
    assert update_failure.reason == "source_missing"
    assert existing.read_text() == "original\n"
    assert not (tmp_path / "missing.txt").exists()


def test_path_escape_and_final_symlink_are_rejected(tmp_path: Path) -> None:
    outside = tmp_path.parent / f"{tmp_path.name}-outside"
    outside.mkdir()
    outside_source = outside / "source.txt"
    outside_source.write_text("outside\n")
    (tmp_path / "escape").symlink_to(outside, target_is_directory=True)
    (tmp_path / "link.txt").symlink_to(outside_source)
    escape_patch = """*** Begin Patch
*** Add File: escape/created.txt
+escaped
*** End Patch"""
    symlink_patch = """*** Begin Patch
*** Delete File: link.txt
*** End Patch"""

    escape_failure = _failure(_execute(tmp_path, escape_patch))
    symlink_failure = _failure(_execute(tmp_path, symlink_patch))

    assert escape_failure.reason == "path_escape"
    assert symlink_failure.reason == "final_symlink"
    assert not (outside / "created.txt").exists()
    assert (tmp_path / "link.txt").is_symlink()
    assert outside_source.read_text() == "outside\n"


def test_duplicate_resolved_paths_through_internal_symlink_are_rejected(
    tmp_path: Path,
) -> None:
    real = tmp_path / "real"
    real.mkdir()
    source = real / "source.txt"
    source.write_text("old\n")
    (tmp_path / "alias").symlink_to(real, target_is_directory=True)
    patch = """*** Begin Patch
*** Update File: real/source.txt
@@
-old
+first
*** Update File: alias/source.txt
@@
-old
+second
*** End Patch"""

    failure = _failure(_execute(tmp_path, patch))

    assert failure.reason == "duplicate_resolved_path"
    assert source.read_text() == "old\n"


def test_directory_source_is_rejected(tmp_path: Path) -> None:
    (tmp_path / "directory").mkdir()
    patch = """*** Begin Patch
*** Delete File: directory
*** End Patch"""

    failure = _failure(_execute(tmp_path, patch))

    assert failure.reason == "unsupported_file_type"
    assert (tmp_path / "directory").is_dir()


def test_file_and_aggregate_byte_limits_leave_sources_unchanged(tmp_path: Path) -> None:
    source = tmp_path / "source.txt"
    source.write_text("old\n")
    patch = """*** Begin Patch
*** Update File: source.txt
@@
-old
+replacement
*** End Patch"""

    file_failure = _failure(
        _execute(
            tmp_path,
            patch,
            limits=ApplyPatchLimits(max_file_bytes=5),
        )
    )
    aggregate_failure = _failure(
        _execute(
            tmp_path,
            patch,
            limits=ApplyPatchLimits(max_aggregate_bytes=10),
        )
    )

    assert file_failure.reason == "file_too_large"
    assert aggregate_failure.reason == "aggregate_bytes_exceeded"
    assert source.read_text() == "old\n"


def test_preflight_cancellation_and_deadline_do_not_mutate(tmp_path: Path) -> None:
    source = tmp_path / "source.txt"
    source.write_text("old\n")
    patch = """*** Begin Patch
*** Update File: source.txt
@@
-old
+new
*** End Patch"""
    cancellation = threading.Event()
    cancellation.set()

    cancelled = _failure(_execute(tmp_path, patch, cancellation=cancellation))
    expired = _failure(
        _execute(
            tmp_path,
            patch,
            deadline_at=datetime.now(UTC) - timedelta(seconds=1),
        )
    )

    assert cancelled.phase == "preflight"
    assert cancelled.reason == "cancelled"
    assert expired.phase == "parse"
    assert expired.reason == "deadline_exceeded"
    assert source.read_text() == "old\n"


def test_external_change_before_revalidation_prevents_patch_mutation(
    tmp_path: Path,
) -> None:
    source = tmp_path / "source.txt"
    source.write_text("old\n")
    patch = """*** Begin Patch
*** Update File: source.txt
@@
-old
+patched
*** End Patch"""

    def change_source(
        point: str,
        index: int,
        operation: PatchOperation,
    ) -> None:
        if point == "stage" and index == 0:
            assert operation.path == "source.txt"
            source.write_text("external\n")

    failure = _failure(_execute(tmp_path, patch, fault_injector=change_source))

    assert failure.phase == "revalidate"
    assert failure.reason == "source_changed"
    assert failure.applied == ()
    assert source.read_text() == "external\n"
    assert _stage_directories(tmp_path) == []


def test_stage_failure_cleans_outputs_and_mutates_nothing(tmp_path: Path) -> None:
    first = tmp_path / "first.txt"
    second = tmp_path / "second.txt"
    first.write_text("one\n")
    second.write_text("two\n")
    patch = """*** Begin Patch
*** Update File: first.txt
@@
-one
+ONE
*** Update File: second.txt
@@
-two
+TWO
*** End Patch"""

    def fail_stage(point: str, index: int, operation: PatchOperation) -> None:
        if point == "stage" and index == 1:
            assert operation.path == "second.txt"
            raise OSError("injected stage failure")

    failure = _failure(_execute(tmp_path, patch, fault_injector=fail_stage))

    assert failure.phase == "stage"
    assert failure.reason == "stage_failed"
    assert failure.applied == ()
    assert failure.failed is not None
    assert failure.failed.path == "second.txt"
    assert first.read_text() == "one\n"
    assert second.read_text() == "two\n"
    assert _stage_directories(tmp_path) == []


def test_later_commit_failure_preserves_and_reports_committed_prefix(
    tmp_path: Path,
) -> None:
    source = tmp_path / "source.txt"
    legacy = tmp_path / "legacy.txt"
    source.write_text("old\n")
    legacy.write_text("legacy\n")
    patch = """*** Begin Patch
*** Delete File: legacy.txt
*** Update File: source.txt
@@
-old
+new
*** Add File: added.txt
+added
*** End Patch"""

    def fail_second_commit(
        point: str,
        index: int,
        operation: PatchOperation,
    ) -> None:
        if point == "commit" and index == 1:
            assert operation.path == "added.txt"
            raise OSError("injected commit failure")

    failure = _failure(_execute(tmp_path, patch, fault_injector=fail_second_commit))

    assert failure.phase == "commit"
    assert failure.reason == "filesystem_error"
    assert [(change.action, change.path) for change in failure.applied] == [
        ("update", "source.txt")
    ]
    assert failure.failed is not None
    assert (failure.failed.action, failure.failed.path) == ("add", "added.txt")
    assert [(item.action, item.path) for item in failure.not_attempted] == [
        ("delete", "legacy.txt")
    ]
    assert failure.exact is True
    assert source.read_text() == "new\n"
    assert not (tmp_path / "added.txt").exists()
    assert legacy.read_text() == "legacy\n"
    assert _stage_directories(tmp_path) == []


def test_add_creates_missing_parents_and_uses_no_overwrite_publication(
    tmp_path: Path,
) -> None:
    patch = """*** Begin Patch
*** Add File: nested/deeper/created.txt
+created
*** End Patch"""

    result = _success(_execute(tmp_path, patch))

    assert (tmp_path / "nested" / "deeper" / "created.txt").read_text() == ("created\n")
    assert result.changes[0].action == "add"


def test_update_stages_on_the_target_filesystem(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    target_parent = tmp_path / "nested"
    target_parent.mkdir()
    source = target_parent / "source.txt"
    source.write_text("old\n")
    patch = """*** Begin Patch
*** Update File: nested/source.txt
@@
-old
+new
*** End Patch"""
    staged_parents: list[Path] = []

    def capture_staged_parent(path: Path, data: bytes) -> None:
        staged_parents.append(path.parent)
        with path.open("xb") as file:
            file.write(data)
            file.flush()
            os.fsync(file.fileno())

    monkeypatch.setattr(
        "azents_runtime_runner.apply_patch._write_staged_file",
        capture_staged_parent,
    )

    _success(_execute(tmp_path, patch))

    assert staged_parents == [target_parent.resolve()]
    assert source.read_text() == "new\n"


@pytest.mark.asyncio
async def test_runner_serializes_patch_operations_per_runtime(tmp_path: Path) -> None:
    first = tmp_path / "first.txt"
    second = tmp_path / "second.txt"
    first.write_text("one\n")
    second.write_text("two\n")
    first_patch = b"""*** Begin Patch
*** Update File: first.txt
@@
-one
+ONE
*** End Patch"""
    second_patch = b"""*** Begin Patch
*** Update File: second.txt
@@
-two
+TWO
*** End Patch"""
    first_entered = threading.Event()
    second_entered = threading.Event()
    release = threading.Event()

    def block_first_patch(point: str, index: int, operation: PatchOperation) -> None:
        if point != "stage" or index != 0:
            return
        if operation.path == "first.txt":
            first_entered.set()
            release.wait(timeout=2)
        elif operation.path == "second.txt":
            second_entered.set()

    client = _FakeClient()
    operations = RunnerOperations(
        client=client,
        workspace=Workspace(str(tmp_path)),
        apply_patch_fault_injector=block_first_patch,
    )
    first_task = asyncio.create_task(
        operations.handle(_operation(tmp_path, first_patch))
    )
    assert await asyncio.to_thread(first_entered.wait, 1)

    second_task = asyncio.create_task(
        operations.handle(_operation(tmp_path, second_patch))
    )
    await asyncio.sleep(0.05)
    assert not second_entered.is_set()

    release.set()
    await asyncio.wait_for(asyncio.gather(first_task, second_task), timeout=2)

    assert second_entered.is_set()
    assert first.read_text() == "ONE\n"
    assert second.read_text() == "TWO\n"
    assert (
        sum(
            event.event_type == RuntimeRunnerEventType.FINAL_SUCCESS
            for event in client.events
        )
        == 2
    )
    await operations.close()


@pytest.mark.asyncio
async def test_runner_operation_emits_typed_success_and_failure(tmp_path: Path) -> None:
    source = tmp_path / "source.txt"
    source.write_text("old\n")
    success_patch = b"""*** Begin Patch
*** Update File: source.txt
@@
-old
+new
*** End Patch"""
    client = _FakeClient()
    operations = RunnerOperations(client=client, workspace=Workspace(str(tmp_path)))

    await operations.handle(_operation(tmp_path, success_patch))

    assert [event.event_type for event in client.events] == [
        RuntimeRunnerEventType.ACCEPTED,
        RuntimeRunnerEventType.FINAL_SUCCESS,
    ]
    success_payload = client.events[-1].payload
    assert success_payload["changes"] == [
        {
            "path": "source.txt",
            "action": "update",
            "added_lines": 1,
            "removed_lines": 1,
            "content_sha256": hashlib.sha256(b"new\n").hexdigest(),
        }
    ]

    client.events.clear()
    await operations.handle(_operation(tmp_path, success_patch))

    assert client.events[-1].event_type == RuntimeRunnerEventType.FINAL_ERROR
    failure_payload = client.events[-1].payload
    assert failure_payload["error_code"] == "FILE_APPLY_PATCH_FAILED"
    detail = failure_payload["file_apply_patch"]
    assert isinstance(detail, dict)
    assert detail["phase"] == "preflight"
    assert detail["reason"] == "missing_context"
    assert detail["applied"] == []
    assert "*** Begin Patch" not in str(failure_payload)
    await operations.close()


@pytest.mark.asyncio
async def test_runner_cancellation_before_commit_settles_to_no_change_failure(
    tmp_path: Path,
) -> None:
    source = tmp_path / "source.txt"
    source.write_text("old\n")
    patch = b"""*** Begin Patch
*** Update File: source.txt
@@
-old
+new
*** End Patch"""
    entered = threading.Event()
    release = threading.Event()

    def block_stage(point: str, index: int, operation: PatchOperation) -> None:
        if point == "stage" and index == 0:
            entered.set()
            release.wait(timeout=2)

    client = _FakeClient()
    operations = RunnerOperations(
        client=client,
        workspace=Workspace(str(tmp_path)),
        apply_patch_fault_injector=block_stage,
    )
    task = asyncio.create_task(operations.handle(_operation(tmp_path, patch)))
    assert await asyncio.to_thread(entered.wait, 1)

    task.cancel()
    release.set()
    await asyncio.wait_for(task, timeout=2)

    assert source.read_text() == "old\n"
    assert client.events[-1].event_type == RuntimeRunnerEventType.FINAL_ERROR
    detail = client.events[-1].payload["file_apply_patch"]
    assert isinstance(detail, dict)
    assert detail["reason"] == "cancelled"
    assert detail["applied"] == []
    await operations.close()


@pytest.mark.asyncio
async def test_runner_cancellation_after_commit_starts_waits_for_terminal_result(
    tmp_path: Path,
) -> None:
    source = tmp_path / "source.txt"
    source.write_text("old\n")
    patch = b"""*** Begin Patch
*** Update File: source.txt
@@
-old
+new
*** End Patch"""
    entered = threading.Event()
    release = threading.Event()

    def block_commit(point: str, index: int, operation: PatchOperation) -> None:
        if point == "commit" and index == 0:
            entered.set()
            release.wait(timeout=2)

    client = _FakeClient()
    operations = RunnerOperations(
        client=client,
        workspace=Workspace(str(tmp_path)),
        apply_patch_fault_injector=block_commit,
    )
    task = asyncio.create_task(operations.handle(_operation(tmp_path, patch)))
    assert await asyncio.to_thread(entered.wait, 1)

    task.cancel()
    release.set()
    await asyncio.wait_for(task, timeout=2)

    assert source.read_text() == "new\n"
    assert client.events[-1].event_type == RuntimeRunnerEventType.FINAL_SUCCESS
    await operations.close()


def _operation(base_path: Path, patch: bytes) -> RunnerOperationEnvelope:
    payload: dict[str, JsonValue] = {
        "base_path": str(base_path),
        "total_bytes": len(patch),
        "schema_version": PATCH_SCHEMA_VERSION,
    }
    return RunnerOperationEnvelope(
        request_id="request-1",
        runtime_id="runtime-1",
        runner_generation=1,
        operation_type="file.apply_patch",
        owner_session_id="session-1",
        payload=payload,
        reply_stream_id="reply:request-1",
        body_stream_id="body:request-1",
        body_chunks=(RunnerBodyChunk(chunk_id=0, data=patch, final=True),),
        deadline_at=None,
    )
