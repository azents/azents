"""LiteLLM Responses adapter."""

import asyncio
import base64
import contextlib
import dataclasses
import datetime
import os
from collections.abc import AsyncIterable, AsyncIterator, Awaitable, Sequence
from typing import Any, Protocol, cast, runtime_checkable

from azcommon.uuid import uuid7
from litellm.exceptions import OpenAIError as LiteLLMOpenAIError
from litellm.responses.main import aresponses
from litellm.types.llms.openai import ResponseAPIUsage, ResponsesAPIResponse
from openai import OpenAIError as OpenAIBaseError
from openai.types.responses.tool_param import ToolParam
from openai.types.shared_params.reasoning import Reasoning
from pydantic import TypeAdapter, ValidationError

from azents.core.enums import EventKind, LLMModelDeveloper, LLMProvider
from azents.core.llm_catalog import ModelCapabilities
from azents.engine.events.file_parts import (
    FilePartLoweringCapabilities,
    ModelFileResolver,
    lower_file_output_part,
)
from azents.engine.events.output_parts import (
    iter_output_parts,
    lower_output_to_text,
)
from azents.engine.events.protocols import (
    NativeEvent,
    NativeModelRequest,
    NormalizedAdapterOutput,
    StreamProjection,
)
from azents.engine.events.system_reminders import (
    format_compaction_summary_reminder,
    format_goal_continuation_reminder,
    format_goal_resumed_reminder,
    format_goal_updated_reminder,
    format_interrupted_reminder,
    format_system_reminder,
)
from azents.engine.events.types import (
    AssistantMessagePayload,
    Attachment,
    ClientToolCallPayload,
    ClientToolResultPayload,
    CompactionSummaryPayload,
    Event,
    EventPayload,
    FileOutputPart,
    InputContentPart,
    InputTextPart,
    InterruptedPayload,
    NativeArtifact,
    OutputContentPart,
    OutputTextPart,
    ProviderToolCallPayload,
    ProviderToolResultPayload,
    ReasoningPayload,
    RunMarkerPayload,
    SystemReminderPayload,
    TokenUsagePayload,
    ToolOutput,
    ToolOutputPart,
    UnknownAdapterOutputPayload,
    UserContentPart,
    UserMessagePayload,
    build_native_compat_key,
)
from azents.engine.run.errors import ModelCallError
from azents.engine.run.types import BuiltinToolSpec

_DEFAULT_INSTRUCTIONS = "You are a helpful assistant."
_TOOLS_ADAPTER: TypeAdapter[list[ToolParam]] = TypeAdapter(list[ToolParam])
_REASONING_ADAPTER: TypeAdapter[Reasoning] = TypeAdapter(Reasoning)


def _format_goal_updated_event_reminder(payload: UserMessagePayload) -> str:
    """Render model-visible reminder for goal_updated event metadata."""
    if payload.metadata.get("goal_control_action") == "resume":
        return format_goal_resumed_reminder(
            goal_objective=payload.metadata.get("goal_objective"),
            previous_goal_status=payload.metadata.get("previous_goal_status"),
            resume_hint=payload.metadata.get("resume_hint"),
        )
    return format_goal_updated_reminder(payload.metadata.get("goal_objective"))


@runtime_checkable
class _ModelDumpable(Protocol):
    """Object supporting Pydantic-style model_dump."""

    def model_dump(self) -> dict[str, object]:
        """Convert object to dict."""
        ...


@runtime_checkable
class _StatusCodeError(Protocol):
    """Provider error with HTTP status_code."""

    status_code: int | None


@runtime_checkable
class _ResponseEventWithResponse(Protocol):
    """Responses event with response payload."""

    response: ResponsesAPIResponse | dict[str, object]


class _StreamingLoggingObject(Protocol):
    """LiteLLM streaming iterator logging object."""

    success_handler: Any
    async_success_handler: Any


class UnsupportedRequiredBuiltinToolError(ValueError):
    """Raised when adapter does not support required builtin tool."""


