"""Shared provider-native Responses request lowering."""

import dataclasses
import hashlib
import json
import os
from collections.abc import Mapping, Sequence
from typing import ClassVar

from openai.types.responses.response_includable import ResponseIncludable

from azents.core.enums import EventKind, LLMModelDeveloper, LLMProvider
from azents.core.llm_catalog import ModelCapabilities
from azents.engine.events.file_parts import (
    FilePartLoweringCapabilities,
    ModelFileResolver,
    lower_file_output_part,
)
from azents.engine.events.output_parts import iter_output_parts, lower_output_to_text
from azents.engine.events.protocols import NativeModelRequest
from azents.engine.events.provider_tool_rendering import render_provider_tool_semantic
from azents.engine.events.responses_continuation import sanitize_responses_native_item
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
    AttachmentOutputPart,
    ClientToolCallPayload,
    ClientToolResultPayload,
    CompactionSummaryPayload,
    Event,
    FileOutputPart,
    InputContentPart,
    InputTextPart,
    InterruptedPayload,
    OutputContentPart,
    OutputTextPart,
    ProviderToolCallPayload,
    ReasoningPayload,
    RunMarkerPayload,
    SkillLoadedPayload,
    SystemReminderPayload,
    ToolOutput,
    UnknownAdapterOutputPayload,
    UserContentPart,
    UserMessagePayload,
    build_native_compat_key,
)
from azents.engine.run.builtin_tools import UnsupportedRequiredBuiltinToolError
from azents.engine.run.types import BuiltinToolSpec

_DEFAULT_INSTRUCTIONS = "You are a helpful assistant."
_XAI_PROVIDER_IDS = {LLMProvider.XAI, LLMProvider.XAI_OAUTH}
_PROVIDER_IDS_WITH_INPUT_MESSAGE_INSTRUCTIONS = _XAI_PROVIDER_IDS
_PROVIDER_NAMES_WITH_INPUT_MESSAGE_INSTRUCTIONS = {"xai", "xai_oauth"}
_PROMPT_CACHE_KEY_PREFIX = "azs"
_OPENAI_PROMPT_CACHE_KEY_MAX_CHARS = 64
_REASONING_ENCRYPTED_CONTENT_INCLUDE: ResponseIncludable = "reasoning.encrypted_content"


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


class ResponsesRequestLowerer:
    """Lower Event transcript to a provider-native Responses request."""

    adapter: ClassVar[str]
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
        """Convert Event transcript to a provider-native Responses request."""
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
            native_items = self._compatible_native_items(event)
            if native_items is not None:
                input_items.extend(native_items)
                continue

            lowered = self._lower_event(event)
            if lowered is not None:
                input_items.append(lowered)

        if kwargs.get("store") is False:
            # With store=False, provider response items are not persisted; replaying
            # ids like rs_... can resolve missing items. Keep call_id for tool
            # continuity, but omit every item id consistently so prompt cache keys
            # remain stable across turns.
            input_items = _omit_response_item_ids_for_unstored_request(input_items)
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
        return NativeModelRequest(
            model=model,
            input=input_items,
            tools=tools,
            kwargs=kwargs,
        )

    def _lower_model_kwargs(self) -> dict[str, object]:
        """Lower RunRequest model options to provider-native Responses kwargs."""
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
        if self._provider_id == LLMProvider.OPENROUTER:
            kwargs.setdefault("custom_llm_provider", "openrouter")
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

    def _compatible_native_items(
        self,
        event: Event,
    ) -> list[dict[str, object]] | None:
        """Return same-native replay items, including Azents-local context."""
        match event.payload:
            case (
                ProviderToolCallPayload(
                    name="image_generation",
                    status=status,
                    semantic=semantic,
                    native_artifact=artifact,
                ) as payload
            ):
                if not artifact.compatible_with(self.compat_key):
                    return None
                file_parts = _file_output_parts(semantic.output)
                if file_parts:
                    result = _rehydrated_image_generation_result(
                        semantic.output,
                        resolver=self.model_file_resolver,
                    )
                    if result is None:
                        return None
                else:
                    native_result = artifact.item.get("result")
                    result = native_result if isinstance(native_result, str) else None
                native_item = _lower_image_generation_native_item(
                    artifact.item,
                    status=status,
                    result=result,
                )
                local_parts = [
                    part
                    for part in iter_output_parts(semantic.output)
                    if isinstance(part, AttachmentOutputPart)
                ]
                if not local_parts:
                    return [native_item]
                local_payload = payload.model_copy(
                    update={
                        "semantic": semantic.model_copy(
                            update={
                                "input": None,
                                "output": local_parts,
                                "references": [],
                            }
                        )
                    }
                )
                return [
                    native_item,
                    _lower_provider_tool_semantic_payload(
                        local_payload,
                        capabilities=self._file_part_capabilities,
                        model_file_resolver=self.model_file_resolver,
                    ),
                ]
            case ReasoningPayload(native_artifact=artifact):
                if artifact.compatible_with(self.compat_key):
                    return [sanitize_responses_native_item(dict(artifact.item))]
            case (
                AssistantMessagePayload(native_artifact=artifact)
                | ClientToolCallPayload(native_artifact=artifact)
                | ProviderToolCallPayload(native_artifact=artifact)
                | UnknownAdapterOutputPayload(native_artifact=artifact)
            ):
                if artifact.compatible_with(self.compat_key):
                    return [artifact.item]
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
            case ProviderToolCallPayload() as payload:
                return _lower_provider_tool_semantic_payload(
                    payload,
                    capabilities=self._file_part_capabilities,
                    model_file_resolver=self.model_file_resolver,
                )
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
    raise TypeError("Responses include option must be list[str]")


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
    """Return whether the target accepts Anthropic cache_control hints."""
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
        LLMProvider.OPENROUTER,
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
    """Lower semantic hosted tool settings to the native Responses surface."""
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
        if tool.name not in supported:
            msg = f"Required builtin tool is not supported: {tool.name}"
            raise UnsupportedRequiredBuiltinToolError(msg)
        config = dict(tool.config)
        match tool.name:
            case "web_search":
                match target:
                    case "openai" | "xai":
                        native_tools.append({"type": "web_search", **config})
                    case "openrouter":
                        native_tools.append({"type": "openrouter:web_search", **config})
                    case "google":
                        native_tools.append({"google_search": config})
                    case "anthropic":
                        native_tools.append(
                            {
                                "type": "web_search_20250305",
                                "name": "web_search",
                                **config,
                            }
                        )
                    case "fallback":
                        msg = f"Required builtin tool is not supported: {tool.name}"
                        raise UnsupportedRequiredBuiltinToolError(msg)
                    case _:
                        msg = f"Required builtin tool is not supported: {tool.name}"
                        raise UnsupportedRequiredBuiltinToolError(msg)
            case "image_generation":
                if target in {"fallback", "openrouter"}:
                    msg = f"Required builtin tool is not supported: {tool.name}"
                    raise UnsupportedRequiredBuiltinToolError(msg)
                native_tools.append({"type": "image_generation", **config})
            case _:
                msg = f"Required builtin tool is not implemented: {tool.name}"
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
    if provider_id == LLMProvider.OPENROUTER:
        return "openrouter"
    if model_developer == LLMModelDeveloper.GOOGLE:
        return "google"
    if model_developer == LLMModelDeveloper.ANTHROPIC:
        return "anthropic"
    if provider in {"openai", "chatgpt_oauth"}:
        return "openai"
    if provider in {"xai", "xai_oauth"}:
        return "xai"
    if provider == "openrouter":
        return "openrouter"
    if provider in {"google_gemini", "google_vertex_ai"}:
        return "google"
    if provider == "anthropic":
        return "anthropic"
    return "fallback"


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


