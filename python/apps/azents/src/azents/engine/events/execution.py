"""Azents-owned event ReAct loop."""

import asyncio
import datetime
import itertools
import logging
from collections.abc import Awaitable, Callable, Iterable, Sequence
from dataclasses import dataclass
from typing import Literal, Protocol

from sqlalchemy.ext.asyncio import AsyncSession

from azents.core.enums import AgentRunPhase, AgentRunStatus, EventKind
from azents.engine.events.model_file_refs import unique_model_file_ids
from azents.engine.events.protocols import (
    AdapterLowerer,
    AdapterOutputNormalizer,
    ClientToolExecutor,
    ModelAdapter,
    NativeEvent,
    NativeModelRequest,
    NormalizedAdapterOutput,
    OutputSink,
    PostLowerFilter,
    PreLowerFilter,
    RunStateRepository,
    SessionHeadRepository,
    TranscriptRepository,
)
from azents.engine.events.types import (
    ActiveToolCall,
    AssistantMessagePayload,
    ClientToolCallPayload,
    ClientToolResultPayload,
    Event,
    OutputTextPart,
    ProviderToolCallPayload,
    ProviderToolResultPayload,
    ReasoningPayload,
    RunMarkerPayload,
    SystemPromptAnalysisPayload,
    TokenUsagePayload,
    TurnMarkerPayload,
    UnknownAdapterOutputPayload,
)
from azents.engine.run.errors import ModelCallError, UserVisibleRuntimeError
from azents.engine.run.types import USER_STOP_CANCEL_MESSAGE
from azents.repos.agent_execution import (
    AgentRunRepository,
    EventTranscriptRepository,
)
from azents.repos.agent_execution.data import EventCreate

logger = logging.getLogger(__name__)


CheckStop = Callable[[], Awaitable[bool]]
PhaseSink = Callable[[AgentRunPhase], Awaitable[None]]
InputPoller = Callable[[AsyncSession, str], Awaitable[list[Event]]]


class PreModelLowerHook(Protocol):
    """Request-local preparation hook before model lowering."""

    async def __call__(
        self,
        *,
        transcript: Sequence[Event],
    ) -> object:
        """Prepare request-local state required by native lowerer."""
        ...


class ModelFilePinRepositoryProtocol(Protocol):
    """ModelFile active run pin repository protocol."""

    async def pin_many(
        self,
        session: AsyncSession,
        *,
        session_id: str,
        run_id: str,
        model_file_ids: Sequence[str],
    ) -> None:
        """Pin ModelFiles for an active run."""
        ...

    async def release_run(self, session: AsyncSession, *, run_id: str) -> None:
        """Release ModelFile pins for a run."""
        ...


@dataclass(frozen=True)
class AgentRunExecutionRequest:
    """Agent run execution request."""

    run_id: str
    session_id: str
    model: str
    run_index: int = 1
    system_prompt: str | None = None
    system_prompt_analysis: SystemPromptAnalysisPayload | None = None
    max_turns: int | None = None


class _ModelStreamUserInterrupted(Exception):
    """Indicates model stream was interrupted by user stop."""

    def __init__(self, native_events: Sequence[NativeEvent]) -> None:
        super().__init__(USER_STOP_CANCEL_MESSAGE)
        self.native_events = list(native_events)


class _ToolExecutionUserInterrupted(Exception):
    """Indicates tool execution was interrupted by user stop."""


