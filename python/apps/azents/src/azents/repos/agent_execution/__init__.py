"""Event agent execution repository."""

import datetime
from collections.abc import Sequence

import sqlalchemy as sa
from azcommon.uuid import uuid7
from pydantic import TypeAdapter
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from azents.core.enums import AgentRunPhase, AgentRunStatus, EventKind
from azents.engine.events.types import (
    ActiveToolCall,
    AgentRunState,
    AssistantMessagePayload,
    ClientToolCallPayload,
    ClientToolResultPayload,
    CompactionMarkerPayload,
    CompactionSummaryPayload,
    Event,
    EventPayload,
    GoalBriefingPayload,
    InterruptedPayload,
    ProviderToolCallPayload,
    ProviderToolResultPayload,
    ReasoningPayload,
    RunMarkerPayload,
    SubagentEndPayload,
    SubagentStartPayload,
    SystemErrorPayload,
    SystemReminderPayload,
    TurnMarkerPayload,
    UnknownAdapterOutputPayload,
    UserMessagePayload,
)
from azents.rdb.models.agent_run import RDBAgentRun
from azents.rdb.models.agent_session import RDBAgentSession
from azents.rdb.models.event import JSONValue, RDBEvent

from .data import (
    AgentRunCreate,
    AgentRunPatch,
    EventCreate,
)

_JSON_OBJECT_ADAPTER = TypeAdapter[dict[str, JSONValue]](dict[str, JSONValue])
_MODEL_ORDER_STEP = 1000


def _validate_payload(
    kind: EventKind,
    payload: dict[str, JSONValue],
) -> EventPayload:
    """Validate JSON payload with payload model by kind."""
    match kind:
        case EventKind.USER_MESSAGE | EventKind.BACKGROUND_COMPLETION:
            return UserMessagePayload.model_validate(payload)
        case EventKind.ASSISTANT_MESSAGE:
            return AssistantMessagePayload.model_validate(payload)
        case EventKind.REASONING:
            return ReasoningPayload.model_validate(payload)
        case EventKind.CLIENT_TOOL_CALL:
            return ClientToolCallPayload.model_validate(payload)
        case EventKind.CLIENT_TOOL_RESULT:
            return ClientToolResultPayload.model_validate(payload)
        case EventKind.PROVIDER_TOOL_CALL:
            return ProviderToolCallPayload.model_validate(payload)
        case EventKind.PROVIDER_TOOL_RESULT:
            return ProviderToolResultPayload.model_validate(payload)
        case EventKind.TURN_MARKER:
            return TurnMarkerPayload.model_validate(payload)
        case EventKind.RUN_MARKER:
            return RunMarkerPayload.model_validate(payload)
        case EventKind.INTERRUPTED:
            return InterruptedPayload.model_validate(payload)
        case EventKind.COMPACTION_MARKER:
            return CompactionMarkerPayload.model_validate(payload)
        case EventKind.COMPACTION_SUMMARY:
            return CompactionSummaryPayload.model_validate(payload)
        case EventKind.SUBAGENT_START:
            return SubagentStartPayload.model_validate(payload)
        case EventKind.SUBAGENT_END:
            return SubagentEndPayload.model_validate(payload)
        case EventKind.GOAL_CONTINUATION | EventKind.GOAL_UPDATED:
            return UserMessagePayload.model_validate(payload)
        case EventKind.GOAL_BRIEFING:
            return GoalBriefingPayload.model_validate(payload)
        case EventKind.SYSTEM_REMINDER:
            return SystemReminderPayload.model_validate(payload)
        case EventKind.SYSTEM_ERROR:
            return SystemErrorPayload.model_validate(payload)
        case EventKind.UNKNOWN_ADAPTER_OUTPUT:
            return UnknownAdapterOutputPayload.model_validate(payload)
        case _:
            raise ValueError("Unsupported event kind")


