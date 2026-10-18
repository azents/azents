"""Routine checking opportunities admitted to the ordinary Session inbox."""

import datetime
from dataclasses import dataclass
from typing import Annotated

from azcommon.uuid import uuid7
from fastapi import Depends

from azents.core.action_execution_data import ActionExecution
from azents.core.enums import (
    ActionExecutionStatus,
    EventKind,
    MailboxItemKind,
    MailboxSchedulingMode,
)
from azents.core.mailbox_data import (
    MailboxPresentationItem,
    RoutineTriggerMailboxPayload,
    TurnActionMailboxPayload,
)
from azents.core.routine import (
    ROUTINE_MIN_ACTION_DELAY,
    ROUTINE_TICK_INTERVAL,
    RoutineScope,
    RoutineUnavailable,
)
from azents.core.routine_execution import (
    RoutineAdmittedContext,
    RoutineCheckState,
    RoutineExecutionState,
    RoutineSourceInput,
)
from azents.core.routine_judgment import (
    RoutineJudgmentCandidate,
    RoutineJudgmentConsidered,
    RoutineSourceEvent,
)
from azents.core.routine_presentation import (
    render_routine_execution_input,
    routine_execution_ref,
)
from azents.core.session_resource_authority import SessionExecutionOwner
from azents.engine.events.action_messages import RoutineJudgmentAction
from azents.engine.events.types import Event, RoutineJudgmentPayload
from azents.rdb.deps import get_session_manager
from azents.rdb.models.agent_session import RDBAgentSession
from azents.rdb.session import SessionManager
from azents.rdb.session_capabilities import WriteSession
from azents.repos.action_execution import ActionExecutionRepository
from azents.repos.agent_execution import EventTranscriptRepository
from azents.repos.agent_execution.data import EventCreate
from azents.repos.mailbox.admission import MailboxAdmissionRepository
from azents.repos.mailbox.admission_data import MailboxAdmissionResult, MailboxEnqueue
from azents.repos.routine.definition import RoutineDefinitionRepository
from azents.repos.routine.records import RoutineWorkRecordRepository
from azents.repos.routine.scope import fence_routine_scope, require_routine_scope
from azents.repos.routine.state import RoutineStateRepository
from azents.repos.session_execution.ownership import (
    fence_owned_session_mutation,
    validate_session_execution_owner,
)


@dataclass(frozen=True)
class RoutineJudgmentInput:
    """Execution-time candidates, detached before any provider I/O."""

    action: RoutineJudgmentAction
    candidates: tuple[RoutineJudgmentCandidate, ...]


@dataclass(frozen=True)
class RoutineJudgmentSettlement:
    """Committed observation and any ordinary selected-work wake."""

    observation: Event | None
    admission: MailboxAdmissionResult | None


