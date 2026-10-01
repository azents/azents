"""Credential-free runtime model profile authority shared with catalog projection."""

from __future__ import annotations

import dataclasses
import re
from collections.abc import Mapping
from typing import Literal, assert_never

from pydantic_ai.models import Model
from pydantic_ai.models.anthropic import AnthropicModel
from pydantic_ai.models.bedrock import BedrockConverseModel
from pydantic_ai.models.google import GoogleModel
from pydantic_ai.models.openai import OpenAIChatModel, OpenAIResponsesModel
from pydantic_ai.native_tools import ImageGenerationTool, WebSearchTool
from pydantic_ai.profiles import ModelProfile, merge_profile
from pydantic_ai.profiles.anthropic import AnthropicModelProfile
from pydantic_ai.profiles.google import GoogleModelProfile
from pydantic_ai.profiles.openai import OpenAIModelProfile
from pydantic_ai.providers.anthropic import AnthropicProvider
from pydantic_ai.providers.bedrock import BedrockModelProfile, BedrockProvider
from pydantic_ai.providers.google import GoogleProvider
from pydantic_ai.providers.openai import OpenAIProvider

from azents.core.builtin_tools import supported_builtin_capabilities
from azents.core.enums import LLMModelDeveloper, LLMProvider
from azents.core.llm_catalog import (
    ModelBuiltInToolCapabilities,
    ModelCapabilities,
    ModelCompatibilityCapabilities,
    ModelContextWindow,
    ModelModalities,
    ModelModality,
    ModelParameterCapabilities,
    ModelReasoningCapabilities,
    ModelReasoningEffort,
    ModelToolCallingCapabilities,
)
from azents.core.model_metadata_source import SourceModelRecord
from azents.engine.events.pydantic_ai_types import NativeModelProtocol
from azents.engine.model_assembly import ModelAssemblyMetadata

RUNTIME_MODEL_PROFILE_RESOLVER_REVISION = "2"

RuntimeModelKind = Literal[
    "native_openai_responses",
    "openai_responses",
    "openai_chat",
    "anthropic",
    "google",
    "bedrock",
]


@dataclasses.dataclass(frozen=True)
class RuntimeModelProfileResolution:
    """One shared runtime route, effective profile, and catalog capability view."""

    protocol: NativeModelProtocol
    model_kind: RuntimeModelKind
    profile: ModelProfile
    normalized_capabilities: ModelCapabilities
    resolver_revision: str


_BEDROCK_MODEL_RESOURCE_ARN = re.compile(
    r"^arn:(?:aws|aws-cn|aws-us-gov|aws-iso|aws-iso-b|aws-iso-e|aws-iso-f)"
    r":bedrock:[a-z0-9-]+:(?P<account>[0-9]{12})?:"
    r"(?P<kind>foundation-model|inference-profile)/"
    r"(?P<model>[a-z0-9][A-Za-z0-9._:-]*)$"
)
_BEDROCK_OPAQUE_RESOURCE_ARN = re.compile(
    r"^arn:(?:aws|aws-cn|aws-us-gov|aws-iso|aws-iso-b|aws-iso-e|aws-iso-f)"
    r":bedrock:[a-z0-9-]+:[0-9]{12}:"
    r"(?:application-inference-profile|inference-profile|provisioned-model|"
    r"custom-model-deployment|custom-model)/[A-Za-z0-9][A-Za-z0-9._:/-]*$"
)


def bedrock_assembly_profile(model: str) -> ModelProfile | None:
    """Look up public Bedrock family wire traits for a literal or resource ID."""
    if not model.startswith("arn:"):
        return BedrockProvider.model_profile(model)
    resource = _BEDROCK_MODEL_RESOURCE_ARN.fullmatch(model)
    if resource is None:
        return None
    account = resource.group("account")
    if (resource.group("kind") == "foundation-model") != (account is None):
        return None
    return BedrockProvider.model_profile(resource.group("model"))


