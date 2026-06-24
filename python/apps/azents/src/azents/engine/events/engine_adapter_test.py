"""Event engine adapter assembly tests."""

import asyncio
import datetime
from collections.abc import AsyncGenerator, Callable, Sequence

import pytest
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from azents.core.chatgpt_oauth import CHATGPT_OAUTH_BACKEND_BASE_URL
from azents.core.enums import (
    AgentRunStatus,
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
from azents.engine.events.execution import AgentRunExecutionRequest
from azents.engine.events.filters import (
    EventPreLowerFilterPipeline,
    PostLowerFilterPipeline,
)
from azents.engine.events.litellm_responses import LiteLLMResponsesLowerer
from azents.engine.events.protocols import (
    NormalizedAdapterOutput,
    OutputSink,
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
    RuntimeHooks,
    TurnInjectedPrompt,
    TurnStartHookContext,
    TurnStartResult,
)
from azents.engine.run.contracts import RunContext, RunRequest, ToolkitBinding
from azents.engine.run.emit import Emit
from azents.engine.run.errors import CompactionFailedError, ModelCallError
from azents.engine.run.types import USER_STOP_CANCEL_MESSAGE, CheckStop
from azents.repos.agent_execution.data import AgentRunCreate, EventCreate
from azents.repos.agent_session.data import AgentSession
from azents.repos.artifact.data import Artifact
from azents.repos.exchange_file.data import ExchangeFile
from azents.repos.model_file.data import ModelFile
from azents.services.artifact import ArtifactService
from azents.services.exchange_file import ExchangeFileService
from azents.services.model_file import ModelFileService


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

    async def expire_for_run_boundary(
        self,
        *,
        session_id: str,
        current_run_index: int,
    ) -> list[Artifact]:
        """Treat as having no expiry targets."""
        del session_id, current_run_index
        return []


class _ExchangeFileService(ExchangeFileService):
    """ExchangeFileService for tests."""

    def __init__(self) -> None:
        """Bypass base dataclass initialization."""

    async def expire_due_files(self) -> list[ExchangeFile]:
        """Treat as having no expiry targets."""
        return []


class _ModelFileService(ModelFileService):
    """ModelFileService for tests."""

    def __init__(self) -> None:
        """Bypass base dataclass initialization."""

    async def expire_for_run_boundary(
        self,
        *,
        session_id: str,
        current_run_index: int,
    ) -> list[ModelFile]:
        """Treat as having no expiry targets."""
        del session_id, current_run_index
        return []


class _RunRepo:
    """Run repo for tests."""

    def __init__(self) -> None:
        self.created: AgentRunCreate | None = None
        self.terminal_status: AgentRunStatus | None = None

    async def create(
        self,
        session: AsyncSession,
        create: AgentRunCreate,
    ) -> AgentRunState:
        """Record create call."""
        del session
        self.created = create
        return AgentRunState(
            id=create.id or "0" * 32,
            session_id=create.session_id,
            run_index=1,
            phase=create.phase,
            status=create.status,
            active_tool_calls=[],
            started_at=datetime.datetime.now(datetime.UTC),
            updated_at=datetime.datetime.now(datetime.UTC),
        )

    async def mark_terminal(
        self,
        session: AsyncSession,
        run_id: str,
        status: AgentRunStatus,
        *,
        ended_at: datetime.datetime,
        last_completed_event_id: str | None = None,
    ) -> object:
        """Record terminal update call."""
        del session, run_id, ended_at, last_completed_event_id
        self.terminal_status = status
        return object()


class _AgentSessionRepo:
    """Legacy session repo for tests."""

    async def get_by_id(
        self,
        session: AsyncSession,
        agent_session_id: str,
    ) -> AgentSession | None:
        """Handle session lookup call."""
        del session, agent_session_id
        return _agent_session()


class _EventSessionRepo:
    """Event session mirror repo for tests."""

    async def ensure_from_legacy_session(
        self,
        session: AsyncSession,
        legacy_session: AgentSession,
    ) -> object:
        """Handle mirror call."""
        del session, legacy_session
        return object()


class _EventSessionHeadState:
    """Event session head state for tests."""

    def __init__(self, head_event_id: str | None) -> None:
        self.model_input_head_event_id = head_event_id


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
        self.protected_token_budget: int | None = None
        self.reason: str | None = None

    async def compact(
        self,
        session: AsyncSession,
        *,
        session_id: str,
        transcript: Sequence[Event],
        compaction_id: str,
        summarize: SummaryGenerator,
        protected_token_budget: int,
        summary_context_window_tokens: int | None = None,
        reason: str | None = None,
    ) -> Event:
        """Call summary generator and return summary event."""
        del session, compaction_id
        self.protected_token_budget = protected_token_budget
        self.reason = reason
        summary = await summarize(
            transcript,
            compute_summary_budget(summary_context_window_tokens),
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
        session: AsyncSession,
        *,
        session_id: str,
        transcript: Sequence[Event],
        compaction_id: str,
        summarize: SummaryGenerator,
        protected_token_budget: int,
        summary_context_window_tokens: int | None = None,
        reason: str | None = None,
    ) -> Event | None:
        """Raise compaction failure."""
        del (
            session,
            session_id,
            transcript,
            compaction_id,
            summarize,
            protected_token_budget,
            summary_context_window_tokens,
            reason,
        )
        raise CompactionFailedError(
            "Compaction failed: summary model returned no text."
        )


class _Execution:
    """Execution for tests."""

    def __init__(self) -> None:
        self.request: AgentRunExecutionRequest | None = None

    async def run(
        self,
        session: AsyncSession,
        request: AgentRunExecutionRequest,
        *,
        check_stop: CheckStop | None = None,
        poll_input_events: object = None,
    ) -> AgentRunStatus:
        """Record run request and return completed."""
        del session, check_stop, poll_input_events
        self.request = request
        return AgentRunStatus.COMPLETED


class _FailingExecution:
    """Execution that raises user-visible runtime error."""

    async def run(
        self,
        session: AsyncSession,
        request: AgentRunExecutionRequest,
        *,
        check_stop: CheckStop | None = None,
        poll_input_events: object = None,
    ) -> AgentRunStatus:
        """Propagate ModelCallError."""
        del session, request, check_stop, poll_input_events
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
        session: AsyncSession,
        request: AgentRunExecutionRequest,
        *,
        check_stop: CheckStop | None = None,
        poll_input_events: object = None,
    ) -> AgentRunStatus:
        """Send tool call output to sink first, then wait for completion signal."""
        del session, request, check_stop, poll_input_events
        event = Event(
            id="1" * 32,
            session_id="session-1",
            kind=EventKind.CLIENT_TOOL_CALL,
            payload=ClientToolCallPayload(
                call_id="call-1",
                name="tool",
                arguments="{}",
                native_artifact=_artifact(
                    {"type": "function_call", "call_id": "call-1"}
                ),
            ),
            created_at=datetime.datetime.now(datetime.UTC),
        )
        if self.output_sink is None:
            raise AssertionError("output sink was not injected")
        await self.output_sink(NormalizedAdapterOutput(events=[]), [event])
        try:
            await self._done.wait()
        except asyncio.CancelledError as exc:
            self.cancel_args = exc.args
            self.cancelled.set()
            raise
        return AgentRunStatus.COMPLETED


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
            prompt="tool prompt",
        )

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
        event_session_repo=_EventSessionRepo(),
        execution_factory=lambda **kwargs: execution,
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
            ),
            RunContext(
                user_id="user-1",
                run_id="0" * 32,
                publish_event=_noop_publish,
            ),
        )
    ]

    assert run_repo.created is not None
    assert run_repo.created.id == "0" * 32
    assert execution.request is not None
    assert execution.request.system_prompt == "## Agent prompt\n\nagent prompt"
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
        event_session_repo=_EventSessionRepo(),
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
        ),
        RunContext(
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


async def test_adapter_forwards_user_stop_cancellation_to_execution() -> None:
    """Propagate adapter consumer user stop cancellation to execution task."""
    done = asyncio.Event()
    execution = _StreamingExecution(done)
    adapter = _agent_engine_adapter(
        session_manager=_session_context,
        artifact_service=_ArtifactService(),
        exchange_file_service=_ExchangeFileService(),
        model_file_service=_ModelFileService(),
        run_repo=_RunRepo(),
        agent_session_repo=_AgentSessionRepo(),
        event_session_repo=_EventSessionRepo(),
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
            ),
            RunContext(
                user_id="user-1",
                run_id="0" * 32,
                publish_event=_noop_publish,
            ),
        ):
            emitted.set()

    task = asyncio.create_task(consume())
    await asyncio.wait_for(emitted.wait(), timeout=1)
    task.cancel(USER_STOP_CANCEL_MESSAGE)

    with pytest.raises(asyncio.CancelledError):
        await task

    assert execution.cancel_args == (USER_STOP_CANCEL_MESSAGE,)


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
        event_session_repo=_EventSessionRepo(),
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
        ),
        RunContext(
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
        event_session_repo=_EventSessionRepo(),
        execution_factory=lambda **kwargs: execution,
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
            ),
            RunContext(
                user_id="user-1",
                run_id="0" * 32,
                publish_event=_noop_publish,
            ),
        )
    ]

    assert execution.request is not None
    assert execution.request.system_prompt == (
        "## Agent prompt\n\nagent prompt\n\n"
        "## Toolkit prompt: hooks\n\ntool prompt\n\n"
        "## Turn injected prompt from hooks\n\nvisible prompt\n\n"
        "## Turn injected prompt from hooks\n\nhidden prompt"
    )


