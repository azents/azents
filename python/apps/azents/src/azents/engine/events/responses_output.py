"""Shared provider-native Responses output normalization."""

import datetime
from collections.abc import Sequence
from typing import ClassVar, Literal

from azcommon.uuid import uuid7

from azents.core.enums import EventKind
from azents.engine.events.protocols import (
    CompletedAdapterOutput,
    ContentDeltaProjection,
    FunctionCallDeltaProjection,
    NativeEvent,
    NormalizedAdapterOutput,
    ReasoningDeltaProjection,
    StreamProjection,
)
from azents.engine.events.provider_output import pending_image_generation_output
from azents.engine.events.provider_tool_activity import (
    ProviderToolActivityAccumulator,
    ProviderToolObservation,
)
from azents.engine.events.provider_tool_semantics import (
    RESPONSES_PROVIDER_TOOL_SPECS,
    normalize_responses_provider_tool_item,
)
from azents.engine.events.responses_continuation import sanitize_responses_native_item
from azents.engine.events.types import (
    AssistantMessagePayload,
    ClientToolCallPayload,
    Event,
    EventPayload,
    NativeArtifact,
    OutputTextPart,
    ProviderToolCallPayload,
    ReasoningPayload,
    TokenUsagePayload,
    UnknownAdapterOutputPayload,
    build_native_compat_key,
)
from azents.engine.run.errors import ModelStreamCallKind
from azents.engine.run.provider_failure import (
    ModelProviderFailure,
    ModelProviderFailureCategory,
    model_provider_failure,
)


