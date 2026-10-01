"""Normalize model assembly with separate native completion and artifact evidence."""

import datetime
import hashlib
import json
from collections.abc import Sequence

from azcommon.types import JSONValue
from azcommon.uuid import uuid7
from pydantic import TypeAdapter
from pydantic_ai.messages import (
    BinaryContent,
    FilePart,
    ModelMessagesTypeAdapter,
    ModelResponse,
    ModelResponsePart,
    NativeToolCallPart,
    NativeToolReturnPart,
    PartDeltaEvent,
    PartEndEvent,
    PartStartEvent,
    TextPart,
    TextPartDelta,
    ThinkingPart,
    ThinkingPartDelta,
    ToolCallPart,
    ToolCallPartDelta,
)

from azents.core.enums import EventKind
from azents.core.model_pricing import CapturedModelPricing
from azents.core.type_guards import is_string_object_dict
from azents.engine.events.generated_files import PendingGeneratedFileOutput
from azents.engine.events.model_usage_pricing import apply_model_usage_pricing
from azents.engine.events.output_parts import enforce_tool_output_text_hard_cap
from azents.engine.events.protocols import (
    ContentDeltaProjection,
    FunctionCallDeltaProjection,
    NormalizedAdapterOutput,
    ProviderToolActivityProjection,
    ReasoningDeltaProjection,
    StreamProjection,
)
from azents.engine.events.provider_tool_semantics import (
    normalize_responses_provider_tool_item,
)
from azents.engine.events.pydantic_ai_types import (
    NativeModelObservation,
    PydanticAIStreamEvent,
)
from azents.engine.events.responses_output import ResponsesOutputNormalizer
from azents.engine.events.types import (
    AssistantMessagePayload,
    ClientToolCallPayload,
    Event,
    NativeArtifact,
    OutputTextPart,
    ProviderToolCallPayload,
    ProviderToolReference,
    ProviderToolSemanticContent,
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

_JSON_OBJECT_ADAPTER = TypeAdapter(dict[str, JSONValue])


class _CanonicalItems(ResponsesOutputNormalizer):
    """Reuse canonical semantic extraction without a Responses transport."""

    adapter = "pydantic_ai"
    native_format = "model_messages"


class PydanticAIOutputNormalizer:
    """Keep native proof and canonical admission separate from common state."""

    adapter = "pydantic_ai"
    native_format = "model_messages"
    schema_version = "1"

    def __init__(
        self,
        *,
        provider: str,
        model: str,
        pricing: CapturedModelPricing | None,
        operation: ModelStreamCallKind,
        integration: str | None,
    ) -> None:
        self.provider = provider
        self.model = model
        self.pricing = pricing
        self.operation = operation
        self.integration = integration
        self.service_tier: str | None = None
        self.compat_key = build_native_compat_key(
            adapter=self.adapter,
            native_format=self.native_format,
            provider=provider,
            model=model,
            schema_version=self.schema_version,
        )
        self.canonical = _CanonicalItems(
            provider=provider,
            model=model,
            pricing=None,
            operation=operation,
            integration=integration,
        )

    def start(self, session_id: str) -> "PydanticAIOutputStream":
        """Freeze request-scoped price authority before observing the dispatch."""
        return PydanticAIOutputStream(self, session_id)


class PydanticAIOutputStream:
    """Common live parts and same-dispatch native evidence for one attempt."""

    def __init__(self, normalizer: PydanticAIOutputNormalizer, session_id: str) -> None:
        self.normalizer = normalizer
        self.session_id = session_id
        self.pricing = normalizer.pricing
        self.service_tier = normalizer.service_tier
        self.parts: dict[int, ModelResponsePart] = {}
        self.closed_parts: dict[int, ModelResponsePart] = {}
        self.response: ModelResponse | None = None
        self.native_success = False
        self.native_failure: ModelProviderFailure | None = None
        self.end_turn: bool | None = None
        self.native_usage: dict[str, object] = {}
        self.reported_charge: float | None = None
        self.protocol: str | None = None
        self.native_items: dict[str, dict[str, object]] = {}
        self.annotations: list[dict[str, object]] = []
        self.dispatch_id = uuid7().hex

    def process_event(
        self, native_event: PydanticAIStreamEvent
    ) -> NormalizedAdapterOutput:
        """Publish provisional semantic deltas; native observations never imply text."""
        projections: list[StreamProjection] = []
        if native_event.observation is not None:
            projections.extend(self._observe(native_event.observation))
        if native_event.response is not None:
            self.response = native_event.response
        event = native_event.event
        if isinstance(event, PartStartEvent):
            self.parts[event.index] = event.part
            projections.extend(self._part_projection(event.index, event.part))
        elif isinstance(event, PartDeltaEvent):
            part = self.parts.get(event.index)
            delta = event.delta
            if isinstance(delta, TextPartDelta):
                if isinstance(part, TextPart):
                    self.parts[event.index] = delta.apply(part)
                projections.append(
                    ContentDeltaProjection(
                        delta=delta.content_delta, content_index=event.index
                    )
                )
            elif isinstance(delta, ThinkingPartDelta):
                if isinstance(part, ThinkingPart):
                    self.parts[event.index] = delta.apply(part)
                if (
                    delta.content_delta
                    and not isinstance(part, ThinkingPart)
                    or delta.content_delta
                    and isinstance(part, ThinkingPart)
                    and part.id != "redacted_thinking"
                ):
                    projections.append(
                        ReasoningDeltaProjection(
                            delta=delta.content_delta,
                            item_id=part.id if isinstance(part, ThinkingPart) else None,
                            output_index=event.index,
                            summary_index=None,
                        )
                    )
            elif isinstance(delta, ToolCallPartDelta):
                if isinstance(part, ToolCallPart):
                    updated = delta.apply(part)
                    self.parts[event.index] = updated
                    argument_delta = delta.args_delta
                    if argument_delta is not None:
                        projections.append(
                            FunctionCallDeltaProjection(
                                index=event.index,
                                call_id=updated.tool_call_id,
                                name=updated.tool_name,
                                delta=argument_delta
                                if isinstance(argument_delta, str)
                                else json.dumps(
                                    argument_delta,
                                    ensure_ascii=False,
                                    separators=(",", ":"),
                                ),
                            )
                        )
        elif isinstance(event, PartEndEvent):
            self.parts[event.index] = event.part
            self.closed_parts[event.index] = event.part
        current_parts = (
            list(self.response.parts)
            if self.response is not None
            else list(self.parts.values())
        )
        return NormalizedAdapterOutput(
            needs_follow_up=False,
            projections=projections,
            usage=self._usage(current_parts),
        )

    def _observe(self, observation: NativeModelObservation) -> list[StreamProjection]:
        self.protocol = observation.protocol
        if observation.terminal == "success":
            self.native_success = True
        if observation.error is not None:
            error = observation.error
            self.native_failure = model_provider_failure(
                operation=self.normalizer.operation,
                provider=self.normalizer.provider,
                model=self.normalizer.model,
                integration=self.normalizer.integration,
                provider_message=error.message,
                status_code=error.status_code,
                provider_code=error.code,
                provider_error_type=error.error_type,
                provider_error_param=error.parameter,
            )
        elif observation.terminal in {"failed", "incomplete"}:
            self.native_failure = model_provider_failure(
                operation=self.normalizer.operation,
                provider=self.normalizer.provider,
                model=self.normalizer.model,
                integration=self.normalizer.integration,
                provider_message=(
                    "The model provider did not complete the response successfully."
                ),
                status_code=None,
                provider_code=None,
                provider_error_type="response_incomplete"
                if observation.terminal == "incomplete"
                else "response_failed",
                provider_error_param=None,
            )
        if isinstance(observation.end_turn, bool):
            self.end_turn = observation.end_turn
        if observation.native_usage is not None:
            self.native_usage.update(observation.native_usage)
        if (
            observation.reported_cost_usd is not None
            and self.normalizer.provider == "openrouter"
        ):
            self.reported_charge = observation.reported_cost_usd
        if observation.service_tier not in {None, "auto"}:
            self.service_tier = observation.service_tier
        self.annotations.extend(observation.annotations)
        projections: list[StreamProjection] = []
        for item in observation.native_items:
            identity = item.get("id") or item.get("call_id")
            item_type = item.get("type")
            key = (
                f"{item_type}:{identity}"
                if isinstance(identity, str)
                else json.dumps(item, sort_keys=True, default=str)
            )
            self.native_items[key] = dict(item)
            normalized = normalize_responses_provider_tool_item(item)
            if normalized is not None and isinstance(identity, str):
                status = item.get("status")
                live_status = (
                    "completed"
                    if status == "completed"
                    else "failed"
                    if status in {"failed", "incomplete", "cancelled"}
                    else "running"
                )
                projections.append(
                    ProviderToolActivityProjection(
                        call_id=identity,
                        name=normalized.name,
                        status=live_status,
                        arguments=normalized.semantic.input,
                    )
                )
        return projections

    @staticmethod
    def _part_projection(index: int, part: ModelResponsePart) -> list[StreamProjection]:
        if isinstance(part, TextPart) and part.content:
            return [ContentDeltaProjection(delta=part.content, content_index=index)]
        if (
            isinstance(part, ThinkingPart)
            and part.content
            and part.id != "redacted_thinking"
        ):
            return [
                ReasoningDeltaProjection(
                    delta=part.content,
                    item_id=part.id,
                    output_index=index,
                    summary_index=None,
                )
            ]
        if isinstance(part, ToolCallPart):
            args = part.args
            return [
                FunctionCallDeltaProjection(
                    index=index,
                    call_id=part.tool_call_id,
                    name=part.tool_name,
                    delta=args
                    if isinstance(args, str)
                    else json.dumps(args, separators=(",", ":"))
                    if args is not None
                    else "",
                )
            ]
        if isinstance(part, NativeToolCallPart):
            return [
                ProviderToolActivityProjection(
                    call_id=part.tool_call_id,
                    name=part.tool_name,
                    status="running",
                    arguments=_arguments(part.args),
                )
            ]
        if isinstance(part, NativeToolReturnPart):
            return [
                ProviderToolActivityProjection(
                    call_id=part.tool_call_id,
                    name=part.tool_name,
                    status="completed" if part.outcome == "success" else "failed",
                    arguments=None,
                )
            ]
        return []

    def complete(self) -> NormalizedAdapterOutput:
        """Admit durable parts only after recognized route-native success."""
        if self.native_failure is not None:
            raise self.native_failure
        if not self.native_success:
            raise model_provider_failure(
                operation=self.normalizer.operation,
                provider=self.normalizer.provider,
                model=self.normalizer.model,
                integration=self.normalizer.integration,
                provider_message="The model response stream ended before completion.",
                status_code=None,
                provider_code="stream_ended_before_completion",
                provider_error_type="response_stream_transport",
                provider_error_param=None,
                category=ModelProviderFailureCategory.TRANSPORT,
            )
        return self._build(interrupted=False)

    def interrupt(self) -> NormalizedAdapterOutput:
        """Preserve bounded completed/assistant output without a success claim."""
        return self._build(interrupted=True).model_copy(
            update={"needs_follow_up": False}
        )

    def _build(self, *, interrupted: bool) -> NormalizedAdapterOutput:
        final_parts = (
            list(self.response.parts)
            if self.response is not None
            else [part for _, part in sorted(self.closed_parts.items())]
        )
        if interrupted and self.response is None:
            final_parts.extend(
                part
                for index, part in sorted(self.parts.items())
                if index not in self.closed_parts
                and isinstance(part, TextPart | ThinkingPart)
            )
        events: list[Event] = []
        pending: list[PendingGeneratedFileOutput] = []
        common_hosted: dict[str, list[ModelResponsePart]] = {}
        for part in final_parts:
            if isinstance(part, NativeToolCallPart | NativeToolReturnPart):
                common_hosted.setdefault(part.tool_call_id, []).append(part)
                continue
            if isinstance(part, TextPart):
                events.append(
                    self._event(
                        EventKind.ASSISTANT_MESSAGE,
                        AssistantMessagePayload(
                            content=part.content, native_artifact=self._artifact([part])
                        ),
                    )
                )
            elif isinstance(part, ThinkingPart):
                events.append(
                    self._event(
                        EventKind.REASONING,
                        ReasoningPayload(
                            text=part.content
                            if part.id != "redacted_thinking"
                            else None,
                            summary=None,
                            native_artifact=self._artifact([part]),
                        ),
                    )
                )
            elif isinstance(part, ToolCallPart):
                native_call = self._native_call(part)
                args = _arguments(part.args)
                if native_call is not None:
                    native_args = native_call.get("arguments")
                    native_input = native_call.get("input")
                    if isinstance(native_args, str):
                        args = native_args
                    elif is_string_object_dict(native_input):
                        args = _arguments(native_input)
                dialect = (part.provider_details or {}).get(
                    "azents_wire_dialect", "json_function"
                )
                if (
                    not part.tool_name
                    or not part.tool_call_id
                    or args is None
                    or native_call is not None
                    and native_call.get("status") in {"incomplete", "in_progress"}
                ):
                    events.append(
                        self._invalid_call_event(
                            part, diagnostic="incomplete_client_tool_call"
                        )
                    )
                    continue
                if dialect == "json_function":
                    try:
                        decoded = json.loads(args)
                    except json.JSONDecodeError:
                        decoded = None
                    if not isinstance(decoded, dict) and not self._closed_call(
                        part, native_call
                    ):
                        events.append(
                            self._invalid_call_event(
                                part, diagnostic="invalid_client_tool_arguments"
                            )
                        )
                        continue
                elif dialect != "plaintext_custom":
                    continue
                events.append(
                    self._event(
                        EventKind.CLIENT_TOOL_CALL,
                        ClientToolCallPayload(
                            call_id=part.tool_call_id,
                            name=part.tool_name,
                            arguments=args,
                            wire_dialect=dialect,
                            native_artifact=self._artifact([part]),
                        ),
                    )
                )
            elif isinstance(part, FilePart):
                file_index = len(pending)
                call_id = part.id or (f"generated-file-{self.dispatch_id}-{file_index}")
                content = part.content
                media_type = content.media_type
                extension = media_type.rsplit("/", 1)[-1]
                pending.append(
                    PendingGeneratedFileOutput(
                        call_id=call_id,
                        tool_name="image_generation",
                        output_index=file_index,
                        filename=f"generated.{extension}",
                        media_type=media_type,
                        sha256=hashlib.sha256(content.data).hexdigest(),
                        body=content.data,
                    )
                )
                events.append(
                    self._event(
                        EventKind.PROVIDER_TOOL_CALL,
                        ProviderToolCallPayload(
                            call_id=call_id,
                            name="image_generation",
                            status="interrupted" if interrupted else "completed",
                            semantic=ProviderToolSemanticContent(
                                input=None, output=[], references=[]
                            ),
                            native_artifact=self._artifact(
                                [],
                                supplemental={
                                    "file_media_type": media_type,
                                    "file_sha256": hashlib.sha256(
                                        content.data
                                    ).hexdigest(),
                                },
                            ),
                        ),
                    )
                )
            else:
                events.append(
                    self._event(
                        EventKind.UNKNOWN_ADAPTER_OUTPUT,
                        UnknownAdapterOutputPayload(
                            native_artifact=self._artifact(
                                [],
                                supplemental={"unsupported_part_kind": part.part_kind},
                            )
                        ),
                    )
                )
        represented: set[str] = set()
        for item in self.native_items.values():
            normalized = normalize_responses_provider_tool_item(item)
            if normalized is None:
                continue
            identity = item.get("id") or item.get("call_id")
            if not isinstance(identity, str) or identity in represented:
                continue
            represented.add(identity)
            parts = common_hosted.get(identity, [])
            mapped = self.normalizer.canonical.normalize_completed_output(
                self.session_id, {"output": [item]}, []
            )
            for event in mapped.events:
                if isinstance(event.payload, ProviderToolCallPayload):
                    events.append(
                        event.model_copy(
                            update={
                                "payload": event.payload.model_copy(
                                    update={
                                        "native_artifact": self._artifact(
                                            parts,
                                            supplemental={
                                                "native_item": _safe_native_item(item)
                                            },
                                        )
                                    }
                                )
                            }
                        )
                    )
            pending.extend(mapped.pending_provider_files)
        for identity, parts in common_hosted.items():
            if identity in represented:
                continue
            call = next(
                (part for part in parts if isinstance(part, NativeToolCallPart)), None
            )
            returned = next(
                (part for part in parts if isinstance(part, NativeToolReturnPart)), None
            )
            name = (
                call.tool_name
                if call is not None
                else returned.tool_name
                if returned is not None
                else "unknown"
            )
            output = (
                _native_tool_content(returned.content) if returned is not None else ""
            )
            events.append(
                self._event(
                    EventKind.PROVIDER_TOOL_CALL,
                    ProviderToolCallPayload(
                        call_id=identity,
                        name=name,
                        status="interrupted"
                        if interrupted
                        else "completed"
                        if returned is not None and returned.outcome == "success"
                        else "failed"
                        if returned is not None
                        else None,
                        semantic=ProviderToolSemanticContent(
                            input=_arguments(call.args) if call is not None else None,
                            output=enforce_tool_output_text_hard_cap(
                                [OutputTextPart(text=output)]
                            )
                            if output
                            else [],
                            references=_native_tool_references(returned.content)
                            if returned is not None
                            else [],
                        ),
                        native_artifact=self._artifact(parts),
                    ),
                )
            )
        calls = any(
            isinstance(event.payload, ClientToolCallPayload) for event in events
        )
        if events and self.native_items:
            event = events[0]
            payload = event.payload
            if isinstance(
                payload,
                AssistantMessagePayload
                | ReasoningPayload
                | ClientToolCallPayload
                | ProviderToolCallPayload,
            ):
                artifact = payload.native_artifact
                item = dict(artifact.item)
                item["native_supplement"] = [
                    _safe_native_item(value) for value in self.native_items.values()
                ]
                events[0] = event.model_copy(
                    update={
                        "payload": payload.model_copy(
                            update={
                                "native_artifact": artifact.model_copy(
                                    update={
                                        "item": _JSON_OBJECT_ADAPTER.validate_python(
                                            item
                                        )
                                    }
                                )
                            }
                        )
                    }
                )
        follow_up = not self.end_turn if self.end_turn is not None else calls
        return NormalizedAdapterOutput(
            needs_follow_up=follow_up,
            events=events,
            usage=self._usage(final_parts),
            pending_provider_files=pending,
        )

    def _native_call(self, part: ToolCallPart) -> dict[str, object] | None:
        return next(
            (
                item
                for item in self.native_items.values()
                if item.get("type") in {"function_call", "custom_tool_call", "tool_use"}
                and (
                    item.get("call_id") == part.tool_call_id
                    or item.get("id") == part.tool_call_id
                    or part.id is not None
                    and item.get("id") == part.id
                )
            ),
            None,
        )

    def _closed_call(
        self, part: ToolCallPart, native_call: dict[str, object] | None
    ) -> bool:
        return (
            native_call is not None
            and native_call.get("status") == "completed"
            or any(
                isinstance(closed, ToolCallPart)
                and closed.tool_call_id == part.tool_call_id
                for closed in self.closed_parts.values()
            )
        )

    def _invalid_call_event(self, part: ToolCallPart, *, diagnostic: str) -> Event:
        return self._event(
            EventKind.UNKNOWN_ADAPTER_OUTPUT,
            UnknownAdapterOutputPayload(
                reason=diagnostic,
                native_artifact=self._artifact(
                    [],
                    supplemental={
                        "diagnostic": diagnostic,
                        "tool_name": part.tool_name[:200],
                        "call_id": part.tool_call_id[:200],
                    },
                ),
            ),
        )

    def _artifact(
        self,
        parts: Sequence[ModelResponsePart],
        *,
        supplemental: dict[str, object] | None = None,
    ) -> NativeArtifact:
        item: dict[str, object] = {}
        if parts:
            message = ModelResponse(
                parts=parts,
                model_name=self.response.model_name
                if self.response is not None
                else self.normalizer.model,
                provider_name=self.response.provider_name
                if self.response is not None
                else self.normalizer.provider,
                provider_response_id=self.response.provider_response_id
                if self.response is not None
                else None,
            )
            serialized = ModelMessagesTypeAdapter.dump_python([message], mode="json")
            item["message"] = serialized[0]
        if supplemental is not None:
            item["supplement"] = supplemental
        if self.annotations:
            item["annotations"] = list(self.annotations)
        return NativeArtifact(
            compat_key=self.normalizer.compat_key,
            adapter=self.normalizer.adapter,
            native_format=self.normalizer.native_format,
            provider=self.normalizer.provider,
            model=self.normalizer.model,
            schema_version=self.normalizer.schema_version,
            item=_JSON_OBJECT_ADAPTER.validate_python(item),
        )

    def _event(
        self,
        kind: EventKind,
        payload: AssistantMessagePayload
        | ReasoningPayload
        | ClientToolCallPayload
        | ProviderToolCallPayload
        | UnknownAdapterOutputPayload,
    ) -> Event:
        return Event(
            id=uuid7().hex,
            session_id=self.session_id,
            kind=kind,
            payload=payload,
            created_at=datetime.datetime.now(datetime.UTC),
        )

    def _usage(self, parts: Sequence[ModelResponsePart]) -> TokenUsagePayload | None:
        common = self.response.usage if self.response is not None else None
        if common is None and not self.native_usage:
            return None
        raw: dict[str, object] = dict(self.native_usage)
        details = common.details or {} if common is not None else {}
        prompt = (
            common.input_tokens
            if common is not None
            else _first_int(
                _int(raw.get("input_tokens")), _int(raw.get("prompt_tokens"))
            )
        )
        completion = (
            common.output_tokens
            if common is not None
            else _first_int(
                _int(raw.get("output_tokens")),
                _int(raw.get("completion_tokens")),
            )
        )
        cached = (
            common.cache_read_tokens
            if common is not None and common.cache_read_tokens != 0
            else _int(raw.get("cache_read_input_tokens"))
        )
        written = (
            common.cache_write_tokens
            if common is not None and common.cache_write_tokens != 0
            else _int(raw.get("cache_creation_input_tokens"))
        )
        reasoning = _first_int(
            _int(details.get("reasoning_tokens")),
            _int(details.get("thoughts_tokens")),
        )
        if self.protocol == "anthropic":
            cached = (
                _int(raw.get("cache_read_input_tokens"))
                if "cache_read_input_tokens" in raw
                else cached
            )
            written = (
                _int(raw.get("cache_creation_input_tokens"))
                if "cache_creation_input_tokens" in raw
                else written
            )
            if (native_prompt := _int(raw.get("input_tokens"))) is not None:
                prompt = native_prompt + (cached or 0) + (written or 0)
            if (native_completion := _int(raw.get("output_tokens"))) is not None:
                completion = native_completion
        elif self.protocol == "google":
            if (native_prompt := _int(raw.get("promptTokenCount"))) is not None:
                prompt = native_prompt
            thoughts = _int(raw.get("thoughtsTokenCount"))
            if (native_completion := _int(raw.get("candidatesTokenCount"))) is not None:
                completion = native_completion + (thoughts or 0)
            reasoning = thoughts if thoughts is not None else reasoning
            cached = (
                _int(raw.get("cachedContentTokenCount"))
                if "cachedContentTokenCount" in raw
                else cached
            )
        elif self.protocol == "bedrock":
            cached = (
                _int(raw.get("cacheReadInputTokens"))
                if "cacheReadInputTokens" in raw
                else cached
            )
            written = (
                _int(raw.get("cacheWriteInputTokens"))
                if "cacheWriteInputTokens" in raw
                else written
            )
            if (native_prompt := _int(raw.get("inputTokens"))) is not None:
                prompt = native_prompt + (cached or 0) + (written or 0)
            if (native_completion := _int(raw.get("outputTokens"))) is not None:
                completion = native_completion
        elif self.protocol in {"responses", "chat_completions"}:
            if (
                native_prompt := _first_int(
                    _int(raw.get("input_tokens")),
                    _int(raw.get("prompt_tokens")),
                )
            ) is not None:
                prompt = native_prompt
            if (
                native_completion := _first_int(
                    _int(raw.get("output_tokens")),
                    _int(raw.get("completion_tokens")),
                )
            ) is not None:
                completion = native_completion
            input_details = _dict(raw.get("input_tokens_details")) or _dict(
                raw.get("prompt_tokens_details")
            )
            output_details = _dict(raw.get("output_tokens_details")) or _dict(
                raw.get("completion_tokens_details")
            )
            cached = (
                _int(input_details.get("cached_tokens"))
                if "cached_tokens" in input_details
                else cached
            )
            written = (
                _int(input_details.get("cache_write_tokens"))
                if "cache_write_tokens" in input_details
                else written
            )
            reasoning = (
                _int(output_details.get("reasoning_tokens"))
                if "reasoning_tokens" in output_details
                else reasoning
            )
        if prompt is None or completion is None:
            return None
        if (
            common is not None
            and not details
            and prompt == 0
            and completion == 0
            and not any(
                _int(raw.get(key)) is not None
                for key in (
                    "input_tokens",
                    "output_tokens",
                    "prompt_tokens",
                    "completion_tokens",
                    "promptTokenCount",
                    "candidatesTokenCount",
                    "inputTokens",
                    "outputTokens",
                )
            )
        ):
            return None
        raw.update(
            {
                "input_tokens": prompt,
                "output_tokens": completion,
                "total_tokens": prompt + completion,
            }
        )
        usage = TokenUsagePayload(
            prompt_tokens=prompt,
            completion_tokens=completion,
            total_tokens=prompt + completion,
            raw=raw,
            cached_tokens=cached,
            cache_creation_tokens=written,
            reasoning_tokens=reasoning,
            cost_usd=None,
            raw_hidden_params=None,
        )
        output_types = [
            "web_search_call"
            if isinstance(part, NativeToolCallPart)
            and part.tool_name in {"web_search", "google_search"}
            else "file_search_call"
            if isinstance(part, NativeToolCallPart) and part.tool_name == "file_search"
            else "message"
            if isinstance(part, TextPart)
            else "reasoning"
            if isinstance(part, ThinkingPart)
            else "function_call"
            if isinstance(part, ToolCallPart)
            else part.part_kind
            for part in parts
            if not isinstance(part, NativeToolReturnPart)
        ]
        represented_tools = {
            part.tool_call_id for part in parts if isinstance(part, NativeToolCallPart)
        }
        for item in self.native_items.values():
            identity = item.get("id") or item.get("call_id")
            item_type = item.get("type")
            if (
                identity not in represented_tools
                and isinstance(item_type, str)
                and normalize_responses_provider_tool_item(item) is not None
            ):
                output_types.append(item_type)
                if isinstance(identity, str):
                    represented_tools.add(identity)
        return apply_model_usage_pricing(
            usage,
            provider=self.normalizer.provider,
            model_identifier=self.normalizer.model,
            pricing=self.pricing,
            service_tier=self.service_tier,
            output_item_types=output_types,
            reported_charge=self.reported_charge,
        )


def _arguments(value: str | dict[str, object] | None) -> str | None:
    if isinstance(value, str):
        return value
    if value is None:
        return None
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def _native_tool_content(value: object) -> str:
    if isinstance(value, str):
        return value
    if value is None:
        return ""
    return json.dumps(
        _visible_tool_content(value),
        ensure_ascii=False,
        separators=(",", ":"),
        default=str,
    )


def _native_tool_references(value: object) -> list[ProviderToolReference]:
    references: list[ProviderToolReference] = []
    pending: list[tuple[object, int]] = [(value, 0)]
    seen: set[str] = set()
    while pending and len(references) < 100:
        candidate, depth = pending.pop()
        if depth > 5:
            continue
        if isinstance(candidate, list):
            pending.extend((nested, depth + 1) for nested in candidate[:100])
            continue
        item = _dict(candidate)
        uri = item.get("url") or item.get("uri")
        if isinstance(uri, str) and uri not in seen:
            seen.add(uri)
            title = item.get("title")
            excerpt = item.get("excerpt") or item.get("snippet")
            references.append(
                ProviderToolReference(
                    kind="url",
                    uri=uri[:4096],
                    title=title[:1000] if isinstance(title, str) else None,
                    excerpt=excerpt[:4000] if isinstance(excerpt, str) else None,
                    metadata={},
                )
            )
        pending.extend(
            (nested, depth + 1)
            for key, nested in item.items()
            if key not in {"encrypted_content", "signature", "thought_signature"}
            and isinstance(nested, dict | list)
        )
    return references


def _visible_tool_content(value: object) -> object:
    """Keep search/result text readable without displaying encrypted payloads."""
    if isinstance(value, bytes | BinaryContent):
        return "[non-text provider output]"
    if isinstance(value, list):
        return [_visible_tool_content(nested) for nested in value]
    if is_string_object_dict(value):
        return {
            key: _visible_tool_content(nested)
            for key, nested in value.items()
            if key not in {"encrypted_content", "signature", "thought_signature"}
        }
    return value


def _safe_native_item(item: dict[str, object]) -> dict[str, object]:
    """Retain SDK metadata while excluding known transient generated-file bytes."""
    values = dict(item)
    if values.get("type") == "image_generation_call":
        values.pop("result", None)
        values.pop("partial_image_b64", None)
    if values.get("type") in {"image", "document", "audio", "video"}:
        source = _dict(values.get("source"))
        if source.get("type") == "base64":
            values["source"] = {
                key: value for key, value in source.items() if key != "data"
            }
    return values


def _dict(value: object) -> dict[str, object]:
    return value if is_string_object_dict(value) else {}


def _int(value: object) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def _first_int(*values: int | None) -> int | None:
    return next((value for value in values if value is not None), None)