class EventTranscriptRepository:
    """Event transcript append/read repository."""

    async def append(
        self,
        session: AsyncSession,
        create: EventCreate,
    ) -> Event:
        """Append event.

        Treat event with ``external_id`` as session-scoped dedup key. Since multiple
        writers can append the same corrective event concurrently on stop/recovery
        paths, guarantee atomic idempotency with DB upsert.
        """
        if create.external_id is not None:
            return await self._append_with_external_id(session, create)

        payload = _validate_payload(create.kind, create.payload)
        model_order = (
            create.model_order
            if create.model_order is not None
            else await self._allocate_model_order(session, create.session_id)
        )
        rdb = RDBEvent(
            session_id=create.session_id,
            kind=create.kind,
            payload=_JSON_OBJECT_ADAPTER.validate_python(
                payload.model_dump(mode="json", exclude_none=True)
            ),
            model_order=model_order,
            external_id=None,
            adapter=create.adapter,
            provider=create.provider,
            model=create.model,
            native_format=create.native_format,
            schema_version=create.schema_version,
        )
        session.add(rdb)
        await session.flush()
        return self._build(rdb)

    async def _append_with_external_id(
        self,
        session: AsyncSession,
        create: EventCreate,
    ) -> Event:
        """Atomically append event with External ID."""
        external_id = create.external_id
        if external_id is None:
            raise ValueError("External ID is required for idempotent append")

        payload = _validate_payload(create.kind, create.payload)
        payload_json = _JSON_OBJECT_ADAPTER.validate_python(
            payload.model_dump(mode="json", exclude_none=True)
        )
        model_order = (
            create.model_order
            if create.model_order is not None
            else await self._allocate_model_order(session, create.session_id)
        )
        stmt = (
            insert(RDBEvent)
            .values(
                id=uuid7().hex,
                session_id=create.session_id,
                kind=create.kind,
                payload=payload_json,
                model_order=model_order,
                external_id=external_id,
                adapter=create.adapter,
                provider=create.provider,
                model=create.model,
                native_format=create.native_format,
                schema_version=create.schema_version,
            )
            .on_conflict_do_nothing(
                index_elements=[RDBEvent.session_id, RDBEvent.external_id],
                index_where=RDBEvent.external_id.is_not(None),
            )
            .returning(RDBEvent)
        )
        result = await session.execute(stmt)
        inserted = result.scalar_one_or_none()
        if inserted is not None:
            await session.flush()
            return self._build(inserted)

        existing = await self.get_by_external_id(
            session,
            create.session_id,
            external_id,
        )
        if existing is None:
            raise RuntimeError("Event idempotent append failed")
        return existing

    async def list_for_model_input(
        self,
        session: AsyncSession,
        session_id: str,
        *,
        head_event_id: str | None = None,
    ) -> list[Event]:
        """Fetch transcript after model input head in id order."""
        stmt = (
            sa.select(RDBEvent)
            .where(RDBEvent.session_id == session_id, RDBEvent.reverted.is_(False))
            .order_by(RDBEvent.model_order.asc(), RDBEvent.id.asc())
        )
        if head_event_id is not None:
            head_order = (
                sa.select(RDBEvent.model_order)
                .where(
                    RDBEvent.session_id == session_id,
                    RDBEvent.id == head_event_id,
                )
                .scalar_subquery()
            )
            stmt = stmt.where(RDBEvent.model_order >= head_order)
        result = await session.execute(stmt)
        return [self._build(rdb) for rdb in result.scalars()]

    async def list_recent_by_session_id(
        self,
        session: AsyncSession,
        session_id: str,
        *,
        limit: int,
    ) -> list[Event]:
        """Fetch recent Session events in physical append order."""
        bounded_limit = max(1, min(limit, 500))
        subquery = (
            sa.select(RDBEvent.id)
            .where(RDBEvent.session_id == session_id)
            .where(RDBEvent.reverted.is_(False))
            .order_by(RDBEvent.id.desc())
            .limit(bounded_limit)
            .subquery()
        )
        result = await session.execute(
            sa.select(RDBEvent)
            .where(RDBEvent.id.in_(sa.select(subquery.c.id)))
            .order_by(RDBEvent.id.asc())
        )
        return [self._build(rdb) for rdb in result.scalars()]

    async def exists_in_session(
        self,
        session: AsyncSession,
        session_id: str,
        event_id: str,
    ) -> bool:
        """Check whether Event exists in that session transcript."""
        result = await session.execute(
            sa.select(RDBEvent.id).where(
                RDBEvent.session_id == session_id,
                RDBEvent.id == event_id,
            )
        )
        return result.scalar_one_or_none() is not None

    async def get_by_external_id(
        self,
        session: AsyncSession,
        session_id: str,
        external_id: str,
    ) -> Event | None:
        """Fetch event by dedup key."""
        result = await session.execute(
            sa.select(RDBEvent).where(
                RDBEvent.session_id == session_id,
                RDBEvent.external_id == external_id,
            )
        )
        rdb = result.scalar_one_or_none()
        if rdb is None:
            return None
        return self._build(rdb)

    async def update_model_orders(
        self,
        session: AsyncSession,
        session_id: str,
        order_by_event_id: dict[str, int],
    ) -> None:
        """Update Event model input logical order."""
        if not order_by_event_id:
            return
        rows: list[RDBEvent] = []
        for event_id in order_by_event_id:
            rdb = await session.get(RDBEvent, event_id)
            if rdb is None or rdb.session_id != session_id:
                raise ValueError("Event not found in session")
            rows.append(rdb)

        result = await session.execute(
            sa.select(sa.func.min(RDBEvent.model_order)).where(
                RDBEvent.session_id == session_id
            )
        )
        min_order = int(result.scalar_one_or_none() or 0)
        for offset, rdb in enumerate(rows, start=1):
            rdb.model_order = min_order - offset
        await session.flush()

        for rdb in rows:
            rdb.model_order = order_by_event_id[rdb.id]
        await session.flush()

    async def update_payload(
        self,
        session: AsyncSession,
        event_id: str,
        payload: EventPayload,
    ) -> Event:
        """Update Event payload within same kind shape."""
        rdb = await session.get(RDBEvent, event_id)
        if rdb is None:
            raise ValueError("Event not found")
        validated = _validate_payload(
            rdb.kind,
            _JSON_OBJECT_ADAPTER.validate_python(
                payload.model_dump(mode="json", exclude_none=True)
            ),
        )
        rdb.payload = _JSON_OBJECT_ADAPTER.validate_python(
            validated.model_dump(mode="json", exclude_none=True)
        )
        await session.flush()
        await session.refresh(rdb)
        return self._build(rdb)

    async def _allocate_model_order(
        self,
        session: AsyncSession,
        session_id: str,
    ) -> int:
        """Acquire Session row lock and assign next model_order."""
        await self._lock_session_for_model_order(session, session_id)
        return await self._next_model_order(session, session_id)

    async def _lock_session_for_model_order(
        self,
        session: AsyncSession,
        session_id: str,
    ) -> None:
        """Serialize model_order calculation for concurrent appends by session."""
        result = await session.execute(
            sa.select(RDBAgentSession.id)
            .where(RDBAgentSession.id == session_id)
            .with_for_update()
        )
        if result.scalar_one_or_none() is None:
            raise ValueError("Event session not found")

    async def _next_model_order(
        self,
        session: AsyncSession,
        session_id: str,
    ) -> int:
        """Calculate next model input logical order inside Session.

        Sequential appends keep a fixed gap. This leaves room to assign middle
        logical order without renumbering the full transcript each time auto
        compaction shows summary first and keeps preserved tail after it.
        `model_order` is DB BigInteger, so overflow from increments of 1000 is
        not a practical constraint from session event count perspective.
        """
        result = await session.execute(
            sa.select(sa.func.max(RDBEvent.model_order)).where(
                RDBEvent.session_id == session_id
            )
        )
        current = result.scalar_one_or_none()
        if current is None:
            return _MODEL_ORDER_STEP
        return int(current) + _MODEL_ORDER_STEP

    def _build(self, rdb: RDBEvent) -> Event:
        """Convert RDB row to domain model."""
        payload = _validate_payload(rdb.kind, rdb.payload)
        return Event(
            id=rdb.id,
            session_id=rdb.session_id,
            kind=rdb.kind,
            payload=payload,
            model_order=rdb.model_order,
            external_id=rdb.external_id,
            adapter=rdb.adapter,
            provider=rdb.provider,
            model=rdb.model,
            native_format=rdb.native_format,
            schema_version=rdb.schema_version,
            created_at=rdb.created_at,
        )


