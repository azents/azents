"""Normalized subscription usage domain data."""

import dataclasses
import datetime
import enum
from typing import TypeAlias

from azents.core.enums import LLMProvider


class SubscriptionUsageUnavailableReason(enum.StrEnum):
    """Controlled reasons a subscription usage read is unavailable."""

    DISABLED = "disabled"
    RECONNECT_REQUIRED = "reconnect_required"
    ACCOUNT_METADATA_MISSING = "account_metadata_missing"
    PERMISSION_DENIED = "permission_denied"
    ENTITLEMENT_UNAVAILABLE = "entitlement_unavailable"
    RATE_LIMITED = "rate_limited"
    TEMPORARILY_UNAVAILABLE = "temporarily_unavailable"
    INVALID_PROVIDER_RESPONSE = "invalid_provider_response"
    UNSUPPORTED_ACCOUNT = "unsupported_account"
    NO_CREDIT_LIMIT = "no_credit_limit"


@dataclasses.dataclass(frozen=True)
class SubscriptionUsageLimit:
    """One normalized provider subscription usage window."""

    id: str
    label: str
    used_percent: float
    window_minutes: int | None
    resets_at: datetime.datetime | None
    primary: bool


@dataclasses.dataclass(frozen=True)
class ChatGPTSubscriptionFinancialDetails:
    """Optional ChatGPT financial subscription details."""

    has_credits: bool | None
    unlimited: bool | None
    balance: str | None
    spend_limit: str | None
    spend_used: str | None
    spend_remaining_percent: float | None
    spend_resets_at: datetime.datetime | None
    reached_type: str | None


@dataclasses.dataclass(frozen=True)
class XaiSubscriptionFinancialDetails:
    """Optional xAI financial subscription details."""

    prepaid_balance_cents: int | None
    payg_cap_cents: int | None
    payg_used_cents: int | None
    auto_top_up_enabled: bool | None
    auto_top_up_amount_cents: int | None
    auto_top_up_monthly_maximum_cents: int | None


@dataclasses.dataclass(frozen=True)
class OpenRouterSubscriptionFinancialDetails:
    """OpenRouter API-key credit details for integration managers."""

    credit_limit: float
    credit_remaining: float
    usage: float
    usage_daily: float
    usage_weekly: float
    usage_monthly: float
    limit_reset: str | None
    include_byok_in_limit: bool


SubscriptionUsageFinancialDetails: TypeAlias = (
    ChatGPTSubscriptionFinancialDetails
    | XaiSubscriptionFinancialDetails
    | OpenRouterSubscriptionFinancialDetails
)


@dataclasses.dataclass(frozen=True)
class SubscriptionUsageAvailable:
    """Available normalized subscription usage snapshot."""

    integration_id: str
    provider: LLMProvider
    fetched_at: datetime.datetime
    plan_label: str | None
    limits: tuple[SubscriptionUsageLimit, ...]
    financial_details: SubscriptionUsageFinancialDetails | None


@dataclasses.dataclass(frozen=True)
class SubscriptionUsageExternal:
    """Provider-directed external subscription usage page."""

    integration_id: str
    provider: LLMProvider
    fetched_at: datetime.datetime
    url: str
    message: str


@dataclasses.dataclass(frozen=True)
class SubscriptionUsageUnavailable:
    """Controlled unavailable subscription usage snapshot."""

    integration_id: str
    provider: LLMProvider
    fetched_at: datetime.datetime
    reason: SubscriptionUsageUnavailableReason
    message: str
    retryable: bool


SubscriptionUsageOutcome: TypeAlias = (
    SubscriptionUsageAvailable
    | SubscriptionUsageExternal
    | SubscriptionUsageUnavailable
)


@dataclasses.dataclass(frozen=True)
class SubscriptionUsageNotFound:
    """Requested subscription integration was not found."""

    integration_id: str


@dataclasses.dataclass(frozen=True)
class SubscriptionUsageNotInWorkspace:
    """Requested subscription integration belongs to another workspace."""

    integration_id: str


@dataclasses.dataclass(frozen=True)
class SubscriptionUsageUnsupportedProvider:
    """Requested provider does not implement subscription usage."""

    provider: LLMProvider


SubscriptionUsageServiceFailure: TypeAlias = (
    SubscriptionUsageNotFound
    | SubscriptionUsageNotInWorkspace
    | SubscriptionUsageUnsupportedProvider
)


@dataclasses.dataclass(frozen=True)
class ChatGPTUsageSnapshot:
    """Normalized ChatGPT adapter result before integration projection."""

    plan_label: str | None
    limits: tuple[SubscriptionUsageLimit, ...]
    financial_details: ChatGPTSubscriptionFinancialDetails | None


