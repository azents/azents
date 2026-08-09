"""Standalone contained apply-patch operation helper entrypoint."""

import threading

from azents_runtime_runner.contained_apply_patch import (
    ApplyPatchFailure,
    ApplyPatchLimits,
    execute_apply_patch,
)
from azents_runtime_runner.contained_helper_runtime import (
    ContainedHelperRequest,
    emit_error,
    emit_event,
    emit_success,
    mapping,
    optional_datetime,
    read_helper_request,
    read_request_bodies,
    run_cancellable_dispatch,
)
from azents_runtime_runner.contained_requests import (
    FileApplyPatchRequest,
    decode_contained_request,
)


def main() -> None:
    """Run one exact framed apply-patch helper request."""
    request = read_helper_request()
    run_cancellable_dispatch(request, read_request_bodies(request), _run_dispatch)


def _run_dispatch(
    helper_request: ContainedHelperRequest,
    bodies: tuple[bytes, ...],
    cancellation: threading.Event,
) -> None:
    try:
        payload = mapping(helper_request.metadata.get("payload"), "payload")
        request = decode_contained_request(helper_request.operation, dict(payload))
        if not isinstance(request, FileApplyPatchRequest):
            raise RuntimeError("contained apply-patch request type is invalid")
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
            deadline_at=optional_datetime(
                helper_request.metadata.get("deadline_at"),
                "deadline_at",
            ),
            limits=ApplyPatchLimits(),
            fault_injector=None,
        )
        if isinstance(result, ApplyPatchFailure):
            _emit_patch_failure(result)
            return
        emit_success(result.payload())
    except ValueError as error:
        emit_error("INVALID_PATH", str(error))
    except OSError as error:
        emit_error("RUNNER_OPERATION_ERROR", str(error))


def _emit_patch_failure(failure: ApplyPatchFailure) -> None:
    emit_event(
        "final_error",
        {
            "error_code": "FILE_APPLY_PATCH_FAILED",
            "error_message": failure.message,
            "file_apply_patch": failure.detail_payload(),
        },
        final=True,
    )


if __name__ == "__main__":
    main()
