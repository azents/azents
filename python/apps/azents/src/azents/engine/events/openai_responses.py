"""Official OpenAI SDK Responses HTTP adapter."""

import asyncio
import dataclasses
import logging
import math
import os
from collections.abc import AsyncIterable, AsyncIterator, Mapping, Sequence
from types import SimpleNamespace
from typing import Any, Protocol, TypedDict, runtime_checkable

from litellm import completion_cost
from litellm.types.llms.openai import ResponsesAPIResponse
from openai import (
    APIStatusError,
    AsyncOpenAI,
    Omit,
    OpenAIError,
    omit,
)
from openai.types.responses import (
    Response,
    ResponseCompletedEvent,
    ResponseErrorEvent,
    ResponseFailedEvent,
    ResponseFunctionCallArgumentsDeltaEvent,
    ResponseIncompleteEvent,
    ResponseOutputItemAddedEvent,
    ResponseOutputItemDoneEvent,
    ResponseReasoningSummaryTextDeltaEvent,
    ResponseStreamEvent,
    ResponseTextDeltaEvent,
)
from openai.types.responses.response_includable import ResponseIncludable
from openai.types.responses.response_input_param import ResponseInputParam
from openai.types.responses.response_text_config_param import ResponseTextConfigParam
from openai.types.responses.tool_param import ToolParam
from openai.types.shared_params.reasoning import Reasoning
from pydantic import BaseModel, ConfigDict, Field, TypeAdapter

from azents.core.enums import LLMModelDeveloper, LLMProvider
from azents.core.llm_catalog import ModelCapabilities
from azents.engine.events.file_parts import ModelFileResolver
from azents.engine.events.litellm_responses import (
    LiteLLMResponsesLowerer,
    LiteLLMResponsesOutputNormalizer,
)
from azents.engine.events.protocols import NormalizedAdapterOutput, StreamProjection
from azents.engine.events.responses_continuation import (
    ResponsesContinuationPlan,
    ResponsesContinuationPlanner,
    sanitize_responses_native_item,
)
from azents.engine.events.types import (
    AssistantMessagePayload,
    Event,
    OutputTextPart,
    TokenUsagePayload,
    build_native_compat_key,
)
from azents.engine.model_stream import (
    ModelStreamCallContext,
    ModelStreamTimeoutPolicy,
    ModelStreamWatchdog,
    close_stream_response,
    connect_only_http_timeout,
)
from azents.engine.run.errors import ModelCallError
from azents.engine.run.types import BuiltinToolSpec

logger = logging.getLogger(__name__)

_RESPONSE_INPUT_ADAPTER: TypeAdapter[ResponseInputParam] = TypeAdapter(
    ResponseInputParam
)
_TOOLS_ADAPTER: TypeAdapter[list[ToolParam]] = TypeAdapter(list[ToolParam])
_REASONING_ADAPTER: TypeAdapter[Reasoning] = TypeAdapter(Reasoning)
_INCLUDE_ADAPTER: TypeAdapter[list[ResponseIncludable]] = TypeAdapter(
    list[ResponseIncludable]
)
_TEXT_ADAPTER: TypeAdapter[ResponseTextConfigParam] = TypeAdapter(
    ResponseTextConfigParam
)
_OPENAI_ENDPOINT_OPTION_KEYS = {
    "api_base",
    "api_key",
    "base_url",
    "custom_llm_provider",
}
_OPENAI_REQUEST_OPTION_KEYS = {
    "extra_headers",
    "include",
    "instructions",
    "max_output_tokens",
    "parallel_tool_calls",
    "prompt_cache_key",
    "reasoning",
    "service_tier",
    "stop",
    "store",
    "temperature",
    "text",
    "tool_choice",
    "top_p",
}
_RESPONSES_LITE_HEADER = "x-openai-internal-codex-responses-lite"
_SAFE_ERROR_CODE_MAX_CHARS = 96


class OpenAIResponsesOptions(TypedDict, total=False):
    """Presence-preserving logical Responses request options."""

    instructions: str | None
    max_output_tokens: int | None
    reasoning: dict[str, object] | None
    store: bool | None
    temperature: float | None
    top_p: float | None
    include: list[str] | None
    prompt_cache_key: str | None
    parallel_tool_calls: bool | None
    text: dict[str, object] | None
    tool_choice: object
    service_tier: str | None
    stop: str | list[str] | None
    extra_headers: dict[str, str] | None


