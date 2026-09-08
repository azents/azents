"""Repository-owned atomic Mailbox promotion."""

import dataclasses
import enum
import logging
from typing import Annotated

from fastapi import Depends
from pydantic import TypeAdapter
from sqlalchemy.ext.asyncio import AsyncSession

from azents.core.enums import ActionExecutionStatus, AgentRunStatus, EventKind
from azents.core.skill_projection import SkillProjectionItem, resolve_active_skill
from azents.engine.events.types import AgentMessagePayload, Event
from azents.rdb.deps import get_session_manager
from azents.rdb.models.event import JSONValue
from azents.rdb.session import SessionManager
from azents.repos.action_execution import ActionExecutionRepository
from azents.repos.action_execution.data import ActionExecution, ActionExecutionCreate
from azents.repos.agent_execution import AgentRunRepository, EventTranscriptRepository
from azents.repos.agent_execution.data import EventCreate
from azents.repos.agent_session import AgentSessionRepository
from azents.repos.goal.store import (
    GoalAlreadyExistsError,
    GoalStateStore,
    get_goal_state_store,
)
from azents.repos.mailbox import MailboxRepository
from azents.repos.mailbox.data import MailboxItem
from azents.repos.skill_state import SkillStateRepository

logger = logging.getLogger(__name__)
_AGENT_MESSAGE_ADAPTER = TypeAdapter(AgentMessagePayload)


class MailboxPromotionConflict(enum.StrEnum):
    """Authority predicate that changed after promotion preflight."""

    OWNER_GENERATION = "owner_generation"
    FIFO_HEAD = "fifo_head"


class MailboxPromotionConflictError(RuntimeError):
    """Mailbox promotion preflight no longer matches durable authority."""

    def __init__(self, conflict: MailboxPromotionConflict) -> None:
        """Create a typed promotion conflict."""
        super().__init__(conflict.value)
        self.conflict = conflict


@dataclasses.dataclass(frozen=True)
class MailboxPromotionEvent:
    """One prepared semantic event for atomic Mailbox promotion."""

    kind: EventKind
    payload: dict[str, JSONValue]
    external_id: str
    item_key: str
    initial_title_candidate: str | None


@dataclasses.dataclass(frozen=True)
class MailboxGoalCreate:
    """Typed Goal mutation performed with Mailbox promotion."""

    objective: str
    updated_at: str


@dataclasses.dataclass(frozen=True)
class MailboxSkillRevalidation:
    """Filesystem Skill projection authority expected after preflight."""

    item: SkillProjectionItem


@dataclasses.dataclass(frozen=True)
class MailboxActionExecutionCreate:
    """Typed operation action handoff performed with Mailbox promotion."""

    action_type: str
    action: dict[str, JSONValue]


@dataclasses.dataclass(frozen=True)
class MailboxPromotionPlan:
    """Detached preparation consumed by one final database transaction."""

    session_id: str
    owner_generation: int
    expected_buffer_id: str | None
    active_run_id: str | None
    success_events: list[MailboxPromotionEvent]
    failure_events: list[MailboxPromotionEvent]
    goal_create: MailboxGoalCreate | None
    skill_revalidation: MailboxSkillRevalidation | None
    action_execution: MailboxActionExecutionCreate | None
    continuation_predecessor_run_id: str | None


@dataclasses.dataclass(frozen=True)
class MailboxPromotionResult:
    """Committed atomic Mailbox promotion result."""

    buffer: MailboxItem | None
    events: list[Event]
    promoted_event_ids: list[str]
    deleted_buffer_ids: list[str]
    changed_session_agent_ids: list[str]
    action_execution: ActionExecution | None
    deduped_count: int
    handled_failure: bool
    deferred: bool


