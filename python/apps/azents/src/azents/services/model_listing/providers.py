"""Provider-visible model listing adapters for user catalogs."""

from __future__ import annotations

import asyncio
import json
from collections.abc import Callable, Sequence
from contextlib import AbstractAsyncContextManager
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Annotated, ClassVar, Protocol

import boto3
import google.auth.transport.requests
import httpx
from botocore.exceptions import (
    BotoCoreError,
    ClientError,
    HTTPClientError,
    NoCredentialsError,
    PartialCredentialsError,
)
from botocore.exceptions import (
    ConnectionError as BotoConnectionError,
)
from google.auth.exceptions import (
    GoogleAuthError,
)
from google.auth.exceptions import (
    TransportError as GoogleTransportError,
)
from google.oauth2 import service_account
from openai import APIStatusError, AsyncOpenAI, OpenAIError
from pydantic import (
    BaseModel,
    BeforeValidator,
    ConfigDict,
    Field,
    TypeAdapter,
    ValidationError,
    field_validator,
    model_validator,
)

from azents.core.builtin_tools import supported_builtin_capabilities
from azents.core.chatgpt_oauth import (
    CHATGPT_MODEL_CATALOG_CLIENT_VERSION,
    CHATGPT_OAUTH_BACKEND_BASE_URL,
    build_chatgpt_oauth_headers,
)
from azents.core.credentials import (
    ApiKeySecrets,
    AwsConfig,
    AwsSecrets,
    ChatGPTOAuthConfig,
    ChatGPTOAuthSecrets,
    GcpConfig,
    GcpSecrets,
    KimiOAuthConfig,
    KimiOAuthSecrets,
    XaiOAuthConfig,
    XaiOAuthSecrets,
)
from azents.core.enums import LLMModelDeveloper, LLMProvider
from azents.core.kimi_oauth import (
    build_kimi_compatibility_headers,
    resolve_kimi_code_api_base_url,
)
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
from azents.core.model_capability_evidence import ProviderCapabilityEvidence
from azents.core.model_catalog_source import CatalogFact
from azents.core.model_execution_options import (
    ModelExecutionOptionId,
    validate_supported_execution_options,
)
from azents.core.openai_client_config import openai_responses_client_config
from azents.core.openrouter import OPENROUTER_API_BASE_URL
from azents.core.xai import resolve_xai_api_base_url
from azents.core.xai_oauth import (
    XAI_MODELS_CLIENT_VERSION,
    resolve_xai_usage_base_url,
)
from azents.repos.llm_provider_integration.data import (
    LLMProviderIntegrationWithSecrets,
)

from .data import (
    ImageGenerationModelListingOutput,
    ModelListingOutput,
    ModelListingSkipSummary,
    ModelListingSummary,
    NormalizedModelCandidate,
)

VERTEX_PUBLISHERS: dict[str, LLMModelDeveloper] = {
    "google": LLMModelDeveloper.GOOGLE,
    "anthropic": LLMModelDeveloper.ANTHROPIC,
}
OPENROUTER_PUBLISHERS: dict[str, LLMModelDeveloper] = {
    "openai": LLMModelDeveloper.OPENAI,
    "anthropic": LLMModelDeveloper.ANTHROPIC,
    "google": LLMModelDeveloper.GOOGLE,
    "x-ai": LLMModelDeveloper.XAI,
    "meta-llama": LLMModelDeveloper.META,
    "mistralai": LLMModelDeveloper.MISTRAL,
}

_OPENAI_FAST_MODEL_IDS = frozenset(
    {
        "gpt-6-astra",
        "gpt-5.6-sol",
        "gpt-5.6-terra",
        "gpt-5.6-luna",
        "gpt-5.5",
        "gpt-5.4",
        "gpt-5.4-mini",
        "gpt-5.2",
        "gpt-5.1",
        "gpt-5",
        "gpt-5-mini",
        "gpt-4.1",
        "gpt-4.1-mini",
        "gpt-4.1-nano",
        "gpt-4o",
        "gpt-4o-2024-05-13",
        "gpt-4o-mini",
        "o3",
        "o4-mini",
        "gpt-5.3-codex",
    }
)

_OPENAI_ULTRAFAST_MODEL_IDS = frozenset({"gpt-6-astra", "gpt-5.6-sol"})


def _openai_supported_execution_options(
    model_id: str,
) -> list[ModelExecutionOptionId]:
    """Return options for an exact reviewed OpenAI model identifier."""
    supported: list[ModelExecutionOptionId] = []
    if model_id in _OPENAI_FAST_MODEL_IDS:
        supported.append(ModelExecutionOptionId.FAST)
    if model_id in _OPENAI_ULTRAFAST_MODEL_IDS:
        supported.append(ModelExecutionOptionId.ULTRAFAST)
    return validate_supported_execution_options(
        provider=LLMProvider.OPENAI,
        supported=supported,
    )


def _chatgpt_supported_execution_options(
    model: _ChatGPTModelPayload,
) -> list[ModelExecutionOptionId]:
    """Return options from authoritative ChatGPT service-tier metadata only."""
    tiers = set(model.service_tiers or [])
    supported: list[ModelExecutionOptionId] = []
    if {"priority", "fast"} & tiers:
        supported.append(ModelExecutionOptionId.FAST)
    if "ultrafast" in tiers:
        supported.append(ModelExecutionOptionId.ULTRAFAST)
    return validate_supported_execution_options(
        provider=LLMProvider.CHATGPT_OAUTH,
        supported=supported,
    )


class _XaiOAuthReasoningEffortPayload(BaseModel):
    """Validated xAI OAuth reasoning-effort metadata."""

    model_config = ConfigDict(extra="allow", strict=True)

    id: str | None = None
    value: str | None = None
    default: bool | None = None


class _XaiOAuthModelPayload(BaseModel):
    """Validated xAI OAuth model-list entry."""

    model_config = ConfigDict(extra="allow", strict=True)

    id: str
    model: str | None = None
    name: str | None = None
    context_window: int | None = None
    api_backend: str | None = None
    supports_reasoning_effort: bool | None = None
    reasoning_efforts: list[_XaiOAuthReasoningEffortPayload] | None = None
    supports_backend_search: bool | None = None
    auto_compact_threshold_percent: int | None = None
    compaction_at_tokens: bool | None = None
    show_model_fingerprint: bool | None = None


class _XaiOAuthModelsPayload(BaseModel):
    """Validated xAI OAuth model-list response."""

    model_config = ConfigDict(extra="allow", strict=True)

    data: list[_XaiOAuthModelPayload]


class _ListingEvidencePayload(BaseModel):
    """Decode consumed fields while retaining opaque provider extensions."""

    model_config = ConfigDict(extra="allow", strict=True)


class _ChatGPTReasoningLevel(_ListingEvidencePayload):
    effort: str


class _ChatGPTEvidencePayload(_ListingEvidencePayload):
    context_window: int | None = None
    max_context_window: int | None = None
    input_modalities: list[str] | None = None
    supported_reasoning_levels: list[_ChatGPTReasoningLevel] | None = None
    default_reasoning_level: str | None = None
    supports_parallel_tool_calls: bool | None = None
    supports_reasoning_summaries: bool | None = None
    experimental_supported_tools: list[str] | None = None


class _KimiEvidencePayload(_ListingEvidencePayload):
    context_length: int | None = None
    supports_reasoning: bool | None = None
    supports_image_in: bool | None = None
    supports_video_in: bool | None = None


class _BedrockEvidencePayload(_ListingEvidencePayload):
    inputModalities: list[str] | None = None
    outputModalities: list[str] | None = None


class _VertexEvidencePayload(_ListingEvidencePayload):
    inputTokenLimit: int | None = None
    outputTokenLimit: int | None = None


class _OpenRouterArchitectureEvidence(_ListingEvidencePayload):
    input_modalities: list[str] | None = None
    output_modalities: list[str] | None = None


class _OpenRouterTopProviderEvidence(_ListingEvidencePayload):
    max_completion_tokens: int | None = None


class _OpenRouterEvidencePayload(_ListingEvidencePayload):
    context_length: int | None = None
    architecture: _OpenRouterArchitectureEvidence | None = None
    top_provider: _OpenRouterTopProviderEvidence | None = None
    supported_parameters: list[str] | None = None


class _XaiApiCapabilitiesEvidence(_ListingEvidencePayload):
    reasoning: bool | None = None
    reasoning_effort: bool | list[str] | None = None
    default_reasoning_effort: str | None = None


class _XaiApiEvidencePayload(_ListingEvidencePayload):
    context_length: int | None = None
    capabilities: _XaiApiCapabilitiesEvidence | None = None


def _identity(value: object) -> str | None:
    """Preserve the listing's best-effort, non-coercing identity contract."""
    return value if isinstance(value, str) and value else None


_OptionalIdentity = Annotated[str | None, BeforeValidator(_identity)]


