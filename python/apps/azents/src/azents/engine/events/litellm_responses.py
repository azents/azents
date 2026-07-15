"""LiteLLM Responses adapter."""

import asyncio
import base64
import dataclasses
import datetime
import hashlib
import json
import os
from collections.abc import AsyncIterable, AsyncIterator, Sequence
from typing import Any, Protocol, runtime_checkable

from azcommon.uuid import uuid7
from litellm.exceptions import OpenAIError as LiteLLMOpenAIError
from litellm.responses.main import aresponses
from litellm.types.llms.openai import ResponseAPIUsage, ResponsesAPIResponse
from openai import OpenAIError as OpenAIBaseError
from openai.types.responses.response_includable import ResponseIncludable
from openai.types.responses.tool_param import ToolParam
from openai.types.shared_params.reasoning import Reasoning
from pydantic import TypeAdapter, ValidationError

from azents.core.chatgpt_oauth import (
    CHATGPT_OAUTH_PROTOCOL_VERSION,
    CHATGPT_RESPONSES_LITE_HEADER,
)
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
    format_plain_system_reminder,
)
from azents.engine.events.types import (
    AgentMessagePayload,
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
    SkillLoadedPayload,
    SystemReminderPayload,
    TokenUsagePayload,
    ToolOutput,
    ToolOutputPart,
    UnknownAdapterOutputPayload,
    UserContentPart,
    UserMessagePayload,
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

_DEFAULT_INSTRUCTIONS = "You are a helpful assistant."
_XAI_PROVIDER_IDS = {LLMProvider.XAI, LLMProvider.XAI_OAUTH}
_PROVIDER_IDS_WITH_INPUT_MESSAGE_INSTRUCTIONS = _XAI_PROVIDER_IDS
_PROVIDER_NAMES_WITH_INPUT_MESSAGE_INSTRUCTIONS = {"xai", "xai_oauth"}
_PROMPT_CACHE_KEY_PREFIX = "azs"
_OPENAI_PROMPT_CACHE_KEY_MAX_CHARS = 64
_MODEL_CALL_ERROR_DETAIL_MAX_CHARS = 512
_REASONING_ENCRYPTED_CONTENT_INCLUDE: ResponseIncludable = "reasoning.encrypted_content"
_TOOLS_ADAPTER: TypeAdapter[list[ToolParam]] = TypeAdapter(list[ToolParam])
_REASONING_ADAPTER: TypeAdapter[Reasoning] = TypeAdapter(Reasoning)
_INCLUDE_ADAPTER: TypeAdapter[list[ResponseIncludable]] = TypeAdapter(
    list[ResponseIncludable]
)


@dataclasses.dataclass(frozen=True)
class _PromptCacheInputs:
    """Model input and tools after provider cache hints are applied."""

    input_items: list[dict[str, object]]
    tools: list[dict[str, object]]


def _format_goal_updated_event_reminder(payload: UserMessagePayload) -> str:
    """Render model-visible reminder for goal_updated event metadata."""
    if payload.metadata.get("goal_control_action") == "resume":
        return format_goal_resumed_reminder(
            goal_objective=payload.metadata.get("goal_objective"),
            previous_goal_status=payload.metadata.get("previous_goal_status"),
            resume_hint=payload.metadata.get("resume_hint"),
        )
    return format_goal_updated_reminder(payload.metadata.get("goal_objective"))


def _format_agent_message(payload: AgentMessagePayload) -> str:
    """Render agent_message as an explicitly sourced model-visible task."""
    message_type = _agent_message_type(payload.message_kind)
    return "\n".join(
        [
            f"Message Type: {message_type}",
            f"Task name: {payload.target_path}",
            f"Sender: {payload.source_path}",
            "Payload:",
            payload.content,
        ]
    )


def _agent_message_type(message_kind: str) -> str:
    """Return the model-visible agent mailbox message type."""
    if message_kind in {"spawn_agent", "followup_task"}:
        return "NEW_TASK"
    return "MESSAGE"


def _format_skill_loaded_event(payload: SkillLoadedPayload) -> str:
    """Render model-visible Skill body injection for a loaded Skill event."""
    user_message_note = (
        "The user's request is provided in the next user message."
        if payload.user_message.strip()
        else "No additional user request was provided."
    )
    return "\n".join(
        [
            f"Skill `{payload.name}` has been loaded.",
            "Read and follow the following Skill body.",
            user_message_note,
            "",
            f"Skill path: `{payload.skill_path}`",
            "",
            "<skill_body>",
            payload.body,
            "</skill_body>",
        ]
    )


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


@runtime_checkable
class _SyncStreamingLogger(Protocol):
    """LiteLLM streaming logger with a synchronous success handler."""

    success_handler: Any


@runtime_checkable
class _AsyncStreamingLogger(Protocol):
    """LiteLLM streaming logger with an asynchronous success handler."""

    async_success_handler: Any


class UnsupportedRequiredBuiltinToolError(ValueError):
    """Raised when adapter does not support required builtin tool."""


def _uses_input_message_instructions(
    *,
    provider: str,
    provider_id: LLMProvider | None,
) -> bool:
    """Return whether system instructions belong in the Responses input."""
    return (
        provider_id in _PROVIDER_IDS_WITH_INPUT_MESSAGE_INSTRUCTIONS
        or provider in _PROVIDER_NAMES_WITH_INPUT_MESSAGE_INSTRUCTIONS
    )


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
        """Set lowerer target provider/model."""
        self.provider = provider
        self.model = model
        self._tools = list(tools or [])
        self._extra_kwargs = dict(kwargs or {})
        self._provider_id = provider_id
        self._credential_kwargs = dict(credential_kwargs or {})
        self._temperature = temperature
        self._max_output_tokens = max_output_tokens
        self._top_p = top_p
        self._stop = list(stop) if stop is not None else None
        self._reasoning_effort = reasoning_effort
        self._hosted_tools = list(hosted_tools or [])
        self._prompt_cache_scope = prompt_cache_scope
        self._model_developer = model_developer
        self._model_capabilities = model_capabilities or ModelCapabilities()
        self._file_part_capabilities = (
            FilePartLoweringCapabilities.from_model_capabilities(
                self._model_capabilities
            )
        )
        self.model_file_resolver = model_file_resolver
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
        instructions = system_prompt or str(default_instructions)
        if _uses_input_message_instructions(
            provider=self.provider,
            provider_id=self._provider_id,
        ):
            kwargs.pop("instructions", None)
            input_items.append({"role": "system", "content": instructions})
        else:
            kwargs["instructions"] = instructions

        for event in transcript:
            native_item = self._compatible_native_item(event)
            if native_item is not None:
                input_items.append(native_item)
                continue

            lowered = self._lower_event(event)
            if lowered is not None:
                input_items.append(lowered)

        if kwargs.get("store") is False:
            # With store=False, provider response items are not persisted; replaying
            # ids like rs_... can resolve missing items. Keep call_id for tool
            # continuity, but mask every item id consistently so prompt cache keys
            # remain stable across turns.
            input_items = _mask_response_item_ids_for_unstored_request(input_items)
        input_items = _drop_orphan_tool_outputs(input_items)
        hosted = _lower_hosted_tools(
            self._hosted_tools,
            provider=self.provider,
            provider_id=self._provider_id,
            model_developer=self._model_developer,
            model_capabilities=self._model_capabilities,
        )
        tools = [*self._tools, *hosted.tools]
        prompt_cache_inputs = _apply_provider_prompt_cache_hints(
            input_items,
            tools,
            provider_id=self._provider_id,
            model_developer=self._model_developer,
        )
        input_items = prompt_cache_inputs.input_items
        tools = prompt_cache_inputs.tools
        kwargs.update(hosted.kwargs)
        if self._uses_responses_lite():
            return self._lower_responses_lite_request(
                model=model,
                input_items=input_items,
                tools=tools,
                instructions=(
                    system_prompt if system_prompt is not None else instructions
                ),
                kwargs=kwargs,
            )
        return NativeModelRequest(
            model=model,
            input=input_items,
            tools=tools,
            kwargs=kwargs,
        )

    def _uses_responses_lite(self) -> bool:
        """Return whether the saved model snapshot requires Responses Lite."""
        return (
            self._provider_id == LLMProvider.CHATGPT_OAUTH
            and self._model_capabilities.compatibility.responses_lite
        )

    def _lower_responses_lite_request(
        self,
        *,
        model: str,
        input_items: Sequence[dict[str, object]],
        tools: Sequence[dict[str, object]],
        instructions: str,
        kwargs: dict[str, object],
    ) -> NativeModelRequest:
        """Apply the ChatGPT Responses Lite request contract."""
        kwargs.pop("instructions", None)
        kwargs["parallel_tool_calls"] = False
        kwargs["store"] = False
        reasoning = kwargs.get("reasoning")
        if reasoning is None:
            kwargs["reasoning"] = {"context": "all_turns"}
        elif isinstance(reasoning, dict):
            kwargs["reasoning"] = {**reasoning, "context": "all_turns"}
        else:
            raise TypeError("LiteLLM kwarg reasoning must be dict")
        session_id = self._prompt_cache_scope
        if session_id is None or not session_id.strip():
            raise ValueError("Responses Lite requires a session identifier")
        kwargs["prompt_cache_key"] = session_id
        headers = _merged_string_headers(kwargs.get("extra_headers"))
        headers.update(
            {
                "session-id": session_id,
                "x-session-affinity": session_id,
            }
        )
        headers.update(
            {
                "version": CHATGPT_OAUTH_PROTOCOL_VERSION,
                CHATGPT_RESPONSES_LITE_HEADER: "true",
            }
        )
        kwargs["extra_headers"] = headers
        prefix: list[dict[str, object]] = [
            {
                "type": "additional_tools",
                "role": "developer",
                "tools": list(tools),
            }
        ]
        if instructions:
            prefix.append(
                {
                    "type": "message",
                    "role": "developer",
                    "content": [{"type": "input_text", "text": instructions}],
                }
            )
        return NativeModelRequest(
            model=model,
            input=[*prefix, *_strip_responses_lite_image_details(input_items)],
            tools=[],
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
        if self._provider_id in _XAI_PROVIDER_IDS:
            kwargs.setdefault("custom_llm_provider", "xai")
            base_url = kwargs.get("base_url") or kwargs.get("api_base")
            if base_url is not None:
                kwargs.setdefault("base_url", base_url)
                kwargs.setdefault("api_base", base_url)
        if self._provider_id in {LLMProvider.OPENAI, LLMProvider.CHATGPT_OAUTH}:
            prompt_cache_key = _openai_prompt_cache_key(self._prompt_cache_scope)
            if prompt_cache_key is not None:
                kwargs.setdefault("prompt_cache_key", prompt_cache_key)
        if self._temperature is not None:
            kwargs["temperature"] = self._temperature
        if self._max_output_tokens is not None:
            kwargs["max_output_tokens"] = self._max_output_tokens
        if self._top_p is not None:
            kwargs["top_p"] = self._top_p
        if self._stop is not None:
            kwargs["stop"] = self._stop
        if self._reasoning_effort is not None:
            kwargs["reasoning"] = {"effort": self._reasoning_effort, "summary": "auto"}
        kwargs.update(self._extra_kwargs)
        if self._provider_id == LLMProvider.CHATGPT_OAUTH:
            kwargs.setdefault("store", False)
            _append_include_value(kwargs, _REASONING_ENCRYPTED_CONTENT_INCLUDE)
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
        if event.kind == EventKind.SKILL_LOADED and isinstance(
            event.payload, SkillLoadedPayload
        ):
            return {
                "role": "user",
                "content": _format_skill_loaded_event(event.payload),
            }
        if event.kind == EventKind.AGENT_MESSAGE and isinstance(
            event.payload, AgentMessagePayload
        ):
            return {
                "role": "user",
                "content": _format_agent_message(event.payload),
            }
        match event.payload:
            case UserMessagePayload(content=content, attachments=attachments):
                return {
                    "role": "user",
                    "content": _lower_user_message_content(
                        content,
                        attachments,
                        capabilities=self._file_part_capabilities,
                        model_file_resolver=self.model_file_resolver,
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
                    "content": format_plain_system_reminder(text),
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
            model_file_resolver=self.model_file_resolver,
        )


@dataclasses.dataclass(frozen=True)
class _HostedToolLowering:
    """Hosted tool lowering result."""

    tools: list[dict[str, object]]
    kwargs: dict[str, object]


def _openai_prompt_cache_key(scope: str | None) -> str | None:
    """Build a stable OpenAI prompt cache routing key for one conversation."""
    if scope is None:
        return None
    normalized = scope.strip()
    if not normalized:
        return None
    digest = hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:32]
    return f"{_PROMPT_CACHE_KEY_PREFIX}:{digest}"[:_OPENAI_PROMPT_CACHE_KEY_MAX_CHARS]


def _merged_string_headers(value: object) -> dict[str, str]:
    """Copy optional string headers for provider-specific augmentation."""
    if value is None:
        return {}
    if not isinstance(value, dict) or not all(
        isinstance(key, str) and isinstance(item, str) for key, item in value.items()
    ):
        raise TypeError("LiteLLM kwarg extra_headers must be dict[str, str]")
    return dict(value)


def _strip_responses_lite_image_details(
    input_items: Sequence[dict[str, object]],
) -> list[dict[str, object]]:
    """Remove unsupported image detail fields from Responses Lite input."""
    stripped: list[dict[str, object]] = []
    for item in input_items:
        copied = dict(item)
        content = copied.get("content")
        if isinstance(content, list):
            copied["content"] = [
                _strip_image_detail_from_part(part) for part in content
            ]
        output = copied.get("output")
        if isinstance(output, list):
            copied["output"] = [_strip_image_detail_from_part(part) for part in output]
        stripped.append(copied)
    return stripped


def _strip_image_detail_from_part(part: object) -> object:
    """Copy one content part without an input image detail field."""
    if not isinstance(part, dict):
        return part
    copied = dict(part)
    if copied.get("type") == "input_image":
        copied.pop("detail", None)
    return copied


def _append_include_value(
    kwargs: dict[str, object],
    value: ResponseIncludable,
) -> None:
    """Add a Responses include value to kwargs without dropping explicit values."""
    raw_include = kwargs.get("include")
    if raw_include is None:
        kwargs["include"] = [value]
        return
    if isinstance(raw_include, list) and all(
        isinstance(item, str) for item in raw_include
    ):
        include = list(raw_include)
        if value not in include:
            include.append(value)
        kwargs["include"] = include
        return
    raise TypeError("LiteLLM kwarg include must be list[str]")


def _apply_provider_prompt_cache_hints(
    input_items: Sequence[dict[str, object]],
    tools: Sequence[dict[str, object]],
    *,
    provider_id: LLMProvider | None,
    model_developer: LLMModelDeveloper | None,
) -> _PromptCacheInputs:
    """Apply provider-native prompt caching hints without overriding defaults."""
    if not _uses_anthropic_cache_control(
        provider_id=provider_id,
        model_developer=model_developer,
    ):
        return _PromptCacheInputs(input_items=list(input_items), tools=list(tools))
    return _apply_anthropic_cache_control(input_items, tools)


def _uses_anthropic_cache_control(
    *,
    provider_id: LLMProvider | None,
    model_developer: LLMModelDeveloper | None,
) -> bool:
    """Return whether LiteLLM can translate cache_control for this target."""
    if provider_id == LLMProvider.ANTHROPIC:
        return True
    if provider_id in {LLMProvider.AWS_BEDROCK, LLMProvider.GOOGLE_VERTEX_AI}:
        return model_developer == LLMModelDeveloper.ANTHROPIC
    if provider_id in {
        LLMProvider.OPENAI,
        LLMProvider.CHATGPT_OAUTH,
        LLMProvider.XAI,
        LLMProvider.XAI_OAUTH,
        LLMProvider.GOOGLE_GEMINI,
    }:
        return False
    return model_developer == LLMModelDeveloper.ANTHROPIC


def _apply_anthropic_cache_control(
    input_items: Sequence[dict[str, object]],
    tools: Sequence[dict[str, object]],
) -> _PromptCacheInputs:
    """Mark stable prefix blocks for Anthropic/Claude prompt caching."""
    input_with_cache = [_copy_item(item) for item in input_items]
    tools_with_cache = [_copy_item(tool) for tool in tools]
    remaining = 4
    cacheable_tools = [
        tool for tool in tools_with_cache if tool.get("type") == "function"
    ]
    if cacheable_tools and _set_cache_control_if_absent(cacheable_tools[-1]):
        remaining -= 1
    for item in input_with_cache:
        if remaining <= 0:
            break
        if _set_item_cache_control_if_absent(item):
            remaining -= 1
    return _PromptCacheInputs(
        input_items=input_with_cache,
        tools=tools_with_cache,
    )


def _copy_item(item: dict[str, object]) -> dict[str, object]:
    """Shallow-copy a native item before adding cache metadata."""
    copied = dict(item)
    content = copied.get("content")
    if isinstance(content, list):
        copied["content"] = [
            dict(part) if isinstance(part, dict) else part for part in content
        ]
    return copied


def _set_item_cache_control_if_absent(item: dict[str, object]) -> bool:
    """Set cache_control on a cacheable input item when absent."""
    if item.get("type") in {"function_call", "function_call_output"}:
        return False
    content = item.get("content")
    if isinstance(content, str):
        item["content"] = [
            {
                "type": "input_text",
                "text": content,
                "cache_control": {"type": "ephemeral"},
            }
        ]
        return True
    if isinstance(content, list) and content:
        last_part = content[-1]
        if isinstance(last_part, dict):
            return _set_cache_control_if_absent(last_part)
    return False


def _set_cache_control_if_absent(item: dict[str, object]) -> bool:
    """Attach Anthropic cache control only when no default exists."""
    if "cache_control" in item:
        return False
    item["cache_control"] = {"type": "ephemeral"}
    return True


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

    for tool in sorted(
        hosted_tools,
        key=lambda item: (
            item.name,
            bool(item.config),
            json.dumps(item.config, sort_keys=True, separators=(",", ":")),
        ),
    ):
        if tool.name != "web_search":
            continue
        if tool.name not in supported:
            msg = f"Required builtin tool is not supported: {tool.name}"
            raise UnsupportedRequiredBuiltinToolError(msg)
        config = dict(tool.config)
        match target:
            case "openai" | "xai":
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
    if provider_id in _XAI_PROVIDER_IDS:
        return "xai"
    if model_developer == LLMModelDeveloper.GOOGLE:
        return "google"
    if model_developer == LLMModelDeveloper.ANTHROPIC:
        return "anthropic"
    if provider in {"openai", "chatgpt_oauth"}:
        return "openai"
    if provider in {"xai", "xai_oauth"}:
        return "xai"
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

        async def open_response() -> object:
            response = await _call_litellm_responses(
                request,
                kwargs,
                connect_timeout_seconds=timeout_policy.connect_timeout_seconds,
            )
            if isinstance(response, AsyncIterable):
                guard_litellm_streaming_logging(response)
            return response

        response: object | None = None
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
                if isinstance(event, _ModelDumpable):
                    yield LiteLLMEvent(
                        type=event.__class__.__name__,
                        item=event.model_dump(),
                    )
                else:
                    yield LiteLLMEvent(type=event.__class__.__name__, item={})
        except asyncio.CancelledError:
            raise
        except (LiteLLMOpenAIError, OpenAIBaseError) as exc:
            # LiteLLM retry finishes inside aresponses, then
            # only final provider errors arrive here.
            if not _is_user_visible_provider_error(exc):
                raise
            raise ModelCallError(_format_model_call_error(exc)) from exc
        finally:
            await close_stream_response(response)


async def _call_litellm_responses(
    request: NativeModelRequest,
    kwargs: dict[str, object],
    *,
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
        include=_optional_include(kwargs, "include"),
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


def _mask_response_item_ids_for_unstored_request(
    input_items: Sequence[dict[str, object]],
) -> list[dict[str, object]]:
    """Set response item ids to null when response items are unstored."""
    normalized: list[dict[str, object]] = []
    for item in input_items:
        if "id" not in item:
            normalized.append(item)
            continue
        masked = dict(item)
        masked["id"] = None
        normalized.append(masked)
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

    def start(self, session_id: str) -> "_LiteLLMResponsesOutputStream":
        """Start incremental normalization for one native model stream."""
        return _LiteLLMResponsesOutputStream(self, session_id)

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
        output = response.get("output")
        if isinstance(output, list) and output:
            return self.normalize_output_items(session_id, output)
        return self.normalize_output_items(session_id, completed_output_items)

    def normalize_output_items(
        self,
        session_id: str,
        output_items: Sequence[object],
    ) -> list[Event]:
        """Convert output item list to events."""
        events: list[Event] = []
        for output_item in output_items:
            raw_item = _dict(output_item)
            if _has_output_item_type(raw_item):
                events.append(self.normalize_output_item(session_id, raw_item))
        return events

    def normalize_output_item(
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


class _LiteLLMResponsesOutputStream:
    """Minimal normalization state for one LiteLLM Responses stream."""

    def __init__(
        self,
        normalizer: LiteLLMResponsesOutputNormalizer,
        session_id: str,
    ) -> None:
        self.normalizer = normalizer
        self._session_id = session_id
        self._tool_refs: dict[int, tuple[str, str]] = {}
        self._completed_output_items: list[dict[str, object]] = []
        self._completed_response: dict[str, object] | None = None
        self._completed_response_seen = False
        self._terminal_error: ModelCallError | None = None
        self._usage: TokenUsagePayload | None = None
        self._partial_text: list[str] = []

    def process_event(
        self,
        native_event: NativeEvent,
    ) -> NormalizedAdapterOutput:
        """Update stream state and return projections for one native event."""
        event_type = native_event.type
        item = native_event.item
        projections: list[StreamProjection] = []

        if event_type in {"OutputTextDeltaEvent", "ResponseTextDeltaEvent"}:
            delta = str(item.get("delta", ""))
            self._partial_text.append(delta)
            projections.append(
                StreamProjection(
                    type="content_delta",
                    delta=delta,
                )
            )
        elif event_type in {"OutputItemAddedEvent", "ResponseOutputItemAddedEvent"}:
            output_index = _int_or_none(item.get("output_index"))
            raw_item = _dict(item.get("item"))
            if raw_item.get("type") == "function_call" and output_index is not None:
                call_id = str(raw_item.get("call_id") or raw_item.get("id") or "")
                name = str(raw_item.get("name") or "")
                self._tool_refs[output_index] = (call_id, name)
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
                self._completed_output_items.append(raw_item)
        elif event_type in {
            "FunctionCallArgumentsDeltaEvent",
            "ResponseFunctionCallArgumentsDeltaEvent",
        }:
            output_index = _int_or_none(item.get("output_index"))
            ref_index = output_index if output_index is not None else -1
            call_id, name = self._tool_refs.get(ref_index, (None, None))
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
        elif event_type == "ResponseIncompleteEvent":
            self._terminal_error = _incomplete_response_model_error(
                _dict(item.get("response"))
            )
        elif event_type == "ResponseFailedEvent":
            self._terminal_error = _failed_response_model_error(
                _dict(item.get("response"))
            )
        elif event_type == "ResponseErrorEvent":
            self._terminal_error = _response_error_event_model_error(item)
        elif event_type == "ResponseCompletedEvent":
            self._completed_response_seen = True
            self._completed_response = _dict(item.get("response"))
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
            raise ModelCallError("Model response stream ended before completion.")
        return self._build_output()

    def _build_output(self) -> NormalizedAdapterOutput:
        """Build output from received state without validating terminal status."""
        events = self.normalizer.normalize_completed(
            self._session_id,
            self._completed_response or {},
            self._completed_output_items,
        )
        return NormalizedAdapterOutput(
            needs_follow_up=(self._completed_response or {}).get("end_turn") is False,
            events=events,
            usage=self._usage,
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


def _incomplete_response_model_error(
    response: dict[str, object],
) -> ModelCallError:
    """Create a safe error for a provider-incomplete response."""
    details = _dict(response.get("incomplete_details"))
    return _terminal_model_call_error(
        "Model response was incomplete",
        message=_bounded_terminal_detail(details.get("reason")),
    )


def _failed_response_model_error(response: dict[str, object]) -> ModelCallError:
    """Create a safe error for a provider-failed response."""
    error = _dict(response.get("error"))
    return _terminal_model_call_error(
        "Model response failed",
        message=_bounded_terminal_detail(error.get("message")),
        code=_bounded_terminal_detail(error.get("code")),
    )


def _response_error_event_model_error(
    item: dict[str, object],
) -> ModelCallError:
    """Create a safe error for a native Responses error event."""
    return _terminal_model_call_error(
        "Model call failed",
        message=_bounded_terminal_detail(item.get("message")),
        code=_bounded_terminal_detail(item.get("code")),
    )


def _terminal_model_call_error(
    summary: str,
    *,
    message: str | None,
    code: str | None = None,
) -> ModelCallError:
    """Format bounded terminal details as a user-visible model error."""
    details: list[str] = []
    if message is not None:
        details.append(message)
    if code is not None and code != message:
        details.append(f"code: {code}")
    if not details:
        return ModelCallError(f"{summary}.")
    return ModelCallError(f"{summary}: {'; '.join(details)}")


def _bounded_terminal_detail(value: object) -> str | None:
    """Return a bounded scalar provider terminal detail."""
    if isinstance(value, str):
        detail = value.strip()
    elif isinstance(value, (int, float)) and not isinstance(value, bool):
        detail = str(value)
    else:
        return None
    if not detail:
        return None
    return detail[:_MODEL_CALL_ERROR_DETAIL_MAX_CHARS]


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
    raw_hidden_params = _dict(response.get("_hidden_params")) or None
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
