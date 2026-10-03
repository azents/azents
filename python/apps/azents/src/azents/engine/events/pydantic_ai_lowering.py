"""Lower canonical Azents history to the public Pydantic model message layer."""

import base64
import json
from collections.abc import Mapping, Sequence
from typing import Any, Literal

from google.genai.types import ThinkingConfigDict
from google.genai.types import ThinkingLevel as GoogleThinkingLevel
from pydantic import BaseModel, ConfigDict, Field, TypeAdapter
from pydantic_ai.messages import (
    BinaryContent,
    CachePoint,
    DocumentUrl,
    ImageUrl,
    ModelMessage,
    ModelMessagesTypeAdapter,
    ModelRequest,
    ModelResponse,
    SystemPromptPart,
    TextPart,
    ToolCallPart,
    ToolReturnPart,
    UserContent,
    UserPromptPart,
)
from pydantic_ai.models import ModelRequestParameters
from pydantic_ai.models.anthropic import AnthropicModelSettings
from pydantic_ai.models.google import GoogleModelSettings
from pydantic_ai.models.openai import OpenAIResponsesModelSettings
from pydantic_ai.native_tools import (
    AbstractNativeTool,
    ImageGenerationTool,
    WebSearchTool,
)
from pydantic_ai.settings import ModelSettings
from pydantic_ai.tools import ToolDefinition

from azents.core.enums import EventKind, LLMModelDeveloper, LLMProvider
from azents.core.llm_catalog import ModelCapabilities
from azents.core.model_execution_options import ModelExecutionOptionId
from azents.core.type_guards import is_string_object_dict
from azents.engine.events.external_channel_rendering import render_external_channel_turn
from azents.engine.events.file_parts import (
    FilePartLoweringCapabilities,
    ModelFileResolver,
    file_output_part_placeholder_text,
    lower_file_output_part,
)
from azents.engine.events.model_messages import ModelTranscriptMessage
from azents.engine.events.output_parts import (
    enforce_tool_output_text_hard_cap,
    lower_output_to_text,
)
from azents.engine.events.provider_tool_rendering import render_provider_tool_semantic
from azents.engine.events.pydantic_ai_types import PydanticAIRequest
from azents.engine.events.responses_lowering import resolve_openai_service_tier
from azents.engine.events.system_reminders import (
    format_compaction_summary_reminder,
    format_external_channel_continuation_reminder,
    format_goal_continuation_reminder,
    format_goal_resumed_reminder,
    format_goal_updated_reminder,
    format_interrupted_reminder,
    format_plain_system_reminder,
)
from azents.engine.events.types import (
    AgentMessagePayload,
    AssistantMessagePayload,
    AttachmentOutputPart,
    ClientToolCallPayload,
    ClientToolResultPayload,
    CompactionSummaryPayload,
    ExternalChannelMessagePayload,
    FileOutputPart,
    InputTextPart,
    InterruptedPayload,
    OutputTextPart,
    ProviderToolCallPayload,
    ReasoningPayload,
    ScheduledTaskContinuationPayload,
    ScheduledTaskResultPayload,
    ScheduledTaskTriggerPayload,
    SkillLoadedPayload,
    SystemReminderPayload,
    ToolOutput,
    UserMessagePayload,
    build_native_compat_key,
)
from azents.engine.run.types import BuiltinToolSpec

_TOOL_DEFINITION_ADAPTER = TypeAdapter(ToolDefinition)
_DEFAULT_INSTRUCTIONS = "You are a helpful assistant."


class _OpenAISettings(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)
    value: OpenAIResponsesModelSettings


class _AnthropicSettings(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)
    value: AnthropicModelSettings


class _GoogleSettings(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)
    value: GoogleModelSettings


class _BedrockRequestSettings(ModelSettings, total=False):
    """Runtime-complete settings for the Bedrock request fields Azents uses."""

    bedrock_cache_instructions: bool | Literal["5m", "1h"]
    bedrock_cache_tool_definitions: bool | Literal["5m", "1h"]
    bedrock_cache_messages: bool | Literal["5m", "1h"]
    bedrock_additional_model_requests_fields: Mapping[str, Any]
    bedrock_inference_profile: str


