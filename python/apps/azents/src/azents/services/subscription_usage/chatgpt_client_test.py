"""ChatGPT subscription usage adapter tests."""

import datetime
from collections.abc import Callable

import httpx
import pytest

from azents.core.chatgpt_oauth import ChatGPTOAuthConnectionMethod
from azents.core.credentials import ChatGPTOAuthConfig, ChatGPTOAuthSecrets

from .chatgpt_client import ChatGPTSubscriptionUsageClient
from .data import (
    ChatGPTUsageSnapshot,
    ChatGPTUsageUnauthorized,
    ChatGPTUsageUnavailable,
    SubscriptionUsageUnavailableReason,
)


def _secrets() -> ChatGPTOAuthSecrets:
    return ChatGPTOAuthSecrets(
        access_token="test-access-token",
        refresh_token="test-refresh-token",
        expires_at=datetime.datetime.now(datetime.UTC) + datetime.timedelta(hours=1),
    )


def _config(account_id: str | None = "test-account-id") -> ChatGPTOAuthConfig:
    return ChatGPTOAuthConfig(
        account_id=account_id,
        email="test@example.com",
        connection_method=ChatGPTOAuthConnectionMethod.DEVICE.value,
        status="connected",
        connected_at=datetime.datetime.now(datetime.UTC),
        last_refreshed_at=datetime.datetime.now(datetime.UTC),
    )


def _payload() -> dict[str, object]:
    return {
        "plan_type": "Pro",
        "rate_limit": {
            "primary_window": {
                "used_percent": 23.5,
                "limit_window_seconds": 5 * 60 * 60,
                "reset_at": 1_780_000_000,
            },
            "secondary_window": {
                "used_percent": 105,
                "limit_window_seconds": 7 * 24 * 60 * 60,
                "reset_at": 1_780_100_000,
            },
        },
        "credits": {
            "has_credits": True,
            "unlimited": False,
            "balance": "12.50",
        },
        "spend_control": {
            "reached": False,
            "individual_limit": {
                "limit": "20.00",
                "used": "3.00",
                "remaining_percent": -1,
                "reset_at": 1_780_200_000,
            },
        },
        "rate_limit_reached_type": {"type": "primary"},
    }


async def _read(
    handler: Callable[[httpx.Request], httpx.Response],
    *,
    config: ChatGPTOAuthConfig | None = None,
) -> object:
    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as http_client:
        client = ChatGPTSubscriptionUsageClient(
            http_client=http_client,
            usage_base_url="https://usage.example.test/backend-api",
        )
        return await client.read_usage(secrets=_secrets(), config=config or _config())


async def test_normalizes_main_windows_and_financial_details() -> None:
    """Normalize main windows, clamp percentages, and preserve financial strings."""

    def handler(request: httpx.Request) -> httpx.Response:
        assert str(request.url) == "https://usage.example.test/backend-api/wham/usage"
        assert request.headers["authorization"] == "Bearer test-access-token"
        assert request.headers["chatgpt-account-id"] == "test-account-id"
        assert request.headers["originator"] == "azents"
        assert request.headers["user-agent"].startswith("azents/")
        return httpx.Response(200, json=_payload())

    result = await _read(handler)

    assert isinstance(result, ChatGPTUsageSnapshot)
    assert result.plan_label == "Pro"
    assert [limit.id for limit in result.limits] == ["primary", "secondary"]
    assert [limit.label for limit in result.limits] == ["5-hour limit", "Weekly limit"]
    assert result.limits[0].used_percent == 23.5
    assert result.limits[1].used_percent == 100.0
    assert result.limits[0].window_minutes == 300
    assert result.limits[0].resets_at is not None
    assert result.limits[0].resets_at.tzinfo is not None
    assert result.financial_details is not None
    assert result.financial_details.balance == "12.50"
    assert result.financial_details.spend_remaining_percent == 0.0


