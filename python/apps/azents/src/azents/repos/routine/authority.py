"""Exact Routine execution authority derived from canonical Run input associations."""

from dataclasses import dataclass
from typing import Annotated

import sqlalchemy as sa
from fastapi import Depends

from azents.core.enums import AgentLifecycleStatus, AgentSessionStatus, EventKind
from azents.core.routine import RoutineScope, RoutineUnavailable
from azents.core.routine_execution import RoutineExecutionRef
from azents.core.routine_presentation import routine_execution_ref
from azents.core.session_resource_authority import SessionResourceAuthority
from azents.engine.events.types import RoutineInputPayload
from azents.rdb.models.agent import RDBAgent
from azents.rdb.models.agent_run import RDBAgentRun
from azents.rdb.models.agent_run_input_event import RDBAgentRunInputEvent
from azents.rdb.models.agent_session import RDBAgentSession
from azents.rdb.models.event import RDBEvent
from azents.rdb.session_capabilities import ReadSession, WriteSession
from azents.repos.routine.scope import require_routine_scope
from azents.repos.routine.state import RoutineStateRepository
from azents.repos.session_execution.ownership import fence_owned_session_mutation


@dataclass(frozen=True)
class RoutineExecutionAuthorityRepository:
    """Read existing provenance; a Routine identifier alone grants no exemption."""

    states: Annotated[RoutineStateRepository, Depends()]

    async def run_is_routine_only(
        self,
        session: ReadSession,
        *,
        scope: RoutineScope,
        run_id: str,
    ) -> bool:
        """Require every associated input to be valid Routine execution input."""
        run = await session.read_session.get(RDBAgentRun, run_id)
        if (
            run is None
            or run.session_id != scope.session_id
            or run.scheduled_task_cycle_id is not None
        ):
            return False
        rows = (
            await session.read_session.execute(
                sa.select(RDBEvent.kind, RDBEvent.payload, RDBEvent.session_id)
                .join(
                    RDBAgentRunInputEvent, RDBAgentRunInputEvent.event_id == RDBEvent.id
                )
                .where(RDBAgentRunInputEvent.agent_run_id == run_id)
                .order_by(RDBAgentRunInputEvent.input_order)
            )
        ).all()
        if not rows:
            return False
        input_refs: set[tuple[str, str]] = set()
        for row in rows:
            if row.session_id != scope.session_id or row.kind not in {
                EventKind.ROUTINE_TRIGGER,
                EventKind.ROUTINE_CONTINUATION,
            }:
                return False
            payload = RoutineInputPayload.model_validate(row.payload)
            input_refs.update(
                (ref.routine_id, ref.execution_id) for ref in payload.executions
            )
        current_refs = {
            (item.state.context.candidate.routine_id, item.state.context.execution_id)
            for item in await self.states.list_executions(session, scope=scope)
            if item.state.current_run_id == run_id
            and item.state.phase in {"started", "completed"}
        }
        return bool(current_refs) and current_refs.issubset(input_refs)

    async def refs_are_current(
        self,
        session: ReadSession,
        *,
        scope: RoutineScope,
        refs: tuple[RoutineExecutionRef, ...],
        phase: str,
    ) -> bool:
        """Resolve every typed pending identity against its original snapshot."""
        if not refs:
            return False
        for ref in refs:
            record = await self.states.get_occurrence(
                session,
                scope=scope,
                slug=ref.slug,
                execution_id=ref.execution_id,
            )
            if (
                record is None
                or record.state.phase != phase
                or routine_execution_ref(record.state) != ref
            ):
                return False
        return True

    async def require_execution_scope(
        self,
        session: ReadSession,
        *,
        scope: RoutineScope,
        run_id: str,
    ) -> None:
        """Allow only already-started original work in an archived root Session."""
        target = (
            await session.read_session.execute(
                sa.select(
                    RDBAgentSession.status,
                    RDBAgent.lifecycle_status,
                )
                .join(RDBAgent, RDBAgent.id == RDBAgentSession.agent_id)
                .where(
                    RDBAgentSession.id == scope.session_id,
                    RDBAgentSession.agent_id == scope.agent_id,
                    RDBAgentSession.workspace_id == scope.workspace_id,
                    RDBAgent.workspace_id == scope.workspace_id,
                )
            )
        ).one_or_none()
        if target is None:
            raise RoutineUnavailable("Routine Session authority is unavailable.")
        if target.status is AgentSessionStatus.ACTIVE:
            await require_routine_scope(session, scope=scope)
            return
        if (
            target.status is not AgentSessionStatus.ARCHIVED
            or target.lifecycle_status
            not in {AgentLifecycleStatus.ACTIVE, AgentLifecycleStatus.DECOMMISSIONING}
            or not any(
                item.state.phase in {"started", "completed"}
                and item.state.current_run_id == run_id
                for item in await self.states.list_executions(session, scope=scope)
            )
        ):
            raise RoutineUnavailable(
                "Archived Session has no preserved Routine execution authority."
            )

    async def fence_execution_scope(
        self,
        session: WriteSession,
        *,
        scope: RoutineScope,
        authority: SessionResourceAuthority,
    ) -> None:
        """Fence the ordinary Session owner before checking its narrow exception."""
        agent = await session.write_session.scalar(
            sa.select(RDBAgent.id)
            .where(
                RDBAgent.id == scope.agent_id,
                RDBAgent.workspace_id == scope.workspace_id,
                RDBAgent.lifecycle_status.in_(
                    (AgentLifecycleStatus.ACTIVE, AgentLifecycleStatus.DECOMMISSIONING)
                ),
            )
            .with_for_update(read=True, key_share=True)
        )
        if agent is None:
            raise RoutineUnavailable("Routine execution Agent is unavailable.")
        await fence_owned_session_mutation(session, authority.execution_owner)
        await self.require_execution_scope(
            session, scope=scope, run_id=authority.run_id
        )