class AgentRunExecution:
    """ReAct loop based on event transcript."""

    def __init__(
        self,
        *,
        lowerer: AdapterLowerer,
        post_lower_filter: PostLowerFilter,
        model_adapter: ModelAdapter,
        output_normalizer: AdapterOutputNormalizer,
        tool_executor: ClientToolExecutor,
        pre_lower_filter: PreLowerFilter | None = None,
        output_sink: OutputSink | None = None,
        phase_sink: PhaseSink | None = None,
        pre_model_lower_hook: PreModelLowerHook | None = None,
        model_file_pin_repo: ModelFilePinRepositoryProtocol | None = None,
        run_repo: RunStateRepository | None = None,
        transcript_repo: TranscriptRepository | None = None,
        session_repo: SessionHeadRepository | None = None,
    ) -> None:
        """Inject loop dependencies."""
        self._lowerer = lowerer
        self._post_lower_filter = post_lower_filter
        self._model_adapter = model_adapter
        self._output_normalizer = output_normalizer
        self._tool_executor = tool_executor
        self._pre_lower_filter = pre_lower_filter
        self._output_sink = output_sink
        self._phase_sink = phase_sink
        self._pre_model_lower_hook = pre_model_lower_hook
        self._model_file_pin_repo = model_file_pin_repo
        self._run_repo = run_repo or AgentRunRepository()
        self._transcript_repo = transcript_repo or EventTranscriptRepository()
        self._session_repo = session_repo

    async def run(
        self,
        session: AsyncSession,
        request: AgentRunExecutionRequest,
        *,
        check_stop: CheckStop | None = None,
        poll_input_events: InputPoller | None = None,
    ) -> AgentRunStatus:
        """Run until terminal state."""
        try:
            for _turn in _turn_range(request.max_turns):
                if await _stopped(check_stop):
                    await self._mark_terminal(
                        session,
                        request.run_id,
                        AgentRunStatus.INTERRUPTED,
                    )
                    await session.commit()
                    return AgentRunStatus.INTERRUPTED

                if poll_input_events is not None:
                    polled_events = await poll_input_events(
                        session,
                        request.session_id,
                    )
                    if polled_events:
                        await session.commit()

                head_event_id = await self._model_input_head_event_id(
                    session,
                    request.session_id,
                )
                transcript = await self._transcript_repo.list_for_model_input(
                    session,
                    request.session_id,
                    head_event_id=head_event_id,
                )
                repaired_events = await self._append_missing_tool_results(
                    session,
                    request,
                    transcript,
                )
                if repaired_events:
                    await session.commit()
                    transcript = await self._transcript_repo.list_for_model_input(
                        session,
                        request.session_id,
                        head_event_id=head_event_id,
                    )
                await self._update_phase(
                    session,
                    request.run_id,
                    AgentRunPhase.PREPARING_INPUT,
                )
                compacted = False
                if self._pre_lower_filter is not None:
                    transcript = await self._pre_lower_filter.apply(session, transcript)
                    compacted = self._pre_lower_filter.was_compacted
                if compacted:
                    await session.commit()
                if self._model_file_pin_repo is not None:
                    await self._model_file_pin_repo.pin_many(
                        session,
                        session_id=request.session_id,
                        run_id=request.run_id,
                        model_file_ids=unique_model_file_ids(transcript),
                    )
                    await session.commit()
                if self._pre_model_lower_hook is not None:
                    await self._pre_model_lower_hook(transcript=transcript)
                native_request = self._lowerer.lower(
                    _without_existing_terminal_run_markers(transcript)
                    if compacted
                    else transcript,
                    model=request.model,
                    system_prompt=request.system_prompt,
                )
                native_request = self._post_lower_filter.apply(native_request)

                await self._update_phase(
                    session,
                    request.run_id,
                    AgentRunPhase.WAITING_FOR_MODEL,
                )
                await session.commit()
                try:
                    native_events = await self._stream_model(
                        session,
                        request.run_id,
                        native_request,
                    )
                except _ModelStreamUserInterrupted as exc:
                    return await self._complete_user_interrupted_model_stream(
                        session,
                        request,
                        exc.native_events,
                    )

                await self._update_phase(
                    session,
                    request.run_id,
                    AgentRunPhase.NORMALIZING_OUTPUT,
                )
                normalized = self._output_normalizer.normalize(
                    request.session_id,
                    native_events,
                )

                await self._update_phase(
                    session,
                    request.run_id,
                    AgentRunPhase.APPENDING_EVENTS,
                )
                if not _has_durable_model_output(normalized.events):
                    raise ModelCallError("Model completed without assistant output.")
                appended = await self._append_events(session, normalized.events)
                turn_marker = await self._append_turn_marker(
                    session,
                    request.session_id,
                    request.run_id,
                    normalized.usage,
                    system_prompt=request.system_prompt_analysis,
                )
                turn_events = [turn_marker] if turn_marker is not None else []
                client_tool_calls = [
                    event.payload
                    for event in appended
                    if isinstance(event.payload, ClientToolCallPayload)
                ]
                if not client_tool_calls:
                    run_marker = await self._append_run_marker(
                        session,
                        request.session_id,
                        request.run_id,
                        "completed",
                    )
                    await self._mark_terminal(
                        session,
                        request.run_id,
                        AgentRunStatus.COMPLETED,
                    )
                    await session.commit()
                    if self._output_sink is not None:
                        await self._output_sink(
                            normalized,
                            [*appended, *turn_events, run_marker],
                        )
                    return AgentRunStatus.COMPLETED

                await session.commit()
                if self._output_sink is not None:
                    await self._output_sink(normalized, [*appended, *turn_events])
                try:
                    await self._execute_tools(
                        session,
                        request.run_id,
                        request.session_id,
                        client_tool_calls,
                    )
                except _ToolExecutionUserInterrupted:
                    run_marker = await self._append_run_marker(
                        session,
                        request.session_id,
                        request.run_id,
                        "interrupted",
                    )
                    await self._mark_terminal(
                        session,
                        request.run_id,
                        AgentRunStatus.INTERRUPTED,
                    )
                    await session.commit()
                    if self._output_sink is not None:
                        await self._output_sink(
                            NormalizedAdapterOutput(events=[]),
                            [run_marker],
                        )
                    return AgentRunStatus.INTERRUPTED
        except UserVisibleRuntimeError:
            raise

        await self._append_run_marker(
            session,
            request.session_id,
            request.run_id,
            "interrupted",
        )
        await self._mark_terminal(session, request.run_id, AgentRunStatus.INTERRUPTED)
        await session.commit()
        return AgentRunStatus.INTERRUPTED

    async def _stream_model(
        self,
        session: AsyncSession,
        run_id: str,
        native_request: NativeModelRequest,
    ) -> list[NativeEvent]:
        """Collect model stream."""
        await self._update_phase(
            session,
            run_id,
            AgentRunPhase.STREAMING_MODEL,
        )
        await session.commit()
        events: list[NativeEvent] = []
        try:
            async for event in self._model_adapter.stream(native_request):
                events.append(event)
        except asyncio.CancelledError as exc:
            if _is_user_stop_cancellation(exc):
                raise _ModelStreamUserInterrupted(events) from exc
            raise
        return events

    async def _complete_user_interrupted_model_stream(
        self,
        session: AsyncSession,
        request: AgentRunExecutionRequest,
        native_events: Sequence[NativeEvent],
    ) -> AgentRunStatus:
        """Durabilize partial text from model stream interrupted by user stop."""
        await self._update_phase(
            session,
            request.run_id,
            AgentRunPhase.APPENDING_EVENTS,
        )
        normalized = self._output_normalizer.normalize(
            request.session_id,
            native_events,
        )
        assistant_events = [
            event
            for event in normalized.events
            if event.kind == EventKind.ASSISTANT_MESSAGE
            and isinstance(event.payload, AssistantMessagePayload)
            and _assistant_content_is_non_empty(event.payload.content)
        ]
        appended = await self._append_events(session, assistant_events)
        run_marker = await self._append_run_marker(
            session,
            request.session_id,
            request.run_id,
            "interrupted",
        )
        await self._mark_terminal(
            session,
            request.run_id,
            AgentRunStatus.INTERRUPTED,
        )
        await session.commit()
        if self._output_sink is not None:
            await self._output_sink(
                NormalizedAdapterOutput(events=assistant_events),
                [*appended, run_marker],
            )
        return AgentRunStatus.INTERRUPTED

    async def _append_events(
        self,
        session: AsyncSession,
        events: Sequence[Event],
    ) -> list[Event]:
        """Append events to durable transcript."""
        appended: list[Event] = []
        for event in events:
            appended.append(
                await self._transcript_repo.append(
                    session,
                    EventCreate(
                        session_id=event.session_id,
                        kind=event.kind,
                        payload=event.payload.model_dump(
                            mode="json",
                            exclude_none=True,
                        ),
                        external_id=event.external_id,
                        adapter=event.adapter,
                        provider=event.provider,
                        model=event.model,
                        native_format=event.native_format,
                        schema_version=event.schema_version,
                    ),
                )
            )
        return appended

    async def _execute_tools(
        self,
        session: AsyncSession,
        run_id: str,
        session_id: str,
        tool_calls: Sequence[ClientToolCallPayload],
    ) -> None:
        """Run foreground client tool calls in parallel and append results."""
        active_calls = [
            _active_tool_call(call, background=False) for call in tool_calls
        ]
        await self._update_phase(
            session,
            run_id,
            AgentRunPhase.EXECUTING_TOOLS,
            active_tool_calls=active_calls,
        )
        await session.commit()
        try:
            results = await asyncio.gather(
                *(self._execute_tool_safely(call) for call in tool_calls)
            )
        except asyncio.CancelledError as exc:
            if not _is_user_stop_cancellation(exc):
                raise
            for call in tool_calls:
                self._tool_executor.request_cancel(call)
            await self._append_cancelled_tool_results(
                session,
                session_id,
                tool_calls,
            )
            await self._update_phase(
                session,
                run_id,
                AgentRunPhase.STOPPING,
                active_tool_calls=[],
            )
            await session.commit()
            raise _ToolExecutionUserInterrupted from exc
        appended: list[Event] = []
        for result in results:
            appended.append(
                await self._transcript_repo.append(
                    session,
                    EventCreate(
                        session_id=session_id,
                        kind=EventKind.CLIENT_TOOL_RESULT,
                        payload=result.model_dump(mode="json", exclude_none=True),
                    ),
                )
            )
        await self._update_phase(
            session,
            run_id,
            AgentRunPhase.APPENDING_EVENTS,
            active_tool_calls=[],
        )
        await session.commit()
        if self._output_sink is not None:
            await self._output_sink(NormalizedAdapterOutput(events=[]), appended)

    async def _append_missing_tool_results(
        self,
        session: AsyncSession,
        request: AgentRunExecutionRequest,
        transcript: Sequence[Event],
    ) -> list[Event]:
        """Repair orphan tool calls absent from state with cancelled results."""
        unresolved_calls = _unresolved_client_tool_calls(transcript)
        if not unresolved_calls:
            return []

        run_state = await self._run_repo.get_by_id(session, request.run_id)
        active_call_ids = (
            {active.call_id for active in run_state.active_tool_calls}
            if run_state is not None
            else set()
        )
        orphan_calls = [
            call for call in unresolved_calls if call.call_id not in active_call_ids
        ]
        return await self._append_cancelled_tool_results(
            session,
            request.session_id,
            orphan_calls,
        )

    async def _append_cancelled_tool_results(
        self,
        session: AsyncSession,
        session_id: str,
        tool_calls: Sequence[ClientToolCallPayload],
    ) -> list[Event]:
        """Append tool call as cancelled event result."""
        appended: list[Event] = []
        for call in tool_calls:
            payload = ClientToolResultPayload(
                call_id=call.call_id,
                name=call.name,
                status="cancelled",
                output=[
                    OutputTextPart(
                        text=(
                            "Tool execution was cancelled before a result was recorded."
                        ),
                    )
                ],
            )
            external_id = f"tool-result:{call.call_id}:cancelled"
            existing = await self._transcript_repo.get_by_external_id(
                session,
                session_id,
                external_id,
            )
            if existing is not None:
                appended.append(existing)
                continue
            appended.append(
                await self._transcript_repo.append(
                    session,
                    EventCreate(
                        session_id=session_id,
                        kind=EventKind.CLIENT_TOOL_RESULT,
                        payload=payload.model_dump(mode="json", exclude_none=True),
                        external_id=external_id,
                    ),
                )
            )
        if appended and self._output_sink is not None:
            await self._output_sink(NormalizedAdapterOutput(events=[]), appended)
        return appended

    async def _model_input_head_event_id(
        self,
        session: AsyncSession,
        session_id: str,
    ) -> str | None:
        """Fetch model input head of event session."""
        if self._session_repo is None:
            return None
        state = await self._session_repo.get_by_id(session, session_id)
        if state is None:
            return None
        return state.model_input_head_event_id

    async def _execute_tool_safely(
        self,
        call: ClientToolCallPayload,
    ) -> ClientToolResultPayload:
        """Repair tool exception as failed tool result."""
        try:
            return await self._tool_executor.execute(call)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.exception(
                "Client tool execution failed",
                extra={
                    "call_id": call.call_id,
                    "tool_name": call.name,
                    "error_type": exc.__class__.__name__,
                },
            )
            return ClientToolResultPayload(
                call_id=call.call_id,
                name=call.name,
                status="failed",
                output=[
                    OutputTextPart(
                        text=f"Tool execution failed: {exc.__class__.__name__}",
                    )
                ],
            )

    async def _append_run_marker(
        self,
        session: AsyncSession,
        session_id: str,
        run_id: str,
        status: Literal["completed", "stopped", "failed", "interrupted"],
    ) -> Event:
        """Append run marker."""
        external_id = f"run-marker:{run_id}:{status}"
        existing = await self._transcript_repo.get_by_external_id(
            session,
            session_id,
            external_id,
        )
        if existing is not None:
            return existing
        return await self._transcript_repo.append(
            session,
            EventCreate(
                session_id=session_id,
                kind=EventKind.RUN_MARKER,
                payload=RunMarkerPayload(
                    run_id=run_id,
                    status=status,
                ).model_dump(mode="json", exclude_none=True),
                external_id=external_id,
            ),
        )

    async def _append_turn_marker(
        self,
        session: AsyncSession,
        session_id: str,
        run_id: str,
        usage: TokenUsagePayload | None,
        *,
        system_prompt: SystemPromptAnalysisPayload | None = None,
    ) -> Event | None:
        """Append turn marker."""
        if usage is None:
            return None
        return await self._transcript_repo.append(
            session,
            EventCreate(
                session_id=session_id,
                kind=EventKind.TURN_MARKER,
                payload=TurnMarkerPayload(
                    run_id=run_id,
                    usage=usage,
                    system_prompt=system_prompt,
                ).model_dump(mode="json", exclude_none=True),
            ),
        )

    async def _mark_terminal(
        self,
        session: AsyncSession,
        run_id: str,
        status: AgentRunStatus,
    ) -> None:
        """Record run terminal state."""
        await self._run_repo.mark_terminal(
            session,
            run_id,
            status,
            ended_at=datetime.datetime.now(datetime.UTC),
        )
        if self._model_file_pin_repo is not None:
            await self._model_file_pin_repo.release_run(session, run_id=run_id)

    async def _update_phase(
        self,
        session: AsyncSession,
        run_id: str,
        phase: AgentRunPhase,
        *,
        active_tool_calls: list[ActiveToolCall] | None = None,
    ) -> None:
        """Reflect run phase in durable state and UI projection."""
        await self._run_repo.update_phase(
            session,
            run_id,
            phase,
            active_tool_calls=active_tool_calls,
        )
        if self._phase_sink is not None:
            await self._phase_sink(phase)


