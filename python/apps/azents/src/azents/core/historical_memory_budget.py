"""Content-free execution observations and shared-core turn cutoff."""

import dataclasses
import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class ConsolidationTurnLimitExceeded(RuntimeError):
    """The configured turn cutoff stops execution without publishing."""


class ConsolidationUsage(BaseModel):
    """Only normalized scalar usage/provenance; never raw provider body or params."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    prompt_tokens: int = Field(ge=0)
    completion_tokens: int = Field(ge=0)
    total_tokens: int = Field(ge=0)
    cached_tokens: int | None = Field(ge=0)
    cache_creation_tokens: int | None = Field(ge=0)
    reasoning_tokens: int | None = Field(ge=0)
    cost_usd: float | None = Field(ge=0)
    cost_method: Literal["provider_reported", "estimated"] | None
    cost_source_key: str | None
    cost_collected_at: datetime.datetime | None
    cost_source_model_key: str | None
    cost_estimator_version: str | None


@dataclasses.dataclass(frozen=True)
class ConsolidationDispatchReservation:
    """Durably admitted one physical dispatch, including a transport retry."""

    dispatch_id: str
    request_number: int
    input_tokens: int
    output_tokens: int | None
