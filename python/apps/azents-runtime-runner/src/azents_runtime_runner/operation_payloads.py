"""Operation-specific Runtime payloads decoded once at the transport boundary.

The protocol accepts extension keys and optional null/default choices. Supplied
malformed fields fail before effects; handlers receive only declared validated
fields and retain ownership of filesystem, process, and Git semantic outcomes.
"""

from collections.abc import Mapping
from dataclasses import dataclass

from azents_runtime_control.runner import JsonValue


@dataclass(frozen=True)
class BashPayload:
    command: str
    timeout_seconds: int
    env: dict[str, str]


@dataclass(frozen=True)
class FileReadPayload:
    path: str | None
    offset: int
    max_bytes: int | None


@dataclass(frozen=True)
class FileReadTextPayload:
    path: str | None
    character_offset: int
    max_characters: int
    encoding: str


@dataclass(frozen=True)
class FileWritePayload:
    path: str | None


@dataclass(frozen=True)
class FileApplyPatchPayload:
    base_path: str
    total_bytes: int
    schema_version: int


@dataclass(frozen=True)
class FileEditPayload:
    path: str | None
    old_string: str
    new_string: str
    replace_all: bool


@dataclass(frozen=True)
class FileListPayload:
    path: str | None
    recursive: bool
    exclude_patterns: list[str]


@dataclass(frozen=True)
class FileGlobPayload:
    pattern: str
    exclude_patterns: list[str]


@dataclass(frozen=True)
class FileGrepPayload:
    path: str | None
    pattern: str
    recursive: bool
    exclude_patterns: list[str]
    max_matching_files: int
    max_lines_per_file: int
    max_searched_files: int
    max_scanned_bytes: int


@dataclass(frozen=True)
class FileStatPayload:
    path: str | None


@dataclass(frozen=True)
class FileDeletePayload:
    path: str | None
    recursive: bool


@dataclass(frozen=True)
class FileMkdirPayload:
    path: str | None
    parents: bool


@dataclass(frozen=True)
class FileMovePayload:
    source_path: str | None
    destination_path: str | None
    overwrite: bool


@dataclass(frozen=True)
class FileBulkDeletePayload:
    paths: list[str]
    recursive: bool


@dataclass(frozen=True)
class FileBulkMovePayload:
    source_paths: list[str]
    destination_directory: str | None
    overwrite: bool


@dataclass(frozen=True)
class ProcessStartPayload:
    command: str
    workdir: str | None
    env: dict[str, str]
    yield_time_ms: int
    max_output_bytes: int


@dataclass(frozen=True)
class ProcessWritePayload:
    process_id: str
    stdin: str
    yield_time_ms: int
    max_output_bytes: int


@dataclass(frozen=True)
class ProcessTerminateSessionPayload:
    owner_session_id: str


@dataclass(frozen=True)
class GitListRefsPayload:
    source_project_path: str | None


@dataclass(frozen=True)
class GitCreateWorktreePayload:
    source_project_path: str | None
    worktree_path: str | None
    starting_ref: str
    branch_name: str


@dataclass(frozen=True)
class GitInspectWorktreePayload:
    source_project_path: str | None
    worktree_path: str | None


@dataclass(frozen=True)
class GitDiscoverManagedWorktreesPayload:
    """Discovery has no operation-specific input fields."""


@dataclass(frozen=True)
class GitRemoveDiscoveredWorktreePayload:
    worktree_path: str | None
    repository_anchor_path: str
    branch_name: str
    fingerprint: str
    force: bool


@dataclass(frozen=True)
class GitRemoveWorktreePayload:
    source_project_path: str | None
    worktree_path: str | None
    branch_name: str
    force: bool


@dataclass(frozen=True)
class GitDeleteBranchPayload:
    source_project_path: str | None
    branch_name: str


@dataclass(frozen=True)
class UnsupportedPayload:
    operation_type: str


type OperationPayload = (
    BashPayload
    | FileReadPayload
    | FileReadTextPayload
    | FileWritePayload
    | FileApplyPatchPayload
    | FileEditPayload
    | FileListPayload
    | FileGlobPayload
    | FileGrepPayload
    | FileStatPayload
    | FileDeletePayload
    | FileMkdirPayload
    | FileMovePayload
    | FileBulkDeletePayload
    | FileBulkMovePayload
    | ProcessStartPayload
    | ProcessWritePayload
    | ProcessTerminateSessionPayload
    | GitListRefsPayload
    | GitCreateWorktreePayload
    | GitInspectWorktreePayload
    | GitDiscoverManagedWorktreesPayload
    | GitRemoveDiscoveredWorktreePayload
    | GitRemoveWorktreePayload
    | GitDeleteBranchPayload
    | UnsupportedPayload
)


