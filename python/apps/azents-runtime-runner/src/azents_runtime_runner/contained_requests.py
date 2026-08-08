"""Typed contained-operation requests decoded from protocol JSON."""

from dataclasses import dataclass
from typing import TypeAlias

from azents_runtime_runner.contained_protocol import JsonValue


@dataclass(frozen=True)
class FileReadRequest:
    path: str
    offset: int
    max_bytes: int | None


@dataclass(frozen=True)
class FileReadTextRequest:
    path: str
    offset: int
    max_bytes: int | None
    encoding: str


@dataclass(frozen=True)
class FileWriteRequest:
    path: str


@dataclass(frozen=True)
class FileApplyPatchRequest:
    base_path: str
    total_bytes: int
    schema_version: int


@dataclass(frozen=True)
class FileEditRequest:
    path: str
    old_string: str
    new_string: str
    replace_all: bool


@dataclass(frozen=True)
class FileListRequest:
    path: str
    recursive: bool
    exclude_patterns: tuple[str, ...]


@dataclass(frozen=True)
class FileGlobRequest:
    pattern: str
    exclude_patterns: tuple[str, ...]


@dataclass(frozen=True)
class FileGrepRequest:
    path: str
    pattern: str
    recursive: bool
    exclude_patterns: tuple[str, ...]
    max_matching_files: int
    max_lines_per_file: int
    max_searched_files: int
    max_scanned_bytes: int


@dataclass(frozen=True)
class FileStatRequest:
    path: str


@dataclass(frozen=True)
class FileDeleteRequest:
    path: str
    recursive: bool


@dataclass(frozen=True)
class FileMkdirRequest:
    path: str
    parents: bool


@dataclass(frozen=True)
class FileMoveRequest:
    source_path: str
    destination_path: str
    overwrite: bool


@dataclass(frozen=True)
class FileBulkDeleteRequest:
    paths: tuple[str, ...]
    recursive: bool


@dataclass(frozen=True)
class FileBulkMoveRequest:
    source_paths: tuple[str, ...]
    destination_directory: str
    overwrite: bool


@dataclass(frozen=True)
class GitListRefsRequest:
    source_project_path: str


@dataclass(frozen=True)
class GitCreateWorktreeRequest:
    source_project_path: str
    worktree_path: str
    branch_name: str
    starting_ref: str


@dataclass(frozen=True)
class GitInspectWorktreeRequest:
    source_project_path: str
    worktree_path: str


@dataclass(frozen=True)
class GitDiscoverManagedWorktreesRequest:
    pass


@dataclass(frozen=True)
class GitRemoveDiscoveredWorktreeRequest:
    worktree_path: str
    repository_anchor_path: str
    branch_name: str
    fingerprint: str
    force: bool


@dataclass(frozen=True)
class GitRemoveWorktreeRequest:
    source_project_path: str
    worktree_path: str
    branch_name: str
    force: bool


@dataclass(frozen=True)
class GitDeleteBranchRequest:
    source_project_path: str
    branch_name: str


@dataclass(frozen=True)
class TransferDownloadRequest:
    runtime_path: str
    expected_size: int
    expected_sha256: str
    overwrite: bool


@dataclass(frozen=True)
class TransferUploadRequest:
    runtime_path: str
    expected_size: int
    expected_sha256: str | None


FileRequest: TypeAlias = (
    FileReadRequest
    | FileReadTextRequest
    | FileWriteRequest
    | FileApplyPatchRequest
    | FileEditRequest
    | FileListRequest
    | FileGlobRequest
    | FileGrepRequest
    | FileStatRequest
    | FileDeleteRequest
    | FileMkdirRequest
    | FileMoveRequest
    | FileBulkDeleteRequest
    | FileBulkMoveRequest
)
GitRequest: TypeAlias = (
    GitListRefsRequest
    | GitCreateWorktreeRequest
    | GitInspectWorktreeRequest
    | GitDiscoverManagedWorktreesRequest
    | GitRemoveDiscoveredWorktreeRequest
    | GitRemoveWorktreeRequest
    | GitDeleteBranchRequest
)
TransferRequest: TypeAlias = TransferDownloadRequest | TransferUploadRequest
ContainedRequest: TypeAlias = FileRequest | GitRequest | TransferRequest


