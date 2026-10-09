"""Bounded foreground input fitting through every supported provider lowerer."""

import asyncio
import datetime
from collections.abc import AsyncIterator, Awaitable, Callable, Sequence
from typing import Literal

import pytest

from azents.core.enums import AgentRunPhase, AgentRunStatus, EventKind, LLMProvider
from azents.core.llm_catalog import ModelCapabilities, ModelModalities, ModelModality
from azents.engine.events.execution import AgentRunExecutionRequest, PreparedModelCall
from azents.engine.events.execution_test import (
    _artifact,
    _assistant_event,
    _execution,
    _model_call_preparer,
    _Normalizer,
    _OpenToolAdmissionBarrier,
    _OutputMetadataRepository,
    _RunRepo,
    _session_context,
    _StaticOutputStream,
    _ToolExecutor,
    _TranscriptRepo,
)
from azents.engine.events.file_parts import (
    ModelFileLoweringContent,
    RequestLocalModelFileResolver,
    make_model_file_data_url,
)
from azents.engine.events.filters import NativeRequestSizeGuard
from azents.engine.events.openai_responses import (
    OpenAIResponsesLowerer,
    OpenAIResponsesRequest,
)
from azents.engine.events.protocols import NativeEvent, NormalizedAdapterOutput
from azents.engine.events.pydantic_ai_lowering import PydanticAILowerer
from azents.engine.events.pydantic_ai_types import PydanticAIRequest
from azents.engine.events.types import (
    ClientToolCallPayload,
    ClientToolResultPayload,
    CompactionSummaryPayload,
    Event,
    FileOutputPart,
)
from azents.engine.run.errors import CompactionPlanStaleError, ModelInputTooLargeError
from azents.engine.run.provider_failure import (
    ModelProviderFailure,
    ModelProviderFailureCategory,
    ModelProviderFailureRetryability,
)
from azents.engine.run.turn_action_bridge import TurnActionBridgeBoundary
from azents.testing.model_stream import make_test_model_stream_watchdog

Mode = Literal[
    "native",
    "context",
    "still_native",
    "still_context",
    "unrelated",
    "skip",
    "cancel",
    "stale",
    "no_compactor",
    "stop",
    "terminal_context",
    "still_terminal_context",
]
type Request = OpenAIResponsesRequest | PydanticAIRequest


class _ForcedCompactor:
    """Skip ordinary token compaction, recording forced recovery separately."""

    def __init__(self, mode: Mode) -> None:
        self.mode = mode
        self.was_compacted = False
        self.reasons: list[str] = []
        self.inputs: list[list[Event]] = []

    async def compact(
        self,
        transcript: Sequence[Event],
        *,
        on_started: Callable[[], Awaitable[None]] | None = None,
    ) -> list[Event]:
        """Simulate input below the automatic token threshold."""
        self.was_compacted = False
        return list(transcript)

    async def force_compact(
        self,
        transcript: Sequence[Event],
        *,
        reason: str,
        on_started: Callable[[], Awaitable[None]] | None,
    ) -> list[Event]:
        """Return the ordinary text summary without retaining image pixels."""
        self.reasons.append(reason)
        self.inputs.append(list(transcript))
        assert on_started is not None
        await on_started()
        if self.mode == "skip":
            return list(transcript)
        if self.mode == "cancel":
            raise asyncio.CancelledError
        if self.mode == "stale":
            raise CompactionPlanStaleError("Compaction plan changed.")
        self.was_compacted = True
        if self.mode == "still_native":
            return list(transcript)
        return [
            Event(
                id="2" * 32,
                session_id="session-1",
                kind=EventKind.COMPACTION_SUMMARY,
                payload=CompactionSummaryPayload(
                    compaction_id="compact-1",
                    content="Inspect the image file again if needed.",
                    covered_until_event_id=transcript[-1].id,
                ),
                created_at=datetime.datetime.now(datetime.UTC),
            )
        ]


def _provider_failure(category: ModelProviderFailureCategory) -> ModelProviderFailure:
    return ModelProviderFailure(
        operation="sampling",
        category=category,
        retryability=ModelProviderFailureRetryability.NON_RETRYABLE,
        provider_message="Synthetic provider failure",
        status_code=400,
        provider_code="context_length_exceeded"
        if category is ModelProviderFailureCategory.CONTEXT_LIMIT
        else "invalid_request",
        provider_error_type=None,
        provider_error_param=None,
        retry_hint_seconds=None,
        provider="test",
        integration=None,
        model="selected-model",
    )


