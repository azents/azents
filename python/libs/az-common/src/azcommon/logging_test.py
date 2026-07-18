"""Structured logging integration tests."""

from typing import TYPE_CHECKING, cast

from azcommon.logging import apply_structured_sentry_fingerprint

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