class ResponsesOutputNormalizer:
    """Normalize provider-native Responses output to canonical events."""

    adapter: ClassVar[str]
    native_format = "responses"
    schema_version = "1"

    def __init__(
        self,
        *,
        provider: str,
        model: str,
        operation: ModelStreamCallKind,
        integration: str | None,
    ) -> None:
        """Set normalizer origin and provider-failure context."""
        self.provider: str = provider
        self.model: str = model
        self.operation: ModelStreamCallKind = operation
        self.integration: str | None = integration
        self.compat_key = build_native_compat_key(
            adapter=self.adapter,
            native_format=self.native_format,
            provider=provider,
            model=model,
            schema_version=self.schema_version,
        )

    def start(self, session_id: str) -> "_ResponsesOutputStream":
        """Start incremental normalization for one native model stream."""
        return _ResponsesOutputStream(self, session_id)

    def normalize(
        self,
        session_id: str,
        native_events: Sequence[NativeEvent],
    ) -> NormalizedAdapterOutput:
        """Normalize a completed native event sequence for direct callers."""
        output_stream = self.start(session_id)
        projections: list[StreamProjection] = []
        for native_event in native_events:
            projections.extend(output_stream.process_event(native_event).projections)
        completed = output_stream.complete()
        return completed.model_copy(update={"projections": projections})

    def normalize_completed(
        self,
        session_id: str,
        response: dict[str, object],
        completed_output_items: Sequence[dict[str, object]],
    ) -> list[Event]:
        """Convert completed response output item to event."""
        return self.normalize_completed_output(
            session_id,
            response,
            completed_output_items,
        ).events

    def normalize_completed_output(
        self,
        session_id: str,
        response: dict[str, object],
        completed_output_items: Sequence[dict[str, object]],
    ) -> CompletedAdapterOutput:
        """Convert completed items to canonical events and transient files."""
        output = response.get("output")
        output_items: Sequence[object] = (
            output if isinstance(output, list) and output else completed_output_items
        )
        events = self.normalize_output_items(session_id, output_items)
        pending_provider_files = [
            pending_image_generation_output(raw_item, output_index=output_index)
            for output_index, output_item in enumerate(output_items)
            if (raw_item := response_item_dict(output_item)).get("type")
            == "image_generation_call"
        ]
        return CompletedAdapterOutput(
            events=events,
            pending_provider_files=pending_provider_files,
        )

    def normalize_output_items(
        self,
        session_id: str,
        output_items: Sequence[object],
    ) -> list[Event]:
        """Convert output item list to events."""
        events: list[Event] = []
        for fallback_output_index, output_item in enumerate(output_items):
            raw_item = response_item_dict(output_item)
            if has_response_output_item_type(raw_item):
                output_index = _int_or_none(raw_item.get("output_index"))
                events.append(
                    self.normalize_output_item(
                        session_id,
                        raw_item,
                        output_index=(
                            output_index
                            if output_index is not None
                            else fallback_output_index
                        ),
                    )
                )
        return events

    def normalize_output_item(
        self,
        session_id: str,
        output_item: dict[str, object],
        *,
        output_index: int,
    ) -> Event:
        """Convert one output item to event."""
        item_type = str(output_item.get("type") or "")
        artifact = self._artifact(output_item, output_index=output_index)

        if item_type == "message":
            payload = AssistantMessagePayload(
                content=_extract_message_text(output_item),
                attachments=[],
                native_artifact=artifact,
            )
            return _event(session_id, EventKind.ASSISTANT_MESSAGE, payload)
        if item_type == "reasoning":
            payload = ReasoningPayload(
                text=_extract_reasoning_part_text(output_item, "content") or None,
                summary=_extract_reasoning_part_text(output_item, "summary") or None,
                native_artifact=artifact,
            )
            return _event(session_id, EventKind.REASONING, payload)
        if item_type == "function_call":
            payload = ClientToolCallPayload(
                call_id=str(output_item.get("call_id") or output_item.get("id") or ""),
                name=str(output_item.get("name") or ""),
                arguments=str(output_item.get("arguments") or ""),
                wire_dialect="json_function",
                native_artifact=artifact,
            )
            return _event(session_id, EventKind.CLIENT_TOOL_CALL, payload)
        if item_type == "custom_tool_call":
            call_id = output_item.get("call_id") or output_item.get("id")
            name = output_item.get("name")
            input_value = output_item.get("input")
            if not (
                isinstance(call_id, str)
                and call_id
                and isinstance(name, str)
                and name
                and isinstance(input_value, str)
            ):
                return _event(
                    session_id,
                    EventKind.UNKNOWN_ADAPTER_OUTPUT,
                    UnknownAdapterOutputPayload(
                        native_artifact=artifact,
                        reason="custom_tool_call:invalid",
                    ),
                )
            payload = ClientToolCallPayload(
                call_id=call_id,
                name=name,
                arguments=input_value,
                wire_dialect="plaintext_custom",
                native_artifact=artifact,
            )
            return _event(session_id, EventKind.CLIENT_TOOL_CALL, payload)
        provider_tool = normalize_responses_provider_tool_item(output_item)
        if provider_tool is not None:
            call_id = str(output_item.get("call_id") or output_item.get("id") or "")
            if not call_id:
                return _event(
                    session_id,
                    EventKind.UNKNOWN_ADAPTER_OUTPUT,
                    UnknownAdapterOutputPayload(
                        native_artifact=artifact,
                        reason=f"{item_type}:missing_call_id",
                    ),
                )
            call_payload = ProviderToolCallPayload(
                call_id=call_id,
                name=provider_tool.name,
                status=_canonical_provider_tool_status(output_item.get("status")),
                semantic=provider_tool.semantic,
                native_artifact=artifact,
            )
            return _event(
                session_id,
                EventKind.PROVIDER_TOOL_CALL,
                call_payload,
            )

        return _event(
            session_id,
            EventKind.UNKNOWN_ADAPTER_OUTPUT,
            UnknownAdapterOutputPayload(
                native_artifact=artifact,
                reason=item_type or None,
            ),
        )

    def normalize_partial_assistant(self, session_id: str, text: str) -> Event:
        """Create canonical-fallback output from interrupted text deltas."""
        item: dict[str, object] = {
            "type": "message",
            "status": "incomplete",
            "content": [{"type": "output_text", "text": text}],
        }
        partial_schema_version = f"{self.schema_version}-partial"
        artifact = NativeArtifact(
            compat_key=build_native_compat_key(
                adapter=self.adapter,
                native_format=self.native_format,
                provider=self.provider,
                model=self.model,
                schema_version=partial_schema_version,
            ),
            adapter=self.adapter,
            native_format=self.native_format,
            provider=self.provider,
            model=self.model,
            schema_version=partial_schema_version,
            item=item,
        )
        return _event(
            session_id,
            EventKind.ASSISTANT_MESSAGE,
            AssistantMessagePayload(
                content=text,
                attachments=[],
                native_artifact=artifact,
            ),
        )

    def _artifact(
        self,
        item: dict[str, object],
        *,
        output_index: int,
    ) -> NativeArtifact:
        """Create native artifact with canonical output position metadata."""
        artifact_item = sanitize_responses_native_item(item)
        if item.get("type") == "reasoning":
            artifact_item["output_index"] = output_index
        return NativeArtifact(
            compat_key=self.compat_key,
            adapter=self.adapter,
            native_format=self.native_format,
            provider=self.provider,
            model=self.model,
            schema_version=self.schema_version,
            item=artifact_item,
        )