async def test_normalizes_additional_rate_limit() -> None:
    """Normalize a provider feature identifier into a stable additional limit ID."""
    payload = _payload()
    payload["additional_rate_limits"] = [
        {
            "limit_name": "Image generation",
            "metered_feature": "image_generation.v2",
            "rate_limit": {
                "primary_window": {
                    "used_percent": 47,
                    "limit_window_seconds": 60 * 60,
                    "reset_at": 1_780_300_000,
                },
                "secondary_window": {
                    "used_percent": 12,
                    "limit_window_seconds": 24 * 60 * 60,
                    "reset_at": 1_780_400_000,
                },
            },
        }
    ]

    result = await _read(lambda _request: httpx.Response(200, json=payload))

    assert isinstance(result, ChatGPTUsageSnapshot)
    assert [limit.id for limit in result.limits[-2:]] == [
        "image-generation-v2",
        "image-generation-v2-secondary",
    ]
    assert [limit.label for limit in result.limits[-2:]] == [
        "Image generation",
        "Image generation secondary",
    ]
    assert all(limit.primary is False for limit in result.limits[-2:])


async def test_missing_optional_financial_sections_are_allowed() -> None:
    """A valid operational response does not require financial source fields."""
    payload = _payload()
    del payload["credits"]
    del payload["spend_control"]
    del payload["rate_limit_reached_type"]

    result = await _read(lambda _request: httpx.Response(200, json=payload))

    assert isinstance(result, ChatGPTUsageSnapshot)
    assert result.financial_details is None


async def test_accepts_reset_credit_summary_without_public_projection() -> None:
    """Validate reset-credit compatibility without adding it to the snapshot."""
    payload = _payload()
    payload["rate_limit_reset_credits"] = {"available_count": 3}

    result = await _read(lambda _request: httpx.Response(200, json=payload))

    assert isinstance(result, ChatGPTUsageSnapshot)
    assert not hasattr(result, "rate_limit_reset_credits")


@pytest.mark.parametrize(
    "summary",
    [
        [],
        {},
        {"available_count": True},
        {"available_count": 1.5},
        {"available_count": -1},
    ],
)
async def test_rejects_invalid_reset_credit_summary(summary: object) -> None:
    """Detect incompatible reset-credit summary shapes as provider drift."""
    payload = _payload()
    payload["rate_limit_reset_credits"] = summary

    result = await _read(lambda _request: httpx.Response(200, json=payload))

    assert isinstance(result, ChatGPTUsageUnavailable)
    assert result.reason == SubscriptionUsageUnavailableReason.INVALID_PROVIDER_RESPONSE


@pytest.mark.parametrize("account_id", [None, "", "   "])
async def test_missing_account_metadata_makes_no_http_call(
    account_id: str | None,
) -> None:
    """Missing account metadata fails before the client receives an HTTP request."""
    calls = 0

    def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(200, json=_payload())

    result = await _read(handler, config=_config(account_id=account_id))

    assert isinstance(result, ChatGPTUsageUnavailable)
    assert result.reason == SubscriptionUsageUnavailableReason.ACCOUNT_METADATA_MISSING
    assert calls == 0


@pytest.mark.parametrize(
    ("status_code", "expected_reason", "retryable"),
    [
        (403, SubscriptionUsageUnavailableReason.PERMISSION_DENIED, False),
        (429, SubscriptionUsageUnavailableReason.RATE_LIMITED, True),
        (500, SubscriptionUsageUnavailableReason.TEMPORARILY_UNAVAILABLE, True),
        (418, SubscriptionUsageUnavailableReason.UNSUPPORTED_ACCOUNT, False),
    ],
)
async def test_classifies_controlled_http_statuses(
    status_code: int,
    expected_reason: SubscriptionUsageUnavailableReason,
    retryable: bool,
) -> None:
    """Classify usage-specific HTTP failures without serializing their bodies."""
    result = await _read(
        lambda _request: httpx.Response(status_code, text="provider-private-error")
    )

    assert isinstance(result, ChatGPTUsageUnavailable)
    assert result.reason == expected_reason
    assert result.retryable is retryable
    assert result.http_status == status_code


