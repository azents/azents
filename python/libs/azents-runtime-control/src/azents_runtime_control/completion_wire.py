"""Strict JSON ingress for the protobuf Runner completion schemas."""

from collections.abc import Mapping

from google.protobuf.descriptor import Descriptor, FieldDescriptor
from google.protobuf.json_format import ParseDict, ParseError

from azents_runtime_control.proto import runtime_runner_control_pb2 as pb
from azents_runtime_control.runner import JsonValue


class CompletionPayloadError(ValueError):
    """A completion cannot be represented without losing its evidence."""


# Only wire aliases live here; protobuf remains the field/type source of truth.
_ALIASES: dict[str, dict[str, str]] = {
    "FileGlobFinalSuccess": {"entries": "matches"},
    "FileDeleteFinalSuccess": {"path": "deleted_path"},
    "FileMkdirFinalSuccess": {"path": "created_path"},
    "FileMoveFinalSuccess": {
        "source_path": "moved_source_path",
        "destination_path": "moved_destination_path",
    },
    "FileBulkDeleteFinalSuccess": {"paths": "deleted_paths"},
    "FileBulkMoveFinalSuccess": {"entries": "moved_entries"},
    "GitListRefsFinalSuccess": {"refs": "git_refs"},
    "GitInspectWorktreeFinalSuccess": {"registered": "worktree_registered"},
    "GitDiscoverManagedWorktreesFinalSuccess": {"entries": "discovered_worktrees"},
    "GitRemoveDiscoveredWorktreeFinalSuccess": {
        "worktree_path": "removed_discovered_worktree_path"
    },
    "GitRemoveWorktreeFinalSuccess": {"worktree_path": "removed_worktree_path"},
    "GitDeleteBranchFinalSuccess": {"branch_name": "deleted_branch_name"},
}
# These existing string fields use protobuf empty strings for absent metadata.
_NULLABLE_STRINGS: dict[str, frozenset[str]] = {
    "GitListRefsFinalSuccess": frozenset({"default_branch", "head_commit"}),
    "ProcessOperationFinalSuccess": frozenset({"missing_reason"}),
}
_COMPLETION_ARMS = (
    ("process_id", "process"),
    ("status", "process"),
    ("terminated_count", "process_terminate_session"),
    ("exit_code", "bash"),
    ("bytes_read", "file_read"),
    ("start_character", "file_read_text"),
    ("bytes_written", "file_write"),
    ("matches", "file_glob"),
    ("changes", "file_apply_patch"),
    ("replacements", "file_edit"),
    ("entries", "file_list"),
    ("files", "file_grep"),
    ("kind", "file_stat"),
    ("deleted_paths", "file_bulk_delete"),
    ("deleted_path", "file_delete"),
    ("created_path", "file_mkdir"),
    ("moved_entries", "file_bulk_move"),
    ("moved_source_path", "file_move"),
    ("moved_destination_path", "file_move"),
    ("git_refs", "git_list_refs"),
    ("base_commit", "git_create_worktree"),
    ("worktree_registered", "git_inspect_worktree"),
    ("discovered_worktrees", "git_discover_managed_worktrees"),
    ("removed_discovered_worktree_path", "git_remove_discovered_worktree"),
    ("removed_worktree_path", "git_remove_worktree"),
    ("deleted_branch_name", "git_delete_branch"),
)


def copy_completion(
    message: pb.RunnerOperationFinalSuccessPayload,
    payload: Mapping[str, JsonValue],
) -> None:
    """Decode into the selected typed arm before protobuf can apply defaults."""
    for discriminator, arm in _COMPLETION_ARMS:
        if discriminator in payload:
            descriptor = message.DESCRIPTOR.fields_by_name[arm].message_type
            assert descriptor is not None
            normalized = _message_payload(descriptor, payload)
            try:
                ParseDict({arm: normalized}, message)
            except ParseError as exc:
                # Protobuf also owns integer range validation.
                raise CompletionPayloadError("Invalid Runner completion") from exc
            return
    raise CompletionPayloadError("Runner completion has no result")


def _message_payload(
    descriptor: Descriptor,
    payload: Mapping[str, JsonValue],
) -> dict[str, JsonValue]:
    aliases = _ALIASES.get(descriptor.name, {})
    nullable_strings = _NULLABLE_STRINGS.get(descriptor.name, frozenset())
    expected = {aliases.get(field.name, field.name) for field in descriptor.fields}
    if payload.keys() - expected:
        raise CompletionPayloadError("Unexpected Runner completion field")
    result: dict[str, JsonValue] = {}
    for field in descriptor.fields:
        wire_name = aliases.get(field.name, field.name)
        optional = field.has_presence or field.name in nullable_strings
        if wire_name not in payload:
            if optional:
                continue
            raise CompletionPayloadError("Missing Runner completion field")
        value = payload[wire_name]
        if value is None and optional:
            continue
        if field.is_repeated:
            if not isinstance(value, list):
                raise CompletionPayloadError("Invalid Runner completion collection")
            result[field.name] = [_field_value(field, item) for item in value]
        else:
            result[field.name] = _field_value(field, value)
    return result


def _field_value(field: FieldDescriptor, value: JsonValue) -> JsonValue:
    if field.message_type is not None:
        if not isinstance(value, dict):
            raise CompletionPayloadError("Invalid Runner completion entry")
        return _message_payload(field.message_type, value)
    valid = False
    match field.type:
        case FieldDescriptor.TYPE_STRING:
            valid = isinstance(value, str)
        case FieldDescriptor.TYPE_BOOL:
            valid = isinstance(value, bool)
        case (
            FieldDescriptor.TYPE_INT32
            | FieldDescriptor.TYPE_INT64
            | FieldDescriptor.TYPE_UINT32
            | FieldDescriptor.TYPE_UINT64
        ):
            valid = type(value) is int
    if not valid:
        raise CompletionPayloadError("Invalid Runner completion primitive")
    return value
