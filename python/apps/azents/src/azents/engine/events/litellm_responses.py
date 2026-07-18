"""LiteLLM Responses adapter."""

import asyncio
import dataclasses
import logging
from collections.abc import AsyncIterable, AsyncIterator, Sequence
from typing import Any, Protocol, runtime_checkable

from litellm.exceptions import OpenAIError as LiteLLMOpenAIError
from litellm.responses.main import aresponses
from litellm.types.llms.openai import ResponseAPIUsage, ResponsesAPIResponse
from openai import OpenAIError as OpenAIBaseError
from openai.types.responses.response_includable import ResponseIncludable
from openai.types.responses.tool_param import ToolParam
from openai.types.shared_params.reasoning import Reasoning
from pydantic import TypeAdapter, ValidationError

from azents.engine.events.protocols import (
    NativeEvent,
    NativeModelRequest,
)
from azents.engine.events.responses_continuation import (
    ResponsesContinuationPlan,
    ResponsesContinuationPlanner,
)
from azents.engine.events.responses_lowering import ResponsesRequestLowerer
from azents.engine.events.responses_output import (
    ResponsesOutputNormalizer,
    has_response_output_item_type,
    response_item_dict,
)
from azents.engine.model_stream import (
    ModelStreamCallContext,
    ModelStreamTimeoutPolicy,
    ModelStreamWatchdog,
    close_stream_response,
    connect_only_http_timeout,
)
from azents.engine.run.provider_failure import (
    ModelProviderFailure,
    ModelProviderFailureCategory,
    classify_model_provider_failure,
    extract_provider_message_text,
    model_provider_failure,
    sanitize_provider_identifier,
)

_TOOLS_ADAPTER: TypeAdapter[list[ToolParam]] = TypeAdapter(list[ToolParam])
_REASONING_ADAPTER: TypeAdapter[Reasoning] = TypeAdapter(Reasoning)
_INCLUDE_ADAPTER: TypeAdapter[list[ResponseIncludable]] = TypeAdapter(
    list[ResponseIncludable]
)

logger = logging.getLogger(__name__)


@dataclasses.dataclass(frozen=True)
class _ContinuationObservation:
    """Continuation state observed from one native stream event."""

    completed_response: dict[str, object] | None
    terminal_failure: bool


@runtime_checkable
class _ModelDumpable(Protocol):
    """Object supporting Pydantic-style model_dump."""

    def model_dump(self) -> dict[str, object]:
        """Convert object to dict."""
        ...


@runtime_checkable
class _ResponseEventWithResponse(Protocol):
    """Responses event with response payload."""

    response: ResponsesAPIResponse | dict[str, object]


@runtime_checkable
class _SyncStreamingLogger(Protocol):
    """LiteLLM streaming logger with a synchronous success handler."""

    success_handler: Any


@runtime_checkable
class _AsyncStreamingLogger(Protocol):
    """LiteLLM streaming logger with an asynchronous success handler."""

    async_success_handler: Any


class LiteLLMResponsesLowerer(ResponsesRequestLowerer):
    """Lower Event transcript to a LiteLLM Responses request."""

    adapter = "litellm"


class LiteLLMEvent(NativeEvent):
    """LiteLLM Responses native stream event."""


class LiteLLMResponsesOutputNormalizer(ResponsesOutputNormalizer):
    """Normalize LiteLLM Responses native output to canonical events."""

    adapter = "litellm"