_OPTIONS_ADAPTER: TypeAdapter[OpenAIResponsesOptions] = TypeAdapter(
    OpenAIResponsesOptions
)


class OpenAIResponsesRequest(BaseModel):
    """Complete logical OpenAI Responses request before transport reduction."""

    model_config = ConfigDict(frozen=True)

    model: str = Field(min_length=1)
    input: list[dict[str, object]]
    tools: list[dict[str, object]]
    options: OpenAIResponsesOptions

    def native_request_input_chars(self) -> int:
        """Estimate the complete logical request size before continuation."""
        return len(str(self.input)) + len(str(self.tools)) + len(str(self.options))

    def continuation_input_items(self) -> list[dict[str, object]]:
        """Return the complete logical input sequence."""
        return self.input

    def continuation_properties(self) -> object:
        """Return every non-input semantic request property with field presence."""
        return (self.model, self.tools, self.options)

    def continuation_store_enabled(self) -> bool:
        """Return whether stored-response continuation is allowed."""
        return self.options.get("store") is not False

    @property
    def responses_lite(self) -> bool:
        """Return whether this request uses the ChatGPT Responses Lite dialect."""
        headers = self.options.get("extra_headers")
        return isinstance(headers, dict) and headers.get(_RESPONSES_LITE_HEADER) == (
            "true"
        )


class OpenAIResponsesLowerer:
    """Lower canonical events to an OpenAI SDK-owned logical request."""

    adapter = "openai"
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
        max_output_tokens: int | None = None,
        top_p: float | None = None,
        stop: list[str] | None = None,
        reasoning_effort: str | None = None,
        hosted_tools: Sequence[BuiltinToolSpec] | None = None,
        prompt_cache_scope: str | None = None,
        model_developer: LLMModelDeveloper | None = None,
        model_capabilities: ModelCapabilities | None = None,
        model_file_resolver: ModelFileResolver | None = None,
    ) -> None:
        """Reuse canonical event lowering without inheriting its request type."""
        self._lowerer = LiteLLMResponsesLowerer(
            provider=provider,
            model=model,
            tools=tools,
            kwargs=kwargs,
            provider_id=provider_id,
            credential_kwargs=credential_kwargs,
            temperature=temperature,
            max_output_tokens=max_output_tokens,
            top_p=top_p,
            stop=stop,
            reasoning_effort=reasoning_effort,
            hosted_tools=hosted_tools,
            prompt_cache_scope=prompt_cache_scope,
            model_developer=model_developer,
            model_capabilities=model_capabilities,
            model_file_resolver=model_file_resolver,
        )
        self._lowerer.compat_key = build_native_compat_key(
            adapter=self.adapter,
            native_format=self.native_format,
            provider=self._lowerer.provider,
            model=self._lowerer.model,
            schema_version=self.schema_version,
        )
        self.compat_key = self._lowerer.compat_key

    def lower(
        self,
        transcript: Sequence[Event],
        *,
        model: str,
        system_prompt: str | None = None,
    ) -> OpenAIResponsesRequest:
        """Convert an Event transcript without retaining endpoint credentials."""
        native = self._lowerer.lower(
            transcript,
            model=model,
            system_prompt=system_prompt,
        )
        unknown = set(native.kwargs) - (
            _OPENAI_REQUEST_OPTION_KEYS | _OPENAI_ENDPOINT_OPTION_KEYS
        )
        if unknown:
            names = ", ".join(sorted(unknown))
            raise ValueError(f"Unsupported OpenAI Responses options: {names}")
        options = _OPTIONS_ADAPTER.validate_python(
            {
                key: value
                for key, value in native.kwargs.items()
                if key in _OPENAI_REQUEST_OPTION_KEYS
            }
        )
        return OpenAIResponsesRequest(
            model=native.model,
            input=native.input,
            tools=native.tools,
            options=options,
        )


