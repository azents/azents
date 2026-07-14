"""Event engine adapter assembly tests."""

import asyncio
import datetime
from collections.abc import AsyncGenerator, Awaitable, Callable, Sequence

import pytest
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

import azents.engine.events.engine_adapter as engine_adapter_module
from azents.core.chatgpt_oauth import CHATGPT_OAUTH_BACKEND_BASE_URL
from azents.core.enums import (
    AgentRunPhase,
    AgentRunStatus,
    AgentSessionKind,
    AgentSessionStartReason,
    AgentSessionStatus,
    EventKind,
    LLMProvider,
)
from azents.core.tools import Toolkit, ToolkitState, ToolkitStatus, TurnContext
from azents.engine.context.compaction import (
    SummaryModelCall,
    compute_summary_budget,
    summarize_text_with_model,
)
from azents.engine.events.engine_adapter import (
    AgentEngineAdapter,
    EventEngineAdapterConfig,
    RunExecutionFactory,
    _HookedClientToolExecutor,  # pyright: ignore[reportPrivateUsage]  # Fix Hook wrapper cancellation contract.
)
from azents.engine.events.engine_events import RunComplete
from azents.engine.events.execution import (
    AgentRunExecutionRequest,
    ModelCallPreparer,
    PreparedModelCall,
)
from azents.engine.events.filters import (
    EventPreLowerFilterPipeline,
    PostLowerFilterPipeline,
)
from azents.engine.events.protocols import (
    DurableRunWriteFence,
    NormalizedAdapterOutput,
    OutputSink,
    SummaryEnricher,
    SummaryGenerator,
)
from azents.engine.events.types import (
    AgentRunState,
    ClientToolCallPayload,
    ClientToolResultPayload,
    CompactionSummaryPayload,
    Event,
    NativeArtifact,
    OutputTextPart,
    SystemErrorPayload,
    UserMessagePayload,
)
from azents.engine.hooks.dispatcher import RuntimeHookDispatcher
from azents.engine.hooks.types import (
    CompactionSummaryHookContext,
    CompactionSummaryReplace,
    RuntimeHooks,
    TurnInjectedPrompt,
    TurnStartHookContext,
    TurnStartResult,
)
from azents.engine.run.contracts import RunContext, RunRequest, ToolkitBinding
from azents.engine.run.emit import Emit
from azents.engine.run.errors import CompactionFailedError, ModelCallError
from azents.engine.run.types import (
    OWNERSHIP_LOST_CANCEL_MESSAGE,
    USER_STOP_CANCEL_MESSAGE,
    CheckStop,
)
from azents.rdb.session import SessionManager
from azents.repos.agent_execution import AgentRunOwnershipLostError
from azents.repos.agent_execution.data import AgentRunCreate, EventCreate
from azents.repos.agent_session import AgentSessionRepository
from azents.repos.agent_session.data import AgentSession
from azents.repos.model_file_pin import ModelFilePinRepository
from azents.services.artifact import ArtifactService
from azents.services.exchange_file import ExchangeFileService
from azents.services.model_file import ModelFileService


class _OpenToolAdmissionBarrier:
    """Admission barrier that remains open for adapter tests."""

    closed = False

    async def run_if_open(self, action: Callable[[], Awaitable[None]]) -> bool:
        """Run one admission action."""
        await action()
        return True


class _SessionContext:
    """AsyncSession context manager for tests."""

    def __init__(self, session: "_Session | None" = None) -> None:
        """Store fake session."""
        self.session = session or _Session()

    async def __aenter__(self) -> AsyncSession:
        """Return fake session."""
        return self.session

    async def __aexit__(self, *exc: object) -> None:
        """No-op exit."""


class _Session(AsyncSession):
    """AsyncSession for tests."""

    async def commit(self) -> None:
        """No-op commit."""


class _ArtifactService(ArtifactService):
    """ArtifactService for tests."""

    def __init__(self) -> None:
        """Bypass base dataclass initialization."""


class _ExchangeFileService(ExchangeFileService):
    """ExchangeFileService for tests."""

    def __init__(self) -> None:
        """Bypass base dataclass initialization."""


class _ModelFileService(ModelFileService):
    """ModelFileService for tests."""

    def __init__(self) -> None:
        """Bypass base dataclass initialization."""


class _ModelFilePinRepo(ModelFilePinRepository):
    """ModelFile pin repo for tests."""

    def __init__(self) -> None:
        """Bypass base dataclass initialization."""


class _RunRepo:
    """Run repo for tests."""

    def __init__(self) -> None:
        self.created: AgentRunCreate | None = None
        self.terminal_status: AgentRunStatus | None = None
        self.retry_state_updates: list[object | None] = []
        self.ownership_lost = False
        self.authority_checks: list[tuple[str, str, int]] = []
        now = datetime.datetime.now(datetime.UTC)
        self._state: AgentRunState | None = AgentRunState(
            id="0" * 32,
            session_id="session-1",
            run_index=1,
            phase=AgentRunPhase.IDLE,
            status=AgentRunStatus.RUNNING,
            parent_agent_run_id=None,
            active_tool_calls=[],
            created_at=now,
            started_at=now,
            model_call_started_at=None,
            updated_at=now,
        )

    async def get_by_id(
        self,
        session: AsyncSession,
        run_id: str,
    ) -> AgentRunState | None:
        """Return existing run state when retry reuses a run id."""
        del session, run_id
        return self._state

    async def lock_active_owner(
        self,
        session: AsyncSession,
        *,
        run_id: str,
        session_id: str,
        owner_generation: int,
    ) -> AgentRunState:
        """Return the active test Run for a matching owner."""
        del session
        self.authority_checks.append((run_id, session_id, owner_generation))
        if self.ownership_lost:
            raise AgentRunOwnershipLostError(
                run_id=run_id,
                session_id=session_id,
                expected_owner_generation=owner_generation,
                current_owner_generation=owner_generation + 1,
                active_run_id="replacement-run",
            )
        if self._state is None or self._state.id != run_id:
            raise ValueError("Agent run not found")
        if self._state.session_id != session_id:
            raise ValueError("Agent run session mismatch")
        return self._state

    async def create(
        self,
        session: AsyncSession,
        create: AgentRunCreate,
    ) -> AgentRunState:
        """Record create call."""
        del session
        self.created = create
        self._state = AgentRunState(
            id=create.id or "0" * 32,
            session_id=create.session_id,
            run_index=1,
            phase=create.phase,
            status=create.status,
            parent_agent_run_id=None,
            active_tool_calls=[],
            created_at=datetime.datetime.now(datetime.UTC),
            started_at=datetime.datetime.now(datetime.UTC),
            model_call_started_at=None,
            updated_at=datetime.datetime.now(datetime.UTC),
        )
        return self._state

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
    ) -> object:
        """Record terminal update call."""
        del (
            session,
            run_id,
            ended_at,
            last_completed_event_id,
            terminal_result_event_id,
            terminal_result_message,
        )
        self.terminal_status = status
        return object()

    async def update_retry_state(
        self,
        session: AsyncSession,
        run_id: str,
        retry_state: object | None,
    ) -> object:
        """Record durable retry-state updates."""
        del session, run_id
        self.retry_state_updates.append(retry_state)
        return object()


