"""Standalone contained Git operation helper entrypoint."""

import threading

from azents_runtime_runner.contained_git import run_git_operation
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
    GitRequest,
    decode_contained_request,
)
from azents_runtime_runner.workspace import Workspace


def main() -> None:
    """Run one exact framed Git helper request."""
    request = read_helper_request()
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
        if not isinstance(request, GitRequest):
            raise RuntimeError("contained Git request type is invalid")
        run_git_operation(
            request=request,
            workspace=Workspace(helper_request.workspace_path),
            cancellation=cancellation,
            deadline_at=optional_datetime(
                helper_request.metadata.get("deadline_at"),
                "deadline_at",
            ),
            emit=lambda event_type, event_payload, final: emit_event(
                event_type,
                event_payload,
                final=final,
            ),
        )
    except ValueError as error:
        emit_error("INVALID_PATH", str(error))
    except OSError as error:
        emit_error("RUNNER_OPERATION_ERROR", str(error))


if __name__ == "__main__":
    main()
