"""Historical Memory model output contracts."""

from pydantic import BaseModel, ConfigDict, Field


class HistoricalMemorySummaryOutput(BaseModel):
    """Strict source-summary output returned by the extraction model."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    summary: str = Field(description="Bounded Markdown Historical Memory account")
