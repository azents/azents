"""Action execution repository."""

import datetime

import sqlalchemy as sa
from azcommon.uuid import uuid7
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from azents.core.enums import ActionExecutionStatus, EventKind
from azents.rdb.models.action_execution import (
    RDBActionExecution,
    RDBActionExecutionEvent,
)
from azents.rdb.models.event import RDBEvent

from .data import (
    ActionExecution,
    ActionExecutionCreate,
    ActionExecutionEvent,
    ActionExecutionEventCreate,
    ActionExecutionProjection,
)


class ActionExecutionRepository:
    """Durable TurnAction execution repository."""

    async def create(
        self,
        session: AsyncSession,
        create: ActionExecutionCreate,
    ) -> ActionExecution:
        """Create execution state for an action_message event."""
        await self._validate_action_event(
            session,
            session_id=create.session_id,
            action_event_id=create.action_event_id,
        )
        action_execution_id = create.id or uuid7().hex
        result = await session.execute(
            pg_insert(RDBActionExecution)
            .values(
                id=action_execution_id,
                session_id=create.session_id,
                action_event_id=create.action_event_id,
                action_type=create.action_type,
                status=create.status,
                attempt=create.attempt,
            )
            .on_conflict_do_nothing(
                constraint="uq_action_executions_action_event_id",
            )
            .returning(RDBActionExecution)
        )
        rdb = result.scalar_one_or_none()
        if rdb is None:
            existing = await self.get_by_action_event_id(
                session,
                action_event_id=create.action_event_id,
            )
            if existing is None:
                raise RuntimeError("ActionExecution conflict target not found")
            return existing
        await session.flush()
        return self._build_execution(rdb)

    async def get_by_id(
        self,
        session: AsyncSession,
        *,
        action_execution_id: str,
    ) -> ActionExecution | None:
        """Fetch action execution by ID."""
        rdb = await session.get(RDBActionExecution, action_execution_id)
        if rdb is None:
            return None
        return self._build_execution(rdb)

    async def get_by_action_event_id(
        self,
        session: AsyncSession,
        *,
        action_event_id: str,
    ) -> ActionExecution | None:
        """Fetch action execution by durable action_message event ID."""
        result = await session.execute(
            sa.select(RDBActionExecution).where(
                RDBActionExecution.action_event_id == action_event_id
            )
        )
        rdb = result.scalar_one_or_none()
        if rdb is None:
            return None
        return self._build_execution(rdb)

    async def list_by_session_id(
        self,
        session: AsyncSession,
        *,
        session_id: str,
    ) -> list[ActionExecution]:
        """List action executions for a session in creation order."""
        result = await session.execute(
            sa.select(RDBActionExecution)
            .where(RDBActionExecution.session_id == session_id)
            .order_by(RDBActionExecution.created_at, RDBActionExecution.id)
        )
        return [self._build_execution(rdb) for rdb in result.scalars()]

    async def list_pending_or_running_by_session_id(
        self,
        session: AsyncSession,
        *,
        session_id: str,
    ) -> list[ActionExecution]:
        """List unfinished action executions that may block ordered processing."""
        result = await session.execute(
            sa.select(RDBActionExecution)
            .where(
                RDBActionExecution.session_id == session_id,
                RDBActionExecution.status.in_(
                    [ActionExecutionStatus.PENDING, ActionExecutionStatus.RUNNING]
                ),
            )
            .order_by(RDBActionExecution.created_at, RDBActionExecution.id)
        )
        return [self._build_execution(rdb) for rdb in result.scalars()]

    async def append_event(
        self,
        session: AsyncSession,
        create: ActionExecutionEventCreate,
    ) -> ActionExecutionEvent:
        """Append a progress event with an execution-scoped monotonic sequence."""
        await self._lock_action_execution(
            session,
            action_execution_id=create.action_execution_id,
            session_id=create.session_id,
        )
        result = await session.execute(
            sa.select(
                sa.func.coalesce(sa.func.max(RDBActionExecutionEvent.sequence), 0)
            ).where(
                RDBActionExecutionEvent.action_execution_id
                == create.action_execution_id
            )
        )
        next_sequence = int(result.scalar_one()) + 1
        rdb = RDBActionExecutionEvent(
            action_execution_id=create.action_execution_id,
            session_id=create.session_id,
            sequence=next_sequence,
            kind=create.kind,
            step_key=create.step_key,
            command_argv=create.command_argv,
            content=create.content,
            exit_code=create.exit_code,
        )
        session.add(rdb)
        await session.flush()
        return self._build_event(rdb)

    async def list_events(
        self,
        session: AsyncSession,
        *,
        action_execution_id: str,
    ) -> list[ActionExecutionEvent]:
        """List execution progress events in append order."""
        result = await session.execute(
            sa.select(RDBActionExecutionEvent)
            .where(RDBActionExecutionEvent.action_execution_id == action_execution_id)
            .order_by(RDBActionExecutionEvent.sequence)
        )
        return [self._build_event(rdb) for rdb in result.scalars()]

    async def get_projection_by_action_event_id(
        self,
        session: AsyncSession,
        *,
        action_event_id: str,
    ) -> ActionExecutionProjection | None:
        """Fetch execution state plus ordered events by action event identity."""
        execution = await self.get_by_action_event_id(
            session,
            action_event_id=action_event_id,
        )
        if execution is None:
            return None
        events = await self.list_events(
            session,
            action_execution_id=execution.id,
        )
        return ActionExecutionProjection(execution=execution, events=events)

    async def list_projections_by_session_id(
        self,
        session: AsyncSession,
        *,
        session_id: str,
    ) -> list[ActionExecutionProjection]:
        """List action execution projections for a session in creation order."""
        executions = await self.list_by_session_id(session, session_id=session_id)
        return [
            ActionExecutionProjection(
                execution=execution,
                events=await self.list_events(
                    session,
                    action_execution_id=execution.id,
                ),
            )
            for execution in executions
        ]

    async def mark_running(
        self,
        session: AsyncSession,
        *,
        action_execution_id: str,
        started_at: datetime.datetime,
    ) -> ActionExecution:
        """Mark execution as running."""
        rdb = await self._get_required(session, action_execution_id)
        rdb.status = ActionExecutionStatus.RUNNING
        rdb.started_at = started_at
        rdb.completed_at = None
        rdb.failed_at = None
        rdb.failed_final_at = None
        rdb.failure_summary = None
        await session.flush()
        await session.refresh(rdb)
        return self._build_execution(rdb)

    async def mark_completed(
        self,
        session: AsyncSession,
        *,
        action_execution_id: str,
        completed_at: datetime.datetime,
    ) -> ActionExecution:
        """Mark execution as completed."""
        rdb = await self._get_required(session, action_execution_id)
        rdb.status = ActionExecutionStatus.COMPLETED
        rdb.completed_at = completed_at
        rdb.failure_summary = None
        await session.flush()
        await session.refresh(rdb)
        return self._build_execution(rdb)

    async def mark_failed(
        self,
        session: AsyncSession,
        *,
        action_execution_id: str,
        failure_summary: str,
        failed_at: datetime.datetime,
    ) -> ActionExecution:
        """Mark execution as failed and awaiting user decision."""
        rdb = await self._get_required(session, action_execution_id)
        rdb.status = ActionExecutionStatus.FAILED
        rdb.failure_summary = failure_summary
        rdb.failed_at = failed_at
        await session.flush()
        await session.refresh(rdb)
        return self._build_execution(rdb)

    async def mark_pending_for_retry(
        self,
        session: AsyncSession,
        *,
        action_execution_id: str,
    ) -> ActionExecution:
        """Reset a failed execution for retry while preserving durable events."""
        rdb = await self._get_required(session, action_execution_id)
        rdb.status = ActionExecutionStatus.PENDING
        rdb.attempt += 1
        rdb.failure_summary = None
        rdb.started_at = None
        rdb.completed_at = None
        rdb.failed_at = None
        rdb.failed_final_at = None
        await session.flush()
        await session.refresh(rdb)
        return self._build_execution(rdb)

    async def mark_failed_final(
        self,
        session: AsyncSession,
        *,
        action_execution_id: str,
        failed_final_at: datetime.datetime,
    ) -> ActionExecution:
        """Finalize a failed execution after user discard."""
        rdb = await self._get_required(session, action_execution_id)
        rdb.status = ActionExecutionStatus.FAILED_FINAL
        rdb.failed_final_at = failed_final_at
        await session.flush()
        await session.refresh(rdb)
        return self._build_execution(rdb)

    async def _validate_action_event(
        self,
        session: AsyncSession,
        *,
        session_id: str,
        action_event_id: str,
    ) -> None:
        """Validate that the execution references a session action_message event."""
        event = await session.get(RDBEvent, action_event_id)
        if event is None:
            raise ValueError("Action event not found")
        if event.session_id != session_id:
            raise ValueError("Action event belongs to another session")
        if event.kind is not EventKind.ACTION_MESSAGE:
            raise ValueError("Action event must be an action_message event")

    async def _lock_action_execution(
        self,
        session: AsyncSession,
        *,
        action_execution_id: str,
        session_id: str,
    ) -> None:
        """Lock action execution before calculating progress sequence."""
        result = await session.execute(
            sa.select(RDBActionExecution.id)
            .where(
                RDBActionExecution.id == action_execution_id,
                RDBActionExecution.session_id == session_id,
            )
            .with_for_update()
        )
        if result.scalar_one_or_none() is None:
            raise ValueError("ActionExecution row is missing")

    async def _get_required(
        self,
        session: AsyncSession,
        action_execution_id: str,
    ) -> RDBActionExecution:
        """Fetch an action execution row or raise."""
        rdb = await session.get(RDBActionExecution, action_execution_id)
        if rdb is None:
            raise RuntimeError("ActionExecution row is missing")
        return rdb

    def _build_execution(self, rdb: RDBActionExecution) -> ActionExecution:
        """Convert RDB action execution row to domain model."""
        return ActionExecution(
            id=rdb.id,
            session_id=rdb.session_id,
            action_event_id=rdb.action_event_id,
            action_type=rdb.action_type,
            status=rdb.status,
            attempt=rdb.attempt,
            failure_summary=rdb.failure_summary,
            started_at=rdb.started_at,
            completed_at=rdb.completed_at,
            failed_at=rdb.failed_at,
            failed_final_at=rdb.failed_final_at,
            created_at=rdb.created_at,
            updated_at=rdb.updated_at,
        )

    def _build_event(self, rdb: RDBActionExecutionEvent) -> ActionExecutionEvent:
        """Convert RDB action execution event row to domain model."""
        return ActionExecutionEvent(
            id=rdb.id,
            action_execution_id=rdb.action_execution_id,
            session_id=rdb.session_id,
            sequence=rdb.sequence,
            kind=rdb.kind,
            step_key=rdb.step_key,
            command_argv=None if rdb.command_argv is None else list(rdb.command_argv),
            content=rdb.content,
            exit_code=rdb.exit_code,
            created_at=rdb.created_at,
        )
