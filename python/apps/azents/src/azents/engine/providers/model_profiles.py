"""Operation-local provider encoding profiles, separate from model facts."""

from __future__ import annotations

import dataclasses
import re
from typing import Literal, assert_never

from pydantic_ai.models import Model
from pydantic_ai.models.anthropic import AnthropicModel
from pydantic_ai.models.bedrock import BedrockConverseModel
from pydantic_ai.models.google import GoogleModel
from pydantic_ai.models.openai import OpenAIChatModel, OpenAIResponsesModel
from pydantic_ai.native_tools import (
    AbstractNativeTool,
    ImageGenerationTool,
    WebSearchTool,
)
from pydantic_ai.profiles import ModelProfile, merge_profile
from pydantic_ai.profiles.anthropic import AnthropicModelProfile
from pydantic_ai.profiles.google import GoogleModelProfile
from pydantic_ai.profiles.openai import OpenAIModelProfile
from pydantic_ai.providers.anthropic import AnthropicProvider
from pydantic_ai.providers.bedrock import BedrockModelProfile, BedrockProvider
from pydantic_ai.providers.google import GoogleProvider
from pydantic_ai.providers.openai import OpenAIProvider

from azents.core.enums import LLMModelDeveloper, LLMProvider
from azents.core.llm_catalog import ModelCapabilities, ModelReasoningEffort
from azents.core.model_capability_contract import ModelCapabilityFeature
from azents.core.model_catalog_source import CatalogSourceModel
from azents.core.model_provider_protocol import vertex_model_family
from azents.engine.events.pydantic_ai_types import NativeModelProtocol
from azents.engine.model_assembly import ModelAssemblyMetadata

RUNTIME_MODEL_PROFILE_RESOLVER_REVISION = "5"

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
    """One wire profile and an independently justified saved capability view."""

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
    """Look up public Bedrock wire traits without granting model capabilities."""
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
    model: str, *, metadata: ModelAssemblyMetadata | None
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


