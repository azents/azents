"""Azents-owned decoding of the retained public metadata source."""

from pydantic import BaseModel, ConfigDict


class SourceReasoningMetadata(BaseModel):
    """Decode the source flags consumed by reasoning capability projection.

    Missing and null flags remain unknown. Other source fields belong to their
    existing projection contracts or opaque snapshot provenance.
    """

    model_config = ConfigDict(frozen=True, extra="ignore")

    supports_reasoning: bool | None = None
    supports_none_reasoning_effort: bool | None = None
    supports_minimal_reasoning_effort: bool | None = None
    supports_low_reasoning_effort: bool | None = None
    supports_xhigh_reasoning_effort: bool | None = None
    supports_max_reasoning_effort: bool | None = None