class _ModelMetadataPayload(_ListingEvidencePayload):
    """Retain opaque metadata at ingress, separate from consumed typed fields."""

    metadata_keys: ClassVar[frozenset[str] | None] = None
    normalization_fields: ClassVar[frozenset[str]]
    eligible: bool = Field(exclude=True)
    source_metadata: dict[str, object] = Field(exclude=True)

    @classmethod
    def accepts_entry(cls, value: dict[str, object]) -> bool:
        """Validate eligibility before capability fields, as the legacy decoder did."""
        raise NotImplementedError

    @model_validator(mode="before")
    @classmethod
    def retain_metadata(cls, value: object) -> object:
        if not isinstance(value, dict):
            return value
        metadata = {
            key: item
            for key, item in value.items()
            if isinstance(key, str)
            and (cls.metadata_keys is None or key in cls.metadata_keys)
        }
        eligible = cls.accepts_entry(value)
        fields = (
            value
            if eligible
            else {
                key: item
                for key, item in value.items()
                if key not in cls.normalization_fields
            }
        )
        return {**fields, "eligible": eligible, "source_metadata": metadata}


class _ChatGPTModelPayload(_ChatGPTEvidencePayload, _ModelMetadataPayload):
    """Account model fields and exact raw metadata used by catalog replay."""

    normalization_fields = frozenset(_ChatGPTEvidencePayload.model_fields)
    metadata_keys = frozenset(
        {
            "auto_compact_token_limit",
            "context_window",
            "default_reasoning_level",
            "effective_context_window_percent",
            "experimental_supported_tools",
            "input_modalities",
            "max_context_window",
            "minimal_client_version",
            "priority",
            "service_tiers",
            "supported_in_api",
            "supported_reasoning_levels",
            "supports_parallel_tool_calls",
            "supports_reasoning_summaries",
            "tool_mode",
            "visibility",
        }
    )
    slug: _OptionalIdentity = None
    display_name: _OptionalIdentity = None
    visibility: _OptionalIdentity = None
    supported_in_api: bool | None = None
    service_tiers: list[str] | None = None
    builtin_capabilities: list[str] = Field(exclude=True)

    @model_validator(mode="before")
    @classmethod
    def decode_builtin_capabilities(cls, value: object) -> object:
        """Project the shared policy once, including compatible extension fields."""
        if not isinstance(value, dict):
            return value
        slug = _identity(value.get("slug"))
        supported = (
            supported_builtin_capabilities(
                provider=LLMProvider.CHATGPT_OAUTH,
                model_identifier=slug,
                metadata=value,
            )
            if slug is not None and cls.accepts_entry(value)
            else []
        )
        return {**value, "builtin_capabilities": supported}

    @classmethod
    def accepts_entry(cls, value: dict[str, object]) -> bool:
        return (
            _identity(value.get("slug")) is not None
            and value.get("supported_in_api") is True
            and value.get("visibility") == "list"
        )

    @field_validator("supported_in_api", mode="before")
    @classmethod
    def exact_api_support(cls, value: object) -> bool | None:
        return value if isinstance(value, bool) else None

    @field_validator("service_tiers", mode="before")
    @classmethod
    def tier_ids(cls, value: object) -> list[str] | None:
        if not isinstance(value, list):
            return None
        identifiers: list[str] = []
        for tier in value:
            if isinstance(tier, str):
                identifiers.append(tier)
            elif isinstance(tier, dict):
                identifier = tier.get("id")
                if isinstance(identifier, str):
                    identifiers.append(identifier)
        return identifiers


class _KimiModelPayload(_KimiEvidencePayload, _ModelMetadataPayload):
    normalization_fields = frozenset(_KimiEvidencePayload.model_fields)
    metadata_keys = frozenset(
        {
            "context_length",
            "supports_reasoning",
            "supports_image_in",
            "supports_video_in",
        }
    )
    id: _OptionalIdentity = None
    display_name: _OptionalIdentity = None

    @classmethod
    def accepts_entry(cls, value: dict[str, object]) -> bool:
        return _identity(value.get("id")) is not None


class _BedrockLifecyclePayload(_ListingEvidencePayload):
    status: _OptionalIdentity = None


class _BedrockModelPayload(_BedrockEvidencePayload, _ModelMetadataPayload):
    normalization_fields = frozenset(_BedrockEvidencePayload.model_fields)
    modelId: _OptionalIdentity = None
    modelName: _OptionalIdentity = None
    providerName: _OptionalIdentity = None
    modelLifecycle: _BedrockLifecyclePayload | None = None

    @classmethod
    def accepts_entry(cls, value: dict[str, object]) -> bool:
        lifecycle = value.get("modelLifecycle")
        return (
            _identity(value.get("modelId")) is not None
            and _developer_from_bedrock_provider(_identity(value.get("providerName")))
            is not None
            and not (
                isinstance(lifecycle, dict) and lifecycle.get("status") == "LEGACY"
            )
        )

    @field_validator("modelLifecycle", mode="before")
    @classmethod
    def optional_lifecycle(cls, value: object) -> object:
        return value if isinstance(value, dict) else None


class _VertexModelPayload(_VertexEvidencePayload, _ModelMetadataPayload):
    normalization_fields = frozenset(_VertexEvidencePayload.model_fields)
    name: _OptionalIdentity = None
    modelId: _OptionalIdentity = None
    displayName: _OptionalIdentity = None

    @classmethod
    def accepts_entry(cls, value: dict[str, object]) -> bool:
        return (
            _identity(value.get("modelId")) is not None
            or _identity(value.get("name")) is not None
        )


class _OpenRouterModelPayload(_OpenRouterEvidencePayload, _ModelMetadataPayload):
    normalization_fields = frozenset(_OpenRouterEvidencePayload.model_fields)
    metadata_keys = frozenset(
        {
            "architecture",
            "canonical_slug",
            "context_length",
            "created",
            "expiration_date",
            "pricing",
            "reasoning",
            "supported_parameters",
            "top_provider",
        }
    )
    id: _OptionalIdentity = None
    name: _OptionalIdentity = None

    @classmethod
    def accepts_entry(cls, value: dict[str, object]) -> bool:
        if _identity(value.get("id")) is None:
            return False
        architecture = value.get("architecture")
        if not isinstance(architecture, dict):
            return True
        output = architecture.get("output_modalities")
        if output is None:
            return True
        return (
            isinstance(output, Sequence)
            and not isinstance(output, (str, bytes))
            and "text" in output
        )


class _ChatGPTModelsPayload(_ListingEvidencePayload):
    models: list[object]


class _AccountModelsPayload(_ListingEvidencePayload):
    data: list[object]


class _VertexModelsPayload(_ListingEvidencePayload):
    publisherModels: list[object] | None = None

    @model_validator(mode="before")
    @classmethod
    def optional_envelope(cls, value: object) -> object:
        return value if isinstance(value, dict) else {}

    @field_validator("publisherModels", mode="before")
    @classmethod
    def optional_models(cls, value: object) -> list[object] | None:
        return value if isinstance(value, list) else None


class _BedrockModelsPayload(_ListingEvidencePayload):
    modelSummaries: list[object] = Field(default_factory=list)


_BEDROCK_MODEL_SUMMARY_ADAPTER = TypeAdapter(_BedrockModelPayload)
_CHATGPT_MODEL_ADAPTER = TypeAdapter(_ChatGPTModelPayload)
_KIMI_MODEL_ADAPTER = TypeAdapter(_KimiModelPayload)
_OPENROUTER_MODEL_ADAPTER = TypeAdapter(_OpenRouterModelPayload)
_VERTEX_MODEL_ADAPTER = TypeAdapter(_VertexModelPayload)


@dataclass(frozen=True)
class ListingClientFactories:
    """Explicit composition-owned provider client and credential boundaries."""

    http: Callable[..., AbstractAsyncContextManager[httpx.AsyncClient]]
    openai: Callable[..., AbstractAsyncContextManager[AsyncOpenAI]]
    aws_session: Callable[..., boto3.Session]
    vertex_token: Callable[[GcpSecrets], str]


def create_listing_client_factories() -> ListingClientFactories:
    """Compose SDK/HTTP factories outside provider listing orchestration."""
    return ListingClientFactories(
        http=httpx.AsyncClient,
        openai=AsyncOpenAI,
        aws_session=boto3.Session,
        vertex_token=_vertex_access_token,
    )


def _listing_fact[T](payload: BaseModel, field: str, value: T | None) -> CatalogFact[T]:
    """Capture presence at ingress, before candidate serialization."""
    if field not in payload.model_fields_set:
        return CatalogFact(state="absent", value=None)
    if value is None:
        return CatalogFact(state="null", value=None)
    return CatalogFact(state="value", value=value)


def _nested_listing_fact[T](
    payload: BaseModel,
    field: str,
    nested: BaseModel | None,
    nested_field: str,
    value: T | None,
) -> CatalogFact[T]:
    """Preserve an explicitly unknown parent without fabricating child defaults."""
    if field not in payload.model_fields_set:
        return CatalogFact(state="absent", value=None)
    if nested is None:
        return CatalogFact(state="null", value=None)
    return _listing_fact(nested, nested_field, value)


def _modality_values(values: list[str] | None) -> tuple[str, ...] | None:
    """Normalize token spelling without discarding future modality declarations."""
    return tuple(value.lower() for value in values) if values is not None else None