def saved_bedrock_assembly_profile(
    model: str,
    *,
    metadata: ModelAssemblyMetadata | None,
) -> BedrockModelProfile | None:
    """Retain reviewed family wire traits for opaque Bedrock resources."""
    if metadata is None or _BEDROCK_OPAQUE_RESOURCE_ARN.fullmatch(model) is None:
        return None
    match metadata.model_developer:
        case LLMModelDeveloper.ANTHROPIC:
            return BedrockModelProfile(
                bedrock_supports_tool_choice=True,
                bedrock_send_back_thinking_parts=True,
                bedrock_supports_prompt_caching=True,
                bedrock_supports_tool_caching=True,
                bedrock_supported_media_kinds_in_tool_returns=frozenset(
                    {"image", "document"}
                ),
                bedrock_tool_result_colocatable_content=frozenset({"text", "image"}),
                bedrock_supports_leading_assistant_message=True,
                bedrock_thinking_variant="anthropic",
                bedrock_top_k_variant="anthropic",
            )
        case LLMModelDeveloper.MISTRAL:
            return BedrockModelProfile(
                bedrock_tool_result_format="json",
                bedrock_tool_result_colocatable_content=frozenset(),
                bedrock_supported_media_kinds_in_tool_returns=frozenset({"document"}),
            )
        case LLMModelDeveloper.META:
            return BedrockModelProfile(
                bedrock_tool_result_colocatable_content=frozenset(),
                bedrock_supported_media_kinds_in_tool_returns=frozenset(
                    {"image", "document"}
                ),
            )
        case LLMModelDeveloper.OTHER:
            if metadata.model_family not in {"amazon.nova", "nova"}:
                return None
            return BedrockModelProfile(
                bedrock_supports_tool_choice=True,
                bedrock_supports_prompt_caching=True,
                bedrock_top_k_variant="nova",
            )
        case (
            None
            | LLMModelDeveloper.OPENAI
            | LLMModelDeveloper.GOOGLE
            | LLMModelDeveloper.XAI
            | LLMModelDeveloper.MOONSHOT
        ):
            return None
        case _ as unreachable:
            assert_never(unreachable)


def vertex_model_family(model: str) -> Literal["google", "anthropic"]:
    """Interpret a reviewed Vertex publisher resource or literal model ID."""
    parts = model.split("/")
    if "publishers" in parts:
        index = parts.index("publishers")
        if len(parts) <= index + 3 or parts[index + 2] != "models":
            raise ValueError("The Vertex publisher resource is malformed.")
        publisher = parts[index + 1]
        if publisher in {"google", "anthropic"}:
            return publisher
        raise ValueError("The Vertex publisher is not an authorized model family.")
    return "anthropic" if model.startswith("claude-") else "google"


def protocol_for_provider(*, provider: LLMProvider, model: str) -> NativeModelProtocol:
    """Resolve the reviewed native protocol without credentials."""
    match provider:
        case LLMProvider.ANTHROPIC:
            return "anthropic"
        case LLMProvider.GOOGLE_GEMINI:
            return "google"
        case LLMProvider.AWS_BEDROCK:
            return "bedrock"
        case LLMProvider.GOOGLE_VERTEX_AI:
            return (
                "anthropic" if vertex_model_family(model) == "anthropic" else "google"
            )
        case LLMProvider.XAI | LLMProvider.XAI_OAUTH | LLMProvider.OPENROUTER:
            return "responses"
        case LLMProvider.KIMI_OAUTH:
            return "chat_completions"
        case LLMProvider.OPENAI | LLMProvider.CHATGPT_OAUTH:
            return "responses"
        case _ as unreachable:
            assert_never(unreachable)