def _turn_range(max_turns: int | None) -> Iterable[int]:
    """Return unbounded turn iterator when max_turns is None."""
    if max_turns is None:
        return itertools.count()
    return range(max_turns)


def _is_user_stop_cancellation(exc: asyncio.CancelledError) -> bool:
    """Check whether CancelledError is user stop cancellation."""
    return any(arg == USER_STOP_CANCEL_MESSAGE for arg in exc.args)


def _has_durable_model_output(events: Sequence[Event]) -> bool:
    """Check whether model turn contains at least one durable output."""
    for event in events:
        match event.payload:
            case AssistantMessagePayload(content=content):
                if _assistant_content_is_non_empty(content):
                    return True
            case ReasoningPayload(text=text, summary=summary):
                if text or summary:
                    return True
            case (
                ClientToolCallPayload()
                | ProviderToolCallPayload()
                | ProviderToolResultPayload()
                | UnknownAdapterOutputPayload()
            ):
                return True
            case _:
                pass
    return False


def _assistant_content_is_non_empty(content: object) -> bool:
    """Check whether assistant content contains text to durabilize."""
    if isinstance(content, str):
        return bool(content.strip())
    if isinstance(content, Sequence):
        return bool(content)
    return False


def _active_tool_call(
    call: ClientToolCallPayload,
    *,
    background: bool,
) -> ActiveToolCall:
    """Create active tool call projection."""
    return ActiveToolCall(
        call_id=call.call_id,
        name=call.name,
        arguments=call.arguments,
        started_at=datetime.datetime.now(datetime.UTC),
        background=background,
    )


async def _stopped(check_stop: CheckStop | None) -> bool:
    """Check whether stop was requested."""
    if check_stop is None:
        return False
    return await check_stop()


def _without_existing_terminal_run_markers(
    transcript: Sequence[Event],
) -> list[Event]:
    """Exclude past terminal run markers from resume input after compaction."""
    return [
        event for event in transcript if not isinstance(event.payload, RunMarkerPayload)
    ]


def _unresolved_client_tool_calls(
    transcript: Sequence[Event],
) -> list[ClientToolCallPayload]:
    """Return client tool calls that do not yet have results in transcript."""
    pending: dict[str, ClientToolCallPayload] = {}
    for event in transcript:
        payload = event.payload
        if isinstance(payload, ClientToolCallPayload):
            pending[payload.call_id] = payload
        elif isinstance(payload, ClientToolResultPayload):
            pending.pop(payload.call_id, None)
    return list(pending.values())