class _BedrockSettings(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)
    # The SDK's full TypedDict includes foreign TYPE_CHECKING-only AWS types.
    # Validate our used request domain instead of resolving those unused fields.
    value: _BedrockRequestSettings


class _DeclaredTool(BaseModel):
    """Decode an already-selected declaration at the model boundary."""

    model_config = ConfigDict(extra="ignore", frozen=True)

    type: str = "function"
    name: str = Field(min_length=1)
    description: str | None = None
    parameters: dict[str, Any] | None = None
    strict: bool | None = None
    format: dict[str, Any] | None = None


class PydanticAILowerer:
    """Keep transcript and capability authority outside the model library."""

    adapter = "pydantic_ai"
    native_format = "model_messages"
    schema_version = "1"

    def __init__(
        self,
        *,
        provider: str,
        model: str,
        provider_id: LLMProvider,
        tools: Sequence[dict[str, object]] | None,
        model_capabilities: ModelCapabilities | None,
        supported_execution_options: Sequence[ModelExecutionOptionId],
        enabled_execution_options: Sequence[ModelExecutionOptionId],
        kwargs: Mapping[str, object] | None = None,
        temperature: float | None = None,
        max_output_tokens: int | None = None,
        top_p: float | None = None,
        stop: list[str] | None = None,
        reasoning_effort: str | None = None,
        hosted_tools: Sequence[BuiltinToolSpec] | None = None,
        prompt_cache_scope: str | None = None,
        model_developer: LLMModelDeveloper | None = None,
        model_file_resolver: ModelFileResolver | None = None,
        historical_plaintext_custom_supported: bool = False,
    ) -> None:
        self.provider = provider
        self.model = model
        self.provider_id = provider_id
        self.model_capabilities = model_capabilities or ModelCapabilities()
        self.model_file_resolver = model_file_resolver
        self.tools = [dict(tool) for tool in tools] if tools is not None else []
        self.hosted_tools = list(hosted_tools) if hosted_tools is not None else []
        self.options = dict(kwargs) if kwargs is not None else {}
        self.temperature = temperature
        self.max_output_tokens = max_output_tokens
        self.top_p = top_p
        self.stop = stop
        self.reasoning_effort = reasoning_effort
        self.model_developer = model_developer
        self.prompt_cache_scope = prompt_cache_scope
        self.supported_execution_options = tuple(supported_execution_options)
        self.enabled_execution_options = tuple(enabled_execution_options)
        self.historical_plaintext_custom_supported = (
            historical_plaintext_custom_supported
        )
        self.compat_key = build_native_compat_key(
            adapter=self.adapter,
            native_format=self.native_format,
            provider=provider,
            model=model,
            schema_version=self.schema_version,
        )
        self.file_capabilities = FilePartLoweringCapabilities.from_model_capabilities(
            self.model_capabilities
        )

    def lower(
        self,
        transcript: Sequence[ModelTranscriptMessage],
        *,
        model: str,
        system_prompt: str | None = None,
    ) -> PydanticAIRequest:
        """Build explicit model messages without another execution graph."""
        if model != self.model:
            raise ValueError("Lowerer model identity differs from the selected model")
        messages: list[ModelMessage] = [
            ModelRequest(
                parts=[SystemPromptPart(system_prompt or _DEFAULT_INSTRUCTIONS)]
            )
        ]
        calls: dict[str, tuple[str, str]] = {}
        unrepresentable_calls: set[str] = set()
        index = 0
        while index < len(transcript):
            event = transcript[index]
            payload = event.payload
            if isinstance(payload, ExternalChannelMessagePayload):
                batch: list[ExternalChannelMessagePayload] = []
                batch_id = payload.invocation_batch_id
                while index < len(transcript):
                    candidate = transcript[index].payload
                    if not isinstance(candidate, ExternalChannelMessagePayload):
                        break
                    if candidate.invocation_batch_id != batch_id:
                        break
                    batch.append(candidate)
                    index += 1
                messages.append(
                    ModelRequest(
                        parts=[UserPromptPart(render_external_channel_turn(batch))]
                    )
                )
                continue
            index += 1
            if isinstance(payload, ClientToolCallPayload):
                if (
                    payload.wire_dialect == "json_function"
                    and self.provider_id
                    in {
                        LLMProvider.ANTHROPIC,
                        LLMProvider.GOOGLE_GEMINI,
                        LLMProvider.AWS_BEDROCK,
                        LLMProvider.GOOGLE_VERTEX_AI,
                    }
                    and not _object_arguments(payload.arguments)
                ):
                    unrepresentable_calls.add(payload.call_id)
                    preview = payload.arguments[:3000]
                    messages.append(
                        self._prompt(
                            f"[Historical function call: {payload.name}; "
                            "invalid JSON arguments; non-executable]\n"
                            f"{preview}"
                        )
                    )
                    continue
                if (
                    payload.wire_dialect == "plaintext_custom"
                    and not self._custom_supported(payload.name)
                ):
                    messages.append(
                        self._prompt(
                            f"[Historical custom tool call: {payload.name}; "
                            "non-executable]"
                        )
                    )
                    continue
                native = self._native(event)
                if native is not None and self._native_call_matches(native, payload):
                    messages.extend(native)
                else:
                    messages.append(
                        ModelResponse(
                            parts=[
                                ToolCallPart(
                                    tool_name=payload.name,
                                    tool_call_id=payload.call_id,
                                    args=payload.arguments,
                                    provider_details={
                                        "azents_wire_dialect": payload.wire_dialect
                                    },
                                    provider_name=self.provider,
                                )
                            ]
                        )
                    )
                calls[payload.call_id] = (payload.name, payload.wire_dialect)
                continue
            if isinstance(payload, ClientToolResultPayload):
                matched = calls.get(payload.call_id)
                if payload.call_id in unrepresentable_calls:
                    preview = lower_output_to_text(
                        enforce_tool_output_text_hard_cap(payload.output)
                    )[:3000]
                    messages.append(
                        self._prompt(
                            f"[Historical function result; non-executable]\n{preview}"
                        )
                    )
                    continue
                if payload.wire_dialect == "plaintext_custom" and matched is None:
                    preview = lower_output_to_text(
                        enforce_tool_output_text_hard_cap(payload.output)
                    )[:3000]
                    messages.append(
                        self._prompt(
                            "[Historical custom tool result: "
                            f"{payload.name or 'unknown'}; "
                            f"non-executable]\n{preview}"
                        )
                    )
                    continue
                if matched is None or matched[1] != payload.wire_dialect:
                    continue
                name = matched[0]
                messages.append(
                    ModelRequest(
                        parts=[
                            ToolReturnPart(
                                tool_name=name,
                                tool_call_id=payload.call_id,
                                content=self._output_content(
                                    enforce_tool_output_text_hard_cap(payload.output)
                                ),
                                outcome="success"
                                if payload.status == "completed"
                                else "interrupted"
                                if payload.status in {"interrupted", "cancelled"}
                                else "failed",
                                metadata={"azents_wire_dialect": payload.wire_dialect},
                            )
                        ]
                    )
                )
                continue
            native = self._native(event)
            if native is not None:
                messages.extend(native)
                continue
            message = self._canonical(event)
            if message is not None:
                messages.append(message)

        parameters = self._parameters()
        settings = self._settings()
        if self._anthropic_cache_route():
            remaining = 2
            for message in messages:
                if remaining == 0:
                    break
                if not isinstance(message, ModelRequest):
                    continue
                for part in message.parts:
                    if isinstance(part, UserPromptPart) and part.content:
                        values = (
                            [part.content]
                            if isinstance(part.content, str)
                            else list(part.content)
                        )
                        part.content = [*values, CachePoint()]
                        remaining -= 1
                        break
        return PydanticAIRequest(
            provider=self.provider,
            model=model,
            messages=messages,
            settings=settings,
            parameters=parameters,
            assembly_metadata=None,
        )

    @staticmethod
    def _prompt(content: str | Sequence[UserContent]) -> ModelRequest:
        return ModelRequest(parts=[UserPromptPart(content)])

    def _native(self, event: ModelTranscriptMessage) -> list[ModelMessage] | None:
        payload = event.payload
        if not isinstance(
            payload,
            AssistantMessagePayload
            | ReasoningPayload
            | ProviderToolCallPayload
            | ClientToolCallPayload,
        ):
            return None
        artifact = payload.native_artifact
        if not artifact.compatible_with(self.compat_key):
            return None
        message = artifact.item.get("message")
        if not is_string_object_dict(message):
            return None
        decoded = ModelMessagesTypeAdapter.validate_python([message])
        if not all(isinstance(part, ModelResponse) for part in decoded):
            return None
        return decoded

    @staticmethod
    def _native_call_matches(
        messages: Sequence[ModelMessage], payload: ClientToolCallPayload
    ) -> bool:
        parts = [
            part
            for message in messages
            if isinstance(message, ModelResponse)
            for part in message.parts
            if isinstance(part, ToolCallPart)
        ]
        if len(parts) != 1:
            return False
        part = parts[0]
        dialect = (part.provider_details or {}).get(
            "azents_wire_dialect", "json_function"
        )
        matches = (
            part.tool_call_id == payload.call_id
            and part.tool_name == payload.name
            and dialect == payload.wire_dialect
        )
        if not matches:
            return False
        if payload.wire_dialect == "plaintext_custom":
            return part.args == payload.arguments
        try:
            canonical_args = json.loads(payload.arguments)
            native_args = (
                json.loads(part.args) if isinstance(part.args, str) else part.args
            )
        except json.JSONDecodeError:
            return False
        return native_args == canonical_args

    def _canonical(self, event: ModelTranscriptMessage) -> ModelMessage | None:
        payload = event.payload
        if isinstance(payload, UserMessagePayload):
            if event.kind == EventKind.GOAL_CONTINUATION:
                return self._prompt(
                    format_goal_continuation_reminder(
                        payload.metadata.get("goal_objective")
                    )
                )
            if event.kind == EventKind.EXTERNAL_CHANNEL_CONTINUATION:
                return self._prompt(
                    format_external_channel_continuation_reminder(payload.metadata)
                )
            if event.kind == EventKind.GOAL_UPDATED:
                if payload.metadata.get("goal_control_action") == "resume":
                    return self._prompt(
                        format_goal_resumed_reminder(
                            goal_objective=payload.metadata.get("goal_objective"),
                            previous_goal_status=payload.metadata.get(
                                "previous_goal_status"
                            ),
                            resume_hint=payload.metadata.get("resume_hint"),
                        )
                    )
                return self._prompt(
                    format_goal_updated_reminder(payload.metadata.get("goal_objective"))
                )
            content: list[UserContent] = []
            if isinstance(payload.content, str):
                content.append(payload.content)
            else:
                for part in payload.content:
                    if isinstance(part, InputTextPart):
                        content.append(part.text)
                    elif isinstance(part, FileOutputPart):
                        content.append(self._file(part))
            for attachment in payload.attachments:
                content.append(
                    lower_output_to_text(
                        [
                            AttachmentOutputPart(
                                uri=attachment.uri,
                                name=attachment.name,
                                media_type=attachment.media_type,
                                size=attachment.size,
                                availability=attachment.availability,
                                preview_title=attachment.preview_title,
                                preview_summary=attachment.preview_summary,
                            )
                        ]
                    )
                )
            return self._prompt(content)
        if isinstance(payload, AssistantMessagePayload):
            text = (
                payload.content
                if isinstance(payload.content, str)
                else lower_output_to_text(payload.content)
            )
            return ModelResponse(parts=[TextPart(text)])
        if isinstance(payload, ProviderToolCallPayload):
            content = [render_provider_tool_semantic(payload)]
            content.extend(
                self._file(part)
                for part in payload.semantic.output
                if isinstance(part, FileOutputPart)
            )
            return self._prompt(content)
        if isinstance(payload, ReasoningPayload):
            return None
        if isinstance(payload, CompactionSummaryPayload):
            return self._prompt(format_compaction_summary_reminder(payload.content))
        if isinstance(payload, InterruptedPayload):
            return self._prompt(format_interrupted_reminder())
        if isinstance(payload, SystemReminderPayload):
            return self._prompt(format_plain_system_reminder(payload.text))
        if isinstance(
            payload, ScheduledTaskTriggerPayload | ScheduledTaskContinuationPayload
        ):
            return self._prompt(payload.content)
        if isinstance(payload, ScheduledTaskResultPayload):
            return ModelResponse(
                parts=[
                    TextPart(
                        f"Scheduled Task: {payload.title}\n"
                        f"Status: {payload.status}\nResult: {payload.result}"
                    )
                ]
            )
        if isinstance(payload, AgentMessagePayload):
            if payload.message_kind == "agent_result":
                assert payload.run_status is not None
                return self._prompt(
                    f"Message Type: AGENT_RESULT\nTask name: {payload.target_path}\n"
                    f"Sender: {payload.source_path}\n"
                    f"Run status: {payload.run_status.value}\n"
                    f"Payload:\n{payload.content}"
                )
            kind = (
                "NEW_TASK"
                if payload.message_kind in {"spawn_agent", "followup_task"}
                else "MESSAGE"
            )
            return self._prompt(
                f"Message Type: {kind}\nTask name: {payload.target_path}\n"
                f"Sender: {payload.source_path}\nPayload:\n{payload.content}"
            )
        if isinstance(payload, SkillLoadedPayload):
            user_note = (
                "The user's request is provided in the next user message."
                if payload.user_message.strip()
                else "No additional user request was provided."
            )
            return self._prompt(
                f"Skill `{payload.name}` has been loaded.\n"
                "Read and follow the following Skill body.\n\n"
                f"{user_note}\n\n"
                f"Skill path: `{payload.skill_path}`\n\n"
                f"<skill_body>\n{payload.body}\n</skill_body>"
            )
        return None

    def _output_content(self, output: ToolOutput) -> str | list[UserContent]:
        if isinstance(output, str):
            return output
        content: list[UserContent] = []
        for part in output:
            if isinstance(part, FileOutputPart):
                content.append(self._file(part))
            elif isinstance(part, OutputTextPart):
                content.append(part.text)
            else:
                content.append(lower_output_to_text([part]))
        if all(isinstance(part, str) for part in content):
            return "\n".join(part for part in content if isinstance(part, str))
        return content

    def _file(self, part: FileOutputPart) -> UserContent:
        item = lower_file_output_part(
            part, capabilities=self.file_capabilities, resolver=self.model_file_resolver
        )
        if item.get("type") == "input_text":
            text = item.get("text")
            return (
                text
                if isinstance(text, str)
                else file_output_part_placeholder_text(
                    part, reason="file input is unavailable"
                )
            )
        uri = item.get("image_url") or item.get("file_data") or item.get("file_url")
        if not isinstance(uri, str):
            return file_output_part_placeholder_text(
                part, reason="provider file identity is unavailable for this route"
            )
        if uri.startswith("data:"):
            prefix, encoded = uri.split(",", 1)
            if not prefix.endswith(";base64"):
                raise ValueError("Request-local file data URL is not base64 encoded")
            return BinaryContent(
                data=base64.b64decode(encoded, validate=True),
                media_type=part.media_type,
                identifier=part.model_file_id,
            )
        if part.media_type.startswith("image/"):
            return ImageUrl(uri)
        return DocumentUrl(uri, media_type=part.media_type)

    def _custom_supported(self, name: str | None) -> bool:
        return (
            self.provider_id in {LLMProvider.OPENAI, LLMProvider.CHATGPT_OAUTH}
            and self.historical_plaintext_custom_supported
            and name is not None
            and any(
                tool.get("type") == "custom" and tool.get("name") == name
                for tool in self.tools
            )
        )

    def _parameters(self) -> ModelRequestParameters:
        definitions: list[ToolDefinition] = []
        for raw in self.tools:
            nested = raw.get("function")
            selected = (
                {**nested, "type": "function"} if is_string_object_dict(nested) else raw
            )
            tool = _DeclaredTool.model_validate(selected)
            if tool.type not in {"function", "custom"}:
                raise ValueError("Unsupported client tool declaration dialect")
            schema = (
                tool.parameters
                if tool.parameters is not None
                else {"type": "object", "properties": {}}
            )
            if tool.type == "custom":
                if self.provider_id not in {
                    LLMProvider.OPENAI,
                    LLMProvider.CHATGPT_OAUTH,
                }:
                    raise ValueError(
                        "The selected replacement route does not support "
                        "plaintext custom declarations"
                    )
                schema = {
                    "type": "object",
                    "properties": {"input": {"type": "string"}},
                    "required": ["input"],
                }
            if schema.get("type") != "object":
                raise ValueError("Client tool input schema must be a top-level object")
            definitions.append(
                _TOOL_DEFINITION_ADAPTER.validate_python(
                    {
                        "name": tool.name,
                        "description": tool.description,
                        "parameters_json_schema": schema,
                        "strict": (
                            tool.strict is True
                            and self.model_capabilities.tool_calling.strict_json_schema
                            is True
                        ),
                        "metadata": {
                            "azents_wire_dialect": "plaintext_custom"
                            if tool.type == "custom"
                            else "json_function",
                            "azents_declaration": dict(selected),
                        },
                    }
                )
            )
        limit = (
            200
            if self.provider_id in {LLMProvider.XAI, LLMProvider.XAI_OAUTH}
            else 128
            if self.provider_id == LLMProvider.GOOGLE_VERTEX_AI
            and self.model_developer != LLMModelDeveloper.ANTHROPIC
            else None
        )
        if limit is not None and len(definitions) > limit:
            raise ValueError("Provider client tool declaration limit exceeded")
        native_tools: list[AbstractNativeTool] = []
        for selected in self.hosted_tools:
            if selected.name not in self.model_capabilities.built_in_tools.supported:
                raise ValueError(
                    "Hosted tool is not authorized by the saved capability snapshot"
                )
            if selected.name == "image_generation":
                if (
                    self.provider_id
                    not in {
                        LLMProvider.GOOGLE_GEMINI,
                        LLMProvider.GOOGLE_VERTEX_AI,
                    }
                    or self.model_developer == LLMModelDeveloper.ANTHROPIC
                ):
                    raise ValueError(
                        "Selected provider/model route does not support "
                        "hosted image generation"
                    )
                native_tools.append(
                    TypeAdapter(ImageGenerationTool).validate_python(selected.config)
                )
            elif selected.name == "web_search":
                native_tools.append(
                    TypeAdapter(WebSearchTool).validate_python(selected.config)
                )
            else:
                raise ValueError(
                    "Selected hosted tool has no authorized model-layer implementation"
                )
        return ModelRequestParameters(
            function_tools=definitions,
            native_tools=native_tools,
            allow_text_output=True,
        )

    def _anthropic_cache_route(self) -> bool:
        return (
            self.provider_id == LLMProvider.ANTHROPIC
            or self.model_developer == LLMModelDeveloper.ANTHROPIC
            and self.provider_id
            in {
                LLMProvider.AWS_BEDROCK,
                LLMProvider.GOOGLE_VERTEX_AI,
                LLMProvider.KIMI_OAUTH,
            }
        )

    def _settings(self) -> ModelSettings:
        values: dict[str, object] = dict(self.options)
        if any(
            key in values
            for key in (
                "api_key",
                "base_url",
                "api_base",
                "vertex_credentials",
                "aws_secret_access_key",
                "extra_headers",
            )
        ):
            raise ValueError("Model settings must not contain client credentials")
        extra_body = values.get("extra_body")
        if extra_body is not None and not is_string_object_dict(extra_body):
            raise ValueError("Model extra_body must be an object")
        if (
            "service_tier" in values
            or "openai_service_tier" in values
            or extra_body is not None
            and "service_tier" in extra_body
        ):
            raise ValueError("Service tier must come from authorized execution options")
        if self.temperature is not None:
            values["temperature"] = self.temperature
        if self.max_output_tokens is not None:
            values["max_tokens"] = self.max_output_tokens
        if self.top_p is not None:
            values["top_p"] = self.top_p
        if self.stop is not None:
            values["stop_sequences"] = self.stop
        if self.model_capabilities.tool_calling.parallel_tool_calls is not True:
            values["parallel_tool_calls"] = False
        service_tier = resolve_openai_service_tier(
            provider=self.provider_id,
            supported=self.supported_execution_options,
            enabled=self.enabled_execution_options,
        )
        if service_tier == "ultrafast":
            # The public ModelSettings extra_body reaches the official SDK;
            # this pinned model library's typed tier field predates Ultrafast.
            values["extra_body"] = {
                **(extra_body if extra_body is not None else {}),
                "service_tier": service_tier,
            }
        elif service_tier is not None:
            values["openai_service_tier"] = service_tier
        if self.reasoning_effort is not None and self.reasoning_effort not in [
            effort.value for effort in self.model_capabilities.reasoning.effort_levels
        ]:
            raise ValueError(
                "Reasoning effort is not authorized by the saved capability snapshot"
            )
        if self.provider_id == LLMProvider.AWS_BEDROCK:
            settings = _BedrockSettings.model_validate({"value": values}).value
            if self._anthropic_cache_route():
                settings["bedrock_cache_instructions"] = True
                settings["bedrock_cache_tool_definitions"] = True
                if self.reasoning_effort is not None:
                    additional = dict(
                        settings.get("bedrock_additional_model_requests_fields", {})
                    )
                    output_config = additional.get("output_config")
                    if output_config is not None and not is_string_object_dict(
                        output_config
                    ):
                        raise ValueError("Bedrock output_config must be an object")
                    additional["output_config"] = {
                        **(output_config if output_config is not None else {}),
                        "effort": self.reasoning_effort,
                    }
                    settings["bedrock_additional_model_requests_fields"] = additional
            return settings
        if self._anthropic_cache_route():
            values["anthropic_cache_instructions"] = True
            values["anthropic_cache_tool_definitions"] = True
            if self.reasoning_effort is not None:
                values["anthropic_effort"] = self.reasoning_effort
            return _AnthropicSettings.model_validate({"value": values}).value
        if self.provider_id in {
            LLMProvider.GOOGLE_GEMINI,
            LLMProvider.GOOGLE_VERTEX_AI,
        }:
            if self.reasoning_effort is not None:
                values["google_thinking_config"] = _google_thinking_config(
                    model=self.model, effort=self.reasoning_effort
                )
            return _GoogleSettings.model_validate({"value": values}).value
        if self.reasoning_effort is not None:
            extra_body = values.get("extra_body")
            if extra_body is not None and not is_string_object_dict(extra_body):
                raise ValueError("Model extra_body must be an object")
            values["extra_body"] = {
                **(extra_body if extra_body is not None else {}),
                "reasoning": {"effort": self.reasoning_effort, "summary": "auto"},
            }
        if self.provider_id == LLMProvider.OPENROUTER:
            values["openai_include_raw_annotations"] = True
            values["openai_include_web_search_sources"] = True
        return _OpenAISettings.model_validate({"value": values}).value


