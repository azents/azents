"""LLM Provider Integration v1 Public API data models."""

import datetime
from typing import Annotated, Any, Literal, assert_never

from pydantic import BaseModel, Field, HttpUrl, model_validator
from typing_extensions import Self, TypedDict

from azents.core.credentials import (
    PROVIDER_SECRET_TYPES,
    PROVIDERS_WITH_CONFIG,
    ApiKeySecrets,
    AwsConfig,
    AwsSecrets,
    GcpConfig,
    GcpSecrets,
    ProviderConfig,
)
from azents.core.enums import LLMCatalogScope, LLMProvider
from azents.core.llm_catalog import ModelCapabilities
from azents.repos.llm_provider_integration.data import LLMProviderIntegration
from azents.services.llm_catalog import (
    ModelCatalogEntryListOutput,
    ModelCatalogEntryOutput,
    ModelCatalogSyncAttemptOutput,
    SystemCatalogProjectionSummary,
)
from azents.services.llm_provider_integration.data import (
    LLMProviderIntegrationUpdateInput,
)
from azents.services.subscription_usage.data import (
    ChatGPTSubscriptionFinancialDetails,
    OpenRouterSubscriptionFinancialDetails,
    SubscriptionUsageAvailable,
    SubscriptionUsageExternal,
    SubscriptionUsageFinancialDetails,
    SubscriptionUsageLimit,
    SubscriptionUsageOutcome,
    SubscriptionUsageUnavailable,
    SubscriptionUsageUnavailableReason,
    XaiSubscriptionFinancialDetails,
)


class ModelCatalogEntryResponse(BaseModel):
    """Stored model catalog entry response."""

    id: str
    provider: LLMProvider
    provider_model_identifier: str
    runtime_model_identifier: str
    display_name: str
    normalized_capabilities: ModelCapabilities
    lifecycle_status: str
    visibility_status: str
    publisher: str | None
    family: str | None
    source_metadata: dict[str, Any] | None
    projection_metadata: dict[str, Any] | None

    @classmethod
    def convert_from(
        cls,
        entry: ModelCatalogEntryOutput,
    ) -> "ModelCatalogEntryResponse":
        """Convert service output to response model."""
        return cls(
            id=entry.id,
            provider=entry.provider,
            provider_model_identifier=entry.provider_model_identifier,
            runtime_model_identifier=entry.runtime_model_identifier,
            display_name=entry.display_name,
            normalized_capabilities=entry.normalized_capabilities,
            lifecycle_status=entry.lifecycle_status.value,
            visibility_status=entry.visibility_status.value,
            publisher=entry.publisher,
            family=entry.family,
            source_metadata=entry.source_metadata,
            projection_metadata=entry.projection_metadata,
        )


class ModelCatalogSyncAttemptResponse(BaseModel):
    """Latest model catalog sync attempt response."""

    id: str
    status: str
    started_at: datetime.datetime
    finished_at: datetime.datetime | None
    failure_code: str | None
    failure_message: str | None
    action_hint: str | None
    fetched_count: int
    matched_count: int
    skipped_count: int
    hidden_count: int

    @classmethod
    def convert_from(
        cls,
        attempt: ModelCatalogSyncAttemptOutput,
    ) -> "ModelCatalogSyncAttemptResponse":
        """Convert service output to response model."""
        return cls.model_validate(attempt.model_dump())


class ModelCatalogEntryListResponse(BaseModel):
    """Stored model catalog entry list response."""

    catalog_id: str
    catalog_scope: LLMCatalogScope
    current_snapshot_id: str | None
    current_snapshot_created_at: datetime.datetime | None
    latest_attempt: ModelCatalogSyncAttemptResponse | None
    stale: bool
    sync_available_at: datetime.datetime | None
    automatic_retry_blocked: bool
    entries: list[ModelCatalogEntryResponse]
    total: int
    limit: int
    offset: int

    @classmethod
    def convert_from(
        cls,
        data: ModelCatalogEntryListOutput,
    ) -> "ModelCatalogEntryListResponse":
        """Convert service output to response model."""
        return cls(
            catalog_id=data.catalog_id,
            catalog_scope=data.catalog_scope,
            current_snapshot_id=data.current_snapshot_id,
            current_snapshot_created_at=data.current_snapshot_created_at,
            latest_attempt=(
                ModelCatalogSyncAttemptResponse.convert_from(data.latest_attempt)
                if data.latest_attempt is not None
                else None
            ),
            stale=data.stale,
            sync_available_at=data.sync_available_at,
            automatic_retry_blocked=data.automatic_retry_blocked,
            entries=[ModelCatalogEntryResponse.convert_from(e) for e in data.entries],
            total=data.total,
            limit=data.limit,
            offset=data.offset,
        )


