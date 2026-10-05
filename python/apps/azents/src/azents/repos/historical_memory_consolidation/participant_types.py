"""Ephemeral participant discovery requests; none is execution authority."""

from dataclasses import dataclass


class ConsolidationPlanChangedError(RuntimeError):
    """A local planning snapshot changed; its transaction must roll back."""


@dataclass(frozen=True)
class DraftParticipants:
    """Plan draft/exposure influence and optionally the recovery publication."""

    recovery: bool


@dataclass(frozen=True)
class SourceReadParticipants:
    source_session_id: str


@dataclass(frozen=True)
class SourceInventoryParticipants:
    after: str | None
    limit: int
    source_id_prefix: str | None


@dataclass(frozen=True)
class WorkPageParticipants:
    after_sequence: int | None
    limit: int


type ConsolidationParticipantRequest = (
    DraftParticipants
    | SourceReadParticipants
    | SourceInventoryParticipants
    | WorkPageParticipants
)