class LiteLLMResponsesModelAdapter:
    """LiteLLM Responses streaming transport."""

    def __init__(
        self,
        continuation_planner: ResponsesContinuationPlanner | None,
    ) -> None:
        self.continuation_planner = continuation_planner

    async def stream(
        self,
        request: NativeModelRequest,
        *,
        watchdog: ModelStreamWatchdog,
        timeout_policy: ModelStreamTimeoutPolicy,
        call_context: ModelStreamCallContext,
    ) -> AsyncIterator[LiteLLMEvent]:
        """Return a watched LiteLLM Responses stream as native events."""
        kwargs = {
            "model": request.model,
            "input": request.input,
            "tools": request.tools,
            **request.kwargs,
            "stream": True,
        }
        plan = self._plan(request)
        if self.continuation_planner is not None:
            self.continuation_planner.reset()

        async def call_response(active_plan: ResponsesContinuationPlan) -> object:
            if self.continuation_planner is not None:
                logger.info(
                    "Dispatching OpenAI Responses request",
                    extra={
                        "previous_response_id_supplied": (
                            active_plan.previous_response_id is not None
                        )
                    },
                )
            return await _call_litellm_responses(
                request,
                kwargs,
                input_items=active_plan.input_items,
                previous_response_id=active_plan.previous_response_id,
                connect_timeout_seconds=timeout_policy.connect_timeout_seconds,
            )

        async def open_response() -> object:
            nonlocal plan
            try:
                response = await call_response(plan)
            except (LiteLLMOpenAIError, OpenAIBaseError) as exc:
                if not (
                    plan.previous_response_id is not None
                    and _is_previous_response_not_found(exc)
                    and self.continuation_planner is not None
                ):
                    raise
                self.continuation_planner.disable()
                plan = ResponsesContinuationPlan(
                    input_items=request.input,
                    previous_response_id=None,
                )
                response = await call_response(plan)
            if isinstance(response, AsyncIterable):
                guard_litellm_streaming_logging(response)
            return response

        response: object | None = None
        completed_response: dict[str, object] | None = None
        completed_output_items: list[dict[str, object]] = []
        terminal_failure = False
        try:
            response = await watchdog.open_response(
                open_response,
                policy=timeout_policy,
                context=call_context,
            )
            if not isinstance(response, AsyncIterable):
                raise RuntimeError(
                    "LiteLLM Responses call returned non-streaming response"
                )
            async for event in response:
                coerce_litellm_completed_response_for_logging(event)
                event_type = event.__class__.__name__
                if isinstance(event, _ModelDumpable):
                    item = event.model_dump()
                    observation = _observe_continuation_event(
                        event_type,
                        item,
                        completed_response=completed_response,
                        completed_output_items=completed_output_items,
                        terminal_failure=terminal_failure,
                    )
                    completed_response = observation.completed_response
                    terminal_failure = observation.terminal_failure
                    yield LiteLLMEvent(type=event_type, item=item)
                else:
                    yield LiteLLMEvent(type=event_type, item={})
            if completed_response is not None and not terminal_failure:
                self._record_completion(
                    request,
                    completed_response=completed_response,
                    completed_output_items=completed_output_items,
                )
        except asyncio.CancelledError:
            raise
        except (LiteLLMOpenAIError, OpenAIBaseError) as exc:
            # LiteLLM retry finishes inside aresponses, then only a classified
            # provider failure crosses the Engine boundary. Unknown SDK errors
            # retain their original traceback through internal-error handling.
            failure = map_litellm_provider_error(exc, call_context=call_context)
            if failure is None:
                raise
            raise failure from None
        finally:
            await close_stream_response(response)

    def _plan(self, request: NativeModelRequest) -> ResponsesContinuationPlan:
        """Plan the physical request while retaining the full logical request."""
        if self.continuation_planner is None:
            return ResponsesContinuationPlan(
                input_items=request.input,
                previous_response_id=None,
            )
        return self.continuation_planner.plan(request)

    def _record_completion(
        self,
        request: NativeModelRequest,
        *,
        completed_response: dict[str, object],
        completed_output_items: list[dict[str, object]],
    ) -> None:
        """Record a successful terminal response for the next request."""
        if self.continuation_planner is None:
            return
        response_id = completed_response.get("id")
        if not isinstance(response_id, str) or not response_id:
            return
        raw_output = completed_response.get("output")
        output_items = (
            [item for item in raw_output if isinstance(item, dict)]
            if isinstance(raw_output, list) and raw_output
            else completed_output_items
        )
        self.continuation_planner.record_completion(
            request,
            response_id=response_id,
            output_items=output_items,
        )