def resolve_runtime_model_profile(
    *,
    provider: LLMProvider,
    model: str,
    profile_model: str | None,
    assembly_metadata: ModelAssemblyMetadata | None,
    context_window: int | None,
    context_window_explicit: bool,
    source_model: SourceModelRecord | None,
) -> RuntimeModelProfileResolution:
    """Resolve the effective runtime profile without credentials or provider I/O."""
    effective_model = profile_model if profile_model is not None else model
    protocol = protocol_for_provider(provider=provider, model=model)
    match provider:
        case LLMProvider.OPENAI | LLMProvider.CHATGPT_OAUTH:
            model_kind: RuntimeModelKind = "native_openai_responses"
            stock = OpenAIProvider.model_profile(effective_model)
            override: ModelProfile = {}
            model_type: type[Model] = OpenAIResponsesModel
        case (
            LLMProvider.XAI
            | LLMProvider.XAI_OAUTH
            | LLMProvider.OPENROUTER
            | LLMProvider.KIMI_OAUTH
        ):
            model_kind = (
                "openai_chat"
                if provider is LLMProvider.KIMI_OAUTH
                else "openai_responses"
            )
            stock = OpenAIProvider.model_profile(effective_model)
            override = OpenAIModelProfile(
                supports_tools=True,
                supports_json_schema_output=True,
                supports_json_object_output=True,
                supports_thinking=True,
                supported_native_tools=frozenset({WebSearchTool}),
                openai_system_prompt_role="system",
                openai_supports_strict_tool_definition=False,
                openai_supports_encrypted_reasoning_content=True,
                tool_addition_mode=None,
                tool_deferral_mode=None,
            )
            model_type = (
                OpenAIChatModel
                if provider is LLMProvider.KIMI_OAUTH
                else OpenAIResponsesModel
            )
        case LLMProvider.ANTHROPIC:
            model_kind = "anthropic"
            stock = AnthropicProvider.model_profile(effective_model)
            override = _anthropic_override()
            model_type = AnthropicModel
        case LLMProvider.GOOGLE_VERTEX_AI if protocol == "anthropic":
            model_kind = "anthropic"
            stock = AnthropicProvider.model_profile(effective_model)
            override = _anthropic_override()
            model_type = AnthropicModel
        case LLMProvider.GOOGLE_GEMINI | LLMProvider.GOOGLE_VERTEX_AI:
            model_kind = "google"
            stock = GoogleProvider.model_profile(effective_model)
            override = GoogleModelProfile(
                supports_tools=True,
                supports_json_schema_output=True,
                supports_thinking=True,
                supported_native_tools=frozenset({WebSearchTool, ImageGenerationTool}),
                tool_addition_mode=None,
                tool_deferral_mode=None,
            )
            model_type = GoogleModel
        case LLMProvider.AWS_BEDROCK:
            model_kind = "bedrock"
            stock = bedrock_assembly_profile(model)
            if stock is None:
                stock = saved_bedrock_assembly_profile(
                    model,
                    metadata=assembly_metadata,
                )
            override = BedrockModelProfile(
                supports_tools=True,
                supports_json_schema_output=True,
                supports_thinking=True,
                bedrock_supports_strict_tool_definition=False,
                tool_addition_mode=None,
                tool_deferral_mode=None,
            )
            model_type = BedrockConverseModel
        case _ as unreachable:
            assert_never(unreachable)

    profile = merge_profile(stock, override)
    if context_window_explicit:
        profile = merge_profile(
            profile,
            ModelProfile(context_window=context_window),
        )
    profile = _intersect_native_tools(profile, model_type=model_type)
    return RuntimeModelProfileResolution(
        protocol=protocol,
        model_kind=model_kind,
        profile=profile,
        normalized_capabilities=_normalized_capabilities(
            provider=provider,
            model=_capability_model_identifier(effective_model),
            protocol=protocol,
            profile=profile,
            context_window=context_window if context_window_explicit else None,
            source_model=source_model,
        ),
        resolver_revision=RUNTIME_MODEL_PROFILE_RESOLVER_REVISION,
    )


def _anthropic_override() -> AnthropicModelProfile:
    return AnthropicModelProfile(
        supports_tools=True,
        supports_json_schema_output=True,
        supports_thinking=True,
        supported_native_tools=frozenset({WebSearchTool}),
        anthropic_binds_thinking_blocks=False,
        tool_addition_mode=None,
        tool_deferral_mode=None,
    )


