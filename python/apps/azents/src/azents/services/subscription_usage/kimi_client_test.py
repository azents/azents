"""Kimi subscription usage adapter tests."""

import datetime

import httpx

from azents.core.credentials import KimiOAuthSecrets

from .data import (
    KimiUsageSnapshot,
    KimiUsageUnauthorized,
    KimiUsageUnavailable,
    SubscriptionUsageUnavailableReason,
)
from .kimi_client import KimiSubscriptionUsageClient


def _secrets() -> KimiOAuthSecrets:
    """Build encrypted-domain credentials for adapter tests."""
    return KimiOAuthSecrets(
        access_token="access-token",
        refresh_token="refresh-token",
        expires_at=datetime.datetime.now(datetime.UTC) + datetime.timedelta(hours=1),
        device_id="device-id-123",
    )


async def test_normalizes_summary_and_detailed_limits() -> None:
    """Normalize the official CLI usage and limits response shapes."""

    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/coding/v1/usages"
        assert request.headers["Authorization"] == "Bearer access-token"
        assert request.headers["X-Msh-Platform"] == "kimi_cli"
        assert request.headers["X-Msh-Device-Id"] == "device-id-123"
        return httpx.Response(
            200,
            json={
                "plan": "Kimi Code",
                "usage": {
                    "used": 25,
                    "limit": 100,
                    "resetAt": "2026-07-20T00:00:00Z",
                },
                "limits": [
                    {
                        "name": "Five-hour limit",
                        "detail": {"remaining": 40, "limit": 100},
                        "window": {"duration": 5, "timeUnit": "HOUR"},
                    },
                    {"detail": {"used": 1, "limit": 4}},
                ],
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        outcome = await KimiSubscriptionUsageClient(
            client,
            "https://api.kimi.test/coding/v1/",
        ).read_usage(secrets=_secrets())

    assert isinstance(outcome, KimiUsageSnapshot)
    assert outcome.plan_label == "Kimi Code"
    assert len(outcome.limits) == 3
    assert outcome.limits[0].label == "Weekly limit"
    assert outcome.limits[0].used_percent == 25
    assert outcome.limits[0].primary
    assert outcome.limits[0].resets_at == datetime.datetime(
        2026, 7, 20, tzinfo=datetime.UTC
    )
    assert outcome.limits[1].label == "Five-hour limit"
    assert outcome.limits[1].used_percent == 60
    assert outcome.limits[1].window_minutes == 300
    assert not outcome.limits[1].primary
    assert outcome.limits[2].label == "Limit #2"
    assert outcome.limits[2].used_percent == 25


async def test_unauthorized_requests_one_service_refresh() -> None:
    """Return an internal marker for one forced-refresh retry."""

    async def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(401)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        outcome = await KimiSubscriptionUsageClient(
            client,
            "https://api.kimi.test/coding/v1",
        ).read_usage(secrets=_secrets())

    assert isinstance(outcome, KimiUsageUnauthorized)
    assert outcome.http_status == 401


async def test_permission_denied_is_controlled_and_not_retryable() -> None:
    """Map an account permission failure without exposing its payload."""

    async def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(403, json={"private": "provider payload"})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        outcome = await KimiSubscriptionUsageClient(
            client,
            "https://api.kimi.test/coding/v1",
        ).read_usage(secrets=_secrets())

    assert isinstance(outcome, KimiUsageUnavailable)
    assert outcome.reason == SubscriptionUsageUnavailableReason.PERMISSION_DENIED
    assert not outcome.retryable
    assert outcome.http_status == 403


async def test_rate_limit_is_retryable() -> None:
    """Map provider throttling to the normalized retryable reason."""

    async def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(429)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        outcome = await KimiSubscriptionUsageClient(
            client,
            "https://api.kimi.test/coding/v1",
        ).read_usage(secrets=_secrets())

    assert isinstance(outcome, KimiUsageUnavailable)
    assert outcome.reason == SubscriptionUsageUnavailableReason.RATE_LIMITED
    assert outcome.retryable


async def test_invalid_payload_is_controlled() -> None:
    """Reject contract drift without returning provider response data."""

    async def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"limits": []})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        outcome = await KimiSubscriptionUsageClient(
            client,
            "https://api.kimi.test/coding/v1",
        ).read_usage(secrets=_secrets())

    assert isinstance(outcome, KimiUsageUnavailable)
    assert (
        outcome.reason == SubscriptionUsageUnavailableReason.INVALID_PROVIDER_RESPONSE
    )
    assert not outcome.retryable


async def test_transport_failure_is_temporarily_unavailable() -> None:
    """Convert transport failures to a safe retryable result."""

    async def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("network unavailable", request=request)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        outcome = await KimiSubscriptionUsageClient(
            client,
            "https://api.kimi.test/coding/v1",
        ).read_usage(secrets=_secrets())

    assert isinstance(outcome, KimiUsageUnavailable)
    assert outcome.reason == SubscriptionUsageUnavailableReason.TEMPORARILY_UNAVAILABLE
    assert outcome.retryable
    assert outcome.http_status is None
