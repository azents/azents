"""Operation-specific ingress contracts and compatibility defaults."""

from dataclasses import asdict

import pytest
from azents_runtime_control.runner import JsonValue

import azents_runtime_runner.operation_payloads as payloads


@pytest.mark.parametrize(
    ("operation_type", "raw", "schema"),
    [
        ("bash", {"command": "true"}, payloads.BashPayload),
        ("file.read", {}, payloads.FileReadPayload),
        ("file.download", {}, payloads.FileReadPayload),
        ("file.read_text", {}, payloads.FileReadTextPayload),
        ("file.write", {}, payloads.FileWritePayload),
        ("file.upload", {}, payloads.FileWritePayload),
        ("file.apply_patch", {"base_path": "/fixture"}, payloads.FileApplyPatchPayload),
        (
            "file.edit",
            {"old_string": "old", "new_string": ""},
            payloads.FileEditPayload,
        ),
        ("file.list", {}, payloads.FileListPayload),
        ("file.glob", {"pattern": "*"}, payloads.FileGlobPayload),
        ("file.grep", {"pattern": "text"}, payloads.FileGrepPayload),
        ("file.stat", {}, payloads.FileStatPayload),
        ("file.delete", {}, payloads.FileDeletePayload),
        ("file.mkdir", {}, payloads.FileMkdirPayload),
        ("file.move", {}, payloads.FileMovePayload),
        ("file.bulk_delete", {}, payloads.FileBulkDeletePayload),
        ("file.bulk_move", {}, payloads.FileBulkMovePayload),
        ("process.start", {"command": "true"}, payloads.ProcessStartPayload),
        ("process.write", {"process_id": "fixture"}, payloads.ProcessWritePayload),
        (
            "process.terminate_session",
            {"owner_session_id": "fixture"},
            payloads.ProcessTerminateSessionPayload,
        ),
        ("list_git_refs", {}, payloads.GitListRefsPayload),
        ("create_git_worktree", {}, payloads.GitCreateWorktreePayload),
        ("inspect_git_worktree", {}, payloads.GitInspectWorktreePayload),
        (
            "discover_managed_git_worktrees",
            {},
            payloads.GitDiscoverManagedWorktreesPayload,
        ),
        (
            "remove_discovered_git_worktree",
            {
                "repository_anchor_path": "/fixture",
                "branch_name": "fixture",
                "fingerprint": "fixture",
            },
            payloads.GitRemoveDiscoveredWorktreePayload,
        ),
        (
            "remove_git_worktree",
            {"branch_name": "fixture"},
            payloads.GitRemoveWorktreePayload,
        ),
        (
            "delete_git_branch",
            {"branch_name": "fixture"},
            payloads.GitDeleteBranchPayload,
        ),
        ("future_operation", {}, payloads.UnsupportedPayload),
    ],
)
def test_every_operation_has_a_typed_payload_and_ignores_extension_keys(
    operation_type: str,
    raw: dict[str, JsonValue],
    schema: type[payloads.OperationPayload],
) -> None:
    decoded = payloads.decode_operation_payload(
        operation_type, {**raw, "future_extension": {"opaque": True}}
    )
    assert type(decoded) is schema
    assert "future_extension" not in asdict(decoded)


@pytest.mark.parametrize("supplied_null", [False, True])
def test_optional_null_retains_documented_defaults(supplied_null: bool) -> None:
    fields: dict[str, JsonValue] = (
        {
            "workdir": None,
            "env": None,
            "yield_time_ms": None,
            "max_output_bytes": None,
        }
        if supplied_null
        else {}
    )
    decoded = payloads.decode_operation_payload(
        "process.start", {"command": "true", **fields}
    )
    assert decoded == payloads.ProcessStartPayload(
        command="true",
        workdir=None,
        env={},
        yield_time_ms=1_000,
        max_output_bytes=64 * 1024,
    )
    text = payloads.decode_operation_payload(
        "file.read_text",
        {
            "path": "fixture",
            "max_characters": 10,
            **({"encoding": None} if supplied_null else {}),
        },
    )
    assert text == payloads.FileReadTextPayload(
        path="fixture", character_offset=0, max_characters=10, encoding="utf-8"
    )
    listed = payloads.decode_operation_payload(
        "file.list",
        {
            "path": "fixture",
            **({"recursive": None, "exclude_patterns": None} if supplied_null else {}),
        },
    )
    assert listed == payloads.FileListPayload(
        path="fixture", recursive=False, exclude_patterns=[]
    )