def _intersect_native_tools(
    profile: ModelProfile,
    *,
    model_type: type[Model],
) -> ModelProfile:
    profile_tools = profile.get("supported_native_tools")
    if profile_tools is None:
        profile_tools = model_type.supported_native_tools()
    effective = profile_tools & model_type.supported_native_tools()
    return merge_profile(profile, ModelProfile(supported_native_tools=effective))


def _normalized_capabilities(
    *,
    provider: LLMProvider,
    model: str,
    protocol: NativeModelProtocol,
    profile: ModelProfile,
    context_window: int | None,
    source_model: SourceModelRecord | None,
) -> ModelCapabilities:
    values: Mapping[str, object] = profile
    supports_thinking = values.get("supports_thinking") is True
    tool_calling_supported = _supports_tool_calling(
        provider=provider,
        model=model,
        profile=profile,
    )
    return ModelCapabilities(
        context_window=ModelContextWindow(max_input_tokens=context_window),
        modalities=ModelModalities(
            input=_input_modalities(
                provider=provider,
                model=model,
                protocol=protocol,
            ),
            output=[ModelModality.TEXT],
        ),
        tool_calling=ModelToolCallingCapabilities(
            supported=tool_calling_supported,
            strict_json_schema=values.get("supports_json_schema_output") is True,
        ),
        reasoning=ModelReasoningCapabilities(
            supported=supports_thinking,
            effort_levels=_reasoning_efforts(
                provider=provider,
                protocol=protocol,
                profile=profile,
            ),
        ),
        built_in_tools=ModelBuiltInToolCapabilities(
            supported=_built_in_tools(
                provider=provider,
                model=model,
                protocol=protocol,
                profile=profile,
                source_model=source_model,
                tool_calling_supported=tool_calling_supported,
            )
        ),
        parameters=_parameter_capabilities(
            provider=provider,
            protocol=protocol,
            profile=profile,
        ),
        compatibility=ModelCompatibilityCapabilities(
            provider_family=_provider_family(provider),
            responses_api=protocol == "responses",
        ),
    )


def _supports_tool_calling(
    *,
    provider: LLMProvider,
    model: str,
    profile: ModelProfile,
) -> bool:
    if provider in {LLMProvider.OPENAI, LLMProvider.CHATGPT_OAUTH}:
        identifier = model.lower()
        return not identifier.startswith(("o1-mini", "o1-preview"))
    return profile.get("supports_tools") is not False


def _reasoning_efforts(
    *,
    provider: LLMProvider,
    protocol: NativeModelProtocol,
    profile: ModelProfile,
) -> list[ModelReasoningEffort]:
    if profile.get("supports_thinking") is not True:
        return []
    if provider in {LLMProvider.OPENAI, LLMProvider.CHATGPT_OAUTH}:
        efforts: list[ModelReasoningEffort] = []
        if profile.get("openai_supports_reasoning_effort_none") is True:
            efforts.append(ModelReasoningEffort.NONE)
        if profile.get("openai_supports_minimal_reasoning_effort") is True:
            efforts.append(ModelReasoningEffort.MINIMAL)
        efforts.extend(
            (
                ModelReasoningEffort.LOW,
                ModelReasoningEffort.MEDIUM,
                ModelReasoningEffort.HIGH,
            )
        )
        return efforts
    if protocol == "anthropic":
        if profile.get("anthropic_supports_effort") is not True:
            return []
        efforts = [
            ModelReasoningEffort.LOW,
            ModelReasoningEffort.MEDIUM,
            ModelReasoningEffort.HIGH,
        ]
        if profile.get("anthropic_supports_xhigh_effort") is True:
            efforts.append(ModelReasoningEffort.XHIGH)
        return efforts
    if protocol == "google":
        return [
            ModelReasoningEffort.NONE,
            ModelReasoningEffort.MINIMAL,
            ModelReasoningEffort.LOW,
            ModelReasoningEffort.MEDIUM,
            ModelReasoningEffort.HIGH,
        ]
    return [
        ModelReasoningEffort.LOW,
        ModelReasoningEffort.MEDIUM,
        ModelReasoningEffort.HIGH,
    ]


