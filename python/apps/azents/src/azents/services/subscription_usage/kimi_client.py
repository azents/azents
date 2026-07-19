"""Kimi subscription usage adapter."""

import datetime
import json
import logging
import math
from collections.abc import Mapping, Sequence
from typing import Final

import httpx

from azents.core.credentials import KimiOAuthSecrets
from azents.core.kimi_oauth import build_kimi_compatibility_headers

from .data import (
    KimiUsageAdapterOutcome,
    KimiUsageSnapshot,
    KimiUsageUnauthorized,
    KimiUsageUnavailable,
    SubscriptionUsageLimit,
    SubscriptionUsageUnavailableReason,
)

logger = logging.getLogger(__name__)

KIMI_USAGE_CONTRACT_VERSION: Final = "kimi-cli-1.49.0-v1"


class _InvalidKimiUsagePayload(ValueError):
    """Raised when the Kimi usage response has an unsupported shape."""


class KimiSubscriptionUsageClient:
    """Read and normalize the Kimi Code usage wire contract."""

    def __init__(self, http_client: httpx.AsyncClient, usage_base_url: str) -> None:
        """Inject the request-scoped HTTP client and provider root."""
        self.http_client = http_client
        self.usage_base_url = usage_base_url.rstrip("/")

    async def read_usage(
        self,
        *,
        secrets: KimiOAuthSecrets,
    ) -> KimiUsageAdapterOutcome:
        """Read one Kimi usage snapshot without exposing the wire payload."""
        headers = {
            **build_kimi_compatibility_headers(device_id=secrets.device_id),
            "Authorization": f"Bearer {secrets.access_token}",
            "Accept": "application/json",
        }
        try:
            response = await self.http_client.get(
                f"{self.usage_base_url}/usages",
                headers=headers,
            )
        except httpx.TimeoutException, httpx.TransportError:
            return KimiUsageUnavailable(
                reason=SubscriptionUsageUnavailableReason.TEMPORARILY_UNAVAILABLE,
                retryable=True,
                http_status=None,
            )
        if response.status_code == 401:
            return KimiUsageUnauthorized(http_status=401)
        if response.status_code == 403:
            return KimiUsageUnavailable(
                reason=SubscriptionUsageUnavailableReason.PERMISSION_DENIED,
                retryable=False,
                http_status=403,
            )
        if response.status_code == 429:
            return KimiUsageUnavailable(
                reason=SubscriptionUsageUnavailableReason.RATE_LIMITED,
                retryable=True,
                http_status=429,
            )
        if response.status_code >= 500:
            return KimiUsageUnavailable(
                reason=SubscriptionUsageUnavailableReason.TEMPORARILY_UNAVAILABLE,
                retryable=True,
                http_status=response.status_code,
            )
        if not response.is_success:
            return KimiUsageUnavailable(
                reason=SubscriptionUsageUnavailableReason.UNSUPPORTED_ACCOUNT,
                retryable=False,
                http_status=response.status_code,
            )
        try:
            body = response.json()
        except json.JSONDecodeError, UnicodeDecodeError:
            return self._invalid_response(http_status=response.status_code)
        if not isinstance(body, Mapping):
            return self._invalid_response(http_status=response.status_code)
        try:
            return _normalize_usage(body)
        except _InvalidKimiUsagePayload:
            return self._invalid_response(http_status=response.status_code)

    def _invalid_response(self, *, http_status: int) -> KimiUsageUnavailable:
        """Record safe contract-drift telemetry and return its typed outcome."""
        logger.error(
            "Kimi subscription usage response is invalid.",
            extra={
                "provider": "kimi_oauth",
                "operation": "subscription_usage_read",
                "outcome": "invalid_provider_response",
                "http_status": http_status,
                "adapter_contract_version": KIMI_USAGE_CONTRACT_VERSION,
            },
        )
        return KimiUsageUnavailable(
            reason=SubscriptionUsageUnavailableReason.INVALID_PROVIDER_RESPONSE,
            retryable=False,
            http_status=http_status,
        )


def _normalize_usage(body: Mapping[str, object]) -> KimiUsageSnapshot:
    """Normalize optional summary and detailed quota windows."""
    limits: list[SubscriptionUsageLimit] = []
    summary = body.get("usage")
    if summary is not None:
        if not isinstance(summary, Mapping):
            raise _InvalidKimiUsagePayload("usage must be an object")
        row = _normalize_row(
            summary,
            row_id="usage",
            default_label="Weekly limit",
            window=None,
            primary=True,
        )
        if row is not None:
            limits.append(row)

    raw_limits = body.get("limits")
    if raw_limits is not None:
        if not isinstance(raw_limits, Sequence) or isinstance(raw_limits, (str, bytes)):
            raise _InvalidKimiUsagePayload("limits must be a list")
        for index, item in enumerate(raw_limits):
            if not isinstance(item, Mapping):
                continue
            detail_value = item.get("detail")
            detail = detail_value if isinstance(detail_value, Mapping) else item
            window_value = item.get("window")
            window = window_value if isinstance(window_value, Mapping) else None
            row = _normalize_row(
                detail,
                row_id=f"limit-{index + 1}",
                default_label=_limit_label(item, detail, window, index),
                window=window,
                primary=not limits,
            )
            if row is not None:
                limits.append(row)
    if not limits:
        raise _InvalidKimiUsagePayload("usage response contains no quota rows")
    return KimiUsageSnapshot(
        plan_label=_optional_label(body.get("plan") or body.get("plan_name")),
        limits=tuple(limits),
        financial_details=None,
    )


