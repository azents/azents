"""Closed Runner success decoding preserves evidence instead of inventing it."""

import dataclasses
from datetime import datetime, timezone

import pytest

import azents.runtime.control_protocol.runner_operations as operations
from azents.runtime.coordination.data import (
    JsonValue,
    RuntimeReplyEvent,
    RuntimeReplyEventType,
    RuntimeReplyRecord,
)


@dataclasses.dataclass(frozen=True)
class CompletionCase:
    result_type: type
    payload: dict[str, JsonValue]
    derived: dict[str, JsonValue] | None
    optional: tuple[str, ...]


CASES = (
    CompletionCase(operations._FileReadCompletion, {"bytes_read": 0}, None, ()),
    CompletionCase(
        operations._ProcessTerminationCompletion, {"terminated_count": 0}, None, ()
    ),
    CompletionCase(
        operations.RuntimeFileTextReadResult,
        {"start_character": 0, "end_character": 3, "truncated": False},
        {"text": "abc"},
        (),
    ),
    CompletionCase(operations.RuntimeFileListResult, {"entries": []}, None, ()),
    CompletionCase(
        operations.RuntimeFileStatResult,
        {"path": "/a", "kind": "missing", "size_bytes": None, "symlink": False},
        None,
        ("size_bytes",),
    ),
    CompletionCase(operations.RuntimeFileWriteResult, {"bytes_written": 0}, None, ()),
    CompletionCase(operations.RuntimeFileApplyPatchResult, {"changes": []}, None, ()),
    CompletionCase(operations.RuntimeFileEditResult, {"replacements": 0}, None, ()),
    CompletionCase(
        operations.RuntimeFileDeleteResult, {"deleted_path": "/a"}, None, ()
    ),
    CompletionCase(operations.RuntimeFileMkdirResult, {"created_path": "/a"}, None, ()),
    CompletionCase(
        operations.RuntimeFileMoveResult,
        {"moved_source_path": "/a", "moved_destination_path": "/b"},
        None,
        (),
    ),
    CompletionCase(
        operations.RuntimeFileBulkDeleteResult, {"deleted_paths": []}, None, ()
    ),
    CompletionCase(
        operations.RuntimeFileBulkMoveResult, {"moved_entries": []}, None, ()
    ),
    CompletionCase(
        operations.RuntimeGrepResult,
        {
            "files": [],
            "searched_file_count": 0,
            "matched_file_count": 0,
            "truncated": False,
        },
        None,
        (),
    ),
    CompletionCase(
        operations.RuntimeGitRefsResult,
        {"git_refs": [], "repository_anchor_path": "/repo"},
        None,
        (),
    ),
    CompletionCase(
        operations.RuntimeGitCreateWorktreeResult,
        {"base_commit": "abc", "worktree_path": "/tree", "branch_name": "work"},
        None,
        (),
    ),
    CompletionCase(
        operations.RuntimeGitRemoveWorktreeResult,
        {"removed_worktree_path": "/tree", "outcome": "removed"},
        None,
        (),
    ),
    CompletionCase(
        operations.RuntimeGitInspectWorktreeResult,
        {
            "worktree_path": "/tree",
            "worktree_registered": False,
            "target_kind": "missing",
        },
        None,
        (),
    ),
    CompletionCase(
        operations.RuntimeDiscoverManagedGitWorktreesResult,
        {"discovered_worktrees": []},
        None,
        (),
    ),
    CompletionCase(
        operations.RuntimeRemoveDiscoveredGitWorktreeResult,
        {"removed_discovered_worktree_path": "/tree", "outcome": "already_absent"},
        None,
        (),
    ),
    CompletionCase(
        operations.RuntimeGitDeleteBranchResult,
        {"deleted_branch_name": "work", "outcome": "deleted"},
        None,
        (),
    ),
    CompletionCase(
        operations.RuntimeProcessResult,
        {
            "process_id": "p",
            "status": "running",
            "stdout": "",
            "stderr": "",
            "stdout_truncated": False,
            "stderr_truncated": False,
            "stdout_omitted_bytes": 0,
            "stderr_omitted_bytes": 0,
        },
        None,
        (),
    ),
)