@dataclasses.dataclass
class MailboxPromotionRepository:
    """Compose the final database-only Mailbox promotion transaction."""

    session_manager: Annotated[
        SessionManager[AsyncSession], Depends(get_session_manager)
    ]
    mailbox_repository: Annotated[MailboxRepository, Depends(MailboxRepository)]
    session_repository: Annotated[
        AgentSessionRepository, Depends(AgentSessionRepository)
    ]
    event_repository: Annotated[
        EventTranscriptRepository, Depends(EventTranscriptRepository)
    ]
    run_repository: Annotated[AgentRunRepository, Depends(AgentRunRepository)]
    action_execution_repository: Annotated[
        ActionExecutionRepository, Depends(ActionExecutionRepository)
    ]
    goal_store: Annotated[GoalStateStore, Depends(get_goal_state_store)]
    skill_state_repository: Annotated[
        SkillStateRepository, Depends(SkillStateRepository)
    ]

    async def promote(self, plan: MailboxPromotionPlan) -> MailboxPromotionResult:
        """Validate authority and atomically promote one prepared FIFO head."""
        async with self.session_manager() as session:
            agent_session = await self.session_repository.lock_by_id(
                session,
                plan.session_id,
            )
            if agent_session is None:
                raise ValueError("AgentSession not found")
            if agent_session.owner_generation != plan.owner_generation:
                raise MailboxPromotionConflictError(
                    MailboxPromotionConflict.OWNER_GENERATION
                )
            buffer = await self.mailbox_repository.lock_oldest_by_session_id(
                session,
                plan.session_id,
            )
            actual_buffer_id = buffer.id if buffer is not None else None
            if actual_buffer_id != plan.expected_buffer_id:
                raise MailboxPromotionConflictError(MailboxPromotionConflict.FIFO_HEAD)
            if buffer is None:
                return MailboxPromotionResult(
                    buffer=None,
                    events=[],
                    promoted_event_ids=[],
                    deleted_buffer_ids=[],
                    changed_session_agent_ids=[],
                    action_execution=None,
                    deduped_count=0,
                    handled_failure=False,
                    deferred=False,
                )

            if plan.continuation_predecessor_run_id is not None:
                predecessor = await self.run_repository.get_by_id(
                    session,
                    plan.continuation_predecessor_run_id,
                )
                if predecessor is None or predecessor.session_id != plan.session_id:
                    raise ValueError(
                        "TurnAction continuation predecessor Run is invalid."
                    )
                if predecessor.status in {
                    AgentRunStatus.PENDING,
                    AgentRunStatus.RUNNING,
                }:
                    return MailboxPromotionResult(
                        buffer=buffer,
                        events=[],
                        promoted_event_ids=[],
                        deleted_buffer_ids=[],
                        changed_session_agent_ids=[],
                        action_execution=None,
                        deduped_count=0,
                        handled_failure=False,
                        deferred=True,
                    )

            handled_failure = False
            prepared_events = plan.success_events
            if plan.skill_revalidation is not None:
                state = await self.skill_state_repository.load_in_session(
                    session,
                    agent_id=agent_session.agent_id,
                    session_id=plan.session_id,
                )
                current = resolve_active_skill(
                    state,
                    skill_path=plan.skill_revalidation.item.skill_path,
                )
                if current != plan.skill_revalidation.item:
                    handled_failure = True
                    prepared_events = plan.failure_events
            if plan.goal_create is not None:
                try:
                    await self.goal_store.create_in_session(
                        session,
                        agent_id=agent_session.agent_id,
                        session_id=plan.session_id,
                        objective=plan.goal_create.objective,
                        updated_at=plan.goal_create.updated_at,
                    )
                except GoalAlreadyExistsError:
                    handled_failure = True
                    prepared_events = plan.failure_events

            action_execution = None
            if plan.action_execution is not None:
                action_execution = await self.action_execution_repository.create(
                    session,
                    ActionExecutionCreate(
                        id=None,
                        session_id=plan.session_id,
                        mailbox_item_id=buffer.id,
                        sender_user_id=buffer.sender_user_id,
                        action_type=plan.action_execution.action_type,
                        action=plan.action_execution.action,
                        status=ActionExecutionStatus.PENDING,
                        owner_generation=agent_session.owner_generation,
                    ),
                )

            ordered_events, inserted_events = await self._append_events(
                session,
                session_id=plan.session_id,
                buffer=buffer,
                prepared=prepared_events,
            )
            event_by_external_id = {
                event.external_id: event
                for event in ordered_events
                if event.external_id is not None
            }
            for prepared in prepared_events:
                candidate = prepared.initial_title_candidate
                if candidate is None:
                    continue
                event = event_by_external_id[prepared.external_id]
                await self.session_repository.set_initial_auto_title_if_unset(
                    session,
                    session_id=plan.session_id,
                    title=candidate,
                    event_id=event.id,
                )
            promoted_event_ids = list(
                dict.fromkeys(
                    event_by_external_id[prepared.external_id].id
                    for prepared in prepared_events
                )
            )
            changed_session_agent_ids = await self._acknowledge_agent_results(
                session,
                session_id=plan.session_id,
                prepared=prepared_events,
            )
            if plan.active_run_id is not None:
                await self.run_repository.associate_input_events(
                    session,
                    run_id=plan.active_run_id,
                    event_ids=promoted_event_ids,
                )
            deleted_count = await self.mailbox_repository.delete_claimed_by_ids(
                session,
                plan.session_id,
                [buffer.id],
            )
            if deleted_count != 1:
                logger.warning(
                    "Input buffer flush deleted a different row count",
                    extra={
                        "session_id": plan.session_id,
                        "claimed_count": 1,
                        "deleted_count": deleted_count,
                    },
                )
            return MailboxPromotionResult(
                buffer=buffer,
                events=inserted_events,
                promoted_event_ids=promoted_event_ids,
                deleted_buffer_ids=[buffer.id],
                changed_session_agent_ids=changed_session_agent_ids,
                action_execution=action_execution,
                deduped_count=len(ordered_events) - len(inserted_events),
                handled_failure=handled_failure,
                deferred=False,
            )

    async def _append_events(
        self,
        session: AsyncSession,
        *,
        session_id: str,
        buffer: MailboxItem,
        prepared: list[MailboxPromotionEvent],
    ) -> tuple[list[Event], list[Event]]:
        """Append prepared events and recover idempotent conflicts."""
        events_by_external_id: dict[str, Event] = {}
        inserted: list[Event] = []
        for item in prepared:
            existing = await self.event_repository.get_by_external_id(
                session,
                session_id,
                item.external_id,
            )
            if existing is not None:
                events_by_external_id[item.external_id] = existing
                continue
            event = (
                await self.event_repository.append_with_deferred_session_projections(
                    session,
                    EventCreate(
                        session_id=session_id,
                        kind=item.kind,
                        payload={
                            **item.payload,
                            "mailbox_item_id": buffer.id,
                            "mailbox_item_key": item.item_key,
                        },
                        external_id=item.external_id,
                    ),
                )
            )
            inserted.append(event)
            events_by_external_id[item.external_id] = event
        if inserted:
            await self.event_repository.advance_session_projections(
                session,
                session_id=session_id,
                events=inserted,
            )
        missing = [
            item.external_id
            for item in prepared
            if item.external_id not in events_by_external_id
        ]
        if missing:
            raise RuntimeError("Conflicted input buffer event was not found")
        return [events_by_external_id[item.external_id] for item in prepared], inserted

    async def _acknowledge_agent_results(
        self,
        session: AsyncSession,
        *,
        session_id: str,
        prepared: list[MailboxPromotionEvent],
    ) -> list[str]:
        """Advance source cursors for terminal results consumed by the model."""
        result_payloads: list[AgentMessagePayload] = []
        for item in prepared:
            if item.kind is not EventKind.AGENT_MESSAGE:
                continue
            payload = _AGENT_MESSAGE_ADAPTER.validate_python(item.payload)
            if payload.message_kind == "agent_result":
                result_payloads.append(payload)
        if not result_payloads:
            return []

        target = await self.session_repository.get_session_agent_by_session_id(
            session,
            session_id,
        )
        if target is None:
            return []
        changed_ids: list[str] = []
        for payload in result_payloads:
            if payload.target_session_agent_id != target.id:
                continue
            assert payload.source_run_id is not None
            assert payload.source_run_index is not None
            assert payload.run_status is not None
            source = await self.session_repository.get_session_agent_by_id(
                session,
                payload.source_session_agent_id,
            )
            run = await self.run_repository.get_by_id(
                session,
                payload.source_run_id,
            )
            if (
                source is None
                or source.parent_session_agent_id != target.id
                or run is None
                or run.session_id != source.agent_session_id
                or run.run_index != payload.source_run_index
                or run.status != payload.run_status
                or run.terminal_result_event_id
                != payload.source_terminal_result_event_id
            ):
                continue
            updated = (
                await self.session_repository.advance_session_agent_observation_cursor(
                    session,
                    session_agent_id=payload.source_session_agent_id,
                    parent_session_agent_id=target.id,
                    parent_observed_run_index=payload.source_run_index,
                    parent_observed_event_id=payload.source_terminal_result_event_id,
                )
            )
            if updated is not None:
                changed_ids.append(updated.id)
        return list(dict.fromkeys(changed_ids))
