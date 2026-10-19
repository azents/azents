"""Typed Session Toolkit State for Routine checks and admitted occurrences."""

import datetime
from typing import Literal, Self, assert_never

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from azents.core.routine import RoutineDeliveryStatus, RoutineScope, RoutineWorkResult
from azents.core.routine_judgment import RoutineJudgmentCandidate, RoutineSourceEvent


def _aware(value: datetime.datetime | None) -> datetime.datetime | None:
    if value is not None and (value.tzinfo is None or value.utcoffset() is None):
        raise ValueError("Routine state timestamps must be timezone-aware.")
    return value


class RoutineExecutionRef(BaseModel):
    """Exact admitted occurrence identity and its small display projection."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    routine_id: str = Field(min_length=1)
    execution_id: str = Field(min_length=1)
    slug: str = Field(min_length=1)
    title: str = Field(min_length=1)


def validate_routine_execution_refs(refs: tuple[RoutineExecutionRef, ...]) -> None:
    """Reject empty or duplicated occurrence references at typed ingress."""
    if not refs:
        raise ValueError("Routine input requires admitted occurrence identities.")
    routines = [item.routine_id for item in refs]
    executions = [item.execution_id for item in refs]
    if len(routines) != len(set(routines)) or len(executions) != len(set(executions)):
        raise ValueError("Routine input occurrence identities must be unique.")


class RoutineSourceInput(BaseModel):
    """Retained source input consumed by an ordinary inbox judgment action."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    routine_id: str = Field(min_length=1)
    events: tuple[RoutineSourceEvent, ...] = Field(min_length=1)


class RoutineCheckState(BaseModel):
    """Source/delay continuity and dedup identity of the ordinary inbox action."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    last_tick_at: datetime.datetime | None
    last_action_at: datetime.datetime | None
    source_inputs: tuple[RoutineSourceInput, ...]
    queued_judgment_id: str | None = Field(min_length=1)

    @field_validator("last_tick_at", "last_action_at")
    @classmethod
    def require_aware_history(
        cls, value: datetime.datetime | None
    ) -> datetime.datetime | None:
        return _aware(value)

    @model_validator(mode="after")
    def unique_source_inputs(self) -> Self:
        ids = [item.routine_id for item in self.source_inputs]
        if len(ids) != len(set(ids)):
            raise ValueError("Routine source input identities must be unique.")
        return self


class RoutineAdmittedContext(BaseModel):
    """Immutable occurrence context; later definition edits cannot redirect it."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    execution_id: str = Field(min_length=1)
    judgment_id: str = Field(min_length=1)
    scope: RoutineScope
    candidate: RoutineJudgmentCandidate
    admitted_at: datetime.datetime

    @field_validator("admitted_at")
    @classmethod
    def require_aware_admission(cls, value: datetime.datetime) -> datetime.datetime:
        _aware(value)
        return value


class RoutineExecutionState(BaseModel):
    """Scheduled-style admitted/started state with independent item settlement."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    context: RoutineAdmittedContext
    phase: Literal["admitted", "started", "completed", "cancelled"]
    current_run_id: str | None
    started_at: datetime.datetime | None
    completed_at: datetime.datetime | None
    work: RoutineWorkResult | None
    delivery_status: RoutineDeliveryStatus | None
    delivery_error: str | None

    @field_validator("started_at", "completed_at")
    @classmethod
    def require_aware_execution_time(
        cls, value: datetime.datetime | None
    ) -> datetime.datetime | None:
        return _aware(value)

    @model_validator(mode="after")
    def validate_phase(self) -> Self:
        if (self.current_run_id is None) != (self.started_at is None):
            raise ValueError("Routine started time and current Run must agree.")
        match self.phase:
            case "admitted":
                if self.current_run_id is not None or self.completed_at is not None:
                    raise ValueError("Admitted Routine work has not started.")
            case "started":
                if self.current_run_id is None or self.completed_at is not None:
                    raise ValueError("Started Routine work requires its current Run.")
            case "completed":
                if (
                    self.current_run_id is None
                    or self.completed_at is None
                    or self.work is None
                    or self.delivery_status is None
                ):
                    raise ValueError(
                        "Completed Routine work requires its saved outcome."
                    )
                if self.work.notify:
                    if self.delivery_status is RoutineDeliveryStatus.NOT_REQUESTED:
                        raise ValueError(
                            "Requested notification needs a delivery outcome."
                        )
                elif self.delivery_status is not RoutineDeliveryStatus.NOT_REQUESTED:
                    raise ValueError(
                        "Silent Routine work cannot have a delivery attempt."
                    )
            case "cancelled":
                if self.completed_at is None:
                    raise ValueError("Cancelled Routine work requires a closure time.")
            case _ as unreachable:
                assert_never(unreachable)
        if self.phase != "completed" and (
            self.work is not None
            or self.delivery_status is not None
            or self.delivery_error is not None
        ):
            raise ValueError("Only completed Routine work has a result or delivery.")
        if self.delivery_error is not None and (
            self.delivery_status is not RoutineDeliveryStatus.FAILED
        ):
            raise ValueError("Only failed Routine delivery has an error.")
        return self

    @property
    def incomplete(self) -> bool:
        """Only admitted or started work excludes another occurrence."""
        return self.phase in {"admitted", "started"}
