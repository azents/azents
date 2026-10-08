"""Retained Discord delivery labels preserve request-fallback compatibility."""

import pytest

from azents.repos.external_channel.mailbox_ingestion import (
    _RetainedDiscordDeliveryLocator,
)


@pytest.mark.parametrize(
    ("labels", "expected"),
    [
        (None, None),
        ({}, None),
        ({"delivery_channel_id": None}, None),
        ({"delivery_channel_id": ""}, None),
        ({"delivery_channel_id": 123}, None),
        ({"delivery_channel_id": False}, None),
        ({"delivery_channel_id": []}, None),
        ({"delivery_channel_id": "   "}, "   "),
        ({"delivery_channel_id": "thread", "opaque": {"future": 1}}, "thread"),
    ],
)
def test_retained_delivery_locator_keeps_only_historical_nonempty_strings(
    labels: dict[str, object] | None,
    expected: str | None,
) -> None:
    restored = _RetainedDiscordDeliveryLocator.from_labels(labels)
    assert restored.delivery_channel_id == expected
    assert (restored.delivery_channel_id or "request-thread") == (
        expected or "request-thread"
    )