class _AgentSessionRepo(AgentSessionRepository):
    """AgentSession repo for tests."""

    async def get_by_id(
        self,
        session: AsyncSession,
        agent_session_id: str,
    ) -> AgentSession | None:
        """Handle session lookup call."""
        del session, agent_session_id
        return _agent_session()


class _EventSessionHeadState:
    """Event session head state for tests."""

    def __init__(self, head_event_id: str | None) -> None:
        self.model_input_head_event_id = head_event_id
        self.model_input_head_model_order = 1 if head_event_id is not None else None
        self.model_input_head_model_order = 1 if head_event_id is not None else None


class _EventSessionHeadRepo:
    """Event session head repo for tests."""

    def __init__(self, head_event_id: str | None) -> None:
        self._state = _EventSessionHeadState(head_event_id)

    async def get_by_id(
        self,
        session: AsyncSession,
        session_id: str,
    ) -> _EventSessionHeadState:
        """Return head state."""
        del session, session_id
        return self._state


class _TranscriptRepo:
    """Event transcript repo for tests."""

    def __init__(self, events: list[Event]) -> None:
        self._events = events
        self.head_event_id: str | None = None

    async def list_for_model_input(
        self,
        session: AsyncSession,
        session_id: str,
        *,
        head_event_id: str | None = None,
    ) -> list[Event]:
        """Return model input event."""
        del session, session_id
        self.head_event_id = head_event_id
        return list(self._events)

    async def get_by_external_id(
        self,
        session: AsyncSession,
        session_id: str,
        external_id: str,
    ) -> Event | None:
        """Find event by external ID."""
        del session
        return next(
            (
                event
                for event in self._events
                if event.session_id == session_id and event.external_id == external_id
            ),
            None,
        )

    async def append(
        self,
        session: AsyncSession,
        create: EventCreate,
    ) -> Event:
        """Convert Event append call to test event."""
        del session
        if create.kind != EventKind.SYSTEM_ERROR:
            raise AssertionError("only system_error append is supported in this test")
        event = Event(
            id="3" * 32,
            session_id=create.session_id,
            kind=create.kind,
            payload=SystemErrorPayload.model_validate(create.payload),
            external_id=create.external_id,
            created_at=datetime.datetime.now(datetime.UTC),
        )
        self._events.append(event)
        return event


class _Compactor:
    """Manual compactor for tests."""

    def __init__(self) -> None:
        self.summary: str | None = None
        self.reason: str | None = None

    async def compact(
        self,
        *,
        session_id: str,
        transcript: Sequence[Event],
        compaction_id: str,
        summarize: SummaryGenerator,
        write_fence: DurableRunWriteFence,
        on_started: Callable[[], Awaitable[None]] | None = None,
        summary_context_window_tokens: int | None = None,
        reason: str | None = None,
        summary_enricher: SummaryEnricher | None = None,
    ) -> Event:
        """Call summary generator and return summary event."""
        self.reason = reason
        if on_started is not None:
            await on_started()
        summary = await summarize(
            transcript,
            compute_summary_budget(summary_context_window_tokens),
        )
        if summary_enricher is not None:
            summary = await summary_enricher(
                summary=summary,
                continuity_history="## Recent User Messages\n1. recent request",
                compaction_id=compaction_id,
                reason=reason,
                covered_until_event_id=transcript[-1].id,
            )
        self.summary = summary
        return Event(
            id="2" * 32,
            session_id=session_id,
            kind=EventKind.COMPACTION_SUMMARY,
            payload=CompactionSummaryPayload(
                compaction_id="compact-1",
                content=summary,
                covered_until_event_id=transcript[-1].id,
                reason=reason,
            ),
            created_at=datetime.datetime.now(datetime.UTC),
        )


class _FailingCompactor:
    """Failing compactor for tests."""

    async def compact(
        self,
        *,
        session_id: str,
        transcript: Sequence[Event],
        compaction_id: str,
        summarize: SummaryGenerator,
        write_fence: DurableRunWriteFence,
        on_started: Callable[[], Awaitable[None]] | None = None,
        summary_context_window_tokens: int | None = None,
        reason: str | None = None,
        summary_enricher: SummaryEnricher | None = None,
    ) -> Event | None:
        """Raise compaction failure."""
        del (
            session_id,
            transcript,
            compaction_id,
            summarize,
            write_fence,
            on_started,
            summary_context_window_tokens,
            reason,
            summary_enricher,
        )
        raise CompactionFailedError(
            "Compaction failed: summary model returned no text."
        )


class _Execution:
    """Execution for tests."""

    def __init__(self) -> None:
        self.request: AgentRunExecutionRequest | None = None
        self.model_call_preparer: ModelCallPreparer | None = None
        self.prepared_model_call: PreparedModelCall | None = None

    async def run(
        self,
        session_manager: SessionManager[AsyncSession],
        request: AgentRunExecutionRequest,
        *,
        check_stop: CheckStop | None = None,
        poll_input_events: object = None,
    ) -> AgentRunStatus:
        """Record run request and prepare a model call when wired."""
        del session_manager, check_stop, poll_input_events
        self.request = request
        if self.model_call_preparer is not None:
            self.prepared_model_call = await self.model_call_preparer(
                transcript=[],
                model=request.model,
            )
        return AgentRunStatus.COMPLETED


class _FailingExecution:
    """Execution that raises user-visible runtime error."""

    async def run(
        self,
        session_manager: SessionManager[AsyncSession],
        request: AgentRunExecutionRequest,
        *,
        check_stop: CheckStop | None = None,
        poll_input_events: object = None,
    ) -> AgentRunStatus:
        """Propagate ModelCallError."""
        del session_manager, request, check_stop, poll_input_events
        raise ModelCallError("Model call failed (401): Missing scopes")