def _observe_continuation_event(
    event_type: str,
    item: dict[str, object],
    *,
    completed_response: dict[str, object] | None,
    completed_output_items: list[dict[str, object]],
    terminal_failure: bool,
) -> _ContinuationObservation:
    """Observe completion data without changing normal stream delivery."""
    if event_type in {"OutputItemDoneEvent", "ResponseOutputItemDoneEvent"}:
        output_item = response_item_dict(item.get("item"))
        if has_response_output_item_type(output_item):
            completed_output_items.append(output_item)
    elif event_type == "ResponseCompletedEvent":
        completed_response = response_item_dict(item.get("response"))
    elif event_type in {
        "ResponseErrorEvent",
        "ResponseFailedEvent",
        "ResponseIncompleteEvent",
    }:
        terminal_failure = True
    return _ContinuationObservation(
        completed_response=completed_response,
        terminal_failure=terminal_failure,
    )


def _is_previous_response_not_found(exc: Exception) -> bool:
    """Match only the provider's missing stored response error code."""
    code = getattr(exc, "code", None)
    if code == "previous_response_not_found":
        return True
    body = getattr(exc, "body", None)
    if not isinstance(body, dict):
        return False
    error = body.get("error")
    return isinstance(error, dict) and error.get("code") == (
        "previous_response_not_found"
    )


async def _call_litellm_responses(
    request: NativeModelRequest,
    kwargs: dict[str, object],
    *,
    input_items: list[dict[str, object]],
    previous_response_id: str | None,
    connect_timeout_seconds: float,
) -> object:
    """Call LiteLLM Responses API."""
    tools: Any | None = None
    if request.tools:
        if _contains_provider_hosted_tool(
            request.tools
        ) or _contains_cache_control_tool(request.tools):
            _validate_non_hosted_tools(request.tools)
            tools = request.tools
        else:
            tools = _TOOLS_ADAPTER.validate_python(request.tools)
    extra_kwargs = _extra_litellm_kwargs(kwargs)
    native_input: Any = input_items
    return await aresponses(
        input=native_input,
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
        include=_optional_include(kwargs, "include"),
        previous_response_id=previous_response_id,
        timeout=connect_only_http_timeout(connect_timeout_seconds),
        **extra_kwargs,
    )


def _contains_provider_hosted_tool(tools: Sequence[dict[str, object]]) -> bool:
    """Check whether hosted tool shape fails OpenAI ToolParam validation."""
    return any(_is_provider_hosted_tool(tool) for tool in tools)


def _contains_cache_control_tool(tools: Sequence[dict[str, object]]) -> bool:
    """Check whether tool cache_control must survive Pydantic validation."""
    return any("cache_control" in tool for tool in tools)


def _is_provider_hosted_tool(tool: dict[str, object]) -> bool:
    """Check whether shape is provider-hosted tool native shape."""
    tool_type = tool.get("type")
    return "google_search" in tool or tool_type in {
        "web_search_20250305",
        "web_fetch_20250910",
    }


def _validate_non_hosted_tools(tools: Sequence[dict[str, object]]) -> None:
    """Continue validating normal tool shapes passed with hosted tools."""
    non_hosted_tools = [
        _tool_without_cache_control(tool)
        for tool in tools
        if not _is_provider_hosted_tool(tool)
    ]
    if non_hosted_tools:
        _TOOLS_ADAPTER.validate_python(non_hosted_tools)


def _tool_without_cache_control(tool: dict[str, object]) -> dict[str, object]:
    """Return a validation copy without provider-specific cache metadata."""
    if "cache_control" not in tool:
        return tool
    sanitized = dict(tool)
    sanitized.pop("cache_control", None)
    return sanitized