async def test_adapter_emits_user_visible_model_call_error() -> None:
    """User-visible model error is emitted as event system_error event."""
    adapter = _agent_engine_adapter(
        session_manager=_session_context,
        artifact_service=_ArtifactService(),
        exchange_file_service=_ExchangeFileService(),
        model_file_service=_ModelFileService(),
        run_repo=_RunRepo(),
        agent_session_repo=_AgentSessionRepo(),
        event_session_repo=_EventSessionRepo(),
        transcript_repo=_TranscriptRepo([]),
        execution_factory=lambda **kwargs: _FailingExecution(),
    )

    emits = [
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
            ),
            RunContext(
                user_id="user-1",
                run_id="0" * 32,
                publish_event=_noop_publish,
            ),
        )
    ]

    error_event = _events(emits)[0]
    assert isinstance(error_event, Event)
    assert error_event.kind == EventKind.SYSTEM_ERROR
    assert isinstance(error_event.payload, SystemErrorPayload)
    assert error_event.payload.content == "Model call failed (401): Missing scopes"
    assert isinstance(_events(emits)[-1], RunComplete)


async def test_model_kwargs_routes_chatgpt_oauth_to_backend_api() -> None:
    """ChatGPT OAuth calls chatgpt backend-api/codex endpoint."""
    captured: dict[str, object] = {}

    def factory(**kwargs: object) -> _Execution:
        captured.update(kwargs)
        return _Execution()

    adapter = _agent_engine_adapter(
        session_manager=_session_context,
        artifact_service=_ArtifactService(),
        exchange_file_service=_ExchangeFileService(),
        model_file_service=_ModelFileService(),
        run_repo=_RunRepo(),
        agent_session_repo=_AgentSessionRepo(),
        event_session_repo=_EventSessionRepo(),
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
            ),
            RunContext(
                user_id="user-1",
                run_id="0" * 32,
                publish_event=_noop_publish,
            ),
        )
    ]
    lowerer = captured["lowerer"]
    assert isinstance(lowerer, LiteLLMResponsesLowerer)
    result = lowerer.lower([], model="gpt-5.1-codex").kwargs

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

    event_session_head_repo = _EventSessionHeadRepo(None)
    adapter = _agent_engine_adapter(
        session_manager=_session_context,
        artifact_service=_ArtifactService(),
        exchange_file_service=_ExchangeFileService(),
        model_file_service=_ModelFileService(),
        run_repo=_RunRepo(),
        agent_session_repo=_AgentSessionRepo(),
        event_session_repo=_EventSessionRepo(),
        event_session_head_repo=event_session_head_repo,
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
                max_tokens=123,
                max_input_tokens=64_000,
                compaction_max_input_tokens=32_000,
            ),
            RunContext(
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
    assert captured["session_repo"] is event_session_head_repo


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
        max_tokens: int,
        session_id: str | None = None,
    ) -> str:
        """Replace summary model call."""
        del provider, model, credential_kwargs, max_tokens, session_id
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
        event_session_repo=_EventSessionRepo(),
        event_session_head_repo=_EventSessionHeadRepo("1" * 32),
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
            )
        )
    ]

    assert [emit.event.__class__.__name__ for emit in emits] == [
        "CompactionStarted",
        "CompactionComplete",
    ]
    assert transcript_repo.head_event_id == "1" * 32
    assert compactor.protected_token_budget == 0
    assert compactor.reason == "manual_command"
    assert compactor.summary == "summary::[User]: old request"
    assert "durable handoff checkpoint" in captured_prompts["system_prompt"]
    assert "Do not answer the user" in captured_prompts["system_prompt"]
    assert "## Relevant Files and Symbols" in captured_prompts["user_prompt"]
    assert "existing checkpoints" in captured_prompts["user_prompt"]


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
        max_tokens: int,
        session_id: str | None = None,
    ) -> str:
        """Capture summary input."""
        del provider, model, credential_kwargs, system_prompt, user_prompt
        del max_tokens, session_id
        captured["conversation_text"] = conversation_text
        return "summary"

    adapter = _agent_engine_adapter(
        session_manager=_session_context,
        artifact_service=_ArtifactService(),
        exchange_file_service=_ExchangeFileService(),
        model_file_service=_ModelFileService(),
        run_repo=_RunRepo(),
        agent_session_repo=_AgentSessionRepo(),
        event_session_repo=_EventSessionRepo(),
        event_session_head_repo=_EventSessionHeadRepo("6" * 32),
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
                max_input_tokens=12_000,
                compaction_max_input_tokens=12_000,
            )
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
        event_session_repo=_EventSessionRepo(),
        event_session_head_repo=_EventSessionHeadRepo("1" * 32),
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
        )
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
        id="session-1",
        workspace_id="workspace-1",
        agent_runtime_id="runtime-1",
        agent_id="agent-1",
        status=AgentSessionStatus.ACTIVE,
        start_reason=AgentSessionStartReason.INITIAL,
        created_at=now,
        updated_at=now,
        started_at=now,
    )


async def _noop_publish(_event: object) -> None:
    """No-op publish."""


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
    event_session_repo: _EventSessionRepo | None = None,
    event_session_head_repo: _EventSessionHeadRepo | None = None,
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
        event_session_repo=event_session_repo or _EventSessionRepo(),
        event_session_head_repo=event_session_head_repo or _EventSessionHeadRepo(None),
        transcript_repo=transcript_repo or _TranscriptRepo([]),
        compactor=compactor or _Compactor(),
        summary_model_call=summary_model_call or summarize_text_with_model,
    )


def _events(emits: list[Emit]) -> list[object]:
    """Return emit event list."""
    return [emit.event for emit in emits]