def _effort_values(values: list[str] | None) -> tuple[ModelReasoningEffort, ...] | None:
    """Preserve canonical controls without adding levels for future provider values."""
    if values is None:
        return None
    canonical = {effort.value: effort for effort in ModelReasoningEffort}
    return tuple(canonical[value] for value in values if value in canonical)


def _canonical_effort(value: str | None) -> ModelReasoningEffort | None:
    """Keep unsupported provider defaults unknown rather than choosing another level."""
    return next(
        (effort for effort in ModelReasoningEffort if effort.value == value), None
    )


def _effort_diagnostics(values: list[str]) -> dict[str, object]:
    """Explain filtering of unsupported wire labels while retaining raw metadata."""
    unsupported = [value for value in values if _canonical_effort(value) is None]
    return (
        {
            "capability_evidence_diagnostics": {
                "unsupported_reasoning_effort_labels": unsupported,
            }
        }
        if unsupported
        else {}
    )


def _chatgpt_capability_evidence(
    payload: _ChatGPTModelPayload,
) -> ProviderCapabilityEvidence:
    """Keep account declarations independent of model-name and SDK profile rules."""
    levels = _effort_values(
        [level.effort for level in payload.supported_reasoning_levels]
        if payload.supported_reasoning_levels is not None
        else None
    )
    context = _listing_fact(payload, "context_window", payload.context_window)
    return ProviderCapabilityEvidence(
        default_input_tokens=context,
        max_input_tokens=(
            _listing_fact(payload, "max_context_window", payload.max_context_window)
            if "max_context_window" in payload.model_fields_set
            else context
        ),
        input_modalities=_listing_fact(
            payload, "input_modalities", _modality_values(payload.input_modalities)
        ),
        parallel_function_calling=_listing_fact(
            payload,
            "supports_parallel_tool_calls",
            payload.supports_parallel_tool_calls,
        ),
        reasoning=(
            CatalogFact(state="value", value=True)
            if levels
            else CatalogFact(state="absent", value=None)
        ),
        reasoning_efforts=_listing_fact(payload, "supported_reasoning_levels", levels),
        default_reasoning_effort=_listing_fact(
            payload,
            "default_reasoning_level",
            _canonical_effort(payload.default_reasoning_level),
        ),
        reasoning_summaries=_listing_fact(
            payload,
            "supports_reasoning_summaries",
            payload.supports_reasoning_summaries,
        ),
        client_image_generation=(
            CatalogFact(state="value", value=True)
            if payload.experimental_supported_tools is not None
            and "image_generation" in payload.experimental_supported_tools
            else CatalogFact(state="absent", value=None)
        ),
    )


def _kimi_capability_evidence(payload: _KimiModelPayload) -> ProviderCapabilityEvidence:
    """Record Kimi's independent flags; missing media/effort facts are not denials."""
    return ProviderCapabilityEvidence(
        max_input_tokens=_listing_fact(
            payload, "context_length", payload.context_length
        ),
        image_input=_listing_fact(
            payload, "supports_image_in", payload.supports_image_in
        ),
        video_input=_listing_fact(
            payload, "supports_video_in", payload.supports_video_in
        ),
        reasoning=_listing_fact(
            payload, "supports_reasoning", payload.supports_reasoning
        ),
    )


def _bedrock_capability_evidence(
    payload: _BedrockModelPayload,
) -> ProviderCapabilityEvidence:
    """Summary media is evidence; synthetic reasoning/function defaults are not."""
    return ProviderCapabilityEvidence(
        input_modalities=_listing_fact(
            payload, "inputModalities", _modality_values(payload.inputModalities)
        ),
        output_modalities=_listing_fact(
            payload, "outputModalities", _modality_values(payload.outputModalities)
        ),
    )


def _vertex_capability_evidence(
    payload: _VertexModelPayload,
) -> ProviderCapabilityEvidence:
    """Publisher token fields do not imply placeholder capability denials."""
    return ProviderCapabilityEvidence(
        max_input_tokens=_listing_fact(
            payload, "inputTokenLimit", payload.inputTokenLimit
        ),
        max_output_tokens=_listing_fact(
            payload, "outputTokenLimit", payload.outputTokenLimit
        ),
    )


def _openrouter_capability_evidence(
    payload: _OpenRouterModelPayload,
) -> ProviderCapabilityEvidence:
    """Use complete parameter declarations without inventing model effort levels."""
    parameters = payload.supported_parameters

    def parameter(*names: str) -> CatalogFact[bool]:
        return _listing_fact(
            payload,
            "supported_parameters",
            any(name in parameters for name in names)
            if parameters is not None
            else None,
        )

    architecture = payload.architecture
    top = payload.top_provider
    effort_parameter = parameter("reasoning", "reasoning_effort")
    return ProviderCapabilityEvidence(
        max_input_tokens=_listing_fact(
            payload, "context_length", payload.context_length
        ),
        max_output_tokens=_nested_listing_fact(
            payload,
            "top_provider",
            top,
            "max_completion_tokens",
            top.max_completion_tokens if top is not None else None,
        ),
        input_modalities=_nested_listing_fact(
            payload,
            "architecture",
            architecture,
            "input_modalities",
            _modality_values(architecture.input_modalities)
            if architecture is not None
            else None,
        ),
        output_modalities=_nested_listing_fact(
            payload,
            "architecture",
            architecture,
            "output_modalities",
            _modality_values(architecture.output_modalities)
            if architecture is not None
            else None,
        ),
        function_calling=parameter("tools"),
        parallel_function_calling=parameter("parallel_tool_calls"),
        structured_response=parameter("structured_outputs"),
        reasoning=parameter("reasoning", "reasoning_effort", "include_reasoning"),
        reasoning_efforts=(
            CatalogFact(state="value", value=())
            if effort_parameter.state == "value" and effort_parameter.value is False
            else CatalogFact(state="null", value=None)
            if effort_parameter.state == "null"
            else CatalogFact(state="absent", value=None)
        ),
        temperature=parameter("temperature"),
        top_p=parameter("top_p"),
        top_k=parameter("top_k"),
        stop_sequences=parameter("stop"),
        max_output_parameter=parameter("max_tokens", "max_completion_tokens"),
    )


def _xai_api_capability_evidence(
    extra: dict[str, object] | None,
) -> ProviderCapabilityEvidence:
    """Validate SDK model extensions without transferring opaque request hints."""
    payload = _XaiApiEvidencePayload.model_validate(extra if extra is not None else {})
    caps = payload.capabilities
    raw_efforts = caps.reasoning_effort if caps is not None else None
    effort_fact: CatalogFact[tuple[ModelReasoningEffort, ...]]
    if isinstance(raw_efforts, list):
        effort_fact = _nested_listing_fact(
            payload,
            "capabilities",
            caps,
            "reasoning_effort",
            _effort_values(raw_efforts),
        )
    elif raw_efforts is False:
        effort_fact = CatalogFact(state="value", value=())
    elif raw_efforts is True:
        effort_fact = CatalogFact(state="absent", value=None)
    else:
        effort_fact = _nested_listing_fact(
            payload, "capabilities", caps, "reasoning_effort", None
        )
    reasoning = _nested_listing_fact(
        payload,
        "capabilities",
        caps,
        "reasoning",
        caps.reasoning if caps is not None else None,
    )
    if reasoning.state == "absent" and (raw_efforts is True or bool(effort_fact.value)):
        reasoning = CatalogFact(state="value", value=True)
    return ProviderCapabilityEvidence(
        max_input_tokens=_listing_fact(
            payload, "context_length", payload.context_length
        ),
        reasoning=reasoning,
        reasoning_efforts=effort_fact,
        default_reasoning_effort=_nested_listing_fact(
            payload,
            "capabilities",
            caps,
            "default_reasoning_effort",
            _canonical_effort(caps.default_reasoning_effort)
            if caps is not None
            else None,
        ),
    )


def _xai_oauth_capability_evidence(
    payload: _XaiOAuthModelPayload,
) -> ProviderCapabilityEvidence:
    """Preserve proxy declarations without treating empty controls as no reasoning."""
    levels = None
    default = None
    if payload.reasoning_efforts is not None:
        values = []
        defaults = []
        for preset in payload.reasoning_efforts:
            value = preset.id if preset.id is not None else preset.value
            if value is None:
                raise ValueError("Provider reasoning preset must contain an effort.")
            effort = _canonical_effort(value)
            if effort is not None:
                values.append(effort)
            if preset.default is True:
                defaults.append(effort)
        levels = tuple(values)
        default = defaults[0] if len(defaults) == 1 else None
    control = _listing_fact(
        payload, "supports_reasoning_effort", payload.supports_reasoning_effort
    )
    effort_fact: CatalogFact[tuple[ModelReasoningEffort, ...]] = _listing_fact(
        payload, "reasoning_efforts", levels
    )
    if control.state == "value" and control.value is False:
        effort_fact = CatalogFact(state="value", value=())
        default = None
    elif effort_fact.state == "absent" and control.state == "null":
        effort_fact = CatalogFact(state="null", value=None)
    backend = _listing_fact(payload, "api_backend", payload.api_backend)
    return ProviderCapabilityEvidence(
        max_input_tokens=_listing_fact(
            payload, "context_window", payload.context_window
        ),
        reasoning=(
            CatalogFact(state="value", value=True)
            if payload.supports_reasoning_effort is True or bool(levels)
            else CatalogFact(state="absent", value=None)
        ),
        reasoning_efforts=effort_fact,
        default_reasoning_effort=(
            CatalogFact(state="value", value=default)
            if default is not None
            else CatalogFact(state="null", value=None)
            if payload.reasoning_efforts is not None
            and any(preset.default is True for preset in payload.reasoning_efforts)
            else CatalogFact(state="absent", value=None)
        ),
        web_search=_listing_fact(
            payload, "supports_backend_search", payload.supports_backend_search
        ),
        responses_api=(
            CatalogFact(state="value", value=backend.value == "responses")
            if backend.state == "value"
            else CatalogFact(state=backend.state, value=None)
        ),
    )


