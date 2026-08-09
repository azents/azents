"""Standalone common file-operation helper entrypoint."""

import codecs
import re
import threading
from typing import assert_never

from azents_runtime_runner.contained_helper_runtime import (
    ContainedHelperRequest,
    emit_error,
    emit_event,
    emit_success,
    mapping,
    read_helper_request,
    read_request_bodies,
    run_cancellable_dispatch,
)
from azents_runtime_runner.contained_kernels import (
    _delete_path,
    _delete_paths,
    _edit_file_text,
    _FileOperationSemanticError,
    _glob_file_entries,
    _grep_files,
    _list_file_entries,
    _make_directory,
    _move_path,
    _move_paths,
    _read_file_bytes,
    _read_file_range_bytes,
    _read_stat_payload,
    _resolve_lexical_path,
    _write_file_bytes,
)
from azents_runtime_runner.contained_requests import (
    FileApplyPatchRequest,
    FileBulkDeleteRequest,
    FileBulkMoveRequest,
    FileDeleteRequest,
    FileEditRequest,
    FileGlobRequest,
    FileGrepRequest,
    FileListRequest,
    FileMkdirRequest,
    FileMoveRequest,
    FileReadRequest,
    FileReadTextRequest,
    FileStatRequest,
    FileWriteRequest,
    GitRequest,
    TransferRequest,
    decode_contained_request,
)
from azents_runtime_runner.workspace import Workspace

_MAX_FILE_READ_BYTES = 8 * 1024 * 1024
_MAX_TEXT_READ_BYTES = 64 * 1024


def main() -> None:
    """Run one exact framed common file helper request."""
    request = read_helper_request()
    run_cancellable_dispatch(request, read_request_bodies(request), _run_dispatch)


def _run_dispatch(
    helper_request: ContainedHelperRequest,
    bodies: tuple[bytes, ...],
    cancellation: threading.Event,
) -> None:
    """Run one operation and translate its bounded terminal failure."""
    try:
        _dispatch(helper_request, bodies, cancellation)
    except _FileOperationSemanticError as error:
        emit_error(error.code, error.message)
    except ValueError as error:
        emit_error("INVALID_PATH", str(error))
    except OSError as error:
        emit_error("RUNNER_OPERATION_ERROR", str(error))


