"""Privacy-preserving Runner origin evidence and shared log context tests."""

import json
import logging

import grpc
import pytest
from azents_runtime_control.grpc_runner_client import RuntimeRunnerControlStreamClosed

from azents_runtime_runner.diagnostics import (
    RunnerDiagnosticReason,
    bind_extra,
    runner_exception_diagnostic,
)
from azents_runtime_runner.main import (
    StructuredLogFormatter,
    _log_control_client_close_timeout,
    _log_control_stream_closed,
)
from azents_runtime_runner.transfer import _bounded_grpc_failure_reason


def _failure_with_sensitive_cause() -> ValueError:
    """Return a raised error whose value and source literal must remain private."""
    try:
        try:
            raise RuntimeError("SIGNED_URL_SENTINEL?token=PRIVATE_TOKEN_SENTINEL")
        except RuntimeError as cause:
            raise ValueError("APPLICATION_CONTENT_SENTINEL") from cause
    except ValueError as error:
        return error


def test_safe_diagnostic_retains_origin_without_value_chain_or_source() -> None:
    """Keep original frame locations while omitting content-bearing traceback text."""
    error = _failure_with_sensitive_cause()
    diagnostic = runner_exception_diagnostic(
        error, RunnerDiagnosticReason.WEB_PROTOCOL_FAILED
    )
    assert diagnostic.error_type == "ValueError"
    assert diagnostic.frames[-1].file == "diagnostics_test.py"
    assert diagnostic.frames[-1].function == "_failure_with_sensitive_cause"
    assert diagnostic.frames[-1].line > 0
    record = logging.LogRecord(
        "runner-test",
        logging.WARNING,
        __file__,
        1,
        "Runtime Web protocol failed",
        (),
        diagnostic.exc_info,
    )
    record.__dict__.update(diagnostic.log_fields())
    rendered = StructuredLogFormatter().format(record)
    assert "SIGNED_URL_SENTINEL" not in rendered
    assert "PRIVATE_TOKEN_SENTINEL" not in rendered
    assert "APPLICATION_CONTENT_SENTINEL" not in rendered
    assert "runner_web_protocol_failed" in rendered
    assert "_failure_with_sensitive_cause" in rendered
    assert "error_frames" in json.loads(rendered)
    assert diagnostic.exc_info.traceback is None
    assert diagnostic.exc_info.exception.__cause__ is None
    assert diagnostic.exc_info.exception.__context__ is None


def test_bound_context_preserves_per_log_fields(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Merge bounded stable identity with each call's independent diagnostic fields."""
    logger = logging.getLogger("runner-bound-test")
    bound = bind_extra(logger, {"runtime_id": "runtime", "runner_id": "runner"})
    with caplog.at_level(logging.INFO, logger="runner-bound-test"):
        bound.info("First", extra={"status": "starting"})
        bound.warning("Second", extra={"reason": "retry"})
    first, second = caplog.records
    assert first.__dict__["runtime_id"] == second.__dict__["runtime_id"] == "runtime"
    assert first.__dict__["runner_id"] == second.__dict__["runner_id"] == "runner"
    assert first.__dict__["status"] == "starting"
    assert "reason" not in first.__dict__
    assert second.__dict__["reason"] == "retry"
    assert "status" not in second.__dict__


@pytest.mark.parametrize("details", ["Transfer is unavailable", "Upload failed"])
def test_known_server_failure_labels_remain_visible(details: str) -> None:
    """Preserve bounded existing server-owned operator diagnostics."""
    metadata = grpc.aio.Metadata()
    error = grpc.aio.AioRpcError(
        grpc.StatusCode.FAILED_PRECONDITION,
        metadata,
        metadata,
        details,
        None,
    )
    assert _bounded_grpc_failure_reason(error) == details


def test_arbitrary_rpc_failure_details_are_not_log_reasons() -> None:
    """Unknown RPC details must not become application- or credential-bearing logs."""
    metadata = grpc.aio.Metadata()
    error = grpc.aio.AioRpcError(
        grpc.StatusCode.FAILED_PRECONDITION,
        metadata,
        metadata,
        "https://example.invalid/object?token=PRIVATE_TOKEN_SENTINEL",
        None,
    )
    assert _bounded_grpc_failure_reason(error) == "grpc_request_failed"


def test_control_stream_closed_preserves_safe_origin(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """The reconnect warning excludes original content and source text."""
    logger = logging.getLogger("runner-stream-close-test")
    try:
        raise RuntimeRunnerControlStreamClosed("STREAM_PRIVATE_VALUE") from ValueError(
            "STREAM_PRIVATE_CAUSE"
        )
    except RuntimeRunnerControlStreamClosed as error:
        _log_control_stream_closed(logger, error)
    record = caplog.records[-1]
    rendered = StructuredLogFormatter().format(record)
    assert record.__dict__["error_type"] == "RuntimeRunnerControlStreamClosed"
    assert record.__dict__["error_frames"][-1]["function"] == (
        "test_control_stream_closed_preserves_safe_origin"
    )
    assert "runner_control_stream_failed" in rendered
    assert "STREAM_PRIVATE_VALUE" not in rendered
    assert "STREAM_PRIVATE_CAUSE" not in rendered
    assert "raise RuntimeRunnerControlStreamClosed" not in rendered
    assert record.exc_info is not None
    assert record.exc_info[2] is None


def _timeout_with_sensitive_cause() -> TimeoutError:
    """Build only synthetic timeout diagnostics, without running a client."""
    try:
        try:
            raise RuntimeError("CLOSE_PRIVATE_TOKEN_SENTINEL")
        except RuntimeError as cause:
            raise TimeoutError("CLOSE_APPLICATION_CONTENT_SENTINEL") from cause
    except TimeoutError as error:
        return error


def test_control_close_timeout_uses_the_safe_warning_boundary(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """The actual timeout warning retains origin while excluding private content."""
    logger = logging.getLogger("runner-close-test")
    bound = bind_extra(logger, {"runtime_id": "runtime", "runner_id": "runner"})
    with caplog.at_level(logging.WARNING, logger="runner-close-test"):
        _log_control_client_close_timeout(
            bound,
            _timeout_with_sensitive_cause(),
            timeout_seconds=0.25,
        )
    record = caplog.records[0]
    rendered = StructuredLogFormatter().format(record)
    assert record.__dict__["timeout_seconds"] == 0.25
    assert record.__dict__["runtime_id"] == "runtime"
    assert "_timeout_with_sensitive_cause" in rendered
    assert "runner_control_close_timed_out" in rendered
    assert "CLOSE_PRIVATE_TOKEN_SENTINEL" not in rendered
    assert "CLOSE_APPLICATION_CONTENT_SENTINEL" not in rendered
    assert record.exc_info is not None
    assert record.exc_info[2] is None
