"""Standalone contained operation helper entrypoint."""

import codecs
import re
import select
import sys
import threading
from collections.abc import Mapping
from datetime import datetime
from typing import TYPE_CHECKING, assert_never

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
from azents_runtime_runner.contained_protocol import (
    PROTOCOL_VERSION,
    FrameKind,
    JsonValue,
    read_sync_frame,
    write_sync_binary,
    write_sync_control,
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
    TransferDownloadRequest,
    TransferUploadRequest,
    decode_contained_request,
)
from azents_runtime_runner.workspace import Workspace

if TYPE_CHECKING:
    from azents_runtime_runner.contained_apply_patch import ApplyPatchFailure
    from azents_runtime_runner.contained_transfer import ContainedTransferError

_MAX_FILE_READ_BYTES = 8 * 1024 * 1024
_MAX_TEXT_READ_BYTES = 64 * 1024


def main() -> None:
    """Run one exact framed helper request."""
    request = read_sync_frame(sys.stdin.buffer)
    control = request.control
    if control is None:
        raise RuntimeError("contained helper request must be a control frame")
    if control.get("protocol_version") != PROTOCOL_VERSION:
        raise RuntimeError("contained helper protocol version is unsupported")
    operation = control.get("operation")
    workspace_path = control.get("workspace_path")
    metadata = control.get("metadata")
    if (
        not isinstance(operation, str)
        or not isinstance(workspace_path, str)
        or not isinstance(metadata, dict)
    ):
        raise RuntimeError("contained helper request shape is invalid")
    if operation == "transfer.download":
        _run_download_transfer(metadata)
        return
    body_count = (
        0 if operation == "ping" else _integer(metadata.get("body_count"), "body_count")
    )
    bodies = tuple(_read_binary() for _ in range(body_count))
    cancellation = threading.Event()
    worker = threading.Thread(
        target=_run_dispatch,
        args=(operation, workspace_path, metadata, bodies, cancellation),
        name="azents-contained-operation",
    )
    worker.start()
    cancellation_received = False
    while worker.is_alive():
        if not cancellation_received:
            readable, _, _ = select.select([sys.stdin.buffer], [], [], 0.05)
            if readable:
                _receive_cancellation(cancellation)
                cancellation_received = True
        else:
            worker.join(timeout=0.05)
    worker.join()


def _run_dispatch(
    operation: str,
    workspace_path: str,
    metadata: Mapping[str, JsonValue],
    bodies: tuple[bytes, ...],
    cancellation: threading.Event,
) -> None:
    """Run one operation and translate its bounded terminal failure."""
    try:
        _dispatch(operation, workspace_path, metadata, bodies, cancellation)
    except _FileOperationSemanticError as error:
        _emit_error(error.code, error.message)
    except ValueError as error:
        _emit_error("INVALID_PATH", str(error))
    except OSError as error:
        _emit_error("RUNNER_OPERATION_ERROR", str(error))