def _dispatch(
    helper_request: ContainedHelperRequest,
    bodies: tuple[bytes, ...],
    cancellation: threading.Event,
) -> None:
    operation = helper_request.operation
    metadata = helper_request.metadata
    if operation == "ping":
        emit_success({"metadata": dict(metadata)})
        return
    payload = mapping(metadata.get("payload"), "payload")
    request = decode_contained_request(operation, dict(payload))
    if isinstance(request, FileApplyPatchRequest | GitRequest | TransferRequest):
        raise RuntimeError("contained operation was routed to the wrong helper")
    workspace = Workspace(helper_request.workspace_path)

    match request:
        case FileReadRequest():
            path = workspace.resolve(request.path)
            max_bytes = (
                request.max_bytes
                if request.max_bytes is not None
                else _MAX_FILE_READ_BYTES
            )
            data = _read_file_bytes(
                path,
                offset=request.offset,
                max_bytes=max_bytes,
                cancellation=cancellation,
            )
            emit_event("file_chunk", {}, binary=data)
            emit_success({"bytes_read": len(data)})
        case FileReadTextRequest():
            path = workspace.resolve(request.path)
            max_bytes = min(
                request.max_bytes
                if request.max_bytes is not None
                else _MAX_TEXT_READ_BYTES,
                _MAX_TEXT_READ_BYTES,
            )
            try:
                codecs.lookup(request.encoding)
            except LookupError:
                emit_error(
                    "FILE_READ_TEXT_UNSUPPORTED_ENCODING",
                    f"Unsupported text encoding: {request.encoding}",
                )
                return
            data = _read_file_range_bytes(
                path,
                offset=request.offset,
                max_bytes=max_bytes,
                cancellation=cancellation,
            )
            try:
                text = data.decode(request.encoding)
            except UnicodeDecodeError:
                emit_error(
                    "FILE_READ_TEXT_DECODE_ERROR",
                    f"File range cannot be decoded as {request.encoding}",
                )
                return
            emit_event("stdout", {"text": text})
            emit_success({"bytes_read": len(data)})
        case FileWriteRequest():
            path = workspace.resolve(request.path)
            bytes_written = _write_file_bytes(
                path,
                chunks=bodies,
                cancellation=cancellation,
            )
            emit_success({"bytes_written": bytes_written})
        case FileEditRequest():
            try:
                path = _resolve_lexical_path(request.path, workspace=workspace)
            except ValueError as error:
                emit_error("FILE_EDIT_INVALID_PATH", str(error))
                return
            replacements = _edit_file_text(
                path,
                old_string=request.old_string,
                new_string=request.new_string,
                replace_all=request.replace_all,
                cancellation=cancellation,
            )
            emit_success({"replacements": replacements})
        case FileListRequest():
            entries = _list_file_entries(
                workspace.resolve(request.path),
                workspace=workspace,
                recursive=request.recursive,
                exclude_patterns=list(request.exclude_patterns),
                cancellation=cancellation,
            )
            emit_success({"entries": entries})
        case FileGlobRequest():
            if not request.pattern:
                emit_error("INVALID_PATTERN", "pattern is required")
                return
            entries = _glob_file_entries(
                request.pattern,
                workspace=workspace,
                exclude_patterns=list(request.exclude_patterns),
                cancellation=cancellation,
            )
            emit_success({"matches": entries})
        case FileStatRequest():
            path = _resolve_lexical_path(request.path, workspace=workspace)
            try:
                result = _read_stat_payload(
                    path,
                    workspace=workspace,
                    cancellation=cancellation,
                )
            except FileNotFoundError:
                emit_error("NOT_FOUND", f"No such file: {path}")
                return
            except OSError as error:
                emit_error("STAT_FAILED", str(error))
                return
            emit_success(result)
        case FileDeleteRequest():
            result = _delete_path(
                _resolve_lexical_path(request.path, workspace=workspace),
                workspace=workspace,
                recursive=request.recursive,
                cancellation=cancellation,
            )
            emit_success(result)
        case FileMkdirRequest():
            result = _make_directory(
                _resolve_lexical_path(request.path, workspace=workspace),
                workspace=workspace,
                parents=request.parents,
                cancellation=cancellation,
            )
            emit_success(result)
        case FileMoveRequest():
            result = _move_path(
                _resolve_lexical_path(request.source_path, workspace=workspace),
                _resolve_lexical_path(request.destination_path, workspace=workspace),
                workspace=workspace,
                overwrite=request.overwrite,
                cancellation=cancellation,
            )
            emit_success(result)
        case FileBulkDeleteRequest():
            paths = [
                _resolve_lexical_path(value, workspace=workspace)
                for value in request.paths
            ]
            if not paths:
                emit_error("INVALID_PAYLOAD", "paths is required")
                return
            result = _delete_paths(
                paths,
                workspace=workspace,
                recursive=request.recursive,
                cancellation=cancellation,
            )
            emit_success(result)
        case FileBulkMoveRequest():
            source_paths = [
                _resolve_lexical_path(value, workspace=workspace)
                for value in request.source_paths
            ]
            if not source_paths:
                emit_error("INVALID_PAYLOAD", "source_paths is required")
                return
            result = _move_paths(
                source_paths,
                _resolve_lexical_path(
                    request.destination_directory,
                    workspace=workspace,
                ),
                workspace=workspace,
                overwrite=request.overwrite,
                cancellation=cancellation,
            )
            emit_success(result)
        case FileGrepRequest():
            if not request.pattern:
                emit_error("INVALID_PAYLOAD", "pattern is required")
                return
            try:
                regex = re.compile(request.pattern)
            except re.error as error:
                emit_error("INVALID_REGEX", str(error))
                return
            result = _grep_files(
                workspace.resolve(request.path),
                workspace=workspace,
                regex=regex,
                recursive=request.recursive,
                exclude_patterns=list(request.exclude_patterns),
                max_matching_files=request.max_matching_files,
                max_lines_per_file=request.max_lines_per_file,
                max_searched_files=request.max_searched_files,
                max_scanned_bytes=request.max_scanned_bytes,
                cancellation=cancellation,
            )
            emit_success(result)
        case _ as unreachable:
            assert_never(unreachable)


if __name__ == "__main__":
    main()
