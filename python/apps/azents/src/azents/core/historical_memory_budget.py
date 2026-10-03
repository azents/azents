"""Approved consolidation limits and content-free provider usage evidence."""

import dataclasses
import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

CONSOLIDATION_MODEL_REQUEST_LIMIT = 32
CONSOLIDATION_TOOL_CALL_LIMIT = 96
CONSOLIDATION_INPUT_TOKEN_LIMIT = 250_000
CONSOLIDATION_OUTPUT_TOKEN_LIMIT = 16_000


class ConsolidationBudgetExceeded(ValueError):
    """A hard attempt boundary stops admission, never successful publication."""


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
    output_tokens: int
