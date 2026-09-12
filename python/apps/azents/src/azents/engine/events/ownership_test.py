"""Real PostgreSQL regressions for obsolete engine execution authority."""

import asyncio
import dataclasses
from collections.abc import Sequence

import pytest
from azcommon.uuid import uuid7
from sqlalchemy.ext.asyncio import AsyncSession

from azents.core.enums import AgentRunStatus, AgentSessionProductMode, EventKind
from azents.engine.context.compaction import CompactionSummaryBudget
from azents.engine.events.engine_adapter import _OwnerBoundClientToolInvoker
from azents.engine.events.execution import AgentRunExecution, AgentRunExecutionRequest
from azents.engine.events.execution_test import (
    _assistant_event,
    _BlockingModelAdapter,
    _model_call_preparer,
    _ModelAdapter,
    _Normalizer,
    _OpenToolAdmissionBarrier,
    _PostFilter,
    _tool_call_event,
    _ToolExecutor,
)
from azents.engine.events.filters import EventCompactor
from azents.engine.events.protocols import NativeEvent, NativeModelRequest
from azents.engine.events.tool_invocation import (
    PreparedClientToolInvocation,
    UnboundedClientToolResult,
)
from azents.engine.events.types import (
    ClientToolCallPayload,
    ClientToolResultPayload,
    Event,
    OutputTextPart,
    UserMessagePayload,
)
from azents.engine.run.turn_action_bridge import TurnActionBridgeBoundary
from azents.rdb.session import SessionManager
from azents.repos.agent_execution import AgentRunRepository, EventTranscriptRepository
from azents.repos.agent_execution.data import AgentRunCreate, EventCreate
from azents.repos.agent_session import AgentSessionRepository
from azents.repos.agent_session.data import AgentSessionCreate
from azents.repos.agent_session.repository_test import _create_agent, _create_workspace
from azents.repos.session_execution import CanonicalExecutionOwnerGenerationStaleError
from azents.repos.session_execution.ownership import OwnerBoundSessionManager
from azents.testing.model_stream import make_test_model_stream_watchdog


@dataclasses.dataclass(frozen=True)
class _ExecutionState:
    session_id: str
    run_id: str
    owner: OwnerBoundSessionManager
    input_event: Event


async def _create_execution(
    session_manager: SessionManager[AsyncSession],
) -> _ExecutionState:
    """Create committed durable authority and input before starting external work."""
    sessions = AgentSessionRepository()
    async with session_manager() as session:
        handle = f"engine-owner-{uuid7().hex}"
        workspace_id = await _create_workspace(session, handle)
        agent_id = await _create_agent(session, workspace_id, handle)
        created = await sessions.create(
            session,
            AgentSessionCreate(
                workspace_id=workspace_id,
                product_mode=AgentSessionProductMode.TEAM,
                associated_user_id=None,
                agent_id=agent_id,
                title=None,
            ),
        )
        generation = await sessions.claim_owner_generation(session, created.id)
        run = await AgentRunRepository().create(
            session,
            AgentRunCreate(
                session_id=created.id,
                parent_agent_run_id=None,
                scheduled_task_cycle_id=None,
            ),
        )
        event = await EventTranscriptRepository().append(
            session,
            EventCreate(
                session_id=created.id,
                kind=EventKind.USER_MESSAGE,
                payload=UserMessagePayload(
                    sender_user_id=None,
                    content="Complete this request under the current owner.",
                ).model_dump(mode="json"),
            ),
        )
    return _ExecutionState(
        session_id=created.id,
        run_id=run.id,
        owner=OwnerBoundSessionManager(
            session_manager=session_manager,
            session_id=created.id,
            owner_generation=generation,
        ),
        input_event=event,
    )


async def _take_over(
    session_manager: SessionManager[AsyncSession], state: _ExecutionState
) -> None:
    """Claim the next owner with repository code, never a test-only SQL update."""
    async with session_manager() as session:
        generation = await AgentSessionRepository().claim_owner_generation(
            session, state.session_id
        )
    assert generation == state.owner.owner_generation + 1


def _request(state: _ExecutionState) -> AgentRunExecutionRequest:
    """Build the immutable old-owner execution request."""
    return AgentRunExecutionRequest(
        run_id=state.run_id,
        session_id=state.session_id,
        model="test-model",
        owner_generation=state.owner.owner_generation,
        tool_admission_barrier=_OpenToolAdmissionBarrier(),
        turn_action_bridge_boundary=TurnActionBridgeBoundary(),
        max_turns=1,
    )


def _execution(
    state: _ExecutionState,
    *,
    model_adapter: _ModelAdapter | _BlockingModelAdapter,
    events: list[Event],
    tool_executor: _ToolExecutor,
) -> AgentRunExecution[NativeModelRequest, NativeEvent]:
    """Use actual durable repositories with fake external model/tool providers."""
    return AgentRunExecution(
        session_manager=state.owner,
        post_lower_filter=_PostFilter(),
        model_stream_watchdog=make_test_model_stream_watchdog(),
        model_stream_provider="test",
        model_stream_provider_integration_id=None,
        model_stream_inference_profile=None,
        model_adapter=model_adapter,
        output_normalizer=_Normalizer(events),
        model_call_preparer=_model_call_preparer(tool_executor=tool_executor),
    )