class ListingProviderError(Exception):
    """Provider listing adapter failure with automatic retry policy."""

    def __init__(self, message: str, *, automatic_retry_blocked: bool) -> None:
        super().__init__(message)
        self.automatic_retry_blocked = automatic_retry_blocked


class InvalidProviderResponseError(ValueError):
    """Provider returned a response that cannot be projected."""


class _OpenAIModelItem(Protocol):
    """Minimal official SDK model item shape used by image discovery."""

    @property
    def id(self) -> str | None:
        """Return the exact provider model identifier."""


class _OpenAIModelPage(Protocol):
    """Minimal official SDK page shape used by image discovery."""

    @property
    def data(self) -> Sequence[_OpenAIModelItem]:
        """Return the current provider page items."""

    def has_next_page(self) -> bool:
        """Return whether one provider page remains."""

    async def get_next_page(self) -> "_OpenAIModelPage":
        """Fetch the next provider page."""


class XaiListingProviderError(ListingProviderError):
    """Sanitized xAI listing failure safe for persisted diagnostics."""

    def __init__(
        self,
        *,
        failure_code: str,
        automatic_retry_blocked: bool,
    ) -> None:
        super().__init__(
            "xAI model listing failed.",
            automatic_retry_blocked=automatic_retry_blocked,
        )
        self.failure_code = failure_code


async def list_bedrock_models_for_integration(
    integration: LLMProviderIntegrationWithSecrets,
    *,
    clients: ListingClientFactories,
) -> ModelListingOutput:
    """Fetch provider listing of AWS Bedrock integration."""
    try:
        return await _list_bedrock_models(integration, clients=clients)
    except (BotoCoreError, ClientError, ValueError) as exc:
        raise ListingProviderError(
            "AWS Bedrock model listing failed.",
            automatic_retry_blocked=automatic_retry_blocked_for_listing_error(exc),
        ) from exc


async def list_vertex_models_for_integration(
    integration: LLMProviderIntegrationWithSecrets,
    *,
    clients: ListingClientFactories,
) -> ModelListingOutput:
    """Fetch provider listing of Google Vertex AI integration."""
    try:
        return await _list_vertex_models(integration, clients=clients)
    except (GoogleAuthError, httpx.HTTPError, json.JSONDecodeError, ValueError) as exc:
        raise ListingProviderError(
            "Google Vertex AI model listing failed.",
            automatic_retry_blocked=automatic_retry_blocked_for_listing_error(exc),
        ) from exc


async def list_chatgpt_models_for_integration(
    integration: LLMProviderIntegrationWithSecrets,
    *,
    clients: ListingClientFactories,
) -> ModelListingOutput:
    """Fetch account-visible models from the ChatGPT Codex backend."""
    try:
        return await _list_chatgpt_models(integration, clients=clients)
    except (httpx.HTTPError, json.JSONDecodeError, ValueError) as exc:
        raise ListingProviderError(
            "ChatGPT model listing failed.",
            automatic_retry_blocked=automatic_retry_blocked_for_listing_error(exc),
        ) from exc


async def list_kimi_models_for_integration(
    integration: LLMProviderIntegrationWithSecrets,
    *,
    clients: ListingClientFactories,
) -> ModelListingOutput:
    """Fetch account-visible models from the Kimi Code API."""
    try:
        return await _list_kimi_models(integration, clients=clients)
    except (httpx.HTTPError, json.JSONDecodeError, ValueError) as exc:
        raise ListingProviderError(
            "Kimi model listing failed.",
            automatic_retry_blocked=automatic_retry_blocked_for_listing_error(exc),
        ) from exc


async def list_openrouter_models_for_integration(
    integration: LLMProviderIntegrationWithSecrets,
    *,
    clients: ListingClientFactories,
) -> ModelListingOutput:
    """Fetch account-visible text-output models from OpenRouter."""
    try:
        return await _list_openrouter_models(integration, clients=clients)
    except (httpx.HTTPError, json.JSONDecodeError, ValueError) as exc:
        raise ListingProviderError(
            "OpenRouter model listing failed.",
            automatic_retry_blocked=automatic_retry_blocked_for_listing_error(exc),
        ) from exc


async def list_xai_models_for_integration(
    integration: LLMProviderIntegrationWithSecrets,
    *,
    clients: ListingClientFactories,
) -> ModelListingOutput:
    """Fetch credential-visible models from the matching xAI product."""
    try:
        if integration.provider == LLMProvider.XAI:
            return await _list_xai_api_key_models(integration, clients=clients)
        if integration.provider == LLMProvider.XAI_OAUTH:
            return await _list_xai_oauth_models(integration, clients=clients)
        raise ValueError("xAI integration provider is required.")
    except (
        OpenAIError,
        httpx.HTTPError,
        json.JSONDecodeError,
        UnicodeDecodeError,
        ValidationError,
        ValueError,
    ) as exc:
        raise _xai_listing_provider_error(exc) from None


async def list_openai_image_generation_models_for_integration(
    integration: LLMProviderIntegrationWithSecrets,
    *,
    clients: ListingClientFactories,
) -> ImageGenerationModelListingOutput:
    """List every exact model identifier visible to an OpenAI API-key integration."""
    try:
        return await _list_openai_image_generation_models(integration, clients=clients)
    except (OpenAIError, ValueError) as exc:
        raise ListingProviderError(
            "OpenAI image model listing failed.",
            automatic_retry_blocked=automatic_retry_blocked_for_listing_error(exc),
        ) from exc


def automatic_retry_blocked_for_listing_error(exc: Exception) -> bool:
    """Return whether a provider failure requires user configuration changes."""
    if isinstance(exc, (NoCredentialsError, PartialCredentialsError)):
        return True
    if isinstance(exc, GoogleTransportError):
        return False
    if isinstance(exc, ClientError):
        response = exc.response
        error = response.get("Error", {})
        code = str(error.get("Code", ""))
        metadata = response.get("ResponseMetadata", {})
        status_code = metadata.get("HTTPStatusCode")
        return code not in {
            "InternalFailure",
            "InternalServerException",
            "RequestLimitExceeded",
            "ServiceUnavailable",
            "Throttling",
            "ThrottlingException",
            "TooManyRequestsException",
        } and not (isinstance(status_code, int) and status_code >= 500)
    if isinstance(exc, httpx.HTTPStatusError):
        status_code = exc.response.status_code
        return status_code not in {408, 409, 425, 429} and status_code < 500
    if isinstance(exc, APIStatusError):
        return exc.status_code not in {408, 409, 425, 429} and exc.status_code < 500
    if isinstance(exc, (BotoConnectionError, HTTPClientError)):
        return False
    if isinstance(
        exc,
        (
            httpx.TransportError,
            json.JSONDecodeError,
            UnicodeDecodeError,
            ValidationError,
            InvalidProviderResponseError,
        ),
    ):
        return False
    if isinstance(exc, (GoogleAuthError, BotoCoreError)):
        return True
    return isinstance(exc, ValueError)


def _xai_listing_provider_error(exc: Exception) -> XaiListingProviderError:
    """Convert one xAI SDK or HTTP failure to a credential-safe category."""
    status_code: int | None = None
    if isinstance(exc, httpx.HTTPStatusError):
        status_code = exc.response.status_code
    elif isinstance(exc, APIStatusError):
        status_code = exc.status_code

    if status_code == 401:
        failure_code = "XaiCredentialRejected"
    elif status_code == 403:
        failure_code = "XaiEntitlementDenied"
    elif status_code == 429:
        failure_code = "XaiRateLimited"
    elif status_code in {408, 409, 425} or (
        status_code is not None and status_code >= 500
    ):
        failure_code = "XaiProviderUnavailable"
    elif status_code is not None:
        failure_code = "XaiRequestRejected"
    elif isinstance(
        exc,
        (
            json.JSONDecodeError,
            UnicodeDecodeError,
            ValidationError,
            InvalidProviderResponseError,
        ),
    ):
        failure_code = "XaiInvalidProviderResponse"
    elif isinstance(exc, (httpx.TransportError, OpenAIError)):
        failure_code = "XaiTransportUnavailable"
    else:
        failure_code = "XaiInvalidConfiguration"
    return XaiListingProviderError(
        failure_code=failure_code,
        automatic_retry_blocked=automatic_retry_blocked_for_listing_error(exc),
    )