class LiteLLMResponsesLowerer:
    """Lower Event transcript to LiteLLM Responses request."""

    adapter = "litellm"
    native_format = "responses"
    schema_version = "1"

    def __init__(
        self,
        *,
        provider: str,
        model: str,
        tools: Sequence[dict[str, object]] | None = None,
        kwargs: dict[str, object] | None = None,
        provider_id: LLMProvider | None = None,
        credential_kwargs: dict[str, object] | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
        top_p: float | None = None,
        stop: list[str] | None = None,
        reasoning_effort: str | None = None,
        hosted_tools: Sequence[BuiltinToolSpec] | None = None,
        model_developer: LLMModelDeveloper | None = None,
        model_capabilities: ModelCapabilities | None = None,
        model_file_resolver: ModelFileResolver | None = None,
    ) -> None:
        """Set lowerer target provider/model."""
        self.provider = provider
        self.model = model
        self._tools = list(tools or [])
        self._extra_kwargs = dict(kwargs or {})
        self._provider_id = provider_id
        self._credential_kwargs = dict(credential_kwargs or {})
        self._temperature = temperature
        self._max_tokens = max_tokens
        self._top_p = top_p
        self._stop = list(stop) if stop is not None else None
        self._reasoning_effort = reasoning_effort
        self._hosted_tools = list(hosted_tools or [])
        self._model_developer = model_developer
        self._model_capabilities = model_capabilities or ModelCapabilities()
        self._file_part_capabilities = (
            FilePartLoweringCapabilities.from_model_capabilities(
                self._model_capabilities
            )
        )
        self._model_file_resolver = model_file_resolver
        self.compat_key = build_native_compat_key(
            adapter=self.adapter,
            native_format=self.native_format,
            provider=provider,
            model=model,
            schema_version=self.schema_version,
        )

    def lower(
        self,
        transcript: Sequence[Event],
        *,
        model: str,
        system_prompt: str | None = None,
    ) -> NativeModelRequest:
        """Convert Event transcript to LiteLLM Responses request."""
        input_items: list[dict[str, object]] = []
        kwargs = self._lower_model_kwargs()
        default_instructions = kwargs.get("instructions") or _DEFAULT_INSTRUCTIONS
        kwargs["instructions"] = system_prompt or str(default_instructions)

        for event in transcript:
            native_item = self._compatible_native_item(event)
            if native_item is not None:
                if kwargs.get("store") is False:
                    # With store=False, provider response items are not persisted;
                    # replaying ids like rs_... can resolve missing items.
                    # Keep call_id for tool continuity.
                    native_item = _drop_provider_item_id_for_unstored_request(
                        native_item
                    )
                input_items.append(native_item)
                continue

            lowered = self._lower_event(event)
            if lowered is not None:
                input_items.append(lowered)

        input_items = _drop_orphan_tool_outputs(input_items)
        hosted = _lower_hosted_tools(
            self._hosted_tools,
            provider=self.provider,
            provider_id=self._provider_id,
            model_developer=self._model_developer,
            model_capabilities=self._model_capabilities,
        )
        tools = [*self._tools, *hosted.tools]
        kwargs.update(hosted.kwargs)
        return NativeModelRequest(
            model=model,
            input=input_items,
            tools=tools,
            kwargs=kwargs,
        )

    def _lower_model_kwargs(self) -> dict[str, object]:
        """Lower RunRequest model options to LiteLLM Responses kwargs."""
        kwargs: dict[str, object] = dict(self._credential_kwargs)
        if self._provider_id in {LLMProvider.OPENAI, LLMProvider.CHATGPT_OAUTH}:
            kwargs.setdefault("custom_llm_provider", "openai")
            base_url = kwargs.get("base_url") or kwargs.get("api_base")
            if base_url is None and self._provider_id == LLMProvider.OPENAI:
                base_url = os.environ.get("AZ_OPENAI_BASE_URL")
            if base_url is not None:
                kwargs.setdefault("base_url", base_url)
                kwargs.setdefault("api_base", base_url)
        if self._provider_id == LLMProvider.CHATGPT_OAUTH:
            kwargs.setdefault("store", False)
        if self._temperature is not None:
            kwargs["temperature"] = self._temperature
        if self._max_tokens is not None:
            kwargs["max_output_tokens"] = self._max_tokens
        if self._top_p is not None:
            kwargs["top_p"] = self._top_p
        if self._stop is not None:
            kwargs["stop"] = self._stop
        if self._reasoning_effort is not None:
            kwargs["reasoning"] = {"effort": self._reasoning_effort, "summary": "auto"}
        kwargs.update(self._extra_kwargs)
        return kwargs

    def _compatible_native_item(
        self,
        event: Event,
    ) -> dict[str, object] | None:
        """Return raw item that can be replayed same-native."""
        match event.payload:
            case (
                AssistantMessagePayload(native_artifact=artifact)
                | ReasoningPayload(native_artifact=artifact)
                | ClientToolCallPayload(native_artifact=artifact)
                | ProviderToolCallPayload(native_artifact=artifact)
                | ProviderToolResultPayload(native_artifact=artifact)
                | UnknownAdapterOutputPayload(native_artifact=artifact)
            ):
                if artifact.compatible_with(self.compat_key):
                    return artifact.item
            case _:
                pass
        return None

    def _lower_event(self, event: Event) -> dict[str, object] | None:
        """Lower one Event to native input item."""
        if event.kind == EventKind.GOAL_CONTINUATION and isinstance(
            event.payload, UserMessagePayload
        ):
            return {
                "role": "user",
                "content": format_goal_continuation_reminder(
                    event.payload.metadata.get("goal_objective")
                ),
            }
        if event.kind == EventKind.GOAL_UPDATED and isinstance(
            event.payload, UserMessagePayload
        ):
            return {
                "role": "user",
                "content": _format_goal_updated_event_reminder(event.payload),
            }
        match event.payload:
            case UserMessagePayload(content=content, attachments=attachments):
                return {
                    "role": "user",
                    "content": _lower_user_message_content(
                        content,
                        attachments,
                        capabilities=self._file_part_capabilities,
                        model_file_resolver=self._model_file_resolver,
                    ),
                }
            case AssistantMessagePayload(content=content):
                return {"role": "assistant", "content": _lower_output_content(content)}
            case ProviderToolCallPayload(name=name, arguments=arguments):
                return {
                    "role": "assistant",
                    "content": _provider_tool_call_text(name, arguments),
                }
            case ProviderToolResultPayload(name=name, status=status, output=output):
                return {
                    "role": "assistant",
                    "content": _provider_tool_result_text(name, status, output),
                }
            case ClientToolCallPayload(call_id=call_id, name=name, arguments=args):
                return {
                    "type": "function_call",
                    "call_id": call_id,
                    "name": name,
                    "arguments": args,
                }
            case ClientToolResultPayload(call_id=call_id, output=output):
                return {
                    "type": "function_call_output",
                    "call_id": call_id,
                    "output": self._lower_tool_output(output),
                }
            case CompactionSummaryPayload(content=content):
                return {
                    "role": "user",
                    "content": format_compaction_summary_reminder(content),
                }
            case InterruptedPayload():
                return {
                    "role": "user",
                    "content": format_interrupted_reminder(),
                }
            case SystemReminderPayload(text=text):
                return {
                    "role": "user",
                    "content": format_system_reminder(
                        reminder_type="system_reminder",
                        instruction=text,
                        data=(),
                    ),
                }
            case RunMarkerPayload():
                return None
            case ReasoningPayload():
                return None
            case _:
                return None

    def _lower_tool_output(self, output: ToolOutput) -> str | list[dict[str, object]]:
        """Lower Tool output to Responses function_call_output payload."""
        return _lower_tool_output(
            output,
            capabilities=self._file_part_capabilities,
            model_file_resolver=self._model_file_resolver,
        )


