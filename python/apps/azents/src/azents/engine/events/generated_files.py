"""Transient generated-file values excluded from durable event payloads."""

from pydantic import BaseModel, ConfigDict, Field


class GeneratedFileOutput(BaseModel):
    """Validated generated file produced by a client tool handler."""

    model_config = ConfigDict(frozen=True)

    output_index: int = Field(ge=0)
    filename: str = Field(min_length=1)
    media_type: str = Field(min_length=1)
    sha256: str = Field(min_length=64, max_length=64)
    body: bytes = Field(exclude=True, repr=False)


class PendingGeneratedFileOutput(GeneratedFileOutput):
    """Generated file bytes awaiting transactional result admission."""

    call_id: str = Field(min_length=1)
    tool_name: str = Field(min_length=1)
