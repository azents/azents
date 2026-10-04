"""Completed database-only Mailbox runtime reads and Scheduled FIFO admission."""

import dataclasses
import datetime
from collections.abc import Sequence
from typing import Annotated

from fastapi import Depends
from pydantic import TypeAdapter
from sqlalchemy.ext.asyncio import AsyncSession

from azents.core.agent_session_data import AgentSession
from azents.core.enums import (
    AgentRunStatus,
    AgentSessionStatus,
    EventKind,
    MailboxItemKind,
    MailboxSchedulingMode,
)
from azents.core.json_value import JSONValue
from azents.core.mailbox_data import (
    MailboxItem,
    ScheduledTaskContinuationMailboxPayload,
    ScheduledTaskTriggerMailboxPayload,
)
from azents.core.mailbox_errors import MailboxOwnerGenerationStaleError
from azents.core.session_resource_authority import SessionResourceAuthority
from azents.engine.events.types import (
    AgentRunState,
    Event,
    ScheduledTaskContinuationPayload,
    ScheduledTaskTriggerPayload,
)
from azents.rdb.deps import get_session_manager
from azents.rdb.session import SessionManager
from azents.repos.action_execution import ActionExecutionRepository
from azents.repos.agent_execution import AgentRunRepository, EventTranscriptRepository
from azents.repos.agent_execution.data import EventCreate
from azents.repos.agent_session import AgentSessionRepository
from azents.repos.mailbox import MailboxRepository
from azents.repos.scheduled_task.presentation import (
    render_scheduled_task_runtime_message,
)
from azents.repos.scheduled_task.repository import ScheduledTaskRepository
from azents.repos.scheduled_task_cycle import ScheduledTaskCycleRepository
from azents.repos.scheduled_task_cycle.data import ScheduledTaskCycleRecord

_JSON_OBJECT_ADAPTER = TypeAdapter[dict[str, JSONValue]](dict[str, JSONValue])


@dataclasses.dataclass(frozen=True)
class MailboxPreparationRead:
    """One detached Session identity and its current FIFO head."""

    agent_session: AgentSession | None
    buffer: MailboxItem | None


@dataclasses.dataclass(frozen=True)
class ScheduledMailboxDatabaseAdmission:
    """Committed scheduled admission without model-prompt orchestration."""

    run: AgentRunState | None
    buffer: MailboxItem | None
    cycle: ScheduledTaskCycleRecord | None
    events: list[Event]
    stale: bool