@dataclasses.dataclass(frozen=True)
class _HostedToolLowering:
    """Hosted tool lowering result."""

    tools: list[dict[str, object]]
    kwargs: dict[str, object]


def _lower_hosted_tools(
    hosted_tools: Sequence[BuiltinToolSpec],
    *,
    provider: str,
    provider_id: LLMProvider | None,
    model_developer: LLMModelDeveloper | None,
    model_capabilities: ModelCapabilities,
) -> _HostedToolLowering:
    """Lower semantic hosted tool settings to LiteLLM native request surface."""
    native_tools: list[dict[str, object]] = []
    kwargs: dict[str, object] = {}
    supported = set(model_capabilities.built_in_tools.supported)
    target = _hosted_tool_target(
        provider=provider,
        provider_id=provider_id,
        model_developer=model_developer,
    )

    for tool in hosted_tools:
        if tool.name != "web_search":
            continue
        if tool.name not in supported:
            msg = f"Required builtin tool is not supported: {tool.name}"
            raise UnsupportedRequiredBuiltinToolError(msg)
        config = dict(tool.config)
        match target:
            case "openai":
                native_tools.append({"type": "web_search", **config})
            case "google":
                native_tools.append({"google_search": config})
            case "anthropic":
                native_tools.append(
                    {"type": "web_search_20250305", "name": "web_search", **config}
                )
            case "fallback":
                msg = f"Required builtin tool is not supported: {tool.name}"
                raise UnsupportedRequiredBuiltinToolError(msg)
            case _:
                msg = f"Required builtin tool is not supported: {tool.name}"
                raise UnsupportedRequiredBuiltinToolError(msg)

    return _HostedToolLowering(tools=native_tools, kwargs=kwargs)


def _hosted_tool_target(
    *,
    provider: str,
    provider_id: LLMProvider | None,
    model_developer: LLMModelDeveloper | None,
) -> str:
    """Choose hosted tool lowering target from provider/model developer pair."""
    if provider_id in {LLMProvider.OPENAI, LLMProvider.CHATGPT_OAUTH}:
        return "openai"
    if model_developer == LLMModelDeveloper.GOOGLE:
        return "google"
    if model_developer == LLMModelDeveloper.ANTHROPIC:
        return "anthropic"
    if provider in {"openai", "chatgpt_oauth"}:
        return "openai"
    if provider in {"google_gemini", "google_vertex_ai"}:
        return "google"
    if provider == "anthropic":
        return "anthropic"
    return "fallback"


class LiteLLMEvent(NativeEvent):
    """LiteLLM Responses native stream event."""


class LiteLLMResponsesModelAdapter:
    """LiteLLM Responses streaming transport."""

    async def stream(
        self,
        request: NativeModelRequest,
    ) -> AsyncIterator[LiteLLMEvent]:
        """Return LiteLLM Responses stream as LiteLLM event wrapper."""
        kwargs = {
            "model": request.model,
            "input": request.input,
            "tools": request.tools,
            **request.kwargs,
            "stream": True,
        }
        response: object | None = None
        try:
            response = await _call_litellm_responses(request, kwargs)
            if not isinstance(response, AsyncIterable):
                raise RuntimeError(
                    "LiteLLM Responses call returned non-streaming response"
                )
            guard_litellm_streaming_logging(response)
            async for event in response:
                coerce_litellm_completed_response_for_logging(event)
                if isinstance(event, _ModelDumpable):
                    yield LiteLLMEvent(
                        type=event.__class__.__name__,
                        item=event.model_dump(),
                    )
                else:
                    yield LiteLLMEvent(type=event.__class__.__name__, item={})
        except asyncio.CancelledError:
            await _close_stream_response(response)
            raise
        except (LiteLLMOpenAIError, OpenAIBaseError) as exc:
            # LiteLLM retry finishes inside aresponses, then
            # only final provider errors arrive here.
            if not _is_user_visible_provider_error(exc):
                raise
            raise ModelCallError(_format_model_call_error(exc)) from exc


