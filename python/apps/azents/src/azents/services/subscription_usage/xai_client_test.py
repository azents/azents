"""xAI subscription usage adapter tests."""

import datetime
import json
import logging
from collections.abc import Callable

import httpx
import pytest

from azents.core.credentials import XaiOAuthConfig, XaiOAuthSecrets
from azents.core.xai_oauth import XaiOAuthConnectionMethod, XaiOAuthConnectionStatus

from .data import (
    SubscriptionUsageUnavailableReason,
    XaiUsageAdapterOutcome,
    XaiUsageExternal,
    XaiUsageSnapshot,
    XaiUsageUnauthorized,
    XaiUsageUnavailable,
)
from .xai_client import XAI_USAGE_CONTRACT_VERSION, XaiSubscriptionUsageClient

_BASE_URL = "https://usage.example.test/v1"


def _secrets() -> XaiOAuthSecrets:
    return XaiOAuthSecrets(
        access_token="secret-access-token",
        refresh_token="secret-refresh-token",
        expires_at=datetime.datetime.now(datetime.UTC) + datetime.timedelta(hours=1),
    )


def _config(*, account_id: str | None = "account-secret") -> XaiOAuthConfig:
    return XaiOAuthConfig(
        account_id=account_id,
        email="private@example.com",
        connection_method=XaiOAuthConnectionMethod.DEVICE.value,
        status=XaiOAuthConnectionStatus.CONNECTED.value,
    )


def _billing_payload(
    *,
    percentage: object = 42.5,
    prepaid: object = 1250,
    period_type: str = "USAGE_PERIOD_TYPE_WEEKLY",
) -> dict[str, object]:
    return {
        "config": {
            "creditUsagePercent": percentage,
            "currentPeriod": {
                "type": period_type,
                "start": "2026-07-13T00:00:00Z",
                "end": "2026-07-20T00:00:00Z",
            },
            "onDemandCap": {"val": 5000},
            "onDemandUsed": {"val": 300},
            "prepaidBalance": {"val": prepaid},
            "isUnifiedBillingUser": True,
        },
        "onDemandEnabled": True,
        "subscriptionTier": "Billing tier",
    }


async def _read(
    handler: Callable[[httpx.Request], httpx.Response],
    *,
    account_id: str | None = "account-secret",
) -> XaiUsageAdapterOutcome:
    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    adapter = XaiSubscriptionUsageClient(client, _BASE_URL)
    try:
        return await adapter.read_usage(
            secrets=_secrets(),
            config=_config(account_id=account_id),
        )
    finally:
        await client.aclose()


async def test_settings_billing_and_auto_top_up_normalize_with_pinned_identity() -> (
    None
):
    """Read the source-backed sequence with exact compatible request identity."""
    paths: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        paths.append(request.url.path)
        assert request.headers["authorization"] == "Bearer secret-access-token"
        assert request.headers["x-xai-token-auth"] == "xai-grok-cli"
        assert request.headers["x-userid"] == "account-secret"
        assert request.headers["x-grok-client-version"] == "0.2.105"
        assert request.headers["x-grok-client-identifier"] == "grok-shell"
        assert request.headers["x-grok-client-mode"] == "interactive"
        assert "x-email" not in request.headers
        if request.url.path == "/v1/settings":
            return httpx.Response(
                200,
                json={
                    "subscription_tier": "raw-tier",
                    "subscription_tier_display": "Display tier",
                    "on_demand_enabled": True,
                },
            )
        if request.url.path == "/v1/billing":
            assert request.url.query == b"format=credits"
            return httpx.Response(200, json=_billing_payload())
        assert request.url.path == "/v1/auto-topup-rule"
        return httpx.Response(
            200,
            json={
                "rule": {
                    "enabled": True,
                    "topupAmount": {"val": 500},
                    "maxAmountPerMonth": {"val": 2000},
                    "minBeforeHittingSl": {},
                }
            },
        )

    result = await _read(handler)

    assert isinstance(result, XaiUsageSnapshot)
    assert paths == ["/v1/settings", "/v1/billing", "/v1/auto-topup-rule"]
    assert result.plan_label == "Display tier"
    assert result.limits[0].label == "Weekly limit"
    assert result.limits[0].used_percent == 42.5
    assert result.limits[0].window_minutes == 7 * 24 * 60
    assert result.limits[0].resets_at == datetime.datetime(
        2026, 7, 20, tzinfo=datetime.UTC
    )
    assert result.financial_details is not None
    assert result.financial_details.prepaid_balance_cents == 1250
    assert result.financial_details.payg_cap_cents == 5000
    assert result.financial_details.payg_used_cents == 300
    assert result.financial_details.auto_top_up_enabled is True
    assert result.financial_details.auto_top_up_amount_cents == 500
    assert result.financial_details.auto_top_up_monthly_maximum_cents == 2000