@dataclasses.dataclass(frozen=True)
class MailboxRuntimeOperations:
    """Own runtime Mailbox transaction lifetimes and Scheduled admission atomicity."""

    session_manager: Annotated[
        SessionManager[AsyncSession], Depends(get_session_manager)
    ]
    mailbox_item_repository: Annotated[MailboxRepository, Depends(MailboxRepository)]
    agent_session_repository: Annotated[
        AgentSessionRepository, Depends(AgentSessionRepository)
    ]
    event_transcript_repository: Annotated[
        EventTranscriptRepository, Depends(EventTranscriptRepository)
    ]
    agent_run_repository: Annotated[AgentRunRepository, Depends(AgentRunRepository)]
    scheduled_task_repository: Annotated[
        ScheduledTaskRepository, Depends(ScheduledTaskRepository)
    ]
    scheduled_task_cycle_repository: Annotated[
        ScheduledTaskCycleRepository, Depends(ScheduledTaskCycleRepository)
    ]
    action_execution_repository: Annotated[
        ActionExecutionRepository, Depends(ActionExecutionRepository)
    ]

    async def _first_promotable_in_session(
        self, session: AsyncSession, session_id: str
    ) -> MailboxItem | None:
        pending = await self.mailbox_item_repository.list_for_flush(
            session, session_id, limit=1
        )
        return pending[0] if pending else None

    async def first_promotable(self, session_id: str) -> MailboxItem | None:
        async with self.session_manager() as session:
            return await self._first_promotable_in_session(session, session_id)

    async def has_pending_wake_items(self, session_id: str) -> bool:
        async with self.session_manager() as session:
            pending = await self.mailbox_item_repository.list_for_flush(
                session, session_id
            )
            return any(
                buffer.scheduling_mode is MailboxSchedulingMode.WAKE_SESSION
                for buffer in pending
            )

    async def has_pending_agent_messages(self, session_id: str) -> bool:
        async with self.session_manager() as session:
            return await self.mailbox_item_repository.has_by_session_id_and_kind(
                session, session_id=session_id, kind=MailboxItemKind.AGENT_MESSAGE
            )

    async def read_preparation(self, session_id: str) -> MailboxPreparationRead:
        async with self.session_manager() as session:
            agent_session = await self.agent_session_repository.get_by_id(
                session, session_id
            )
            buffer = await self._first_promotable_in_session(session, session_id)
            return MailboxPreparationRead(agent_session=agent_session, buffer=buffer)

    async def attachment_authority(
        self,
        *,
        session_id: str,
        active_run_id: str,
        agent_id: str,
        workspace_id: str,
        owner_generation: int,
    ) -> SessionResourceAuthority | None:
        async with self.session_manager() as session:
            current = await self.agent_session_repository.get_by_id(session, session_id)
            get_root = (
                self.agent_session_repository.get_root_session_agent_by_session_id
            )
            root = await get_root(session, session_id)
            run = await self.agent_run_repository.get_by_id(session, active_run_id)
            if (
                current is None
                or root is None
                or run is None
                or run.session_id != session_id
                or run.status not in {AgentRunStatus.PENDING, AgentRunStatus.RUNNING}
                or current.workspace_id != workspace_id
                or current.agent_id != agent_id
                or current.status is not AgentSessionStatus.ACTIVE
                or current.owner_generation != owner_generation
            ):
                return None
            return SessionResourceAuthority(
                workspace_id=current.workspace_id,
                agent_id=current.agent_id,
                session_id=session_id,
                root_session_id=root.agent_session_id,
                run_id=run.id,
                run_index=run.run_index,
                owner_generation=owner_generation,
            )

    async def admit_scheduled_head(
        self, *, session_id: str, owner_generation: int, expected_buffer_id: str | None
    ) -> ScheduledMailboxDatabaseAdmission | None:
        """Commit cycle/Run/input/delete with the unchanged FIFO ownership fences."""
        async with self.session_manager() as session:
            agent_session = await self.agent_session_repository.lock_by_id(
                session, session_id
            )
            if agent_session is None:
                raise ValueError("AgentSession not found")
            if agent_session.owner_generation != owner_generation:
                raise MailboxOwnerGenerationStaleError(
                    "Session owner generation changed before Scheduled admission"
                )
            buffer = await self.mailbox_item_repository.lock_oldest_by_session_id(
                session, session_id
            )
            if buffer is None or buffer.id != expected_buffer_id:
                return None
            if buffer.kind not in {
                MailboxItemKind.SCHEDULED_TASK_TRIGGER,
                MailboxItemKind.SCHEDULED_TASK_CONTINUATION,
            }:
                return None
            payload = buffer.payload
            if not isinstance(
                payload,
                ScheduledTaskTriggerMailboxPayload
                | ScheduledTaskContinuationMailboxPayload,
            ):
                raise ValueError("Scheduled Task mailbox payload is malformed.")
            cycle_id = payload.cycle_id
            cycle = await self.scheduled_task_cycle_repository.lock(
                session,
                agent_id=agent_session.agent_id,
                session_id=session_id,
                cycle_id=cycle_id,
            )
            stale = cycle is None
            if (
                cycle is not None
                and buffer.kind is MailboxItemKind.SCHEDULED_TASK_TRIGGER
            ):
                task = await self.scheduled_task_repository.get_by_session_and_id(
                    session,
                    session_id=session_id,
                    task_id=cycle.state.task_id,
                    lock=True,
                )
                if (
                    cycle.state.phase != "admitted"
                    or task is None
                    or task.active_cycle_id != cycle_id
                    or task.active_scheduled_for != cycle.state.scheduled_for
                ):
                    await self.scheduled_task_cycle_repository.delete_if_admitted(
                        session,
                        agent_id=agent_session.agent_id,
                        session_id=session_id,
                        cycle_id=cycle_id,
                    )
                    stale = True
            elif cycle is not None and cycle.state.phase != "started":
                stale = True
            if stale:
                await self.mailbox_item_repository.delete_claimed_by_ids(
                    session, session_id, [buffer.id]
                )
                await session.commit()
                return ScheduledMailboxDatabaseAdmission(
                    run=None, buffer=None, cycle=None, events=[], stale=True
                )
            assert cycle is not None
            run = await self.agent_run_repository.create_pending(
                session,
                session_id=session_id,
                parent_agent_run_id=None,
                scheduled_task_cycle_id=cycle_id,
            )
            started_at = datetime.datetime.now(datetime.UTC)
            if buffer.kind is MailboxItemKind.SCHEDULED_TASK_TRIGGER:
                await self.scheduled_task_cycle_repository.start(
                    session, record=cycle, run_id=run.id, started_at=started_at
                )
            else:
                await self.scheduled_task_cycle_repository.bind_run(
                    session, record=cycle, run_id=run.id
                )
            event = _scheduled_event_input(buffer, cycle)
            inserted = await self.append_events_in_session(session, session_id, [event])
            await self.agent_run_repository.associate_input_events(
                session, run_id=run.id, event_ids=[event.id for event in inserted]
            )
            deleted = await self.mailbox_item_repository.delete_claimed_by_ids(
                session, session_id, [buffer.id]
            )
            if deleted != 1:
                raise RuntimeError("Scheduled Task mailbox admission lost its FIFO row")
            await session.commit()
            return ScheduledMailboxDatabaseAdmission(
                run=run, buffer=buffer, cycle=cycle, events=inserted, stale=False
            )

    async def append_events_in_session(
        self, session: AsyncSession, session_id: str, events: Sequence[EventCreate]
    ) -> list[Event]:
        """Append a prepared batch, advancing projections once for actual inserts."""
        inserted: list[Event] = []
        repository = self.event_transcript_repository
        for event in events:
            if event.external_id is None:
                raise ValueError(
                    "Mailbox input event requires durable external identity"
                )
            existing = await self.event_transcript_repository.get_by_external_id(
                session, session_id, event.external_id
            )
            if existing is not None:
                continue
            append = repository.append_with_deferred_session_projections
            inserted.append(await append(session, event))
        if inserted:
            await self.event_transcript_repository.advance_session_projections(
                session, session_id=session_id, events=inserted
            )
        return inserted


