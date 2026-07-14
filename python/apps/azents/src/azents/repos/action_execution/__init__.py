"""Action execution repository."""

import datetime

import sqlalchemy as sa
from azcommon.uuid import uuid7
from pydantic import TypeAdapter
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from azents.core.enums import ActionExecutionStatus
from azents.rdb.models.action_execution import (
    RDBActionExecution,
    RDBActionExecutionEvent,
)
from azents.rdb.models.event import JSONValue

from .data import (
    ActionExecution,
    ActionExecutionCreate,
    ActionExecutionEvent,
    ActionExecutionEventCreate,
    ActionExecutionProjection,
)

_JSON_OBJECT_ADAPTER = TypeAdapter[dict[str, JSONValue]](dict[str, JSONValue])


class ActionExecutionEventIdentityConflictError(RuntimeError):
    """A preallocated progress-event ID resolved to different durable content."""


class ActionExecutionRepository:
    """Live TurnAction execution repository."""

    async def create(
        self,
        session: AsyncSession,
        create: ActionExecutionCreate,
    ) -> ActionExecution:
        """Create execution state for one source input buffer."""
        action_execution_id = create.id or uuid7().hex
        result = await session.execute(
            pg_insert(RDBActionExecution)
            .values(
                id=action_execution_id,
                session_id=create.session_id,
                input_buffer_id=create.input_buffer_id,
                action_type=create.action_type,
                action=create.action,
                status=create.status,
                owner_generation=create.owner_generation,
            )
            .on_conflict_do_nothing(
                constraint="uq_action_executions_input_buffer_id",
            )
            .returning(RDBActionExecution)
        )
        rdb = result.scalar_one_or_none()
        if rdb is None:
            existing = await self.get_by_input_buffer_id(
                session,
                input_buffer_id=create.input_buffer_id,
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

    async def get_by_input_buffer_id(
        self,
        session: AsyncSession,
        *,
        input_buffer_id: str,
    ) -> ActionExecution | None:
        """Fetch action execution by durable source input buffer ID."""
        result = await session.execute(
            sa.select(RDBActionExecution).where(
                RDBActionExecution.input_buffer_id == input_buffer_id
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
        """Append or recover one exact progress event under the execution lock."""
        await self._lock_action_execution(
            session,
            action_execution_id=create.action_execution_id,
            session_id=create.session_id,
        )
        event_id = create.id or uuid7().hex
        existing = await session.get(RDBActionExecutionEvent, event_id)
        if existing is not None:
            if not _event_matches_create(existing, create):
                raise ActionExecutionEventIdentityConflictError(
                    "ActionExecution event ID resolved to different durable content"
                )
            return self._build_event(existing)
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
        rdb.id = event_id
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

    async def get_projection_by_input_buffer_id(
        self,
        session: AsyncSession,
        *,
        input_buffer_id: str,
    ) -> ActionExecutionProjection | None:
        """Fetch execution state plus ordered events by input buffer identity."""
        execution = await self.get_by_input_buffer_id(
            session,
            input_buffer_id=input_buffer_id,
        )
        if execution is None:
            return None
        events = await self.list_events(
            session,
            action_execution_id=execution.id,
        )
        return ActionExecutionProjection(execution=execution, events=events)

    async def get_projection_by_id(
        self,
        session: AsyncSession,
        *,
        action_execution_id: str,
    ) -> ActionExecutionProjection | None:
        """Fetch one active execution and its ordered progress events."""
        execution = await self.get_by_id(
            session,
            action_execution_id=action_execution_id,
        )
        if execution is None:
            return None
        return ActionExecutionProjection(
            execution=execution,
            events=await self.list_events(
                session,
                action_execution_id=action_execution_id,
            ),
        )

    async def list_projections_by_session_id(
        self,
        session: AsyncSession,
        *,
        session_id: str,
    ) -> list[ActionExecutionProjection]:
        """List active action execution projections in creation order."""
        executions = await self.list_pending_or_running_by_session_id(
            session,
            session_id=session_id,
        )
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

    async def lock_projection_by_id(
        self,
        session: AsyncSession,
        *,
        action_execution_id: str,
        session_id: str,
    ) -> ActionExecutionProjection | None:
        """Lock and load one active execution projection for terminalization."""
        result = await session.execute(
            sa.select(RDBActionExecution)
            .where(
                RDBActionExecution.id == action_execution_id,
                RDBActionExecution.session_id == session_id,
            )
            .with_for_update()
        )
        rdb = result.scalar_one_or_none()
        if rdb is None:
            return None
        return ActionExecutionProjection(
            execution=self._build_execution(rdb),
            events=await self.list_events(
                session,
                action_execution_id=action_execution_id,
            ),
        )

    async def delete_by_id(
        self,
        session: AsyncSession,
        *,
        action_execution_id: str,
    ) -> None:
        """Delete one live execution and its cascaded progress events."""
        await session.execute(
            sa.delete(RDBActionExecution).where(
                RDBActionExecution.id == action_execution_id
            )
        )
        await session.flush()

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
        rdb.cancelled_at = None
        rdb.failure_summary = None
        rdb.cancellation_summary = None
        await session.flush()
        await session.refresh(rdb)
        return self._build_execution(rdb)

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
            input_buffer_id=rdb.input_buffer_id,
            action_type=rdb.action_type,
            action=_JSON_OBJECT_ADAPTER.validate_python(rdb.action),
            status=rdb.status,
            owner_generation=rdb.owner_generation,
            failure_summary=rdb.failure_summary,
            cancellation_summary=rdb.cancellation_summary,
            started_at=rdb.started_at,
            completed_at=rdb.completed_at,
            failed_at=rdb.failed_at,
            cancelled_at=rdb.cancelled_at,
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


def _event_matches_create(
    event: RDBActionExecutionEvent,
    create: ActionExecutionEventCreate,
) -> bool:
    """Return whether a durable event is the exact preallocated write."""
    return (
        event.action_execution_id == create.action_execution_id
        and event.session_id == create.session_id
        and event.kind is create.kind
        and event.step_key == create.step_key
        and (None if event.command_argv is None else list(event.command_argv))
        == create.command_argv
        and event.content == create.content
        and event.exit_code == create.exit_code
    )