@dataclass(frozen=True)
class RoutineJudgmentInboxRepository:
    """Use existing inbox idempotency and Session ownership, not another lease."""

    session_manager: Annotated[
        SessionManager[WriteSession], Depends(get_session_manager)
    ]
    definitions: Annotated[RoutineDefinitionRepository, Depends()]
    records: Annotated[RoutineWorkRecordRepository, Depends()]
    states: Annotated[RoutineStateRepository, Depends()]
    admission: Annotated[MailboxAdmissionRepository, Depends()]
    actions: Annotated[ActionExecutionRepository, Depends()]
    events: Annotated[EventTranscriptRepository, Depends()]

    async def admit_tick(
        self, *, scope: RoutineScope, now: datetime.datetime
    ) -> MailboxAdmissionResult | None:
        """Coalesce source input and atomically enqueue at most one neutral action."""
        _require_aware(now)
        async with self.session_manager() as session:
            await fence_routine_scope(session, scope=scope, owner=None)
            target = await session.read_session.get(RDBAgentSession, scope.session_id)
            if target is None or target.stop_requested_at is not None:
                return None
            record = await self.states.get_check(session, scope=scope)
            previous = (
                record.state
                if record is not None
                else RoutineCheckState(
                    last_tick_at=None,
                    last_action_at=None,
                    source_inputs=(),
                    queued_judgment_id=None,
                )
            )
            if (
                previous.last_tick_at is not None
                and now - previous.last_tick_at < ROUTINE_TICK_INTERVAL
            ):
                return None
            definitions = await self.definitions.list_for_session(session, scope=scope)
            current_ids = {item.id for item in definitions}
            sources = {
                item.routine_id: item.events
                for item in previous.source_inputs
                if item.routine_id in current_ids
            }
            for definition in definitions:
                if definition.content.sources:
                    sources[definition.id] = (
                        *sources.get(definition.id, ()),
                        RoutineSourceEvent(source_type="manual", observed_at=now),
                    )
            next_state = RoutineCheckState(
                last_tick_at=now,
                last_action_at=previous.last_action_at,
                source_inputs=tuple(
                    RoutineSourceInput(routine_id=key, events=events)
                    for key, events in sorted(sources.items())
                ),
                queued_judgment_id=previous.queued_judgment_id,
            )
            admission = None
            if (
                next_state.queued_judgment_id is None
                and _delay_passes(next_state, now=now)
                and await self._candidates(session, scope=scope, state=next_state)
            ):
                action = RoutineJudgmentAction(judgment_id=uuid7().hex)
                admission = await self.admission.enqueue_in_session(
                    session,
                    MailboxEnqueue(
                        session_id=scope.session_id,
                        kind=MailboxItemKind.ACTION_MESSAGE,
                        scheduling_mode=MailboxSchedulingMode.WAKE_SESSION,
                        requested_model_target_label=None,
                        requested_reasoning_effort=None,
                        requested_enabled_execution_options=[],
                        sender_user_id=None,
                        order_group=None,
                        order_sequence=0,
                        content="",
                        idempotency_key=f"routine-judgment:{action.judgment_id}",
                        metadata={},
                        attachments=[],
                        file_parts=[],
                        action=action.model_dump(mode="json"),
                        payload=TurnActionMailboxPayload(
                            type="action_message",
                            items=[
                                MailboxPresentationItem(
                                    item_key="action_message:0",
                                    presentation_kind="action_message",
                                    action=action.model_dump(mode="json"),
                                )
                            ],
                        ),
                    ),
                )
                next_state = next_state.model_copy(
                    update={"queued_judgment_id": action.judgment_id}
                )
            await self.states.save_check(
                session,
                scope=scope,
                state=next_state,
                expected_version=None if record is None else record.version,
            )
            return admission

    async def capture(
        self,
        *,
        scope: RoutineScope,
        action: RoutineJudgmentAction,
        execution: ActionExecution,
        owner: SessionExecutionOwner,
        now: datetime.datetime,
    ) -> RoutineJudgmentInput:
        """Capture live definitions and source input at normal action execution."""
        _require_aware(now)
        async with self.session_manager() as session:
            await fence_routine_scope(session, scope=scope, owner=owner)
            target = await session.read_session.get(RDBAgentSession, scope.session_id)
            projection = await self.actions.lock_projection_by_id(
                session,
                action_execution_id=execution.id,
                session_id=scope.session_id,
            )
            if (
                target is None
                or target.stop_requested_at is not None
                or projection is None
                or projection.execution.owner_generation != owner.owner_generation
                or projection.execution.action != action.model_dump(mode="json")
                or projection.execution.status
                not in {ActionExecutionStatus.PENDING, ActionExecutionStatus.RUNNING}
            ):
                raise RoutineUnavailable("Routine inbox action is no longer current.")
            record = await self.states.get_check(session, scope=scope)
            if record is None or record.state.queued_judgment_id != action.judgment_id:
                raise RoutineUnavailable("Routine inbox action is no longer pending.")
            candidates = (
                await self._candidates(session, scope=scope, state=record.state)
                if _delay_passes(record.state, now=now)
                else ()
            )
            await self.actions.mark_running(
                session, action_execution_id=execution.id, started_at=now
            )
            return RoutineJudgmentInput(action=action, candidates=candidates)

    async def settle(
        self,
        *,
        scope: RoutineScope,
        captured: RoutineJudgmentInput,
        execution: ActionExecution,
        owner: SessionExecutionOwner,
        outcome: RoutineJudgmentPayload | None,
        provider: str | None,
        model: str | None,
        now: datetime.datetime,
    ) -> RoutineJudgmentSettlement:
        """Commit observation, item admission, source consumption and action close."""
        _require_aware(now)
        if outcome is None:
            if captured.candidates:
                raise ValueError("Nonempty Routine judgment requires an outcome.")
        else:
            if outcome.judgment_id != captured.action.judgment_id:
                raise ValueError("Routine judgment outcome identity does not match.")
            if outcome.considered != tuple(
                RoutineJudgmentConsidered(
                    routine_id=item.routine_id, slug=item.slug, title=item.content.title
                )
                for item in captured.candidates
            ):
                raise ValueError("Routine judgment considered candidates do not match.")
            if outcome.decision is not None:
                outcome.decision.validate_candidates(captured.candidates)
        external_id = f"routine-judgment:{captured.action.judgment_id}"
        async with self.session_manager() as session:
            await fence_routine_scope(session, scope=scope, owner=owner)
            target = await session.read_session.get(RDBAgentSession, scope.session_id)
            if target is None or target.stop_requested_at is not None:
                raise RoutineUnavailable("Routine judgment was stopped.")
            projection = await self.actions.lock_projection_by_id(
                session, action_execution_id=execution.id, session_id=scope.session_id
            )
            if projection is None:
                existing = await self.events.get_by_external_id(
                    session, scope.session_id, external_id
                )
                if existing is not None:
                    return RoutineJudgmentSettlement(
                        observation=existing, admission=None
                    )
                raise RoutineUnavailable("Routine inbox action is no longer current.")
            if (
                projection.execution.owner_generation != owner.owner_generation
                or projection.execution.action
                != captured.action.model_dump(mode="json")
                or projection.execution.status
                not in {ActionExecutionStatus.PENDING, ActionExecutionStatus.RUNNING}
            ):
                raise RoutineUnavailable("Routine inbox action is no longer current.")
            check = await self.states.get_check(session, scope=scope)
            if (
                check is None
                or check.state.queued_judgment_id != captured.action.judgment_id
            ):
                raise RoutineUnavailable("Routine inbox action is no longer pending.")
            selected = (
                {item.routine_id for item in outcome.decision.decisions if item.act}
                if outcome is not None and outcome.decision is not None
                else set()
            )
            current_ids = {
                item.id
                for item in await self.definitions.list_for_session(
                    session, scope=scope
                )
            }
            admitted: list[RoutineExecutionState] = []
            for candidate in captured.candidates:
                if (
                    candidate.routine_id not in selected
                    or candidate.routine_id not in current_ids
                ):
                    continue
                previous = await self.states.get_execution(
                    session, scope=scope, routine_id=candidate.routine_id
                )
                if (
                    not _delay_passes(check.state, now=now)
                    or previous is not None
                    and previous.state.incomplete
                ):
                    continue
                state = RoutineExecutionState(
                    context=RoutineAdmittedContext(
                        execution_id=uuid7().hex,
                        judgment_id=captured.action.judgment_id,
                        scope=scope,
                        candidate=candidate,
                        admitted_at=now,
                    ),
                    phase="admitted",
                    current_run_id=None,
                    started_at=None,
                    completed_at=None,
                    work=None,
                    delivery_status=None,
                    delivery_error=None,
                )
                await self.states.save_execution(
                    session,
                    scope=scope,
                    state=state,
                    expected_version=None if previous is None else previous.version,
                )
                admitted.append(state)
            admission = None
            if admitted:
                states = tuple(admitted)
                content = render_routine_execution_input(states, continuation=False)
                admission = await self.admission.enqueue_in_session(
                    session,
                    MailboxEnqueue(
                        session_id=scope.session_id,
                        kind=MailboxItemKind.ROUTINE_TRIGGER,
                        scheduling_mode=MailboxSchedulingMode.WAKE_SESSION,
                        requested_model_target_label=None,
                        requested_reasoning_effort=None,
                        requested_enabled_execution_options=[],
                        sender_user_id=None,
                        order_group=None,
                        order_sequence=0,
                        content=content,
                        idempotency_key=f"{external_id}:selected",
                        metadata={},
                        attachments=[],
                        file_parts=[],
                        action=None,
                        payload=RoutineTriggerMailboxPayload(
                            type="routine_trigger",
                            executions=tuple(
                                routine_execution_ref(item) for item in states
                            ),
                            items=[
                                MailboxPresentationItem(
                                    item_key="routine_trigger:0",
                                    presentation_kind="routine_trigger",
                                    content=content,
                                )
                            ],
                        ),
                    ),
                )
            observation = (
                await self.events.append(
                    session,
                    EventCreate(
                        session_id=scope.session_id,
                        kind=EventKind.ROUTINE_JUDGMENT,
                        payload=outcome.model_dump(mode="json"),
                        external_id=external_id,
                        provider=provider,
                        model=model,
                    ),
                )
                if outcome is not None
                else None
            )
            admitted_ids = {item.context.candidate.routine_id for item in admitted}
            consumed = (
                {
                    item.routine_id: item.events
                    for item in captured.candidates
                    if item.routine_id not in selected
                    or item.routine_id in admitted_ids
                }
                if outcome is not None and outcome.decision is not None
                else {}
            )
            remaining: list[RoutineSourceInput] = []
            for source in check.state.source_inputs:
                prefix = consumed.get(source.routine_id, ())
                if source.events[: len(prefix)] != prefix:
                    raise ValueError(
                        "Routine source continuity changed during judgment."
                    )
                events = source.events[len(prefix) :]
                if events:
                    remaining.append(
                        RoutineSourceInput(routine_id=source.routine_id, events=events)
                    )
            await self.states.save_check(
                session,
                scope=scope,
                state=RoutineCheckState(
                    last_tick_at=check.state.last_tick_at,
                    last_action_at=now if admitted else check.state.last_action_at,
                    source_inputs=tuple(remaining),
                    queued_judgment_id=None,
                ),
                expected_version=check.version,
            )
            await self.actions.delete_by_id(session, action_execution_id=execution.id)
            return RoutineJudgmentSettlement(
                observation=observation, admission=admission
            )

    async def capture_transcript(
        self, *, scope: RoutineScope, owner: SessionExecutionOwner
    ) -> list[Event]:
        """Read the same canonical head and transcript as ordinary model input."""
        if owner.session_id != scope.session_id:
            raise RoutineUnavailable("Routine context owner does not match Session.")
        async with self.session_manager() as session:
            await validate_session_execution_owner(session, owner)
            await require_routine_scope(session, scope=scope)
            target = await session.read_session.get(RDBAgentSession, scope.session_id)
            if target is None or target.stop_requested_at is not None:
                raise RoutineUnavailable("Routine judgment context was stopped.")
            return await self.events.list_for_model_input(
                session,
                scope.session_id,
                head_event_id=target.model_input_head_event_id,
            )

    async def assert_current_owner(self, *, owner: SessionExecutionOwner) -> None:
        """Observe ordinary ownership immediately before an external model call."""
        async with self.session_manager() as session:
            await validate_session_execution_owner(session, owner)

    async def cancel_action(
        self, *, execution: ActionExecution, owner: SessionExecutionOwner
    ) -> None:
        """Remove a normal inbox action during Stop or ordinary owner recovery."""
        if execution.session_id != owner.session_id:
            raise RoutineUnavailable("Routine action owner does not match Session.")
        action = RoutineJudgmentAction.model_validate(execution.action)
        async with self.session_manager() as session:
            await fence_owned_session_mutation(session, owner)
            projection = await self.actions.lock_projection_by_id(
                session,
                action_execution_id=execution.id,
                session_id=owner.session_id,
            )
            if projection is None:
                return
            if projection.execution.action != execution.action:
                raise RoutineUnavailable("Routine action identity changed.")
            target = await session.read_session.get(RDBAgentSession, owner.session_id)
            if target is None:
                raise RoutineUnavailable("Routine action Session is unavailable.")
            scope = RoutineScope(
                workspace_id=target.workspace_id,
                agent_id=target.agent_id,
                session_id=target.id,
            )
            check = await self.states.get_check(session, scope=scope)
            if (
                check is not None
                and check.state.queued_judgment_id == action.judgment_id
            ):
                await self.states.save_check(
                    session,
                    scope=scope,
                    state=check.state.model_copy(update={"queued_judgment_id": None}),
                    expected_version=check.version,
                )
            await self.actions.delete_by_id(session, action_execution_id=execution.id)

    async def _candidates(
        self, session: WriteSession, *, scope: RoutineScope, state: RoutineCheckState
    ) -> tuple[RoutineJudgmentCandidate, ...]:
        sources = {item.routine_id: item.events for item in state.source_inputs}
        candidates: list[RoutineJudgmentCandidate] = []
        for definition in await self.definitions.list_for_session(session, scope=scope):
            events = sources.get(definition.id)
            if not events:
                continue
            execution = await self.states.get_execution(
                session, scope=scope, routine_id=definition.id
            )
            if execution is not None and execution.state.incomplete:
                continue
            records = await self.records.list_recent(
                session, scope=scope, routine_id=definition.id, limit=1
            )
            candidates.append(
                RoutineJudgmentCandidate(
                    routine_id=definition.id,
                    slug=definition.slug,
                    content=definition.content,
                    events=events,
                    last_executed_at=None if not records else records[0].started_at,
                    latest_work=None if not records else records[0].work,
                )
            )
        return tuple(candidates)


def _require_aware(now: datetime.datetime) -> None:
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("Routine checking time must be timezone-aware.")


def _delay_passes(state: RoutineCheckState, *, now: datetime.datetime) -> bool:
    return (
        state.last_action_at is None
        or now - state.last_action_at >= ROUTINE_MIN_ACTION_DELAY
    )