async def _close_stream_response(response: object | None) -> None:
    """Call provider stream response close hook best-effort."""
    if response is None:
        return
    close = getattr(response, "aclose", None) or getattr(response, "close", None)
    if not callable(close):
        return
    with contextlib.suppress(Exception):
        result = close()
        if isinstance(result, Awaitable):
            await result


async def _call_litellm_responses(
    request: NativeModelRequest,
    kwargs: dict[str, object],
) -> object:
    """Call LiteLLM Responses API."""
    tools: Any | None = None
    if request.tools:
        if _contains_provider_hosted_tool(request.tools):
            _validate_non_hosted_tools(request.tools)
            tools = request.tools
        else:
            tools = _TOOLS_ADAPTER.validate_python(request.tools)
    extra_kwargs = _extra_litellm_kwargs(kwargs)
    input_items: Any = request.input
    return await aresponses(
        input=input_items,
        model=request.model,
        tools=tools,
        stream=True,
        instructions=_optional_str(kwargs, "instructions"),
        max_output_tokens=_optional_int(kwargs, "max_output_tokens"),
        reasoning=_optional_reasoning(kwargs, "reasoning"),
        store=_optional_bool(kwargs, "store"),
        temperature=_optional_float(kwargs, "temperature"),
        top_p=_optional_float(kwargs, "top_p"),
        custom_llm_provider=_optional_str(kwargs, "custom_llm_provider"),
        api_key=_optional_str(kwargs, "api_key"),
        base_url=_optional_str(kwargs, "base_url"),
        api_base=_optional_str(kwargs, "api_base"),
        stop=_optional_stop(kwargs, "stop"),
        **extra_kwargs,
    )


def _contains_provider_hosted_tool(tools: Sequence[dict[str, object]]) -> bool:
    """Check whether hosted tool shape fails OpenAI ToolParam validation."""
    return any(_is_provider_hosted_tool(tool) for tool in tools)


def _is_provider_hosted_tool(tool: dict[str, object]) -> bool:
    """Check whether shape is provider-hosted tool native shape."""
    tool_type = tool.get("type")
    return "google_search" in tool or tool_type in {
        "web_search_20250305",
        "web_fetch_20250910",
    }


def _validate_non_hosted_tools(tools: Sequence[dict[str, object]]) -> None:
    """Continue validating normal tool shapes passed with hosted tools."""
    non_hosted_tools = [tool for tool in tools if not _is_provider_hosted_tool(tool)]
    if non_hosted_tools:
        _TOOLS_ADAPTER.validate_python(non_hosted_tools)


def _extra_litellm_kwargs(kwargs: dict[str, object]) -> dict[str, Any]:
    """Return passthrough kwargs excluding kwargs already passed as explicit args."""
    excluded = {
        "input",
        "instructions",
        "max_output_tokens",
        "model",
        "reasoning",
        "store",
        "stream",
        "temperature",
        "top_p",
        "tools",
        "custom_llm_provider",
        "api_key",
        "base_url",
        "api_base",
        "stop",
    }
    return {key: value for key, value in kwargs.items() if key not in excluded}


def _optional_str(kwargs: dict[str, object], key: str) -> str | None:
    """Return optional string kwarg."""
    value = kwargs.get(key)
    if value is None:
        return None
    if isinstance(value, str):
        return value
    raise TypeError(f"LiteLLM kwarg {key} must be str")


def _drop_orphan_tool_outputs(
    input_items: Sequence[dict[str, object]],
) -> list[dict[str, object]]:
    """Remove function_call_output without matching function_call."""
    seen_calls: set[str] = set()
    filtered: list[dict[str, object]] = []
    for item in input_items:
        item_type = item.get("type")
        call_id = item.get("call_id")
        if item_type == "function_call" and isinstance(call_id, str):
            seen_calls.add(call_id)
            filtered.append(item)
            continue
        if item_type == "function_call_output" and isinstance(call_id, str):
            if call_id in seen_calls:
                filtered.append(item)
            continue
        filtered.append(item)
    return filtered


def _drop_provider_item_id_for_unstored_request(
    item: dict[str, object],
) -> dict[str, object]:
    """Remove provider item id from native replay when response items are unstored."""
    if "id" not in item:
        return item
    normalized = dict(item)
    normalized.pop("id", None)
    return normalized


def _optional_bool(kwargs: dict[str, object], key: str) -> bool | None:
    """Return optional bool kwarg."""
    value = kwargs.get(key)
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    raise TypeError(f"LiteLLM kwarg {key} must be bool")


