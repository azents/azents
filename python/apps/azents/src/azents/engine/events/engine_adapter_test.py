"""Event engine adapter assembly tests."""

import asyncio
import base64
import datetime
import functools
from collections.abc import AsyncGenerator, AsyncIterator, Awaitable, Callable, Sequence
from contextlib import asynccontextmanager
from io import BytesIO
from types import SimpleNamespace
from typing import Annotated
from unittest.mock import AsyncMock

import pytest
from azcommon.result import Failure, Success
from fastapi import Depends
from fastapi.dependencies.utils import get_dependant
from PIL import Image
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

import azents.engine.events.engine_adapter as engine_adapter_module
from azents.core.chatgpt_oauth import CHATGPT_OAUTH_BACKEND_BASE_URL
from azents.core.credentials import XaiOAuthSecrets
from azents.core.enums import (
    AgentRunPhase,
    AgentRunStatus,
    AgentSessionKind,
    AgentSessionStartReason,
    AgentSessionStatus,
    EventKind,
    LLMModelDeveloper,
    LLMProvider,
)
from azents.core.inference_profile import SessionInferenceState
from azents.core.llm_catalog import ModelBuiltInToolCapabilities, ModelCapabilities
from azents.core.openrouter import OPENROUTER_API_BASE_URL, OPENROUTER_APP_TITLE
from azents.core.tools import (
    ProfiledToolkitPrompt,
    Toolkit,
    ToolkitState,
    ToolkitStatus,
    TurnContext,
)
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
    _WorkingSetClientToolExecutor,  # pyright: ignore[reportPrivateUsage]  # Verify deferred recency wrapper.
    _xai_imagine_client_factory,  # pyright: ignore[reportPrivateUsage]  # Test-only default dependency.
)
from azents.engine.events.engine_events import RunComplete
from azents.engine.events.execution import (
    AgentRunExecutionRequest,
    ModelCallPreparer,
    PreparedModelCall,
)
from azents.engine.events.filters import (
    EventAutoCompactionFilter,
    EventPreLowerFilterPipeline,
    PostLowerFilterPipeline,
)
from azents.engine.events.litellm_responses import LiteLLMResponsesModelAdapter
from azents.engine.events.openai_responses import (
    OpenAIResponsesModelAdapter,
    OpenAIResponsesRequest,
)
from azents.engine.events.protocols import (
    NativeModelRequest,
    NativeRequestInspection,
    NormalizedAdapterOutput,
    OutputSink,
    SummaryEnricher,
    SummaryGenerator,
)
from azents.engine.events.responses_continuation import ResponsesContinuationPlanner
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
from azents.engine.hooks.dispatcher import (
    RuntimeHookDispatcher,
    RuntimeHookProviderRef,
)
from azents.engine.hooks.types import (
    BeforeToolCallHookContext,
    CompactionSummaryHookContext,
    CompactionSummaryReplace,
    RuntimeHooks,
    ToolCallDeny,
    TurnInjectedPrompt,
    TurnStartHookContext,
    TurnStartResult,
)
from azents.engine.run.client_tool_compatibility import ClientToolProfile
from azents.engine.run.contracts import RunContext, RunRequest, ToolkitBinding
from azents.engine.run.emit import Emit
from azents.engine.run.errors import CompactionFailedError, ModelCallError
from azents.engine.run.model_transport import InMemoryModelTransportState
from azents.engine.run.types import (
    USER_STOP_CANCEL_MESSAGE,
    BuiltinToolSpec,
    CheckStop,
    FunctionTool,
    FunctionToolError,
    FunctionToolSpec,
)
from azents.engine.tooling.tool_search import (
    ToolWorkingSetState,
    ToolWorkingSetStore,
)
from azents.engine.tools.xai_image_generation import XaiImagineClientFactory
from azents.repos.agent_execution.data import AgentRunCreate, EventCreate
from azents.repos.agent_session import AgentSessionRepository
from azents.repos.agent_session.data import AgentSession
from azents.repos.model_file_pin import ModelFilePinRepository
from azents.services.artifact import ArtifactService
from azents.services.exchange_file import ExchangeFileService
from azents.services.model_file import ModelFileService
from azents.services.xai_imagine import (
    XaiImagineAuthenticationError,
    XaiImagineClient,
    XaiImagineRequest,
)
from azents.services.xai_oauth.data import (
    ProviderEntitlementDenied,
    ProviderRejected,
    ProviderUnavailable,
)
from azents.testing.model_selection import (
    make_test_model_selection,
    make_test_model_settings,
)
from azents.testing.model_stream import make_test_model_stream_watchdog


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