@dataclasses.dataclass(frozen=True)
class OpenAIResponsesClientConfig:
    """Credential-bearing configuration kept outside logical requests."""

    api_key: str | None
    base_url: str | None
    default_headers: dict[str, str] | None


class OpenAIResponsesProviderError(RuntimeError):
    """Sanitized non-user-visible OpenAI provider failure."""

    def __init__(
        self,
        *,
        error_type: str,
        status_code: int | None,
        code: str | None,
    ) -> None:
        """Retain only allowlisted bounded operational metadata."""
        super().__init__("OpenAI Responses request failed.")
        self.error_type = error_type
        self.status_code = status_code
        self.code = code


def openai_responses_client_config(
    *,
    provider: LLMProvider,
    credential_kwargs: Mapping[str, object],
) -> OpenAIResponsesClientConfig:
    """Build official SDK client configuration from resolved credentials."""
    api_key = _optional_credential_string(credential_kwargs, "api_key")
    base_url = _optional_credential_string(credential_kwargs, "base_url")
    if base_url is None:
        base_url = _optional_credential_string(credential_kwargs, "api_base")
    if base_url is None and provider == LLMProvider.OPENAI:
        base_url = os.environ.get("AZ_OPENAI_BASE_URL")
    default_headers = _optional_credential_headers(
        credential_kwargs.get("extra_headers")
    )
    return OpenAIResponsesClientConfig(
        api_key=api_key,
        base_url=base_url,
        default_headers=default_headers,
    )


class OpenAIResponsesClient(Protocol):
    """Narrow operation-scoped Responses client used by the adapter."""

    async def create_response(self, **kwargs: object) -> object:
        """Create one streaming response through the public SDK resource."""
        ...

    async def close(self) -> None:
        """Close the client transport."""
        ...


class OpenAISDKResponsesClient:
    """Operation-scoped wrapper around the official SDK client."""

    def __init__(self, sdk_client: AsyncOpenAI) -> None:
        self.sdk_client = sdk_client

    async def create_response(self, **kwargs: object) -> object:
        """Call the SDK's public Responses create method."""
        create: Any = self.sdk_client.responses.create
        return await create(**kwargs)

    async def close(self) -> None:
        """Close the wrapped SDK client."""
        await self.sdk_client.close()


def create_openai_responses_client(
    *,
    provider: LLMProvider,
    credential_kwargs: Mapping[str, object],
) -> OpenAIResponsesClient:
    """Create one operation-scoped official SDK client."""
    _suppress_openai_wire_loggers()
    config = openai_responses_client_config(
        provider=provider,
        credential_kwargs=credential_kwargs,
    )
    return OpenAISDKResponsesClient(
        AsyncOpenAI(
            api_key=config.api_key,
            base_url=config.base_url,
            default_headers=config.default_headers,
        )
    )


def _suppress_openai_wire_loggers() -> None:
    """Keep SDK and HTTP wire diagnostics below the application log boundary."""
    for name in ("openai", "httpx", "httpcore"):
        logging.getLogger(name).setLevel(logging.WARNING)