@pytest.mark.parametrize("account_id", [None, "", "   "])
async def test_missing_account_metadata_makes_zero_provider_calls(
    account_id: str | None,
) -> None:
    """Do not issue ambiguous xAI requests without a usable account id."""
    calls = 0

    def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(500)

    result = await _read(handler, account_id=account_id)

    assert isinstance(result, XaiUsageUnavailable)
    assert result.reason == SubscriptionUsageUnavailableReason.ACCOUNT_METADATA_MISSING
    assert calls == 0


@pytest.mark.parametrize(
    "url",
    [
        "https://x.ai/usage",
        "https://billing.x.ai/usage",
        "https://grok.com/usage",
        "https://account.grok.com/usage?source=grok",
    ],
)
async def test_trusted_redirect_short_circuits_billing(url: str) -> None:
    """Return only validated provider-managed usage locations."""
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        assert request.url.path == "/v1/settings"
        return httpx.Response(200, json={"usage_billing_redirect_url": url})

    result = await _read(handler)

    assert isinstance(result, XaiUsageExternal)
    assert result.url == url
    assert calls == 1


@pytest.mark.parametrize(
    "url",
    [
        "http://x.ai/usage",
        "https://user:password@x.ai/usage",
        "https://evilx.ai/usage",
        "https://x.ai.evil.example/usage",
        "https://grok.com.evil.example/usage",
        "https://x.ai./usage",
        "https://127.0.0.1/usage",
        "//x.ai/usage",
        "/usage",
    ],
)
async def test_untrusted_redirect_is_invalid_and_skips_billing(url: str) -> None:
    """Reject lookalike or non-HTTPS redirects without provider fallback."""
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        assert request.url.path == "/v1/settings"
        return httpx.Response(200, json={"usage_billing_redirect_url": url})

    result = await _read(handler)

    assert isinstance(result, XaiUsageUnavailable)
    assert result.reason == SubscriptionUsageUnavailableReason.INVALID_PROVIDER_RESPONSE
    assert calls == 1


@pytest.mark.parametrize(
    "settings_response", [httpx.Response(503), httpx.Response(200, text="not-json")]
)
async def test_settings_failure_is_best_effort(
    settings_response: httpx.Response,
) -> None:
    """Continue to required billing when optional settings are unavailable."""
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        if request.url.path == "/v1/settings":
            return settings_response
        assert request.url.path == "/v1/billing"
        return httpx.Response(200, json=_billing_payload(prepaid=0))

    result = await _read(handler)

    assert isinstance(result, XaiUsageSnapshot)
    assert result.plan_label == "Billing tier"
    assert calls == 2


async def test_legacy_usage_percentage_and_reset_fallback() -> None:
    """Support the legacy monthly billing shape when credits fields are absent."""

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/v1/settings":
            return httpx.Response(200, json={})
        return httpx.Response(
            200,
            json={
                "config": {
                    "monthlyLimit": {"val": 2000},
                    "used": {"val": 1000},
                    "billingPeriodStart": "2026-07-01T00:00:00Z",
                    "billingPeriodEnd": "2026-08-01T00:00:00Z",
                    "prepaidBalance": {},
                }
            },
        )

    result = await _read(handler)

    assert isinstance(result, XaiUsageSnapshot)
    assert result.limits[0].used_percent == 50.0
    assert result.limits[0].label == "Subscription limit"
    assert result.financial_details is not None
    assert result.financial_details.prepaid_balance_cents == 0