def _object_arguments(value: str) -> bool:
    try:
        decoded = json.loads(value)
    except json.JSONDecodeError:
        return False
    return isinstance(decoded, dict)


def _google_thinking_config(*, model: str, effort: str) -> ThinkingConfigDict:
    """Preserve the previous authorized Gemini effort-to-wire mapping."""
    if effort not in {"none", "minimal", "low", "medium", "high"}:
        raise ValueError("Selected Google reasoning effort has no supported mapping")
    # Inspect known family tokens without rewriting the selected resource ID.
    # The retired Gemini mapper distinguishes Gemini 3 from budget-based models.
    name = model.lower()
    include_thoughts = effort != "none"
    if "gemini-3" in name:
        flash = "flash" in name
        if effort in {"none", "minimal"}:
            level = GoogleThinkingLevel.MINIMAL if flash else GoogleThinkingLevel.LOW
        elif effort == "low":
            level = GoogleThinkingLevel.LOW
        elif effort == "medium":
            level = (
                GoogleThinkingLevel.MEDIUM
                if flash or "gemini-3.1-pro-preview" in name
                else GoogleThinkingLevel.HIGH
            )
        else:
            level = GoogleThinkingLevel.HIGH
        return ThinkingConfigDict(
            thinking_level=level, include_thoughts=include_thoughts
        )
    if effort == "minimal":
        budget = (
            512
            if "gemini-2.5-flash-lite" in name
            else 128
            if "gemini-2.5-pro" in name
            else 1
            if "gemini-2.5-flash" in name
            else 128
        )
    else:
        budget = {"none": 0, "low": 1024, "medium": 2048, "high": 4096}[effort]
    return ThinkingConfigDict(thinking_budget=budget, include_thoughts=include_thoughts)