def _lower_image_generation_native_item(
    native_item: Mapping[str, object],
    *,
    status: str | None,
    result: str | None,
) -> dict[str, object]:
    """Rebuild one generated-image replay item for the Responses input schema."""
    native_status = native_item.get("status")
    if isinstance(native_status, str) and native_status in {
        "in_progress",
        "completed",
        "generating",
        "failed",
    }:
        replay_status = native_status
    elif status == "completed":
        replay_status = "completed"
    else:
        replay_status = "failed"
    lowered: dict[str, object] = {
        "type": "image_generation_call",
        "status": replay_status,
        "result": result,
    }
    native_id = native_item.get("id")
    if isinstance(native_id, str) and native_id:
        lowered["id"] = native_id
    return lowered


def _omit_response_item_ids_for_unstored_request(
    input_items: Sequence[dict[str, object]],
) -> list[dict[str, object]]:
    """Omit provider item ids from unstored Responses replay."""
    normalized: list[dict[str, object]] = []
    for item in input_items:
        if "id" not in item:
            normalized.append(item)
            continue
        without_id = dict(item)
        without_id.pop("id")
        normalized.append(without_id)
    return normalized


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


def _file_output_parts(output: ToolOutput) -> list[FileOutputPart]:
    """Return FileParts from one provider or client tool result."""
    return [
        part for part in iter_output_parts(output) if isinstance(part, FileOutputPart)
    ]


def _rehydrated_image_generation_result(
    output: ToolOutput,
    *,
    resolver: ModelFileResolver | None,
) -> str | None:
    """Resolve one generated image as plain request-local Base64."""
    file_parts = _file_output_parts(output)
    if len(file_parts) != 1 or resolver is None:
        return None
    content = resolver.resolve(file_parts[0])
    if content is None or content.data_url is None:
        return None
    header, separator, encoded = content.data_url.partition(";base64,")
    if not separator or not header.startswith("data:") or not encoded:
        return None
    return encoded


def _lower_provider_tool_semantic_payload(
    payload: ProviderToolCallPayload,
    *,
    capabilities: FilePartLoweringCapabilities,
    model_file_resolver: ModelFileResolver | None,
) -> dict[str, object]:
    """Lower canonical provider-tool semantics with rich FileParts when present."""
    file_parts = _file_output_parts(payload.semantic.output)
    if not file_parts:
        return {
            "role": "assistant",
            "content": render_provider_tool_semantic(payload),
        }

    non_file_output = [
        part
        for part in iter_output_parts(payload.semantic.output)
        if not isinstance(part, FileOutputPart)
    ]
    rendered_payload = payload.model_copy(
        update={
            "semantic": payload.semantic.model_copy(update={"output": non_file_output})
        }
    )
    content: list[dict[str, object]] = [
        {
            "type": "input_text",
            "text": render_provider_tool_semantic(rendered_payload),
        }
    ]
    content.extend(
        lower_file_output_part(
            part,
            capabilities=capabilities,
            resolver=model_file_resolver,
        )
        for part in file_parts
    )
    return {"role": "user", "content": content}
