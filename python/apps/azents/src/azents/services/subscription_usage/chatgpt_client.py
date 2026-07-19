"""ChatGPT subscription usage adapter."""

import datetime
import json
import logging
import math
import re
from collections.abc import Mapping
from typing import Final

import httpx

from azents.core.chatgpt_oauth import build_chatgpt_oauth_headers
from azents.core.credentials import ChatGPTOAuthConfig, ChatGPTOAuthSecrets

from .data import (
    ChatGPTSubscriptionFinancialDetails,
    ChatGPTUsageAdapterOutcome,
    ChatGPTUsageSnapshot,
    ChatGPTUsageUnauthorized,
    ChatGPTUsageUnavailable,
    SubscriptionUsageLimit,
    SubscriptionUsageUnavailableReason,
)

logger = logging.getLogger(__name__)

CHATGPT_USAGE_CONTRACT_VERSION: Final = "chatgpt-wham-usage-v1"


class _InvalidChatGPTUsagePayload(ValueError):
    """Raised when the ChatGPT usage response has an unsupported shape."""


class ChatGPTSubscriptionUsageClient:
    """Read and normalize the ChatGPT subscription usage wire contract."""

    def __init__(self, http_client: httpx.AsyncClient, usage_base_url: str) -> None:
        """
        :param http_client: Injected HTTP client for the usage request.
        :param usage_base_url: ChatGPT backend root without the runtime `/codex` path.
        """
        self.http_client = http_client
        self.usage_base_url = usage_base_url.rstrip("/")

    async def read_usage(
        self,
        *,
        secrets: ChatGPTOAuthSecrets,
        config: ChatGPTOAuthConfig,
    ) -> ChatGPTUsageAdapterOutcome:
        """Read one ChatGPT usage snapshot without exposing the wire payload."""
        account_id = config.account_id
        if account_id is None or not account_id.strip():
            return ChatGPTUsageUnavailable(
                reason=SubscriptionUsageUnavailableReason.ACCOUNT_METADATA_MISSING,
                retryable=False,
                http_status=None,
            )

        headers = build_chatgpt_oauth_headers(account_id=account_id.strip())
        headers["Authorization"] = f"Bearer {secrets.access_token}"
        try:
            response = await self.http_client.get(
                f"{self.usage_base_url}/wham/usage",
                headers=headers,
            )
        except httpx.TimeoutException:
            return ChatGPTUsageUnavailable(
                reason=SubscriptionUsageUnavailableReason.TEMPORARILY_UNAVAILABLE,
                retryable=True,
                http_status=None,
            )
        except httpx.TransportError:
            return ChatGPTUsageUnavailable(
                reason=SubscriptionUsageUnavailableReason.TEMPORARILY_UNAVAILABLE,
                retryable=True,
                http_status=None,
            )

        if response.status_code == 401:
            return ChatGPTUsageUnauthorized(http_status=response.status_code)
        if response.status_code == 403:
            return ChatGPTUsageUnavailable(
                reason=SubscriptionUsageUnavailableReason.PERMISSION_DENIED,
                retryable=False,
                http_status=response.status_code,
            )
        if response.status_code == 429:
            return ChatGPTUsageUnavailable(
                reason=SubscriptionUsageUnavailableReason.RATE_LIMITED,
                retryable=True,
                http_status=response.status_code,
            )
        if response.status_code >= 500:
            return ChatGPTUsageUnavailable(
                reason=SubscriptionUsageUnavailableReason.TEMPORARILY_UNAVAILABLE,
                retryable=True,
                http_status=response.status_code,
            )
        if response.status_code < 200 or response.status_code >= 300:
            return ChatGPTUsageUnavailable(
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
        except _InvalidChatGPTUsagePayload:
            return self._invalid_response(http_status=response.status_code)

    def _invalid_response(self, *, http_status: int) -> ChatGPTUsageUnavailable:
        """Record safe contract-drift telemetry and return its typed outcome."""
        logger.error(
            "ChatGPT subscription usage response is invalid.",
            extra={
                "provider": "chatgpt_oauth",
                "operation": "subscription_usage_read",
                "outcome": "invalid_provider_response",
                "http_status": http_status,
                "adapter_contract_version": CHATGPT_USAGE_CONTRACT_VERSION,
            },
        )
        return ChatGPTUsageUnavailable(
            reason=SubscriptionUsageUnavailableReason.INVALID_PROVIDER_RESPONSE,
            retryable=False,
            http_status=http_status,
        )


def _normalize_usage_payload(body: object) -> ChatGPTUsageSnapshot:
    """Normalize the source-backed ChatGPT usage response."""
    payload = _mapping(body, "response body")
    plan_label = _optional_string(payload.get("plan_type"), "plan_type")
    limits = _normalize_limits(payload)
    _validate_reset_credit_summary(payload)
    financial_details = _normalize_financial_details(payload)
    return ChatGPTUsageSnapshot(
        plan_label=plan_label,
        limits=tuple(limits),
        financial_details=financial_details,
    )


def _normalize_limits(payload: Mapping[str, object]) -> list[SubscriptionUsageLimit]:
    """Normalize main and additional provider rate-limit windows."""
    limits: list[SubscriptionUsageLimit] = []
    rate_limit_value = payload.get("rate_limit")
    if rate_limit_value is not None:
        rate_limit = _mapping(rate_limit_value, "rate_limit")
        primary_window = rate_limit.get("primary_window")
        if primary_window is not None:
            limits.append(
                _normalize_window(
                    primary_window,
                    identifier="primary",
                    label_fallback="Primary limit",
                    prefer_duration_label=True,
                    primary=True,
                )
            )
        secondary_window = rate_limit.get("secondary_window")
        if secondary_window is not None:
            limits.append(
                _normalize_window(
                    secondary_window,
                    identifier="secondary",
                    label_fallback="Secondary limit",
                    prefer_duration_label=True,
                    primary=True,
                )
            )

    additional_rate_limits = payload.get("additional_rate_limits")
    if additional_rate_limits is not None:
        if not isinstance(additional_rate_limits, list):
            raise _InvalidChatGPTUsagePayload("additional_rate_limits must be a list")
        for additional_rate_limit in additional_rate_limits:
            additional = _mapping(additional_rate_limit, "additional rate limit")
            limit_name = _required_string(additional.get("limit_name"), "limit_name")
            metered_feature = _required_string(
                additional.get("metered_feature"), "metered_feature"
            )
            rate_limit = _mapping(additional.get("rate_limit"), "additional rate_limit")
            identifier = _sanitize_identifier(metered_feature)
            primary_window = rate_limit.get("primary_window")
            if primary_window is not None:
                limits.append(
                    _normalize_window(
                        primary_window,
                        identifier=identifier,
                        label_fallback=limit_name,
                        prefer_duration_label=False,
                        primary=False,
                    )
                )
            secondary_window = rate_limit.get("secondary_window")
            if secondary_window is not None:
                limits.append(
                    _normalize_window(
                        secondary_window,
                        identifier=f"{identifier}-secondary",
                        label_fallback=f"{limit_name} secondary",
                        prefer_duration_label=False,
                        primary=False,
                    )
                )

    if not limits:
        raise _InvalidChatGPTUsagePayload("usage response has no rate-limit windows")
    ids = {limit.id for limit in limits}
    if len(ids) != len(limits):
        raise _InvalidChatGPTUsagePayload("rate-limit identifiers are not unique")
    return limits


def _normalize_window(
    value: object,
    *,
    identifier: str,
    label_fallback: str,
    prefer_duration_label: bool,
    primary: bool,
) -> SubscriptionUsageLimit:
    """Normalize one source rate-limit window."""
    window = _mapping(value, "rate-limit window")
    used_percent = _bounded_percentage(window.get("used_percent"), "used_percent")
    window_minutes = _window_minutes(window.get("limit_window_seconds"))
    resets_at = _reset_at(window.get("reset_at"))
    label = (
        _window_label(window_minutes, fallback=label_fallback)
        if prefer_duration_label
        else label_fallback
    )
    return SubscriptionUsageLimit(
        id=identifier,
        label=label,
        used_percent=used_percent,
        window_minutes=window_minutes,
        resets_at=resets_at,
        primary=primary,
    )


def _validate_reset_credit_summary(payload: Mapping[str, object]) -> None:
    """Validate the optional reset-credit summary without exposing it publicly."""
    value = payload.get("rate_limit_reset_credits")
    if value is None:
        return
    summary = _mapping(value, "rate_limit_reset_credits")
    available_count = summary.get("available_count")
    if isinstance(available_count, bool) or not isinstance(available_count, int):
        raise _InvalidChatGPTUsagePayload(
            "rate_limit_reset_credits.available_count must be an integer"
        )
    if available_count < 0:
        raise _InvalidChatGPTUsagePayload(
            "rate_limit_reset_credits.available_count must not be negative"
        )


def _normalize_financial_details(
    payload: Mapping[str, object],
) -> ChatGPTSubscriptionFinancialDetails | None:
    """Normalize optional ChatGPT financial values without relabeling them."""
    credits_value = payload.get("credits")
    spend_control_value = payload.get("spend_control")
    reached_type_value = payload.get("rate_limit_reached_type")
    if (
        credits_value is None
        and spend_control_value is None
        and reached_type_value is None
    ):
        return None

    credits = _mapping(credits_value, "credits") if credits_value is not None else None
    spend_control = (
        _mapping(spend_control_value, "spend_control")
        if spend_control_value is not None
        else None
    )
    reached_type = (
        _mapping(reached_type_value, "rate_limit_reached_type")
        if reached_type_value is not None
        else None
    )

    has_credits = (
        _optional_boolean(credits.get("has_credits"), "credits.has_credits")
        if credits is not None
        else None
    )
    unlimited = (
        _optional_boolean(credits.get("unlimited"), "credits.unlimited")
        if credits is not None
        else None
    )
    balance = (
        _optional_formatted_value(credits.get("balance"), "credits.balance")
        if credits is not None
        else None
    )

    spend_limit: str | None = None
    spend_used: str | None = None
    spend_remaining_percent: float | None = None
    spend_resets_at: datetime.datetime | None = None
    if spend_control is not None:
        reached = spend_control.get("reached")
        if reached is not None:
            _optional_boolean(reached, "spend_control.reached")
        individual_limit_value = spend_control.get("individual_limit")
        if individual_limit_value is not None:
            individual_limit = _mapping(
                individual_limit_value, "spend_control.individual_limit"
            )
            spend_limit = _optional_formatted_value(
                individual_limit.get("limit"), "spend_control.individual_limit.limit"
            )
            spend_used = _optional_formatted_value(
                individual_limit.get("used"), "spend_control.individual_limit.used"
            )
            remaining_percent_value = individual_limit.get("remaining_percent")
            if remaining_percent_value is not None:
                spend_remaining_percent = _bounded_percentage(
                    remaining_percent_value,
                    "spend_control.individual_limit.remaining_percent",
                )
            spend_resets_at = _reset_at(individual_limit.get("reset_at"))

    reached_type = (
        _optional_string(reached_type.get("type"), "rate_limit_reached_type.type")
        if reached_type is not None
        else None
    )
    return ChatGPTSubscriptionFinancialDetails(
        has_credits=has_credits,
        unlimited=unlimited,
        balance=balance,
        spend_limit=spend_limit,
        spend_used=spend_used,
        spend_remaining_percent=spend_remaining_percent,
        spend_resets_at=spend_resets_at,
        reached_type=reached_type,
    )


def _mapping(value: object, field: str) -> Mapping[str, object]:
    """Return a JSON object mapping or reject an invalid source shape."""
    if not isinstance(value, Mapping):
        raise _InvalidChatGPTUsagePayload(f"{field} must be an object")
    return value


def _required_string(value: object, field: str) -> str:
    """Read one required non-empty source string."""
    if not isinstance(value, str) or not value.strip():
        raise _InvalidChatGPTUsagePayload(f"{field} must be a non-empty string")
    return value


def _optional_string(value: object, field: str) -> str | None:
    """Read one optional source string."""
    if value is None:
        return None
    if not isinstance(value, str):
        raise _InvalidChatGPTUsagePayload(f"{field} must be a string")
    return value


def _optional_boolean(value: object, field: str) -> bool | None:
    """Read one optional source boolean without accepting integer aliases."""
    if value is None:
        return None
    if not isinstance(value, bool):
        raise _InvalidChatGPTUsagePayload(f"{field} must be a boolean")
    return value


def _optional_formatted_value(value: object, field: str) -> str | None:
    """Preserve provider-formatted strings and normalize finite numeric values."""
    if value is None:
        return None
    if isinstance(value, str):
        return value
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise _InvalidChatGPTUsagePayload(f"{field} must be a formatted value")
    if not math.isfinite(float(value)):
        raise _InvalidChatGPTUsagePayload(f"{field} must be finite")
    return str(value)


def _bounded_percentage(value: object, field: str) -> float:
    """Validate and clamp a source percentage for presentation."""
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise _InvalidChatGPTUsagePayload(f"{field} must be numeric")
    percentage = float(value)
    if not math.isfinite(percentage):
        raise _InvalidChatGPTUsagePayload(f"{field} must be finite")
    return min(max(percentage, 0.0), 100.0)


def _window_minutes(value: object) -> int | None:
    """Convert a valid source duration in seconds into whole minutes."""
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise _InvalidChatGPTUsagePayload("limit_window_seconds must be numeric")
    seconds = float(value)
    if not math.isfinite(seconds) or seconds <= 0:
        raise _InvalidChatGPTUsagePayload("limit_window_seconds must be positive")
    return int(seconds // 60)


def _reset_at(value: object) -> datetime.datetime | None:
    """Convert an optional Unix timestamp in seconds to aware UTC time."""
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise _InvalidChatGPTUsagePayload("reset_at must be a Unix timestamp")
    seconds = float(value)
    if not math.isfinite(seconds):
        raise _InvalidChatGPTUsagePayload("reset_at must be finite")
    try:
        return datetime.datetime.fromtimestamp(seconds, tz=datetime.UTC)
    except (OverflowError, OSError, ValueError) as exc:
        raise _InvalidChatGPTUsagePayload("reset_at is invalid") from exc


def _window_label(window_minutes: int | None, *, fallback: str) -> str:
    """Build a stable operational label from a normalized window duration."""
    if window_minutes is None:
        return fallback
    if window_minutes == 24 * 60:
        return "Daily limit"
    if window_minutes == 7 * 24 * 60:
        return "Weekly limit"
    if window_minutes > 0 and window_minutes % 60 == 0:
        hours = window_minutes // 60
        return f"{hours}-hour limit"
    return f"{window_minutes}-minute limit"


def _sanitize_identifier(value: str) -> str:
    """Return a stable public identifier derived from a provider feature name."""
    identifier = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    if not identifier:
        raise _InvalidChatGPTUsagePayload("metered_feature has no usable identifier")
    return identifier
