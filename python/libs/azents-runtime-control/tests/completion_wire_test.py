"""Runner final-success evidence survives the production protobuf event codec."""

from datetime import datetime, timezone

import pytest

from azents_runtime_control.grpc_runner_client import (
    _copy_event_payload,
    runner_event_from_message,
)
from azents_runtime_control.proto import runtime_runner_control_pb2 as pb
from azents_runtime_control.runner import (
    JsonValue,
    RunnerOperationEvent,
    RuntimeRunnerEventType,
)


def roundtrip(payload: dict[str, JsonValue]) -> RunnerOperationEvent:
    """Exercise both production mappings and protobuf binary serialization."""
    event = RunnerOperationEvent(
        request_id="request",
        runtime_id="runtime",
        generation=1,
        event_type=RuntimeRunnerEventType.FINAL_SUCCESS,
        payload=payload,
        created_at=datetime.now(timezone.utc),
        final=True,
    )
    message = pb.RunnerOperationEvent(
        runtime_id=event.runtime_id,
        generation=event.generation,
        event_type=event.event_type.value,
        final=event.final,
    )
    message.created_at.FromDatetime(event.created_at)
    _copy_event_payload(message, event)
    return runner_event_from_message(
        pb.RunnerOperationEvent.FromString(message.SerializeToString()),
        request_id=event.request_id,
    )


VALID: tuple[dict[str, JsonValue], ...] = (
    {"exit_code": 0},
    {"exit_code": 7},
    {"bytes_read": 0},
    {"bytes_written": 0},
    {"replacements": 0},
    {"terminated_count": 0},
    {"terminated_count": 2},
    {"start_character": 0, "end_character": 0, "truncated": False},
    {"entries": []},
    {"matches": []},
    {"changes": []},
    {"deleted_paths": []},
    {"moved_entries": []},
    {
        "files": [],
        "searched_file_count": 0,
        "matched_file_count": 0,
        "truncated": False,
    },
    {"deleted_path": "/a"},
    {"created_path": "/a"},
    {"moved_source_path": "/a", "moved_destination_path": "/b"},
    {"base_commit": "sha", "worktree_path": "/tree", "branch_name": "work"},
    {"removed_worktree_path": "/tree", "outcome": "removed"},
    {"removed_discovered_worktree_path": "/tree", "outcome": "already_absent"},
    {"deleted_branch_name": "work", "outcome": "deleted"},
    {"discovered_worktrees": []},
    {"entries": [{"path": "/a", "type": "file", "size_bytes": 0, "modified_at": None}]},
    {
        "changes": [
            {"path": "/a", "action": "add", "added_lines": 0, "removed_lines": 0}
        ]
    },
)


@pytest.mark.parametrize("payload", VALID)
def test_valid_evidence_roundtrips_without_defaults(
    payload: dict[str, JsonValue],
) -> None:
    event = roundtrip(payload)
    assert event.event_type == RuntimeRunnerEventType.FINAL_SUCCESS
    assert event.payload == (
        {"entries": payload["matches"]} if "matches" in payload else payload
    )
    assert event.final


@pytest.mark.parametrize("payload", VALID)
def test_unknown_fields_never_disappear(payload: dict[str, JsonValue]) -> None:
    event = roundtrip({**payload, "unexpected": "evidence"})
    assert event.event_type == RuntimeRunnerEventType.FINAL_ERROR
    assert event.payload["error_code"] == (
        "invalid_bash_completion"
        if "exit_code" in payload
        else "invalid_runner_completion"
    )


@pytest.mark.parametrize("value", [None, "0", True, False, 1.0, [], {}, -1, 2**64])
@pytest.mark.parametrize("field", ["bytes_written", "bytes_read", "terminated_count"])
def test_malformed_counts_are_errors_not_zero(field: str, value: JsonValue) -> None:
    event = roundtrip({field: value})
    assert event.event_type == RuntimeRunnerEventType.FINAL_ERROR
    assert event.payload["error_code"] == "invalid_runner_completion"


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"end_character": 0, "truncated": False},
        {"start_character": 0, "truncated": False},
        {"start_character": 0, "end_character": 0},
        {"files": [], "matched_file_count": 0, "truncated": False},
        {"moved_source_path": "/a"},
        {"entries": [None]},
        {"entries": [{"path": "/a"}]},
        {"entries": [{"path": "/a", "type": "file", "size_bytes": True}]},
        {"entries": [{"path": "/a", "type": "file", "extra": 1}]},
        {"deleted_paths": ["/a", 5]},
        {"moved_entries": [{"source_path": "/a"}]},
        {"git_refs": [{"name": "main"}], "repository_anchor_path": "/repo"},
        {
            "changes": [
                {"path": "/a", "action": "add", "added_lines": True, "removed_lines": 0}
            ]
        },
        {
            "files": [
                {
                    "path": "/a",
                    "truncated": False,
                    "lines": [{"line_number": True, "text": "x"}],
                }
            ],
            "searched_file_count": 1,
            "matched_file_count": 1,
            "truncated": False,
        },
    ],
)
def test_missing_and_nested_evidence_is_rejected(payload: dict[str, JsonValue]) -> None:
    event = roundtrip(payload)
    assert event.event_type == RuntimeRunnerEventType.FINAL_ERROR
    assert event.payload["error_code"] == "invalid_runner_completion"


@pytest.mark.parametrize("count", [0, 2])
def test_termination_uses_its_typed_result_arm(count: int) -> None:
    event = RunnerOperationEvent(
        request_id="r",
        runtime_id="runtime",
        generation=1,
        event_type=RuntimeRunnerEventType.FINAL_SUCCESS,
        payload={"terminated_count": count},
        created_at=datetime.now(timezone.utc),
        final=True,
    )
    message = pb.RunnerOperationEvent(event_type="final_success", final=True)
    _copy_event_payload(message, event)
    assert message.final_success.WhichOneof("result") == "process_terminate_session"
    assert message.final_success.process_terminate_session.terminated_count == count


def test_declared_nullable_metadata_is_preserved() -> None:
    stat = roundtrip(
        {
            "path": "/a",
            "kind": "missing",
            "size_bytes": None,
            "symlink": False,
            "real_path": None,
            "modified_at": None,
        }
    )
    assert stat.event_type == RuntimeRunnerEventType.FINAL_SUCCESS
    assert stat.payload == {
        "path": "/a",
        "kind": "missing",
        "size_bytes": None,
        "symlink": False,
    }
    refs = roundtrip(
        {
            "git_refs": [],
            "repository_anchor_path": "/repo",
            "default_branch": None,
            "head_commit": None,
        }
    )
    assert refs.event_type == RuntimeRunnerEventType.FINAL_SUCCESS
    assert refs.payload["default_branch"] == refs.payload["head_commit"] == ""


@pytest.mark.parametrize("reason", [None, "max_matches", ""])
def test_grep_producer_stop_reason_survives_roundtrip(reason: str | None) -> None:
    event = roundtrip(
        {
            "files": [],
            "searched_file_count": 0,
            "matched_file_count": 0,
            "truncated": reason is not None,
            "stopped_reason": reason,
        }
    )
    assert event.event_type == RuntimeRunnerEventType.FINAL_SUCCESS
    assert event.payload.get("stopped_reason") == reason