class OpenAIResponsesModelAdapter:
    """Official OpenAI SDK streaming Responses transport."""

    def __init__(
        self,
        *,
        client: OpenAIResponsesClient,
        continuation_planner: ResponsesContinuationPlanner | None,
    ) -> None:
        """Own one client and optional sampling-only continuation planner."""
        self.client = client
        self.continuation_planner = continuation_planner
        self._closed = False

    async def close(self) -> None:
        """Close the operation-scoped SDK client exactly once."""
        if self._closed:
            return
        self._closed = True
        await self.client.close()

    async def stream(
        self,
        request: OpenAIResponsesRequest,
        *,
        watchdog: ModelStreamWatchdog,
        timeout_policy: ModelStreamTimeoutPolicy,
        call_context: ModelStreamCallContext,
    ) -> AsyncIterator[ResponseStreamEvent]:
        """Return watched official SDK events and retain safe continuation state."""
        plan = self._plan(request)
        if self.continuation_planner is not None:
            self.continuation_planner.reset()
        physical_response: object | None = None

        async def open_response() -> object:
            nonlocal physical_response, plan
            try:
                physical_response = await self._create_stream(
                    request,
                    plan=plan,
                    connect_timeout_seconds=timeout_policy.connect_timeout_seconds,
                )
                return physical_response
            except OpenAIError as exc:
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
                physical_response = await self._create_stream(
                    request,
                    plan=plan,
                    connect_timeout_seconds=timeout_policy.connect_timeout_seconds,
                )
                return physical_response

        response: object | None = None
        completed_response: Response | None = None
        completed_output_items: list[dict[str, object]] = []
        terminal_failure = False
        try:
            response = await watchdog.open_response(
                open_response,
                policy=timeout_policy,
                context=call_context,
            )
            if not isinstance(response, AsyncIterable):
                raise RuntimeError("OpenAI Responses call returned a non-stream")
            async for event in response:
                if (
                    isinstance(event, ResponseOutputItemDoneEvent)
                    and event.type == "response.output_item.done"
                ):
                    completed_output_items.append(_sdk_model_dump(event.item))
                elif (
                    isinstance(event, ResponseCompletedEvent)
                    and event.type == "response.completed"
                ):
                    completed_response = event.response
                elif (
                    (
                        isinstance(event, ResponseFailedEvent)
                        and event.type == "response.failed"
                    )
                    or (
                        isinstance(event, ResponseIncompleteEvent)
                        and event.type == "response.incomplete"
                    )
                    or (isinstance(event, ResponseErrorEvent) and event.type == "error")
                ):
                    terminal_failure = True
                yield event
            if completed_response is not None and not terminal_failure:
                self._record_completion(
                    request,
                    completed_response=completed_response,
                    completed_output_items=completed_output_items,
                )
        except asyncio.CancelledError:
            raise
        except OpenAIError as exc:
            raise _map_openai_error(exc) from None
        finally:
            await close_stream_response(response)
            if physical_response is not response:
                await close_stream_response(physical_response)

    def _plan(self, request: OpenAIResponsesRequest) -> ResponsesContinuationPlan:
        """Plan physical input only after the complete request was validated."""
        if self.continuation_planner is None:
            return ResponsesContinuationPlan(
                input_items=request.input,
                previous_response_id=None,
            )
        return self.continuation_planner.plan(request)

    async def _create_stream(
        self,
        request: OpenAIResponsesRequest,
        *,
        plan: ResponsesContinuationPlan,
        connect_timeout_seconds: float,
    ) -> object:
        """Dispatch one physical request through the public SDK surface."""
        if self.continuation_planner is not None:
            logger.info(
                "Dispatching OpenAI Responses request",
                extra={
                    "previous_response_id_supplied": (
                        plan.previous_response_id is not None
                    )
                },
            )
        options = request.options
        native_input: object = plan.input_items
        native_tools: object = (
            request.tools if request.tools or request.responses_lite else omit
        )
        return await self.client.create_response(
            model=request.model,
            input=native_input,
            tools=native_tools,
            stream=True,
            instructions=_optional_str(options, "instructions"),
            max_output_tokens=_optional_int(options, "max_output_tokens"),
            reasoning=_optional_reasoning(options, "reasoning"),
            store=_optional_bool(options, "store"),
            temperature=_optional_float(options, "temperature"),
            top_p=_optional_float(options, "top_p"),
            include=_optional_include(options, "include"),
            prompt_cache_key=_optional_str(options, "prompt_cache_key"),
            parallel_tool_calls=_optional_bool(options, "parallel_tool_calls"),
            text=_optional_text(options, "text"),
            tool_choice=_optional_object(options, "tool_choice"),
            service_tier=_optional_service_tier(options, "service_tier"),
            previous_response_id=(plan.previous_response_id or omit),
            extra_headers=_optional_headers(options, "extra_headers"),
            extra_body=_stop_extra_body(options),
            timeout=connect_only_http_timeout(connect_timeout_seconds),
        )

    def _record_completion(
        self,
        request: OpenAIResponsesRequest,
        *,
        completed_response: Response,
        completed_output_items: list[dict[str, object]],
    ) -> None:
        """Commit only an explicitly completed provider boundary."""
        if self.continuation_planner is None or not completed_response.id:
            return
        output_items = [
            _sdk_model_dump(item) for item in completed_response.output
        ] or completed_output_items
        self.continuation_planner.record_completion(
            request,
            response_id=completed_response.id,
            output_items=output_items,
        )


