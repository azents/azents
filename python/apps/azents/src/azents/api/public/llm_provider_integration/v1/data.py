"""LLM Provider Integration v1 Public API data models."""

import datetime
from typing import Any

from pydantic import BaseModel, Field, model_validator
from typing_extensions import Self

from azents.core.credentials import (
    PROVIDER_SECRET_TYPES,
    PROVIDERS_WITH_CONFIG,
    ProviderConfig,
    ProviderSecrets,
)
from azents.core.enums import LLMProvider
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
    current_snapshot_id: str | None
    current_snapshot_created_at: datetime.datetime | None
    latest_attempt: ModelCatalogSyncAttemptResponse | None
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
            current_snapshot_id=data.current_snapshot_id,
            current_snapshot_created_at=data.current_snapshot_created_at,
            latest_attempt=(
                ModelCatalogSyncAttemptResponse.convert_from(data.latest_attempt)
                if data.latest_attempt is not None
                else None
            ),
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


class LLMProviderIntegrationCreateRequest(BaseModel):
    """LLM Provider Integration creation request."""

    provider: LLMProvider = Field(description="LLM Hosting provider")
    name: str | None = Field(
        default=None, description="Alias; uses provider name when omitted"
    )
    secrets: ProviderSecrets = Field(description="Secrets such as API keys")
    config: ProviderConfig | None = Field(
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


class LLMProviderIntegrationUpdateRequest(LLMProviderIntegrationUpdateInput):
    """LLM Provider Integration update request for partial updates."""

    pass
