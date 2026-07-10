"""Shared LiteLLM Responses API helpers."""

import dataclasses
import os
from collections.abc import AsyncIterable, Sequence
from typing import Protocol, runtime_checkable

from litellm.responses.main import aresponses
from openai.types.responses.response_includable import ResponseIncludable
from openai.types.responses.response_input_param import ResponseInputParam
from openai.types.responses.response_text_config_param import ResponseTextConfigParam
from pydantic import TypeAdapter

from azents.core.enums import LLMProvider
from azents.engine.events.litellm_responses import guard_litellm_streaming_logging

_RESPONSE_INPUT_ADAPTER: TypeAdapter[ResponseInputParam] = TypeAdapter(
    ResponseInputParam
)
_RESPONSE_TEXT_ADAPTER: TypeAdapter[ResponseTextConfigParam] = TypeAdapter(
    ResponseTextConfigParam
)
DEFAULT_RESPONSES_TEXT_CONFIG: ResponseTextConfigParam = (
    _RESPONSE_TEXT_ADAPTER.validate_python(
        {"format": {"type": "text"}, "verbosity": "low"}
    )
)
_REASONING_ENCRYPTED_CONTENT_INCLUDE: ResponseIncludable = "reasoning.encrypted_content"
_PROVIDER_IDS_WITH_INPUT_MESSAGE_INSTRUCTIONS = {
    LLMProvider.XAI,
    LLMProvider.XAI_OAUTH,
}


@dataclasses.dataclass(frozen=True)
class ResponsesEndpointKwargs:
    """Endpoint kwargs to pass to LiteLLM Responses calls."""

    api_key: str | None = None
    api_base: str | None = None
    base_url: str | None = None
    custom_llm_provider: str | None = None
    store: bool | None = None
    include: list[ResponseIncludable] | None = None


@dataclasses.dataclass(frozen=True)
class ResponsesOutputError(Exception):
    """Responses output stream ended with provider-reported failure."""

    event_type: str
    message: str | None = None
    code: object | None = None


def responses_endpoint_kwargs(
    credential_kwargs: dict[str, object],
    *,
    provider: LLMProvider,
) -> ResponsesEndpointKwargs:
    """Normalize integration credentials to Responses endpoint kwargs."""
    api_key = _optional_string(credential_kwargs.get("api_key"), "api_key")
    api_base = _optional_string(credential_kwargs.get("api_base"), "api_base")
    base_url = _optional_string(credential_kwargs.get("base_url"), "base_url")
    custom_llm_provider = _optional_string(
        credential_kwargs.get("custom_llm_provider"),
        "custom_llm_provider",
    )
    store = _optional_bool(credential_kwargs.get("store"), "store")

    include: list[ResponseIncludable] | None = None
    if provider in {LLMProvider.OPENAI, LLMProvider.CHATGPT_OAUTH}:
        custom_llm_provider = custom_llm_provider or "openai"
        base_url = base_url or api_base
        if base_url is None and provider == LLMProvider.OPENAI:
            base_url = os.environ.get("AZ_OPENAI_BASE_URL")
        api_base = api_base or base_url
        if provider == LLMProvider.CHATGPT_OAUTH:
            store = False if store is None else store
            include = [_REASONING_ENCRYPTED_CONTENT_INCLUDE]
    if provider in {LLMProvider.XAI, LLMProvider.XAI_OAUTH}:
        custom_llm_provider = custom_llm_provider or "xai"
        base_url = base_url or api_base
        api_base = api_base or base_url

    return ResponsesEndpointKwargs(
        api_key=api_key,
        api_base=api_base,
        base_url=base_url,
        custom_llm_provider=custom_llm_provider,
        store=store,
        include=include,
    )


def responses_max_output_tokens(
    provider: LLMProvider,
    max_output_tokens: int | None,
) -> int | None:
    """Return output token limit supported by the target Responses endpoint."""
    if provider in {LLMProvider.OPENAI, LLMProvider.CHATGPT_OAUTH}:
        return None
    if max_output_tokens is None or max_output_tokens <= 0:
        return None
    return max_output_tokens