class AgentRunRepository:
    """Event agent_runs repository."""

    async def create(
        self,
        session: AsyncSession,
        create: AgentRunCreate,
    ) -> AgentRunState:
        """Create Agent run row."""
        await self.mark_session_running_terminal(
            session,
            session_id=create.session_id,
            status=AgentRunStatus.CANCELLED,
            ended_at=datetime.datetime.now(datetime.UTC),
        )
        run_index = create.run_index
        if run_index is None:
            max_run_index = await session.scalar(
                sa.select(sa.func.max(RDBAgentRun.run_index)).where(
                    RDBAgentRun.session_id == create.session_id
                )
            )
            run_index = (max_run_index or 0) + 1
        rdb = RDBAgentRun(
            session_id=create.session_id,
            run_index=run_index,
            phase=create.phase,
            status=create.status,
        )
        if create.id is not None:
            rdb.id = create.id
        session.add(rdb)
        await session.flush()
        return self._build(rdb)

    async def mark_session_running_terminal(
        self,
        session: AsyncSession,
        *,
        session_id: str,
        status: AgentRunStatus,
        ended_at: datetime.datetime,
    ) -> None:
        """Close remaining running run projection in session as terminal state."""
        await session.execute(
            sa.update(RDBAgentRun)
            .where(
                RDBAgentRun.session_id == session_id,
                RDBAgentRun.status == AgentRunStatus.RUNNING,
            )
            .values(
                status=status,
                phase=AgentRunPhase.IDLE,
                active_tool_calls=[],
                ended_at=ended_at,
            )
        )
        await session.flush()

    async def next_run_index(
        self,
        session: AsyncSession,
        *,
        session_id: str,
    ) -> int:
        """Return next run_index for session."""
        max_run_index = await session.scalar(
            sa.select(sa.func.max(RDBAgentRun.run_index)).where(
                RDBAgentRun.session_id == session_id
            )
        )
        return (max_run_index or 0) + 1

    async def latest_run_indexes(
        self,
        session: AsyncSession,
        *,
        session_ids: Sequence[str] | None,
    ) -> dict[str, int]:
        """Return latest known run_index by session."""
        stmt = sa.select(
            RDBAgentRun.session_id,
            sa.func.max(RDBAgentRun.run_index),
        ).group_by(RDBAgentRun.session_id)
        if session_ids is not None:
            if not session_ids:
                return {}
            stmt = stmt.where(RDBAgentRun.session_id.in_(session_ids))
        rows = (await session.execute(stmt)).all()
        return {session_id: int(run_index) for session_id, run_index in rows}

    async def get_by_id(
        self,
        session: AsyncSession,
        run_id: str,
    ) -> AgentRunState | None:
        """Fetch agent run by ID."""
        rdb = await session.get(RDBAgentRun, run_id)
        if rdb is None:
            return None
        return self._build(rdb)

    async def get_running_by_session_id(
        self,
        session: AsyncSession,
        *,
        session_id: str,
    ) -> AgentRunState | None:
        """Fetch currently running run for session."""
        rdb = await session.scalar(
            sa.select(RDBAgentRun)
            .where(
                RDBAgentRun.session_id == session_id,
                RDBAgentRun.status == AgentRunStatus.RUNNING,
            )
            .order_by(RDBAgentRun.run_index.desc())
            .limit(1)
        )
        if rdb is None:
            return None
        return self._build(rdb)

    async def update(
        self,
        session: AsyncSession,
        run_id: str,
        patch: AgentRunPatch,
    ) -> AgentRunState:
        """Update Agent run state."""
        rdb = await session.get(RDBAgentRun, run_id)
        if rdb is None:
            raise ValueError("Agent run not found")

        values = patch.model_dump(exclude_unset=True)
        if "active_tool_calls" in values:
            values["active_tool_calls"] = [
                call.model_dump(mode="json", exclude_none=True)
                for call in patch.active_tool_calls or []
            ]
        if values:
            for key, value in values.items():
                setattr(rdb, key, value)
        await session.flush()
        await session.refresh(rdb)
        return self._build(rdb)

    async def update_phase(
        self,
        session: AsyncSession,
        run_id: str,
        phase: AgentRunPhase,
        *,
        active_tool_calls: list[ActiveToolCall] | None = None,
    ) -> AgentRunState:
        """Update phase and active tool call projection."""
        if active_tool_calls is None:
            patch = AgentRunPatch(phase=phase)
        else:
            patch = AgentRunPatch(phase=phase, active_tool_calls=active_tool_calls)
        return await self.update(session, run_id, patch)

    async def mark_terminal(
        self,
        session: AsyncSession,
        run_id: str,
        status: AgentRunStatus,
        *,
        ended_at: datetime.datetime,
        last_completed_event_id: str | None = None,
    ) -> AgentRunState:
        """Transition Run to terminal state."""
        return await self.update(
            session,
            run_id,
            AgentRunPatch(
                status=status,
                phase=AgentRunPhase.IDLE,
                active_tool_calls=[],
                ended_at=ended_at,
                last_completed_event_id=last_completed_event_id,
            ),
        )

    async def mark_terminal_if_running(
        self,
        session: AsyncSession,
        run_id: str,
        status: AgentRunStatus,
        *,
        ended_at: datetime.datetime,
        last_completed_event_id: str | None = None,
    ) -> AgentRunState | None:
        """Close Run as terminal state if it is still running."""
        rdb = await session.get(RDBAgentRun, run_id)
        if rdb is None:
            return None
        if rdb.status != AgentRunStatus.RUNNING:
            return self._build(rdb)
        rdb.status = status
        rdb.phase = AgentRunPhase.IDLE
        rdb.active_tool_calls = []
        rdb.ended_at = ended_at
        rdb.last_completed_event_id = last_completed_event_id
        await session.flush()
        await session.refresh(rdb)
        return self._build(rdb)

    def _build(self, rdb: RDBAgentRun) -> AgentRunState:
        """Convert RDB row to domain model."""
        active_tool_calls = [
            ActiveToolCall.model_validate(call) for call in rdb.active_tool_calls
        ]
        return AgentRunState(
            id=rdb.id,
            session_id=rdb.session_id,
            run_index=rdb.run_index,
            phase=rdb.phase,
            status=rdb.status,
            active_tool_calls=active_tool_calls,
            last_completed_event_id=rdb.last_completed_event_id,
            stop_requested_at=rdb.stop_requested_at,
            started_at=rdb.started_at,
            ended_at=rdb.ended_at,
            updated_at=rdb.updated_at,
        )