def final(payload: dict[str, JsonValue]) -> RuntimeReplyRecord:
    return RuntimeReplyRecord(
        cursor="7-0",
        event=RuntimeReplyEvent(
            request_id="r",
            runtime_id="runtime",
            generation=1,
            event_type=RuntimeReplyEventType.FINAL_SUCCESS,
            payload=payload,
            created_at=datetime.now(timezone.utc),
            final=True,
        ),
    )


@pytest.mark.parametrize("case", CASES, ids=lambda case: case.result_type.__name__)
def test_valid_completion_preserves_empty_values_and_cursor(
    case: CompletionCase,
) -> None:
    result = operations._decode_completion(
        case.result_type,
        final(case.payload),
        derived=case.derived,
    )
    assert isinstance(result, case.result_type)
    assert dataclasses.is_dataclass(result) and not isinstance(result, type)
    assert dataclasses.asdict(result)["final_cursor"] == "7-0"


@pytest.mark.parametrize("case", CASES, ids=lambda case: case.result_type.__name__)
def test_required_fields_and_unknown_fields_fail_closed(case: CompletionCase) -> None:
    for key, value in case.payload.items():
        if key in case.optional:
            continue
        missing = {name: item for name, item in case.payload.items() if name != key}
        invalid = dict(case.payload)
        invalid[key] = (
            True if type(value) is int else 42 if isinstance(value, bool) else None
        )
        for payload in (missing, invalid):
            with pytest.raises(operations.RuntimeRunnerOperationFailedError) as error:
                operations._decode_completion(
                    case.result_type,
                    final(payload),
                    derived=case.derived,
                )
            assert error.value.code == "invalid_runner_completion"
    for key in ("unexpected", "final_cursor"):
        payload = {**case.payload, key: "injected"}
        with pytest.raises(operations.RuntimeRunnerOperationFailedError):
            operations._decode_completion(
                case.result_type,
                final(payload),
                derived=case.derived,
            )


@pytest.mark.parametrize(
    "result_type,key,item",
    [
        (
            operations.RuntimeFileListResult,
            "entries",
            {"path": "/a", "type": "bogus", "size_bytes": 0},
        ),
        (operations.RuntimeFileBulkDeleteResult, "deleted_paths", 5),
        (operations.RuntimeFileBulkMoveResult, "moved_entries", {"source_path": "/a"}),
        (
            operations.RuntimeFileApplyPatchResult,
            "changes",
            {"path": "/a", "action": "add", "added_lines": True, "removed_lines": 0},
        ),
        (
            operations.RuntimeDiscoverManagedGitWorktreesResult,
            "discovered_worktrees",
            {"worktree_path": "/a", "fingerprint": "f"},
        ),
        (
            operations.RuntimeGrepResult,
            "files",
            {
                "path": "/a",
                "truncated": False,
                "lines": [{"line_number": True, "text": "line"}],
            },
        ),
        (
            operations.RuntimeGitRefsResult,
            "git_refs",
            {
                "name": "main",
                "ref": "refs/heads/main",
                "type": "branch",
                "target": "abc",
                "default": "false",
            },
        ),
    ],
)
def test_bad_collection_items_are_rejected_not_filtered(
    result_type: type,
    key: str,
    item: JsonValue,
) -> None:
    case = next(case for case in CASES if case.result_type is result_type)
    payload = {**case.payload, key: [item]}
    with pytest.raises(operations.RuntimeRunnerOperationFailedError):
        operations._decode_completion(result_type, final(payload), derived=None)


def test_discovery_empty_optional_wire_strings_normalize_without_mutation() -> None:
    entry: dict[str, JsonValue] = {
        "worktree_path": "/tree",
        "registered": False,
        "fingerprint": "f",
        "repository_anchor_path": "",
        "branch_name": "",
        "failure_code": "",
    }
    result = operations._decode_completion(
        operations.RuntimeDiscoverManagedGitWorktreesResult,
        final({"discovered_worktrees": [entry]}),
        derived=None,
    )
    assert result.entries[0].repository_anchor_path is None
    assert result.entries[0].branch_name is None
    assert result.entries[0].failure_code is None
    assert entry["branch_name"] == ""