class OpenAIResponsesOutputNormalizer:
    """Normalize official SDK typed Responses events to canonical events."""

    adapter = "openai"
    native_format = "responses"
    schema_version = "1"

    def __init__(self, *, provider: str, model: str) -> None:
        """Configure OpenAI-native artifact ownership."""
        self.provider = provider
        self.model = model
        self._canonical = LiteLLMResponsesOutputNormalizer(
            provider=provider,
            model=model,
        )
        self._canonical.adapter = self.adapter
        self._canonical.compat_key = build_native_compat_key(
            adapter=self.adapter,
            native_format=self.native_format,
            provider=provider,
            model=model,
            schema_version=self.schema_version,
        )

    def start(self, session_id: str) -> "_OpenAIResponsesOutputStream":
        """Start typed normalization state for one SDK stream."""
        return _OpenAIResponsesOutputStream(self, session_id)

    def normalize_completed(
        self,
        session_id: str,
        response: dict[str, object],
        completed_output_items: Sequence[dict[str, object]],
    ) -> list[Event]:
        """Normalize completed plain output items with OpenAI artifacts."""
        return self._canonical.normalize_completed(
            session_id,
            response,
            completed_output_items,
        )

    def normalize_partial_assistant(self, session_id: str, text: str) -> Event:
        """Create a canonical fallback for interrupted partial text."""
        return self._canonical.normalize_partial_assistant(session_id, text)


class _OpenAIResponsesOutputStream:
    """Typed normalization state for one official SDK Responses stream."""

    def __init__(
        self,
        normalizer: OpenAIResponsesOutputNormalizer,
        session_id: str,
    ) -> None:
        self.normalizer = normalizer
        self._session_id = session_id
        self._tool_refs: dict[int, tuple[str, str]] = {}
        self._completed_output_items: list[dict[str, object]] = []
        self._completed_response: Response | None = None
        self._completed_response_seen = False
        self._terminal_error: ModelCallError | None = None
        self._partial_text: list[str] = []

    def process_event(
        self,
        native_event: ResponseStreamEvent,
    ) -> NormalizedAdapterOutput:
        """Consume one class-and-wire matched SDK event."""
        projections: list[StreamProjection] = []
        if (
            isinstance(native_event, ResponseTextDeltaEvent)
            and native_event.type == "response.output_text.delta"
        ):
            self._partial_text.append(native_event.delta)
            projections.append(
                StreamProjection(type="content_delta", delta=native_event.delta)
            )
        elif (
            isinstance(native_event, ResponseOutputItemAddedEvent)
            and native_event.type == "response.output_item.added"
        ):
            raw_item = _sdk_model_dump(native_event.item)
            if raw_item.get("type") == "function_call":
                call_id = _string_value(raw_item.get("call_id") or raw_item.get("id"))
                name = _string_value(raw_item.get("name"))
                self._tool_refs[native_event.output_index] = (call_id, name)
                projections.append(
                    StreamProjection(
                        type="function_call_delta",
                        index=native_event.output_index,
                        call_id=call_id,
                        name=name,
                        delta="",
                    )
                )
        elif (
            isinstance(native_event, ResponseOutputItemDoneEvent)
            and native_event.type == "response.output_item.done"
        ):
            raw_item = _sdk_model_dump(native_event.item)
            if isinstance(raw_item.get("type"), str):
                self._completed_output_items.append(raw_item)
        elif (
            isinstance(native_event, ResponseFunctionCallArgumentsDeltaEvent)
            and native_event.type == "response.function_call_arguments.delta"
        ):
            call_id, name = self._tool_refs.get(native_event.output_index, (None, None))
            projections.append(
                StreamProjection(
                    type="function_call_delta",
                    index=native_event.output_index,
                    call_id=call_id,
                    name=name,
                    delta=native_event.delta,
                )
            )
        elif (
            isinstance(native_event, ResponseReasoningSummaryTextDeltaEvent)
            and native_event.type == "response.reasoning_summary_text.delta"
        ):
            projections.append(
                StreamProjection(type="reasoning_delta", delta=native_event.delta)
            )
        elif (
            isinstance(native_event, ResponseIncompleteEvent)
            and native_event.type == "response.incomplete"
        ):
            self._terminal_error = ModelCallError("Model response was incomplete.")
        elif (
            isinstance(native_event, ResponseFailedEvent)
            and native_event.type == "response.failed"
        ):
            self._terminal_error = ModelCallError("Model response failed.")
        elif (
            isinstance(native_event, ResponseErrorEvent)
            and native_event.type == "error"
        ):
            self._terminal_error = ModelCallError("Model call failed.")
        elif (
            isinstance(native_event, ResponseCompletedEvent)
            and native_event.type == "response.completed"
        ):
            self._completed_response_seen = True
            self._completed_response = native_event.response

        return NormalizedAdapterOutput(
            needs_follow_up=False,
            projections=projections,
        )

    def complete(self) -> NormalizedAdapterOutput:
        """Build durable output only after typed explicit completion."""
        if self._terminal_error is not None:
            raise self._terminal_error
        if not self._completed_response_seen or self._completed_response is None:
            raise ModelCallError("Model response stream ended before completion.")
        return self._build_output()

    def interrupt(self) -> NormalizedAdapterOutput:
        """Preserve completed items and non-empty partial assistant text."""
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

    def _build_output(self) -> NormalizedAdapterOutput:
        """Build canonical output from all currently completed SDK items."""
        response = self._completed_response
        response_dict = _sdk_model_dump(response) if response is not None else {}
        events = self.normalizer.normalize_completed(
            self._session_id,
            response_dict,
            self._completed_output_items,
        )
        usage = (
            _normalize_openai_usage(response, model=self.normalizer.model)
            if response is not None
            else None
        )
        return NormalizedAdapterOutput(
            needs_follow_up=response_dict.get("end_turn") is False,
            events=events,
            usage=usage,
        )


