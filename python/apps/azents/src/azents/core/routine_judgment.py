"""Typed joint Routine judgment contracts without execution or tool authority."""

import datetime
from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from azents.core.routine import RoutineContent, RoutineWorkResult


class RoutineSourceEvent(BaseModel):
    """A supported source's candidate input, separate from an execution command."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    source_type: Literal["manual"]
    observed_at: datetime.datetime

    @field_validator("observed_at")
    @classmethod
    def require_aware_time(cls, value: datetime.datetime) -> datetime.datetime:
        """Reject an ambiguous timestamp before judgment or persistence."""
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("Routine event time must be timezone-aware.")
        return value


class RoutineJudgmentCandidate(BaseModel):
    """Exact candidate context read for one joint judgment operation."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    routine_id: str
    slug: str
    content: RoutineContent
    events: tuple[RoutineSourceEvent, ...]
    last_executed_at: datetime.datetime | None
    latest_work: RoutineWorkResult | None

    @model_validator(mode="after")
    def require_candidate_event(self) -> Self:
        """Empty source input must be filtered before a model call."""
        if not self.events:
            raise ValueError("A Routine judgment candidate must have source input.")
        if self.last_executed_at is not None and (
            self.last_executed_at.tzinfo is None
            or self.last_executed_at.utcoffset() is None
        ):
            raise ValueError("Routine last execution time must be timezone-aware.")
        return self


class RoutineActionDecision(BaseModel):
    """Action selection only: it neither creates objectives nor invokes tools."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    routine_id: str
    act: bool = Field(strict=True)


class RoutineJudgmentDecision(BaseModel):
    """One Structured decision for every supplied candidate identity."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    decisions: tuple[RoutineActionDecision, ...]

    @model_validator(mode="after")
    def unique_identities(self) -> Self:
        """Duplicate selections are invalid output, not another occurrence."""
        ids = [decision.routine_id for decision in self.decisions]
        if len(ids) != len(set(ids)):
            raise ValueError(
                "Routine judgment contains duplicate candidate identities."
            )
        return self

    def validate_candidates(
        self, candidates: tuple[RoutineJudgmentCandidate, ...]
    ) -> Self:
        """Reject foreign or omitted identities instead of inventing no-action."""
        expected = {candidate.routine_id for candidate in candidates}
        if len(expected) != len(candidates):
            raise ValueError("Routine judgment input contains duplicate candidates.")
        if {decision.routine_id for decision in self.decisions} != expected:
            raise ValueError(
                "Routine judgment must decide every supplied candidate only."
            )
        return self


class RoutineJudgmentConsidered(BaseModel):
    """Small retained identity/title projection, not a second definition store."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    routine_id: str
    slug: str
    title: str


JUDGMENT_INSTRUCTIONS = """Judge the supplied Session Routine candidates together.
Use the Session conversation and each candidate's stored objective, source input,
last execution time, latest work result, and next-check hint to decide whether
this occurrence needs action now. Periodic preferences belong to the objective;
do not confuse a checking opportunity with a mandatory output obligation.
Return exactly one Structured decision for each supplied routine_id. Set act to
true only when work is needed. Do not create a new objective, execute tools,
write a user notification, or generate a free-form decision explanation.
"""


def render_judgment_input(candidates: tuple[RoutineJudgmentCandidate, ...]) -> str:
    """Render only the final request; canonical conversation stays structured."""
    if not candidates:
        raise ValueError("Empty Routine candidates do not require a model call.")
    ids = [candidate.routine_id for candidate in candidates]
    if len(ids) != len(set(ids)):
        raise ValueError("Routine judgment input contains duplicate candidates.")
    return (
        JUDGMENT_INSTRUCTIONS
        + "\nCandidates:\n["
        + ",\n".join(candidate.model_dump_json() for candidate in candidates)
        + "]"
    )
