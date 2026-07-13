"""System bootstrap repository data models."""

import datetime

from pydantic import BaseModel, Field


class SystemBootstrapState(BaseModel):
    """Persisted singleton bootstrap state."""

    token_hash: str = Field(description="SHA-256 setup token hash")
    created_at: datetime.datetime = Field(description="Token activation time")
    consumed_at: datetime.datetime | None = Field(description="Token consumption time")
