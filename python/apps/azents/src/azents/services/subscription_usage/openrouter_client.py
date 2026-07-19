"""OpenRouter API-key credit usage adapter."""

import dataclasses
import json
import logging
import math
from collections.abc import Mapping
from typing import Final

import httpx

from azents.core.credentials import ApiKeySecrets

from .data import (
    OpenRouterSubscriptionFinancialDetails,
    OpenRouterUsageAdapterOutcome,
    OpenRouterUsageHidden,
    OpenRouterUsageSnapshot,
    OpenRouterUsageUnavailable,
    SubscriptionUsageLimit,
    SubscriptionUsageUnavailableReason,
)

logger = logging.getLogger(__name__)

OPENROUTER_USAGE_CONTRACT_VERSION: Final = "openrouter-current-key-v1"


class _InvalidOpenRouterUsagePayload(ValueError):
    """Raised when the OpenRouter current-key response is invalid."""


@dataclasses.dataclass(frozen=True)
class _CreditLimit:
    """Validated OpenRouter per-key credit limit."""

    limit: float
    remaining: float
    reset: str | None


class OpenRouterSubscriptionUsageClient:
    """Read and normalize OpenRouter per-key credit usage."""

    def __init__(self, http_client: httpx.AsyncClient, api_base_url: str) -> None:
        """
        :param http_client: Injected HTTP client for the current-key request.
        :param api_base_url: Fixed OpenRouter API root.
        """
        self.http_client = http_client
        self.api_base_url = api_base_url.rstrip("/")

    async def read_usage(
        self,
        *,
        secrets: ApiKeySecrets,
    ) -> OpenRouterUsageAdapterOutcome:
        """Read one OpenRouter key-credit snapshot without exposing credentials."""
        try:
            response = await self.http_client.get(
                f"{self.api_base_url}/key",
                headers={"Authorization": f"Bearer {secrets.api_key}"},
            )
        except httpx.TimeoutException, httpx.TransportError:
            return OpenRouterUsageUnavailable(
                reason=SubscriptionUsageUnavailableReason.TEMPORARILY_UNAVAILABLE,
                retryable=True,
                http_status=None,
            )

        if response.status_code in {401, 403}:
            return OpenRouterUsageUnavailable(
                reason=SubscriptionUsageUnavailableReason.PERMISSION_DENIED,
                retryable=False,
                http_status=response.status_code,
            )
        if response.status_code == 429:
            return OpenRouterUsageUnavailable(
                reason=SubscriptionUsageUnavailableReason.RATE_LIMITED,
                retryable=True,
                http_status=response.status_code,
            )
        if response.status_code >= 500:
            return OpenRouterUsageUnavailable(
                reason=SubscriptionUsageUnavailableReason.TEMPORARILY_UNAVAILABLE,
                retryable=True,
                http_status=response.status_code,
            )
        if not 200 <= response.status_code < 300:
            return OpenRouterUsageUnavailable(
                reason=SubscriptionUsageUnavailableReason.UNSUPPORTED_ACCOUNT,
                retryable=False,
                http_status=response.status_code,
            )

        try:
            body = response.json()
        except json.JSONDecodeError, UnicodeDecodeError:
            return self._invalid_response(http_status=response.status_code)

        try:
            return _normalize_usage_payload(body)
        except _InvalidOpenRouterUsagePayload:
            return self._invalid_response(http_status=response.status_code)

    def _invalid_response(self, *, http_status: int) -> OpenRouterUsageUnavailable:
        """Record safe contract-drift telemetry and return a typed outcome."""
        logger.error(
            "OpenRouter key usage response is invalid.",
            extra={
                "provider": "openrouter",
                "operation": "subscription_usage_read",
                "outcome": "invalid_provider_response",
                "http_status": http_status,
                "adapter_contract_version": OPENROUTER_USAGE_CONTRACT_VERSION,
            },
        )
        return OpenRouterUsageUnavailable(
            reason=SubscriptionUsageUnavailableReason.INVALID_PROVIDER_RESPONSE,
            retryable=False,
            http_status=http_status,
        )


