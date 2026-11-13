"""Exact work references carried independently of execution-segment identity."""

from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, model_validator

from azents.core.routine_execution import RoutineExecutionRef


class WorkContext(BaseModel):
    """Server-admitted work and provenance carried by an execution segment."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    scheduled_cycle_ids: tuple[Annotated[str, Field(min_length=32, max_length=32)], ...]
    routine_executions: tuple[RoutineExecutionRef, ...]
    unrelated_input: bool

    @model_validator(mode="after")
    def unique_occurrences(self) -> "WorkContext":
        """Reject contradictory identities instead of silently dropping work."""
        executions = [ref.execution_id for ref in self.routine_executions]
        if len(executions) != len(set(executions)):
            raise ValueError("Work context occurrence identities must be unique.")
        if len(self.scheduled_cycle_ids) != len(set(self.scheduled_cycle_ids)):
            raise ValueError("Work context Scheduled cycle identities must be unique.")
        return self

    @classmethod
    def empty(cls) -> "WorkContext":
        """Return an execution with no admitted work or consumed ordinary input."""
        return cls(
            scheduled_cycle_ids=(),
            routine_executions=(),
            unrelated_input=False,
        )

    def merge(self, other: "WorkContext") -> "WorkContext":
        """Combine admitted input without changing any domain's work lifecycle."""
        refs = {ref.execution_id: ref for ref in self.routine_executions}
        for ref in other.routine_executions:
            existing = refs.get(ref.execution_id)
            if existing is not None and existing != ref:
                raise ValueError("Work context has conflicting Routine occurrences.")
            refs[ref.execution_id] = ref
        return WorkContext(
            scheduled_cycle_ids=tuple(
                dict.fromkeys((*self.scheduled_cycle_ids, *other.scheduled_cycle_ids))
            ),
            routine_executions=tuple(refs.values()),
            unrelated_input=self.unrelated_input or other.unrelated_input,
        )

    def contains_routine(self, *, routine_id: str, execution_id: str) -> bool:
        """Test the exact occurrence rather than a definition or host Run."""
        return any(
            ref.routine_id == routine_id and ref.execution_id == execution_id
            for ref in self.routine_executions
        )

    @property
    def scheduled_only(self) -> bool:
        """Preserve the archive exception only for unmixed Scheduled work."""
        return bool(self.scheduled_cycle_ids) and (
            not self.routine_executions and not self.unrelated_input
        )

    @property
    def routine_only(self) -> bool:
        """Preserve the existing narrow archive exception for Routine-only work."""
        return bool(self.routine_executions) and (
            not self.scheduled_cycle_ids and not self.unrelated_input
        )
