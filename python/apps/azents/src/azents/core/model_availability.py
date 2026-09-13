"""Session model availability and Primary reservation contracts."""

import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class ModelCandidateIdentity(BaseModel):
    """Public-safe exact physical candidate identity."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    llm_provider_integration_id: str = Field(min_length=1)
    model_identifier: str = Field(min_length=1)


class PrimaryModelReservation(BaseModel):
    """Durable one-shot Session authority for a Primary candidate attempt."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal[1] = 1
    semantic_label: str = Field(min_length=1)
    candidate: ModelCandidateIdentity
    health_generation: int = Field(ge=1)
    reservation_generation: int = Field(ge=1)
    claim_token: str = Field(min_length=1)
    created_at: datetime.datetime
    expires_at: datetime.datetime


class SessionModelAvailability(BaseModel):
    """Authoritative DB-derived model recovery projection for one Session."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    semantic_label: str = Field(min_length=1)
    primary: ModelCandidateIdentity
    primary_display_name: str = Field(min_length=1)
    state: Literal["available", "cooldown", "probing", "primary_next"]
    deadline: datetime.datetime | None
    server_time: datetime.datetime
    first_usable_fallback_display_name: str | None
    reservation: PrimaryModelReservation | None


class ReservePrimaryModelRequest(BaseModel):
    """Optimistic exact-identity request for one Primary recovery reservation."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    semantic_label: str = Field(min_length=1)
    primary: ModelCandidateIdentity


class CancelPrimaryModelReservationRequest(BaseModel):
    """Generation-fenced cancellation request for a Session reservation."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    reservation_generation: int = Field(ge=1)