async def call_responses_model(
    *,
    provider: LLMProvider,
    model: str,
    credential_kwargs: dict[str, object],
    input_items: Sequence[dict[str, object]],
    instructions: str,
    stream: bool,
    max_output_tokens: int | None,
    text: ResponseTextConfigParam = DEFAULT_RESPONSES_TEXT_CONFIG,
) -> object:
    """Call LiteLLM Responses API with Azents-standard endpoint handling."""
    endpoint_kwargs = responses_endpoint_kwargs(
        credential_kwargs,
        provider=provider,
    )
    request_input_items = list(input_items)
    top_level_instructions: str | None = instructions
    if provider in _PROVIDER_IDS_WITH_INPUT_MESSAGE_INSTRUCTIONS:
        request_input_items.insert(0, {"role": "system", "content": instructions})
        top_level_instructions = None
    input_payload = _RESPONSE_INPUT_ADAPTER.validate_python(request_input_items)
    response = await aresponses(
        model=model,
        input=input_payload,
        instructions=top_level_instructions,
        stream=stream,
        max_output_tokens=responses_max_output_tokens(provider, max_output_tokens),
        text=text,
        include=endpoint_kwargs.include,
        custom_llm_provider=endpoint_kwargs.custom_llm_provider,
        store=endpoint_kwargs.store,
        api_key=endpoint_kwargs.api_key,
        api_base=endpoint_kwargs.api_base,
        base_url=endpoint_kwargs.base_url,
    )
    if isinstance(response, AsyncIterable):
        guard_litellm_streaming_logging(response)
    return response


async def extract_response_text(response: object) -> str:
    """Extract assistant text from LiteLLM/OpenAI Responses response."""
    if isinstance(response, AsyncIterable):
        return await _extract_stream_response_text(response)

    if isinstance(response, _ResponseWithOutputText) and response.output_text:
        return response.output_text

    raw_response = model_dump(response)
    raw_texts = extract_response_output_text(raw_response)
    if raw_texts:
        return "\n".join(raw_texts)

    if not isinstance(response, _ResponseWithOutput):
        return ""

    parts: list[str] = []
    for item in response.output:
        raw = model_dump(item)
        if raw.get("type") != "message":
            continue
        text = extract_message_item_text(raw)
        if text:
            parts.append(text)
    return "\n".join(parts)


def extract_response_output_text(response: dict[str, object]) -> list[str]:
    """Extract message text from completed response output."""
    output_text = response.get("output_text")
    if isinstance(output_text, str) and output_text:
        return [output_text]
    output = response.get("output")
    if not isinstance(output, list):
        return []
    messages: list[str] = []
    for item in output:
        raw_item = model_dump(item)
        if raw_item.get("type") != "message":
            continue
        text = extract_message_item_text(raw_item)
        if text:
            messages.append(text)
    return messages


def extract_message_item_text(item: dict[str, object]) -> str:
    """Extract text part from a Responses message output item."""
    content = item.get("content")
    if isinstance(content, str):
        return content
    if not isinstance(content, list):
        return ""
    parts: list[str] = []
    for part in content:
        raw_part = model_dump(part)
        text = raw_part.get("text")
        if isinstance(text, str) and text:
            parts.append(text)
    return "\n".join(parts)


def model_dump(item: object) -> dict[str, object]:
    """Convert Pydantic/dict response item to dict."""
    if isinstance(item, dict):
        return item
    if isinstance(item, _ModelDumpable):
        return item.model_dump(mode="python")
    return {}


