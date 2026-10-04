"""Exact-scope identities and current-source evidence for consolidation work."""

import datetime
import enum
import hashlib
import json
from typing import assert_never

from pydantic import BaseModel, ConfigDict, Field, model_validator

from azents.core.historical_memory import HistoricalMemoryCompletion


class ConsolidationScope(enum.StrEnum):
    """One independent input corpus, never a combined foreground consumer view."""

    TEAM = "team"
    USER = "user"


class ConsolidationWorkKind(enum.StrEnum):
    """Source changes enrolled without retaining a second body history."""

    PREPARED = "prepared"
    REMOVED = "removed"
    RESTORED = "restored"


class ConsolidationDisposition(enum.StrEnum):
    """Explicit private work choice, independent from evidence exposure."""

    CONSIDERED = "considered"
    OMITTED = "omitted"


class ConsolidationWorkState(enum.StrEnum):
    """Exact work disposition, independent of the current published overview."""

    PENDING = "pending"
    CONSIDERED = "considered"
    PUBLISHED = "published"
    SUPERSEDED = "superseded"


class ConsolidationAttemptState(enum.StrEnum):
    """Internal attempt lifecycle, not a foreground Run state."""

    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    INVALIDATED = "invalidated"


class ConsolidationUnitKey(BaseModel):
    """Server-owned identity of an independently maintained overview."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    agent_id: str = Field(min_length=32, max_length=32)
    workspace_id: str = Field(min_length=32, max_length=32)
    scope: ConsolidationScope
    associated_user_id: str | None = Field(min_length=32, max_length=32)

    @model_validator(mode="after")
    def validate_scope_owner(self) -> "ConsolidationUnitKey":
        """Require a User exactly for personal scope, without scope widening."""
        match self.scope:
            case ConsolidationScope.TEAM:
                if self.associated_user_id is not None:
                    raise ValueError(
                        "Team consolidation must not have an associated User."
                    )
            case ConsolidationScope.USER:
                if self.associated_user_id is None:
                    raise ValueError(
                        "Personal consolidation requires an associated User."
                    )
            case _:
                assert_never(self.scope)
        return self


class ConsolidationJobPrincipal(BaseModel):
    """Internal attempt identity, not a fabricated foreground Session or Run."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    unit: ConsolidationUnitKey
    attempt_id: str = Field(min_length=32, max_length=32)
    owner_generation: int = Field(ge=1)
    owner_token: str = Field(min_length=32, max_length=32)


class ConsolidationSourceVersion(BaseModel):
    """Body-free evidence identity; current authority is checked separately."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    source_session_id: str = Field(min_length=32, max_length=32)
    summary_generation: int = Field(ge=1)
    evidence_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    availability_generation: int = Field(ge=1)
    membership_grant_id: str | None = Field(min_length=32, max_length=32)


def prepared_source_evidence_hash(completion: HistoricalMemoryCompletion) -> str:
    """Hash the exact published summary and its model-visible preparation metadata.

    Normalize aware instants to UTC and the summary to the existing repository's
    empty-result representation. Preserve exact title/summary Unicode bytes and
    whitespace; this is evidence identity, not semantic deduplication or a grant.
    """
    payload = {
        "schema_version": 1,
        "summary": completion.summary or None,
        "source_title": completion.source_title_snapshot,
        "source_activity_at": completion.source_activity_at.astimezone(
            datetime.UTC
        ).isoformat(),
        "source_tail_event_id": completion.source_tail_event_id,
        "prepared_at": completion.prepared_at.astimezone(datetime.UTC).isoformat(),
    }
    encoded = json.dumps(
        payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()