def _extra_litellm_kwargs(kwargs: dict[str, object]) -> dict[str, Any]:
    """Return passthrough kwargs excluding kwargs already passed as explicit args."""
    excluded = {
        "input",
        "instructions",
        "max_output_tokens",
        "model",
        "previous_response_id",
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
        "include",
        "timeout",
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
    """Return optional reasoning kwarg while preserving Lite extensions."""
    value = kwargs.get(key)
    if value is None:
        return None
    validated = _REASONING_ADAPTER.validate_python(value)
    if isinstance(value, dict) and value.get("context") == "all_turns":
        validated["context"] = "all_turns"
    return validated


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


def _optional_include(
    kwargs: dict[str, object],
    key: str,
) -> list[ResponseIncludable] | None:
    """Return optional include kwarg."""
    value = kwargs.get(key)
    if value is None:
        return None
    if isinstance(value, list) and all(isinstance(item, str) for item in value):
        return _INCLUDE_ADAPTER.validate_python(value)
    raise TypeError(f"LiteLLM kwarg {key} must be list[str]")


def map_litellm_provider_error(
    exc: LiteLLMOpenAIError | OpenAIBaseError,
    *,
    call_context: ModelStreamCallContext,
) -> ModelProviderFailure | None:
    """Map one classified SDK exception or return None for bare re-raise."""
    body = getattr(exc, "body", None)
    nested_error = body.get("error") if isinstance(body, dict) else None
    error_body = (
        nested_error
        if isinstance(nested_error, dict)
        else body
        if isinstance(body, dict)
        else {}
    )
    status_value = getattr(exc, "status_code", None)
    status_code = status_value if isinstance(status_value, int) else None
    provider_code = sanitize_provider_identifier(
        error_body.get("code") or getattr(exc, "code", None)
    )
    provider_error_type = sanitize_provider_identifier(
        error_body.get("type") or exc.__class__.__name__
    )
    category = classify_model_provider_failure(
        status_code=status_code,
        provider_code=provider_code,
        provider_error_type=provider_error_type,
    )
    if category is ModelProviderFailureCategory.UNKNOWN:
        return None
    return model_provider_failure(
        operation=call_context.call_kind,
        provider=call_context.provider,
        model=call_context.model,
        integration=call_context.provider_integration_id,
        provider_message=(
            extract_provider_message_text(error_body.get("message"))
            or _litellm_provider_message(exc)
        ),
        status_code=status_code,
        provider_code=provider_code,
        provider_error_type=provider_error_type,
        retry_hint_seconds=_retry_after_seconds(exc),
        category=category,
    )


def _litellm_provider_message(exc: Exception) -> str | None:
    """Remove LiteLLM's exception-class prefix from typed provider text."""
    message = getattr(exc, "message", None)
    if not isinstance(message, str):
        return None
    prefixes = (
        f"litellm.{exc.__class__.__name__}: ",
        f"{exc.__class__.__name__}: ",
    )
    for prefix in prefixes:
        if message.startswith(prefix):
            message = message[len(prefix) :]
            break
    return extract_provider_message_text(message)


def _retry_after_seconds(exc: Exception) -> float | None:
    """Extract one numeric Retry-After hint without retaining headers."""
    response = getattr(exc, "response", None)
    headers = getattr(response, "headers", None)
    if headers is None:
        return None
    value = headers.get("retry-after")
    if not isinstance(value, str):
        return None
    try:
        seconds = float(value)
    except ValueError:
        return None
    return seconds if 0 <= seconds <= 86_400 else None


def guard_litellm_streaming_logging(response: AsyncIterable[object]) -> None:
    """Repair model_construct fallback dict of LiteLLM Responses stream logger."""
    logging_obj = getattr(response, "logging_obj", None)
    if logging_obj is None:
        return
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

    if original_success_handler is not None and isinstance(
        logging_obj, _SyncStreamingLogger
    ):
        logging_obj.success_handler = guarded_success_handler
    if original_async_success_handler is not None and isinstance(
        logging_obj, _AsyncStreamingLogger
    ):
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