def _normalize_row(
    data: Mapping[str, object],
    *,
    row_id: str,
    default_label: str,
    window: Mapping[str, object] | None,
    primary: bool,
) -> SubscriptionUsageLimit | None:
    """Normalize one quota row from used, remaining, and limit values."""
    limit = _optional_number(data.get("limit"))
    used = _optional_number(data.get("used"))
    if used is None:
        remaining = _optional_number(data.get("remaining"))
        if remaining is not None and limit is not None:
            used = limit - remaining
    if used is None and limit is None:
        return None
    if limit is None or limit <= 0 or used is None:
        raise _InvalidKimiUsagePayload("quota row must contain a positive limit")
    used_percent = min(max(used / limit * 100.0, 0.0), 100.0)
    return SubscriptionUsageLimit(
        id=row_id,
        label=_optional_label(data.get("name") or data.get("title")) or default_label,
        used_percent=used_percent,
        window_minutes=_window_minutes(data=data, window=window),
        resets_at=_reset_at(data),
        primary=primary,
    )


def _limit_label(
    item: Mapping[str, object],
    detail: Mapping[str, object],
    window: Mapping[str, object] | None,
    index: int,
) -> str:
    """Build a stable display label from provider metadata."""
    for key in ("name", "title", "scope"):
        value = _optional_label(item.get(key) or detail.get(key))
        if value is not None:
            return value
    minutes = _window_minutes(data=detail, window=window)
    if minutes is not None:
        if minutes % (24 * 60) == 0:
            return f"{minutes // (24 * 60)}d limit"
        if minutes % 60 == 0:
            return f"{minutes // 60}h limit"
        return f"{minutes}m limit"
    return f"Limit #{index + 1}"


def _window_minutes(
    *,
    data: Mapping[str, object],
    window: Mapping[str, object] | None,
) -> int | None:
    """Normalize a provider duration and time unit to minutes."""
    sources = [source for source in (window, data) if source is not None]
    duration: float | None = None
    unit = ""
    for source in sources:
        duration = _optional_number(source.get("duration"))
        unit_value = source.get("timeUnit") or source.get("time_unit")
        unit = unit_value.upper() if isinstance(unit_value, str) else ""
        if duration is not None:
            break
    if duration is None or duration <= 0:
        return None
    if "MINUTE" in unit:
        minutes = duration
    elif "HOUR" in unit:
        minutes = duration * 60
    elif "DAY" in unit:
        minutes = duration * 24 * 60
    else:
        minutes = duration / 60
    return max(int(minutes), 1)


def _reset_at(data: Mapping[str, object]) -> datetime.datetime | None:
    """Normalize absolute or relative reset metadata to UTC."""
    for key in ("reset_at", "resetAt", "reset_time", "resetTime"):
        value = data.get(key)
        if value is None:
            continue
        if not isinstance(value, str):
            raise _InvalidKimiUsagePayload("reset timestamp must be a string")
        normalized = value
        if "." in normalized and normalized.endswith("Z"):
            base, fraction = normalized[:-1].split(".", maxsplit=1)
            normalized = f"{base}.{fraction[:6]}Z"
        try:
            parsed = datetime.datetime.fromisoformat(normalized.replace("Z", "+00:00"))
        except ValueError as exc:
            raise _InvalidKimiUsagePayload("reset timestamp is invalid") from exc
        if parsed.tzinfo is None:
            raise _InvalidKimiUsagePayload("reset timestamp must include timezone")
        return parsed.astimezone(datetime.UTC)
    for key in ("reset_in", "resetIn", "ttl"):
        seconds = _optional_number(data.get(key))
        if seconds is not None and seconds > 0:
            return datetime.datetime.now(datetime.UTC) + datetime.timedelta(
                seconds=seconds
            )
    return None


def _optional_number(value: object) -> float | None:
    """Return one finite provider number without accepting booleans."""
    if value is None:
        return None
    if isinstance(value, bool):
        raise _InvalidKimiUsagePayload("quota value must be numeric")
    if not isinstance(value, int | float | str):
        raise _InvalidKimiUsagePayload("quota value must be numeric")
    try:
        parsed = float(value)
    except (ValueError, OverflowError) as exc:
        raise _InvalidKimiUsagePayload("quota value must be numeric") from exc
    if not math.isfinite(parsed):
        raise _InvalidKimiUsagePayload("quota value must be finite")
    return parsed


def _optional_label(value: object) -> str | None:
    """Return a non-empty provider label."""
    if not isinstance(value, str):
        return None
    normalized = value.strip()
    return normalized or None