def responses_need_follow_up(
    response: dict[str, object],
    events: Sequence[Event],
) -> bool:
    """Combine standard client-tool and best-effort dialect continuation signals."""
    return response.get("end_turn") is False or any(
        isinstance(event.payload, ClientToolCallPayload) for event in events
    )


class _ResponsesOutputStream:
    """Minimal normalization state for one provider-native Responses stream."""

    def __init__(
        self,
        normalizer: ResponsesOutputNormalizer,
        session_id: str,
    ) -> None:
        self.normalizer = normalizer
        self._session_id = session_id
        self._tool_refs: dict[int, tuple[str, str]] = {}
        self._completed_output_items: list[dict[str, object]] = []
        self._completed_response: dict[str, object] | None = None
        self._completed_response_seen = False
        self._terminal_error: ModelProviderFailure | None = None
        self._usage: TokenUsagePayload | None = None
        self._partial_text: list[str] = []
        self._provider_tool_activity = ProviderToolActivityAccumulator()

    def process_event(
        self,
        native_event: NativeEvent,
    ) -> NormalizedAdapterOutput:
        """Update stream state and return projections for one native event."""
        event_type = native_event.type
        item = native_event.item
        projections: list[StreamProjection] = []
        observation = _responses_provider_tool_observation(event_type, item)
        if observation is not None:
            activity = self._provider_tool_activity.observe(observation)
            if activity is not None:
                projections.append(activity)

        if event_type in {"OutputTextDeltaEvent", "ResponseTextDeltaEvent"}:
            delta = str(item.get("delta", ""))
            self._partial_text.append(delta)
            projections.append(ContentDeltaProjection(delta=delta))
        elif event_type in {"OutputItemAddedEvent", "ResponseOutputItemAddedEvent"}:
            output_index = _int_or_none(item.get("output_index"))
            raw_item = response_item_dict(item.get("item"))
            if raw_item.get("type") == "function_call" and output_index is not None:
                call_id = str(raw_item.get("call_id") or raw_item.get("id") or "")
                name = str(raw_item.get("name") or "")
                self._tool_refs[output_index] = (call_id, name)
                projections.append(
                    FunctionCallDeltaProjection(
                        index=output_index,
                        call_id=call_id,
                        name=name,
                        delta="",
                    )
                )
        elif event_type in {"OutputItemDoneEvent", "ResponseOutputItemDoneEvent"}:
            raw_item = response_item_dict(item.get("item"))
            if has_response_output_item_type(raw_item):
                output_index = _int_or_none(item.get("output_index"))
                self._completed_output_items.append(
                    {
                        **raw_item,
                        **(
                            {"output_index": output_index}
                            if output_index is not None
                            and raw_item.get("type") == "reasoning"
                            else {}
                        ),
                    }
                )
        elif event_type in {
            "FunctionCallArgumentsDeltaEvent",
            "ResponseFunctionCallArgumentsDeltaEvent",
        }:
            output_index = _int_or_none(item.get("output_index"))
            ref_index = output_index if output_index is not None else -1
            call_id, name = self._tool_refs.get(ref_index, (None, None))
            projections.append(
                FunctionCallDeltaProjection(
                    index=ref_index,
                    call_id=call_id,
                    name=name,
                    delta=str(item.get("delta", "")),
                )
            )
        elif event_type in {
            "ReasoningSummaryTextDeltaEvent",
            "ResponseReasoningSummaryTextDeltaEvent",
        }:
            item_id = item.get("item_id")
            projections.append(
                ReasoningDeltaProjection(
                    delta=str(item.get("delta", "")),
                    item_id=item_id if isinstance(item_id, str) else None,
                    output_index=_int_or_none(item.get("output_index")),
                    summary_index=_int_or_none(item.get("summary_index")),
                )
            )
        elif event_type == "ResponseIncompleteEvent":
            self._terminal_error = _incomplete_response_model_error(
                response_item_dict(item.get("response")),
                operation=self.normalizer.operation,
                provider=self.normalizer.provider,
                model=self.normalizer.model,
                integration=self.normalizer.integration,
            )
        elif event_type == "ResponseFailedEvent":
            self._terminal_error = _failed_response_model_error(
                response_item_dict(item.get("response")),
                operation=self.normalizer.operation,
                provider=self.normalizer.provider,
                model=self.normalizer.model,
                integration=self.normalizer.integration,
            )
        elif event_type == "ResponseErrorEvent":
            self._terminal_error = _response_error_event_model_error(
                item,
                operation=self.normalizer.operation,
                provider=self.normalizer.provider,
                model=self.normalizer.model,
                integration=self.normalizer.integration,
            )
        elif event_type == "ResponseCompletedEvent":
            self._completed_response_seen = True
            self._completed_response = response_item_dict(item.get("response"))
            self._usage = (
                _normalize_response_usage(self._completed_response) or self._usage
            )

        return NormalizedAdapterOutput(
            needs_follow_up=False,
            projections=projections,
        )

    def complete(self) -> NormalizedAdapterOutput:
        """Build durable output only after explicit successful completion."""
        if self._terminal_error is not None:
            raise self._terminal_error
        if not self._completed_response_seen:
            raise model_provider_failure(
                operation=self.normalizer.operation,
                provider=self.normalizer.provider,
                model=self.normalizer.model,
                integration=self.normalizer.integration,
                provider_message="The model response stream ended before completion.",
                status_code=None,
                provider_code="stream_ended_before_completion",
                provider_error_type="response_stream_transport",
                category=ModelProviderFailureCategory.TRANSPORT,
            )
        return self._build_output()

    def _build_output(self) -> NormalizedAdapterOutput:
        """Build output from received state without validating terminal status."""
        completed = self.normalizer.normalize_completed_output(
            self._session_id,
            self._completed_response or {},
            self._completed_output_items,
        )
        return NormalizedAdapterOutput(
            needs_follow_up=responses_need_follow_up(
                self._completed_response or {},
                completed.events,
            ),
            events=completed.events,
            usage=self._usage,
            pending_provider_files=completed.pending_provider_files,
        )

    def interrupt(self) -> NormalizedAdapterOutput:
        """Build completed output plus received partial assistant text."""
        if self._terminal_error is not None:
            raise self._terminal_error
        completed = self._build_output().model_copy(update={"needs_follow_up": False})
        partial_text = "".join(self._partial_text)
        if not partial_text or _has_assistant_text(completed.events):
            return completed
        partial_event = self.normalizer.normalize_partial_assistant(
            self._session_id,
            partial_text,
        )
        return completed.model_copy(
            update={"events": [*completed.events, partial_event]}
        )


