"""Typed Routine state in the existing Session Toolkit State storage boundary."""

import datetime
from dataclasses import dataclass
from typing import Annotated

import sqlalchemy as sa
from fastapi import Depends

from azents.core.routine import RoutineScope, RoutineUnavailable
from azents.core.routine_execution import RoutineCheckState, RoutineExecutionState
from azents.rdb.models.toolkit_state import RDBToolkitState
from azents.rdb.session_capabilities import ReadSession, WriteSession
from azents.repos.toolkit_state import ToolkitStateRepository
from azents.repos.toolkit_state.data import ToolkitStateUpsert

ROUTINE_STATE_NAMESPACE = "routines"
ROUTINE_CHECK_STATE_NAME = "check"
_EXECUTION_PREFIX = "execution:"


@dataclass(frozen=True)
class RoutineStateRecord[T]:
    """A decoded state plus its existing storage mutation fence."""

    toolkit_state_id: str
    version: int
    state: T


@dataclass(frozen=True)
class RoutineStateRepository:
    """Persist check continuity and per-definition admitted snapshots without I/O."""

    toolkit_states: Annotated[ToolkitStateRepository, Depends(ToolkitStateRepository)]

    async def get_check(
        self, session: ReadSession, *, scope: RoutineScope
    ) -> RoutineStateRecord[RoutineCheckState] | None:
        record = await self.toolkit_states.get(
            session,
            agent_id=scope.agent_id,
            session_id=scope.session_id,
            toolkit_namespace=ROUTINE_STATE_NAMESPACE,
            state_name=ROUTINE_CHECK_STATE_NAME,
        )
        if record is None:
            return None
        if record.schema_version != 1:
            raise ValueError("Unsupported Routine check state schema.")
        return RoutineStateRecord(
            toolkit_state_id=record.id,
            version=record.version,
            state=RoutineCheckState.model_validate(record.state_json),
        )

    async def save_check(
        self,
        session: WriteSession,
        *,
        scope: RoutineScope,
        state: RoutineCheckState,
        expected_version: int | None,
    ) -> RoutineStateRecord[RoutineCheckState]:
        record = await self.toolkit_states.save(
            session,
            ToolkitStateUpsert(
                agent_id=scope.agent_id,
                session_id=scope.session_id,
                toolkit_namespace=ROUTINE_STATE_NAMESPACE,
                state_name=ROUTINE_CHECK_STATE_NAME,
                state_json=state.model_dump(mode="json"),
                schema_version=1,
                expected_version=expected_version,
            ),
        )
        return RoutineStateRecord(
            toolkit_state_id=record.id, version=record.version, state=state
        )

    async def get_execution(
        self,
        session: ReadSession,
        *,
        scope: RoutineScope,
        routine_id: str,
    ) -> RoutineStateRecord[RoutineExecutionState] | None:
        record = await self.toolkit_states.get(
            session,
            agent_id=scope.agent_id,
            session_id=scope.session_id,
            toolkit_namespace=ROUTINE_STATE_NAMESPACE,
            state_name=_EXECUTION_PREFIX + routine_id,
        )
        if record is None:
            return None
        if record.schema_version != 1:
            raise ValueError("Unsupported Routine execution state schema.")
        state = RoutineExecutionState.model_validate(record.state_json)
        self._require_scope(state, scope=scope, routine_id=routine_id)
        return RoutineStateRecord(
            toolkit_state_id=record.id, version=record.version, state=state
        )

    async def get_occurrence(
        self,
        session: ReadSession,
        *,
        scope: RoutineScope,
        slug: str,
        execution_id: str,
    ) -> RoutineStateRecord[RoutineExecutionState] | None:
        """Read one exact admitted identity, including a deleted definition's work."""
        result = await session.read_session.execute(
            sa.select(RDBToolkitState)
            .where(
                RDBToolkitState.agent_id == scope.agent_id,
                RDBToolkitState.session_id == scope.session_id,
                RDBToolkitState.toolkit_namespace == ROUTINE_STATE_NAMESPACE,
                RDBToolkitState.state_name.startswith(_EXECUTION_PREFIX),
                RDBToolkitState.state_json["context"]["execution_id"].astext
                == execution_id,
                RDBToolkitState.state_json["context"]["candidate"]["slug"].astext
                == slug,
            )
            .execution_options(populate_existing=True)
        )
        row = result.scalar_one_or_none()
        if row is None:
            return None
        if row.schema_version != 1:
            raise ValueError("Unsupported Routine execution state schema.")
        state = RoutineExecutionState.model_validate(row.state_json)
        self._require_scope(
            state,
            scope=scope,
            routine_id=row.state_name.removeprefix(_EXECUTION_PREFIX),
        )
        return RoutineStateRecord(
            toolkit_state_id=row.id, version=row.version, state=state
        )

    async def list_executions(
        self, session: ReadSession, *, scope: RoutineScope
    ) -> list[RoutineStateRecord[RoutineExecutionState]]:
        rows = await session.read_session.scalars(
            sa.select(RDBToolkitState)
            .where(
                RDBToolkitState.agent_id == scope.agent_id,
                RDBToolkitState.session_id == scope.session_id,
                RDBToolkitState.toolkit_namespace == ROUTINE_STATE_NAMESPACE,
                RDBToolkitState.state_name.startswith(_EXECUTION_PREFIX),
            )
            .order_by(RDBToolkitState.state_name)
            .execution_options(populate_existing=True)
        )
        result: list[RoutineStateRecord[RoutineExecutionState]] = []
        for row in rows:
            if row.schema_version != 1:
                raise ValueError("Unsupported Routine execution state schema.")
            state = RoutineExecutionState.model_validate(row.state_json)
            self._require_scope(
                state,
                scope=scope,
                routine_id=row.state_name.removeprefix(_EXECUTION_PREFIX),
            )
            result.append(
                RoutineStateRecord(
                    toolkit_state_id=row.id, version=row.version, state=state
                )
            )
        return result

    async def save_execution(
        self,
        session: WriteSession,
        *,
        scope: RoutineScope,
        state: RoutineExecutionState,
        expected_version: int | None,
    ) -> RoutineStateRecord[RoutineExecutionState]:
        self._require_scope(
            state, scope=scope, routine_id=state.context.candidate.routine_id
        )
        record = await self.toolkit_states.save(
            session,
            ToolkitStateUpsert(
                agent_id=scope.agent_id,
                session_id=scope.session_id,
                toolkit_namespace=ROUTINE_STATE_NAMESPACE,
                state_name=_EXECUTION_PREFIX + state.context.candidate.routine_id,
                state_json=state.model_dump(mode="json"),
                schema_version=1,
                expected_version=expected_version,
            ),
        )
        return RoutineStateRecord(
            toolkit_state_id=record.id, version=record.version, state=state
        )

    async def cancel_for_stop(
        self,
        session: WriteSession,
        *,
        scope: RoutineScope,
        now: datetime.datetime,
    ) -> None:
        """Close incomplete authority inside the caller's Session Stop fence."""
        if now.tzinfo is None or now.utcoffset() is None:
            raise ValueError("Routine Stop time must be timezone-aware.")
        check = await self.get_check(session, scope=scope)
        if check is not None and check.state.queued_judgment_id is not None:
            await self.save_check(
                session,
                scope=scope,
                state=RoutineCheckState(
                    last_tick_at=check.state.last_tick_at,
                    last_action_at=check.state.last_action_at,
                    source_inputs=check.state.source_inputs,
                    queued_judgment_id=None,
                ),
                expected_version=check.version,
            )
        for item in await self.list_executions(session, scope=scope):
            if not item.state.incomplete:
                continue
            await self.save_execution(
                session,
                scope=scope,
                state=RoutineExecutionState(
                    context=item.state.context,
                    phase="cancelled",
                    current_run_id=item.state.current_run_id,
                    started_at=item.state.started_at,
                    completed_at=now,
                    work=None,
                    delivery_status=None,
                    delivery_error=None,
                ),
                expected_version=item.version,
            )

    @staticmethod
    def _require_scope(
        state: RoutineExecutionState, *, scope: RoutineScope, routine_id: str
    ) -> None:
        if (
            state.context.scope != scope
            or state.context.candidate.routine_id != routine_id
        ):
            raise RoutineUnavailable(
                "Routine admitted context does not match its owner."
            )