async def _list_bedrock_models(
    integration: LLMProviderIntegrationWithSecrets,
    *,
    clients: ListingClientFactories,
) -> ModelListingOutput:
    """Fetch candidates with AWS Bedrock ListFoundationModels API."""
    config = _require_aws_config(integration.config)
    secrets = _require_aws_secrets(integration.secrets)
    fetched_at = datetime.now(timezone.utc)
    summaries = await asyncio.to_thread(
        _list_bedrock_models_sync,
        config,
        secrets,
        integration.workspace_id,
        clients=clients,
    )
    models: list[NormalizedModelCandidate] = []
    skipped = 0
    for raw_summary in summaries:
        summary = _BEDROCK_MODEL_SUMMARY_ADAPTER.validate_python(raw_summary)
        candidate = _candidate_from_bedrock_summary(summary, fetched_at=fetched_at)
        if candidate is None:
            skipped += 1
            continue
        models.append(candidate)
    return _output(
        source="aws_bedrock:list_foundation_models",
        fetched_at=fetched_at,
        models=models,
        skips=_skip_summary("unsupported_bedrock_model", skipped),
    )


def _list_bedrock_models_sync(
    config: AwsConfig,
    secrets: AwsSecrets,
    workspace_id: str,
    *,
    clients: ListingClientFactories,
) -> list[object]:
    """Perform synchronous boto3 Bedrock call."""
    session = clients.aws_session(
        aws_access_key_id=config.access_key_id,
        aws_secret_access_key=secrets.secret_access_key,
        region_name=config.region,
    )
    if config.role_arn is not None:
        sts = session.client("sts", region_name=config.region)
        assumed = sts.assume_role(
            RoleArn=config.role_arn,
            RoleSessionName=f"azents-{workspace_id[:8]}",
        )
        credentials = assumed["Credentials"]
        session = clients.aws_session(
            aws_access_key_id=credentials["AccessKeyId"],
            aws_secret_access_key=credentials["SecretAccessKey"],
            aws_session_token=credentials["SessionToken"],
            region_name=config.region,
        )
    bedrock = session.client("bedrock", region_name=config.region)
    payload = _BedrockModelsPayload.model_validate(bedrock.list_foundation_models())
    return [summary for summary in payload.modelSummaries if isinstance(summary, dict)]


def _candidate_from_bedrock_summary(
    summary: _BedrockModelPayload,
    *,
    fetched_at: datetime,
) -> NormalizedModelCandidate | None:
    """Normalize Bedrock summary."""
    model_id = summary.modelId
    if model_id is None or not summary.eligible:
        return None
    lifecycle = summary.modelLifecycle
    if lifecycle is not None and lifecycle.status == "LEGACY":
        return None
    developer = _developer_from_bedrock_provider(summary.providerName)
    if developer is None:
        return None
    modalities = _modalities_from_bedrock(summary)
    return NormalizedModelCandidate(
        provider=LLMProvider.AWS_BEDROCK,
        model_identifier=model_id,
        model_display_name=summary.modelName or model_id,
        model_developer=developer,
        model_family=_bedrock_family(model_id),
        capability_evidence=_bedrock_capability_evidence(summary),
        normalized_capabilities=ModelCapabilities(
            modalities=modalities,
            tool_calling=ModelToolCallingCapabilities(supported=True),
            compatibility=ModelCompatibilityCapabilities(provider_family="bedrock"),
        ),
        supported_execution_options=[],
        model_snapshot={
            "source": "aws_bedrock:list_foundation_models",
            "provider": LLMProvider.AWS_BEDROCK.value,
            "model_identifier": model_id,
            "model_display_name": summary.modelName or model_id,
            "model_developer": developer.value,
        },
        source_metadata=summary.source_metadata,
        last_refreshed_at=fetched_at,
    )


async def _list_chatgpt_models(
    integration: LLMProviderIntegrationWithSecrets,
    *,
    clients: ListingClientFactories,
) -> ModelListingOutput:
    """Fetch candidates from the ChatGPT Codex models endpoint."""
    config = _require_chatgpt_config(integration.config)
    secrets = _require_chatgpt_secrets(integration.secrets)
    fetched_at = datetime.now(timezone.utc)
    headers = build_chatgpt_oauth_headers(account_id=config.account_id)
    headers["Authorization"] = f"Bearer {secrets.access_token}"
    async with clients.http(timeout=20.0) as client:
        response = await client.get(
            f"{CHATGPT_OAUTH_BACKEND_BASE_URL}/models",
            params={"client_version": CHATGPT_MODEL_CATALOG_CLIENT_VERSION},
            headers=headers,
        )
        response.raise_for_status()
        payload = _ChatGPTModelsPayload.model_validate(response.json())
    models: list[NormalizedModelCandidate] = []
    skipped = 0
    for raw_model in payload.models:
        model = _CHATGPT_MODEL_ADAPTER.validate_python(raw_model)
        candidate = _candidate_from_chatgpt_model(model, fetched_at=fetched_at)
        if candidate is None:
            skipped += 1
            continue
        models.append(candidate)
    return _output(
        source="chatgpt:codex_models",
        fetched_at=fetched_at,
        models=models,
        skips=_skip_summary("unsupported_chatgpt_model", skipped),
    )


def _candidate_from_chatgpt_model(
    model: _ChatGPTModelPayload,
    *,
    fetched_at: datetime,
) -> NormalizedModelCandidate | None:
    """Normalize ChatGPT Codex model metadata."""
    model_id = model.slug
    if model_id is None or not model.eligible:
        return None
    display_name = model.display_name or model_id
    reasoning_efforts = _chatgpt_reasoning_efforts(model.supported_reasoning_levels)
    input_modalities = _chatgpt_modalities(model)
    context_window = _chatgpt_context_window(model)
    capabilities = ModelCapabilities(
        context_window=context_window,
        modalities=ModelModalities(
            input=input_modalities,
            output=[ModelModality.TEXT],
        ),
        tool_calling=ModelToolCallingCapabilities(
            supported=True,
            parallel_tool_calls=model.supports_parallel_tool_calls,
        ),
        reasoning=ModelReasoningCapabilities(
            supported=bool(reasoning_efforts),
            effort_levels=reasoning_efforts,
            summaries=model.supports_reasoning_summaries,
        ),
        built_in_tools=ModelBuiltInToolCapabilities(
            supported=model.builtin_capabilities
        ),
        compatibility=ModelCompatibilityCapabilities(
            provider_family="chatgpt",
            responses_api=True,
        ),
    )
    return NormalizedModelCandidate(
        provider=LLMProvider.CHATGPT_OAUTH,
        model_identifier=model_id,
        model_display_name=display_name,
        model_developer=LLMModelDeveloper.OPENAI,
        model_family=_chatgpt_family(model_id),
        capability_evidence=_chatgpt_capability_evidence(model),
        normalized_capabilities=capabilities,
        supported_execution_options=_chatgpt_supported_execution_options(model),
        model_snapshot={
            "source": "chatgpt:codex_models",
            "provider": LLMProvider.CHATGPT_OAUTH.value,
            "model_identifier": model_id,
            "model_display_name": display_name,
            "model_developer": LLMModelDeveloper.OPENAI.value,
        },
        source_metadata=_chatgpt_source_metadata(model),
        last_refreshed_at=fetched_at,
    )


def _chatgpt_source_metadata(model: _ChatGPTModelPayload) -> dict[str, object]:
    """Keep catalog-relevant ChatGPT metadata without storing model instructions."""
    return {
        **model.source_metadata,
        **_effort_diagnostics(
            [preset.effort for preset in model.supported_reasoning_levels or []]
        ),
    }


async def _list_kimi_models(
    integration: LLMProviderIntegrationWithSecrets,
    *,
    clients: ListingClientFactories,
) -> ModelListingOutput:
    """Fetch candidates from the authenticated Kimi Code models endpoint."""
    _require_kimi_config(integration.config)
    secrets = _require_kimi_secrets(integration.secrets)
    fetched_at = datetime.now(timezone.utc)
    headers = {
        **build_kimi_compatibility_headers(device_id=secrets.device_id),
        "Authorization": f"Bearer {secrets.access_token}",
        "Accept": "application/json",
    }
    async with clients.http(timeout=20.0) as client:
        response = await client.get(
            f"{resolve_kimi_code_api_base_url()}/models",
            headers=headers,
        )
        response.raise_for_status()
        payload = _AccountModelsPayload.model_validate(response.json())
    models: list[NormalizedModelCandidate] = []
    skipped = 0
    for raw_model in payload.data:
        try:
            model = _KIMI_MODEL_ADAPTER.validate_python(raw_model)
        except ValidationError:
            if isinstance(raw_model, dict):
                raise
            skipped += 1
            continue
        candidate = _candidate_from_kimi_model(model, fetched_at=fetched_at)
        if candidate is None:
            skipped += 1
            continue
        models.append(candidate)
    return _output(
        source="kimi:code_models",
        fetched_at=fetched_at,
        models=models,
        skips=_skip_summary("invalid_kimi_model", skipped),
    )