def _responses_provider_tool_observation(
    event_type: str,
    item: dict[str, object],
) -> ProviderToolObservation | None:
    """Extract one hosted-tool observation from a native Responses event."""
    if event_type in {
        "OutputItemAddedEvent",
        "ResponseOutputItemAddedEvent",
        "response.output_item.added",
    }:
        return _provider_tool_output_item_observation(
            response_item_dict(item.get("item")),
            default_status="running",
        )
    if event_type in {
        "OutputItemDoneEvent",
        "ResponseOutputItemDoneEvent",
        "response.output_item.done",
    }:
        return _provider_tool_output_item_observation(
            response_item_dict(item.get("item")),
            default_status="completed",
        )
    lifecycle: dict[
        str,
        tuple[str, Literal["running", "completed", "failed"]],
    ] = {
        "ResponseWebSearchCallInProgressEvent": ("web_search", "running"),
        "ResponseWebSearchCallSearchingEvent": ("web_search", "running"),
        "ResponseWebSearchCallCompletedEvent": ("web_search", "completed"),
        "response.web_search_call.in_progress": ("web_search", "running"),
        "response.web_search_call.searching": ("web_search", "running"),
        "response.web_search_call.completed": ("web_search", "completed"),
        "ResponseFileSearchCallInProgressEvent": ("file_search", "running"),
        "ResponseFileSearchCallSearchingEvent": ("file_search", "running"),
        "ResponseFileSearchCallCompletedEvent": ("file_search", "completed"),
        "response.file_search_call.in_progress": ("file_search", "running"),
        "response.file_search_call.searching": ("file_search", "running"),
        "response.file_search_call.completed": ("file_search", "completed"),
        "ResponseCodeInterpreterCallInProgressEvent": (
            "code_interpreter",
            "running",
        ),
        "ResponseCodeInterpreterCallInterpretingEvent": (
            "code_interpreter",
            "running",
        ),
        "ResponseCodeInterpreterCallCompletedEvent": (
            "code_interpreter",
            "completed",
        ),
        "response.code_interpreter_call.in_progress": (
            "code_interpreter",
            "running",
        ),
        "response.code_interpreter_call.interpreting": (
            "code_interpreter",
            "running",
        ),
        "response.code_interpreter_call.completed": (
            "code_interpreter",
            "completed",
        ),
        "ResponseImageGenCallInProgressEvent": ("image_generation", "running"),
        "ResponseImageGenCallGeneratingEvent": ("image_generation", "running"),
        "ResponseImageGenCallCompletedEvent": ("image_generation", "completed"),
        "response.image_generation_call.in_progress": (
            "image_generation",
            "running",
        ),
        "response.image_generation_call.generating": (
            "image_generation",
            "running",
        ),
        "response.image_generation_call.completed": (
            "image_generation",
            "completed",
        ),
        "ResponseMcpCallInProgressEvent": ("mcp", "running"),
        "ResponseMcpCallCompletedEvent": ("mcp", "completed"),
        "ResponseMcpCallFailedEvent": ("mcp", "failed"),
        "response.mcp_call.in_progress": ("mcp", "running"),
        "response.mcp_call.completed": ("mcp", "completed"),
        "response.mcp_call.failed": ("mcp", "failed"),
    }
    activity = lifecycle.get(event_type)
    if activity is None:
        return None
    call_id = item.get("item_id") or item.get("call_id") or item.get("id")
    if not isinstance(call_id, str) or not call_id:
        return None
    name, status = activity
    return ProviderToolObservation(
        call_id=call_id,
        name=name,
        status=status,
    )


