"""Event agent execution repository."""

import datetime
from collections.abc import Sequence

import sqlalchemy as sa
from azcommon.uuid import uuid7
from pydantic import TypeAdapter
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from azents.core.agent import AgentModelSelection
from azents.core.enums import AgentRunPhase, AgentRunStatus, EventKind
from azents.core.inference_profile import (
    InferenceProfileFailureCode,
    InferenceProfileSource,
    InferenceRunSummary,
    RequestedInferenceProfile,
    ResolvedInferenceProfileSummary,
)
from azents.core.llm_catalog import ModelReasoningEffort
from azents.engine.events.action_messages import ActionMessagePayload
from azents.engine.events.types import (
    ActiveToolCall,
    AgentRunState,
    Event,
    EventPayload,
    UserMessagePayload,
    validate_event_payload,
)
from azents.engine.run.failure import FailedRunRetryState
from azents.rdb.models.agent_run import RDBAgentRun
from azents.rdb.models.agent_run_input_event import RDBAgentRunInputEvent
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
    """Validate JSON payload using the canonical payload model mapping."""
    return validate_event_payload(kind, payload)


def _serialize_payload(payload: EventPayload) -> dict[str, JSONValue]:
    """Serialize an event while preserving explicit Default profile effort."""
    serialized = _JSON_OBJECT_ADAPTER.validate_python(
        payload.model_dump(mode="json", exclude_none=True)
    )
    if (
        isinstance(payload, (UserMessagePayload, ActionMessagePayload))
        and payload.requested_inference_profile is not None
    ):
        serialized["requested_inference_profile"] = (
            _JSON_OBJECT_ADAPTER.validate_python(
                payload.requested_inference_profile.model_dump(mode="json")
            )
        )
    return serialized


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
            payload=_serialize_payload(payload),
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
        await self._update_session_last_user_input_at(session, rdb)
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
        payload_json = _serialize_payload(payload)
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
            await self._update_session_last_user_input_at(session, inserted)
            return self._build(inserted)

        existing = await self.get_by_external_id(
            session,
            create.session_id,
            external_id,
        )
        if existing is None:
            raise RuntimeError("Event idempotent append failed")
        return existing

    async def _update_session_last_user_input_at(
        self,
        session: AsyncSession,
        event: RDBEvent,
    ) -> None:
        """Update AgentSession latest user input timestamp for user messages."""
        if event.kind != EventKind.USER_MESSAGE:
            return
        await session.execute(
            sa.update(RDBAgentSession)
            .where(RDBAgentSession.id == event.session_id)
            .values(last_user_input_at=event.created_at)
        )
        await session.flush()

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

    async def list_model_file_gc_range(
        self,
        session: AsyncSession,
        session_id: str,
        *,
        after_order: int,
        to_order: int,
        limit: int,
    ) -> list[Event]:
        """Fetch a bounded event range for ModelFile GC cursor processing."""
        result = await session.execute(
            sa.select(RDBEvent)
            .where(
                RDBEvent.session_id == session_id,
                RDBEvent.reverted.is_(False),
                RDBEvent.model_order > after_order,
                RDBEvent.model_order <= to_order,
            )
            .order_by(RDBEvent.model_order.asc(), RDBEvent.id.asc())
            .limit(limit)
        )
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

    async def get_by_id(
        self,
        session: AsyncSession,
        *,
        event_id: str,
    ) -> Event | None:
        """Fetch one event by ID."""
        rdb = await session.get(RDBEvent, event_id)
        if rdb is None:
            return None
        return self._build(rdb)

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
        validated = _validate_payload(rdb.kind, _serialize_payload(payload))
        rdb.payload = _serialize_payload(validated)
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

        Sequential appends keep a fixed gap. This leaves room to insert future
        model-visible system events without renumbering the full transcript.
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
            requested_model_target_label=create.requested_model_target_label,
            requested_reasoning_effort=create.requested_reasoning_effort,
            inference_profile_source=create.inference_profile_source,
            resolved_model_selection=(
                create.resolved_model_selection.model_dump(mode="json")
                if create.resolved_model_selection is not None
                else None
            ),
            resolved_reasoning_effort=create.resolved_reasoning_effort,
            resolved_at=create.resolved_at,
            effective_context_window_tokens=create.effective_context_window_tokens,
            effective_auto_compaction_threshold_tokens=(
                create.effective_auto_compaction_threshold_tokens
            ),
            inference_profile_failure_code=create.inference_profile_failure_code,
            inference_profile_failure_message=create.inference_profile_failure_message,
            parent_agent_run_id=create.parent_agent_run_id,
            phase=create.phase,
            status=create.status,
        )
        if create.id is not None:
            rdb.id = create.id
        if create.status == AgentRunStatus.RUNNING:
            rdb.started_at = datetime.datetime.now(datetime.UTC)
        session.add(rdb)
        await session.flush()
        return self._build(rdb)

    async def create_pending(
        self,
        session: AsyncSession,
        *,
        session_id: str,
        requested_model_target_label: str | None,
        requested_reasoning_effort: ModelReasoningEffort | None,
        inference_profile_source: InferenceProfileSource,
        parent_agent_run_id: str | None,
        resolved_model_selection: AgentModelSelection | None,
        resolved_reasoning_effort: ModelReasoningEffort | None,
        resolved_at: datetime.datetime | None,
        effective_context_window_tokens: int | None,
        effective_auto_compaction_threshold_tokens: int | None,
    ) -> AgentRunState:
        """Create a pending run without cancelling an active run."""
        locked_session_id = await session.scalar(
            sa.select(RDBAgentSession.id)
            .where(RDBAgentSession.id == session_id)
            .with_for_update()
        )
        if locked_session_id is None:
            raise ValueError("AgentSession not found")
        run_index = await self.next_run_index(session, session_id=session_id)
        rdb = RDBAgentRun(
            session_id=session_id,
            run_index=run_index,
            requested_model_target_label=requested_model_target_label,
            requested_reasoning_effort=requested_reasoning_effort,
            inference_profile_source=inference_profile_source,
            resolved_model_selection=(
                resolved_model_selection.model_dump(mode="json")
                if resolved_model_selection is not None
                else None
            ),
            resolved_reasoning_effort=resolved_reasoning_effort,
            resolved_at=resolved_at,
            effective_context_window_tokens=effective_context_window_tokens,
            effective_auto_compaction_threshold_tokens=(
                effective_auto_compaction_threshold_tokens
            ),
            inference_profile_failure_code=None,
            inference_profile_failure_message=None,
            parent_agent_run_id=parent_agent_run_id,
            phase=AgentRunPhase.IDLE,
            status=AgentRunStatus.PENDING,
        )
        session.add(rdb)
        await session.flush()
        return self._build(rdb)

    async def get_pending_by_session_id(
        self,
        session: AsyncSession,
        *,
        session_id: str,
    ) -> AgentRunState | None:
        """Fetch the session's pending run when present."""
        rdb = await session.scalar(
            sa.select(RDBAgentRun)
            .where(
                RDBAgentRun.session_id == session_id,
                RDBAgentRun.status == AgentRunStatus.PENDING,
            )
            .order_by(RDBAgentRun.run_index.asc())
            .limit(1)
        )
        if rdb is None:
            return None
        return self._build(rdb)

    async def claim_pending_by_session_id(
        self,
        session: AsyncSession,
        *,
        session_id: str,
    ) -> AgentRunState | None:
        """Lock and return the session's pending run for one worker."""
        rdb = await session.scalar(
            sa.select(RDBAgentRun)
            .where(
                RDBAgentRun.session_id == session_id,
                RDBAgentRun.status == AgentRunStatus.PENDING,
            )
            .order_by(RDBAgentRun.run_index.asc())
            .with_for_update(skip_locked=True)
            .limit(1)
        )
        if rdb is None:
            return None
        return self._build(rdb)

    async def activate_pending(
        self,
        session: AsyncSession,
        *,
        run_id: str,
        resolved_model_selection: AgentModelSelection,
        resolved_reasoning_effort: ModelReasoningEffort | None,
        resolved_at: datetime.datetime,
        effective_context_window_tokens: int,
        effective_auto_compaction_threshold_tokens: int,
    ) -> AgentRunState:
        """Atomically activate one resolved pending run and its session profile."""
        rdb = await session.scalar(
            sa.select(RDBAgentRun)
            .where(
                RDBAgentRun.id == run_id,
                RDBAgentRun.status == AgentRunStatus.PENDING,
            )
            .with_for_update()
        )
        if rdb is None:
            raise ValueError("Pending AgentRun not found")
        if rdb.requested_model_target_label is None:
            raise ValueError("Pending AgentRun has no requested model target")

        rdb.resolved_model_selection = resolved_model_selection.model_dump(mode="json")
        rdb.resolved_reasoning_effort = resolved_reasoning_effort
        rdb.resolved_at = resolved_at
        rdb.effective_context_window_tokens = effective_context_window_tokens
        rdb.effective_auto_compaction_threshold_tokens = (
            effective_auto_compaction_threshold_tokens
        )
        rdb.status = AgentRunStatus.RUNNING
        rdb.started_at = resolved_at
        await session.execute(
            sa.update(RDBAgentSession)
            .where(RDBAgentSession.id == rdb.session_id)
            .values(
                last_model_target_label=rdb.requested_model_target_label,
                last_reasoning_effort=rdb.requested_reasoning_effort,
            )
        )
        await session.flush()
        await session.refresh(rdb)
        return self._build(rdb)

    async def activate_inherited_pending(
        self,
        session: AsyncSession,
        *,
        run_id: str,
        activated_at: datetime.datetime,
    ) -> AgentRunState:
        """Activate a pre-resolved child run without replacing its provenance."""
        rdb = await session.scalar(
            sa.select(RDBAgentRun)
            .where(
                RDBAgentRun.id == run_id,
                RDBAgentRun.status == AgentRunStatus.PENDING,
            )
            .with_for_update()
        )
        if rdb is None:
            raise ValueError("Pending AgentRun not found")
        if rdb.inference_profile_source != InferenceProfileSource.PARENT_RUN:
            raise ValueError("Pending AgentRun is not inherited from a parent run")
        if rdb.parent_agent_run_id is None:
            raise ValueError("Inherited AgentRun has no parent run")
        if rdb.requested_model_target_label is None:
            raise ValueError("Inherited AgentRun has no requested model target")
        if rdb.resolved_model_selection is None or rdb.resolved_at is None:
            raise ValueError("Inherited AgentRun has incomplete resolved provenance")
        if (
            rdb.effective_context_window_tokens is None
            or rdb.effective_auto_compaction_threshold_tokens is None
        ):
            raise ValueError("Inherited AgentRun has incomplete effective limits")

        rdb.status = AgentRunStatus.RUNNING
        rdb.started_at = activated_at
        await session.execute(
            sa.update(RDBAgentSession)
            .where(RDBAgentSession.id == rdb.session_id)
            .values(
                last_model_target_label=rdb.requested_model_target_label,
                last_reasoning_effort=rdb.requested_reasoning_effort,
            )
        )
        await session.flush()
        await session.refresh(rdb)
        return self._build(rdb)

    async def fail_pending_profile_resolution(
        self,
        session: AsyncSession,
        *,
        run_id: str,
        failure_code: InferenceProfileFailureCode,
        failure_message: str,
        ended_at: datetime.datetime,
    ) -> AgentRunState:
        """Finalize a pending run with safe typed profile failure data."""
        rdb = await session.scalar(
            sa.select(RDBAgentRun)
            .where(
                RDBAgentRun.id == run_id,
                RDBAgentRun.status == AgentRunStatus.PENDING,
            )
            .with_for_update()
        )
        if rdb is None:
            raise ValueError("Pending AgentRun not found")
        rdb.status = AgentRunStatus.FAILED
        rdb.inference_profile_failure_code = failure_code
        rdb.inference_profile_failure_message = failure_message
        rdb.ended_at = ended_at
        await session.flush()
        await session.refresh(rdb)
        return self._build(rdb)

    async def fail_profile_resolution_if_running(
        self,
        session: AsyncSession,
        *,
        run_id: str,
        failure_code: InferenceProfileFailureCode,
        failure_message: str,
        ended_at: datetime.datetime,
    ) -> AgentRunState | None:
        """Finalize a running run with safe typed profile failure data."""
        rdb = await session.scalar(
            sa.select(RDBAgentRun).where(RDBAgentRun.id == run_id).with_for_update()
        )
        if rdb is None:
            return None
        if rdb.status != AgentRunStatus.RUNNING:
            return self._build(rdb)
        rdb.status = AgentRunStatus.FAILED
        rdb.phase = AgentRunPhase.IDLE
        rdb.active_tool_calls = []
        rdb.retry_state = None
        rdb.inference_profile_failure_code = failure_code
        rdb.inference_profile_failure_message = failure_message
        rdb.ended_at = ended_at
        await session.flush()
        await session.refresh(rdb)
        return self._build(rdb)

    async def associate_input_events(
        self,
        session: AsyncSession,
        *,
        run_id: str,
        event_ids: Sequence[str],
    ) -> None:
        """Associate ordered input events with one run idempotently."""
        if not event_ids:
            return
        run_session_id = await session.scalar(
            sa.select(RDBAgentRun.session_id)
            .where(RDBAgentRun.id == run_id)
            .with_for_update()
        )
        if run_session_id is None:
            raise ValueError("AgentRun not found")
        existing_ids = set(
            (
                await session.execute(
                    sa.select(RDBAgentRunInputEvent.event_id).where(
                        RDBAgentRunInputEvent.agent_run_id == run_id
                    )
                )
            ).scalars()
        )
        new_event_ids = [
            event_id
            for event_id in dict.fromkeys(event_ids)
            if event_id not in existing_ids
        ]
        if not new_event_ids:
            return
        event_rows = (
            await session.execute(
                sa.select(RDBEvent.id, RDBEvent.session_id).where(
                    RDBEvent.id.in_(new_event_ids)
                )
            )
        ).all()
        if len(event_rows) != len(new_event_ids) or any(
            event_session_id != run_session_id for _, event_session_id in event_rows
        ):
            raise ValueError("Input events must belong to the AgentRun session")
        max_input_order = await session.scalar(
            sa.select(sa.func.max(RDBAgentRunInputEvent.input_order)).where(
                RDBAgentRunInputEvent.agent_run_id == run_id
            )
        )
        first_order = (max_input_order if max_input_order is not None else -1) + 1
        await session.execute(
            insert(RDBAgentRunInputEvent).values(
                [
                    {
                        "agent_run_id": run_id,
                        "event_id": event_id,
                        "input_order": first_order + offset,
                    }
                    for offset, event_id in enumerate(new_event_ids)
                ]
            )
        )
        await session.flush()

    async def list_input_event_ids(
        self,
        session: AsyncSession,
        *,
        run_id: str,
    ) -> list[str]:
        """List a run's associated input events in stable order."""
        result = await session.execute(
            sa.select(RDBAgentRunInputEvent.event_id)
            .where(RDBAgentRunInputEvent.agent_run_id == run_id)
            .order_by(RDBAgentRunInputEvent.input_order.asc())
        )
        return list(result.scalars())

    async def list_by_input_event_id(
        self,
        session: AsyncSession,
        *,
        event_id: str,
    ) -> list[AgentRunState]:
        """List runs associated with one input event in run order."""
        result = await session.execute(
            sa.select(RDBAgentRun)
            .join(
                RDBAgentRunInputEvent,
                RDBAgentRunInputEvent.agent_run_id == RDBAgentRun.id,
            )
            .where(RDBAgentRunInputEvent.event_id == event_id)
            .order_by(RDBAgentRun.run_index.asc(), RDBAgentRun.created_at.asc())
        )
        return [self._build(rdb) for rdb in result.scalars()]

    async def get_latest_by_input_event_id(
        self,
        session: AsyncSession,
        *,
        event_id: str,
    ) -> AgentRunState | None:
        """Fetch the latest run associated with one input event."""
        rdb = await session.scalar(
            sa.select(RDBAgentRun)
            .join(
                RDBAgentRunInputEvent,
                RDBAgentRunInputEvent.agent_run_id == RDBAgentRun.id,
            )
            .where(RDBAgentRunInputEvent.event_id == event_id)
            .order_by(RDBAgentRun.run_index.desc(), RDBAgentRun.created_at.desc())
            .limit(1)
        )
        if rdb is None:
            return None
        return self._build(rdb)

    async def get_latest_inference_run_summary_by_event_id(
        self,
        session: AsyncSession,
        *,
        event_id: str,
    ) -> InferenceRunSummary | None:
        """Project the latest associated run through the safe public allowlist."""
        run = await self.get_latest_by_input_event_id(session, event_id=event_id)
        if run is None:
            return None
        return self.build_inference_run_summary(run)

    async def list_latest_inference_run_summaries_by_event_ids(
        self,
        session: AsyncSession,
        *,
        event_ids: Sequence[str],
    ) -> dict[str, InferenceRunSummary]:
        """Project each event's latest associated run through the public allowlist."""
        unique_event_ids = list(dict.fromkeys(event_ids))
        if not unique_event_ids:
            return {}
        result = await session.execute(
            sa.select(RDBAgentRunInputEvent.event_id, RDBAgentRun)
            .join(
                RDBAgentRun,
                RDBAgentRun.id == RDBAgentRunInputEvent.agent_run_id,
            )
            .where(RDBAgentRunInputEvent.event_id.in_(unique_event_ids))
            .order_by(
                RDBAgentRunInputEvent.event_id.asc(),
                RDBAgentRun.run_index.desc(),
                RDBAgentRun.created_at.desc(),
            )
        )
        summaries: dict[str, InferenceRunSummary] = {}
        for event_id, rdb in result.all():
            if event_id not in summaries:
                summaries[event_id] = self.build_inference_run_summary(self._build(rdb))
        return summaries

    @staticmethod
    def build_inference_run_summary(run: AgentRunState) -> InferenceRunSummary:
        """Build the safe public summary for one run."""
        requested_profile = (
            RequestedInferenceProfile(
                model_target_label=run.requested_model_target_label,
                reasoning_effort=run.requested_reasoning_effort,
            )
            if run.requested_model_target_label is not None
            else None
        )
        resolved_profile = (
            ResolvedInferenceProfileSummary.from_model_selection(
                run.resolved_model_selection
            )
            if run.resolved_model_selection is not None
            else None
        )
        return InferenceRunSummary(
            run_id=run.id,
            run_index=run.run_index,
            status=run.status,
            requested_profile=requested_profile,
            source=run.inference_profile_source,
            resolved_profile=resolved_profile,
            resolved_reasoning_effort=run.resolved_reasoning_effort,
            effective_context_window_tokens=run.effective_context_window_tokens,
            effective_auto_compaction_threshold_tokens=(
                run.effective_auto_compaction_threshold_tokens
            ),
            failure_code=run.inference_profile_failure_code,
            failure_message=run.inference_profile_failure_message,
        )

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
                retry_state=None,
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

    async def get_inference_run_summary_by_id(
        self,
        session: AsyncSession,
        *,
        run_id: str,
    ) -> InferenceRunSummary | None:
        """Fetch one allowlisted run summary by AgentRun ID."""
        run = await self.get_by_id(session, run_id)
        if run is None:
            return None
        return self.build_inference_run_summary(run)

    async def list_inference_run_summaries_by_ids(
        self,
        session: AsyncSession,
        *,
        run_ids: Sequence[str],
    ) -> dict[str, InferenceRunSummary]:
        """Fetch allowlisted summaries keyed by AgentRun ID."""
        unique_run_ids = list(dict.fromkeys(run_ids))
        if not unique_run_ids:
            return {}
        result = await session.scalars(
            sa.select(RDBAgentRun).where(RDBAgentRun.id.in_(unique_run_ids))
        )
        return {
            rdb.id: self.build_inference_run_summary(self._build(rdb))
            for rdb in result.all()
        }

    async def get_failed_by_terminal_result_event_id(
        self,
        session: AsyncSession,
        *,
        session_id: str,
        terminal_result_event_id: str,
    ) -> AgentRunState | None:
        """Fetch the failed run finalized by a specific session event."""
        rdb = await session.scalar(
            sa.select(RDBAgentRun)
            .where(
                RDBAgentRun.session_id == session_id,
                RDBAgentRun.status == AgentRunStatus.FAILED,
                RDBAgentRun.terminal_result_event_id == terminal_result_event_id,
            )
            .order_by(RDBAgentRun.run_index.desc())
            .limit(1)
        )
        if rdb is None:
            return None
        return self._build(rdb)

    async def list_latest_by_session_ids(
        self,
        session: AsyncSession,
        *,
        session_ids: Sequence[str],
    ) -> dict[str, AgentRunState]:
        """Fetch the latest run for each session ID."""
        latest: dict[str, AgentRunState] = {}
        for session_id in dict.fromkeys(session_ids):
            rdb = await session.scalar(
                sa.select(RDBAgentRun)
                .where(RDBAgentRun.session_id == session_id)
                .order_by(RDBAgentRun.run_index.desc())
                .limit(1)
            )
            if rdb is not None:
                latest[session_id] = self._build(rdb)
        return latest

    async def get_active_by_session_id(
        self,
        session: AsyncSession,
        *,
        session_id: str,
    ) -> AgentRunState | None:
        """Fetch the newest pending or running run for a session."""
        rdb = await session.scalar(
            sa.select(RDBAgentRun)
            .where(
                RDBAgentRun.session_id == session_id,
                RDBAgentRun.status.in_(
                    [AgentRunStatus.PENDING, AgentRunStatus.RUNNING]
                ),
            )
            .order_by(RDBAgentRun.run_index.desc())
            .limit(1)
        )
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
        if "retry_state" in values:
            values["retry_state"] = (
                patch.retry_state.model_dump(mode="json", exclude_none=True)
                if patch.retry_state is not None
                else None
            )
        if "resolved_model_selection" in values:
            values["resolved_model_selection"] = (
                patch.resolved_model_selection.model_dump(mode="json")
                if patch.resolved_model_selection is not None
                else None
            )
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

    async def update_retry_state(
        self,
        session: AsyncSession,
        run_id: str,
        retry_state: FailedRunRetryState | None,
    ) -> AgentRunState:
        """Set or clear durable failed-run retry state."""
        return await self.update(
            session,
            run_id,
            AgentRunPatch(retry_state=retry_state),
        )

    async def mark_terminal(
        self,
        session: AsyncSession,
        run_id: str,
        status: AgentRunStatus,
        *,
        ended_at: datetime.datetime,
        last_completed_event_id: str | None = None,
        terminal_result_event_id: str | None = None,
        terminal_result_message: str | None = None,
    ) -> AgentRunState:
        """Transition Run to terminal state."""
        return await self.update(
            session,
            run_id,
            AgentRunPatch(
                status=status,
                phase=AgentRunPhase.IDLE,
                active_tool_calls=[],
                retry_state=None,
                ended_at=ended_at,
                last_completed_event_id=last_completed_event_id,
                terminal_result_event_id=terminal_result_event_id,
                terminal_result_message=terminal_result_message,
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
        terminal_result_event_id: str | None = None,
        terminal_result_message: str | None = None,
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
        rdb.retry_state = None
        rdb.ended_at = ended_at
        rdb.last_completed_event_id = last_completed_event_id
        rdb.terminal_result_event_id = terminal_result_event_id
        rdb.terminal_result_message = terminal_result_message
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
            requested_model_target_label=rdb.requested_model_target_label,
            requested_reasoning_effort=rdb.requested_reasoning_effort,
            inference_profile_source=rdb.inference_profile_source,
            resolved_model_selection=(
                AgentModelSelection.model_validate(rdb.resolved_model_selection)
                if rdb.resolved_model_selection is not None
                else None
            ),
            resolved_reasoning_effort=rdb.resolved_reasoning_effort,
            resolved_at=rdb.resolved_at,
            effective_context_window_tokens=rdb.effective_context_window_tokens,
            effective_auto_compaction_threshold_tokens=(
                rdb.effective_auto_compaction_threshold_tokens
            ),
            inference_profile_failure_code=rdb.inference_profile_failure_code,
            inference_profile_failure_message=rdb.inference_profile_failure_message,
            parent_agent_run_id=rdb.parent_agent_run_id,
            active_tool_calls=active_tool_calls,
            retry_state=FailedRunRetryState.model_validate(rdb.retry_state)
            if rdb.retry_state is not None
            else None,
            last_completed_event_id=rdb.last_completed_event_id,
            terminal_result_event_id=rdb.terminal_result_event_id,
            terminal_result_message=rdb.terminal_result_message,
            stop_requested_at=rdb.stop_requested_at,
            created_at=rdb.created_at,
            started_at=rdb.started_at,
            ended_at=rdb.ended_at,
            updated_at=rdb.updated_at,
        )