class _ToolWorkingSetStore(ToolWorkingSetStore):
    """In-memory working-set store for adapter assembly tests."""

    def __init__(self) -> None:
        self.states: dict[tuple[str, str], ToolWorkingSetState] = {}

    async def load(self, agent_id: str, session_id: str) -> ToolWorkingSetState:
        """Return current in-memory state."""
        return self.states.get((agent_id, session_id), ToolWorkingSetState())

    async def activate(
        self,
        agent_id: str,
        session_id: str,
        tool_names: Sequence[str],
    ) -> ToolWorkingSetState:
        """Move activated names to the in-memory recency front."""
        current = await self.load(agent_id, session_id)
        activated = list(dict.fromkeys(tool_names))
        state = ToolWorkingSetState(
            tool_names=[
                *activated,
                *(name for name in current.tool_names if name not in activated),
            ]
        )
        self.states[(agent_id, session_id)] = state
        return state

    async def touch(
        self,
        agent_id: str,
        session_id: str,
        tool_name: str,
    ) -> ToolWorkingSetState:
        """Move one invoked name to the in-memory recency front."""
        return await self.activate(agent_id, session_id, [tool_name])

    async def clear_in_session(
        self,
        session: AsyncSession,
        agent_id: str,
        session_id: str,
    ) -> ToolWorkingSetState:
        """Clear one in-memory working set."""
        del session
        state = ToolWorkingSetState()
        self.states[(agent_id, session_id)] = state
        return state


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
        now = datetime.datetime.now(datetime.UTC)
        self._state: AgentRunState | None = AgentRunState(
            id="0" * 32,
            session_id="session-1",
            run_index=1,
            phase=AgentRunPhase.IDLE,
            status=AgentRunStatus.RUNNING,
            parent_agent_run_id=None,
            active_tool_calls=[],
            parent_result_delivery_state=None,
            parent_result_input_buffer_id=None,
            parent_result_enqueued_at=None,
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
            parent_result_delivery_state=None,
            parent_result_input_buffer_id=None,
            parent_result_enqueued_at=None,
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
        on_started: Callable[[], Awaitable[None]] | None = None,
        summary_context_window_tokens: int | None = None,
        reason: str | None = None,
        summary_enricher: SummaryEnricher | None = None,
        on_committing: Callable[[AsyncSession], Awaitable[None]] | None = None,
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
        if on_committing is not None:
            await on_committing(_Session())
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
        on_started: Callable[[], Awaitable[None]] | None = None,
        summary_context_window_tokens: int | None = None,
        reason: str | None = None,
        summary_enricher: SummaryEnricher | None = None,
        on_committing: Callable[[AsyncSession], Awaitable[None]] | None = None,
    ) -> Event | None:
        """Raise compaction failure."""
        del (
            session_id,
            transcript,
            compaction_id,
            summarize,
            on_started,
            summary_context_window_tokens,
            reason,
            summary_enricher,
            on_committing,
        )
        raise CompactionFailedError(
            "Compaction failed: summary model returned no text."
        )


class _Execution:
    """Execution for tests."""

    def __init__(self) -> None:
        self.request: AgentRunExecutionRequest | None = None
        self.model_call_preparer: ModelCallPreparer[NativeRequestInspection] | None = (
            None
        )
        self.prepared_model_call: PreparedModelCall[NativeRequestInspection] | None = (
            None
        )

    async def run(
        self,
        request: AgentRunExecutionRequest,
        *,
        check_stop: CheckStop | None = None,
        poll_input_events: object = None,
    ) -> AgentRunStatus:
        """Record run request and prepare a model call when wired."""
        del check_stop, poll_input_events
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
        request: AgentRunExecutionRequest,
        *,
        check_stop: CheckStop | None = None,
        poll_input_events: object = None,
    ) -> AgentRunStatus:
        """Propagate ModelCallError."""
        del request, check_stop, poll_input_events
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
        request: AgentRunExecutionRequest,
        *,
        check_stop: CheckStop | None = None,
        poll_input_events: object = None,
    ) -> AgentRunStatus:
        """Send tool call output to sink first, then wait for completion signal."""
        del request, check_stop, poll_input_events
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
        await self.output_sink(
            NormalizedAdapterOutput(needs_follow_up=False, events=[]),
            [event],
        )
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


class _DeferredToolkit(Toolkit[BaseModel]):
    """Registered service Toolkit used for Tool Search integration tests."""

    display_name = "Deferred Service"

    def __init__(self, tool_names: Sequence[str]) -> None:
        self.tool_names = list(tool_names)

    async def update_context(self, context: TurnContext) -> ToolkitState:
        """Return the current deferred operation set."""
        del context
        tools: list[FunctionTool] = []
        for name in self.tool_names:

            async def handler(arguments: str, *, tool_name: str = name) -> str:
                return f"{tool_name}:{arguments}"

            tools.append(
                FunctionTool(
                    spec=FunctionToolSpec(
                        name=name,
                        description=f"Run the {name} deferred service operation.",
                        input_schema={"type": "object", "properties": {}},
                    ),
                    handler=handler,
                )
            )
        return ToolkitState(status=ToolkitStatus.ENABLED, tools=tools)


class _ProfiledCandidateToolkit(Toolkit[BaseModel]):
    """Toolkit exposing one profile-gated deferred tool and prompt."""

    display_name = "Profiled Service"

    async def update_context(self, context: TurnContext) -> ToolkitState:
        """Return one profile-gated candidate tool."""
        del context

        async def handler(arguments: str) -> str:
            return arguments

        return ToolkitState(
            status=ToolkitStatus.ENABLED,
            tools=[
                FunctionTool(
                    spec=FunctionToolSpec(
                        name="apply_patch",
                        description="Apply one V4A patch.",
                        input_schema={"type": "object", "properties": {}},
                    ),
                    handler=handler,
                ).with_required_client_tool_profile(
                    ClientToolProfile.GPT_V4A_APPLY_PATCH
                )
            ],
        )

    async def get_profiled_static_prompts(
        self,
        context: TurnContext,
    ) -> list[ProfiledToolkitPrompt]:
        """Return guidance coupled to the profile-gated tool."""
        del context
        return [
            ProfiledToolkitPrompt(
                required_client_tool_profile=(ClientToolProfile.GPT_V4A_APPLY_PATCH),
                content="Use apply_patch for multi-file changes.",
            )
        ]


