"""Canonical per-item Routine completion inside the ordinary Session/Run fence."""

import datetime
from dataclasses import dataclass
from typing import Annotated, Literal

from fastapi import Depends

from azents.core.enums import AgentRunStatus
from azents.core.routine import (
    RoutineDeliveryStatus,
    RoutineScope,
    RoutineUnavailable,
    RoutineWorkRecord,
    RoutineWorkResult,
)
from azents.core.routine_execution import RoutineExecutionState
from azents.core.session_resource_authority import (
    SessionExecutionOwner,
    SessionResourceAuthority,
)
from azents.engine.events.types import AgentRunState
from azents.rdb.deps import get_read_only_session_manager, get_session_manager
from azents.rdb.session import SessionManager
from azents.rdb.session_capabilities import ReadSession, WriteSession
from azents.repos.agent_execution import AgentRunRepository
from azents.repos.routine.authority import RoutineExecutionAuthorityRepository
from azents.repos.routine.records import RoutineWorkRecordRepository
from azents.repos.routine.state import RoutineStateRepository
from azents.repos.session_execution.ownership import validate_session_execution_owner


@dataclass(frozen=True)
class RoutineResultRecording:
    """Canonical result plus the sole permission to attempt requested delivery."""

    state: RoutineExecutionState
    record: RoutineWorkRecord | None
    created: bool