class OperationPayloadError(ValueError):
    """Expected malformed input with an existing terminal failure classification."""

    def __init__(self, code: str, message: str, *, patch_reason: str | None) -> None:
        super().__init__(message)
        self.code = code
        self.patch_reason = patch_reason


class _Fields:
    """Validate primitive fields only at the operation-specific ingress boundary."""

    def __init__(self, operation_type: str, raw: Mapping[str, JsonValue]) -> None:
        self.operation_type = operation_type
        self.raw = raw

    def failure(self, key: str, message: str) -> OperationPayloadError:
        code = "INVALID_PAYLOAD"
        patch_reason: str | None = None
        if self.operation_type == "file.apply_patch":
            code = "FILE_APPLY_PATCH_FAILED"
            patch_reason = {
                "base_path": "base_path_required",
                "total_bytes": "patch_size_mismatch",
                "schema_version": "unsupported_schema_version",
            }[key]
        elif self.operation_type in {"file.read", "file.download"} and key in {
            "offset",
            "max_bytes",
        }:
            code = "INVALID_FILE_READ_RANGE"
        elif self.operation_type == "file.read_text" and key in {
            "character_offset",
            "max_characters",
        }:
            code = "INVALID_FILE_READ_TEXT_RANGE"
        elif key == "encoding":
            code = "FILE_READ_TEXT_UNSUPPORTED_ENCODING"
        elif key == "workdir":
            code = "INVALID_WORKDIR"
        elif key == "env":
            code = "INVALID_ENVIRONMENT"
        elif key in {
            "path",
            "source_path",
            "destination_path",
            "destination_directory",
        }:
            code = (
                "FILE_EDIT_INVALID_PATH"
                if self.operation_type == "file.edit"
                else "INVALID_PATH"
            )
        elif key == "source_project_path":
            code = "invalid_source_path"
        elif key == "worktree_path":
            code = "invalid_worktree_path"
        elif key == "starting_ref":
            code = "invalid_ref"
        elif key == "branch_name":
            code = "invalid_branch"
        elif key == "repository_anchor_path":
            code = "worktree_ownership_ambiguous"
        elif key == "fingerprint":
            code = "identity_changed"
        elif self.operation_type == "file.glob" and key == "pattern":
            code = "INVALID_PATTERN"
        return OperationPayloadError(code, message, patch_reason=patch_reason)

    def optional_string(self, key: str) -> str | None:
        value = self.raw.get(key)
        if value is None or isinstance(value, str):
            return value
        raise self.failure(key, f"{key} must be a string")

    def string(self, key: str, *, required: bool = True) -> str:
        value = self.optional_string(key)
        if value is None:
            if required:
                raise self.failure(key, f"{key} is required")
            return ""
        return value

    def optional_integer(self, key: str) -> int | None:
        value = self.raw.get(key)
        if value is None:
            return None
        if isinstance(value, int) and not isinstance(value, bool):
            return value
        raise self.failure(key, f"{key} must be an integer")

    def integer(self, key: str, *, default: int) -> int:
        value = self.optional_integer(key)
        return value if value is not None else default

    def positive_integer(self, key: str, *, default: int) -> int:
        value = self.integer(key, default=default)
        if value <= 0:
            raise self.failure(key, f"{key} must be positive")
        return value

    def non_negative_integer(self, key: str, *, default: int) -> int:
        value = self.integer(key, default=default)
        if value < 0:
            raise self.failure(key, f"{key} must be non-negative")
        return value

    def boolean(self, key: str, *, default: bool) -> bool:
        value = self.raw.get(key)
        if value is None:
            return default
        if isinstance(value, bool):
            return value
        raise self.failure(key, f"{key} must be a boolean")

    def strings(self, key: str) -> list[str]:
        value = self.raw.get(key)
        if value is None:
            return []
        if not isinstance(value, list):
            raise self.failure(key, f"{key} must be a list of strings")
        result: list[str] = []
        for item in value:
            if not isinstance(item, str):
                raise self.failure(key, f"{key} must contain only strings")
            result.append(item)
        return result

    def environment(self) -> dict[str, str]:
        value = self.raw.get("env")
        if value is None:
            return {}
        if not isinstance(value, dict):
            raise self.failure("env", "env must be a string mapping")
        result: dict[str, str] = {}
        for key, item in value.items():
            if not isinstance(key, str) or not isinstance(item, str):
                raise self.failure(
                    "env", "env must contain only string keys and values"
                )
            result[key] = item
        return result