async def test_unauthorized_is_an_internal_retry_marker() -> None:
    """Leave 401 handling to the service's one forced-refresh retry flow."""
    result = await _read(lambda _request: httpx.Response(401))

    assert isinstance(result, ChatGPTUsageUnauthorized)
    assert result.http_status == 401


@pytest.mark.parametrize(
    "error",
    [
        httpx.ReadTimeout("test timeout"),
        httpx.ConnectError("test transport failure"),
    ],
)
async def test_timeout_and_transport_failures_are_retryable(
    error: httpx.TransportError,
) -> None:
    """Classify expected transport failures as temporary availability failures."""

    def handler(_request: httpx.Request) -> httpx.Response:
        raise error

    result = await _read(handler)

    assert isinstance(result, ChatGPTUsageUnavailable)
    assert result.reason == SubscriptionUsageUnavailableReason.TEMPORARILY_UNAVAILABLE
    assert result.retryable is True
    assert result.http_status is None


@pytest.mark.parametrize(
    "body",
    [
        {"rate_limit": "not-an-object"},
        {"rate_limit": {"primary_window": {}}},
        {
            "rate_limit": {
                "primary_window": {
                    "used_percent": True,
                    "limit_window_seconds": 3600,
                }
            }
        },
        {
            "rate_limit": {
                "primary_window": {
                    "used_percent": 1,
                    "limit_window_seconds": 3600,
                    "reset_at": "invalid",
                }
            }
        },
    ],
)
async def test_rejects_malformed_success_bodies(body: dict[str, object]) -> None:
    """Reject malformed source payloads as a typed provider-contract outcome."""
    result = await _read(lambda _request: httpx.Response(200, json=body))

    assert isinstance(result, ChatGPTUsageUnavailable)
    assert result.reason == SubscriptionUsageUnavailableReason.INVALID_PROVIDER_RESPONSE
    assert result.retryable is False


async def test_rejects_non_object_and_invalid_json() -> None:
    """Reject non-object, invalid JSON, and invalid UTF-8 successful responses."""
    non_object = await _read(lambda _request: httpx.Response(200, json=[]))
    invalid_json = await _read(lambda _request: httpx.Response(200, content=b"{"))
    invalid_utf8 = await _read(lambda _request: httpx.Response(200, content=b"\xff"))
    non_finite = await _read(
        lambda _request: httpx.Response(
            200,
            content=(
                b'{"rate_limit":{"primary_window":{'
                b'"used_percent":Infinity,"limit_window_seconds":3600}}}'
            ),
        )
    )

    expected_reason = SubscriptionUsageUnavailableReason.INVALID_PROVIDER_RESPONSE
    assert isinstance(non_object, ChatGPTUsageUnavailable)
    assert non_object.reason == expected_reason
    assert isinstance(invalid_json, ChatGPTUsageUnavailable)
    assert invalid_json.reason == expected_reason
    assert isinstance(invalid_utf8, ChatGPTUsageUnavailable)
    assert invalid_utf8.reason == expected_reason
    assert isinstance(non_finite, ChatGPTUsageUnavailable)
    assert non_finite.reason == expected_reason


async def test_invalid_response_logs_no_secret_or_financial_values(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Keep credentials, account metadata, and provider values out of diagnostics."""
    payload = {
        "rate_limit": {
            "primary_window": {
                "used_percent": "provider-private-balance-123",
                "limit_window_seconds": 3600,
            }
        }
    }

    result = await _read(lambda _request: httpx.Response(200, json=payload))

    assert isinstance(result, ChatGPTUsageUnavailable)
    log_text = caplog.text
    assert "test-access-token" not in log_text
    assert "test-account-id" not in log_text
    assert "test@example.com" not in log_text
    assert "provider-private-balance-123" not in log_text