class _DenyHookToolkit(Toolkit[BaseModel]):
    """Runtime hook provider that denies every tool call."""

    async def update_context(self, context: TurnContext) -> ToolkitState:
        """Return no tools; only the hook behavior is needed."""
        del context
        return ToolkitState(status=ToolkitStatus.ENABLED, tools=[])

    def hooks(self) -> RuntimeHooks:
        """Return the deny hook mapping."""
        return {"on_before_tool_call": self._deny}

    async def _deny(self, context: BeforeToolCallHookContext) -> ToolCallDeny:
        """Deny one tool call."""
        del context
        return ToolCallDeny(message="denied")


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


def test_agent_engine_adapter_dependency_graph_is_valid() -> None:
    """FastAPI can construct the complete adapter dependency graph."""

    def endpoint(
        adapter: Annotated[AgentEngineAdapter, Depends(AgentEngineAdapter)],
    ) -> None:
        del adapter

    assert get_dependant(path="/", call=endpoint).dependencies


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


async def test_working_set_recency_refreshes_before_hook_denial() -> None:
    """Treat a denied deferred invocation as current capability intent."""
    store = _ToolWorkingSetStore()
    await store.activate("agent-1", "session-1", ["service__other"])
    hooked = _HookedClientToolExecutor(
        inner=_RecordingToolExecutor(),
        dispatcher=RuntimeHookDispatcher(),
        providers=[RuntimeHookProviderRef(slug="deny", toolkit=_DenyHookToolkit())],
        workspace_id="workspace-1",
        agent_id="agent-1",
        session_id="session-1",
        run_id="run-1",
    )
    wrapper = _WorkingSetClientToolExecutor(
        inner=hooked,
        deferred_tool_names=frozenset({"service__probe"}),
        store=store,
        agent_id="agent-1",
        session_id="session-1",
    )

    result = await wrapper.execute(
        ClientToolCallPayload(
            call_id="call-1",
            name="service__probe",
            arguments="{}",
            native_artifact=_artifact({"type": "function_call"}),
        )
    )
    state = await store.load("agent-1", "session-1")

    assert result.status == "failed"
    assert state.tool_names == ["service__probe", "service__other"]


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
                tool_search_enabled=False,
                auto_compaction_threshold_tokens=None,
                inference_state=None,
                compaction_provider_integration_id=None,
            ),
            RunContext(
                owner_generation=1,
                tool_admission_barrier=_OpenToolAdmissionBarrier(),
                model_transport_state=InMemoryModelTransportState(
                    websocket_enabled=False
                ),
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
    assert isinstance(prepared_request, OpenAIResponsesRequest)
    assert prepared_request.options.get("instructions") == (
        "## Agent prompt\n\nagent prompt"
    )
    assert isinstance(prepared_request.options.get("prompt_cache_key"), str)
    assert isinstance(_events(emits)[0], RunComplete)


async def test_disabled_tool_search_exposes_complete_catalog() -> None:
    """Preserve the complete legacy tool catalog when Tool Search is disabled."""
    toolkit = _DeferredToolkit(["probe", "other"])
    store = _ToolWorkingSetStore()
    execution = _Execution()
    adapter = _agent_engine_adapter(
        tool_working_set_store=store,
        execution_factory=lambda **kwargs: (
            setattr(
                execution,
                "model_call_preparer",
                kwargs["model_call_preparer"],
            )
            or execution
        ),
    )
    request = RunRequest(
        session_id="session-1",
        user_messages=[],
        agent_prompt=None,
        toolkits=[
            ToolkitBinding(
                toolkit=toolkit,
                slug="service",
                use_prefix=True,
                toolkit_type="github",
            )
        ],
        model="gpt-5.1",
        credential_kwargs={"api_key": "test"},
        workspace_id="workspace-1",
        agent_id="agent-1",
        tool_search_enabled=False,
        auto_compaction_threshold_tokens=None,
        inference_state=None,
        compaction_provider_integration_id=None,
    )

    _ = [emit async for emit in adapter.run(request, _run_context())]

    assert execution.prepared_model_call is not None
    prepared = execution.prepared_model_call
    native_request = prepared.native_request
    assert isinstance(native_request, OpenAIResponsesRequest)
    assert [tool["name"] for tool in native_request.tools] == [
        "service__other",
        "service__probe",
    ]

    result = await prepared.tool_executor.execute(
        ClientToolCallPayload(
            call_id="probe-1",
            name="service__probe",
            arguments="{}",
            native_artifact=_artifact({"type": "function_call"}),
        )
    )

    assert result.status == "completed"
    assert (await store.load("agent-1", "session-1")).tool_names == []


@pytest.mark.parametrize(
    ("model_identifier", "model_developer", "model_family", "expected_tools"),
    [
        (
            "gpt-5.1",
            LLMModelDeveloper.OPENAI,
            "gpt-5",
            ["tool_search"],
        ),
        (
            "claude-sonnet-4",
            LLMModelDeveloper.ANTHROPIC,
            "claude-sonnet-4",
            [],
        ),
    ],
)
async def test_client_tool_profile_projects_before_search_and_lowering(
    model_identifier: str,
    model_developer: LLMModelDeveloper,
    model_family: str,
    expected_tools: list[str],
) -> None:
    """Project profile-gated candidates before search indexing and lowering."""
    prepared = await _prepare_profiled_model_call(
        model_identifier=model_identifier,
        model_developer=model_developer,
        model_family=model_family,
        request_model_developer=model_developer,
    )

    native_request = prepared.native_request
    assert isinstance(native_request, OpenAIResponsesRequest)
    assert [tool["name"] for tool in native_request.tools] == expected_tools
    instructions = native_request.options.get("instructions")
    if expected_tools:
        assert isinstance(instructions, str)
        assert "Use apply_patch for multi-file changes." in instructions
    else:
        assert isinstance(instructions, str)
        assert "Use apply_patch for multi-file changes." not in instructions


async def test_client_tool_profile_uses_selected_snapshot_developer() -> None:
    """Prefer immutable selected-model identity over the request fallback field."""
    prepared = await _prepare_profiled_model_call(
        model_identifier="gpt-5.1",
        model_developer=LLMModelDeveloper.OPENAI,
        model_family="gpt-5",
        request_model_developer=LLMModelDeveloper.ANTHROPIC,
    )

    native_request = prepared.native_request
    assert isinstance(native_request, OpenAIResponsesRequest)
    assert [tool["name"] for tool in native_request.tools] == ["tool_search"]


async def test_client_tool_profile_re_evaluates_for_changed_model_snapshot() -> None:
    """Re-evaluate profile projection when the selected model snapshot changes."""
    gpt_prepared = await _prepare_profiled_model_call(
        model_identifier="gpt-5.1",
        model_developer=LLMModelDeveloper.OPENAI,
        model_family="gpt-5",
        request_model_developer=LLMModelDeveloper.OPENAI,
    )
    non_gpt_prepared = await _prepare_profiled_model_call(
        model_identifier="claude-sonnet-4",
        model_developer=LLMModelDeveloper.ANTHROPIC,
        model_family="claude-sonnet-4",
        request_model_developer=LLMModelDeveloper.ANTHROPIC,
    )

    gpt_request = gpt_prepared.native_request
    non_gpt_request = non_gpt_prepared.native_request
    assert isinstance(gpt_request, OpenAIResponsesRequest)
    assert isinstance(non_gpt_request, OpenAIResponsesRequest)
    assert [tool["name"] for tool in gpt_request.tools] == ["tool_search"]
    assert non_gpt_request.tools == []


async def test_tool_search_activation_updates_the_next_prepared_call() -> None:
    """Hide deferred tools until search and retain immutable call snapshots."""
    toolkit = _DeferredToolkit(["probe", "other"])
    store = _ToolWorkingSetStore()
    execution = _Execution()
    adapter = _agent_engine_adapter(
        tool_working_set_store=store,
        execution_factory=lambda **kwargs: (
            setattr(
                execution,
                "model_call_preparer",
                kwargs["model_call_preparer"],
            )
            or execution
        ),
    )
    request = RunRequest(
        session_id="session-1",
        user_messages=[],
        agent_prompt=None,
        toolkits=[
            ToolkitBinding(
                toolkit=toolkit,
                slug="service",
                use_prefix=True,
                toolkit_type="github",
            )
        ],
        model="gpt-5.1",
        credential_kwargs={"api_key": "test"},
        workspace_id="workspace-1",
        agent_id="agent-1",
        tool_search_enabled=True,
        auto_compaction_threshold_tokens=None,
        inference_state=None,
        compaction_provider_integration_id=None,
    )
    _ = [
        emit
        async for emit in adapter.run(
            request,
            RunContext(
                owner_generation=1,
                tool_admission_barrier=_OpenToolAdmissionBarrier(),
                model_transport_state=InMemoryModelTransportState(
                    websocket_enabled=False
                ),
                user_id="user-1",
                run_id="0" * 32,
                publish_event=_noop_publish,
            ),
        )
    ]

    assert execution.prepared_model_call is not None
    first_prepared = execution.prepared_model_call
    first_request = first_prepared.native_request
    assert isinstance(first_request, OpenAIResponsesRequest)
    assert [tool["name"] for tool in first_request.tools] == ["tool_search"]

    hidden_result = await first_prepared.tool_executor.execute(
        ClientToolCallPayload(
            call_id="hidden-1",
            name="service__probe",
            arguments="{}",
            native_artifact=_artifact({"type": "function_call"}),
        )
    )
    assert hidden_result.status == "failed"
    assert (await store.load("agent-1", "session-1")).tool_names == []

    search_result = await first_prepared.tool_executor.execute(
        ClientToolCallPayload(
            call_id="search-1",
            name="tool_search",
            arguments='{"query":"probe operation","limit":1}',
            native_artifact=_artifact({"type": "function_call"}),
        )
    )
    assert search_result.status == "completed"

    toolkit.tool_names.append("new_operation")
    stale_result = await first_prepared.tool_executor.execute(
        ClientToolCallPayload(
            call_id="stale-1",
            name="service__new_operation",
            arguments="{}",
            native_artifact=_artifact({"type": "function_call"}),
        )
    )
    assert stale_result.status == "failed"

    assert execution.model_call_preparer is not None
    second_prepared = await execution.model_call_preparer(
        transcript=[],
        model="gpt-5.1",
    )
    second_request = second_prepared.native_request
    assert isinstance(second_request, OpenAIResponsesRequest)
    assert [tool["name"] for tool in second_request.tools] == [
        "service__probe",
        "tool_search",
    ]

    await store.activate("agent-1", "session-1", ["service__other"])
    invoked = await second_prepared.tool_executor.execute(
        ClientToolCallPayload(
            call_id="probe-1",
            name="service__probe",
            arguments="{}",
            native_artifact=_artifact({"type": "function_call"}),
        )
    )
    state = await store.load("agent-1", "session-1")

    assert invoked.status == "completed"
    assert state.tool_names[:2] == ["service__probe", "service__other"]


async def _prepare_profiled_model_call(
    *,
    model_identifier: str,
    model_developer: LLMModelDeveloper,
    model_family: str,
    request_model_developer: LLMModelDeveloper | None,
) -> PreparedModelCall[NativeRequestInspection]:
    """Prepare one call from a normalized selected-model snapshot."""
    execution = _Execution()
    adapter = _agent_engine_adapter(
        execution_factory=lambda **kwargs: (
            setattr(
                execution,
                "model_call_preparer",
                kwargs["model_call_preparer"],
            )
            or execution
        ),
    )
    selection = make_test_model_selection(
        model_identifier=model_identifier,
        model_developer=model_developer,
    ).model_copy(update={"model_family": model_family})
    inference_state = SessionInferenceState(
        model_target_label="default",
        model_selection=selection,
        model_settings=make_test_model_settings(),
        reasoning_effort=None,
        effective_context_window_tokens=128_000,
        effective_auto_compaction_threshold_tokens=102_400,
        resolved_at=datetime.datetime.now(datetime.UTC),
    )
    request = RunRequest(
        session_id="session-1",
        user_messages=[],
        agent_prompt=None,
        toolkits=[
            ToolkitBinding(
                toolkit=_ProfiledCandidateToolkit(),
                slug="profiled",
                use_prefix=False,
                toolkit_type="github",
            )
        ],
        model=model_identifier,
        model_developer=request_model_developer,
        credential_kwargs={"api_key": "test"},
        workspace_id="workspace-1",
        agent_id="agent-1",
        tool_search_enabled=True,
        auto_compaction_threshold_tokens=None,
        inference_state=inference_state,
        compaction_provider_integration_id=None,
    )

    _ = [emit async for emit in adapter.run(request, _run_context())]

    if execution.prepared_model_call is None:
        raise AssertionError("model call was not prepared")
    return execution.prepared_model_call


def _valid_png_base64() -> str:
    """Return one deterministic valid PNG payload."""
    body = BytesIO()
    Image.new("RGB", (1, 1), color=(255, 0, 0)).save(body, format="PNG")
    return base64.b64encode(body.getvalue()).decode()


class _RefreshingImagineClient(XaiImagineClient):
    """Record credentials and reject the known stale token."""

    def __init__(self, tokens: list[str]) -> None:
        self.tokens = tokens

    async def generate(
        self,
        request: XaiImagineRequest,
        *,
        access_token: str,
    ) -> str:
        """Reject the old token and return one deterministic image otherwise."""
        del request
        self.tokens.append(access_token)
        if access_token == "old-access-token":
            raise XaiImagineAuthenticationError(
                "xAI Imagine rejected the integration credential."
            )
        return _valid_png_base64()


def _refreshing_imagine_client_factory(tokens: list[str]) -> XaiImagineClientFactory:
    """Return a factory sharing one assertion-visible credential log."""

    @asynccontextmanager
    async def create() -> AsyncIterator[XaiImagineClient]:
        yield _RefreshingImagineClient(tokens)

    return create


def _xai_oauth_inference_state() -> SessionInferenceState:
    """Return xAI OAuth inference state with a selected integration identity."""
    return SessionInferenceState(
        model_target_label="planning",
        model_selection=make_test_model_selection(
            integration_id="integration-1",
            provider=LLMProvider.XAI_OAUTH,
            model_identifier="grok-4",
            model_developer=LLMModelDeveloper.XAI,
        ),
        model_settings=make_test_model_settings(),
        reasoning_effort=None,
        effective_context_window_tokens=128_000,
        effective_auto_compaction_threshold_tokens=102_400,
        resolved_at=datetime.datetime.now(datetime.UTC),
    )


async def test_xai_image_generation_is_bound_as_client_function_tool() -> None:
    """Expose Imagine to Grok without lowering it as a provider-hosted tool."""
    execution = _Execution()
    adapter = _agent_engine_adapter(
        session_manager=_session_context,
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
                agent_prompt=None,
                toolkits=[],
                provider=LLMProvider.XAI,
                model="xai/grok-4",
                model_capabilities=ModelCapabilities(
                    built_in_tools=ModelBuiltInToolCapabilities(
                        supported=["image_generation"]
                    )
                ),
                credential_kwargs={"api_key": "xai-api-key"},
                workspace_id="workspace-1",
                agent_id="agent-1",
                tool_search_enabled=False,
                auto_compaction_threshold_tokens=None,
                inference_state=None,
                compaction_provider_integration_id=None,
                builtin_tools=[BuiltinToolSpec(name="image_generation", config={})],
            ),
            RunContext(
                owner_generation=1,
                tool_admission_barrier=_OpenToolAdmissionBarrier(),
                model_transport_state=InMemoryModelTransportState(
                    websocket_enabled=False
                ),
                user_id="user-1",
                run_id="0" * 32,
                publish_event=_noop_publish,
            ),
        )
    ]

    assert execution.prepared_model_call is not None
    prepared_request = execution.prepared_model_call.native_request
    assert isinstance(prepared_request, NativeModelRequest)
    assert [tool["name"] for tool in prepared_request.tools] == ["image_generation"]
    assert all(tool.get("type") == "function" for tool in prepared_request.tools)