class _StreamingExecution:
    """Execution that waits for completion after output sink call."""

    def __init__(self, done: asyncio.Event) -> None:
        self._done = done
        self.cancelled = asyncio.Event()
        self.cancel_args: tuple[object, ...] | None = None
        self.output_sink: OutputSink | None = None

    async def run(
        self,
        session_manager: SessionManager[AsyncSession],
        request: AgentRunExecutionRequest,
        *,
        check_stop: CheckStop | None = None,
        poll_input_events: object = None,
    ) -> AgentRunStatus:
        """Send tool call output to sink first, then wait for completion signal."""
        del session_manager, request, check_stop, poll_input_events
        if self.output_sink is None:
            raise AssertionError("output sink was not injected")
        await self.output_sink(
            NormalizedAdapterOutput(events=[]),
            [_streaming_tool_call_event()],
        )
        try:
            await self._done.wait()
        except asyncio.CancelledError as exc:
            self.cancel_args = exc.args
            self.cancelled.set()
            raise
        return AgentRunStatus.COMPLETED


class _CancellationResistantFencedExecution(_StreamingExecution):
    """Ignore cancellation, then attempt one exact-owner-fenced late write."""

    def __init__(self, run_repo: _RunRepo) -> None:
        super().__init__(asyncio.Event())
        self._run_repo = run_repo
        self.release = asyncio.Event()
        self.cancel_args_history: list[tuple[object, ...]] = []
        self.fence_rejected = asyncio.Event()
        self.durable_mutations = 0

    async def run(
        self,
        session_manager: SessionManager[AsyncSession],
        request: AgentRunExecutionRequest,
        *,
        check_stop: CheckStop | None = None,
        poll_input_events: object = None,
    ) -> AgentRunStatus:
        """Remain alive past quarantine and prove a stale write is rejected."""
        del check_stop, poll_input_events
        if self.output_sink is None:
            raise AssertionError("output sink was not injected")
        await self.output_sink(
            NormalizedAdapterOutput(events=[]),
            [_streaming_tool_call_event()],
        )
        while not self.release.is_set():
            try:
                await self.release.wait()
            except asyncio.CancelledError as exc:
                self.cancel_args_history.append(exc.args)
                self.cancelled.set()
        try:
            async with session_manager() as session:
                await self._run_repo.lock_active_owner(
                    session,
                    run_id=request.run_id,
                    session_id=request.session_id,
                    owner_generation=request.owner_generation,
                )
                self.durable_mutations += 1
        except AgentRunOwnershipLostError:
            self.fence_rejected.set()
            raise
        return AgentRunStatus.COMPLETED


class _CleanupFailingStreamingExecution(_StreamingExecution):
    """Execution that reports a cleanup failure after receiving cancellation."""

    async def run(
        self,
        session_manager: SessionManager[AsyncSession],
        request: AgentRunExecutionRequest,
        *,
        check_stop: CheckStop | None = None,
        poll_input_events: object = None,
    ) -> AgentRunStatus:
        """Convert the injected execution cancellation into a cleanup failure."""
        try:
            return await super().run(
                session_manager,
                request,
                check_stop=check_stop,
                poll_input_events=poll_input_events,
            )
        except asyncio.CancelledError:
            raise RuntimeError("execution cleanup failed") from None


class _RecordingToolExecutor:
    """Tool executor that records request_cancel calls."""

    def __init__(self) -> None:
        self.cancelled: list[ClientToolCallPayload] = []

    async def execute(self, call: ClientToolCallPayload) -> ClientToolResultPayload:
        """Return completed result for tests."""
        return ClientToolResultPayload(
            call_id=call.call_id,
            name=call.name,
            status="completed",
            output=[OutputTextPart(text="ok")],
        )

    def request_cancel(self, call: ClientToolCallPayload) -> None:
        """Record cancellation request."""
        self.cancelled.append(call)


class _PromptHookToolkit(Toolkit[BaseModel]):
    """Toolkit for turn start prompt injection tests."""

    async def update_context(self, context: TurnContext) -> ToolkitState:
        """Return Toolkit prompt."""
        del context
        return ToolkitState(
            status=ToolkitStatus.ENABLED,
            tools=[],
        )

    async def get_static_prompt(self, context: TurnContext) -> str:
        """Return static prompt."""
        del context
        return "tool prompt"

    def hooks(self) -> RuntimeHooks:
        """Return turn start hook."""
        return {"on_turn_start": self._on_turn_start}

    async def _on_turn_start(
        self,
        context: TurnStartHookContext,
    ) -> TurnStartResult:
        """Return visible/hidden injected prompt."""
        del context
        return TurnStartResult(
            injected_prompts=[
                TurnInjectedPrompt(
                    persistence="visible_user_input",
                    text="visible prompt",
                ),
                TurnInjectedPrompt(
                    persistence="hidden_internal_input",
                    text="hidden prompt",
                ),
            ]
        )


class _CompactionSummaryHookToolkit(Toolkit[BaseModel]):
    """Toolkit for compaction summary hook tests."""

    def __init__(self) -> None:
        self.context: CompactionSummaryHookContext | None = None

    async def update_context(self, context: TurnContext) -> ToolkitState:
        """Return active empty toolkit state."""
        del context
        return ToolkitState(status=ToolkitStatus.ENABLED, tools=[])

    def hooks(self) -> RuntimeHooks:
        """Return compaction summary hook."""
        return {"on_compaction_summary": self._on_compaction_summary}

    async def _on_compaction_summary(
        self,
        context: CompactionSummaryHookContext,
    ) -> CompactionSummaryReplace:
        """Append hook enrichment before continuity is reattached."""
        self.context = context
        return CompactionSummaryReplace(
            summary=context.summary + "\n\n## Toolkit Enrichment\n- extra"
        )


def test_hooked_tool_executor_forwards_request_cancel() -> None:
    """Hook wrapper forwards cancellation request to inner executor."""
    inner = _RecordingToolExecutor()
    wrapper = _HookedClientToolExecutor(
        inner=inner,
        dispatcher=RuntimeHookDispatcher(),
        providers=[],
        workspace_id="workspace-1",
        agent_id="agent-1",
        session_id="session-1",
        run_id="run-1",
        owner_generation=1,
    )
    call = ClientToolCallPayload(
        call_id="call-1",
        name="tool",
        arguments="{}",
        native_artifact=_artifact({"type": "function_call"}),
    )

    wrapper.request_cancel(call)

    assert inner.cancelled == [call]