def _normalize_openai_usage(
    response: Response,
    *,
    model: str,
) -> TokenUsagePayload | None:
    """Normalize SDK usage and estimate content-free public-map pricing."""
    usage = response.usage
    if usage is None:
        return None
    raw_usage = _sdk_model_dump(usage)
    input_details: object = usage.input_tokens_details
    output_details: object = usage.output_tokens_details
    return TokenUsagePayload(
        prompt_tokens=usage.input_tokens,
        completion_tokens=usage.output_tokens,
        total_tokens=usage.total_tokens,
        raw=raw_usage,
        cached_tokens=_optional_usage_detail(input_details, "cached_tokens"),
        cache_creation_tokens=_optional_usage_detail(
            input_details,
            "cache_write_tokens",
        ),
        reasoning_tokens=_optional_usage_detail(
            output_details,
            "reasoning_tokens",
        ),
        cost_usd=_estimate_openai_cost(response, model=model),
        raw_hidden_params=None,
    )


def _optional_usage_detail(details: object, field: str) -> int | None:
    """Read an optional integer from a provider-compatible usage detail object."""
    value = getattr(details, field, None)
    if not isinstance(value, int) or isinstance(value, bool):
        return None
    return value


def _estimate_openai_cost(response: Response, *, model: str) -> float | None:
    """Estimate cost through LiteLLM using only usage and pricing metadata."""
    minimal_response = ResponsesAPIResponse.model_construct(
        model=model,
        usage=_sdk_model_dump(response.usage),
        output=[
            SimpleNamespace(type=item.type)
            for item in response.output
            if isinstance(getattr(item, "type", None), str)
        ],
    )
    service_tier = getattr(response, "service_tier", None)
    try:
        cost = completion_cost(
            completion_response=minimal_response,
            model=model,
            call_type="responses",
            custom_llm_provider="openai",
            service_tier=service_tier if isinstance(service_tier, str) else None,
        )
    except Exception:
        return None
    if not isinstance(cost, int | float) or isinstance(cost, bool):
        return None
    normalized = float(cost)
    if not math.isfinite(normalized) or normalized < 0:
        return None
    return normalized