class _Adapter:
    """Record physical sends and optionally reject the provider input window."""

    def __init__(self, mode: Mode) -> None:
        self.mode = mode
        self.requests: list[Request] = []
        self.closed = False

    async def stream(
        self, request: Request, **kwargs: object
    ) -> AsyncIterator[NativeEvent]:
        self.requests.append(request)
        if self.mode == "unrelated":
            raise _provider_failure(ModelProviderFailureCategory.INVALID_REQUEST)
        if self.mode == "still_context" or (
            self.mode == "context" and len(self.requests) == 1
        ):
            raise _provider_failure(ModelProviderFailureCategory.CONTEXT_LIMIT)
        yield NativeEvent(type="done", item={})

    async def close(self) -> None:
        self.closed = True


class _TerminalContextStream(_StaticOutputStream):
    """Provider error classified only when terminal normalization completes."""

    def complete(self) -> NormalizedAdapterOutput:
        raise _provider_failure(ModelProviderFailureCategory.CONTEXT_LIMIT)


class _TerminalContextNormalizer(_Normalizer):
    """Exercise response.failed errors raised after the iterator has ended."""

    def __init__(self, mode: Mode) -> None:
        super().__init__([_assistant_event()])
        self.mode = mode
        self.starts = 0

    def start(self, session_id: str) -> _StaticOutputStream:
        self.starts += 1
        if self.mode == "still_terminal_context" or (
            self.mode == "terminal_context" and self.starts == 1
        ):
            return _TerminalContextStream(
                NormalizedAdapterOutput(needs_follow_up=False)
            )
        return super().start(session_id)