class ContainedRequestError(ValueError):
    """One protocol payload cannot be decoded as its operation request."""


def decode_contained_request(
    operation: str,
    payload: dict[str, JsonValue],
) -> ContainedRequest:
    """Decode one operation-specific request at the protocol boundary."""
    match operation:
        case "file.read" | "file.download":
            return FileReadRequest(
                path=_string(payload, "path"),
                offset=_integer(payload, "offset", default=0),
                max_bytes=_optional_integer(payload, "max_bytes"),
            )
        case "file.read_text":
            return FileReadTextRequest(
                path=_string(payload, "path"),
                offset=_integer(payload, "offset", default=0),
                max_bytes=_optional_integer(payload, "max_bytes"),
                encoding=_optional_string(payload, "encoding") or "utf-8",
            )
        case "file.write" | "file.upload":
            return FileWriteRequest(path=_string(payload, "path"))
        case "file.apply_patch":
            return FileApplyPatchRequest(
                base_path=_string(payload, "base_path"),
                total_bytes=_integer(payload, "total_bytes", default=-1),
                schema_version=_integer(payload, "schema_version", default=0),
            )
        case "file.edit":
            return FileEditRequest(
                path=_string(payload, "path"),
                old_string=_string(payload, "old_string"),
                new_string=_string(payload, "new_string"),
                replace_all=_boolean(payload, "replace_all", default=False),
            )
        case "file.list":
            return FileListRequest(
                path=_string(payload, "path"),
                recursive=_boolean(payload, "recursive", default=False),
                exclude_patterns=_string_tuple(payload, "exclude_patterns"),
            )
        case "file.glob":
            return FileGlobRequest(
                pattern=_string(payload, "pattern"),
                exclude_patterns=_string_tuple(payload, "exclude_patterns"),
            )
        case "file.grep":
            return FileGrepRequest(
                path=_string(payload, "path"),
                pattern=_string(payload, "pattern"),
                recursive=_boolean(payload, "recursive", default=True),
                exclude_patterns=_string_tuple(payload, "exclude_patterns"),
                max_matching_files=_positive_integer(
                    payload, "max_matching_files", default=50
                ),
                max_lines_per_file=_positive_integer(
                    payload, "max_lines_per_file", default=10
                ),
                max_searched_files=_positive_integer(
                    payload, "max_searched_files", default=10_000
                ),
                max_scanned_bytes=_positive_integer(
                    payload, "max_scanned_bytes", default=128 * 1024 * 1024
                ),
            )
        case "file.stat":
            return FileStatRequest(path=_string(payload, "path"))
        case "file.delete":
            return FileDeleteRequest(
                path=_string(payload, "path"),
                recursive=_boolean(payload, "recursive", default=False),
            )
        case "file.mkdir":
            return FileMkdirRequest(
                path=_string(payload, "path"),
                parents=_boolean(payload, "parents", default=False),
            )
        case "file.move":
            return FileMoveRequest(
                source_path=_string(payload, "source_path"),
                destination_path=_string(payload, "destination_path"),
                overwrite=_boolean(payload, "overwrite", default=False),
            )
        case "file.bulk_delete":
            return FileBulkDeleteRequest(
                paths=_string_tuple(payload, "paths"),
                recursive=_boolean(payload, "recursive", default=False),
            )
        case "file.bulk_move":
            return FileBulkMoveRequest(
                source_paths=_string_tuple(payload, "source_paths"),
                destination_directory=_string(payload, "destination_directory"),
                overwrite=_boolean(payload, "overwrite", default=False),
            )
        case "list_git_refs":
            return GitListRefsRequest(
                source_project_path=_string(payload, "source_project_path")
            )
        case "create_git_worktree":
            return GitCreateWorktreeRequest(
                source_project_path=_string(payload, "source_project_path"),
                worktree_path=_string(payload, "worktree_path"),
                branch_name=_string(payload, "branch_name"),
                starting_ref=_string(payload, "starting_ref"),
            )
        case "inspect_git_worktree":
            return GitInspectWorktreeRequest(
                source_project_path=_string(payload, "source_project_path"),
                worktree_path=_string(payload, "worktree_path"),
            )
        case "discover_managed_git_worktrees":
            return GitDiscoverManagedWorktreesRequest()
        case "remove_discovered_git_worktree":
            return GitRemoveDiscoveredWorktreeRequest(
                worktree_path=_string(payload, "worktree_path"),
                repository_anchor_path=_string(payload, "repository_anchor_path"),
                branch_name=_string(payload, "branch_name"),
                fingerprint=_string(payload, "fingerprint"),
                force=_boolean(payload, "force", default=False),
            )
        case "remove_git_worktree":
            return GitRemoveWorktreeRequest(
                source_project_path=_string(payload, "source_project_path"),
                worktree_path=_string(payload, "worktree_path"),
                branch_name=_string(payload, "branch_name"),
                force=_boolean(payload, "force", default=False),
            )
        case "delete_git_branch":
            return GitDeleteBranchRequest(
                source_project_path=_string(payload, "source_project_path"),
                branch_name=_string(payload, "branch_name"),
            )
        case "transfer.download":
            return TransferDownloadRequest(
                runtime_path=_required_string(payload, "runtime_path"),
                expected_size=_required_non_negative_integer(payload, "expected_size"),
                expected_sha256=_required_string(payload, "expected_sha256"),
                overwrite=_required_boolean(payload, "overwrite"),
            )
        case "transfer.upload":
            return TransferUploadRequest(
                runtime_path=_required_string(payload, "runtime_path"),
                expected_size=_required_non_negative_integer(payload, "expected_size"),
                expected_sha256=_optional_string(payload, "expected_sha256"),
            )
        case _:
            raise ContainedRequestError(
                f"contained operation payload is unsupported: {operation}"
            )


