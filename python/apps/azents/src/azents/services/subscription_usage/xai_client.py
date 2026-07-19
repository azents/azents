"""xAI subscription usage adapter."""

import dataclasses
import datetime
import ipaddress
import json
import logging
import math
from collections.abc import Mapping
from typing import Final, assert_never
from urllib.parse import urlsplit

import httpx

from azents.core.credentials import XaiOAuthConfig, XaiOAuthSecrets
from azents.core.xai_oauth import XAI_USAGE_CLIENT_VERSION

from .data import (
    SubscriptionUsageLimit,
    SubscriptionUsageUnavailableReason,
    XaiSubscriptionFinancialDetails,
    XaiUsageAdapterOutcome,
    XaiUsageExternal,
    XaiUsageSnapshot,
    XaiUsageUnauthorized,
    XaiUsageUnavailable,
)

logger = logging.getLogger(__name__)

XAI_USAGE_CONTRACT_VERSION: Final = "xai-grok-build-0.2.105-v1"
XAI_USAGE_EXTERNAL_MESSAGE: Final = "Usage is managed on xAI."
_I64_MIN: Final = -(2**63)
_I64_MAX: Final = 2**63 - 1


class _InvalidXaiUsagePayload(ValueError):
    """Raised when the xAI usage response has an unsupported shape."""


@dataclasses.dataclass(frozen=True)
class _SettingsData:
    """Best-effort xAI settings used to enrich billing."""

    subscription_tier: str | None
    subscription_tier_display: str | None


@dataclasses.dataclass(frozen=True)
class _SettingsExternal:
    """Validated provider-managed usage redirect."""

    url: str


@dataclasses.dataclass(frozen=True)
class _SettingsInvalidRedirect:
    """Marker for an unsafe or malformed provider redirect."""


_SettingsOutcome = _SettingsData | _SettingsExternal | _SettingsInvalidRedirect