class ModelCatalogSyncResponse(BaseModel):
    """Model catalog sync response."""

    provider: LLMProvider
    catalog_id: str
    snapshot_id: str | None
    visible_count: int
    hidden_count: int
    status: str
    failure_code: str | None
    failure_message: str | None
    action_hint: str | None

    @classmethod
    def convert_from(
        cls,
        summary: SystemCatalogProjectionSummary,
    ) -> "ModelCatalogSyncResponse":
        """Convert service output to response model."""
        return cls(
            provider=summary.provider,
            catalog_id=summary.catalog_id,
            snapshot_id=summary.snapshot_id,
            visible_count=summary.visible_count,
            hidden_count=summary.hidden_count,
            status=summary.status,
            failure_code=summary.failure_code,
            failure_message=summary.failure_message,
            action_hint=summary.action_hint,
        )


class LLMProviderIntegrationResponse(BaseModel):
    """LLM Provider Integration response without secrets."""

    id: str
    provider: LLMProvider
    name: str
    config: ProviderConfig | None
    enabled: bool
    created_at: datetime.datetime
    updated_at: datetime.datetime

    @classmethod
    def convert_from(
        cls, data: LLMProviderIntegration
    ) -> "LLMProviderIntegrationResponse":
        """Convert from domain model to response object.

        :param data: LLM Provider Integration domain model
        :return: Response object
        """
        return cls(
            id=data.id,
            provider=data.provider,
            name=data.name,
            config=data.config,
            enabled=data.enabled,
            created_at=data.created_at,
            updated_at=data.updated_at,
        )


class LLMProviderIntegrationListResponse(BaseModel):
    """LLM Provider Integration list response."""

    items: list[LLMProviderIntegrationResponse]


class LLMProviderCapabilityResponse(BaseModel):
    """LLM provider capability exposed to the workspace UI."""

    provider: LLMProvider
    display_name: str
    credential_type: str
    experimental: bool = False


class LLMProviderCapabilityListResponse(BaseModel):
    """Available LLM provider capability list response."""

    items: list[LLMProviderCapabilityResponse]


GenericIntegrationProvider = Literal[
    LLMProvider.OPENAI,
    LLMProvider.XAI,
    LLMProvider.OPENROUTER,
    LLMProvider.ANTHROPIC,
    LLMProvider.GOOGLE_GEMINI,
    LLMProvider.AWS_BEDROCK,
    LLMProvider.GOOGLE_VERTEX_AI,
]
GenericIntegrationSecrets = Annotated[
    ApiKeySecrets | AwsSecrets | GcpSecrets,
    Field(discriminator="type"),
]
GenericIntegrationConfig = Annotated[
    AwsConfig | GcpConfig,
    Field(discriminator="type"),
]


class LLMProviderIntegrationCreateRequest(BaseModel):
    """LLM Provider Integration creation request."""

    provider: GenericIntegrationProvider = Field(description="LLM Hosting provider")
    name: str | None = Field(
        default=None, description="Alias; uses provider name when omitted"
    )
    secrets: GenericIntegrationSecrets = Field(description="Secrets such as API keys")
    config: GenericIntegrationConfig | None = Field(
        default=None, description="Provider configuration such as AWS or GCP"
    )
    enabled: bool = Field(default=True, description="Enabled state")

    @model_validator(mode="after")
    def validate_secrets_and_config(self) -> Self:
        """Validate whether secrets/config types match the provider."""
        # Validate secret type
        expected_secret = PROVIDER_SECRET_TYPES[self.provider]
        if self.secrets.type != expected_secret:
            msg = (
                f"Provider '{self.provider.value}' requires"
                f" '{expected_secret}'  secret type."
            )
            raise ValueError(msg)

        # Validate whether config is required
        if self.provider in PROVIDERS_WITH_CONFIG:
            if self.config is None:
                msg = f"Provider '{self.provider.value}' requires  config settings."
                raise ValueError(msg)
            if self.config.type != expected_secret:
                msg = (
                    f"Provider '{self.provider.value}' requires"
                    f" '{expected_secret}'  config type."
                )
                raise ValueError(msg)
        elif self.config is not None:
            msg = f"Provider '{self.provider.value}' requires  does not require config."
            raise ValueError(msg)

        return self


class LLMProviderIntegrationUpdateRequest(TypedDict, total=False):
    """Public partial update without server-owned OAuth credentials."""

    name: Annotated[str, Field(description="Display name")]
    secrets: Annotated[
        GenericIntegrationSecrets,
        Field(description="Generic integration secrets before encryption"),
    ]
    config: Annotated[
        GenericIntegrationConfig | None,
        Field(description="Generic integration plaintext config"),
    ]
    enabled: Annotated[bool, Field(description="Enabled flag")]


