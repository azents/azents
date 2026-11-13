"""Routine occurrence transitions inside ordinary Session FIFO transactions."""

import datetime
from dataclasses import dataclass
from typing import Annotated

from fastapi import Depends

from azents.core.enums import AgentSessionStatus
from azents.core.routine import RoutineScope
from azents.core.routine_execution import RoutineExecutionRef, RoutineExecutionState
from azents.core.routine_presentation import routine_execution_ref
from azents.core.work_context import WorkContext
from azents.rdb.session_capabilities import WriteSession
from azents.repos.routine.state import RoutineStateRepository


@dataclass(frozen=True)
class RoutineExecutionRepository:
    """Use the consuming ordinary Run without a separate Routine Run owner."""

    states: Annotated[RoutineStateRepository, Depends(RoutineStateRepository)]

    async def retry_context(
        self,
        session: WriteSession,
        *,
        scope: RoutineScope,
        context: WorkContext,
    ) -> WorkContext:
        """Preserve only exact unfinished work without rewriting its owner."""
        refs: list[RoutineExecutionRef] = []
        for ref in context.routine_executions:
            record = await self.states.get_execution(
                session, scope=scope, routine_id=ref.routine_id
            )
            if (
                record is not None
                and record.state.phase == "started"
                and routine_execution_ref(record.state) == ref
            ):
                refs.append(ref)
        return context.model_copy(update={"routine_executions": tuple(refs)})

    async def bind_input(
        self,
        session: WriteSession,
        *,
        scope: RoutineScope,
        refs: tuple[RoutineExecutionRef, ...],
        continuation: bool,
        session_status: AgentSessionStatus,
        now: datetime.datetime,
    ) -> tuple[RoutineExecutionState, ...]:
        """Start exact work once; continuation never reassigns domain ownership."""
        bound: list[RoutineExecutionState] = []
        for ref in refs:
            record = await self.states.get_execution(
                session, scope=scope, routine_id=ref.routine_id
            )
            if record is None or routine_execution_ref(record.state) != ref:
                continue
            current = record.state
            if continuation:
                if current.phase != "started":
                    continue
                bound.append(current)
                continue
            elif (
                current.phase != "admitted"
                or session_status is not AgentSessionStatus.ACTIVE
            ):
                continue
            state = RoutineExecutionState(
                context=current.context,
                phase="started",
                started_at=current.started_at if continuation else now,
                completed_at=None,
                work=None,
                delivery_status=None,
                delivery_error=None,
            )
            await self.states.save_execution(
                session,
                scope=scope,
                state=state,
                expected_version=record.version,
            )
            bound.append(state)
        return tuple(bound)
