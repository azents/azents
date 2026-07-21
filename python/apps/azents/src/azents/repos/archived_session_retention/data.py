"""Archived-session retention repository data models."""

import dataclasses
import datetime
from typing import Literal

from pydantic import BaseModel, Field

from azents.core.enums import (
    ArchivedSessionPurgeParticipantPhase,
    ArchivedSessionPurgeStatus,
    ArchivedSessionRetentionApplicationStatus,
)

RetentionApplicationScope = Literal["new_archives_only", "recalculate_existing"]


class SystemFileLifecycleSettings(BaseModel):
    """Instance-wide file lifecycle settings."""

    archived_session_retention_days: int | None = Field(
        ge=0,
        description="Whole-day archive retention; null means Unlimited",
    )
    revision: int = Field(ge=1, description="Optimistic settings revision")
    updated_by_user_id: str | None = Field(description="Latest administrator ID")
    created_at: datetime.datetime = Field(description="Created timestamp")
    updated_at: datetime.datetime = Field(description="Updated timestamp")


class RetentionImpactPreview(BaseModel):
    """Impact of applying one retention value to existing archives."""

    affected_count: int = Field(ge=0)
    immediately_eligible_count: int = Field(ge=0)
    cancelled_count: int = Field(ge=0)
    scheduled_count: int = Field(ge=0)
    excluded_count: int = Field(ge=0)


class ArchivedSessionRetentionApplication(BaseModel):
    """Durable existing-archive retention application."""

    id: str
    target_revision: int
    target_retention_days: int | None
    requested_by_user_id: str | None
    status: ArchivedSessionRetentionApplicationStatus
    cursor_session_id: str | None
    affected_count: int
    immediately_eligible_count: int
    cancelled_count: int
    scheduled_count: int
    skipped_count: int
    attempt_count: int
    lease_owner: str | None
    lease_until: datetime.datetime | None
    next_attempt_at: datetime.datetime | None
    last_error_kind: str | None
    last_error_summary: str | None
    started_at: datetime.datetime | None
    completed_at: datetime.datetime | None
    created_at: datetime.datetime
    updated_at: datetime.datetime


class ArchivedSessionPurgeJob(BaseModel):
    """Durable purge work for one archived root."""

    id: str
    root_session_id: str
    eligible_at: datetime.datetime
    policy_revision: int
    status: ArchivedSessionPurgeStatus
    fencing_started_at: datetime.datetime | None
    attempt_count: int
    lease_owner: str | None
    lease_until: datetime.datetime | None
    next_attempt_at: datetime.datetime | None
    last_error_kind: str | None
    last_error_summary: str | None
    last_error_participant_key: str | None
    last_error_phase: ArchivedSessionPurgeParticipantPhase | None
    model_file_count: int
    artifact_count: int
    exchange_file_count: int
    worktree_count: int
    started_at: datetime.datetime | None
    last_attempt_at: datetime.datetime | None
    cancelled_at: datetime.datetime | None
    completed_at: datetime.datetime | None
    created_at: datetime.datetime
    updated_at: datetime.datetime


class ArchivedSessionPurgeParticipantExecution(BaseModel):
    """Durable checkpoint for one participant selected by a fenced purge job."""

    purge_job_id: str
    participant_key: str
    policy_version: int
    phase: ArchivedSessionPurgeParticipantPhase
    attempt_count: int
    blocked_by_participant_key: str | None
    last_error_kind: str | None
    last_error_summary: str | None
    operational_summary: dict[str, object] | None
    prepared_at: datetime.datetime | None
    cleanup_completed_at: datetime.datetime | None
    verified_at: datetime.datetime | None
    last_attempt_at: datetime.datetime | None
    created_at: datetime.datetime
    updated_at: datetime.datetime


@dataclasses.dataclass(frozen=True)
class ArchivedSessionPurgeParticipantSnapshot:
    """One stable participant policy version materialized at purge fencing."""

    participant_key: str
    policy_version: int


@dataclasses.dataclass(frozen=True)
class RetentionBatchResult:
    """Outcome of scanning one bounded recalculation batch."""

    scanned_count: int
    affected_count: int
    immediately_eligible_count: int
    cancelled_count: int
    scheduled_count: int
    skipped_count: int
    cursor_session_id: str | None