def convert_integration_update_request(
    request: LLMProviderIntegrationUpdateRequest,
) -> LLMProviderIntegrationUpdateInput:
    """Widen a public generic-credential patch to the service update contract."""
    update: LLMProviderIntegrationUpdateInput = {}
    if "name" in request:
        update["name"] = request["name"]
    if "secrets" in request:
        update["secrets"] = request["secrets"]
    if "config" in request:
        update["config"] = request["config"]
    if "enabled" in request:
        update["enabled"] = request["enabled"]
    return update


SubscriptionUsageProvider = Literal[
    "chatgpt_oauth", "xai_oauth", "openrouter", "kimi_oauth"
]


class SubscriptionUsageLimitResponse(BaseModel):
    """Normalized public subscription usage window."""

    id: str
    label: str
    used_percent: float
    window_minutes: int | None
    resets_at: datetime.datetime | None
    primary: bool

    @classmethod
    def convert_from(
        cls, data: SubscriptionUsageLimit
    ) -> "SubscriptionUsageLimitResponse":
        """Convert a normalized domain limit to its public response."""
        return cls(
            id=data.id,
            label=data.label,
            used_percent=data.used_percent,
            window_minutes=data.window_minutes,
            resets_at=(
                _utc_datetime(data.resets_at) if data.resets_at is not None else None
            ),
            primary=data.primary,
        )


class ChatGPTSubscriptionFinancialDetailsResponse(BaseModel):
    """Management-only ChatGPT subscription financial details."""

    type: Literal["chatgpt"]
    has_credits: bool | None
    unlimited: bool | None
    balance: str | None
    spend_limit: str | None
    spend_used: str | None
    spend_remaining_percent: float | None
    spend_resets_at: datetime.datetime | None
    reached_type: str | None

    @classmethod
    def convert_from(
        cls, data: ChatGPTSubscriptionFinancialDetails
    ) -> "ChatGPTSubscriptionFinancialDetailsResponse":
        """Convert ChatGPT financial detail without provider wire metadata."""
        return cls(
            type="chatgpt",
            has_credits=data.has_credits,
            unlimited=data.unlimited,
            balance=data.balance,
            spend_limit=data.spend_limit,
            spend_used=data.spend_used,
            spend_remaining_percent=data.spend_remaining_percent,
            spend_resets_at=(
                _utc_datetime(data.spend_resets_at)
                if data.spend_resets_at is not None
                else None
            ),
            reached_type=data.reached_type,
        )


class XaiSubscriptionFinancialDetailsResponse(BaseModel):
    """Management-only xAI subscription financial details."""

    type: Literal["xai"]
    prepaid_balance_cents: int | None
    payg_cap_cents: int | None
    payg_used_cents: int | None
    auto_top_up_enabled: bool | None
    auto_top_up_amount_cents: int | None
    auto_top_up_monthly_maximum_cents: int | None

    @classmethod
    def convert_from(
        cls, data: XaiSubscriptionFinancialDetails
    ) -> "XaiSubscriptionFinancialDetailsResponse":
        """Convert xAI financial detail reserved for the Phase 2 producer."""
        return cls(
            type="xai",
            prepaid_balance_cents=data.prepaid_balance_cents,
            payg_cap_cents=data.payg_cap_cents,
            payg_used_cents=data.payg_used_cents,
            auto_top_up_enabled=data.auto_top_up_enabled,
            auto_top_up_amount_cents=data.auto_top_up_amount_cents,
            auto_top_up_monthly_maximum_cents=data.auto_top_up_monthly_maximum_cents,
        )


class OpenRouterSubscriptionFinancialDetailsResponse(BaseModel):
    """Management-only OpenRouter API-key credit details."""

    type: Literal["openrouter"]
    credit_limit: float
    credit_remaining: float
    usage: float
    usage_daily: float
    usage_weekly: float
    usage_monthly: float
    limit_reset: str | None
    include_byok_in_limit: bool

    @classmethod
    def convert_from(
        cls, data: OpenRouterSubscriptionFinancialDetails
    ) -> "OpenRouterSubscriptionFinancialDetailsResponse":
        """Convert normalized OpenRouter credit details to public data."""
        return cls(
            type="openrouter",
            credit_limit=data.credit_limit,
            credit_remaining=data.credit_remaining,
            usage=data.usage,
            usage_daily=data.usage_daily,
            usage_weekly=data.usage_weekly,
            usage_monthly=data.usage_monthly,
            limit_reset=data.limit_reset,
            include_byok_in_limit=data.include_byok_in_limit,
        )


SubscriptionUsageFinancialDetailsResponse = Annotated[
    ChatGPTSubscriptionFinancialDetailsResponse
    | XaiSubscriptionFinancialDetailsResponse
    | OpenRouterSubscriptionFinancialDetailsResponse,
    Field(discriminator="type"),
]