def _normalize_usage_payload(
    body: object,
) -> OpenRouterUsageSnapshot | OpenRouterUsageHidden:
    """Normalize the OpenRouter current-key response."""
    response = _mapping(body, "response body")
    data = _mapping(response.get("data"), "data")
    credit_limit = _credit_limit(data)
    if credit_limit is None:
        return OpenRouterUsageHidden()

    usage = _non_negative_number(data.get("usage"), "usage")
    usage_daily = _non_negative_number(data.get("usage_daily"), "usage_daily")
    usage_weekly = _non_negative_number(data.get("usage_weekly"), "usage_weekly")
    usage_monthly = _non_negative_number(data.get("usage_monthly"), "usage_monthly")
    include_byok = data.get("include_byok_in_limit")
    if not isinstance(include_byok, bool):
        raise _InvalidOpenRouterUsagePayload("include_byok_in_limit must be a boolean")

    limit = SubscriptionUsageLimit(
        id="api-key-credit",
        label=_limit_label(credit_limit.reset),
        used_percent=_used_percent(credit_limit),
        window_minutes=_window_minutes(credit_limit.reset),
        resets_at=None,
        primary=True,
    )
    financial_details = OpenRouterSubscriptionFinancialDetails(
        credit_limit=credit_limit.limit,
        credit_remaining=credit_limit.remaining,
        usage=usage,
        usage_daily=usage_daily,
        usage_weekly=usage_weekly,
        usage_monthly=usage_monthly,
        limit_reset=credit_limit.reset,
        include_byok_in_limit=include_byok,
    )
    return OpenRouterUsageSnapshot(
        plan_label=None,
        limits=(limit,),
        financial_details=financial_details,
    )


def _credit_limit(data: Mapping[str, object]) -> _CreditLimit | None:
    """Return the bounded key limit, or None for an unlimited key."""
    limit_value = data.get("limit")
    remaining_value = data.get("limit_remaining")
    if limit_value is None or remaining_value is None:
        return None
    limit = _non_negative_number(limit_value, "limit")
    remaining = _number(remaining_value, "limit_remaining")
    reset_value = data.get("limit_reset")
    reset = _optional_string(reset_value, "limit_reset")
    return _CreditLimit(limit=limit, remaining=remaining, reset=reset)


def _used_percent(credit_limit: _CreditLimit) -> float:
    """Calculate a bounded consumed percentage from limit and remaining credit."""
    if credit_limit.limit == 0:
        return 100.0
    used = credit_limit.limit - credit_limit.remaining
    return round(min(100.0, max(0.0, used / credit_limit.limit * 100.0)), 6)


def _limit_label(reset: str | None) -> str:
    """Return a stable user-facing label for the key limit window."""
    if reset is None:
        return "API key credit limit"
    labels = {
        "daily": "Daily credit limit",
        "weekly": "Weekly credit limit",
        "monthly": "Monthly credit limit",
    }
    return labels.get(reset, "API key credit limit")


def _window_minutes(reset: str | None) -> int | None:
    """Map known reset policies to approximate window lengths."""
    if reset is None:
        return None
    windows = {
        "daily": 24 * 60,
        "weekly": 7 * 24 * 60,
    }
    return windows.get(reset)


def _mapping(value: object, field: str) -> Mapping[str, object]:
    """Return a JSON object mapping or reject an invalid source shape."""
    if not isinstance(value, Mapping):
        raise _InvalidOpenRouterUsagePayload(f"{field} must be an object")
    return value


def _number(value: object, field: str) -> float:
    """Read one required finite source number."""
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise _InvalidOpenRouterUsagePayload(f"{field} must be a number")
    normalized = float(value)
    if not math.isfinite(normalized):
        raise _InvalidOpenRouterUsagePayload(f"{field} must be finite")
    return normalized


def _non_negative_number(value: object, field: str) -> float:
    """Read one required non-negative finite source number."""
    normalized = _number(value, field)
    if normalized < 0:
        raise _InvalidOpenRouterUsagePayload(f"{field} must not be negative")
    return normalized


def _optional_string(value: object, field: str) -> str | None:
    """Read one optional non-empty source string."""
    if value is None:
        return None
    if not isinstance(value, str) or not value.strip():
        raise _InvalidOpenRouterUsagePayload(f"{field} must be a non-empty string")
    return value.strip()