def _optional_int(kwargs: dict[str, object], key: str) -> int | None:
    """Return optional int kwarg."""
    value = kwargs.get(key)
    if value is None:
        return None
    if isinstance(value, int) and not isinstance(value, bool):
        return value
    raise TypeError(f"LiteLLM kwarg {key} must be int")


def _optional_float(kwargs: dict[str, object], key: str) -> float | None:
    """Return optional float kwarg."""
    value = kwargs.get(key)
    if value is None:
        return None
    if isinstance(value, bool):
        raise TypeError(f"LiteLLM kwarg {key} must be float")
    if isinstance(value, int | float):
        return float(value)
    raise TypeError(f"LiteLLM kwarg {key} must be float")


def _optional_reasoning(kwargs: dict[str, object], key: str) -> Reasoning | None:
    """Return optional reasoning kwarg."""
    value = kwargs.get(key)
    if value is None:
        return None
    return _REASONING_ADAPTER.validate_python(value)


def _optional_stop(kwargs: dict[str, object], key: str) -> str | list[str] | None:
    """Return optional stop kwarg."""
    value = kwargs.get(key)
    if value is None:
        return None
    if isinstance(value, str):
        return value
    if isinstance(value, list) and all(isinstance(item, str) for item in value):
        return value
    raise TypeError(f"LiteLLM kwarg {key} must be str or list[str]")


def _format_model_call_error(exc: Exception) -> str:
    """Convert LiteLLM/OpenAI provider error to user-visible message."""
    status_code = exc.status_code if isinstance(exc, _StatusCodeError) else None
    message = str(exc)
    if status_code is None:
        return f"Model call failed: {message}"
    return f"Model call failed ({status_code}): {message}"


def _is_user_visible_provider_error(exc: Exception) -> bool:
    """Check whether final provider error is user-visible."""
    if not isinstance(exc, _StatusCodeError):
        return False
    status_code = exc.status_code
    return status_code in {401, 403, 429} or (
        status_code is not None and 500 <= status_code <= 599
    )


def guard_litellm_streaming_logging(response: AsyncIterable[object]) -> None:
    """Repair model_construct fallback dict of LiteLLM Responses stream logger."""
    logging_obj = getattr(response, "logging_obj", None)
    if logging_obj is None:
        return
    logging_obj = cast(_StreamingLoggingObject, logging_obj)
    original_success_handler = getattr(logging_obj, "success_handler", None)
    original_async_success_handler = getattr(
        logging_obj,
        "async_success_handler",
        None,
    )

    # LiteLLM keeps streaming chunks usable by falling back to model_construct()
    # when a Responses event fails pydantic validation. That fallback leaves the
    # nested response payload as a dict, while LiteLLM's own success loggers read
    # result.response.usage via attribute access. Coerce only the object passed to
    # LiteLLM logging; event normalization still uses model_dump() output.
    def guarded_success_handler(
        result: object = None,
        start_time: object = None,
        end_time: object = None,
        cache_hit: object = None,
        **kwargs: object,
    ) -> object:
        coerce_litellm_completed_response_for_logging(result)
        if original_success_handler is None:
            return None
        return original_success_handler(
            result=result,
            start_time=start_time,
            end_time=end_time,
            cache_hit=cache_hit,
            **kwargs,
        )

    async def guarded_async_success_handler(
        result: object = None,
        start_time: object = None,
        end_time: object = None,
        cache_hit: object = None,
        **kwargs: object,
    ) -> object:
        coerce_litellm_completed_response_for_logging(result)
        if original_async_success_handler is None:
            return None
        return await original_async_success_handler(
            result=result,
            start_time=start_time,
            end_time=end_time,
            cache_hit=cache_hit,
            **kwargs,
        )

    if original_success_handler is not None:
        logging_obj.success_handler = guarded_success_handler
    if original_async_success_handler is not None:
        logging_obj.async_success_handler = guarded_async_success_handler


def coerce_litellm_completed_response_for_logging(
    completed_response: object | None,
) -> None:
    """Restore nested response dict before LiteLLM logging."""
    if not isinstance(completed_response, _ResponseEventWithResponse):
        return
    response = completed_response.response
    if isinstance(response, ResponsesAPIResponse):
        return
    if isinstance(response, dict):
        completed_response.response = _responses_api_response_from_dict(response)


def _responses_api_response_from_dict(
    response: dict[str, object],
) -> ResponsesAPIResponse:
    """Ensure usage attribute access even in validation failure fallback payload."""
    try:
        return ResponsesAPIResponse.model_validate(response)
    except ValidationError:
        normalized = dict(response)
        constructed = ResponsesAPIResponse.model_construct(
            _fields_set=set(normalized),
            id=str(normalized.get("id") or ""),
            created_at=_int_or_zero(normalized.get("created_at")),
            output=_list_or_empty(normalized.get("output")),
            usage=_response_api_usage_or_none(normalized.get("usage")),
        )
        for key, value in normalized.items():
            if key not in {"id", "created_at", "output", "usage"}:
                setattr(constructed, key, value)
        return constructed