class SubscriptionUsageAvailableResponse(BaseModel):
    """Public available subscription usage response."""

    type: Literal["available"]
    integration_id: str
    provider: SubscriptionUsageProvider
    fetched_at: datetime.datetime
    plan_label: str | None
    limits: Annotated[list[SubscriptionUsageLimitResponse], Field(min_length=1)]
    financial_details: SubscriptionUsageFinancialDetailsResponse | None

    @classmethod
    def convert_from(
        cls, data: SubscriptionUsageAvailable
    ) -> "SubscriptionUsageAvailableResponse":
        """Convert a normalized available outcome to a public response."""
        return cls(
            type="available",
            integration_id=data.integration_id,
            provider=_subscription_usage_provider(data.provider),
            fetched_at=_utc_datetime(data.fetched_at),
            plan_label=data.plan_label,
            limits=[
                SubscriptionUsageLimitResponse.convert_from(limit)
                for limit in data.limits
            ],
            financial_details=(
                convert_subscription_usage_financial_details(data.financial_details)
                if data.financial_details is not None
                else None
            ),
        )


class SubscriptionUsageExternalResponse(BaseModel):
    """Public provider-managed subscription usage response."""

    type: Literal["external"]
    integration_id: str
    provider: SubscriptionUsageProvider
    fetched_at: datetime.datetime
    url: HttpUrl
    message: str

    @classmethod
    def convert_from(
        cls, data: SubscriptionUsageExternal
    ) -> "SubscriptionUsageExternalResponse":
        """Convert a validated external outcome to a public response."""
        return cls(
            type="external",
            integration_id=data.integration_id,
            provider=_subscription_usage_provider(data.provider),
            fetched_at=_utc_datetime(data.fetched_at),
            url=HttpUrl(data.url),
            message=data.message,
        )


class SubscriptionUsageUnavailableResponse(BaseModel):
    """Public controlled unavailable subscription usage response."""

    type: Literal["unavailable"]
    integration_id: str
    provider: SubscriptionUsageProvider
    fetched_at: datetime.datetime
    reason: SubscriptionUsageUnavailableReason
    message: str
    retryable: bool

    @classmethod
    def convert_from(
        cls, data: SubscriptionUsageUnavailable
    ) -> "SubscriptionUsageUnavailableResponse":
        """Convert a controlled unavailable outcome to a public response."""
        return cls(
            type="unavailable",
            integration_id=data.integration_id,
            provider=_subscription_usage_provider(data.provider),
            fetched_at=_utc_datetime(data.fetched_at),
            reason=data.reason,
            message=data.message,
            retryable=data.retryable,
        )


SubscriptionUsageResponse = Annotated[
    SubscriptionUsageAvailableResponse
    | SubscriptionUsageExternalResponse
    | SubscriptionUsageUnavailableResponse,
    Field(discriminator="type"),
]


def convert_subscription_usage_financial_details(
    data: SubscriptionUsageFinancialDetails,
) -> SubscriptionUsageFinancialDetailsResponse:
    """Convert a closed provider financial detail union to public data."""
    match data:
        case ChatGPTSubscriptionFinancialDetails():
            return ChatGPTSubscriptionFinancialDetailsResponse.convert_from(data)
        case XaiSubscriptionFinancialDetails():
            return XaiSubscriptionFinancialDetailsResponse.convert_from(data)
        case OpenRouterSubscriptionFinancialDetails():
            return OpenRouterSubscriptionFinancialDetailsResponse.convert_from(data)
        case _:
            assert_never(data)


def convert_subscription_usage_response(
    data: SubscriptionUsageOutcome,
) -> SubscriptionUsageResponse:
    """Convert a closed subscription usage outcome union to public data."""
    match data:
        case SubscriptionUsageAvailable():
            return SubscriptionUsageAvailableResponse.convert_from(data)
        case SubscriptionUsageExternal():
            return SubscriptionUsageExternalResponse.convert_from(data)
        case SubscriptionUsageUnavailable():
            return SubscriptionUsageUnavailableResponse.convert_from(data)
        case _:
            assert_never(data)


def _subscription_usage_provider(provider: LLMProvider) -> SubscriptionUsageProvider:
    """Restrict the public usage provider contract to subscription OAuth providers."""
    if provider == LLMProvider.CHATGPT_OAUTH:
        return "chatgpt_oauth"
    if provider == LLMProvider.XAI_OAUTH:
        return "xai_oauth"
    if provider == LLMProvider.OPENROUTER:
        return "openrouter"
    if provider == LLMProvider.KIMI_OAUTH:
        return "kimi_oauth"

    msg = "Subscription usage response has an unsupported provider."
    raise ValueError(msg)


def _utc_datetime(value: datetime.datetime) -> datetime.datetime:
    """Normalize subscription usage timestamps to aware UTC datetimes."""
    if value.tzinfo is None:
        return value.replace(tzinfo=datetime.UTC)
    return value.astimezone(datetime.UTC)