async def _extract_stream_response_text(response: AsyncIterable[object]) -> str:
    """Extract assistant text from a streaming Responses event sequence."""
    deltas: list[str] = []
    completed_texts: list[str] = []
    async for event in response:
        raw = model_dump(event)
        stream_error = _stream_error(raw)
        if stream_error is not None:
            raise stream_error
        delta = _text_delta(raw)
        if delta:
            deltas.append(delta)
        text = _event_text(raw)
        if text:
            completed_texts.append(text)
        raw_item = raw.get("item")
        item = model_dump(raw_item)
        if item.get("type") == "message":
            text = extract_message_item_text(item)
            if text:
                completed_texts.append(text)
        nested_item = model_dump(item.get("item"))
        if nested_item.get("type") == "message":
            text = extract_message_item_text(nested_item)
            if text:
                completed_texts.append(text)
        response_dict = model_dump(raw.get("response"))
        completed_texts.extend(extract_response_output_text(response_dict))
        item_response_dict = model_dump(item.get("response"))
        completed_texts.extend(extract_response_output_text(item_response_dict))
    if completed_texts:
        return "\n".join(_dedupe_adjacent(completed_texts))
    if deltas:
        return "".join(deltas)
    return ""


def _stream_error(event: dict[str, object]) -> ResponsesOutputError | None:
    """Convert Responses stream error event to a shared output error."""
    event_type = _event_type(event)
    if event_type not in {"error", "response.failed", "response.incomplete"}:
        return None

    error = model_dump(event.get("error"))
    response = model_dump(event.get("response"))
    response_error = model_dump(response.get("error"))
    details = error or response_error
    if details:
        message = details.get("message")
        code = details.get("code")
        return ResponsesOutputError(
            event_type=event_type,
            message=message if isinstance(message, str) else None,
            code=code,
        )

    incomplete_details = model_dump(response.get("incomplete_details"))
    reason = incomplete_details.get("reason")
    return ResponsesOutputError(
        event_type=event_type,
        message=reason if isinstance(reason, str) else None,
        code=reason,
    )


def _text_delta(event: dict[str, object]) -> str:
    """Extract text delta from a Responses stream event."""
    delta = event.get("delta")
    if isinstance(delta, str) and delta:
        return delta
    item = model_dump(event.get("item"))
    item_delta = item.get("delta")
    if isinstance(item_delta, str) and item_delta:
        return item_delta
    return ""


def _event_text(event: dict[str, object]) -> str:
    """Extract completed text field from a Responses done event."""
    text = event.get("text")
    if isinstance(text, str) and text:
        return text
    item = model_dump(event.get("item"))
    item_text = item.get("text")
    if isinstance(item_text, str) and item_text:
        return item_text
    part = model_dump(event.get("part"))
    part_text = part.get("text")
    if isinstance(part_text, str) and part_text:
        return part_text
    return ""


def _event_type(event: dict[str, object]) -> str:
    """Return Responses stream event type as string."""
    event_type = event.get("type")
    if isinstance(event_type, str):
        return event_type
    value = getattr(event_type, "value", None)
    if isinstance(value, str):
        return value
    return str(event_type)


def _dedupe_adjacent(texts: list[str]) -> list[str]:
    """Keep identical adjacent completed text only once."""
    deduped: list[str] = []
    for text in texts:
        if deduped and deduped[-1] == text:
            continue
        deduped.append(text)
    return deduped


def _optional_string(value: object, name: str) -> str | None:
    """Validate credential string option."""
    if value is None:
        return None
    if isinstance(value, str):
        return value
    msg = f"{name} must be a string"
    raise TypeError(msg)


def _optional_bool(value: object, name: str) -> bool | None:
    """Validate credential bool option."""
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    msg = f"{name} must be a bool"
    raise TypeError(msg)


@runtime_checkable
class _ResponseWithOutputText(Protocol):
    """Response with Responses output_text attribute."""

    output_text: str


@runtime_checkable
class _ResponseWithOutput(Protocol):
    """Response with Responses output list attribute."""

    output: list[object]


@runtime_checkable
class _ModelDumpable(Protocol):
    """Object supporting Pydantic-style model_dump."""

    def model_dump(self, *, mode: str = "python") -> dict[str, object]:
        """Convert object to dict."""

        ...
