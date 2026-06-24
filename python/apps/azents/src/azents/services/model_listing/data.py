"""Provider model listing service data models."""

import datetime
from typing import Any

from pydantic import BaseModel, Field

from azents.core.enums import LLMModelDeveloper, LLMProvider
from azents.core.llm_catalog import ModelCapabilities


class NormalizedModelCandidate(BaseModel):
    """Normalized model candidate used to create Agent model selection snapshot."""

    provider: LLMProvider = Field(description="Hosting provider")
    model_identifier: str = Field(description="Provider model identifier")
    model_display_name: str = Field(description="Model display name")
    model_developer: LLMModelDeveloper = Field(description="Model developer")
    model_family: str | None = Field(default=None, description="Model family")
    normalized_capabilities: ModelCapabilities = Field(
        description="Normalized capability contract"
    )
    model_snapshot: dict[str, Any] = Field(description="Normalized model snapshot")
    source_metadata: dict[str, Any] | None = Field(
        default=None, description="source diagnostic metadata"
    )
    last_refreshed_at: datetime.datetime | None = Field(
        default=None, description="Last refresh time"
    )


class ModelListingSkipSummary(BaseModel):
    """listing normalization skip summary."""

    reason: str = Field(description="skip reason")
    count: int = Field(description="skip count")


class ModelListingSummary(BaseModel):
    """provider model listing summary."""

    source: str = Field(description="listing source")
    fetched_at: datetime.datetime = Field(description="Fetch time")
    returned_count: int = Field(description="Returned model count")
    skipped_count: int = Field(description="Skipped model count")


class ModelListingOutput(BaseModel):
    """provider model listing result."""

    models: list[NormalizedModelCandidate] = Field(
        description="Normalized model candidates"
    )
    summary: ModelListingSummary = Field(description="listing summary")
    skips: list[ModelListingSkipSummary] = Field(description="skip summary")


class ListingNotFound(BaseModel):
    """listing target integration not found."""

    integration_id: str


class ListingNotBelongToWorkspace(BaseModel):
    """listing target integration does not belong to requested workspace."""

    integration_id: str


class IntegrationDisabled(BaseModel):
    """listing target integration is disabled."""

    integration_id: str


class CandidateNotFound(BaseModel):
    """Selected model candidate not found in latest listing."""

    provider: LLMProvider
    model_identifier: str
