"""Model candidate health repository data models."""

import datetime
import enum

from pydantic import BaseModel, ConfigDict, Field

from azents.core.enums import ModelCandidateClaimKind


class ModelCandidateIdentity(BaseModel):
    """Workspace-scoped physical model candidate identity."""

    model_config = ConfigDict(extra="forbid")

    workspace_id: str = Field(min_length=1, max_length=32)
    llm_provider_integration_id: str = Field(min_length=1, max_length=32)
    model_identifier: str = Field(min_length=1)


class ModelCandidateHealthStatus(enum.StrEnum):
    """Database-derived candidate availability state."""

    AVAILABLE = "available"
    COOLDOWN = "cooldown"
    RECOVERY_PENDING = "recovery_pending"
    CLAIMED = "claimed"


class ModelCandidateHealthSnapshot(BaseModel):
    """Detached durable health and claim authority."""

    identity: ModelCandidateIdentity
    generation: int = Field(ge=1)
    cooldown_until: datetime.datetime
    claim_kind: ModelCandidateClaimKind | None
    claim_owner_id: str | None
    claim_token: str | None
    claim_until: datetime.datetime | None
    created_at: datetime.datetime
    updated_at: datetime.datetime


class ModelCandidateHealthObservation(BaseModel):
    """Candidate health interpreted using authoritative database time."""

    server_time: datetime.datetime
    status: ModelCandidateHealthStatus
    health: ModelCandidateHealthSnapshot | None


class ForegroundProbeOutcome(enum.StrEnum):
    """Result of trying to acquire foreground half-open authority."""

    HEALTHY = "healthy"
    COOLDOWN = "cooldown"
    BUSY = "busy"
    CLAIMED = "claimed"


class ForegroundProbeResult(BaseModel):
    """Foreground half-open probe claim result."""

    outcome: ForegroundProbeOutcome
    observation: ModelCandidateHealthObservation


class ReservationClaimOutcome(enum.StrEnum):
    """Result of trying to reserve one candidate recovery opportunity."""

    HEALTHY = "healthy"
    BUSY = "busy"
    CLAIMED = "claimed"
    IDEMPOTENT = "idempotent"


class ReservationClaimResult(BaseModel):
    """Session reservation claim result."""

    outcome: ReservationClaimOutcome
    observation: ModelCandidateHealthObservation


class CandidateClaimTransfer(BaseModel):
    """Transferred foreground probe authority."""

    server_time: datetime.datetime
    health: ModelCandidateHealthSnapshot


class CandidateHealthSettlement(enum.StrEnum):
    """Result of an owner- and generation-fenced health transition."""

    APPLIED = "applied"
    STALE = "stale"