async def test_old_model_response_cannot_commit_output_or_terminal_state(
    rdb_session_manager: SessionManager[AsyncSession],
) -> None:
    """Takeover completes during a blocked stream and rejects its later output."""
    state = await _create_execution(rdb_session_manager)
    model = _BlockingModelAdapter()
    execution = _execution(
        state,
        model_adapter=model,
        events=[_assistant_event().model_copy(update={"session_id": state.session_id})],
        tool_executor=_ToolExecutor(),
    )
    task = asyncio.create_task(execution.run(_request(state)))
    try:
        async with asyncio.timeout(10):
            await model.waiting_after_delta.wait()
            await _take_over(rdb_session_manager, state)
            model.release.set()
            with pytest.raises(CanonicalExecutionOwnerGenerationStaleError):
                await task
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
    async with rdb_session_manager() as session:
        events = await EventTranscriptRepository().list_for_model_input(
            session, state.session_id
        )
        run = await AgentRunRepository().get_by_id(session, state.run_id)
    assert [event.id for event in events] == [state.input_event.id]
    assert run is not None
    assert run.status is AgentRunStatus.RUNNING
    assert run.terminal_result_event_id is None


class _RecordingInvoker:
    """Record an external effect only when its handler is actually admitted."""

    def __init__(self) -> None:
        self.invocations: list[PreparedClientToolInvocation] = []

    def request_cancel(self, call: PreparedClientToolInvocation) -> None:
        """No effect has started in the rejected-admission scenario."""
        del call

    async def invoke(
        self, call: PreparedClientToolInvocation
    ) -> UnboundedClientToolResult:
        """Record the external call and return its ordinary result."""
        self.invocations.append(call)
        return UnboundedClientToolResult(
            call_id=call.call_id,
            name=call.name,
            wire_dialect=call.wire_dialect,
            status="completed",
            execution_succeeded=True,
            output=[OutputTextPart(text="effect completed")],
            metadata={},
            pending_generated_files=(),
            terminal_run=False,
        )


async def test_superseded_tool_admission_never_invokes_external_handler(
    rdb_session_manager: SessionManager[AsyncSession],
) -> None:
    """The adapter's actual tool wrapper rejects a revoked owner before I/O."""
    state = await _create_execution(rdb_session_manager)
    inner = _RecordingInvoker()
    invoker = _OwnerBoundClientToolInvoker(inner=inner, owner=state.owner)
    await _take_over(rdb_session_manager, state)
    with pytest.raises(CanonicalExecutionOwnerGenerationStaleError):
        await invoker.invoke(
            PreparedClientToolInvocation(
                call_id="revoked-call",
                name="external_effect",
                arguments="{}",
                wire_dialect="json_function",
            )
        )
    assert inner.invocations == []


class _BlockedToolExecutor(_ToolExecutor):
    """Pause an admitted external tool until ownership has changed."""

    def __init__(self) -> None:
        super().__init__()
        self.started = asyncio.Event()
        self.release = asyncio.Event()

    async def execute(self, call: ClientToolCallPayload) -> ClientToolResultPayload:
        """Complete the original effect once, without replay after takeover."""
        self.started.set()
        await self.release.wait()
        return await super().execute(call)


async def test_completed_old_tool_cannot_commit_result_after_takeover(
    rdb_session_manager: SessionManager[AsyncSession],
) -> None:
    """An already admitted call may complete, but its obsolete result is fenced."""
    state = await _create_execution(rdb_session_manager)
    tool = _BlockedToolExecutor()
    execution = _execution(
        state,
        model_adapter=_ModelAdapter(),
        events=[_tool_call_event().model_copy(update={"session_id": state.session_id})],
        tool_executor=tool,
    )
    task = asyncio.create_task(execution.run(_request(state)))
    try:
        async with asyncio.timeout(10):
            await tool.started.wait()
            await _take_over(rdb_session_manager, state)
            tool.release.set()
            with pytest.raises(CanonicalExecutionOwnerGenerationStaleError):
                await task
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
    async with rdb_session_manager() as session:
        events = await EventTranscriptRepository().list_for_model_input(
            session, state.session_id
        )
        run = await AgentRunRepository().get_by_id(session, state.run_id)
    assert len(tool.executed_calls) == 1
    assert sum(event.kind is EventKind.CLIENT_TOOL_CALL for event in events) == 1
    assert not any(event.kind is EventKind.CLIENT_TOOL_RESULT for event in events)
    assert run is not None
    assert run.status is AgentRunStatus.RUNNING
    assert len(run.active_tool_calls) == 1
    assert run.active_tool_calls[0].owner_generation == state.owner.owner_generation


async def test_old_compaction_summary_cannot_move_new_owner_input_head(
    rdb_session_manager: SessionManager[AsyncSession],
) -> None:
    """Summary generation is outside the transaction and its commit is fenced."""
    state = await _create_execution(rdb_session_manager)
    started = asyncio.Event()
    release = asyncio.Event()

    async def summarize(
        events: Sequence[Event], budget: CompactionSummaryBudget
    ) -> str:
        del events, budget
        started.set()
        await release.wait()
        return "This summary was generated under an obsolete owner."

    compactor = EventCompactor(
        session_manager=rdb_session_manager,
        transcript_repo=EventTranscriptRepository(),
        session_repo=AgentSessionRepository(),
    ).with_session_manager(state.owner)
    task = asyncio.create_task(
        compactor.compact(
            session_id=state.session_id,
            transcript=[state.input_event],
            compaction_id=uuid7().hex,
            summarize=summarize,
        )
    )
    try:
        async with asyncio.timeout(10):
            await started.wait()
            await _take_over(rdb_session_manager, state)
            release.set()
            with pytest.raises(CanonicalExecutionOwnerGenerationStaleError):
                await task
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
    async with rdb_session_manager() as session:
        events = await EventTranscriptRepository().list_for_model_input(
            session, state.session_id
        )
        current = await AgentSessionRepository().get_by_id(session, state.session_id)
    assert [event.id for event in events] == [state.input_event.id]
    assert current is not None
    assert current.model_input_head_event_id is None
