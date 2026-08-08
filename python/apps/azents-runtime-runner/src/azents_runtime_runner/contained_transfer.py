"""Contained Runtime transfer path kernels."""

import contextlib
import hashlib
import os
import secrets
import stat
import sys
import threading
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import PurePath

from azents_runtime_runner.contained_protocol import (
    FrameKind,
    JsonValue,
    read_sync_frame,
)
from azents_runtime_runner.contained_requests import (
    TransferDownloadRequest,
    TransferUploadRequest,
)

_TRANSFER_CHUNK_BYTES = 1024 * 1024
TransferEventEmitter = Callable[
    [str, Mapping[str, JsonValue], bytes | None, bool],
    None,
]


@dataclass(frozen=True)
class _FileIdentity:
    device: int
    inode: int
    size: int
    mtime_ns: int
    ctime_ns: int


class ContainedTransferError(Exception):
    """Typed helper transfer failure rendered by the protocol entrypoint."""

    def __init__(self, failure: str, reason: str) -> None:
        super().__init__(reason)
        self.failure = failure
        self.reason = reason


def run_download_transfer(
    *,
    request: TransferDownloadRequest,
    deadline_at: datetime,
    emit: TransferEventEmitter,
) -> None:
    """Stage streamed input and atomically commit the verified destination."""
    parent_fd, destination_name = _open_parent(request.runtime_path, create=True)
    stage_fd: int | None = None
    stage_name: str | None = None
    try:
        stage_fd, stage_name = _open_temporary_file(parent_fd)
        emit("transfer_ready", {}, None, False)
        offset = 0
        digest = hashlib.sha256()
        while True:
            _check_deadline(deadline_at)
            frame = read_sync_frame(sys.stdin.buffer)
            if frame.kind is FrameKind.BINARY:
                data = frame.binary
                if (
                    data is None
                    or not data
                    or offset + len(data) > request.expected_size
                ):
                    raise ContainedTransferError(
                        "integrity_failed",
                        "download_chunk_integrity_mismatch",
                    )
                _write_all(stage_fd, data)
                digest.update(data)
                offset += len(data)
                continue
            control = frame.control
            if control is not None and control.get("kind") == "cancel":
                raise ContainedTransferError("cancelled", "cancellation_requested")
            if control is None or control.get("kind") != "transfer_complete":
                raise ContainedTransferError(
                    "protocol_violation",
                    "download_completion_invalid",
                )
            actual_size = control.get("actual_size")
            actual_sha256 = control.get("sha256")
            if (
                not isinstance(actual_size, int)
                or isinstance(actual_size, bool)
                or not isinstance(actual_sha256, str)
                or offset != request.expected_size
                or actual_size != offset
                or actual_sha256 != digest.hexdigest()
                or actual_sha256 != request.expected_sha256
            ):
                raise ContainedTransferError(
                    "integrity_failed",
                    "download_manifest_mismatch",
                )
            break
        os.fsync(stage_fd)
        _check_deadline(deadline_at)
        if request.overwrite:
            os.replace(
                stage_name,
                destination_name,
                src_dir_fd=parent_fd,
                dst_dir_fd=parent_fd,
            )
            stage_name = None
        else:
            _assert_empty_destination(parent_fd, destination_name)
            os.link(
                stage_name,
                destination_name,
                src_dir_fd=parent_fd,
                dst_dir_fd=parent_fd,
                follow_symlinks=False,
            )
            os.unlink(stage_name, dir_fd=parent_fd)
            stage_name = None
        emit(
            "final_success",
            {
                "actual_size": offset,
                "sha256": digest.hexdigest(),
                "destination_committed": True,
            },
            None,
            True,
        )
    except OSError as error:
        raise ContainedTransferError("destination_failed", "local_io_error") from error
    finally:
        if stage_name is not None:
            with contextlib.suppress(FileNotFoundError):
                os.unlink(stage_name, dir_fd=parent_fd)
        if stage_fd is not None:
            os.close(stage_fd)
        os.close(parent_fd)