@pytest.mark.parametrize(
    ("status", "outcome_type", "reason", "retryable"),
    [
        (401, XaiUsageUnauthorized, None, None),
        (
            403,
            XaiUsageUnavailable,
            SubscriptionUsageUnavailableReason.ENTITLEMENT_UNAVAILABLE,
            False,
        ),
        (
            429,
            XaiUsageUnavailable,
            SubscriptionUsageUnavailableReason.RATE_LIMITED,
            True,
        ),
        (
            503,
            XaiUsageUnavailable,
            SubscriptionUsageUnavailableReason.TEMPORARILY_UNAVAILABLE,
            True,
        ),
        (
            404,
            XaiUsageUnavailable,
            SubscriptionUsageUnavailableReason.UNSUPPORTED_ACCOUNT,
            False,
        ),
    ],
)
async def test_required_billing_status_classification(
    status: int,
    outcome_type: type[XaiUsageUnauthorized] | type[XaiUsageUnavailable],
    reason: SubscriptionUsageUnavailableReason | None,
    retryable: bool | None,
) -> None:
    """Classify required billing failures without provider-authored detail."""

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/v1/settings":
            return httpx.Response(200, json={})
        return httpx.Response(status, json={"error": "private provider detail"})

    result = await _read(handler)

    assert isinstance(result, outcome_type)
    if isinstance(result, XaiUsageUnavailable):
        assert result.reason == reason
        assert result.retryable is retryable


@pytest.mark.parametrize("percentage", [-4, 125])
async def test_percentage_is_clamped_for_presentation(percentage: int) -> None:
    """Clamp finite provider percentages into the public presentation range."""

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/v1/settings":
            return httpx.Response(200, json={})
        return httpx.Response(
            200, json=_billing_payload(percentage=percentage, prepaid=0)
        )

    result = await _read(handler)

    assert isinstance(result, XaiUsageSnapshot)
    assert result.limits[0].used_percent == min(max(float(percentage), 0.0), 100.0)


@pytest.mark.parametrize(
    "percentage", [True, "50", float("nan"), float("inf"), 10**400]
)
async def test_invalid_percentage_is_controlled_contract_drift(
    percentage: object,
) -> None:
    """Reject booleans, strings, and non-finite provider percentages."""

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/v1/settings":
            return httpx.Response(200, json={})
        payload = _billing_payload(percentage=percentage, prepaid=0)
        return httpx.Response(
            200,
            content=json.dumps(payload).encode(),
            headers={"content-type": "application/json"},
        )

    result = await _read(handler)

    assert isinstance(result, XaiUsageUnavailable)
    assert result.reason == SubscriptionUsageUnavailableReason.INVALID_PROVIDER_RESPONSE


@pytest.mark.parametrize(
    "auto_response",
    [
        httpx.Response(401),
        httpx.Response(503),
        httpx.Response(200, text="not-json"),
        httpx.Response(200, json={"rule": {"enabled": "yes"}}),
    ],
)
async def test_auto_top_up_failure_preserves_available_billing(
    auto_response: httpx.Response,
) -> None:
    """Omit optional enrichment rather than failing the usage snapshot."""

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/v1/settings":
            return httpx.Response(200, json={})
        if request.url.path == "/v1/billing":
            return httpx.Response(200, json=_billing_payload())
        return auto_response

    result = await _read(handler)

    assert isinstance(result, XaiUsageSnapshot)
    assert result.financial_details is not None
    assert result.financial_details.prepaid_balance_cents == 1250
    assert result.financial_details.auto_top_up_enabled is None
    assert result.financial_details.auto_top_up_amount_cents is None


async def test_safe_logs_exclude_provider_and_financial_values(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Keep credentials, metadata, redirects, payloads, and money out of logs."""
    caplog.set_level(logging.INFO)
    rejected_url = "https://user:password@x.ai/usage?account=account-secret"

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"usage_billing_redirect_url": rejected_url})

    result = await _read(handler)

    assert isinstance(result, XaiUsageUnavailable)
    rendered = "\n".join(record.getMessage() for record in caplog.records)
    assert XAI_USAGE_CONTRACT_VERSION not in rendered
    for secret in [
        "secret-access-token",
        "secret-refresh-token",
        "account-secret",
        "private@example.com",
        rejected_url,
        "1250",
    ]:
        assert secret not in rendered
