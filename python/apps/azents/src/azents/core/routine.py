"""Session Routine content, completion, and detached persistence contracts."""

import datetime
import enum
from dataclasses import dataclass
from typing import Literal, Self, TypedDict

from pydantic import BaseModel, ConfigDict, field_validator, model_validator

MAX_ROUTINES_PER_SESSION = 20
MAX_ROUTINE_WORK_RECORDS = 100
ROUTINE_TICK_INTERVAL = datetime.timedelta(minutes=30)


class RoutineObjectiveOutcome(enum.StrEnum):
    """Objective achievement, distinct from recording or message delivery."""

    FINISHED = "finished"
    FAILED = "failed"


class RoutineDeliveryStatus(enum.StrEnum):
    """Observed publication outcome, never a retry queue."""

    NOT_REQUESTED = "not_requested"
    UNOBSERVED = "unobserved"
    DELIVERED = "delivered"
    FAILED = "failed"


class ManualRoutineSource(BaseModel):
    """Candidate input at eligible checks without a manual user action."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    type: Literal["manual"]


class RoutineContent(BaseModel):
    """Exactly comparable editable content with no implicit text rewriting."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    title: str
    objective: str
    sources: tuple[ManualRoutineSource, ...]

    @field_validator("title", "objective")
    @classmethod
    def require_content(cls, value: str) -> str:
        """Reject blank content while preserving exact accepted text."""
        if not value.strip():
            raise ValueError("Routine title and objective must not be blank.")
        return value


class RoutineChanges(TypedDict, total=False):
    """Omission preserves content; supplied values are validated normally."""

    title: str
    objective: str
    sources: tuple[ManualRoutineSource, ...]


class RoutineContentConflict(ValueError):
    """The provided prior content does not match the current definition."""


class RoutineUnavailable(ValueError):
    """The authorized Session or Routine is unavailable."""


class RoutineLimitReached(ValueError):
    """The Session already contains the permitted number of definitions."""


def update_routine_content(
    *,
    current: RoutineContent,
    expected: RoutineContent,
    changes: RoutineChanges,
) -> RoutineContent:
    """Apply separate changes only after comparing the complete prior content."""
    if current != expected:
        raise RoutineContentConflict(
            "Routine content changed. Read the current content before updating."
        )
    return RoutineContent.model_validate({**current.model_dump(), **changes})


class RoutineWorkResult(BaseModel):
    """One completed objective and independently chosen user notification."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    objective_outcome: RoutineObjectiveOutcome
    result: str
    next_hint: str
    notify: bool
    message: str | None

    @field_validator("result", "next_hint")
    @classmethod
    def require_record_text(cls, value: str) -> str:
        """Preserve text without imposing a sentence parser or length cap."""
        if not value.strip():
            raise ValueError("Routine result and next hint must not be blank.")
        return value

    @model_validator(mode="after")
    def validate_notification(self) -> Self:
        """Enforce the message/notification relationship at runtime."""
        if self.notify:
            if self.message is None or not self.message.strip():
                raise ValueError("Routine notification requires a user message.")
        elif self.message is not None:
            raise ValueError("A silent Routine result must not include a message.")
        return self


@dataclass(frozen=True)
class RoutineScope:
    """Exact durable owner identity, not permission supplied by a model."""

    workspace_id: str
    agent_id: str
    session_id: str


@dataclass(frozen=True)
class RoutineDefinition:
    """Detached definition returned after a complete repository operation."""

    id: str
    scope: RoutineScope
    slug: str
    content: RoutineContent
    created_at: datetime.datetime
    updated_at: datetime.datetime


@dataclass(frozen=True)
class RoutineWorkRecord:
    """Retained work with recording, objective, and delivery kept distinct."""

    id: str
    routine_id: str
    execution_id: str
    started_at: datetime.datetime
    completed_at: datetime.datetime
    work: RoutineWorkResult
    delivery_status: RoutineDeliveryStatus
    delivery_error: str | None