async def call_openai_responses_text(
    *,
    provider: LLMProvider,
    model: str,
    credential_kwargs: Mapping[str, object],
    input_items: Sequence[dict[str, object]],
    instructions: str,
    text: ResponseTextConfigParam,
    watchdog: ModelStreamWatchdog,
    timeout_policy: ModelStreamTimeoutPolicy,
    call_context: ModelStreamCallContext,
) -> str:
    """Run one operation-scoped standard-dialect Responses text call."""
    client = create_openai_responses_client(
        provider=provider,
        credential_kwargs=credential_kwargs,
    )
    options: OpenAIResponsesOptions = {
        "instructions": instructions,
        "text": dict(text),
    }
    if provider == LLMProvider.CHATGPT_OAUTH:
        options["store"] = False
        options["include"] = ["reasoning.encrypted_content"]
    request = OpenAIResponsesRequest(
        model=model,
        input=list(input_items),
        tools=[],
        options=options,
    )
    adapter = OpenAIResponsesModelAdapter(
        client=client,
        continuation_planner=None,
    )
    normalizer = OpenAIResponsesOutputNormalizer(
        provider=provider.value,
        model=model,
    )
    stream = normalizer.start(call_context.session_id or "bounded-operation")
    try:
        async for event in adapter.stream(
            request,
            watchdog=watchdog,
            timeout_policy=timeout_policy,
            call_context=call_context,
        ):
            stream.process_event(event)
        completed = stream.complete()
        return _assistant_text(completed.events)
    finally:
        await adapter.close()


def _assistant_text(events: Sequence[Event]) -> str:
    """Extract completed assistant text from canonical message events."""
    texts: list[str] = []
    for event in events:
        payload = event.payload
        if not isinstance(payload, AssistantMessagePayload):
            continue
        if isinstance(payload.content, str):
            if payload.content:
                texts.append(payload.content)
            continue
        texts.extend(
            part.text
            for part in payload.content
            if isinstance(part, OutputTextPart) and part.text
        )
    return "\n".join(texts)


def _map_openai_error(exc: OpenAIError) -> Exception:
    """Convert SDK failures without retaining raw provider bodies or causes."""
    status_code = exc.status_code if isinstance(exc, APIStatusError) else None
    code = _safe_openai_error_code(exc)
    if status_code == 401:
        return ModelCallError("Model authentication failed.")
    if status_code == 403:
        return ModelCallError("Model access was denied.")
    if status_code == 429:
        return ModelCallError("The model provider rate limit was exceeded.")
    if status_code is not None and status_code >= 500:
        return ModelCallError("The model provider is temporarily unavailable.")
    return OpenAIResponsesProviderError(
        error_type=exc.__class__.__name__,
        status_code=status_code,
        code=code,
    )


def _safe_openai_error_code(exc: OpenAIError) -> str | None:
    """Extract one bounded scalar provider code without copying error text."""
    raw_code = getattr(exc, "code", None)
    if raw_code is None and isinstance(exc, APIStatusError):
        body = exc.body
        if isinstance(body, dict):
            error = body.get("error")
            if isinstance(error, dict):
                raw_code = error.get("code")
    if not isinstance(raw_code, str):
        return None
    code = raw_code.strip()[:_SAFE_ERROR_CODE_MAX_CHARS]
    if not code or not all(char.isalnum() or char in {"_", "-", "."} for char in code):
        return None
    return code


def _is_previous_response_not_found(exc: OpenAIError) -> bool:
    """Match only the provider's missing stored response code."""
    return _safe_openai_error_code(exc) == "previous_response_not_found"


@runtime_checkable
class _SDKModel(Protocol):
    """Pydantic-compatible SDK model serialization surface."""

    def model_dump(
        self,
        *,
        mode: str,
        exclude_unset: bool,
        warnings: bool,
    ) -> dict[str, object]:
        """Serialize an SDK model to plain data."""
        ...


def _sdk_model_dump(value: object) -> dict[str, object]:
    """Serialize SDK models while preserving nulls, extras, and presence."""
    if value is None:
        return {}
    if isinstance(value, dict):
        return sanitize_responses_native_item(dict(value))
    if isinstance(value, _SDKModel):
        return sanitize_responses_native_item(
            value.model_dump(
                mode="json",
                exclude_unset=True,
                warnings=False,
            )
        )
    return {}