@dataclass(frozen=True)
class RoutineCompletionRepository:
    """Settle one occurrence without terminalizing its host or other work."""

    session_manager: Annotated[
        SessionManager[WriteSession], Depends(get_session_manager)
    ]
    read_session_manager: Annotated[
        SessionManager[ReadSession], Depends(get_read_only_session_manager)
    ]
    states: Annotated[RoutineStateRepository, Depends()]
    records: Annotated[RoutineWorkRecordRepository, Depends()]
    runs: Annotated[AgentRunRepository, Depends()]
    execution_authority: Annotated[RoutineExecutionAuthorityRepository, Depends()]

    async def authorize(
        self, *, scope: RoutineScope, authority: SessionResourceAuthority
    ) -> None:
        """Validate exact root, live Run and ordinary owner for tool reads."""
        _require_root_authority(scope, authority)
        async with self.read_session_manager() as session:
            await self.execution_authority.require_execution_scope(
                session, scope=scope, run_id=authority.run_id
            )
            await self._require_run(session, authority=authority)

    async def list_for_idle(
        self, *, scope: RoutineScope, owner: SessionExecutionOwner, run_id: str
    ) -> tuple[RoutineExecutionState, ...]:
        """Read obligations only at the ordinary normal completed-Run boundary."""
        if owner.session_id != scope.session_id:
            raise RoutineUnavailable("Routine idle owner does not match Session.")
        async with self.read_session_manager() as session:
            await self.execution_authority.require_execution_scope(
                session, scope=scope, run_id=run_id
            )
            current = await validate_session_execution_owner(session, owner)
            if current.stop_requested_at is not None:
                return ()
            run = await self.runs.get_by_id(session, run_id)
            if (
                run is None
                or run.session_id != scope.session_id
                or run.status is not AgentRunStatus.COMPLETED
            ):
                return ()
            return tuple(
                item.state
                for item in await self.states.list_executions(session, scope=scope)
                if item.state.phase == "started" and item.state.current_run_id == run_id
            )

    async def observe_delivery(
        self,
        *,
        scope: RoutineScope,
        authority: SessionResourceAuthority,
        recording: RoutineResultRecording,
        status: Literal[RoutineDeliveryStatus.DELIVERED, RoutineDeliveryStatus.FAILED],
        error: str | None,
    ) -> RoutineExecutionState:
        """Observe one immediate effect without recreating records or retry work."""
        _require_root_authority(scope, authority)
        original = recording.state
        async with self.session_manager() as session:
            await self.execution_authority.fence_execution_scope(
                session, scope=scope, authority=authority
            )
            await self._require_run(session, authority=authority)
            current = await self.states.get_occurrence(
                session,
                scope=scope,
                slug=original.context.candidate.slug,
                execution_id=original.context.execution_id,
            )
            if (
                current is None
                or current.state.phase != "completed"
                or current.state.current_run_id != authority.run_id
                or current.state.work != original.work
            ):
                raise RoutineUnavailable(
                    "Routine delivery result is no longer current."
                )
            if current.state.delivery_status is not RoutineDeliveryStatus.UNOBSERVED:
                return current.state
            state = current.state.model_copy(
                update={"delivery_status": status, "delivery_error": error}
            )
            if recording.record is not None:
                await self.records.observe_delivery(
                    session,
                    scope=scope,
                    record_id=recording.record.id,
                    status=status,
                    error=error,
                )
            await self.states.save_execution(
                session, scope=scope, state=state, expected_version=current.version
            )
            return state

    async def context(
        self,
        *,
        scope: RoutineScope,
        authority: SessionResourceAuthority,
        slug: str,
        execution_id: str,
    ) -> RoutineExecutionState:
        """Read exact original context only for the current ordinary host Run."""
        _require_root_authority(scope, authority)
        async with self.read_session_manager() as session:
            await self.execution_authority.require_execution_scope(
                session, scope=scope, run_id=authority.run_id
            )
            await self._require_run(session, authority=authority)
            record = await self.states.get_occurrence(
                session, scope=scope, slug=slug, execution_id=execution_id
            )
            if (
                record is None
                or record.state.current_run_id != authority.run_id
                or record.state.phase not in {"started", "completed"}
            ):
                raise RoutineUnavailable(
                    "Routine occurrence is not available to this Run."
                )
            return record.state

    async def list_started(
        self, *, scope: RoutineScope, authority: SessionResourceAuthority
    ) -> tuple[RoutineExecutionState, ...]:
        """Read current started work for ordinary prompt and idle continuation hooks."""
        _require_root_authority(scope, authority)
        async with self.read_session_manager() as session:
            await self.execution_authority.require_execution_scope(
                session, scope=scope, run_id=authority.run_id
            )
            await self._require_run(session, authority=authority)
            return tuple(
                item.state
                for item in await self.states.list_executions(session, scope=scope)
                if item.state.phase == "started"
                and item.state.current_run_id == authority.run_id
            )

    async def list_for_compaction(
        self, *, scope: RoutineScope, authority: SessionResourceAuthority
    ) -> tuple[RoutineExecutionState, ...]:
        """Read started Session obligations without rebinding execution authority."""
        _require_root_authority(scope, authority)
        async with self.read_session_manager() as session:
            await self.execution_authority.require_execution_scope(
                session, scope=scope, run_id=authority.run_id
            )
            await self._require_run(session, authority=authority)
            return tuple(
                item.state
                for item in await self.states.list_executions(session, scope=scope)
                if item.state.phase == "started"
            )

    async def complete(
        self,
        *,
        scope: RoutineScope,
        authority: SessionResourceAuthority,
        slug: str,
        execution_id: str,
        work: RoutineWorkResult,
        now: datetime.datetime,
    ) -> RoutineResultRecording:
        """Record and close one item atomically; duplicate calls cannot resend."""
        _require_root_authority(scope, authority)
        if now.tzinfo is None or now.utcoffset() is None:
            raise ValueError("Routine completion time must be timezone-aware.")
        async with self.session_manager() as session:
            await self.execution_authority.fence_execution_scope(
                session, scope=scope, authority=authority
            )
            run = await self._require_run(session, authority=authority)
            if run.status is not AgentRunStatus.RUNNING:
                raise RoutineUnavailable(
                    "Routine completion requires its running host."
                )
            record = await self.states.get_occurrence(
                session, scope=scope, slug=slug, execution_id=execution_id
            )
            if record is None or record.state.current_run_id != authority.run_id:
                raise RoutineUnavailable(
                    "Routine occurrence is not available to this Run."
                )
            current = record.state
            if current.phase == "completed":
                if current.work != work:
                    raise RoutineUnavailable(
                        "Routine occurrence already has another result."
                    )
                recent = await self.records.list_recent(
                    session,
                    scope=scope,
                    routine_id=current.context.candidate.routine_id,
                    limit=1,
                )
                saved = (
                    recent[0]
                    if recent and recent[0].execution_id == execution_id
                    else None
                )
                return RoutineResultRecording(
                    state=current, record=saved, created=False
                )
            if current.phase != "started" or current.started_at is None:
                raise RoutineUnavailable(
                    "Routine occurrence has not started or was cancelled."
                )
            saved = await self.records.append(
                session,
                scope=scope,
                routine_id=current.context.candidate.routine_id,
                execution_id=execution_id,
                started_at=current.started_at,
                work=work,
            )
            if saved.record is not None and not saved.created:
                raise RuntimeError(
                    "Routine record exists without completed execution state."
                )
            completed = RoutineExecutionState(
                context=current.context,
                phase="completed",
                current_run_id=current.current_run_id,
                started_at=current.started_at,
                completed_at=now if saved.record is None else saved.record.completed_at,
                work=work,
                delivery_status=(
                    RoutineDeliveryStatus.UNOBSERVED
                    if work.notify
                    else RoutineDeliveryStatus.NOT_REQUESTED
                ),
                delivery_error=None,
            )
            await self.states.save_execution(
                session, scope=scope, state=completed, expected_version=record.version
            )
            return RoutineResultRecording(
                state=completed, record=saved.record, created=True
            )

    async def _require_run(
        self, session: ReadSession, *, authority: SessionResourceAuthority
    ) -> AgentRunState:
        owner = await validate_session_execution_owner(
            session, authority.execution_owner
        )
        if owner.stop_requested_at is not None:
            raise RoutineUnavailable("Routine execution was stopped.")
        run = await self.runs.get_by_id(session, authority.run_id)
        if (
            run is None
            or run.session_id != authority.session_id
            or run.run_index != authority.run_index
            or run.status not in {AgentRunStatus.PENDING, AgentRunStatus.RUNNING}
        ):
            raise RoutineUnavailable(
                "Routine execution authority is no longer current."
            )
        return run


def _require_root_authority(
    scope: RoutineScope, authority: SessionResourceAuthority
) -> None:
    if (
        authority.workspace_id != scope.workspace_id
        or authority.agent_id != scope.agent_id
        or authority.session_id != scope.session_id
        or authority.root_session_id != scope.session_id
    ):
        raise RoutineUnavailable(
            "Routine tools require their exact root Session authority."
        )