def _input_modalities(
    *,
    provider: LLMProvider,
    model: str,
    protocol: NativeModelProtocol,
) -> list[ModelModality]:
    modalities = [ModelModality.TEXT]
    identifier = model.lower()
    if provider in {LLMProvider.OPENAI, LLMProvider.CHATGPT_OAUTH}:
        if identifier.startswith(("gpt-4o", "gpt-4.1", "gpt-5", "gpt-6", "o3", "o4")):
            modalities.extend((ModelModality.IMAGE, ModelModality.PDF))
    elif protocol == "anthropic" and identifier.startswith("claude-"):
        modalities.extend((ModelModality.IMAGE, ModelModality.PDF))
    elif protocol == "google" and identifier.startswith("gemini-"):
        modalities.extend((ModelModality.IMAGE, ModelModality.PDF))
    return modalities


def _built_in_tools(
    *,
    provider: LLMProvider,
    model: str,
    protocol: NativeModelProtocol,
    profile: ModelProfile,
    source_model: SourceModelRecord | None,
    tool_calling_supported: bool,
) -> list[str]:
    native_tools = profile.get("supported_native_tools") or frozenset()
    source_web_search = source_model is not None and any(
        "web_searches_kcount" in price_set.prices for price_set in source_model.prices
    )
    metadata: dict[str, object] = {
        "mode": "chat",
        "supports_function_calling": tool_calling_supported,
        "supports_web_search": (
            WebSearchTool in native_tools
            and (source_web_search or protocol == "google")
        ),
        "supports_image_generation": (
            protocol == "google" and ImageGenerationTool in native_tools
        ),
    }
    return supported_builtin_capabilities(
        provider=provider,
        model_identifier=model,
        metadata=metadata,
    )


def _parameter_capabilities(
    *,
    provider: LLMProvider,
    protocol: NativeModelProtocol,
    profile: ModelProfile,
) -> ModelParameterCapabilities:
    reasoning = profile.get("supports_thinking") is True
    sampling = not reasoning
    if protocol == "anthropic":
        sampling = profile.get("anthropic_disallows_sampling_settings") is not True
    if protocol == "google":
        sampling = True
    return ModelParameterCapabilities(
        temperature=sampling,
        max_output_tokens=True,
        top_p=sampling,
        top_k=provider
        in {
            LLMProvider.ANTHROPIC,
            LLMProvider.GOOGLE_GEMINI,
            LLMProvider.GOOGLE_VERTEX_AI,
            LLMProvider.AWS_BEDROCK,
        },
        stop_sequences=True,
    )


def _capability_model_identifier(profile_model: str) -> str:
    """Return the provider model ID used by capability family policy."""
    parts = profile_model.split("/")
    if "publishers" not in parts:
        return profile_model
    index = parts.index("publishers")
    if len(parts) <= index + 3 or parts[index + 2] != "models":
        raise ValueError("The Vertex publisher resource is malformed.")
    return "/".join(parts[index + 3 :])


def _provider_family(provider: LLMProvider) -> str:
    match provider:
        case LLMProvider.OPENAI | LLMProvider.CHATGPT_OAUTH:
            return "openai"
        case LLMProvider.ANTHROPIC:
            return "anthropic"
        case LLMProvider.GOOGLE_GEMINI:
            return "google"
        case LLMProvider.GOOGLE_VERTEX_AI:
            return "vertex"
        case LLMProvider.AWS_BEDROCK:
            return "bedrock"
        case LLMProvider.XAI | LLMProvider.XAI_OAUTH:
            return "xai"
        case LLMProvider.KIMI_OAUTH:
            return "moonshot"
        case LLMProvider.OPENROUTER:
            return "openrouter"
        case _ as unreachable:
            assert_never(unreachable)