async def test_xai_oauth_refresh_updates_later_model_turn_credentials(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Reuse a forced-refresh token for later model calls and tool bindings."""
    tokens: list[str] = []
    execution = _Execution()
    integration_repository = AsyncMock()
    integration_repository.get_by_id_with_secrets.return_value = SimpleNamespace(
        workspace_id="workspace-1",
        provider=LLMProvider.XAI_OAUTH,
    )

    async def refresh_tokens(**_kwargs: object) -> object:
        return Success(
            SimpleNamespace(
                secrets=XaiOAuthSecrets(
                    access_token="new-access-token",
                    refresh_token="refresh-token",
                    id_token=None,
                    expires_at=datetime.datetime.now(datetime.UTC)
                    + datetime.timedelta(hours=1),
                )
            )
        )

    monkeypatch.setattr(
        engine_adapter_module,
        "refresh_runtime_tokens",
        refresh_tokens,
    )
    adapter = _agent_engine_adapter(
        session_manager=_session_context,
        execution_factory=lambda **kwargs: (
            setattr(
                execution,
                "model_call_preparer",
                kwargs["model_call_preparer"],
            )
            or execution
        ),
        integration_repository=integration_repository,
        xai_imagine_client_factory=_refreshing_imagine_client_factory(tokens),
    )
    request = RunRequest(
        session_id="session-1",
        user_messages=[],
        agent_prompt=None,
        toolkits=[],
        provider=LLMProvider.XAI_OAUTH,
        model="xai/grok-4",
        model_capabilities=ModelCapabilities(
            built_in_tools=ModelBuiltInToolCapabilities(supported=["image_generation"])
        ),
        credential_kwargs={"api_key": "old-access-token"},
        workspace_id="workspace-1",
        agent_id="agent-1",
        tool_search_enabled=False,
        auto_compaction_threshold_tokens=None,
        inference_state=_xai_oauth_inference_state(),
        compaction_provider_integration_id=None,
        builtin_tools=[BuiltinToolSpec(name="image_generation", config={})],
    )

    _ = [emit async for emit in adapter.run(request, _run_context())]

    assert execution.prepared_model_call is not None
    first_result = await execution.prepared_model_call.tool_executor.execute(
        ClientToolCallPayload(
            call_id="call-1",
            name="image_generation",
            arguments='{"prompt":"First image"}',
            native_artifact=_artifact({"type": "function_call"}),
        )
    )
    assert first_result.status == "completed"
    assert request.credential_kwargs["api_key"] == "new-access-token"
    assert execution.model_call_preparer is not None
    second_prepared = await execution.model_call_preparer(
        transcript=[],
        model="xai/grok-4",
    )
    second_request = second_prepared.native_request
    assert isinstance(second_request, NativeModelRequest)
    assert second_request.kwargs["api_key"] == "new-access-token"

    second_result = await second_prepared.tool_executor.execute(
        ClientToolCallPayload(
            call_id="call-2",
            name="image_generation",
            arguments='{"prompt":"Second image"}',
            native_artifact=_artifact({"type": "function_call"}),
        )
    )

    assert second_result.status == "completed"
    assert tokens == ["old-access-token", "new-access-token", "new-access-token"]


@pytest.mark.parametrize(
    ("refresh_error", "expected_message"),
    [
        (
            ProviderRejected(reason="rejected"),
            "xAI OAuth reconnect is required for image generation.",
        ),
        (
            ProviderEntitlementDenied(reason="denied"),
            "xAI Imagine access is not permitted for this account.",
        ),
        (
            ProviderUnavailable(reason="unavailable"),
            "xAI OAuth is temporarily unavailable. Try again later.",
        ),
    ],
)
async def test_xai_oauth_refresh_preserves_failure_classification(
    monkeypatch: pytest.MonkeyPatch,
    refresh_error: ProviderRejected | ProviderEntitlementDenied | ProviderUnavailable,
    expected_message: str,
) -> None:
    """Keep forced-refresh credential, entitlement, and outage errors distinct."""
    integration_repository = AsyncMock()
    integration_repository.get_by_id_with_secrets.return_value = SimpleNamespace(
        workspace_id="workspace-1",
        provider=LLMProvider.XAI_OAUTH,
    )

    async def refresh_tokens(**_kwargs: object) -> object:
        return Failure(refresh_error)

    monkeypatch.setattr(
        engine_adapter_module,
        "refresh_runtime_tokens",
        refresh_tokens,
    )
    adapter = _agent_engine_adapter(
        integration_repository=integration_repository,
        xai_imagine_client_factory=_refreshing_imagine_client_factory([]),
    )
    request = RunRequest(
        session_id="session-1",
        user_messages=[],
        agent_prompt=None,
        toolkits=[],
        provider=LLMProvider.XAI_OAUTH,
        model="xai/grok-4",
        credential_kwargs={"api_key": "old-access-token"},
        workspace_id="workspace-1",
        agent_id="agent-1",
        tool_search_enabled=False,
        auto_compaction_threshold_tokens=None,
        inference_state=_xai_oauth_inference_state(),
        compaction_provider_integration_id=None,
    )
    tool = adapter._xai_image_generation_tool(request)  # pyright: ignore[reportPrivateUsage]  # Verify forced-refresh error mapping.

    with pytest.raises(FunctionToolError, match=expected_message):
        await tool.handler('{"prompt":"Image"}')


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
            tool_search_enabled=False,
            auto_compaction_threshold_tokens=None,
            inference_state=None,
            compaction_provider_integration_id=None,
        ),
        RunContext(
            owner_generation=1,
            tool_admission_barrier=_OpenToolAdmissionBarrier(),
            model_transport_state=InMemoryModelTransportState(websocket_enabled=False),
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
                tool_search_enabled=False,
                auto_compaction_threshold_tokens=None,
                inference_state=None,
                compaction_provider_integration_id=None,
            ),
            RunContext(
                owner_generation=1,
                tool_admission_barrier=_OpenToolAdmissionBarrier(),
                model_transport_state=InMemoryModelTransportState(
                    websocket_enabled=False
                ),
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
            tool_search_enabled=False,
            auto_compaction_threshold_tokens=None,
            inference_state=None,
            compaction_provider_integration_id=None,
        ),
        RunContext(
            owner_generation=1,
            tool_admission_barrier=_OpenToolAdmissionBarrier(),
            model_transport_state=InMemoryModelTransportState(websocket_enabled=False),
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
                tool_search_enabled=False,
                auto_compaction_threshold_tokens=None,
                inference_state=None,
                compaction_provider_integration_id=None,
            ),
            RunContext(
                owner_generation=1,
                tool_admission_barrier=_OpenToolAdmissionBarrier(),
                model_transport_state=InMemoryModelTransportState(
                    websocket_enabled=False
                ),
                user_id="user-1",
                run_id="0" * 32,
                publish_event=_noop_publish,
            ),
        )
    ]

    assert execution.prepared_model_call is not None
    native_request = execution.prepared_model_call.native_request
    assert isinstance(native_request, OpenAIResponsesRequest)
    assert native_request.options.get("instructions") == (
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
                tool_search_enabled=False,
                auto_compaction_threshold_tokens=None,
                inference_state=None,
                compaction_provider_integration_id=None,
            ),
            RunContext(
                owner_generation=1,
                tool_admission_barrier=_OpenToolAdmissionBarrier(),
                model_transport_state=InMemoryModelTransportState(
                    websocket_enabled=False
                ),
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
    captured: dict[str, object] = {}

    def factory(**kwargs: object) -> _Execution:
        captured.update(kwargs)
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
                tool_search_enabled=False,
                auto_compaction_threshold_tokens=None,
                inference_state=None,
                compaction_provider_integration_id=None,
            ),
            RunContext(
                owner_generation=1,
                tool_admission_barrier=_OpenToolAdmissionBarrier(),
                model_transport_state=InMemoryModelTransportState(
                    websocket_enabled=False
                ),
                user_id="user-1",
                run_id="0" * 32,
                publish_event=_noop_publish,
            ),
        )
    ]
    assert execution.prepared_model_call is not None
    native_request = execution.prepared_model_call.native_request
    assert isinstance(native_request, OpenAIResponsesRequest)
    assert native_request.options.get("store") is False
    assert native_request.options.get("instructions") == "You are a helpful assistant."
    assert "api_key" not in native_request.options
    assert "base_url" not in native_request.options
    model_adapter = captured["model_adapter"]
    assert isinstance(model_adapter, OpenAIResponsesModelAdapter)
    assert model_adapter.continuation_planner is None


async def test_model_kwargs_keep_openrouter_on_litellm_responses() -> None:
    """OpenRouter uses LiteLLM Responses and preserves endpoint credentials."""
    execution = _Execution()
    captured: dict[str, object] = {}

    def factory(**kwargs: object) -> _Execution:
        captured.update(kwargs)
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
                provider=LLMProvider.OPENROUTER,
                model="openrouter/anthropic/claude-sonnet-4.6",
                model_developer=LLMModelDeveloper.ANTHROPIC,
                credential_kwargs={
                    "api_key": "openrouter-test-key",
                    "base_url": OPENROUTER_API_BASE_URL,
                    "api_base": OPENROUTER_API_BASE_URL,
                    "custom_llm_provider": "openrouter",
                    "extra_headers": {
                        "X-OpenRouter-Title": OPENROUTER_APP_TITLE,
                    },
                },
                workspace_id="workspace-1",
                agent_id="agent-1",
                tool_search_enabled=False,
                auto_compaction_threshold_tokens=None,
                inference_state=None,
                compaction_provider_integration_id=None,
            ),
            RunContext(
                owner_generation=1,
                tool_admission_barrier=_OpenToolAdmissionBarrier(),
                model_transport_state=InMemoryModelTransportState(
                    websocket_enabled=False
                ),
                user_id="user-1",
                run_id="0" * 32,
                publish_event=_noop_publish,
            ),
        )
    ]

    assert execution.prepared_model_call is not None
    native_request = execution.prepared_model_call.native_request
    assert isinstance(native_request, NativeModelRequest)
    assert native_request.model == "openrouter/anthropic/claude-sonnet-4.6"
    assert native_request.kwargs["custom_llm_provider"] == "openrouter"
    assert native_request.kwargs["base_url"] == OPENROUTER_API_BASE_URL
    assert native_request.kwargs["extra_headers"] == {
        "X-OpenRouter-Title": OPENROUTER_APP_TITLE,
    }
    assert isinstance(captured["model_adapter"], LiteLLMResponsesModelAdapter)


async def test_adapter_wires_event_filters_and_session_head_repo() -> None:
    """Production assembly injects filters, head lookup, and compaction reset."""
    captured: dict[str, object] = {}
    store = _ToolWorkingSetStore()
    store.states[("agent-1", "session-1")] = ToolWorkingSetState(
        tool_names=["service__probe"]
    )

    def factory(**kwargs: object) -> _Execution:
        captured.update(kwargs)
        return _Execution()

    session_head_repo = _EventSessionHeadRepo(None)
    adapter = _agent_engine_adapter(
        session_manager=_session_context,
        tool_working_set_store=store,
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
                tool_search_enabled=False,
                auto_compaction_threshold_tokens=None,
                inference_state=None,
                compaction_provider_integration_id=None,
                max_output_tokens=123,
                max_input_tokens=64_000,
                compaction_max_input_tokens=32_000,
            ),
            RunContext(
                owner_generation=1,
                tool_admission_barrier=_OpenToolAdmissionBarrier(),
                model_transport_state=InMemoryModelTransportState(
                    websocket_enabled=False
                ),
                user_id="user-1",
                run_id="0" * 32,
                publish_event=_noop_publish,
            ),
        )
    ]

    pre_lower_filter = captured["pre_lower_filter"]
    auto_compaction_filter = captured["auto_compaction_filter"]
    post_lower_filter = captured["post_lower_filter"]
    assert isinstance(pre_lower_filter, EventPreLowerFilterPipeline)
    assert isinstance(auto_compaction_filter, EventAutoCompactionFilter)
    assert isinstance(post_lower_filter, PostLowerFilterPipeline)
    assert [item.__class__.__name__ for item in pre_lower_filter.filters] == [
        "EventAttachmentAvailabilityFilter",
        "EventFilePartPlaceholderFilter",
    ]
    assert [item.__class__.__name__ for item in post_lower_filter.filters] == [
        "NativeRequestSizeGuard",
    ]
    assert captured["session_repo"] is session_head_repo
    model_adapter = captured["model_adapter"]
    assert isinstance(model_adapter, OpenAIResponsesModelAdapter)
    assert isinstance(
        model_adapter.continuation_planner,
        ResponsesContinuationPlanner,
    )
    assert auto_compaction_filter.on_committing is not None
    await auto_compaction_filter.on_committing(_Session())
    assert (await store.load("agent-1", "session-1")).tool_names == []


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
    store = _ToolWorkingSetStore()
    store.states[("agent-1", "session-1")] = ToolWorkingSetState(
        tool_names=["service__probe"]
    )
    captured_prompts: dict[str, str] = {}

    async def summarize(
        *,
        provider: LLMProvider,
        provider_integration_id: str | None,
        model: str,
        credential_kwargs: dict[str, object],
        system_prompt: str,
        user_prompt: str,
        conversation_text: str,
        max_output_tokens: int,
        session_id: str | None = None,
    ) -> str:
        """Replace summary model call."""
        del (
            provider,
            provider_integration_id,
            model,
            credential_kwargs,
            max_output_tokens,
            session_id,
        )
        captured_prompts["system_prompt"] = system_prompt
        captured_prompts["user_prompt"] = user_prompt
        return f"summary::{conversation_text}"

    adapter = _agent_engine_adapter(
        session_manager=_session_context,
        tool_working_set_store=store,
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
                tool_search_enabled=False,
                auto_compaction_threshold_tokens=None,
                inference_state=None,
                compaction_provider_integration_id=None,
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
    assert (await store.load("agent-1", "session-1")).tool_names == []


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
        provider_integration_id: str | None,
        model: str,
        credential_kwargs: dict[str, object],
        system_prompt: str,
        user_prompt: str,
        conversation_text: str,
        max_output_tokens: int,
        session_id: str | None = None,
    ) -> str:
        """Return compact summary."""
        del (
            provider,
            provider_integration_id,
            model,
            credential_kwargs,
            system_prompt,
            user_prompt,
        )
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
                tool_search_enabled=False,
                auto_compaction_threshold_tokens=None,
                inference_state=None,
                compaction_provider_integration_id=None,
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
        provider_integration_id: str | None,
        model: str,
        credential_kwargs: dict[str, object],
        system_prompt: str,
        user_prompt: str,
        conversation_text: str,
        max_output_tokens: int,
        session_id: str | None = None,
    ) -> str:
        """Capture summary input."""
        del (
            provider,
            provider_integration_id,
            model,
            credential_kwargs,
            system_prompt,
            user_prompt,
        )
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
                tool_search_enabled=False,
                auto_compaction_threshold_tokens=None,
                inference_state=None,
                compaction_provider_integration_id=None,
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
    store = _ToolWorkingSetStore()
    store.states[("agent-1", "session-1")] = ToolWorkingSetState(
        tool_names=["service__probe"]
    )
    adapter = _agent_engine_adapter(
        session_manager=_session_context,
        tool_working_set_store=store,
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
            tool_search_enabled=False,
            auto_compaction_threshold_tokens=None,
            inference_state=None,
            compaction_provider_integration_id=None,
        ),
        _run_context(),
    )

    first = await anext(iterator)
    assert first.event.__class__.__name__ == "CompactionStarted"
    with pytest.raises(CompactionFailedError, match="summary model returned no text"):
        await anext(iterator)
    assert (await store.load("agent-1", "session-1")).tool_names == ["service__probe"]


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
        model_transport_state=InMemoryModelTransportState(websocket_enabled=False),
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
    tool_working_set_store: ToolWorkingSetStore | None = None,
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
    integration_repository: AsyncMock | None = None,
    xai_imagine_client_factory: XaiImagineClientFactory | None = None,
) -> AgentEngineAdapter:
    """Create AgentEngineAdapter for tests."""
    watchdog = make_test_model_stream_watchdog()
    return AgentEngineAdapter(
        session_manager=session_manager,
        tool_working_set_store=(tool_working_set_store or _ToolWorkingSetStore()),
        artifact_service=artifact_service or _ArtifactService(),
        exchange_file_service=exchange_file_service or _ExchangeFileService(),
        model_file_service=model_file_service or _ModelFileService(),
        integration_repository=integration_repository or AsyncMock(),
        xai_imagine_client_factory=(
            xai_imagine_client_factory or _xai_imagine_client_factory()
        ),
        config=config or EventEngineAdapterConfig(),
        model_stream_watchdog=watchdog,
        execution_factory=execution_factory or (lambda **kwargs: _Execution()),
        run_repo=run_repo or _RunRepo(),
        agent_session_repo=agent_session_repo or _AgentSessionRepo(),
        session_head_repo=session_head_repo or _EventSessionHeadRepo(None),
        transcript_repo=transcript_repo or _TranscriptRepo([]),
        model_file_pin_repo=_ModelFilePinRepo(),
        compactor=compactor or _Compactor(),
        summary_model_call=summary_model_call
        or functools.partial(summarize_text_with_model, watchdog=watchdog),
    )


def _events(emits: list[Emit]) -> list[object]:
    """Return emit event list."""
    return [emit.event for emit in emits]
