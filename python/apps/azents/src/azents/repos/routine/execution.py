"""Routine occurrence transitions inside ordinary Session FIFO transactions."""

import datetime
from dataclasses import dataclass
from typing import Annotated

from fastapi import Depends

from azents.core.enums import AgentRunStatus, AgentSessionStatus
from azents.core.routine import RoutineScope
from azents.core.routine_execution import RoutineExecutionRef, RoutineExecutionState
from azents.core.routine_presentation import routine_execution_ref
from azents.engine.events.types import AgentRunState
from azents.rdb.session_capabilities import WriteSession
from azents.repos.routine.state import RoutineStateRepository


@dataclass(frozen=True)
class RoutineExecutionRepository:
    """Use the consuming ordinary Run without a separate Routine Run owner."""

    states: Annotated[RoutineStateRepository, Depends(RoutineStateRepository)]

    async def bind_retry(
        self,
        session: WriteSession,
        *,
        scope: RoutineScope,
        source: AgentRunState,
        target: AgentRunState,
    ) -> None:
        """Carry only unfinished source occurrences through explicit ordinary retry."""
        if (
            source.session_id != scope.session_id
            or target.session_id != scope.session_id
            or source.status is not AgentRunStatus.FAILED
            or target.status is not AgentRunStatus.PENDING
            or source.id == target.id
        ):
            raise ValueError("Routine retry requires the failed and new pending host.")
        for record in await self.states.list_executions(session, scope=scope):
            current = record.state
            if current.phase != "started" or current.current_run_id != source.id:
                continue
            await self.states.save_execution(
                session,
                scope=scope,
                state=current.model_copy(update={"current_run_id": target.id}),
                expected_version=record.version,
            )

    async def bind_input(
        self,
        session: WriteSession,
        *,
        scope: RoutineScope,
        refs: tuple[RoutineExecutionRef, ...],
        run_id: str,
        continuation: bool,
        session_status: AgentSessionStatus,
        now: datetime.datetime,
    ) -> tuple[RoutineExecutionState, ...]:
        """Start or rebind valid occurrences under the caller's FIFO/Session fence."""
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
            elif (
                current.phase != "admitted"
                or session_status is not AgentSessionStatus.ACTIVE
            ):
                continue
            state = RoutineExecutionState(
                context=current.context,
                phase="started",
                current_run_id=run_id,
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