def _provider_tool_output_item_observation(
    item: dict[str, object],
    *,
    default_status: Literal["running", "completed", "failed"],
) -> ProviderToolObservation | None:
    """Extract provider-tool activity from one native output item."""
    item_type = item.get("type")
    if not isinstance(item_type, str):
        return None
    spec = RESPONSES_PROVIDER_TOOL_SPECS.get(item_type)
    if spec is None:
        return None
    name = spec.resolve_name(item)
    call_id = item.get("call_id") or item.get("id")
    if not isinstance(call_id, str) or not call_id:
        return None
    return ProviderToolObservation(
        call_id=call_id,
        name=name,
        status=_provider_tool_output_item_status(
            item.get("status"),
            default_status=default_status,
        ),
    )


def _provider_tool_output_item_status(
    native_status: object,
    *,
    default_status: Literal["running", "completed", "failed"],
) -> Literal["running", "completed", "failed"]:
    """Resolve output-item status while respecting terminal done frames."""
    canonical = _canonical_provider_tool_status(native_status)
    activity_status: Literal["running", "completed", "failed"] | None
    match canonical:
        case "cancelled" | "interrupted":
            activity_status = "failed"
        case "running" | "completed" | "failed":
            activity_status = canonical
        case None:
            activity_status = None
    if default_status != "completed":
        return activity_status or default_status
    normalized = (
        native_status.lower().replace("-", "_")
        if isinstance(native_status, str)
        else None
    )
    if activity_status == "failed" or normalized == "incomplete":
        return "failed"
    return "completed"


def _canonical_provider_tool_status(
    native_status: object,
) -> (
    Literal[
        "running",
        "completed",
        "failed",
        "cancelled",
        "interrupted",
    ]
    | None
):
    """Map one native provider-tool state to the canonical lifecycle."""
    if not isinstance(native_status, str):
        return None
    normalized = native_status.lower().replace("-", "_")
    if normalized in {
        "added",
        "queued",
        "pending",
        "in_progress",
        "searching",
        "generating",
        "interpreting",
        "calling",
    }:
        return "running"
    if normalized in {"completed", "done", "succeeded"}:
        return "completed"
    if normalized in {"failed", "error", "incomplete"}:
        return "failed"
    if normalized in {"cancelled", "canceled"}:
        return "cancelled"
    if normalized == "interrupted":
        return "interrupted"
    return None