def run_upload_transfer(
    *,
    request: TransferUploadRequest,
    cancellation: threading.Event,
    deadline_at: datetime,
    emit: TransferEventEmitter,
) -> None:
    """Snapshot one stable source and stream only the immutable copy."""
    parent_fd, source_name = _open_parent(request.runtime_path, create=False)
    source_fd: int | None = None
    snapshot_fd: int | None = None
    snapshot_name: str | None = None
    try:
        source_fd = os.open(
            source_name,
            os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK,
            dir_fd=parent_fd,
        )
        before = _regular_identity(os.fstat(source_fd))
        if before.size != request.expected_size:
            raise ContainedTransferError(
                "integrity_failed",
                "upload_source_size_mismatch",
            )
        snapshot_fd, snapshot_name = _open_temporary_file(parent_fd)
        digest = hashlib.sha256()
        copied = 0
        while True:
            _check_stop(cancellation, deadline_at)
            chunk = os.read(source_fd, _TRANSFER_CHUNK_BYTES)
            if not chunk:
                break
            copied += len(chunk)
            if copied > request.expected_size:
                raise ContainedTransferError(
                    "integrity_failed",
                    "upload_source_exceeds_expected_size",
                )
            _write_all(snapshot_fd, chunk)
            digest.update(chunk)
        os.fsync(snapshot_fd)
        after_fd = _regular_identity(os.fstat(source_fd))
        after_path = _regular_identity(
            os.stat(source_name, dir_fd=parent_fd, follow_symlinks=False)
        )
        if (
            before != after_fd
            or before != after_path
            or copied != request.expected_size
        ):
            raise ContainedTransferError(
                "integrity_failed",
                "upload_source_changed",
            )
        actual_sha256 = digest.hexdigest()
        if (
            request.expected_sha256 is not None
            and actual_sha256 != request.expected_sha256
        ):
            raise ContainedTransferError(
                "integrity_failed",
                "upload_source_digest_mismatch",
            )
        os.lseek(snapshot_fd, 0, os.SEEK_SET)
        offset = 0
        while True:
            _check_stop(cancellation, deadline_at)
            chunk = os.read(snapshot_fd, _TRANSFER_CHUNK_BYTES)
            if not chunk:
                break
            emit("file_chunk", {"offset": offset}, chunk, False)
            offset += len(chunk)
        emit(
            "final_success",
            {
                "actual_size": offset,
                "sha256": actual_sha256,
                "destination_committed": False,
            },
            None,
            True,
        )
    except ContainedTransferError:
        raise
    except FileNotFoundError as error:
        raise ContainedTransferError(
            "integrity_failed",
            "upload_source_missing",
        ) from error
    except OSError as error:
        raise ContainedTransferError("integrity_failed", "local_io_error") from error
    finally:
        if snapshot_name is not None:
            with contextlib.suppress(FileNotFoundError):
                os.unlink(snapshot_name, dir_fd=parent_fd)
        if source_fd is not None:
            os.close(source_fd)
        if snapshot_fd is not None:
            os.close(snapshot_fd)
        os.close(parent_fd)


def _open_parent(path: str, *, create: bool) -> tuple[int, str]:
    candidate = PurePath(path)
    if (
        not candidate.is_absolute()
        or not candidate.name
        or candidate.name in {".", ".."}
    ):
        raise ContainedTransferError("protocol_violation", "runtime_path_invalid")
    parent_fd = os.open("/", os.O_RDONLY | os.O_DIRECTORY)
    try:
        for component in candidate.parts[1:-1]:
            if component in {".", ".."}:
                raise ContainedTransferError(
                    "protocol_violation",
                    "runtime_path_traversal",
                )
            try:
                next_fd = os.open(
                    component,
                    os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
                    dir_fd=parent_fd,
                )
            except FileNotFoundError:
                if not create:
                    raise
                try:
                    os.mkdir(component, 0o700, dir_fd=parent_fd)
                except FileExistsError:
                    pass
                next_fd = os.open(
                    component,
                    os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
                    dir_fd=parent_fd,
                )
            os.close(parent_fd)
            parent_fd = next_fd
        return parent_fd, candidate.name
    except BaseException:
        os.close(parent_fd)
        raise


def _assert_empty_destination(parent_fd: int, name: str) -> None:
    try:
        os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
    except FileNotFoundError:
        return
    raise ContainedTransferError(
        "destination_failed",
        "download_destination_exists",
    )


def _regular_identity(value: os.stat_result) -> _FileIdentity:
    if not stat.S_ISREG(value.st_mode):
        raise ContainedTransferError(
            "protocol_violation",
            "upload_source_not_regular",
        )
    return _FileIdentity(
        value.st_dev,
        value.st_ino,
        value.st_size,
        value.st_mtime_ns,
        value.st_ctime_ns,
    )


def _write_all(fd: int, data: bytes) -> None:
    view = memoryview(data)
    while view:
        written = os.write(fd, view)
        view = view[written:]


def _open_temporary_file(parent_fd: int) -> tuple[int, str]:
    for _ in range(16):
        name = f".azents-transfer-{secrets.token_hex(16)}"
        try:
            descriptor = os.open(
                name,
                os.O_RDWR | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                0o600,
                dir_fd=parent_fd,
            )
        except FileExistsError:
            continue
        return descriptor, name
    raise OSError("could not allocate a unique Runtime transfer staging file")


def _check_stop(cancellation: threading.Event, deadline_at: datetime) -> None:
    if cancellation.is_set():
        raise ContainedTransferError("cancelled", "cancellation_requested")
    _check_deadline(deadline_at)


def _check_deadline(deadline_at: datetime) -> None:
    if datetime.now(UTC) >= deadline_at:
        raise ContainedTransferError("deadline_exceeded", "deadline_exceeded")