class XaiSubscriptionUsageClient:
    """Read and normalize the xAI CLI proxy usage wire contract."""

    def __init__(self, http_client: httpx.AsyncClient, usage_base_url: str) -> None:
        """
        :param http_client: Injected HTTP client for provider usage requests.
        :param usage_base_url: xAI CLI proxy root.
        """
        self.http_client = http_client
        self.usage_base_url = usage_base_url.rstrip("/")

    async def read_usage(
        self,
        *,
        secrets: XaiOAuthSecrets,
        config: XaiOAuthConfig,
    ) -> XaiUsageAdapterOutcome:
        """Read one xAI usage snapshot without exposing the wire payload."""
        account_id = config.account_id
        if account_id is None or not account_id.strip():
            return XaiUsageUnavailable(
                reason=SubscriptionUsageUnavailableReason.ACCOUNT_METADATA_MISSING,
                retryable=False,
                http_status=None,
            )
        headers = _headers(
            access_token=secrets.access_token,
            account_id=account_id.strip(),
        )
        settings = await self._read_settings(headers=headers)
        match settings:
            case _SettingsExternal(url=url):
                return XaiUsageExternal(url=url)
            case _SettingsInvalidRedirect():
                return self._invalid_response(http_status=200)
            case _SettingsData():
                pass
            case _:
                assert_never(settings)

        billing = await self._read_billing(headers=headers)
        if isinstance(billing, XaiUsageUnauthorized | XaiUsageUnavailable):
            return billing
        try:
            snapshot = _normalize_billing(billing, settings=settings)
        except _InvalidXaiUsagePayload:
            return self._invalid_response(http_status=200)

        financial = snapshot.financial_details
        if financial is None:
            return snapshot
        prepaid_balance = financial.prepaid_balance_cents
        if prepaid_balance is None or abs(prepaid_balance) == 0:
            return snapshot
        enrichment = await self._read_auto_top_up(headers=headers)
        if enrichment is None:
            return snapshot
        return dataclasses.replace(
            snapshot,
            financial_details=dataclasses.replace(
                financial,
                auto_top_up_enabled=enrichment.enabled,
                auto_top_up_amount_cents=enrichment.amount_cents,
                auto_top_up_monthly_maximum_cents=enrichment.monthly_maximum_cents,
            ),
        )

    async def _read_settings(self, *, headers: dict[str, str]) -> _SettingsOutcome:
        """Read remote settings as best-effort enrichment and redirect control."""
        try:
            response = await self.http_client.get(
                f"{self.usage_base_url}/settings",
                headers=headers,
            )
        except httpx.TimeoutException, httpx.TransportError:
            self._log_optional_failure(endpoint="settings", http_status=None)
            return _SettingsData(None, None)
        if not 200 <= response.status_code < 300:
            self._log_optional_failure(
                endpoint="settings", http_status=response.status_code
            )
            return _SettingsData(None, None)
        try:
            body = response.json()
        except json.JSONDecodeError, UnicodeDecodeError:
            self._log_optional_failure(
                endpoint="settings", http_status=response.status_code
            )
            return _SettingsData(None, None)
        if not isinstance(body, Mapping):
            self._log_optional_failure(
                endpoint="settings", http_status=response.status_code
            )
            return _SettingsData(None, None)

        redirect = body.get("usage_billing_redirect_url")
        if redirect is not None:
            if not isinstance(redirect, str):
                return _SettingsInvalidRedirect()
            if redirect.strip():
                if not _trusted_redirect(redirect):
                    return _SettingsInvalidRedirect()
                return _SettingsExternal(url=redirect)
        return _SettingsData(
            subscription_tier=_best_effort_string(body.get("subscription_tier")),
            subscription_tier_display=_best_effort_string(
                body.get("subscription_tier_display")
            ),
        )

    async def _read_billing(
        self, *, headers: dict[str, str]
    ) -> Mapping[str, object] | XaiUsageUnauthorized | XaiUsageUnavailable:
        """Read the required xAI credits response."""
        try:
            response = await self.http_client.get(
                f"{self.usage_base_url}/billing",
                params={"format": "credits"},
                headers=headers,
            )
        except httpx.TimeoutException, httpx.TransportError:
            return XaiUsageUnavailable(
                reason=SubscriptionUsageUnavailableReason.TEMPORARILY_UNAVAILABLE,
                retryable=True,
                http_status=None,
            )
        if response.status_code == 401:
            return XaiUsageUnauthorized(http_status=401)
        if response.status_code == 403:
            return XaiUsageUnavailable(
                reason=SubscriptionUsageUnavailableReason.ENTITLEMENT_UNAVAILABLE,
                retryable=False,
                http_status=403,
            )
        if response.status_code == 429:
            return XaiUsageUnavailable(
                reason=SubscriptionUsageUnavailableReason.RATE_LIMITED,
                retryable=True,
                http_status=429,
            )
        if response.status_code >= 500:
            return XaiUsageUnavailable(
                reason=SubscriptionUsageUnavailableReason.TEMPORARILY_UNAVAILABLE,
                retryable=True,
                http_status=response.status_code,
            )
        if not 200 <= response.status_code < 300:
            return XaiUsageUnavailable(
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
        return body

    async def _read_auto_top_up(
        self, *, headers: dict[str, str]
    ) -> "_AutoTopUp | None":
        """Read optional auto top-up details without affecting availability."""
        try:
            response = await self.http_client.get(
                f"{self.usage_base_url}/auto-topup-rule",
                headers=headers,
            )
        except httpx.TimeoutException, httpx.TransportError:
            self._log_optional_failure(endpoint="auto_top_up", http_status=None)
            return None
        if not 200 <= response.status_code < 300:
            self._log_optional_failure(
                endpoint="auto_top_up", http_status=response.status_code
            )
            return None
        try:
            body = response.json()
            return _normalize_auto_top_up(body)
        except json.JSONDecodeError, UnicodeDecodeError, _InvalidXaiUsagePayload:
            self._log_optional_failure(
                endpoint="auto_top_up", http_status=response.status_code
            )
            return None

    def _invalid_response(self, *, http_status: int) -> XaiUsageUnavailable:
        """Record safe contract-drift telemetry and return its typed outcome."""
        logger.error(
            "xAI subscription usage response is invalid.",
            extra={
                "provider": "xai_oauth",
                "operation": "subscription_usage_read",
                "outcome": "invalid_provider_response",
                "http_status": http_status,
                "adapter_contract_version": XAI_USAGE_CONTRACT_VERSION,
            },
        )
        return XaiUsageUnavailable(
            reason=SubscriptionUsageUnavailableReason.INVALID_PROVIDER_RESPONSE,
            retryable=False,
            http_status=http_status,
        )

    def _log_optional_failure(self, *, endpoint: str, http_status: int | None) -> None:
        """Record a safe optional-enrichment failure observation."""
        extra: dict[str, object] = {
            "provider": "xai_oauth",
            "operation": "subscription_usage_read",
            "outcome": "optional_enrichment_unavailable",
            "endpoint_category": endpoint,
            "adapter_contract_version": XAI_USAGE_CONTRACT_VERSION,
        }
        if http_status is not None:
            extra["http_status"] = http_status
        logger.info("xAI subscription usage enrichment is unavailable.", extra=extra)


@dataclasses.dataclass(frozen=True)
class _AutoTopUp:
    """Normalized optional auto top-up details."""

    enabled: bool
    amount_cents: int | None
    monthly_maximum_cents: int | None


def _headers(*, access_token: str, account_id: str) -> dict[str, str]:
    """Build the pinned xAI CLI proxy request identity."""
    return {
        "Authorization": f"Bearer {access_token}",
        "X-XAI-Token-Auth": "xai-grok-cli",
        "x-userid": account_id,
        "x-grok-client-version": XAI_USAGE_CLIENT_VERSION,
        "x-grok-client-identifier": "grok-shell",
        "x-grok-client-mode": "interactive",
    }


def _normalize_billing(
    body: Mapping[str, object], *, settings: _SettingsData
) -> XaiUsageSnapshot:
    """Normalize the required xAI credits response."""
    config = _mapping(body.get("config"), "config")
    percentage = _usage_percentage(config)
    current_period_value = config.get("currentPeriod")
    period_type: str | None = None
    period_start: datetime.datetime | None = None
    period_end: datetime.datetime | None = None
    if current_period_value is not None:
        current_period = _mapping(current_period_value, "currentPeriod")
        period_type = _optional_string(current_period.get("type"), "currentPeriod.type")
        period_start = _optional_rfc3339(
            current_period.get("start"), "currentPeriod.start"
        )
        period_end = _optional_rfc3339(current_period.get("end"), "currentPeriod.end")
    if period_start is None:
        period_start = _optional_rfc3339(
            config.get("billingPeriodStart"), "billingPeriodStart"
        )
    if period_end is None:
        period_end = _optional_rfc3339(
            config.get("billingPeriodEnd"), "billingPeriodEnd"
        )
    if (
        period_start is not None
        and period_end is not None
        and period_end <= period_start
    ):
        raise _InvalidXaiUsagePayload("billing period must be ordered")
    window_minutes = (
        int((period_end - period_start).total_seconds() // 60)
        if period_start is not None and period_end is not None
        else None
    )
    label = _period_label(period_type)

    _optional_boolean(body.get("onDemandEnabled"), "onDemandEnabled")
    _optional_boolean(config.get("isUnifiedBillingUser"), "isUnifiedBillingUser")
    billing_tier = _optional_string(body.get("subscriptionTier"), "subscriptionTier")
    plan_label = (
        settings.subscription_tier_display or billing_tier or settings.subscription_tier
    )
    prepaid_balance = _optional_cent(config.get("prepaidBalance"), "prepaidBalance")
    financial = XaiSubscriptionFinancialDetails(
        prepaid_balance_cents=prepaid_balance,
        payg_cap_cents=_optional_cent(config.get("onDemandCap"), "onDemandCap"),
        payg_used_cents=_optional_cent(config.get("onDemandUsed"), "onDemandUsed"),
        auto_top_up_enabled=None,
        auto_top_up_amount_cents=None,
        auto_top_up_monthly_maximum_cents=None,
    )
    return XaiUsageSnapshot(
        plan_label=plan_label,
        limits=(
            SubscriptionUsageLimit(
                id="subscription",
                label=label,
                used_percent=percentage,
                window_minutes=window_minutes,
                resets_at=period_end,
                primary=True,
            ),
        ),
        financial_details=financial,
    )


def _usage_percentage(config: Mapping[str, object]) -> float:
    """Read the preferred percentage or derive the legacy equivalent."""
    preferred = config.get("creditUsagePercent")
    if preferred is not None:
        return _bounded_percentage(preferred, "creditUsagePercent")
    monthly_limit = _required_cent(config.get("monthlyLimit"), "monthlyLimit")
    used = _required_cent(config.get("used"), "used")
    if monthly_limit <= 0:
        raise _InvalidXaiUsagePayload("monthlyLimit must be positive")
    return _bounded_percentage(used / monthly_limit * 100, "legacy usage percent")


def _normalize_auto_top_up(body: object) -> _AutoTopUp:
    """Normalize the optional auto top-up response."""
    payload = _mapping(body, "auto top-up response")
    rule_value = payload.get("rule")
    if rule_value is None:
        return _AutoTopUp(False, None, None)
    rule = _mapping(rule_value, "rule")
    enabled_value = rule.get("enabled")
    enabled = (
        False if enabled_value is None else _required_boolean(enabled_value, "enabled")
    )
    _optional_cent(rule.get("minBeforeHittingSl"), "minBeforeHittingSl")
    return _AutoTopUp(
        enabled=enabled,
        amount_cents=_optional_cent(rule.get("topupAmount"), "topupAmount"),
        monthly_maximum_cents=_optional_cent(
            rule.get("maxAmountPerMonth"), "maxAmountPerMonth"
        ),
    )


def _trusted_redirect(value: str) -> bool:
    """Validate one absolute provider-managed HTTPS usage URL."""
    try:
        parsed = urlsplit(value)
        hostname = parsed.hostname
        _ = parsed.port
    except ValueError:
        return False
    if (
        parsed.scheme != "https"
        or not parsed.netloc
        or parsed.username
        or parsed.password
    ):
        return False
    if hostname is None or hostname.endswith("."):
        return False
    try:
        ipaddress.ip_address(hostname)
    except ValueError:
        pass
    else:
        return False
    host = hostname.lower()
    return host in {"x.ai", "grok.com"} or host.endswith((".x.ai", ".grok.com"))


def _mapping(value: object, field: str) -> Mapping[str, object]:
    """Return a JSON object mapping or reject an invalid source shape."""
    if not isinstance(value, Mapping):
        raise _InvalidXaiUsagePayload(f"{field} must be an object")
    return value


def _best_effort_string(value: object) -> str | None:
    """Read non-empty settings strings while ignoring malformed enrichment."""
    if not isinstance(value, str):
        return None
    normalized = value.strip()
    return normalized or None


def _optional_string(value: object, field: str) -> str | None:
    """Read one optional provider string."""
    if value is None:
        return None
    if not isinstance(value, str):
        raise _InvalidXaiUsagePayload(f"{field} must be a string")
    normalized = value.strip()
    return normalized or None


def _required_boolean(value: object, field: str) -> bool:
    """Read one required source boolean."""
    if not isinstance(value, bool):
        raise _InvalidXaiUsagePayload(f"{field} must be a boolean")
    return value


def _optional_boolean(value: object, field: str) -> bool | None:
    """Read one optional source boolean."""
    if value is None:
        return None
    return _required_boolean(value, field)


def _required_cent(value: object, field: str) -> int:
    """Read one required strict signed 64-bit Cent wrapper."""
    parsed = _optional_cent(value, field)
    if parsed is None:
        raise _InvalidXaiUsagePayload(f"{field} is required")
    return parsed


def _optional_cent(value: object, field: str) -> int | None:
    """Read an optional Cent wrapper, treating proto3 omitted zero as zero."""
    if value is None:
        return None
    wrapper = _mapping(value, field)
    raw = wrapper.get("val", 0)
    if isinstance(raw, bool) or not isinstance(raw, int):
        raise _InvalidXaiUsagePayload(f"{field}.val must be an integer")
    if not _I64_MIN <= raw <= _I64_MAX:
        raise _InvalidXaiUsagePayload(f"{field}.val is outside signed 64-bit range")
    return raw


def _bounded_percentage(value: object, field: str) -> float:
    """Validate and clamp one provider percentage."""
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise _InvalidXaiUsagePayload(f"{field} must be numeric")
    try:
        percentage = float(value)
    except OverflowError as exc:
        raise _InvalidXaiUsagePayload(f"{field} must be finite") from exc
    if not math.isfinite(percentage):
        raise _InvalidXaiUsagePayload(f"{field} must be finite")
    return min(max(percentage, 0.0), 100.0)


def _optional_rfc3339(value: object, field: str) -> datetime.datetime | None:
    """Parse an optional RFC3339 timestamp into UTC."""
    if value is None:
        return None
    if not isinstance(value, str):
        raise _InvalidXaiUsagePayload(f"{field} must be a timestamp string")
    try:
        parsed = datetime.datetime.fromisoformat(value)
    except ValueError as exc:
        raise _InvalidXaiUsagePayload(f"{field} is invalid") from exc
    if parsed.tzinfo is None:
        raise _InvalidXaiUsagePayload(f"{field} must include a timezone")
    return parsed.astimezone(datetime.UTC)


def _period_label(period_type: str | None) -> str:
    """Return a stable operational label for the provider period enum."""
    if period_type == "USAGE_PERIOD_TYPE_WEEKLY":
        return "Weekly limit"
    if period_type == "USAGE_PERIOD_TYPE_MONTHLY":
        return "Monthly limit"
    return "Subscription limit"
