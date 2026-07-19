"""Structured logging integration tests."""

import logging
from typing import TYPE_CHECKING, cast

from azcommon.logging import (
    SensitiveQueryParameterFilter,
    apply_structured_sentry_fingerprint,
)

if TYPE_CHECKING:
    from sentry_sdk._types import Event


def test_applies_provider_failure_fingerprint_with_release() -> None:
    """Provider fingerprint and release define one Sentry incident group."""
    event = cast(
        "Event",
        {
            "extra": {"provider_failure_fingerprint": "fingerprint-001"},
            "release": "azents@2026.07.17",
        },
    )

    result = apply_structured_sentry_fingerprint(event, {})

    assert result.get("fingerprint") == [
        "model-provider-failure",
        "fingerprint-001",
        "azents@2026.07.17",
    ]


def test_ignores_events_without_approved_fingerprint() -> None:
    """Unrelated logging events retain normal Sentry grouping."""
    event = cast("Event", {"extra": {"request_id": "request-001"}})

    result = apply_structured_sentry_fingerprint(event, {})

    assert "fingerprint" not in result


def test_redacts_ticket_from_uvicorn_access_log_arguments() -> None:
    """Access log paths retain safe query parameters but redact tickets."""
    record = logging.LogRecord(
        name="uvicorn.access",
        level=logging.INFO,
        pathname=__file__,
        lineno=1,
        msg='%s - "%s %s HTTP/%s" %d',
        args=(
            "127.0.0.1:12345",
            "GET",
            "/chat/sessions/session-1?ticket=secret-ticket&view=live",
            "1.1",
            101,
        ),
        exc_info=None,
    )

    SensitiveQueryParameterFilter().filter(record)

    assert (
        record.getMessage() == '127.0.0.1:12345 - "GET '
        '/chat/sessions/session-1?ticket=<redacted>&view=live HTTP/1.1" 101'
    )


def test_redacts_ticket_from_uvicorn_websocket_log_arguments() -> None:
    """WebSocket lifecycle logs do not expose the authentication ticket."""
    record = logging.LogRecord(
        name="uvicorn.error",
        level=logging.INFO,
        pathname=__file__,
        lineno=1,
        msg='%s - "WebSocket %s" [accepted]',
        args=(
            "127.0.0.1:12345",
            "/chat/sessions/session-1?locale=ko&ticket=secret-ticket",
        ),
        exc_info=None,
    )

    SensitiveQueryParameterFilter().filter(record)

    assert (
        record.getMessage() == '127.0.0.1:12345 - "WebSocket '
        '/chat/sessions/session-1?locale=ko&ticket=<redacted>" [accepted]'
    )
