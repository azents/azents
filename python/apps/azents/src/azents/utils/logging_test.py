"""Tests for content-safe logging helpers."""

import logging

from azents.utils.logging import sanitized_exception_info


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