def _incomplete_response_model_error(
    response: dict[str, object],
    *,
    operation: ModelStreamCallKind,
    provider: str,
    model: str,
    integration: str | None,
) -> ModelProviderFailure:
    """Create a typed provider failure for an incomplete response."""
    details = response_item_dict(response.get("incomplete_details"))
    provider_code = details.get("reason")
    return model_provider_failure(
        operation=operation,
        provider=provider,
        model=model,
        integration=integration,
        provider_message=(
            details.get("message")
            or _terminal_failure_fallback_message("incomplete", provider_code)
        ),
        status_code=None,
        provider_code=provider_code,
        provider_error_type="response_incomplete",
    )


def _failed_response_model_error(
    response: dict[str, object],
    *,
    operation: ModelStreamCallKind,
    provider: str,
    model: str,
    integration: str | None,
) -> ModelProviderFailure:
    """Create a typed provider failure for a failed response."""
    error = response_item_dict(response.get("error"))
    provider_code = error.get("code")
    return model_provider_failure(
        operation=operation,
        provider=provider,
        model=model,
        integration=integration,
        provider_message=(
            error.get("message")
            or _terminal_failure_fallback_message("failed", provider_code)
        ),
        status_code=None,
        provider_code=provider_code,
        provider_error_type=error.get("type") or "response_failed",
    )


def _response_error_event_model_error(
    item: dict[str, object],
    *,
    operation: ModelStreamCallKind,
    provider: str,
    model: str,
    integration: str | None,
) -> ModelProviderFailure:
    """Create a typed provider failure for a native Responses error event."""
    provider_code = item.get("code")
    return model_provider_failure(
        operation=operation,
        provider=provider,
        model=model,
        integration=integration,
        provider_message=(
            item.get("message")
            or _terminal_failure_fallback_message("error", provider_code)
        ),
        status_code=None,
        provider_code=provider_code,
        provider_error_type=item.get("type") or "response_error",
    )


def _terminal_failure_fallback_message(
    outcome: Literal["error", "failed", "incomplete"],
    provider_code: object,
) -> str:
    """Return a concise classified fallback when no provider message exists."""
    if provider_code == "max_output_tokens":
        return "The model response reached its output token limit."
    if provider_code in {"content_filter", "bio_policy", "cyber_policy"}:
        return "The model provider rejected the request due to policy."
    if provider_code == "context_length_exceeded":
        return "The model context window was exceeded."
    if provider_code == "insufficient_quota":
        return "The model provider quota was exceeded."
    if provider_code == "rate_limit_exceeded":
        return "The model provider rate limit was exceeded."
    if provider_code == "server_error":
        return "The model provider is temporarily unavailable."
    if outcome == "incomplete":
        return "The model response was incomplete."
    if outcome == "failed":
        return "The model response failed."
    return "The model provider could not process the request."


def _has_assistant_text(events: Sequence[Event]) -> bool:
    """Return whether normalized output already has assistant text."""
    for event in events:
        payload = event.payload
        if not isinstance(payload, AssistantMessagePayload):
            continue
        if isinstance(payload.content, str):
            if payload.content:
                return True
            continue
        if any(
            isinstance(part, OutputTextPart) and bool(part.text)
            for part in payload.content
        ):
            return True
    return False


def _event(
    session_id: str,
    kind: EventKind,
    payload: EventPayload,
) -> Event:
    """Create event wrapper."""
    return Event(
        id=uuid7().hex,
        session_id=session_id,
        kind=kind,
        payload=payload,
        created_at=datetime.datetime.now(datetime.UTC),
    )