def test_explicit_zero_empty_false_values_are_not_defaulted() -> None:
    process = payloads.decode_operation_payload(
        "process.write", {"process_id": "fixture", "stdin": "", "yield_time_ms": 0}
    )
    assert process == payloads.ProcessWritePayload(
        process_id="fixture", stdin="", yield_time_ms=0, max_output_bytes=64 * 1024
    )
    edit = payloads.decode_operation_payload(
        "file.edit",
        {
            "path": "fixture",
            "old_string": "old",
            "new_string": "",
            "replace_all": False,
        },
    )
    assert edit == payloads.FileEditPayload(
        path="fixture", old_string="old", new_string="", replace_all=False
    )
    grep = payloads.decode_operation_payload(
        "file.grep", {"pattern": "text", "recursive": False, "exclude_patterns": []}
    )
    assert isinstance(grep, payloads.FileGrepPayload)
    assert grep.recursive is False
    assert grep.exclude_patterns == []
    assert (
        grep.max_matching_files,
        grep.max_lines_per_file,
        grep.max_searched_files,
        grep.max_scanned_bytes,
    ) == (50, 10, 10_000, 128 * 1024 * 1024)


@pytest.mark.parametrize(
    ("operation_type", "raw", "code"),
    [
        ("file.edit", {"old_string": "old", "new_string": None}, "INVALID_PAYLOAD"),
        ("file.edit", {"old_string": "old", "new_string": 1}, "INVALID_PAYLOAD"),
        ("file.edit", {"old_string": "old"}, "INVALID_PAYLOAD"),
        ("file.read", {"offset": True}, "INVALID_FILE_READ_RANGE"),
        ("file.read", {"offset": "1"}, "INVALID_FILE_READ_RANGE"),
        ("file.read", {"max_bytes": 1.5}, "INVALID_FILE_READ_RANGE"),
        ("file.read_text", {"character_offset": []}, "INVALID_FILE_READ_TEXT_RANGE"),
        ("file.read_text", {"max_characters": "10"}, "INVALID_FILE_READ_TEXT_RANGE"),
        ("file.read_text", {"encoding": False}, "FILE_READ_TEXT_UNSUPPORTED_ENCODING"),
        (
            "bash",
            {"command": "true", "env": {"GOOD": "value", "BAD": 1}},
            "INVALID_ENVIRONMENT",
        ),
        ("process.start", {"command": "true", "env": []}, "INVALID_ENVIRONMENT"),
        ("process.start", {"command": "true", "workdir": 1}, "INVALID_WORKDIR"),
        (
            "process.write",
            {"process_id": "fixture", "yield_time_ms": -1},
            "INVALID_PAYLOAD",
        ),
        (
            "process.write",
            {"process_id": "fixture", "max_output_bytes": 0},
            "INVALID_PAYLOAD",
        ),
        ("file.bulk_delete", {"paths": ["fixture", None]}, "INVALID_PAYLOAD"),
        ("file.list", {"exclude_patterns": ["valid", 1]}, "INVALID_PAYLOAD"),
        ("file.move", {"overwrite": 1}, "INVALID_PAYLOAD"),
        ("file.grep", {"pattern": "text", "recursive": "false"}, "INVALID_PAYLOAD"),
        ("file.grep", {"pattern": "text", "max_matching_files": 0}, "INVALID_PAYLOAD"),
        ("create_git_worktree", {"starting_ref": False}, "invalid_ref"),
        ("delete_git_branch", {"branch_name": False}, "invalid_branch"),
        (
            "file.apply_patch",
            {"base_path": "/fixture", "schema_version": True},
            "FILE_APPLY_PATCH_FAILED",
        ),
    ],
)
def test_malformed_supplied_fields_have_existing_failure_codes(
    operation_type: str, raw: dict[str, JsonValue], code: str
) -> None:
    with pytest.raises(payloads.OperationPayloadError) as caught:
        payloads.decode_operation_payload(operation_type, raw)
    assert caught.value.code == code