@dataclasses.dataclass(frozen=True)
class ChatGPTUsageUnavailable:
    """Controlled unavailable result from the ChatGPT usage adapter."""

    reason: SubscriptionUsageUnavailableReason
    retryable: bool
    http_status: int | None


@dataclasses.dataclass(frozen=True)
class ChatGPTUsageUnauthorized:
    """Internal marker requesting one forced token-refresh retry."""

    http_status: int


ChatGPTUsageAdapterOutcome: TypeAlias = (
    ChatGPTUsageSnapshot | ChatGPTUsageUnavailable | ChatGPTUsageUnauthorized
)


@dataclasses.dataclass(frozen=True)
class XaiUsageSnapshot:
    """Normalized xAI adapter result before integration projection."""

    plan_label: str | None
    limits: tuple[SubscriptionUsageLimit, ...]
    financial_details: XaiSubscriptionFinancialDetails | None


@dataclasses.dataclass(frozen=True)
class XaiUsageExternal:
    """Validated xAI-managed usage location."""

    url: str


@dataclasses.dataclass(frozen=True)
class XaiUsageUnavailable:
    """Controlled unavailable result from the xAI usage adapter."""

    reason: SubscriptionUsageUnavailableReason
    retryable: bool
    http_status: int | None


@dataclasses.dataclass(frozen=True)
class XaiUsageUnauthorized:
    """Internal marker requesting one forced token-refresh retry."""

    http_status: int


XaiUsageAdapterOutcome: TypeAlias = (
    XaiUsageSnapshot | XaiUsageExternal | XaiUsageUnavailable | XaiUsageUnauthorized
)


@dataclasses.dataclass(frozen=True)
class OpenRouterUsageSnapshot:
    """Normalized OpenRouter key-credit result before integration projection."""

    plan_label: str | None
    limits: tuple[SubscriptionUsageLimit, ...]
    financial_details: OpenRouterSubscriptionFinancialDetails | None


@dataclasses.dataclass(frozen=True)
class OpenRouterUsageHidden:
    """Successful OpenRouter read with no bounded credit limit."""


@dataclasses.dataclass(frozen=True)
class OpenRouterUsageUnavailable:
    """Controlled unavailable result from the OpenRouter usage adapter."""

    reason: SubscriptionUsageUnavailableReason
    retryable: bool
    http_status: int | None


@dataclasses.dataclass(frozen=True)
class KimiUsageSnapshot:
    """Normalized Kimi adapter result before integration projection."""

    plan_label: str | None
    limits: tuple[SubscriptionUsageLimit, ...]
    financial_details: None


@dataclasses.dataclass(frozen=True)
class KimiUsageUnavailable:
    """Controlled unavailable result from the Kimi usage adapter."""

    reason: SubscriptionUsageUnavailableReason
    retryable: bool
    http_status: int | None


OpenRouterUsageAdapterOutcome: TypeAlias = (
    OpenRouterUsageSnapshot | OpenRouterUsageHidden | OpenRouterUsageUnavailable
)


@dataclasses.dataclass(frozen=True)
class KimiUsageUnauthorized:
    """Internal marker requesting one forced token-refresh retry."""

    http_status: int


KimiUsageAdapterOutcome: TypeAlias = (
    KimiUsageSnapshot | KimiUsageUnavailable | KimiUsageUnauthorized
)


def unavailable_message(reason: SubscriptionUsageUnavailableReason) -> str:
    """Return fixed Azents copy for a controlled unavailable reason."""
    match reason:
        case SubscriptionUsageUnavailableReason.DISABLED:
            return "Enable this integration to refresh subscription usage."
        case SubscriptionUsageUnavailableReason.RECONNECT_REQUIRED:
            return "Reconnect this integration to refresh subscription usage."
        case SubscriptionUsageUnavailableReason.ACCOUNT_METADATA_MISSING:
            return (
                "Subscription usage is unavailable because account metadata is missing."
            )
        case SubscriptionUsageUnavailableReason.PERMISSION_DENIED:
            return "Subscription usage permission is unavailable."
        case SubscriptionUsageUnavailableReason.ENTITLEMENT_UNAVAILABLE:
            return "Subscription usage entitlement is unavailable."
        case SubscriptionUsageUnavailableReason.RATE_LIMITED:
            return "Subscription usage is rate limited."
        case SubscriptionUsageUnavailableReason.TEMPORARILY_UNAVAILABLE:
            return "Subscription usage is temporarily unavailable."
        case SubscriptionUsageUnavailableReason.INVALID_PROVIDER_RESPONSE:
            return "Subscription usage response is unavailable."
        case SubscriptionUsageUnavailableReason.UNSUPPORTED_ACCOUNT:
            return "Subscription usage is unavailable for this account."
        case SubscriptionUsageUnavailableReason.NO_CREDIT_LIMIT:
            return "Credit usage is unavailable for keys without a credit limit."
