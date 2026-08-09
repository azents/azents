"""Standalone contained Runtime transfer helper entrypoint."""

import threading

from azents_runtime_runner.contained_helper_runtime import (
    ContainedHelperRequest,
    emit_error,
    emit_event,
    mapping,
    optional_datetime,
    read_helper_request,
    read_request_bodies,
    run_cancellable_dispatch,
)
from azents_runtime_runner.contained_requests import (
    TransferDownloadRequest,
    TransferUploadRequest,
    decode_contained_request,
)
from azents_runtime_runner.contained_transfer import (
    ContainedTransferError,
    run_download_transfer,
    run_upload_transfer,
)


def main() -> None:
    """Run one exact framed transfer helper request."""
    request = read_helper_request()
    if request.operation == "transfer.download":
        _run_download_transfer(request)
        return
    run_cancellable_dispatch(request, read_request_bodies(request), _run_dispatch)


def _run_dispatch(
    helper_request: ContainedHelperRequest,
    bodies: tuple[bytes, ...],
    cancellation: threading.Event,
) -> None:
    del bodies
    try:
        payload = mapping(helper_request.metadata.get("payload"), "payload")
        request = decode_contained_request(helper_request.operation, dict(payload))
        if not isinstance(request, TransferUploadRequest):
            raise RuntimeError("contained upload request type is invalid")
        deadline_at = optional_datetime(
            helper_request.metadata.get("deadline_at"),
            "deadline_at",
        )
        if deadline_at is None:
            raise RuntimeError("contained transfer deadline is required")
        run_upload_transfer(
            request=request,
            cancellation=cancellation,
            deadline_at=deadline_at,
            emit=lambda event_type, event_payload, binary, final: emit_event(
                event_type,
                event_payload,
                binary=binary,
                final=final,
            ),
        )
    except ContainedTransferError as error:
        _emit_transfer_error(error)
    except ValueError as error:
        emit_error("INVALID_PATH", str(error))
    except OSError as error:
        emit_error("RUNNER_OPERATION_ERROR", str(error))


def _run_download_transfer(helper_request: ContainedHelperRequest) -> None:
    """Run input streaming on the sole protocol reader thread."""
    try:
        payload = mapping(helper_request.metadata.get("payload"), "payload")
        request = decode_contained_request(helper_request.operation, dict(payload))
        if not isinstance(request, TransferDownloadRequest):
            raise RuntimeError("contained download request type is invalid")
        deadline_at = optional_datetime(
            helper_request.metadata.get("deadline_at"),
            "deadline_at",
        )
        if deadline_at is None:
            raise RuntimeError("contained transfer deadline is required")
        run_download_transfer(
            request=request,
            deadline_at=deadline_at,
            emit=lambda event_type, event_payload, binary, final: emit_event(
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
    emit_event(
        "final_error",
        {
            "error_code": "TRANSFER_FAILED",
            "error_message": error.reason,
            "transfer_failure": error.failure,
        },
        final=True,
    )


if __name__ == "__main__":
    main()