def _candidate_from_kimi_model(
    model: _KimiModelPayload,
    *,
    fetched_at: datetime,
) -> NormalizedModelCandidate | None:
    """Normalize one Kimi Code model entry."""
    model_id = model.id
    if model_id is None or not model.eligible:
        return None
    display_name = model.display_name or model_id
    supports_reasoning = model.supports_reasoning is True
    input_modalities = [ModelModality.TEXT]
    if model.supports_image_in is True:
        input_modalities.append(ModelModality.IMAGE)
    if model.supports_video_in is True:
        input_modalities.append(ModelModality.VIDEO)
    capabilities = ModelCapabilities(
        context_window=ModelContextWindow(
            max_input_tokens=_positive_int(model.context_length)
        ),
        modalities=ModelModalities(
            input=input_modalities,
            output=[ModelModality.TEXT],
        ),
        tool_calling=ModelToolCallingCapabilities(supported=True),
        reasoning=ModelReasoningCapabilities(
            supported=supports_reasoning,
            effort_levels=[],
        ),
        compatibility=ModelCompatibilityCapabilities(
            provider_family="moonshot",
            responses_api=True,
        ),
    )
    return NormalizedModelCandidate(
        provider=LLMProvider.KIMI_OAUTH,
        model_identifier=model_id,
        model_display_name=display_name,
        model_developer=LLMModelDeveloper.MOONSHOT,
        model_family=_kimi_family(model_id),
        capability_evidence=_kimi_capability_evidence(model),
        normalized_capabilities=capabilities,
        supported_execution_options=[],
        model_snapshot={
            "source": "kimi:code_models",
            "provider": LLMProvider.KIMI_OAUTH.value,
            "model_identifier": model_id,
            "model_display_name": display_name,
            "model_developer": LLMModelDeveloper.MOONSHOT.value,
        },
        source_metadata=model.source_metadata,
        last_refreshed_at=fetched_at,
    )


def _kimi_family(model_id: str) -> str:
    """Extract the stable Kimi model family prefix."""
    parts = model_id.split("-")
    if len(parts) >= 2 and parts[0].lower() == "kimi":
        return "-".join(parts[:2])
    return parts[0]


async def _list_xai_api_key_models(
    integration: LLMProviderIntegrationWithSecrets,
    *,
    clients: ListingClientFactories,
) -> ModelListingOutput:
    """Fetch xAI developer models through the OpenAI-compatible SDK."""
    secrets = _require_api_key_secrets(integration.secrets)
    fetched_at = datetime.now(timezone.utc)
    async with clients.openai(
        api_key=secrets.api_key,
        base_url=resolve_xai_api_base_url(),
        timeout=20.0,
    ) as client:
        page = await client.models.list()
    models = [
        _candidate_from_xai_api_key_model(
            model_id=model.id,
            created=model.created,
            extra=model.model_extra,
            fetched_at=fetched_at,
        )
        for model in page.data
        if model.id
    ]
    return _output(
        source="xai:developer_models",
        fetched_at=fetched_at,
        models=models,
        skips=[],
    )


async def _list_openai_image_generation_models(
    integration: LLMProviderIntegrationWithSecrets,
    *,
    clients: ListingClientFactories,
) -> ImageGenerationModelListingOutput:
    """Fetch every visible OpenAI model through the official SDK paginator."""
    if integration.provider != LLMProvider.OPENAI:
        raise ValueError("OpenAI image model listing requires an OpenAI integration.")
    secrets = _require_api_key_secrets(integration.secrets)
    client_config = openai_responses_client_config(
        provider=LLMProvider.OPENAI,
        credential_kwargs={"api_key": secrets.api_key},
    )
    fetched_at = datetime.now(timezone.utc)
    async with clients.openai(
        api_key=secrets.api_key,
        base_url=client_config.base_url,
        organization=client_config.organization,
        project=client_config.project,
        default_headers=client_config.default_headers,
        max_retries=0,
        timeout=20.0,
    ) as client:
        page: _OpenAIModelPage = await client.models.list()
        identifiers = await _complete_openai_model_identifiers(page)
    return ImageGenerationModelListingOutput(
        provider=LLMProvider.OPENAI,
        source="openai:models_list",
        fetched_at=fetched_at,
        provider_model_identifiers=identifiers,
    )


async def _complete_openai_model_identifiers(
    initial_page: _OpenAIModelPage,
) -> list[str]:
    """Consume all SDK pages and reject malformed or ambiguous identifiers."""
    page = initial_page
    identifiers: list[str] = []
    seen: set[str] = set()
    while True:
        for model in page.data:
            model_id = model.id
            if not isinstance(model_id, str) or not model_id:
                raise InvalidProviderResponseError(
                    "OpenAI model listing contained a malformed model identifier."
                )
            if model_id in seen:
                raise InvalidProviderResponseError(
                    "OpenAI model listing contained duplicate model identifiers."
                )
            seen.add(model_id)
            identifiers.append(model_id)
        if not page.has_next_page():
            return identifiers
        page = await page.get_next_page()


def _candidate_from_xai_api_key_model(
    *,
    model_id: str,
    created: int,
    extra: dict[str, object] | None,
    fetched_at: datetime,
) -> NormalizedModelCandidate:
    """Normalize one xAI developer API model."""
    return NormalizedModelCandidate(
        provider=LLMProvider.XAI,
        model_identifier=model_id,
        model_display_name=model_id,
        model_developer=LLMModelDeveloper.XAI,
        model_family=_xai_family(model_id),
        capability_evidence=_xai_api_capability_evidence(extra),
        normalized_capabilities=_conservative_xai_capabilities(),
        supported_execution_options=[],
        model_snapshot={
            "source": "xai:developer_models",
            "provider": LLMProvider.XAI.value,
            "model_identifier": model_id,
            "model_display_name": model_id,
            "model_developer": LLMModelDeveloper.XAI.value,
        },
        source_metadata=_xai_api_source_metadata(created=created, extra=extra),
        last_refreshed_at=fetched_at,
    )


def _xai_api_source_metadata(
    *, created: int, extra: dict[str, object] | None
) -> dict[str, object]:
    """Persist only consumed model facts, not arbitrary SDK provider extensions."""
    payload = _XaiApiEvidencePayload.model_validate(extra if extra is not None else {})
    metadata: dict[str, object] = {"created": created}
    if "context_length" in payload.model_fields_set:
        metadata["context_length"] = payload.context_length
    if "capabilities" in payload.model_fields_set:
        metadata["capabilities"] = (
            payload.capabilities.model_dump(
                mode="json",
                exclude_unset=True,
                include={"reasoning", "reasoning_effort", "default_reasoning_effort"},
            )
            if payload.capabilities is not None
            else None
        )
    if payload.capabilities is not None and isinstance(
        payload.capabilities.reasoning_effort, list
    ):
        metadata.update(_effort_diagnostics(payload.capabilities.reasoning_effort))
    return metadata


async def _list_xai_oauth_models(
    integration: LLMProviderIntegrationWithSecrets,
    *,
    clients: ListingClientFactories,
) -> ModelListingOutput:
    """Fetch Grok OAuth account models from the CLI proxy."""
    config = _require_xai_oauth_config(integration.config)
    secrets = _require_xai_oauth_secrets(integration.secrets)
    account_id = config.account_id
    if account_id is None or not account_id.strip():
        raise ValueError("xAI OAuth account metadata is required.")
    fetched_at = datetime.now(timezone.utc)
    headers = {
        "Authorization": f"Bearer {secrets.access_token}",
        "X-XAI-Token-Auth": "xai-grok-cli",
        "x-userid": account_id.strip(),
        "x-grok-client-version": XAI_MODELS_CLIENT_VERSION,
        "x-grok-client-identifier": "grok-shell",
        "x-grok-client-mode": "interactive",
    }
    async with clients.http(timeout=20.0) as client:
        response = await client.get(
            f"{resolve_xai_usage_base_url()}/models",
            headers=headers,
        )
        response.raise_for_status()
        payload = _XaiOAuthModelsPayload.model_validate(response.json())
    models = [
        _candidate_from_xai_oauth_model(model, fetched_at=fetched_at)
        for model in payload.data
    ]
    return _output(
        source="xai_oauth:grok_models",
        fetched_at=fetched_at,
        models=models,
        skips=[],
    )