def _response_api_usage_or_none(value: object) -> ResponseAPIUsage | None:
    """Convert dict usage, but exclude invalid usage from logging."""
    if isinstance(value, ResponseAPIUsage):
        return value
    if not isinstance(value, dict):
        return None
    try:
        return ResponseAPIUsage.model_validate(value)
    except ValidationError:
        return None


def _list_or_empty(value: object) -> list[object]:
    """Safely return Responses output list."""
    if isinstance(value, list):
        return value
    return []


def _int_or_zero(value: object) -> int:
    """Return Responses created_at value as int."""
    if isinstance(value, int) and not isinstance(value, bool):
        return value
    return 0


class LiteLLMResponsesOutputNormalizer:
    """Normalize LiteLLM Responses native output to event."""

    adapter = "litellm"
    native_format = "responses"
    schema_version = "1"

    def __init__(self, *, provider: str, model: str) -> None:
        """Set normalizer origin provider/model."""
        self.provider = provider
        self.model = model
        self.compat_key = build_native_compat_key(
            adapter=self.adapter,
            native_format=self.native_format,
            provider=provider,
            model=model,
            schema_version=self.schema_version,
        )

    def normalize(
        self,
        session_id: str,
        native_events: Sequence[NativeEvent],
    ) -> NormalizedAdapterOutput:
        """Convert native stream events to events and UI projection."""
        projections: list[StreamProjection] = []
        events: list[Event] = []
        tool_refs: dict[int, tuple[str, str]] = {}
        completed_output_items: list[dict[str, object]] = []
        completed_response_seen = False
        usage: TokenUsagePayload | None = None

        for native_event in native_events:
            event_type = native_event.type
            item = native_event.item
            if event_type in {"OutputTextDeltaEvent", "ResponseTextDeltaEvent"}:
                projections.append(
                    StreamProjection(
                        type="content_delta",
                        delta=str(item.get("delta", "")),
                    )
                )
            elif event_type in {"OutputItemAddedEvent", "ResponseOutputItemAddedEvent"}:
                output_index = _int_or_none(item.get("output_index"))
                raw_item = _dict(item.get("item"))
                if raw_item.get("type") == "function_call" and output_index is not None:
                    call_id = str(raw_item.get("call_id") or raw_item.get("id") or "")
                    name = str(raw_item.get("name") or "")
                    tool_refs[output_index] = (call_id, name)
                    projections.append(
                        StreamProjection(
                            type="function_call_delta",
                            index=output_index,
                            call_id=call_id,
                            name=name,
                            delta="",
                        )
                    )
            elif event_type in {"OutputItemDoneEvent", "ResponseOutputItemDoneEvent"}:
                raw_item = _dict(item.get("item"))
                if _has_output_item_type(raw_item):
                    completed_output_items.append(raw_item)
            elif event_type in {
                "FunctionCallArgumentsDeltaEvent",
                "ResponseFunctionCallArgumentsDeltaEvent",
            }:
                output_index = _int_or_none(item.get("output_index"))
                call_id, name = tool_refs.get(output_index or -1, (None, None))
                projections.append(
                    StreamProjection(
                        type="function_call_delta",
                        index=output_index,
                        call_id=call_id,
                        name=name,
                        delta=str(item.get("delta", "")),
                    )
                )
            elif event_type in {
                "ReasoningSummaryTextDeltaEvent",
                "ResponseReasoningSummaryTextDeltaEvent",
            }:
                projections.append(
                    StreamProjection(
                        type="reasoning_delta",
                        delta=str(item.get("delta", "")),
                    )
                )
            elif event_type == "ResponseCompletedEvent":
                completed_response_seen = True
                response = _dict(item.get("response"))
                usage = _normalize_response_usage(response) or usage
                events.extend(
                    self._normalize_completed(
                        session_id,
                        response,
                        completed_output_items,
                    )
                )

        if not completed_response_seen and completed_output_items:
            events.extend(
                self._normalize_output_items(session_id, completed_output_items)
            )

        return NormalizedAdapterOutput(
            events=events,
            projections=projections,
            usage=usage,
        )

    def _normalize_completed(
        self,
        session_id: str,
        response: dict[str, object],
        completed_output_items: Sequence[dict[str, object]],
    ) -> list[Event]:
        """Convert completed response output item to event."""
        output = response.get("output")
        if isinstance(output, list) and output:
            return self._normalize_output_items(session_id, output)
        return self._normalize_output_items(session_id, completed_output_items)

    def _normalize_output_items(
        self,
        session_id: str,
        output_items: Sequence[object],
    ) -> list[Event]:
        """Convert output item list to events."""
        events: list[Event] = []
        for output_item in output_items:
            raw_item = _dict(output_item)
            if _has_output_item_type(raw_item):
                events.append(self._normalize_output_item(session_id, raw_item))
        return events

    def _normalize_output_item(
        self,
        session_id: str,
        output_item: dict[str, object],
    ) -> Event:
        """Convert one output item to event."""
        item_type = str(output_item.get("type") or "")
        artifact = self._artifact(output_item)

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
                native_artifact=artifact,
            )
            return _event(session_id, EventKind.CLIENT_TOOL_CALL, payload)
        if item_type in {"web_search_call", "web_search"}:
            call_id = str(output_item.get("call_id") or output_item.get("id") or "")
            payload = ProviderToolCallPayload(
                call_id=call_id,
                name="web_search",
                arguments=None,
                native_artifact=artifact,
            )
            return _event(session_id, EventKind.PROVIDER_TOOL_CALL, payload)
        if item_type == "image_generation_call":
            call_id = str(
                output_item.get("call_id") or output_item.get("id") or uuid7().hex
            )
            payload = ProviderToolResultPayload(
                call_id=call_id,
                name="image_generation",
                status="completed",
                output=_image_generation_output(output_item),
                attachments=_image_generation_attachments(output_item),
                native_artifact=artifact,
            )
            return _event(session_id, EventKind.PROVIDER_TOOL_RESULT, payload)

        return _event(
            session_id,
            EventKind.UNKNOWN_ADAPTER_OUTPUT,
            UnknownAdapterOutputPayload(
                native_artifact=artifact,
                reason=item_type or None,
            ),
        )

    def _artifact(self, item: dict[str, object]) -> NativeArtifact:
        """Create native artifact."""
        return NativeArtifact(
            compat_key=self.compat_key,
            adapter=self.adapter,
            native_format=self.native_format,
            provider=self.provider,
            model=self.model,
            schema_version=self.schema_version,
            item=_sanitize_native_item(item),
        )


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
    raw_usage = _dict(response.get("usage"))
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
        _int_or_none(_dict(raw_usage.get("input_tokens_details")).get("cached_tokens")),
        _int_or_none(
            _dict(raw_usage.get("prompt_tokens_details")).get("cached_tokens")
        ),
    )
    cache_creation_tokens = _first_int(
        _int_or_none(raw_usage.get("cache_creation_tokens")),
        _int_or_none(raw_usage.get("cache_creation_input_tokens")),
        _int_or_none(
            _dict(raw_usage.get("input_tokens_details")).get("cache_creation_tokens")
        ),
        _int_or_none(
            _dict(raw_usage.get("prompt_tokens_details")).get("cache_creation_tokens")
        ),
    )
    reasoning_tokens = _first_int(
        _int_or_none(raw_usage.get("reasoning_tokens")),
        _int_or_none(
            _dict(raw_usage.get("output_tokens_details")).get("reasoning_tokens")
        ),
        _int_or_none(
            _dict(raw_usage.get("completion_tokens_details")).get("reasoning_tokens")
        ),
    )
    cost_usd = _first_float(
        _float_or_none(raw_usage.get("cost_usd")),
        _float_or_none(raw_usage.get("cost")),
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


def _lower_input_content(
    content: str | list[UserContentPart],
    *,
    capabilities: FilePartLoweringCapabilities | None = None,
    model_file_resolver: ModelFileResolver | None = None,
) -> str | list[dict[str, object]]:
    """Convert Event input content to native content."""
    if isinstance(content, str):
        return content
    return [
        _lower_user_content_part(
            part,
            capabilities=capabilities,
            model_file_resolver=model_file_resolver,
        )
        for part in content
    ]


def _lower_user_message_content(
    content: str | list[UserContentPart],
    attachments: Sequence[Attachment],
    *,
    capabilities: FilePartLoweringCapabilities | None = None,
    model_file_resolver: ModelFileResolver | None = None,
) -> str | list[dict[str, object]]:
    """Convert user message content and attachment context to native content."""
    attachment_context = _attachment_context(attachments)
    if attachment_context is None:
        return _lower_input_content(
            content,
            capabilities=capabilities,
            model_file_resolver=model_file_resolver,
        )
    if isinstance(content, str):
        return [
            {"type": "input_text", "text": content},
            {"type": "input_text", "text": attachment_context},
        ]
    return [
        *[
            _lower_user_content_part(
                part,
                capabilities=capabilities,
                model_file_resolver=model_file_resolver,
            )
            for part in content
        ],
        {"type": "input_text", "text": attachment_context},
    ]


def _attachment_context(attachments: Sequence[Attachment]) -> str | None:
    """Render attachment metadata as model-visible context text."""
    if not attachments:
        return None
    lines = ["[Attachments]"]
    for attachment in attachments:
        lines.append(f"- {attachment.name} ({attachment.media_type}, {attachment.uri})")
        if attachment.availability != "available":
            lines.append(f"  Status: {attachment.availability}; no longer accessible")
        if attachment.preview_title is not None:
            lines.append(f"  Preview title: {attachment.preview_title}")
        if attachment.preview_summary is not None:
            lines.append(f"```\n{attachment.preview_summary}\n```")
    return "\n".join(lines)


def _lower_user_content_part(
    part: UserContentPart,
    *,
    capabilities: FilePartLoweringCapabilities | None = None,
    model_file_resolver: ModelFileResolver | None = None,
) -> dict[str, object]:
    """Convert Event user content part to OpenAI Responses content part."""
    if isinstance(part, FileOutputPart):
        return lower_file_output_part(
            part,
            capabilities=capabilities or FilePartLoweringCapabilities(),
            resolver=model_file_resolver,
        )
    return _lower_input_part(part)


def _lower_input_part(part: InputContentPart) -> dict[str, object]:
    """Convert Event input part to OpenAI Responses content part."""
    match part:
        case InputTextPart(text=text):
            return {"type": "input_text", "text": text}
        case _:
            return part.model_dump(mode="json", exclude_none=True)


def _lower_output_content(content: str | list[OutputContentPart]) -> str:
    """Convert Event output content to assistant text."""
    if isinstance(content, str):
        return content
    texts: list[str] = []
    for part in content:
        if isinstance(part, OutputTextPart):
            texts.append(part.text)
    return "\n".join(texts)


def _lower_tool_output(
    output: ToolOutput,
    *,
    capabilities: FilePartLoweringCapabilities | None = None,
    model_file_resolver: ModelFileResolver | None = None,
) -> str | list[dict[str, object]]:
    """Convert Tool output to Responses function_call_output payload."""
    if isinstance(output, str):
        return output
    lowered_parts: list[dict[str, object]] = []
    has_rich_or_placeholder = False
    file_capabilities = capabilities or FilePartLoweringCapabilities()
    for part in iter_output_parts(output):
        if isinstance(part, OutputTextPart):
            lowered_parts.append({"type": "input_text", "text": part.text})
            continue
        if isinstance(part, FileOutputPart):
            lowered = lower_file_output_part(
                part,
                capabilities=file_capabilities,
                resolver=model_file_resolver,
            )
            lowered_parts.append(lowered)
            has_rich_or_placeholder = True
            continue
        text = lower_output_to_text([part])
        if text:
            lowered_parts.append({"type": "input_text", "text": text})
    if has_rich_or_placeholder:
        return lowered_parts
    return lower_output_to_text(output)


def _provider_tool_call_text(name: str, arguments: str | None) -> str:
    """Lower unsupported provider tool call to model-visible transcript."""
    rendered_arguments = arguments or ""
    return f"[provider tool call] {name}({rendered_arguments})"


def _provider_tool_result_text(
    name: str | None,
    status: str,
    output: ToolOutput,
) -> str:
    """Lower unsupported provider tool result to model-visible transcript."""
    rendered_name = name or "unknown"
    rendered_output = lower_output_to_text(output)
    if not rendered_output:
        return f"[provider tool result] {rendered_name}: {status}"
    return f"[provider tool result] {rendered_name}: {status}\n{rendered_output}"


def _extract_message_text(item: dict[str, object]) -> str:
    """Extract text from Responses message item."""
    content = item.get("content")
    if not isinstance(content, list):
        return ""
    parts: list[str] = []
    for part in content:
        part_dict = _dict(part)
        text = part_dict.get("text")
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
        text = _dict(part).get("text")
        if isinstance(text, str) and text:
            parts.append(text)
    return "\n".join(parts)


def _image_generation_output(item: dict[str, object]) -> list[ToolOutputPart]:
    """Create image generation output part."""
    result = item.get("result")
    if isinstance(result, str) and result:
        return [
            OutputTextPart(
                text=(
                    "Generated image is available as an attachment "
                    f"(id: inline:{_image_digest(result)})."
                )
            )
        ]
    return []


def _image_generation_attachments(item: dict[str, object]) -> list[Attachment]:
    """Create image generation attachment metadata."""
    result = item.get("result")
    if isinstance(result, str) and result:
        return [
            Attachment(
                attachment_id=f"inline:{_image_digest(result)}",
                uri=f"generated-image:{_image_digest(result)}",
                name="generated-image.png",
                media_type="image/png",
                size=0,
                created_at=datetime.datetime.now(datetime.UTC),
                source="provider_tool",
                availability="unavailable",
            )
        ]
    return []


def _image_digest(value: str) -> str:
    """Create short identifier for Base64 image result."""
    try:
        return base64.b64decode(value.encode(), validate=False).hex()[:32]
    except ValueError:
        return value[:32]


def _sanitize_native_item(item: dict[str, object]) -> dict[str, object]:
    """Remove durable raw blob fields from native artifact."""
    item_type = item.get("type")
    sanitized: dict[str, object] = {}
    for key, value in item.items():
        if item_type == "image_generation_call" and key == "result":
            continue
        if _raw_blob_key(key):
            continue
        sanitized[key] = _sanitize_native_value(value)
    return sanitized


def _sanitize_native_value(value: object) -> object:
    """Remove raw blob fields from nested native artifact values."""
    if isinstance(value, dict):
        return _sanitize_native_item(value)
    if isinstance(value, list):
        return [_sanitize_native_value(item) for item in value]
    return value


def _raw_blob_key(key: str) -> bool:
    """Return whether native artifact key should be treated as raw blob."""
    return key in {"file_data", "base64", "data_base64", "provider_payload"}


def _dict(value: object) -> dict[str, object]:
    """Safely return dict value."""
    if isinstance(value, dict):
        return value
    return {}


def _has_output_item_type(item: dict[str, object]) -> bool:
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
