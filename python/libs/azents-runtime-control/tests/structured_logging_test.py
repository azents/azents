"""Tests for Runtime structured logging helpers."""

import json
import logging
import sys

from azents_runtime_control.structured_logging import StructuredLogFormatter


def test_structured_log_formatter_keeps_extra_fields() -> None:
    """Serialize structured extras alongside the static message."""
    record = logging.LogRecord(
        name="azents_runtime_control.provider",
        level=logging.INFO,
        pathname=__file__,
        lineno=1,
        msg="Runtime Provider command finished",
        args=(),
        exc_info=None,
    )
    record.__dict__.update(
        {
            "provider_id": "provider-1",
            "request_id": "request-1",
            "duration_ms": 12.5,
        }
    )

    payload = json.loads(StructuredLogFormatter().format(record))

    assert payload["message"] == "Runtime Provider command finished"
    assert payload["provider_id"] == "provider-1"
    assert payload["request_id"] == "request-1"
    assert payload["duration_ms"] == 12.5


def test_structured_log_formatter_keeps_exception_details() -> None:
    """Serialize exception details for operator diagnostics."""
    try:
        raise ValueError("invalid provider command")
    except ValueError:
        exc_info = sys.exc_info()

    record = logging.LogRecord(
        name="azents_runtime_control.provider",
        level=logging.ERROR,
        pathname=__file__,
        lineno=1,
        msg="Runtime Provider command failed",
        args=(),
        exc_info=exc_info,
    )

    payload = json.loads(StructuredLogFormatter().format(record))

    assert "ValueError: invalid provider command" in payload["exception"]