def _candidate_from_xai_oauth_model(
    model: _XaiOAuthModelPayload,
    *,
    fetched_at: datetime,
) -> NormalizedModelCandidate:
    """Normalize one account-visible Grok model."""
    efforts = _xai_reasoning_efforts(model.reasoning_efforts)
    built_in_tools = ["web_search"] if model.supports_backend_search is True else []
    responses_api = (
        model.api_backend == "responses" if model.api_backend is not None else None
    )
    capabilities = ModelCapabilities(
        context_window=ModelContextWindow(
            max_input_tokens=_positive_int(model.context_window)
        ),
        modalities=ModelModalities(
            input=[ModelModality.TEXT],
            output=[ModelModality.TEXT],
        ),
        reasoning=ModelReasoningCapabilities(
            supported=model.supports_reasoning_effort is True,
            effort_levels=efforts,
        ),
        built_in_tools=ModelBuiltInToolCapabilities(supported=built_in_tools),
        compatibility=ModelCompatibilityCapabilities(
            provider_family="xai",
            responses_api=responses_api,
        ),
    )
    source_metadata = model.model_dump(
        mode="json",
        exclude_unset=True,
        include={
            "context_window": True,
            "api_backend": True,
            "supports_reasoning_effort": True,
            "reasoning_efforts": {"__all__": {"id", "value", "default"}},
            "supports_backend_search": True,
            "auto_compact_threshold_percent": True,
            "compaction_at_tokens": True,
            "show_model_fingerprint": True,
        },
    )
    raw_efforts = [
        preset.id if preset.id is not None else preset.value
        for preset in model.reasoning_efforts or []
    ]
    source_metadata.update(
        _effort_diagnostics([value for value in raw_efforts if value is not None])
    )
    if model.supports_reasoning_effort is False and model.reasoning_efforts:
        source_metadata["capability_conflicts"] = [
            "reasoning_effort_controls_disabled_with_presets"
        ]
    display_name = model.name or model.model or model.id
    return NormalizedModelCandidate(
        provider=LLMProvider.XAI_OAUTH,
        model_identifier=model.id,
        model_display_name=display_name,
        model_developer=LLMModelDeveloper.XAI,
        model_family=_xai_family(model.id),
        capability_evidence=_xai_oauth_capability_evidence(model),
        normalized_capabilities=capabilities,
        supported_execution_options=[],
        model_snapshot={
            "source": "xai_oauth:grok_models",
            "provider": LLMProvider.XAI_OAUTH.value,
            "model_identifier": model.id,
            "model_display_name": display_name,
            "model_developer": LLMModelDeveloper.XAI.value,
        },
        source_metadata=source_metadata,
        last_refreshed_at=fetched_at,
    )


def _conservative_xai_capabilities() -> ModelCapabilities:
    """Return capabilities safe when xAI omits model metadata."""
    return ModelCapabilities(
        modalities=ModelModalities(
            input=[ModelModality.TEXT],
            output=[ModelModality.TEXT],
        ),
        compatibility=ModelCompatibilityCapabilities(
            provider_family="xai",
            responses_api=None,
        ),
    )


def _xai_reasoning_efforts(
    payloads: list[_XaiOAuthReasoningEffortPayload] | None,
) -> list[ModelReasoningEffort]:
    """Normalize xAI reasoning levels into canonical order."""
    if payloads is None:
        return []
    available: set[ModelReasoningEffort] = set()
    for payload in payloads:
        raw = payload.value or payload.id
        if raw is None:
            continue
        try:
            available.add(ModelReasoningEffort(raw))
        except ValueError:
            continue
    return [effort for effort in ModelReasoningEffort if effort in available]


def _xai_family(model_id: str) -> str:
    """Extract the stable Grok model family prefix."""
    parts = model_id.split("-")
    if len(parts) >= 2 and parts[0].lower() == "grok":
        return "-".join(parts[:2])
    return parts[0]


async def _list_openrouter_models(
    integration: LLMProviderIntegrationWithSecrets,
    *,
    clients: ListingClientFactories,
) -> ModelListingOutput:
    """Fetch candidates from the OpenRouter account model endpoint."""
    secrets = _require_api_key_secrets(integration.secrets)
    fetched_at = datetime.now(timezone.utc)
    async with clients.http(timeout=20.0) as client:
        response = await client.get(
            f"{OPENROUTER_API_BASE_URL}/models/user",
            params={"output_modalities": "text"},
            headers={"Authorization": f"Bearer {secrets.api_key}"},
        )
        response.raise_for_status()
        payload = _AccountModelsPayload.model_validate(response.json())
    models: list[NormalizedModelCandidate] = []
    skipped = 0
    for raw_model in payload.data:
        try:
            model = _OPENROUTER_MODEL_ADAPTER.validate_python(raw_model)
        except ValidationError:
            if isinstance(raw_model, dict):
                raise
            skipped += 1
            continue
        candidate = _candidate_from_openrouter_model(model, fetched_at=fetched_at)
        if candidate is None:
            skipped += 1
            continue
        models.append(candidate)
    return _output(
        source="openrouter:account_models",
        fetched_at=fetched_at,
        models=models,
        skips=_skip_summary("invalid_openrouter_model", skipped),
    )


def _candidate_from_openrouter_model(
    model: _OpenRouterModelPayload,
    *,
    fetched_at: datetime,
) -> NormalizedModelCandidate | None:
    """Normalize one OpenRouter account-visible model."""
    model_id = model.id
    if model_id is None or not model.eligible:
        return None
    display_name = model.name or model_id
    developer = _openrouter_developer(model_id)
    supported_parameters = set(model.supported_parameters or [])
    context_length = _positive_int(model.context_length)
    top_provider = model.top_provider
    max_completion_tokens = (
        _positive_int(top_provider.max_completion_tokens)
        if top_provider is not None
        else None
    )
    reasoning_supported = bool(
        {"include_reasoning", "reasoning", "reasoning_effort"} & supported_parameters
    )
    capabilities = ModelCapabilities(
        context_window=ModelContextWindow(
            max_input_tokens=context_length,
            max_output_tokens=max_completion_tokens,
        ),
        modalities=ModelModalities(
            input=_openrouter_input_modalities(model),
            output=[ModelModality.TEXT],
        ),
        tool_calling=ModelToolCallingCapabilities(
            supported="tools" in supported_parameters,
            parallel_tool_calls=(
                True if "parallel_tool_calls" in supported_parameters else None
            ),
        ),
        reasoning=ModelReasoningCapabilities(
            supported=reasoning_supported,
            effort_levels=[],
        ),
        built_in_tools=ModelBuiltInToolCapabilities(supported=["web_search"]),
        parameters=ModelParameterCapabilities(
            temperature="temperature" in supported_parameters,
            max_output_tokens=bool(
                {"max_completion_tokens", "max_tokens"} & supported_parameters
            ),
            top_p="top_p" in supported_parameters,
            top_k="top_k" in supported_parameters,
            stop_sequences="stop" in supported_parameters,
        ),
        compatibility=ModelCompatibilityCapabilities(
            provider_family="openrouter",
            responses_api=True,
        ),
    )
    return NormalizedModelCandidate(
        provider=LLMProvider.OPENROUTER,
        model_identifier=model_id,
        model_display_name=display_name,
        model_developer=developer,
        model_family=_openrouter_family(model_id),
        capability_evidence=_openrouter_capability_evidence(model),
        normalized_capabilities=capabilities,
        supported_execution_options=[],
        model_snapshot={
            "source": "openrouter:account_models",
            "provider": LLMProvider.OPENROUTER.value,
            "model_identifier": model_id,
            "model_display_name": display_name,
            "model_developer": developer.value,
        },
        source_metadata=model.source_metadata,
        last_refreshed_at=fetched_at,
    )


def _openrouter_input_modalities(model: _OpenRouterModelPayload) -> list[ModelModality]:
    """Project only verified OpenRouter input modalities."""
    architecture = model.architecture
    if architecture is None or "input_modalities" not in architecture.model_fields_set:
        return [ModelModality.TEXT]
    raw_modalities = set(architecture.input_modalities or [])
    modalities: list[ModelModality] = []
    for modality in (ModelModality.TEXT, ModelModality.IMAGE):
        if modality.value in raw_modalities:
            modalities.append(modality)
    return modalities


def _openrouter_developer(model_id: str) -> LLMModelDeveloper:
    """Map the OpenRouter publisher segment to a safe developer value."""
    publisher = model_id.split("/", maxsplit=1)[0].lower()
    return OPENROUTER_PUBLISHERS.get(publisher, LLMModelDeveloper.OTHER)


def _openrouter_family(model_id: str) -> str | None:
    """Derive a diagnostic model family from the OpenRouter model id."""
    model_name = model_id.split("/", maxsplit=1)[-1]
    family = model_name.split("-", maxsplit=1)[0]
    return family or None


async def _list_vertex_models(
    integration: LLMProviderIntegrationWithSecrets,
    *,
    clients: ListingClientFactories,
) -> ModelListingOutput:
    """Fetch candidates with Vertex AI publisher model API."""
    config = _require_gcp_config(integration.config)
    secrets = _require_gcp_secrets(integration.secrets)
    fetched_at = datetime.now(timezone.utc)
    token = await asyncio.to_thread(clients.vertex_token, secrets)
    models: list[NormalizedModelCandidate] = []
    skipped = 0
    async with clients.http(timeout=10.0) as client:
        for publisher, developer in VERTEX_PUBLISHERS.items():
            url = (
                f"https://{config.region}-aiplatform.googleapis.com/v1/"
                f"projects/{config.project_id}/locations/{config.region}/"
                f"publishers/{publisher}/models"
            )
            response = await client.get(
                url,
                headers={"Authorization": f"Bearer {token}"},
            )
            response.raise_for_status()
            payload = _VertexModelsPayload.model_validate(response.json())
            for raw_model in payload.publisherModels or []:
                model = _VERTEX_MODEL_ADAPTER.validate_python(raw_model)
                candidate = _candidate_from_vertex_model(
                    model,
                    publisher=publisher,
                    developer=developer,
                    fetched_at=fetched_at,
                )
                if candidate is None:
                    skipped += 1
                    continue
                models.append(candidate)
    return _output(
        source="google_vertex_ai:publisher_models",
        fetched_at=fetched_at,
        models=models,
        skips=_skip_summary("unsupported_vertex_model", skipped),
    )