def _scheduled_event_input(
    buffer: MailboxItem, cycle: ScheduledTaskCycleRecord
) -> EventCreate:
    state = cycle.state
    content = render_scheduled_task_runtime_message(
        title=state.title,
        objective=state.objective,
        schedule_type=state.schedule_type,
        scheduled_at=state.scheduled_at,
        cron_expression=state.cron_expression,
        timezone=state.timezone,
        scheduled_for=state.scheduled_for,
    )
    if buffer.kind is MailboxItemKind.SCHEDULED_TASK_TRIGGER:
        kind = EventKind.SCHEDULED_TASK_TRIGGER
        payload = ScheduledTaskTriggerPayload(
            cycle_id=state.cycle_id, title=state.title, content=content
        )
    else:
        kind = EventKind.SCHEDULED_TASK_CONTINUATION
        payload = ScheduledTaskContinuationPayload(
            cycle_id=state.cycle_id, title=state.title, content=content
        )
    return EventCreate(
        session_id=buffer.session_id,
        kind=kind,
        payload={
            **_JSON_OBJECT_ADAPTER.validate_python(payload.model_dump(mode="json")),
            "mailbox_item_id": buffer.id,
            "mailbox_item_key": buffer.presentation.item_key,
        },
        external_id=f"{buffer.id}:scheduled_task",
    )
