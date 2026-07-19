"""OpenRouter API-key credit usage adapter tests."""

import json
from collections.abc import Callable

import httpx
import pytest

from azents.core.credentials import ApiKeySecrets

from .data import (
    OpenRouterUsageAdapterOutcome,
    OpenRouterUsageHidden,
    OpenRouterUsageSnapshot,
    OpenRouterUsageUnavailable,
    SubscriptionUsageUnavailableReason,
)
from .openrouter_client import OpenRouterSubscriptionUsageClient

_BASE_URL = "https://openrouter.example.test/api/v1"


async def _read(
    handler: Callable[[httpx.Request], httpx.Response],
) -> OpenRouterUsageAdapterOutcome:
    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    adapter = OpenRouterSubscriptionUsageClient(client, _BASE_URL)
    try:
        return await adapter.read_usage(
            secrets=ApiKeySecrets(api_key="test-openrouter-key"),
        )
    finally:
        await client.aclose()


def _payload(
    *,
    limit: object = 100.0,
    remaining: object = 72.5,
) -> dict[str, object]:
    return {
        "data": {
            "label": "Azents",
            "limit": limit,
            "limit_remaining": remaining,
            "limit_reset": "monthly",
            "include_byok_in_limit": False,
            "usage": 40.0,
            "usage_daily": 1.0,
            "usage_weekly": 7.5,
            "usage_monthly": 27.5,
            "byok_usage": 0.0,
            "byok_usage_daily": 0.0,
            "byok_usage_weekly": 0.0,
            "byok_usage_monthly": 0.0,
            "is_free_tier": False,
            "is_provisioning_key": False,
        }
    }


async def test_bounded_key_normalizes_credit_limit_and_financial_details() -> None:
    """Project a bounded OpenRouter key without retaining raw key metadata."""

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/v1/key"
        assert request.headers["authorization"] == "Bearer test-openrouter-key"
        return httpx.Response(200, json=_payload())

    result = await _read(handler)

    assert isinstance(result, OpenRouterUsageSnapshot)
    assert result.plan_label is None
    assert len(result.limits) == 1
    limit = result.limits[0]
    assert limit.id == "api-key-credit"
    assert limit.label == "Monthly credit limit"
    assert limit.used_percent == 27.5
    assert limit.window_minutes is None
    assert limit.resets_at is None
    assert result.financial_details is not None
    assert result.financial_details.credit_limit == 100.0
    assert result.financial_details.credit_remaining == 72.5
    assert result.financial_details.usage_monthly == 27.5
    assert result.financial_details.include_byok_in_limit is False


@pytest.mark.parametrize(
    ("limit", "remaining"),
    [(None, None), (None, 1.0), (100.0, None)],
)
async def test_null_limit_values_produce_no_displayable_usage(
    limit: object,
    remaining: object,
) -> None:
    """Hide unlimited or incomplete key limits instead of exposing usage UI."""
    result = await _read(
        lambda _request: httpx.Response(
            200,
            json=_payload(limit=limit, remaining=remaining),
        )
    )

    assert isinstance(result, OpenRouterUsageHidden)


@pytest.mark.parametrize(
    ("status", "reason", "retryable"),
    [
        (401, SubscriptionUsageUnavailableReason.PERMISSION_DENIED, False),
        (403, SubscriptionUsageUnavailableReason.PERMISSION_DENIED, False),
        (429, SubscriptionUsageUnavailableReason.RATE_LIMITED, True),
        (500, SubscriptionUsageUnavailableReason.TEMPORARILY_UNAVAILABLE, True),
        (418, SubscriptionUsageUnavailableReason.UNSUPPORTED_ACCOUNT, False),
    ],
)
async def test_http_failures_map_to_controlled_unavailable_states(
    status: int,
    reason: SubscriptionUsageUnavailableReason,
    retryable: bool,
) -> None:
    """Map provider failures without returning provider bodies."""
    result = await _read(lambda _request: httpx.Response(status, text="secret"))

    assert isinstance(result, OpenRouterUsageUnavailable)
    assert result.reason == reason
    assert result.retryable is retryable
    assert result.http_status == status


@pytest.mark.parametrize(
    "response",
    [
        httpx.Response(200, text="not-json"),
        httpx.Response(200, json=[]),
        httpx.Response(200, json={"data": []}),
        httpx.Response(200, json=_payload(limit=-1.0)),
        httpx.Response(200, json=_payload(remaining="72.5")),
    ],
)
async def test_invalid_payloads_return_contract_failure(
    response: httpx.Response,
) -> None:
    """Reject malformed current-key payloads as contract drift."""
    result = await _read(lambda _request: response)

    assert isinstance(result, OpenRouterUsageUnavailable)
    assert result.reason == SubscriptionUsageUnavailableReason.INVALID_PROVIDER_RESPONSE
    assert result.retryable is False


async def test_transport_failure_is_retryable() -> None:
    """Keep transient network failures retryable."""

    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("offline", request=request)

    result = await _read(handler)

    assert isinstance(result, OpenRouterUsageUnavailable)
    assert result.reason == SubscriptionUsageUnavailableReason.TEMPORARILY_UNAVAILABLE
    assert result.retryable is True
    assert result.http_status is None


async def test_non_json_response_is_not_logged_with_provider_body(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Log bounded contract metadata without provider response content."""
    caplog.set_level("ERROR")

    result = await _read(
        lambda _request: httpx.Response(
            200,
            content=json.dumps("secret-provider-body").encode(),
        )
    )

    assert isinstance(result, OpenRouterUsageUnavailable)
    assert "secret-provider-body" not in caplog.text