@pytest.mark.parametrize("provider", list(LLMProvider))
@pytest.mark.parametrize(
    "mode",
    [
        "native",
        "context",
        "still_native",
        "still_context",
        "unrelated",
        "skip",
        "cancel",
        "stale",
        "no_compactor",
        "stop",
        "terminal_context",
        "still_terminal_context",
    ],
)
async def test_overflow_recovery_through_every_lowerer(
    provider: LLMProvider, mode: Mode
) -> None:
    """Recover once in the same turn; terminate persistent or unrelated failures."""
    resolver = RequestLocalModelFileResolver()
    resolver.put(
        model_file_id="image-1",
        content=ModelFileLoweringContent(
            data_url=make_model_file_data_url(
                media_type="image/png", body=b"image" * 4_000
            ),
        ),
    )
    capabilities = ModelCapabilities(
        modalities=ModelModalities(
            input=[ModelModality.TEXT, ModelModality.IMAGE], output=[ModelModality.TEXT]
        ),
    )
    lowerer = (
        OpenAIResponsesLowerer(
            top_k=None,
            provider=provider.value,
            provider_id=provider,
            model="selected-model",
            supported_execution_options=(),
            enabled_execution_options=(),
            model_capabilities=capabilities,
            model_file_resolver=resolver,
        )
        if provider in {LLMProvider.OPENAI, LLMProvider.CHATGPT_OAUTH}
        else PydanticAILowerer(
            top_k=None,
            provider=provider.value,
            provider_id=provider,
            model="selected-model",
            tools=[],
            model_capabilities=capabilities,
            model_file_resolver=resolver,
            supported_execution_options=(),
            enabled_execution_options=(),
        )
    )
    repository = _TranscriptRepo()
    repository.events.extend(
        [
            Event(
                id="0" * 32,
                session_id="session-1",
                kind=EventKind.CLIENT_TOOL_CALL,
                payload=ClientToolCallPayload(
                    call_id="image-read",
                    name="read_image",
                    arguments='{"path": "/image.png"}',
                    wire_dialect="json_function",
                    native_artifact=_artifact(),
                ),
                created_at=datetime.datetime.now(datetime.UTC),
            ),
            Event(
                id="1" * 32,
                session_id="session-1",
                kind=EventKind.CLIENT_TOOL_RESULT,
                payload=ClientToolResultPayload(
                    call_id="image-read",
                    name="read_image",
                    status="completed",
                    wire_dialect="json_function",
                    output=[
                        FileOutputPart(
                            model_file_id="image-1", media_type="image/png", size=20_000
                        )
                    ],
                ),
                created_at=datetime.datetime.now(datetime.UTC),
            ),
        ]
    )
    tool_executor = _ToolExecutor()
    preparer = _model_call_preparer(tool_executor=tool_executor)
    lowered: list[Request] = []
    ends: list[str] = []

    async def on_end(
        reason: Literal["completed", "error", "cancelled", "unknown"],
    ) -> None:
        ends.append(reason)

    async def prepare(
        *, transcript: Sequence[Event], model: str
    ) -> PreparedModelCall[Request]:
        base = await preparer(transcript=transcript, model=model)
        native = lowerer.lower(
            transcript,
            model=model,
            native_replay_context=None,
            system_prompt="Inspect images.",
        )
        lowered.append(native)
        return PreparedModelCall(
            native_request=native,
            inference_state=base.inference_state,
            system_prompt_analysis=base.system_prompt_analysis,
            tool_executor=base.tool_executor,
            on_turn_end=on_end,
            enrich_client_tool_call=base.enrich_client_tool_call,
        )

    compactor = _ForcedCompactor(mode)
    adapter = _Adapter(mode)
    run_repo = _RunRepo()
    execution = _execution(
        session_manager=_session_context,
        input_projection_repository=None,
        terminal_finalization_repository=None,
        metadata_repository=_OutputMetadataRepository(failure=None),
        model_operation_completion=None,
        post_lower_filter=NativeRequestSizeGuard[Request](
            max_input_chars=1_000_000
            if mode
            in {
                "context",
                "still_context",
                "unrelated",
                "terminal_context",
                "still_terminal_context",
            }
            else 2_000
        ),
        model_adapter=adapter,
        model_stream_watchdog=make_test_model_stream_watchdog(),
        model_stream_provider=provider.value,
        model_stream_provider_integration_id=None,
        model_stream_inference_profile=None,
        output_normalizer=_TerminalContextNormalizer(mode),
        model_call_preparer=prepare,
        auto_compaction_filter=None if mode == "no_compactor" else compactor,
        run_repo=run_repo,
        transcript_repo=repository,
    )
    request = AgentRunExecutionRequest(
        owner_generation=1,
        tool_admission_barrier=_OpenToolAdmissionBarrier(),
        turn_action_bridge_boundary=TurnActionBridgeBoundary(),
        run_id="run-1",
        session_id="session-1",
        model="selected-model",
        max_turns=1,
    )
    stop_checks = 0

    async def check_stop() -> bool:
        nonlocal stop_checks
        stop_checks += 1
        return mode == "stop" and stop_checks > 1

    if mode in {"cancel", "stale"}:
        failure = (
            asyncio.CancelledError if mode == "cancel" else CompactionPlanStaleError
        )
        with pytest.raises(failure):
            await execution.run(request)
        assert len(lowered) == 1
        assert ends == ["error"]
    elif mode == "stop":
        assert (
            await execution.run(request, check_stop=check_stop)
            == AgentRunStatus.INTERRUPTED
        )
        assert not compactor.reasons
        assert len(lowered) == 1
        assert ends == ["error"]
    elif mode in {"skip", "no_compactor"}:
        with pytest.raises(ModelInputTooLargeError):
            await execution.run(request)
        assert len(lowered) == 1
        assert ends == ["error"]
    elif mode in {"still_native", "still_context", "still_terminal_context"}:
        with pytest.raises(ModelInputTooLargeError) as caught:
            await execution.run(request)
        assert caught.value.failure_code == "model_input_too_large"
        assert ends == ["error", "error"]
    elif mode == "unrelated":
        with pytest.raises(ModelProviderFailure):
            await execution.run(request)
        assert not compactor.reasons
        assert len(lowered) == 1
        assert ends == ["error"]
    else:
        assert await execution.run(request) == AgentRunStatus.COMPLETED
        assert ends == ["error", "completed"]
        assert lowered[1].native_request_input_chars() < 2_000
    if mode not in {"unrelated", "no_compactor", "stop"}:
        assert compactor.reasons == [
            "native_request_size_exceeded"
            if mode
            not in {
                "context",
                "still_context",
                "terminal_context",
                "still_terminal_context",
            }
            else "provider_context_limit"
        ]
        if mode not in {"skip", "cancel", "stale"}:
            assert len(lowered) == 2
        assert compactor.inputs[0][-1].id == "1" * 32
        assert run_repo.phases.count(AgentRunPhase.COMPACTING) == 1
    assert (
        len(adapter.requests)
        == {
            "native": 1,
            "context": 2,
            "still_native": 0,
            "still_context": 2,
            "unrelated": 1,
            "skip": 0,
            "cancel": 0,
            "stale": 0,
            "no_compactor": 0,
            "stop": 0,
            "terminal_context": 2,
            "still_terminal_context": 2,
        }[mode]
    )
    assert adapter.closed
    assert tool_executor.executed_calls == []