async def test_event_engine_adapter_runs_execution() -> None:
    """Adapter assembles AgentRunExecution and returns terminal emit."""
    run_repo = _RunRepo()
    execution = _Execution()
    adapter = _agent_engine_adapter(
        session_manager=_session_context,
        artifact_service=_ArtifactService(),
        exchange_file_service=_ExchangeFileService(),
        model_file_service=_ModelFileService(),
        run_repo=run_repo,
        agent_session_repo=_AgentSessionRepo(),
        execution_factory=lambda **kwargs: (
            setattr(
                execution,
                "model_call_preparer",
                kwargs["model_call_preparer"],
            )
            or execution
        ),
    )

    emits = [
        emit
        async for emit in adapter.run(
            RunRequest(
                session_id="session-1",
                user_messages=[],
                agent_prompt="agent prompt",
                toolkits=[],
                model="gpt-5.1",
                credential_kwargs={"api_key": "test"},
                workspace_id="workspace-1",
                agent_id="agent-1",
                auto_compaction_threshold_tokens=None,
                inference_state=None,
            ),
            RunContext(
                owner_generation=1,
                tool_admission_barrier=_OpenToolAdmissionBarrier(),
                user_id="user-1",
                run_id="0" * 32,
                publish_event=_noop_publish,
            ),
        )
    ]

    assert run_repo.created is None
    assert run_repo.retry_state_updates == []
    assert execution.request is not None
    assert execution.prepared_model_call is not None
    prepared_request = execution.prepared_model_call.native_request
    assert prepared_request.kwargs["instructions"] == "## Agent prompt\n\nagent prompt"
    assert isinstance(prepared_request.kwargs.get("prompt_cache_key"), str)
    assert isinstance(_events(emits)[0], RunComplete)


async def test_adapter_yields_model_output_before_run_completion() -> None:
    """Adapter yields output sink emit even before execution completes."""
    done = asyncio.Event()
    execution = _StreamingExecution(done)
    adapter = _agent_engine_adapter(
        session_manager=_session_context,
        artifact_service=_ArtifactService(),
        exchange_file_service=_ExchangeFileService(),
        model_file_service=_ModelFileService(),
        run_repo=_RunRepo(),
        agent_session_repo=_AgentSessionRepo(),
        execution_factory=_StreamingExecutionFactory(execution),
    )

    stream = adapter.run(
        RunRequest(
            session_id="session-1",
            user_messages=[],
            agent_prompt=None,
            toolkits=[],
            model="gpt-5.1",
            credential_kwargs={"api_key": "test"},
            workspace_id="workspace-1",
            agent_id="agent-1",
            auto_compaction_threshold_tokens=None,
            inference_state=None,
        ),
        RunContext(
            owner_generation=1,
            tool_admission_barrier=_OpenToolAdmissionBarrier(),
            user_id="user-1",
            run_id="0" * 32,
            publish_event=_noop_publish,
        ),
    )

    first = await asyncio.wait_for(anext(stream), timeout=1)
    assert isinstance(first.event, Event)
    assert first.event.kind == EventKind.CLIENT_TOOL_CALL
    done.set()
    rest = [emit async for emit in stream]
    assert isinstance(_events(rest)[-1], RunComplete)


@pytest.mark.parametrize(
    "cancel_message",
    [USER_STOP_CANCEL_MESSAGE, OWNERSHIP_LOST_CANCEL_MESSAGE],
)
async def test_adapter_forwards_cancellation_reason_to_execution(
    cancel_message: str,
) -> None:
    """Propagate semantic adapter cancellation to the execution task."""
    done = asyncio.Event()
    execution = _StreamingExecution(done)
    adapter = _agent_engine_adapter(
        session_manager=_session_context,
        artifact_service=_ArtifactService(),
        exchange_file_service=_ExchangeFileService(),
        model_file_service=_ModelFileService(),
        run_repo=_RunRepo(),
        agent_session_repo=_AgentSessionRepo(),
        execution_factory=_StreamingExecutionFactory(execution),
    )
    emitted = asyncio.Event()

    async def consume() -> None:
        """Receive external cancellation while consuming adapter stream."""
        async for _emit in adapter.run(
            RunRequest(
                session_id="session-1",
                user_messages=[],
                agent_prompt="agent prompt",
                toolkits=[],
                model="gpt-5.1",
                credential_kwargs={"api_key": "test"},
                workspace_id="workspace-1",
                agent_id="agent-1",
                auto_compaction_threshold_tokens=None,
                inference_state=None,
            ),
            RunContext(
                owner_generation=1,
                tool_admission_barrier=_OpenToolAdmissionBarrier(),
                user_id="user-1",
                run_id="0" * 32,
                publish_event=_noop_publish,
            ),
        ):
            emitted.set()

    task = asyncio.create_task(consume())
    await asyncio.wait_for(emitted.wait(), timeout=1)
    task.cancel(cancel_message)

    with pytest.raises(asyncio.CancelledError):
        await task

    assert execution.cancel_args == (cancel_message,)