def _dispatch(
    operation: str,
    workspace_path: str,
    metadata: Mapping[str, JsonValue],
    bodies: tuple[bytes, ...],
    cancellation: threading.Event,
) -> None:
    if operation == "ping":
        _emit_success({"metadata": dict(metadata)})
        return
    payload = _mapping(metadata.get("payload"), "payload")
    request = decode_contained_request(operation, dict(payload))
    deadline_at = _optional_datetime(metadata.get("deadline_at"), "deadline_at")
    workspace = Workspace(workspace_path)

    if isinstance(request, GitRequest):
        # Keep one-shot helper startup bounded for non-Git native operations.
        from azents_runtime_runner.contained_git import (  # noqa: PLC0415
            run_git_operation,
        )

        run_git_operation(
            request=request,
            workspace=workspace,
            cancellation=cancellation,
            deadline_at=deadline_at,
            emit=lambda event_type, event_payload, final: _emit_event(
                event_type,
                event_payload,
                final=final,
            ),
        )
        return

    match request:
        case TransferUploadRequest():
            if deadline_at is None:
                raise RuntimeError("contained transfer deadline is required")
            _run_upload_transfer(
                request,
                cancellation=cancellation,
                deadline_at=deadline_at,
            )
        case TransferDownloadRequest():
            raise RuntimeError("download transfer must use streaming dispatch")
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
            _emit_event("file_chunk", {}, binary=data)
            _emit_success({"bytes_read": len(data)})
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
                _emit_error(
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
                _emit_error(
                    "FILE_READ_TEXT_DECODE_ERROR",
                    f"File range cannot be decoded as {request.encoding}",
                )
                return
            _emit_event("stdout", {"text": text})
            _emit_success({"bytes_read": len(data)})
        case FileWriteRequest():
            path = workspace.resolve(request.path)
            bytes_written = _write_file_bytes(
                path,
                chunks=bodies,
                cancellation=cancellation,
            )
            _emit_success({"bytes_written": bytes_written})
        case FileApplyPatchRequest():
            _apply_patch(request, bodies, cancellation, deadline_at)
        case FileEditRequest():
            try:
                path = _resolve_lexical_path(request.path, workspace=workspace)
            except ValueError as error:
                _emit_error("FILE_EDIT_INVALID_PATH", str(error))
                return
            replacements = _edit_file_text(
                path,
                old_string=request.old_string,
                new_string=request.new_string,
                replace_all=request.replace_all,
                cancellation=cancellation,
            )
            _emit_success({"replacements": replacements})
        case FileListRequest():
            entries = _list_file_entries(
                workspace.resolve(request.path),
                workspace=workspace,
                recursive=request.recursive,
                exclude_patterns=list(request.exclude_patterns),
                cancellation=cancellation,
            )
            _emit_success({"entries": entries})
        case FileGlobRequest():
            if not request.pattern:
                _emit_error("INVALID_PATTERN", "pattern is required")
                return
            entries = _glob_file_entries(
                request.pattern,
                workspace=workspace,
                exclude_patterns=list(request.exclude_patterns),
                cancellation=cancellation,
            )
            _emit_success({"matches": entries})
        case FileStatRequest():
            path = _resolve_lexical_path(request.path, workspace=workspace)
            try:
                result = _read_stat_payload(
                    path,
                    workspace=workspace,
                    cancellation=cancellation,
                )
            except FileNotFoundError:
                _emit_error("NOT_FOUND", f"No such file: {path}")
                return
            except OSError as error:
                _emit_error("STAT_FAILED", str(error))
                return
            _emit_success(result)
        case FileDeleteRequest():
            result = _delete_path(
                _resolve_lexical_path(request.path, workspace=workspace),
                workspace=workspace,
                recursive=request.recursive,
                cancellation=cancellation,
            )
            _emit_success(result)
        case FileMkdirRequest():
            result = _make_directory(
                _resolve_lexical_path(request.path, workspace=workspace),
                workspace=workspace,
                parents=request.parents,
                cancellation=cancellation,
            )
            _emit_success(result)
        case FileMoveRequest():
            result = _move_path(
                _resolve_lexical_path(request.source_path, workspace=workspace),
                _resolve_lexical_path(request.destination_path, workspace=workspace),
                workspace=workspace,
                overwrite=request.overwrite,
                cancellation=cancellation,
            )
            _emit_success(result)
        case FileBulkDeleteRequest():
            paths = [
                _resolve_lexical_path(value, workspace=workspace)
                for value in request.paths
            ]
            if not paths:
                _emit_error("INVALID_PAYLOAD", "paths is required")
                return
            result = _delete_paths(
                paths,
                workspace=workspace,
                recursive=request.recursive,
                cancellation=cancellation,
            )
            _emit_success(result)
        case FileBulkMoveRequest():
            source_paths = [
                _resolve_lexical_path(value, workspace=workspace)
                for value in request.source_paths
            ]
            if not source_paths:
                _emit_error("INVALID_PAYLOAD", "source_paths is required")
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
            _emit_success(result)
        case FileGrepRequest():
            if not request.pattern:
                _emit_error("INVALID_PAYLOAD", "pattern is required")
                return
            try:
                regex = re.compile(request.pattern)
            except re.error as error:
                _emit_error("INVALID_REGEX", str(error))
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
            _emit_success(result)
        case _ as unreachable:
            assert_never(unreachable)


def _apply_patch(
    request: FileApplyPatchRequest,
    bodies: tuple[bytes, ...],
    cancellation: threading.Event,
    deadline_at: datetime | None,
) -> None:
    # Apply-patch validation is substantial and only needed by this operation.
    from azents_runtime_runner.contained_apply_patch import (  # noqa: PLC0415
        ApplyPatchFailure,
        ApplyPatchLimits,
        execute_apply_patch,
    )

    if not request.base_path:
        _emit_patch_failure(
            ApplyPatchFailure(
                phase="preflight",
                reason="base_path_required",
                message="base_path is required",
                applied=(),
                failed=None,
                not_attempted=(),
                exact=True,
            )
        )
        return
    result = execute_apply_patch(
        base_path=request.base_path,
        patch=b"".join(bodies),
        declared_patch_bytes=request.total_bytes,
        schema_version=request.schema_version,
        cancellation=cancellation,
        deadline_at=deadline_at,
        limits=ApplyPatchLimits(),
        fault_injector=None,
    )
    if isinstance(result, ApplyPatchFailure):
        _emit_patch_failure(result)
        return
    _emit_success(result.payload())


def _run_upload_transfer(
    request: TransferUploadRequest,
    *,
    cancellation: threading.Event,
    deadline_at: datetime,
) -> None:
    # Transfer hashing and I/O support stays off the common file-operation path.
    from azents_runtime_runner.contained_transfer import (  # noqa: PLC0415
        ContainedTransferError,
        run_upload_transfer,
    )

    try:
        run_upload_transfer(
            request=request,
            cancellation=cancellation,
            deadline_at=deadline_at,
            emit=lambda event_type, event_payload, binary, final: _emit_event(
                event_type,
                event_payload,
                binary=binary,
                final=final,
            ),
        )
    except ContainedTransferError as error:
        _emit_transfer_error(error)


def _run_download_transfer(metadata: Mapping[str, JsonValue]) -> None:
    """Run input streaming on the sole protocol reader thread."""
    from azents_runtime_runner.contained_transfer import (  # noqa: PLC0415
        ContainedTransferError,
        run_download_transfer,
    )

    try:
        payload = _mapping(metadata.get("payload"), "payload")
        request = decode_contained_request("transfer.download", dict(payload))
        if not isinstance(request, TransferDownloadRequest):
            raise RuntimeError("contained download request type is invalid")
        deadline_at = _optional_datetime(metadata.get("deadline_at"), "deadline_at")
        if deadline_at is None:
            raise RuntimeError("contained transfer deadline is required")
        run_download_transfer(
            request=request,
            deadline_at=deadline_at,
            emit=lambda event_type, event_payload, binary, final: _emit_event(
                event_type,
                event_payload,
                binary=binary,
                final=final,
            ),
        )
    except ContainedTransferError as error:
        _emit_transfer_error(error)
    except OSError:
        _emit_transfer_error(
            ContainedTransferError("destination_failed", "local_io_error")
        )


def _emit_transfer_error(error: ContainedTransferError) -> None:
    _emit_event(
        "final_error",
        {
            "error_code": "TRANSFER_FAILED",
            "error_message": error.reason,
            "transfer_failure": error.failure,
        },
        final=True,
    )


def _emit_patch_failure(failure: ApplyPatchFailure) -> None:
    _emit_event(
        "final_error",
        {
            "error_code": "FILE_APPLY_PATCH_FAILED",
            "error_message": failure.message,
            "file_apply_patch": failure.detail_payload(),
        },
        final=True,
    )


def _emit_success(payload: Mapping[str, JsonValue]) -> None:
    _emit_event("final_success", payload, final=True)


def _emit_error(code: str, message: str) -> None:
    _emit_event(
        "final_error",
        {"error_code": code, "error_message": message},
        final=True,
    )


def _emit_event(
    event_type: str,
    payload: Mapping[str, JsonValue],
    *,
    binary: bytes | None = None,
    final: bool = False,
) -> None:
    write_sync_control(
        sys.stdout.buffer,
        {
            "kind": "event",
            "event_type": event_type,
            "payload": dict(payload),
            "binary_follows": binary is not None,
            "final": final,
        },
    )
    if binary is not None:
        write_sync_binary(sys.stdout.buffer, binary)


def _read_binary() -> bytes:
    frame = read_sync_frame(sys.stdin.buffer)
    if frame.kind is not FrameKind.BINARY or frame.binary is None:
        raise RuntimeError("contained helper binary request frame is invalid")
    return frame.binary


def _receive_cancellation(cancellation: threading.Event) -> None:
    """Signal cooperative kernels when the Runner sends the cancel frame."""
    try:
        frame = read_sync_frame(sys.stdin.buffer)
    except Exception:
        cancellation.set()
        return
    control = frame.control
    if (
        frame.kind is not FrameKind.CONTROL
        or control is None
        or control.get("kind") != "cancel"
    ):
        cancellation.set()
        return
    cancellation.set()


def _mapping(value: JsonValue | None, label: str) -> Mapping[str, JsonValue]:
    if not isinstance(value, dict):
        raise RuntimeError(f"contained helper {label} is invalid")
    return value


def _integer(value: JsonValue | None, label: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise RuntimeError(f"contained helper {label} is invalid")
    return value


def _optional_datetime(value: JsonValue | None, label: str) -> datetime | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise RuntimeError(f"contained helper {label} is invalid")
    try:
        return datetime.fromisoformat(value)
    except ValueError as error:
        raise RuntimeError(f"contained helper {label} is invalid") from error


if __name__ == "__main__":
    main()