def _normalize_response_usage(
    response: dict[str, object],
) -> TokenUsagePayload | None:
    """Normalize Responses usage payload to UI/legacy token usage shape."""
    raw_usage = response_item_dict(response.get("usage"))
    if not raw_usage:
        return None

    prompt_tokens = _first_int(
        _int_or_none(raw_usage.get("prompt_tokens")),
        _int_or_none(raw_usage.get("input_tokens")),
    )
    completion_tokens = _first_int(
        _int_or_none(raw_usage.get("completion_tokens")),
        _int_or_none(raw_usage.get("output_tokens")),
    )
    if prompt_tokens is None or completion_tokens is None:
        return None

    total_tokens = _first_int(
        _int_or_none(raw_usage.get("total_tokens")),
        prompt_tokens + completion_tokens,
    )
    if total_tokens is None:
        return None

    cached_tokens = _first_int(
        _int_or_none(raw_usage.get("cached_tokens")),
        _int_or_none(raw_usage.get("cache_read_input_tokens")),
        _int_or_none(
            response_item_dict(raw_usage.get("input_tokens_details")).get(
                "cached_tokens"
            )
        ),
        _int_or_none(
            response_item_dict(raw_usage.get("prompt_tokens_details")).get(
                "cached_tokens"
            )
        ),
    )
    cache_creation_tokens = _first_int(
        _int_or_none(raw_usage.get("cache_creation_tokens")),
        _int_or_none(raw_usage.get("cache_creation_input_tokens")),
        _int_or_none(
            response_item_dict(raw_usage.get("input_tokens_details")).get(
                "cache_creation_tokens"
            )
        ),
        _int_or_none(
            response_item_dict(raw_usage.get("prompt_tokens_details")).get(
                "cache_creation_tokens"
            )
        ),
    )
    reasoning_tokens = _first_int(
        _int_or_none(raw_usage.get("reasoning_tokens")),
        _int_or_none(
            response_item_dict(raw_usage.get("output_tokens_details")).get(
                "reasoning_tokens"
            )
        ),
        _int_or_none(
            response_item_dict(raw_usage.get("completion_tokens_details")).get(
                "reasoning_tokens"
            )
        ),
    )
    raw_hidden_params = response_item_dict(response.get("_hidden_params")) or None
    cost_usd = _first_float(
        _float_or_none(raw_usage.get("cost_usd")),
        _float_or_none(raw_usage.get("cost")),
        _float_or_none(
            raw_hidden_params.get("response_cost")
            if raw_hidden_params is not None
            else None
        ),
    )

    return TokenUsagePayload(
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        total_tokens=total_tokens,
        raw=raw_usage,
        cached_tokens=cached_tokens,
        cache_creation_tokens=cache_creation_tokens,
        reasoning_tokens=reasoning_tokens,
        cost_usd=cost_usd,
        raw_hidden_params=raw_hidden_params,
    )


def _first_int(*values: int | None) -> int | None:
    """Return first int value."""
    for value in values:
        if value is not None:
            return value
    return None


def _first_float(*values: float | None) -> float | None:
    """Return first float value."""
    for value in values:
        if value is not None:
            return value
    return None


def _extract_message_text(item: dict[str, object]) -> str:
    """Extract text from Responses message item."""
    content = item.get("content")
    if not isinstance(content, list):
        return ""
    parts: list[str] = []
    for part in content:
        partresponse_item_dict = response_item_dict(part)
        text = partresponse_item_dict.get("text")
        if isinstance(text, str) and text:
            parts.append(text)
    return "\n".join(parts)


def _extract_reasoning_part_text(item: dict[str, object], key: str) -> str:
    """Extract text from specified part list of Responses reasoning item."""
    raw_parts = item.get(key)
    if not isinstance(raw_parts, list):
        return ""
    parts: list[str] = []
    for part in raw_parts:
        text = response_item_dict(part).get("text")
        if isinstance(text, str) and text:
            parts.append(text)
    return "\n".join(parts)


def response_item_dict(value: object) -> dict[str, object]:
    """Safely return dict value."""
    if isinstance(value, dict):
        return value
    return {}


def has_response_output_item_type(item: dict[str, object]) -> bool:
    """Check whether value is Responses output item."""
    item_type = item.get("type")
    return isinstance(item_type, str) and bool(item_type)


def _int_or_none(value: object) -> int | None:
    """Return int-convertible value."""
    if isinstance(value, int) and not isinstance(value, bool):
        return value
    return None


def _float_or_none(value: object) -> float | None:
    """Return float-convertible value."""
    if isinstance(value, bool):
        return None
    if isinstance(value, int | float):
        return float(value)
    return None
