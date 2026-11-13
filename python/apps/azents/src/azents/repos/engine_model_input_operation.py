"""Completed database operations for Engine model-input preparation."""

import dataclasses
import datetime
import json
from collections.abc import Sequence

import sqlalchemy as sa
from pydantic import ValidationError

from azents.core.enums import AgentRunPhase
from azents.core.scheduled_task import ScheduledTaskCycleTarget
from azents.core.session_resource_authority import SessionExecutionOwner
from azents.engine.events.tool_results import cancelled_tool_result
from azents.engine.events.types import (
    ClientToolCallPayload,
    ClientToolResultPayload,
    Event,
    OutputTextPart,
    ScheduledTaskResultPayload,
)
from azents.rdb.models.event import RDBEvent
from azents.rdb.session import SessionManager
from azents.rdb.session_capabilities import WriteSession
from azents.repos.engine_event_contracts import (
    RunStateRepository,
    SessionHeadRepository,
    TranscriptRepository,
)
from azents.repos.engine_input_projection import EngineInputProjectionRepository
from azents.repos.engine_tool_result_operation import (
    EngineToolResultOperationRepository,
)
from azents.repos.session_execution.ownership import (
    fence_owned_session_mutation,
    validate_session_execution_owner,
)
from azents.repos.work_context import has_unfinished_work


@dataclasses.dataclass(frozen=True)
class PreparedEngineModelInput:
    """Detached model input and projections from one completed transaction."""

    transcript: list[Event]
    repaired_events: list[Event]
    model_call_started_at: datetime.datetime | None


@dataclasses.dataclass(frozen=True)
class EngineModelInputOperationRepository:
    """Own atomic transcript repair, phase, and availability preparation."""

    session_manager: SessionManager[WriteSession]
    run_repository: RunStateRepository
    transcript_repository: TranscriptRepository
    session_head_repository: SessionHeadRepository | None
    tool_result_repository: EngineToolResultOperationRepository
    input_projection_repository: EngineInputProjectionRepository | None
    owner: SessionExecutionOwner | None

    async def prepare_input(
        self,
        *,
        run_id: str,
        session_id: str,
        owner_generation: int,
    ) -> PreparedEngineModelInput:
        """Return input only after its complete database atomic group commits."""
        async with self.session_manager() as session:
            if self.owner is not None:
                await validate_session_execution_owner(session, self.owner)
            head_event_id: str | None = None
            if self.session_head_repository is not None:
                state = await self.session_head_repository.get_by_id(
                    session, session_id
                )
                if state is not None:
                    head_event_id = state.model_input_head_event_id
            transcript = await self.transcript_repository.list_for_model_input(
                session, session_id, head_event_id=head_event_id
            )
            repaired_events = await self._repair_tool_results(
                session,
                run_id=run_id,
                session_id=session_id,
                owner_generation=owner_generation,
                transcript=transcript,
            )
            if repaired_events:
                transcript = await self.transcript_repository.list_for_model_input(
                    session, session_id, head_event_id=head_event_id
                )
            run = await self.run_repository.update_phase(
                session, run_id, AgentRunPhase.PREPARING_INPUT
            )
            if self.input_projection_repository is not None:
                transcript = await self.input_projection_repository.apply_in_session(
                    session,
                    session_id=session_id,
                    transcript=transcript,
                )
            return PreparedEngineModelInput(
                transcript=transcript,
                repaired_events=repaired_events,
                model_call_started_at=run.model_call_started_at,
            )

    async def _repair_tool_results(
        self,
        session: WriteSession,
        *,
        run_id: str,
        session_id: str,
        owner_generation: int,
        transcript: Sequence[Event],
    ) -> list[Event]:
        """Reconcile durable calls without replaying Tool execution."""
        run_state = await self.run_repository.get_by_id(session, run_id)
        if run_state is None:
            raise ValueError("Agent run not found")
        calls_by_id = {
            payload.call_id: payload
            for event in transcript
            if isinstance((payload := event.payload), ClientToolCallPayload)
        }
        result_call_ids = {
            payload.call_id
            for event in transcript
            if isinstance((payload := event.payload), ClientToolResultPayload)
        }
        for active in run_state.active_tool_calls:
            if active.call_id not in calls_by_id:
                raise RuntimeError("Active tool call has no durable call event")
            if active.owner_generation > owner_generation:
                raise RuntimeError("Active tool call owner generation is in the future")
        unresolved_calls = [
            call
            for call_id, call in calls_by_id.items()
            if call_id not in result_call_ids
        ]
        terminal_calls: list[
            tuple[ClientToolCallPayload, ScheduledTaskResultPayload, str]
        ] = []
        for call in unresolved_calls:
            if call.name != "submit_scheduled_task_result":
                continue
            try:
                target = ScheduledTaskCycleTarget.model_validate_json(call.arguments)
            except ValidationError:
                continue
            if target.cycle_id not in run_state.work_context.scheduled_cycle_ids:
                continue
            saved = await session.read_session.scalar(
                sa.select(RDBEvent.payload).where(
                    RDBEvent.session_id == session_id,
                    RDBEvent.external_id == f"scheduled-task-result:{target.cycle_id}",
                )
            )
            if saved is not None:
                terminal_calls.append(
                    (
                        call,
                        ScheduledTaskResultPayload.model_validate(saved),
                        target.cycle_id,
                    )
                )
        appended: list[Event] = []
        finish_run = bool(terminal_calls) and not await has_unfinished_work(
            session, session_id=session_id, context=run_state.work_context
        )
        for call, saved_result, cycle_id in terminal_calls:
            appended.append(
                await self.tool_result_repository.finalize_in_session(
                    session,
                    run_id=run_id,
                    session_id=session_id,
                    call=call,
                    result=ClientToolResultPayload(
                        call_id=call.call_id,
                        name=call.name,
                        wire_dialect=call.wire_dialect,
                        status="completed",
                        output=[
                            OutputTextPart(
                                text=json.dumps(
                                    {
                                        "cycle_id": cycle_id,
                                        "status": saved_result.status,
                                        "result": saved_result.result,
                                        "notify": saved_result.notify,
                                        "suppression_reason": (
                                            saved_result.suppression_reason
                                        ),
                                        "recovered": True,
                                        "outcomes": [],
                                    },
                                    ensure_ascii=False,
                                ),
                            )
                        ],
                        terminal_run=finish_run,
                    ),
                )
            )
        terminal_call_ids = {call.call_id for call, _, _ in terminal_calls}
        for call in unresolved_calls:
            if call.call_id in terminal_call_ids:
                continue
            appended.append(
                await self.tool_result_repository.finalize_in_session(
                    session,
                    run_id=run_id,
                    session_id=session_id,
                    call=call,
                    result=cancelled_tool_result(call),
                )
            )
        stale_resolved_ids = {
            active.call_id
            for active in run_state.active_tool_calls
            if active.call_id in result_call_ids
        }
        if stale_resolved_ids:
            if self.owner is not None:
                await fence_owned_session_mutation(session, self.owner)
            refreshed = await self.run_repository.get_by_id(session, run_id)
            if refreshed is None:
                raise ValueError("Agent run not found")
            remaining = [
                active
                for active in refreshed.active_tool_calls
                if active.call_id not in stale_resolved_ids
            ]
            await self.run_repository.update_phase(
                session,
                run_id,
                AgentRunPhase.EXECUTING_TOOLS
                if remaining
                else AgentRunPhase.APPENDING_EVENTS,
                active_tool_calls=remaining,
            )
        return appended
