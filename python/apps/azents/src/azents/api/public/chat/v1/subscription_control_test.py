"""Consumed WebSocket control projection preserves the current wire policy."""

import pytest

from . import _decode_subscription_health_check, _SubscriptionHealthCheck


@pytest.mark.parametrize(
    "value", [None, False, 1, "control", [], {}, {"type": "unknown"}]
)
def test_unknown_controls_remain_ignored(value: object) -> None:
    assert _decode_subscription_health_check(value) is None


@pytest.mark.parametrize("request_id", [None, False, 0, [], {}, "", "request-1"])
def test_health_control_projects_only_the_optional_string_id(
    request_id: object,
) -> None:
    message = {
        "type": "subscription_health_check",
        "request_id": request_id,
        "extension": {"opaque": [1, None]},
    }
    expected = request_id if isinstance(request_id, str) else None
    assert _decode_subscription_health_check(message) == _SubscriptionHealthCheck(
        expected
    )
    assert message["request_id"] is request_id
    assert message["extension"] == {"opaque": [1, None]}


def test_missing_request_id_remains_explicit_null_in_the_projection() -> None:
    assert _decode_subscription_health_check({"type": "subscription_health_check"}) == (
        _SubscriptionHealthCheck(None)
    )