def _vertex_access_token(secrets: GcpSecrets) -> str:
    """Issue Vertex AI access token with service account JSON."""
    info = json.loads(secrets.service_account_json)
    credentials = service_account.Credentials.from_service_account_info(
        info,
        scopes=["https://www.googleapis.com/auth/cloud-platform"],
    )
    request = google.auth.transport.requests.Request()
    credentials.refresh(request)
    return str(credentials.token)


def _candidate_from_vertex_model(
    model: _VertexModelPayload,
    *,
    publisher: str,
    developer: LLMModelDeveloper,
    fetched_at: datetime,
) -> NormalizedModelCandidate | None:
    """Normalize Vertex publisher model."""
    model_id = model.modelId or _last_path_part(model.name)
    if model_id is None or not model.eligible:
        return None
    display_name = model.displayName or model_id
    return NormalizedModelCandidate(
        provider=LLMProvider.GOOGLE_VERTEX_AI,
        model_identifier=model_id,
        model_display_name=display_name,
        model_developer=developer,
        model_family=_vertex_family(model_id),
        capability_evidence=_vertex_capability_evidence(model),
        normalized_capabilities=ModelCapabilities(
            context_window=_vertex_context_window(model),
            modalities=ModelModalities(
                input=[ModelModality.TEXT],
                output=[ModelModality.TEXT],
            ),
            tool_calling=ModelToolCallingCapabilities(supported=True),
            compatibility=ModelCompatibilityCapabilities(provider_family="vertex_ai"),
        ),
        supported_execution_options=[],
        model_snapshot={
            "source": "google_vertex_ai:publisher_models",
            "provider": LLMProvider.GOOGLE_VERTEX_AI.value,
            "publisher": publisher,
            "model_identifier": model_id,
            "model_display_name": display_name,
            "model_developer": developer.value,
        },
        source_metadata=model.source_metadata,
        last_refreshed_at=fetched_at,
    )


def _output(
    *,
    source: str,
    fetched_at: datetime,
    models: list[NormalizedModelCandidate],
    skips: list[ModelListingSkipSummary],
) -> ModelListingOutput:
    """Build Listing output."""
    return ModelListingOutput(
        models=models,
        summary=ModelListingSummary(
            source=source,
            fetched_at=fetched_at,
            returned_count=len(models),
            skipped_count=sum(skip.count for skip in skips),
        ),
        skips=skips,
    )


def _skip_summary(reason: str, count: int) -> list[ModelListingSkipSummary]:
    """Return summary only when Skip count exists."""
    if count == 0:
        return []
    return [ModelListingSkipSummary(reason=reason, count=count)]


def _require_api_key_secrets(secrets: object) -> ApiKeySecrets:
    """Validate generic API-key integration secrets."""
    if not isinstance(secrets, ApiKeySecrets):
        raise ValueError("API-key integration secrets are required.")
    return secrets


def _require_aws_config(config: object) -> AwsConfig:
    """Validate AWS config type."""
    if not isinstance(config, AwsConfig):
        msg = "AWS Bedrock integration config is required."
        raise ValueError(msg)
    return config


def _require_aws_secrets(secrets: object) -> AwsSecrets:
    """Validate AWS secrets type."""
    if not isinstance(secrets, AwsSecrets):
        msg = "AWS Bedrock integration secrets are required."
        raise ValueError(msg)
    return secrets


def _require_chatgpt_config(config: object) -> ChatGPTOAuthConfig:
    """Validate ChatGPT OAuth config type."""
    if not isinstance(config, ChatGPTOAuthConfig):
        raise ValueError("ChatGPT OAuth integration config is required.")
    return config


def _require_chatgpt_secrets(secrets: object) -> ChatGPTOAuthSecrets:
    """Validate ChatGPT OAuth secrets type."""
    if not isinstance(secrets, ChatGPTOAuthSecrets):
        raise ValueError("ChatGPT OAuth integration secrets are required.")
    return secrets


def _require_kimi_config(config: object) -> KimiOAuthConfig:
    """Validate Kimi OAuth config type."""
    if not isinstance(config, KimiOAuthConfig):
        raise ValueError("Kimi OAuth integration config is required.")
    return config


def _require_kimi_secrets(secrets: object) -> KimiOAuthSecrets:
    """Validate Kimi OAuth secrets type."""
    if not isinstance(secrets, KimiOAuthSecrets):
        raise ValueError("Kimi OAuth integration secrets are required.")
    return secrets


def _require_xai_oauth_config(config: object) -> XaiOAuthConfig:
    """Validate xAI OAuth integration config."""
    if not isinstance(config, XaiOAuthConfig):
        raise ValueError("xAI OAuth integration config is required.")
    return config


def _require_xai_oauth_secrets(secrets: object) -> XaiOAuthSecrets:
    """Validate xAI OAuth integration secrets."""
    if not isinstance(secrets, XaiOAuthSecrets):
        raise ValueError("xAI OAuth integration secrets are required.")
    return secrets


def _require_gcp_config(config: object) -> GcpConfig:
    """Validate GCP config type."""
    if not isinstance(config, GcpConfig):
        msg = "Google Vertex AI integration config is required."
        raise ValueError(msg)
    return config


def _require_gcp_secrets(secrets: object) -> GcpSecrets:
    """Validate GCP secrets type."""
    if not isinstance(secrets, GcpSecrets):
        msg = "Google Vertex AI integration secrets are required."
        raise ValueError(msg)
    return secrets


def _positive_int(value: object) -> int | None:
    """Return a positive integer without accepting booleans."""
    if isinstance(value, int) and not isinstance(value, bool) and value > 0:
        return value
    return None


def _last_path_part(value: str | None) -> str | None:
    """Return last segment of Resource name."""
    if value is None:
        return None
    return value.rsplit("/", maxsplit=1)[-1]


def _developer_from_bedrock_provider(
    provider_name: str | None,
) -> LLMModelDeveloper | None:
    """Normalize Bedrock providerName to model developer."""
    normalized = (provider_name or "").lower()
    if "anthropic" in normalized:
        return LLMModelDeveloper.ANTHROPIC
    if "meta" in normalized:
        return LLMModelDeveloper.META
    if "mistral" in normalized:
        return LLMModelDeveloper.MISTRAL
    return None


def _chatgpt_reasoning_efforts(
    value: list[_ChatGPTReasoningLevel] | None,
) -> list[ModelReasoningEffort]:
    """Normalize ChatGPT reasoning effort presets in provider order."""
    if value is None:
        return []
    efforts: list[ModelReasoningEffort] = []
    for preset in value:
        try:
            normalized = ModelReasoningEffort(preset.effort)
        except ValueError:
            continue
        if normalized not in efforts:
            efforts.append(normalized)
    return efforts


def _chatgpt_context_window(model: _ChatGPTModelPayload) -> ModelContextWindow:
    """Preserve ChatGPT default and maximum context-window metadata."""
    default_input_tokens = _positive_int(model.context_window)
    max_input_tokens = _positive_int(model.max_context_window)
    return ModelContextWindow(
        default_input_tokens=default_input_tokens,
        max_input_tokens=max_input_tokens or default_input_tokens,
    )


def _chatgpt_modalities(model: _ChatGPTModelPayload) -> list[ModelModality]:
    """Normalize ChatGPT input modalities with the backend legacy default."""
    if "input_modalities" not in model.model_fields_set:
        return [ModelModality.TEXT, ModelModality.IMAGE]
    modalities: list[ModelModality] = []
    for raw in model.input_modalities or []:
        try:
            modality = ModelModality(raw)
        except ValueError:
            continue
        if modality not in modalities:
            modalities.append(modality)
    return modalities


def _chatgpt_family(model_id: str) -> str:
    """Extract the ChatGPT model family identifier."""
    parts = model_id.split("-")
    if len(parts) >= 2 and parts[0] == "gpt":
        return "-".join(parts[:2])
    return parts[0]


def _bedrock_family(model_id: str) -> str:
    """Extract Bedrock model family."""
    return model_id.split(":", maxsplit=1)[0]


def _vertex_family(model_id: str) -> str:
    """Extract Vertex model family."""
    return model_id.rsplit("@", maxsplit=1)[0]


def _modalities_from_bedrock(summary: _BedrockModelPayload) -> ModelModalities:
    """Normalize Bedrock modality string."""
    return ModelModalities(
        input=_modalities(summary.inputModalities),
        output=_modalities(summary.outputModalities),
    )


def _modalities(value: list[str] | None) -> list[ModelModality]:
    """Convert Provider modality list to internal enum."""
    if value is None:
        return [ModelModality.TEXT]
    result: list[ModelModality] = []
    for raw in value:
        match raw.lower():
            case "text":
                result.append(ModelModality.TEXT)
            case "image":
                result.append(ModelModality.IMAGE)
            case _:
                continue
    return result or [ModelModality.TEXT]


def _vertex_context_window(model: _VertexModelPayload) -> ModelContextWindow:
    """Read context window from Vertex metadata best-effort."""
    return ModelContextWindow(
        max_input_tokens=model.inputTokenLimit,
        max_output_tokens=model.outputTokenLimit,
    )