def _string(payload: dict[str, JsonValue], key: str) -> str:
    value = payload.get(key)
    return value if isinstance(value, str) else ""


def _required_string(payload: dict[str, JsonValue], key: str) -> str:
    value = payload.get(key)
    if not isinstance(value, str) or not value:
        raise ContainedRequestError(f"{key}_invalid")
    return value


def _optional_string(payload: dict[str, JsonValue], key: str) -> str | None:
    value = payload.get(key)
    if value is None:
        return None
    if not isinstance(value, str):
        raise ContainedRequestError(f"{key}_invalid")
    return value


def _integer(payload: dict[str, JsonValue], key: str, *, default: int) -> int:
    value = payload.get(key)
    return value if isinstance(value, int) and not isinstance(value, bool) else default


def _optional_integer(payload: dict[str, JsonValue], key: str) -> int | None:
    value = payload.get(key)
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def _positive_integer(
    payload: dict[str, JsonValue],
    key: str,
    *,
    default: int,
) -> int:
    value = payload.get(key)
    if isinstance(value, int) and not isinstance(value, bool) and value > 0:
        return value
    return default


def _required_non_negative_integer(
    payload: dict[str, JsonValue],
    key: str,
) -> int:
    value = payload.get(key)
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise ContainedRequestError(f"{key}_invalid")
    return value


def _boolean(payload: dict[str, JsonValue], key: str, *, default: bool) -> bool:
    value = payload.get(key)
    return value if isinstance(value, bool) else default


def _required_boolean(payload: dict[str, JsonValue], key: str) -> bool:
    value = payload.get(key)
    if not isinstance(value, bool):
        raise ContainedRequestError(f"{key}_invalid")
    return value


def _string_tuple(payload: dict[str, JsonValue], key: str) -> tuple[str, ...]:
    value = payload.get(key)
    if not isinstance(value, list):
        return ()
    return tuple(item for item in value if isinstance(item, str))
