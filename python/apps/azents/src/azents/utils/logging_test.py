"""Tests for content-safe logging helpers."""

import logging

from azents.utils.logging import (
    content_safe_exception_diagnostic,
    sanitized_exception_info,
)


def _raise_private_source() -> None:
    raise ValueError("PRIVATE_SOURCE_MARKER") from RuntimeError("PRIVATE_CAUSE")


def test_content_safe_diagnostic_excludes_source_lines_and_retains_locations() -> None:
    try:
        _raise_private_source()
    except ValueError as error:
        diagnostic = content_safe_exception_diagnostic(error, message="Safe failure")
    record = logging.LogRecord(
        name="test",
        level=logging.ERROR,
        pathname=__file__,
        lineno=1,
        msg="Safe failure",
        args=(),
        exc_info=diagnostic.exc_info,
    )
    record.__dict__.update(diagnostic.log_fields())
    formatted = logging.Formatter().format(record)
    assert "PRIVATE_SOURCE_MARKER" not in formatted
    assert "PRIVATE_CAUSE" not in formatted
    assert "raise ValueError" not in formatted
    assert diagnostic.error_type == "ValueError"
    assert diagnostic.frames[-1].function == "_raise_private_source"
    assert diagnostic.frames[-1].file == "logging_test.py"
    assert diagnostic.frames[-1].line > 0
    assert diagnostic.exc_info[2] is None


def _failure_with_untrusted_message(message: str) -> RuntimeError:
    """Create one exception whose dynamic message must not reach logs."""
    return RuntimeError(message)


def test_sanitized_exception_info_preserves_frames_without_untrusted_message() -> None:
    """Formatted traceback keeps origin frames and a static safe exception."""
    untrusted = "s3://private-bucket/private-key?endpoint=internal.example"
    try:
        raise _failure_with_untrusted_message(untrusted)
    except RuntimeError as error:
        exc_info = sanitized_exception_info(
            error,
            message="Suppressed cleanup operation failed",
        )

    record = logging.LogRecord(
        name="test",
        level=logging.WARNING,
        pathname=__file__,
        lineno=1,
        msg="Cleanup requires retry",
        args=(),
        exc_info=exc_info,
    )
    formatted = logging.Formatter().format(record)

    assert "Cleanup requires retry" in formatted
    assert "_failure_with_untrusted_message" in formatted
    assert "RuntimeError: Suppressed cleanup operation failed" in formatted
    assert untrusted not in formatted