def decode_operation_payload(
    operation_type: str, raw: Mapping[str, JsonValue]
) -> OperationPayload:
    """Validate each consumed field into its operation's typed input contract.

    Unknown extension fields are ignored. Required values and semantic ranges
    retain the handlers' existing terminal failure classifications; nullable
    optional fields retain their historical compatibility defaults.
    No JSON value or generic field accessor crosses this boundary.
    """
    fields = _Fields(operation_type, raw)
    match operation_type:
        case "bash":
            return BashPayload(
                fields.string("command"),
                fields.integer("timeout_seconds", default=120),
                fields.environment(),
            )
        case "file.read" | "file.download":
            return FileReadPayload(
                fields.optional_string("path"),
                fields.integer("offset", default=0),
                fields.optional_integer("max_bytes"),
            )
        case "file.read_text":
            return FileReadTextPayload(
                fields.optional_string("path"),
                fields.integer("character_offset", default=0),
                fields.integer("max_characters", default=0),
                fields.optional_string("encoding") or "utf-8",
            )
        case "file.write" | "file.upload":
            return FileWritePayload(fields.optional_string("path"))
        case "file.apply_patch":
            return FileApplyPatchPayload(
                fields.string("base_path"),
                fields.integer("total_bytes", default=-1),
                fields.integer("schema_version", default=0),
            )
        case "file.edit":
            return FileEditPayload(
                fields.optional_string("path"),
                fields.string("old_string"),
                fields.string("new_string"),
                fields.boolean("replace_all", default=False),
            )
        case "file.list":
            return FileListPayload(
                fields.optional_string("path"),
                fields.boolean("recursive", default=False),
                fields.strings("exclude_patterns"),
            )
        case "file.glob":
            return FileGlobPayload(
                fields.string("pattern"), fields.strings("exclude_patterns")
            )
        case "file.grep":
            return FileGrepPayload(
                fields.optional_string("path"),
                fields.string("pattern"),
                fields.boolean("recursive", default=True),
                fields.strings("exclude_patterns"),
                fields.positive_integer("max_matching_files", default=50),
                fields.positive_integer("max_lines_per_file", default=10),
                fields.positive_integer("max_searched_files", default=10_000),
                fields.positive_integer("max_scanned_bytes", default=128 * 1024 * 1024),
            )
        case "file.stat":
            return FileStatPayload(fields.optional_string("path"))
        case "file.delete":
            return FileDeletePayload(
                fields.optional_string("path"),
                fields.boolean("recursive", default=False),
            )
        case "file.mkdir":
            return FileMkdirPayload(
                fields.optional_string("path"), fields.boolean("parents", default=False)
            )
        case "file.move":
            return FileMovePayload(
                fields.optional_string("source_path"),
                fields.optional_string("destination_path"),
                fields.boolean("overwrite", default=False),
            )
        case "file.bulk_delete":
            return FileBulkDeletePayload(
                fields.strings("paths"), fields.boolean("recursive", default=False)
            )
        case "file.bulk_move":
            return FileBulkMovePayload(
                fields.strings("source_paths"),
                fields.optional_string("destination_directory"),
                fields.boolean("overwrite", default=False),
            )
        case "process.start":
            return ProcessStartPayload(
                fields.string("command"),
                fields.optional_string("workdir"),
                fields.environment(),
                fields.non_negative_integer("yield_time_ms", default=1_000),
                fields.positive_integer("max_output_bytes", default=64 * 1024),
            )
        case "process.write":
            return ProcessWritePayload(
                fields.string("process_id"),
                fields.string("stdin", required=False),
                fields.non_negative_integer("yield_time_ms", default=1_000),
                fields.positive_integer("max_output_bytes", default=64 * 1024),
            )
        case "process.terminate_session":
            return ProcessTerminateSessionPayload(fields.string("owner_session_id"))
        case "list_git_refs":
            return GitListRefsPayload(fields.optional_string("source_project_path"))
        case "create_git_worktree":
            return GitCreateWorktreePayload(
                fields.optional_string("source_project_path"),
                fields.optional_string("worktree_path"),
                fields.string("starting_ref", required=False),
                fields.string("branch_name", required=False),
            )
        case "inspect_git_worktree":
            return GitInspectWorktreePayload(
                fields.optional_string("source_project_path"),
                fields.optional_string("worktree_path"),
            )
        case "discover_managed_git_worktrees":
            return GitDiscoverManagedWorktreesPayload()
        case "remove_discovered_git_worktree":
            return GitRemoveDiscoveredWorktreePayload(
                fields.optional_string("worktree_path"),
                fields.string("repository_anchor_path"),
                fields.string("branch_name"),
                fields.string("fingerprint"),
                fields.boolean("force", default=False),
            )
        case "remove_git_worktree":
            return GitRemoveWorktreePayload(
                fields.optional_string("source_project_path"),
                fields.optional_string("worktree_path"),
                fields.string("branch_name"),
                fields.boolean("force", default=False),
            )
        case "delete_git_branch":
            return GitDeleteBranchPayload(
                fields.optional_string("source_project_path"),
                fields.string("branch_name"),
            )
        case _:
            return UnsupportedPayload(operation_type)