def _optional_credential_string(
    values: Mapping[str, object],
    key: str,
) -> str | None:
    value = values.get(key)
    if value is None:
        return None
    if not isinstance(value, str):
        raise TypeError(f"OpenAI client option {key} must be a string")
    return value


def _optional_credential_headers(value: object) -> dict[str, str] | None:
    if value is None:
        return None
    if not isinstance(value, dict) or not all(
        isinstance(key, str) and isinstance(item, str) for key, item in value.items()
    ):
        raise TypeError("OpenAI client extra_headers must be dict[str, str]")
    return dict(value)


def _optional_str(
    options: OpenAIResponsesOptions,
    key: str,
) -> str | None | Omit:
    if key not in options:
        return omit
    value = options[key]
    if value is None or isinstance(value, str):
        return value
    raise TypeError(f"OpenAI Responses option {key} must be a string")


def _optional_int(
    options: OpenAIResponsesOptions,
    key: str,
) -> int | None | Omit:
    if key not in options:
        return omit
    value = options[key]
    if value is None or isinstance(value, int) and not isinstance(value, bool):
        return value
    raise TypeError(f"OpenAI Responses option {key} must be an int")


def _optional_bool(
    options: OpenAIResponsesOptions,
    key: str,
) -> bool | None | Omit:
    if key not in options:
        return omit
    value = options[key]
    if value is None or isinstance(value, bool):
        return value
    raise TypeError(f"OpenAI Responses option {key} must be a bool")


def _optional_float(
    options: OpenAIResponsesOptions,
    key: str,
) -> float | None | Omit:
    if key not in options:
        return omit
    value = options[key]
    if value is None:
        return None
    if isinstance(value, int | float) and not isinstance(value, bool):
        return float(value)
    raise TypeError(f"OpenAI Responses option {key} must be a float")


def _optional_reasoning(
    options: OpenAIResponsesOptions,
    key: str,
) -> Reasoning | None | Omit:
    if key not in options:
        return omit
    value = options[key]
    if value is None:
        return None
    validated = _REASONING_ADAPTER.validate_python(value)
    if isinstance(value, dict) and value.get("context") == "all_turns":
        validated["context"] = "all_turns"
    return validated


def _optional_include(
    options: OpenAIResponsesOptions,
    key: str,
) -> list[ResponseIncludable] | None | Omit:
    if key not in options:
        return omit
    value = options[key]
    if value is None:
        return None
    return _INCLUDE_ADAPTER.validate_python(value)


def _optional_text(
    options: OpenAIResponsesOptions,
    key: str,
) -> ResponseTextConfigParam | None | Omit:
    if key not in options:
        return omit
    value = options[key]
    if value is None:
        return None
    return _TEXT_ADAPTER.validate_python(value)


def _optional_object(
    options: OpenAIResponsesOptions,
    key: str,
) -> object | Omit:
    if key not in options:
        return omit
    return options[key]


def _optional_service_tier(
    options: OpenAIResponsesOptions,
    key: str,
) -> str | None | Omit:
    if key not in options:
        return omit
    value = options[key]
    if value is None or isinstance(value, str):
        return value
    raise TypeError(f"OpenAI Responses option {key} must be a string")


def _optional_headers(
    options: OpenAIResponsesOptions,
    key: str,
) -> dict[str, str] | None:
    if key not in options:
        return None
    value = options[key]
    if value is None:
        return None
    if not isinstance(value, dict) or not all(
        isinstance(name, str) and isinstance(item, str) for name, item in value.items()
    ):
        raise TypeError("OpenAI Responses extra_headers must be dict[str, str]")
    return dict(value)


def _stop_extra_body(options: OpenAIResponsesOptions) -> dict[str, object] | None:
    if "stop" not in options:
        return None
    value = options["stop"]
    if (
        value is not None
        and not isinstance(value, str)
        and not (
            isinstance(value, list) and all(isinstance(item, str) for item in value)
        )
    ):
        raise TypeError("OpenAI Responses stop must be a string or list[str]")
    return {"stop": value}


def _string_value(value: object) -> str:
    return value if isinstance(value, str) else ""


def _has_assistant_text(events: Sequence[Event]) -> bool:
    return bool(_assistant_text(events))