async def test_adapter_preserves_ownership_cancel_when_execution_cleanup_fails(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """A cleanup failure cannot replace the stale-owner cancellation marker."""
    done = asyncio.Event()
    execution = _CleanupFailingStreamingExecution(done)
    adapter = _agent_engine_adapter(
        session_manager=_session_context,
        artifact_service=_ArtifactService(),
        exchange_file_service=_ExchangeFileService(),
        model_file_service=_ModelFileService(),
        run_repo=_RunRepo(),
        agent_session_repo=_AgentSessionRepo(),
        execution_factory=_StreamingExecutionFactory(execution),
    )
    emitted = asyncio.Event()

    async def consume() -> None:
        """Receive ownership-loss cancellation while consuming adapter output."""
        async for _emit in adapter.run(
            RunRequest(
                session_id="session-1",
                user_messages=[],
                agent_prompt="agent prompt",
                toolkits=[],
                model="gpt-5.1",
                credential_kwargs={"api_key": "test"},
                workspace_id="workspace-1",
                agent_id="agent-1",
                auto_compaction_threshold_tokens=None,
                inference_state=None,
            ),
            RunContext(
                owner_generation=1,
                tool_admission_barrier=_OpenToolAdmissionBarrier(),
                user_id="user-1",
                run_id="0" * 32,
                publish_event=_noop_publish,
            ),
        ):
            emitted.set()

    task = asyncio.create_task(consume())
    await asyncio.wait_for(emitted.wait(), timeout=1)
    task.cancel(OWNERSHIP_LOST_CANCEL_MESSAGE)

    with pytest.raises(asyncio.CancelledError) as cancelled:
        await task

    assert cancelled.value.args == (OWNERSHIP_LOST_CANCEL_MESSAGE,)
    assert execution.cancel_args == (OWNERSHIP_LOST_CANCEL_MESSAGE,)
    assert "Execution task failed during adapter cancellation cleanup" in caplog.text


async def test_adapter_quarantines_cancel_resistant_execution_and_fences_late_write(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Consumer cancellation stays prompt while stale late writes remain fenced."""
    monkeypatch.setattr(
        engine_adapter_module,
        "_RUN_TASK_CANCEL_DRAIN_TIMEOUT_SECONDS",
        0.01,
    )
    run_repo = _RunRepo()
    execution = _CancellationResistantFencedExecution(run_repo)
    adapter = _agent_engine_adapter(
        session_manager=_session_context,
        artifact_service=_ArtifactService(),
        exchange_file_service=_ExchangeFileService(),
        model_file_service=_ModelFileService(),
        run_repo=run_repo,
        agent_session_repo=_AgentSessionRepo(),
        execution_factory=_StreamingExecutionFactory(execution),
    )
    emitted = asyncio.Event()
    retained_task: asyncio.Task[AgentRunStatus] | None = None

    async def consume() -> None:
        """Receive ownership-loss cancellation while the child refuses to exit."""
        async for _emit in adapter.run(
            RunRequest(
                session_id="session-1",
                user_messages=[],
                agent_prompt="agent prompt",
                toolkits=[],
                model="gpt-5.1",
                credential_kwargs={"api_key": "test"},
                workspace_id="workspace-1",
                agent_id="agent-1",
                auto_compaction_threshold_tokens=None,
                inference_state=None,
            ),
            RunContext(
                owner_generation=1,
                tool_admission_barrier=_OpenToolAdmissionBarrier(),
                user_id="user-1",
                run_id="0" * 32,
                publish_event=_noop_publish,
            ),
        ):
            emitted.set()

    consumer_task = asyncio.create_task(consume())
    await asyncio.wait_for(emitted.wait(), timeout=1)
    consumer_task.cancel(OWNERSHIP_LOST_CANCEL_MESSAGE)

    try:
        with pytest.raises(asyncio.CancelledError) as cancelled:
            await asyncio.wait_for(consumer_task, timeout=1)

        assert cancelled.value.args == (OWNERSHIP_LOST_CANCEL_MESSAGE,)
        assert execution.cancel_args_history
        assert all(
            args == (OWNERSHIP_LOST_CANCEL_MESSAGE,)
            for args in execution.cancel_args_history
        )
        retained_task = next(
            task
            for task in engine_adapter_module._RETAINED_RUN_TASKS  # pyright: ignore[reportPrivateUsage]
            if task.get_name() == f"agent-run-execution:{'0' * 32}" and not task.done()
        )
        assert "Execution task ignored adapter cancellation deadline" in caplog.text
    finally:
        run_repo.ownership_lost = True
        execution.release.set()

    assert retained_task is not None
    await asyncio.wait_for(execution.fence_rejected.wait(), timeout=1)

    async def wait_for_retained_task_release() -> None:
        while retained_task in engine_adapter_module._RETAINED_RUN_TASKS:  # pyright: ignore[reportPrivateUsage]
            await asyncio.sleep(0)

    await asyncio.wait_for(wait_for_retained_task_release(), timeout=1)
    assert execution.durable_mutations == 0
    assert run_repo.authority_checks[-1] == ("0" * 32, "session-1", 1)
    assert "Quarantined execution task failed after adapter cancellation" in caplog.text


async def test_adapter_drains_run_task_on_stream_close() -> None:
    """When consumer closes stream, wait until execution task cancellation finishes."""
    done = asyncio.Event()
    execution = _StreamingExecution(done)
    adapter = _agent_engine_adapter(
        session_manager=_session_context,
        artifact_service=_ArtifactService(),
        exchange_file_service=_ExchangeFileService(),
        model_file_service=_ModelFileService(),
        run_repo=_RunRepo(),
        agent_session_repo=_AgentSessionRepo(),
        execution_factory=_StreamingExecutionFactory(execution),
    )

    stream = adapter.run(
        RunRequest(
            session_id="session-1",
            user_messages=[],
            agent_prompt=None,
            toolkits=[],
            model="gpt-5.1",
            credential_kwargs={"api_key": "test"},
            workspace_id="workspace-1",
            agent_id="agent-1",
            auto_compaction_threshold_tokens=None,
            inference_state=None,
        ),
        RunContext(
            owner_generation=1,
            tool_admission_barrier=_OpenToolAdmissionBarrier(),
            user_id="user-1",
            run_id="0" * 32,
            publish_event=_noop_publish,
        ),
    )
    assert isinstance(stream, AsyncGenerator)

    _ = await asyncio.wait_for(anext(stream), timeout=1)
    await stream.aclose()

    assert execution.cancelled.is_set()


async def test_event_engine_adapter_includes_turn_start_injected_prompts() -> None:
    """Turn start hook prompt is included in system prompt."""
    execution = _Execution()
    adapter = _agent_engine_adapter(
        session_manager=_session_context,
        artifact_service=_ArtifactService(),
        exchange_file_service=_ExchangeFileService(),
        model_file_service=_ModelFileService(),
        run_repo=_RunRepo(),
        agent_session_repo=_AgentSessionRepo(),
        execution_factory=lambda **kwargs: (
            setattr(
                execution,
                "model_call_preparer",
                kwargs["model_call_preparer"],
            )
            or execution
        ),
    )

    _ = [
        emit
        async for emit in adapter.run(
            RunRequest(
                session_id="session-1",
                user_messages=[],
                agent_prompt="agent prompt",
                toolkits=[ToolkitBinding(_PromptHookToolkit(), "hooks", True)],
                model="gpt-5.1",
                credential_kwargs={"api_key": "test"},
                workspace_id="workspace-1",
                agent_id="agent-1",
                auto_compaction_threshold_tokens=None,
                inference_state=None,
            ),
            RunContext(
                owner_generation=1,
                tool_admission_barrier=_OpenToolAdmissionBarrier(),
                user_id="user-1",
                run_id="0" * 32,
                publish_event=_noop_publish,
            ),
        )
    ]

    assert execution.prepared_model_call is not None
    assert execution.prepared_model_call.native_request.kwargs["instructions"] == (
        "## Agent prompt\n\nagent prompt\n\n"
        "## Static toolkit prompt: hooks\n\ntool prompt\n\n"
        "## Turn injected prompt from hooks\n\nvisible prompt\n\n"
        "## Turn injected prompt from hooks\n\nhidden prompt"
    )


async def test_adapter_propagates_user_visible_model_call_error() -> None:
    """User-visible model errors bubble to the worker retry boundary."""
    adapter = _agent_engine_adapter(
        session_manager=_session_context,
        artifact_service=_ArtifactService(),
        exchange_file_service=_ExchangeFileService(),
        model_file_service=_ModelFileService(),
        run_repo=_RunRepo(),
        agent_session_repo=_AgentSessionRepo(),
        transcript_repo=_TranscriptRepo([]),
        execution_factory=lambda **kwargs: _FailingExecution(),
    )

    emits: list[Emit] = []
    with pytest.raises(ModelCallError, match="Missing scopes"):
        async for emit in adapter.run(
            RunRequest(
                session_id="session-1",
                user_messages=[],
                agent_prompt=None,
                toolkits=[],
                model="gpt-5.1",
                credential_kwargs={"api_key": "test"},
                workspace_id="workspace-1",
                agent_id="agent-1",
                auto_compaction_threshold_tokens=None,
                inference_state=None,
            ),
            RunContext(
                owner_generation=1,
                tool_admission_barrier=_OpenToolAdmissionBarrier(),
                user_id="user-1",
                run_id="0" * 32,
                publish_event=_noop_publish,
            ),
        ):
            emits.append(emit)

    assert not any(
        isinstance(event, Event) and event.kind == EventKind.SYSTEM_ERROR
        for event in _events(emits)
    )


async def test_model_kwargs_routes_chatgpt_oauth_to_backend_api() -> None:
    """ChatGPT OAuth calls chatgpt backend-api/codex endpoint."""
    execution = _Execution()

    def factory(**kwargs: object) -> _Execution:
        return (
            setattr(
                execution,
                "model_call_preparer",
                kwargs["model_call_preparer"],
            )
            or execution
        )

    adapter = _agent_engine_adapter(
        session_manager=_session_context,
        artifact_service=_ArtifactService(),
        exchange_file_service=_ExchangeFileService(),
        model_file_service=_ModelFileService(),
        run_repo=_RunRepo(),
        agent_session_repo=_AgentSessionRepo(),
        execution_factory=factory,
    )

    _ = [
        emit
        async for emit in adapter.run(
            RunRequest(
                session_id="session-1",
                user_messages=[],
                agent_prompt=None,
                toolkits=[],
                provider=LLMProvider.CHATGPT_OAUTH,
                model="gpt-5.1-codex",
                credential_kwargs={
                    "api_key": "access-token",
                    "base_url": CHATGPT_OAUTH_BACKEND_BASE_URL,
                },
                workspace_id="workspace-1",
                agent_id="agent-1",
                auto_compaction_threshold_tokens=None,
                inference_state=None,
            ),
            RunContext(
                owner_generation=1,
                tool_admission_barrier=_OpenToolAdmissionBarrier(),
                user_id="user-1",
                run_id="0" * 32,
                publish_event=_noop_publish,
            ),
        )
    ]
    assert execution.prepared_model_call is not None
    result = execution.prepared_model_call.native_request.kwargs

    assert result["api_key"] == "access-token"
    assert result["custom_llm_provider"] == "openai"
    assert result["base_url"] == CHATGPT_OAUTH_BACKEND_BASE_URL
    assert result["api_base"] == CHATGPT_OAUTH_BACKEND_BASE_URL
    assert result["store"] is False
    assert result["instructions"] == "You are a helpful assistant."


async def test_adapter_wires_event_filters_and_session_head_repo() -> None:
    """Production assembly injects ADR filter pipeline and session head lookup."""
    captured: dict[str, object] = {}

    def factory(**kwargs: object) -> _Execution:
        captured.update(kwargs)
        return _Execution()

    session_head_repo = _EventSessionHeadRepo(None)
    adapter = _agent_engine_adapter(
        session_manager=_session_context,
        artifact_service=_ArtifactService(),
        exchange_file_service=_ExchangeFileService(),
        model_file_service=_ModelFileService(),
        run_repo=_RunRepo(),
        agent_session_repo=_AgentSessionRepo(),
        session_head_repo=session_head_repo,
        execution_factory=factory,
    )

    _ = [
        emit
        async for emit in adapter.run(
            RunRequest(
                session_id="session-1",
                user_messages=[],
                agent_prompt=None,
                toolkits=[],
                model="gpt-5.1",
                credential_kwargs={"api_key": "test"},
                workspace_id="workspace-1",
                agent_id="agent-1",
                auto_compaction_threshold_tokens=None,
                inference_state=None,
                max_output_tokens=123,
                max_input_tokens=64_000,
                compaction_max_input_tokens=32_000,
            ),
            RunContext(
                owner_generation=1,
                tool_admission_barrier=_OpenToolAdmissionBarrier(),
                user_id="user-1",
                run_id="0" * 32,
                publish_event=_noop_publish,
            ),
        )
    ]

    pre_lower_filter = captured["pre_lower_filter"]
    post_lower_filter = captured["post_lower_filter"]
    assert isinstance(pre_lower_filter, EventPreLowerFilterPipeline)
    assert isinstance(post_lower_filter, PostLowerFilterPipeline)
    assert [item.__class__.__name__ for item in pre_lower_filter.filters] == [
        "EventAttachmentAvailabilityFilter",
        "EventFilePartPlaceholderFilter",
        "EventAutoCompactionFilter",
    ]
    assert [item.__class__.__name__ for item in post_lower_filter.filters] == [
        "NativeRequestSizeGuard",
    ]
    assert captured["session_repo"] is session_head_repo


async def test_manual_compact_runs_append_only_event_compactor() -> None:
    """Manual compact runs event compactor from transcript head."""
    transcript_event = Event(
        id="1" * 32,
        session_id="session-1",
        kind=EventKind.USER_MESSAGE,
        payload=UserMessagePayload(content="old request"),
        created_at=datetime.datetime.now(datetime.UTC),
    )
    transcript_repo = _TranscriptRepo([transcript_event])
    compactor = _Compactor()
    captured_prompts: dict[str, str] = {}

    async def summarize(
        *,
        provider: LLMProvider,
        model: str,
        credential_kwargs: dict[str, object],
        system_prompt: str,
        user_prompt: str,
        conversation_text: str,
        max_output_tokens: int,
        session_id: str | None = None,
    ) -> str:
        """Replace summary model call."""
        del provider, model, credential_kwargs, max_output_tokens, session_id
        captured_prompts["system_prompt"] = system_prompt
        captured_prompts["user_prompt"] = user_prompt
        return f"summary::{conversation_text}"

    adapter = _agent_engine_adapter(
        session_manager=_session_context,
        artifact_service=_ArtifactService(),
        exchange_file_service=_ExchangeFileService(),
        model_file_service=_ModelFileService(),
        run_repo=_RunRepo(),
        agent_session_repo=_AgentSessionRepo(),
        session_head_repo=_EventSessionHeadRepo("1" * 32),
        transcript_repo=transcript_repo,
        compactor=compactor,
        summary_model_call=summarize,
    )

    emits = [
        emit
        async for emit in adapter.compact(
            RunRequest(
                session_id="session-1",
                user_messages=[],
                agent_prompt=None,
                toolkits=[],
                model="gpt-5.1",
                credential_kwargs={"api_key": "test"},
                workspace_id="workspace-1",
                agent_id="agent-1",
                auto_compaction_threshold_tokens=None,
                inference_state=None,
            ),
            _run_context(),
        )
    ]

    assert [emit.event.__class__.__name__ for emit in emits] == [
        "CompactionStarted",
        "CompactionComplete",
    ]
    assert transcript_repo.head_event_id == "1" * 32
    assert compactor.reason == "manual_command"
    assert compactor.summary == "summary::[User]: old request"
    assert "durable handoff checkpoint" in captured_prompts["system_prompt"]
    assert "Do not answer the user" in captured_prompts["system_prompt"]
    assert "## Relevant Files and Symbols" in captured_prompts["user_prompt"]
    assert "existing checkpoints" in captured_prompts["user_prompt"]


async def test_manual_compact_runs_compaction_summary_hook() -> None:
    """Manual compaction passes summary and continuity history to hook pipeline."""
    transcript_event = Event(
        id="1" * 32,
        session_id="session-1",
        kind=EventKind.USER_MESSAGE,
        payload=UserMessagePayload(content="old request"),
        created_at=datetime.datetime.now(datetime.UTC),
    )
    transcript_repo = _TranscriptRepo([transcript_event])
    compactor = _Compactor()
    toolkit = _CompactionSummaryHookToolkit()

    async def summarize(
        *,
        provider: LLMProvider,
        model: str,
        credential_kwargs: dict[str, object],
        system_prompt: str,
        user_prompt: str,
        conversation_text: str,
        max_output_tokens: int,
        session_id: str | None = None,
    ) -> str:
        """Return compact summary."""
        del provider, model, credential_kwargs, system_prompt, user_prompt
        del conversation_text, max_output_tokens, session_id
        return "summary"

    adapter = _agent_engine_adapter(
        session_manager=_session_context,
        artifact_service=_ArtifactService(),
        exchange_file_service=_ExchangeFileService(),
        model_file_service=_ModelFileService(),
        run_repo=_RunRepo(),
        agent_session_repo=_AgentSessionRepo(),
        session_head_repo=_EventSessionHeadRepo("1" * 32),
        transcript_repo=transcript_repo,
        compactor=compactor,
        summary_model_call=summarize,
    )

    _ = [
        emit
        async for emit in adapter.compact(
            RunRequest(
                session_id="session-1",
                user_messages=[],
                agent_prompt=None,
                toolkits=[ToolkitBinding(toolkit, "hookkit", True)],
                model="gpt-5.1",
                credential_kwargs={"api_key": "test"},
                workspace_id="workspace-1",
                agent_id="agent-1",
                auto_compaction_threshold_tokens=None,
                inference_state=None,
            ),
            _run_context(),
        )
    ]

    assert toolkit.context is not None
    assert toolkit.context.summary == "summary"
    assert (
        toolkit.context.continuity_history
        == "## Recent User Messages\n1. recent request"
    )
    assert toolkit.context.run_id == "0" * 32
    assert compactor.summary == "summary\n\n## Toolkit Enrichment\n- extra"


async def test_manual_compact_trims_summary_input_to_checkpoint_and_tail() -> None:
    """Manual compact limits summary input to latest checkpoint and recent tail."""
    now = datetime.datetime.now(datetime.UTC)
    transcript_events = [
        Event(
            id=f"{index:032d}",
            session_id="session-1",
            kind=kind,
            payload=payload,
            created_at=now,
        )
        for index, (kind, payload) in enumerate(
            [
                (
                    EventKind.USER_MESSAGE,
                    UserMessagePayload(content="old raw input " + ("A" * 30_000)),
                ),
                (
                    EventKind.COMPACTION_SUMMARY,
                    CompactionSummaryPayload(
                        compaction_id="checkpoint-1",
                        content="obsolete checkpoint",
                    ),
                ),
                (
                    EventKind.USER_MESSAGE,
                    UserMessagePayload(content="middle raw input " + ("B" * 30_000)),
                ),
                (
                    EventKind.COMPACTION_SUMMARY,
                    CompactionSummaryPayload(
                        compaction_id="checkpoint-2",
                        content="latest checkpoint state",
                    ),
                ),
                (
                    EventKind.USER_MESSAGE,
                    UserMessagePayload(content="recent tail one"),
                ),
                (
                    EventKind.USER_MESSAGE,
                    UserMessagePayload(content="recent tail two"),
                ),
            ],
            start=1,
        )
    ]
    transcript_repo = _TranscriptRepo(transcript_events)
    compactor = _Compactor()
    captured: dict[str, str] = {}

    async def summarize(
        *,
        provider: LLMProvider,
        model: str,
        credential_kwargs: dict[str, object],
        system_prompt: str,
        user_prompt: str,
        conversation_text: str,
        max_output_tokens: int,
        session_id: str | None = None,
    ) -> str:
        """Capture summary input."""
        del provider, model, credential_kwargs, system_prompt, user_prompt
        del max_output_tokens, session_id
        captured["conversation_text"] = conversation_text
        return "summary"

    adapter = _agent_engine_adapter(
        session_manager=_session_context,
        artifact_service=_ArtifactService(),
        exchange_file_service=_ExchangeFileService(),
        model_file_service=_ModelFileService(),
        run_repo=_RunRepo(),
        agent_session_repo=_AgentSessionRepo(),
        session_head_repo=_EventSessionHeadRepo("6" * 32),
        transcript_repo=transcript_repo,
        compactor=compactor,
        summary_model_call=summarize,
    )

    emits = [
        emit
        async for emit in adapter.compact(
            RunRequest(
                session_id="session-1",
                user_messages=[],
                agent_prompt=None,
                toolkits=[],
                model="gpt-5.1",
                credential_kwargs={"api_key": "test"},
                workspace_id="workspace-1",
                agent_id="agent-1",
                auto_compaction_threshold_tokens=None,
                inference_state=None,
                max_input_tokens=12_000,
                compaction_max_input_tokens=12_000,
            ),
            _run_context(),
        )
    ]

    assert [emit.event.__class__.__name__ for emit in emits] == [
        "CompactionStarted",
        "CompactionComplete",
    ]
    rendered = captured["conversation_text"]
    assert "latest checkpoint state" in rendered
    assert "recent tail one" in rendered
    assert "recent tail two" in rendered
    assert "older raw events were omitted" in rendered
    assert "old raw input" not in rendered
    assert "obsolete checkpoint" not in rendered


async def test_manual_compact_propagates_compaction_failure() -> None:
    """Manual compact failure propagates instead of hidden as complete."""
    transcript_event = Event(
        id="1" * 32,
        session_id="session-1",
        kind=EventKind.USER_MESSAGE,
        payload=UserMessagePayload(content="old request"),
        created_at=datetime.datetime.now(datetime.UTC),
    )
    transcript_repo = _TranscriptRepo([transcript_event])
    adapter = _agent_engine_adapter(
        session_manager=_session_context,
        artifact_service=_ArtifactService(),
        exchange_file_service=_ExchangeFileService(),
        model_file_service=_ModelFileService(),
        run_repo=_RunRepo(),
        agent_session_repo=_AgentSessionRepo(),
        session_head_repo=_EventSessionHeadRepo("1" * 32),
        transcript_repo=transcript_repo,
        compactor=_FailingCompactor(),
    )

    iterator = adapter.compact(
        RunRequest(
            session_id="session-1",
            user_messages=[],
            agent_prompt=None,
            toolkits=[],
            model="gpt-5.1",
            credential_kwargs={"api_key": "test"},
            workspace_id="workspace-1",
            agent_id="agent-1",
            auto_compaction_threshold_tokens=None,
            inference_state=None,
        ),
        _run_context(),
    )

    first = await anext(iterator)
    assert first.event.__class__.__name__ == "CompactionStarted"
    with pytest.raises(CompactionFailedError, match="summary model returned no text"):
        await anext(iterator)


class _StreamingExecutionFactory:
    """Factory that injects output sink into streaming execution."""

    def __init__(self, execution: _StreamingExecution) -> None:
        """Store execution."""
        self._execution = execution

    def __call__(
        self,
        *,
        output_sink: OutputSink,
        **kwargs: object,
    ) -> _StreamingExecution:
        """Implement execution factory protocol."""
        del kwargs
        self._execution.output_sink = output_sink
        return self._execution


def _streaming_tool_call_event() -> Event:
    """Return the durable output used to open adapter streaming tests."""
    return Event(
        id="1" * 32,
        session_id="session-1",
        kind=EventKind.CLIENT_TOOL_CALL,
        payload=ClientToolCallPayload(
            call_id="call-1",
            name="tool",
            arguments="{}",
            native_artifact=_artifact({"type": "function_call", "call_id": "call-1"}),
        ),
        created_at=datetime.datetime.now(datetime.UTC),
    )


def _artifact(item: dict[str, object]) -> NativeArtifact:
    """Create native artifact for tests."""
    return NativeArtifact(
        compat_key="litellm:responses:openai:gpt-5.1:1",
        adapter="litellm",
        native_format="responses",
        provider="openai",
        model="gpt-5.1",
        schema_version="1",
        item=item,
    )


def _agent_session() -> AgentSession:
    """Return legacy agent session for tests."""
    now = datetime.datetime.now(datetime.UTC)
    return AgentSession(
        owner_generation=0,
        inference_state=None,
        id="session-1",
        workspace_id="workspace-1",
        agent_id="agent-1",
        handle="test-session-handle",
        session_kind=AgentSessionKind.ROOT,
        status=AgentSessionStatus.ACTIVE,
        start_reason=AgentSessionStartReason.INITIAL,
        title=None,
        title_source=None,
        title_generated_at=None,
        title_generation_event_id=None,
        last_user_input_at=now,
        created_at=now,
        updated_at=now,
        started_at=now,
    )


async def _noop_publish(_event: object) -> None:
    """No-op publish."""


def _run_context() -> RunContext:
    """Return manual compaction run context for tests."""
    return RunContext(
        owner_generation=1,
        tool_admission_barrier=_OpenToolAdmissionBarrier(),
        user_id="user-1",
        run_id="0" * 32,
        publish_event=_noop_publish,
    )


def _session_context() -> _SessionContext:
    """Return fake session context."""
    return _SessionContext()


def _agent_engine_adapter(
    *,
    session_manager: Callable[[], _SessionContext] = _session_context,
    artifact_service: ArtifactService | None = None,
    exchange_file_service: ExchangeFileService | None = None,
    model_file_service: ModelFileService | None = None,
    config: EventEngineAdapterConfig | None = None,
    execution_factory: RunExecutionFactory | None = None,
    run_repo: _RunRepo | None = None,
    agent_session_repo: _AgentSessionRepo | None = None,
    session_head_repo: _EventSessionHeadRepo | None = None,
    transcript_repo: _TranscriptRepo | None = None,
    compactor: _Compactor | _FailingCompactor | None = None,
    summary_model_call: SummaryModelCall | None = None,
) -> AgentEngineAdapter:
    """Create AgentEngineAdapter for tests."""
    return AgentEngineAdapter(
        session_manager=session_manager,
        artifact_service=artifact_service or _ArtifactService(),
        exchange_file_service=exchange_file_service or _ExchangeFileService(),
        model_file_service=model_file_service or _ModelFileService(),
        config=config or EventEngineAdapterConfig(),
        execution_factory=execution_factory or (lambda **kwargs: _Execution()),
        run_repo=run_repo or _RunRepo(),
        agent_session_repo=agent_session_repo or _AgentSessionRepo(),
        session_head_repo=session_head_repo or _EventSessionHeadRepo(None),
        transcript_repo=transcript_repo or _TranscriptRepo([]),
        model_file_pin_repo=_ModelFilePinRepo(),
        compactor=compactor or _Compactor(),
        summary_model_call=summary_model_call or summarize_text_with_model,
    )


def _events(emits: list[Emit]) -> list[object]:
    """Return emit event list."""
    return [emit.event for emit in emits]