def protocol_for_provider(*, provider: LLMProvider, model: str) -> NativeModelProtocol:
    """Resolve the existing request protocol without credentials or source lookup."""
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
    source_model: CatalogSourceModel | None,
) -> RuntimeModelProfileResolution:
    """Resolve encoding details while saved semantics remain the model authority."""
    protocol = protocol_for_provider(provider=provider, model=model)
    capabilities = (
        assembly_metadata.capabilities
        if assembly_metadata is not None
        else ModelCapabilities()
    )
    if provider in {LLMProvider.OPENAI, LLMProvider.CHATGPT_OAUTH}:
        return RuntimeModelProfileResolution(
            protocol=protocol,
            model_kind="native_openai_responses",
            profile={},
            normalized_capabilities=capabilities,
            resolver_revision=RUNTIME_MODEL_PROFILE_RESOLVER_REVISION,
        )

    effective_model = profile_model if profile_model is not None else model
    match provider:
        case (
            LLMProvider.XAI
            | LLMProvider.XAI_OAUTH
            | LLMProvider.OPENROUTER
            | LLMProvider.KIMI_OAUTH
        ):
            model_kind: RuntimeModelKind = (
                "openai_chat"
                if provider is LLMProvider.KIMI_OAUTH
                else "openai_responses"
            )
            stock = OpenAIProvider.model_profile(effective_model)
            override: ModelProfile = OpenAIModelProfile(
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
            model_type: type[Model] = (
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
                    model, metadata=assembly_metadata
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
    profile = _preserve_sampling_codec(profile, protocol=protocol)
    profile = _apply_saved_support(
        profile, protocol=protocol, capabilities=capabilities
    )
    if context_window_explicit:
        profile = merge_profile(profile, ModelProfile(context_window=context_window))
    profile_tools = profile.get("supported_native_tools")
    if profile_tools is None:
        profile_tools = model_type.supported_native_tools()
    profile = merge_profile(
        profile,
        ModelProfile(
            supported_native_tools=profile_tools & model_type.supported_native_tools()
        ),
    )
    return RuntimeModelProfileResolution(
        protocol=protocol,
        model_kind=model_kind,
        profile=profile,
        normalized_capabilities=capabilities,
        resolver_revision=RUNTIME_MODEL_PROFILE_RESOLVER_REVISION,
    )


def _anthropic_override() -> AnthropicModelProfile:
    """Retain existing Anthropic protocol formatting for historical requests."""
    return AnthropicModelProfile(
        supports_tools=True,
        supports_json_schema_output=True,
        supports_thinking=True,
        supported_native_tools=frozenset({WebSearchTool}),
        anthropic_binds_thinking_blocks=False,
        tool_addition_mode=None,
        tool_deferral_mode=None,
    )


def _preserve_sampling_codec(
    profile: ModelProfile, *, protocol: NativeModelProtocol
) -> ModelProfile:
    """Keep accepted controls for saved and historical requests on the wire."""
    if protocol == "anthropic":
        return merge_profile(
            profile, AnthropicModelProfile(anthropic_disallows_sampling_settings=False)
        )
    if protocol == "bedrock":
        return merge_profile(
            profile,
            AnthropicModelProfile(anthropic_disallows_sampling_settings=False),
            BedrockModelProfile(bedrock_disallows_sampling_settings=False),
        )
    return profile


def _apply_saved_support(
    profile: ModelProfile,
    *,
    protocol: NativeModelProtocol,
    capabilities: ModelCapabilities,
) -> ModelProfile:
    """Configure a codec from saved features; validation owns conditions."""
    reasoning = capabilities.supports(ModelCapabilityFeature.REASONING)
    efforts = set(capabilities.reasoning.effort_levels)
    strict = capabilities.supports(ModelCapabilityFeature.STRICT_FUNCTION_SCHEMA)
    structured = capabilities.supports(ModelCapabilityFeature.STRUCTURED_RESPONSE)
    native_tools: set[type[AbstractNativeTool]] = set()
    if capabilities.supports(ModelCapabilityFeature.WEB_SEARCH):
        native_tools.add(WebSearchTool)
    if protocol == "google" and capabilities.supports(
        ModelCapabilityFeature.IMAGE_GENERATION
    ):
        native_tools.add(ImageGenerationTool)
    profile = merge_profile(
        profile,
        ModelProfile(
            supports_tools=capabilities.supports(
                ModelCapabilityFeature.FUNCTION_CALLING
            ),
            supports_thinking=reasoning,
            supports_json_schema_output=structured
            or (protocol == "anthropic" and strict),
            supports_image_output=protocol == "google"
            and capabilities.supports(ModelCapabilityFeature.OUTPUT_IMAGE),
            supported_native_tools=frozenset(native_tools),
        ),
    )
    match protocol:
        case "responses" | "chat_completions":
            return merge_profile(
                profile,
                OpenAIModelProfile(
                    openai_supports_reasoning=reasoning,
                    openai_supports_reasoning_effort_none=ModelReasoningEffort.NONE
                    in efforts,
                    openai_supports_minimal_reasoning_effort=ModelReasoningEffort.MINIMAL
                    in efforts,
                    # The SDK shares this encoding switch with native response schemas.
                    # Function admission remains an independent final request feature.
                    openai_supports_strict_tool_definition=strict or structured,
                    openai_responses_supports_json_schema_output=structured,
                ),
            )
        case "anthropic":
            return merge_profile(
                profile,
                AnthropicModelProfile(
                    anthropic_supports_effort=bool(efforts),
                    anthropic_supports_xhigh_effort=ModelReasoningEffort.XHIGH
                    in efforts,
                ),
            )
        case "google":
            return merge_profile(
                profile,
                GoogleModelProfile(google_supports_strict_tool_definition=strict),
            )
        case "bedrock":
            return merge_profile(
                profile,
                BedrockModelProfile(bedrock_supports_strict_tool_definition=strict),
            )
        case _ as unreachable:
            assert_never(unreachable)
