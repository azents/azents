"""Provider-visible model listing adapters for user catalogs."""

from __future__ import annotations

import asyncio
import json
from collections.abc import Sequence
from datetime import datetime, timezone

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
from pydantic import TypeAdapter, ValidationError

from azents.core.chatgpt_oauth import (
    CHATGPT_OAUTH_BACKEND_BASE_URL,
    CHATGPT_OAUTH_PROTOCOL_VERSION,
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
)
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
from azents.core.openrouter import OPENROUTER_API_BASE_URL
from azents.repos.llm_provider_integration.data import (
    LLMProviderIntegrationWithSecrets,
)
from azents.services.builtin_capabilities import supported_builtin_capabilities

from .data import (
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

_BEDROCK_MODEL_SUMMARY_ADAPTER = TypeAdapter[dict[str, object]](dict[str, object])
_CHATGPT_MODEL_ADAPTER = TypeAdapter[dict[str, object]](dict[str, object])
_OPENROUTER_MODEL_ADAPTER = TypeAdapter[dict[str, object]](dict[str, object])
_VERTEX_MODEL_ADAPTER = TypeAdapter[dict[str, object]](dict[str, object])


class ListingProviderError(Exception):
    """Provider listing adapter failure with automatic retry policy."""

    def __init__(self, message: str, *, automatic_retry_blocked: bool) -> None:
        super().__init__(message)
        self.automatic_retry_blocked = automatic_retry_blocked


class InvalidProviderResponseError(ValueError):
    """Provider returned a response that cannot be projected."""


async def list_bedrock_models_for_integration(
    integration: LLMProviderIntegrationWithSecrets,
) -> ModelListingOutput:
    """Fetch provider listing of AWS Bedrock integration."""
    try:
        return await _list_bedrock_models(integration)
    except (BotoCoreError, ClientError, ValueError) as exc:
        raise ListingProviderError(
            "AWS Bedrock model listing failed.",
            automatic_retry_blocked=automatic_retry_blocked_for_listing_error(exc),
        ) from exc


async def list_vertex_models_for_integration(
    integration: LLMProviderIntegrationWithSecrets,
) -> ModelListingOutput:
    """Fetch provider listing of Google Vertex AI integration."""
    try:
        return await _list_vertex_models(integration)
    except (GoogleAuthError, httpx.HTTPError, json.JSONDecodeError, ValueError) as exc:
        raise ListingProviderError(
            "Google Vertex AI model listing failed.",
            automatic_retry_blocked=automatic_retry_blocked_for_listing_error(exc),
        ) from exc


async def list_chatgpt_models_for_integration(
    integration: LLMProviderIntegrationWithSecrets,
) -> ModelListingOutput:
    """Fetch account-visible models from the ChatGPT Codex backend."""
    try:
        return await _list_chatgpt_models(integration)
    except (httpx.HTTPError, json.JSONDecodeError, ValueError) as exc:
        raise ListingProviderError(
            "ChatGPT model listing failed.",
            automatic_retry_blocked=automatic_retry_blocked_for_listing_error(exc),
        ) from exc


async def list_openrouter_models_for_integration(
    integration: LLMProviderIntegrationWithSecrets,
) -> ModelListingOutput:
    """Fetch account-visible text-output models from OpenRouter."""
    try:
        return await _list_openrouter_models(integration)
    except (httpx.HTTPError, json.JSONDecodeError, ValueError) as exc:
        raise ListingProviderError(
            "OpenRouter model listing failed.",
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
    if isinstance(exc, (BotoConnectionError, HTTPClientError)):
        return False
    if isinstance(
        exc,
        (
            httpx.TransportError,
            json.JSONDecodeError,
            ValidationError,
            InvalidProviderResponseError,
        ),
    ):
        return False
    if isinstance(exc, (GoogleAuthError, BotoCoreError)):
        return True
    return isinstance(exc, ValueError)


async def _list_bedrock_models(
    integration: LLMProviderIntegrationWithSecrets,
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
) -> list[dict[str, object]]:
    """Perform synchronous boto3 Bedrock call."""
    session = boto3.Session(
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
        session = boto3.Session(
            aws_access_key_id=credentials["AccessKeyId"],
            aws_secret_access_key=credentials["SecretAccessKey"],
            aws_session_token=credentials["SessionToken"],
            region_name=config.region,
        )
    bedrock = session.client("bedrock", region_name=config.region)
    response = bedrock.list_foundation_models()
    summaries = response.get("modelSummaries", [])
    return [summary for summary in summaries if isinstance(summary, dict)]


def _candidate_from_bedrock_summary(
    summary: dict[str, object],
    *,
    fetched_at: datetime,
) -> NormalizedModelCandidate | None:
    """Normalize Bedrock summary."""
    model_id = _str_value(summary, "modelId")
    if model_id is None:
        return None
    lifecycle = summary.get("modelLifecycle")
    if isinstance(lifecycle, dict) and lifecycle.get("status") == "LEGACY":
        return None
    developer = _developer_from_bedrock_provider(_str_value(summary, "providerName"))
    if developer is None:
        return None
    modalities = _modalities_from_bedrock(summary)
    return NormalizedModelCandidate(
        provider=LLMProvider.AWS_BEDROCK,
        model_identifier=model_id,
        model_display_name=_str_value(summary, "modelName") or model_id,
        model_developer=developer,
        model_family=_bedrock_family(model_id),
        normalized_capabilities=ModelCapabilities(
            modalities=modalities,
            tool_calling=ModelToolCallingCapabilities(supported=True),
            compatibility=ModelCompatibilityCapabilities(provider_family="bedrock"),
        ),
        model_snapshot={
            "source": "aws_bedrock:list_foundation_models",
            "provider": LLMProvider.AWS_BEDROCK.value,
            "model_identifier": model_id,
            "model_display_name": _str_value(summary, "modelName") or model_id,
            "model_developer": developer.value,
        },
        source_metadata=summary,
        last_refreshed_at=fetched_at,
    )


async def _list_chatgpt_models(
    integration: LLMProviderIntegrationWithSecrets,
) -> ModelListingOutput:
    """Fetch candidates from the ChatGPT Codex models endpoint."""
    config = _require_chatgpt_config(integration.config)
    secrets = _require_chatgpt_secrets(integration.secrets)
    fetched_at = datetime.now(timezone.utc)
    headers = build_chatgpt_oauth_headers(account_id=config.account_id)
    headers.update(
        {
            "Authorization": f"Bearer {secrets.access_token}",
            "version": CHATGPT_OAUTH_PROTOCOL_VERSION,
        }
    )
    async with httpx.AsyncClient(timeout=20.0) as client:
        response = await client.get(
            f"{CHATGPT_OAUTH_BACKEND_BASE_URL}/models",
            params={"client_version": CHATGPT_OAUTH_PROTOCOL_VERSION},
            headers=headers,
        )
        response.raise_for_status()
        payload = response.json()
    raw_models = payload.get("models") if isinstance(payload, dict) else None
    if not isinstance(raw_models, list):
        raise InvalidProviderResponseError(
            "ChatGPT model listing response must contain models."
        )
    models: list[NormalizedModelCandidate] = []
    skipped = 0
    for raw_model in raw_models:
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
    model: dict[str, object],
    *,
    fetched_at: datetime,
) -> NormalizedModelCandidate | None:
    """Normalize ChatGPT Codex model metadata."""
    model_id = _str_value(model, "slug")
    if (
        model_id is None
        or model.get("supported_in_api") is not True
        or model.get("visibility") != "list"
    ):
        return None
    display_name = _str_value(model, "display_name") or model_id
    reasoning_efforts = _chatgpt_reasoning_efforts(
        model.get("supported_reasoning_levels")
    )
    input_modalities = _chatgpt_modalities(model)
    context_window = _chatgpt_context_window(model)
    parallel_tool_calls_value = model.get("supports_parallel_tool_calls")
    parallel_tool_calls = (
        parallel_tool_calls_value
        if isinstance(parallel_tool_calls_value, bool)
        else None
    )
    reasoning_summaries_value = model.get("supports_reasoning_summaries")
    reasoning_summaries = (
        reasoning_summaries_value
        if isinstance(reasoning_summaries_value, bool)
        else None
    )
    capabilities = ModelCapabilities(
        context_window=ModelContextWindow(max_input_tokens=context_window),
        modalities=ModelModalities(
            input=input_modalities,
            output=[ModelModality.TEXT],
        ),
        tool_calling=ModelToolCallingCapabilities(
            supported=True,
            parallel_tool_calls=parallel_tool_calls,
        ),
        reasoning=ModelReasoningCapabilities(
            supported=bool(reasoning_efforts),
            effort_levels=reasoning_efforts,
            summaries=reasoning_summaries,
        ),
        built_in_tools=ModelBuiltInToolCapabilities(
            supported=supported_builtin_capabilities(
                provider=LLMProvider.CHATGPT_OAUTH,
                model_identifier=model_id,
                metadata=model,
            )
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
        normalized_capabilities=capabilities,
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


def _chatgpt_source_metadata(model: dict[str, object]) -> dict[str, object]:
    """Keep catalog-relevant ChatGPT metadata without storing model instructions."""
    keys = (
        "auto_compact_token_limit",
        "context_window",
        "default_reasoning_level",
        "effective_context_window_percent",
        "experimental_supported_tools",
        "input_modalities",
        "max_context_window",
        "minimal_client_version",
        "priority",
        "supported_in_api",
        "supported_reasoning_levels",
        "supports_parallel_tool_calls",
        "supports_reasoning_summaries",
        "tool_mode",
        "visibility",
    )
    return {key: model[key] for key in keys if key in model}


async def _list_openrouter_models(
    integration: LLMProviderIntegrationWithSecrets,
) -> ModelListingOutput:
    """Fetch candidates from the OpenRouter account model endpoint."""
    secrets = _require_api_key_secrets(integration.secrets)
    fetched_at = datetime.now(timezone.utc)
    async with httpx.AsyncClient(timeout=20.0) as client:
        response = await client.get(
            f"{OPENROUTER_API_BASE_URL}/models/user",
            params={"output_modalities": "text"},
            headers={"Authorization": f"Bearer {secrets.api_key}"},
        )
        response.raise_for_status()
        payload = response.json()
    raw_models = payload.get("data") if isinstance(payload, dict) else None
    if not isinstance(raw_models, list):
        raise InvalidProviderResponseError(
            "OpenRouter model listing response must contain data."
        )
    models: list[NormalizedModelCandidate] = []
    skipped = 0
    for raw_model in raw_models:
        try:
            model = _OPENROUTER_MODEL_ADAPTER.validate_python(raw_model)
        except ValidationError:
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
    model: dict[str, object],
    *,
    fetched_at: datetime,
) -> NormalizedModelCandidate | None:
    """Normalize one OpenRouter account-visible model."""
    model_id = _str_value(model, "id")
    if model_id is None or not _openrouter_supports_text_output(model):
        return None
    display_name = _str_value(model, "name") or model_id
    developer = _openrouter_developer(model_id)
    supported_parameters = _string_values(model.get("supported_parameters"))
    context_length = _positive_int(model.get("context_length"))
    top_provider = model.get("top_provider")
    max_completion_tokens = (
        _positive_int(top_provider.get("max_completion_tokens"))
        if isinstance(top_provider, dict)
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
            effort_levels=(
                [
                    ModelReasoningEffort.LOW,
                    ModelReasoningEffort.MEDIUM,
                    ModelReasoningEffort.HIGH,
                ]
                if "reasoning_effort" in supported_parameters
                else []
            ),
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
        normalized_capabilities=capabilities,
        model_snapshot={
            "source": "openrouter:account_models",
            "provider": LLMProvider.OPENROUTER.value,
            "model_identifier": model_id,
            "model_display_name": display_name,
            "model_developer": developer.value,
        },
        source_metadata=_openrouter_source_metadata(model),
        last_refreshed_at=fetched_at,
    )


def _openrouter_supports_text_output(model: dict[str, object]) -> bool:
    """Return whether OpenRouter metadata permits text output."""
    architecture = model.get("architecture")
    if not isinstance(architecture, dict):
        return True
    output_modalities = architecture.get("output_modalities")
    if output_modalities is None:
        return True
    return "text" in _string_values(output_modalities)


def _openrouter_input_modalities(model: dict[str, object]) -> list[ModelModality]:
    """Project only verified OpenRouter input modalities."""
    architecture = model.get("architecture")
    if not isinstance(architecture, dict) or "input_modalities" not in architecture:
        return [ModelModality.TEXT]
    raw_modalities = _string_values(architecture.get("input_modalities"))
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


def _openrouter_source_metadata(model: dict[str, object]) -> dict[str, object]:
    """Keep bounded catalog-relevant OpenRouter metadata."""
    keys = (
        "architecture",
        "canonical_slug",
        "context_length",
        "created",
        "expiration_date",
        "pricing",
        "reasoning",
        "supported_parameters",
        "top_provider",
    )
    return {key: model[key] for key in keys if key in model}


async def _list_vertex_models(
    integration: LLMProviderIntegrationWithSecrets,
) -> ModelListingOutput:
    """Fetch candidates with Vertex AI publisher model API."""
    config = _require_gcp_config(integration.config)
    secrets = _require_gcp_secrets(integration.secrets)
    fetched_at = datetime.now(timezone.utc)
    token = await asyncio.to_thread(_vertex_access_token, secrets)
    models: list[NormalizedModelCandidate] = []
    skipped = 0
    async with httpx.AsyncClient(timeout=10.0) as client:
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
            payload = response.json()
            raw_models = (
                payload.get("publisherModels") if isinstance(payload, dict) else None
            )
            if not isinstance(raw_models, list):
                raw_models = []
            for raw_model in raw_models:
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
    model: dict[str, object],
    *,
    publisher: str,
    developer: LLMModelDeveloper,
    fetched_at: datetime,
) -> NormalizedModelCandidate | None:
    """Normalize Vertex publisher model."""
    name = _str_value(model, "name")
    model_id = _str_value(model, "modelId") or _last_path_part(name)
    if model_id is None:
        return None
    display_name = _str_value(model, "displayName") or model_id
    return NormalizedModelCandidate(
        provider=LLMProvider.GOOGLE_VERTEX_AI,
        model_identifier=model_id,
        model_display_name=display_name,
        model_developer=developer,
        model_family=_vertex_family(model_id),
        normalized_capabilities=ModelCapabilities(
            context_window=_vertex_context_window(model),
            modalities=ModelModalities(
                input=[ModelModality.TEXT],
                output=[ModelModality.TEXT],
            ),
            tool_calling=ModelToolCallingCapabilities(supported=True),
            compatibility=ModelCompatibilityCapabilities(provider_family="vertex_ai"),
        ),
        model_snapshot={
            "source": "google_vertex_ai:publisher_models",
            "provider": LLMProvider.GOOGLE_VERTEX_AI.value,
            "publisher": publisher,
            "model_identifier": model_id,
            "model_display_name": display_name,
            "model_developer": developer.value,
        },
        source_metadata=model,
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


def _string_values(value: object) -> set[str]:
    """Return string members from a provider sequence."""
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        return set()
    return {item for item in value if isinstance(item, str)}


def _str_value(mapping: dict[str, object], key: str) -> str | None:
    """Extract only string values."""
    value = mapping.get(key)
    if isinstance(value, str) and value:
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


def _chatgpt_reasoning_efforts(value: object) -> list[ModelReasoningEffort]:
    """Normalize ChatGPT reasoning effort presets in provider order."""
    if not isinstance(value, list):
        return []
    efforts: list[ModelReasoningEffort] = []
    for preset in value:
        if not isinstance(preset, dict):
            continue
        effort = preset.get("effort")
        if not isinstance(effort, str):
            continue
        try:
            normalized = ModelReasoningEffort(effort)
        except ValueError:
            continue
        if normalized not in efforts:
            efforts.append(normalized)
    return efforts


def _chatgpt_context_window(model: dict[str, object]) -> int | None:
    """Resolve the effective ChatGPT context window from backend metadata."""
    for key in ("context_window", "max_context_window"):
        value = model.get(key)
        if isinstance(value, int) and not isinstance(value, bool) and value > 0:
            return value
    return None


def _chatgpt_modalities(model: dict[str, object]) -> list[ModelModality]:
    """Normalize ChatGPT input modalities with the backend legacy default."""
    if "input_modalities" not in model:
        return [ModelModality.TEXT, ModelModality.IMAGE]
    value = model.get("input_modalities")
    if not isinstance(value, list):
        return []
    modalities: list[ModelModality] = []
    for raw in value:
        if not isinstance(raw, str):
            continue
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


def _modalities_from_bedrock(summary: dict[str, object]) -> ModelModalities:
    """Normalize Bedrock modality string."""
    return ModelModalities(
        input=_modalities(summary.get("inputModalities")),
        output=_modalities(summary.get("outputModalities")),
    )


def _modalities(value: object) -> list[ModelModality]:
    """Convert Provider modality list to internal enum."""
    if not isinstance(value, Sequence) or isinstance(value, str):
        return [ModelModality.TEXT]
    result: list[ModelModality] = []
    for raw in value:
        if not isinstance(raw, str):
            continue
        match raw.lower():
            case "text":
                result.append(ModelModality.TEXT)
            case "image":
                result.append(ModelModality.IMAGE)
            case _:
                continue
    return result or [ModelModality.TEXT]


def _vertex_context_window(model: dict[str, object]) -> ModelContextWindow:
    """Read context window from Vertex metadata best-effort."""
    input_token_limit = model.get("inputTokenLimit")
    output_token_limit = model.get("outputTokenLimit")
    return ModelContextWindow(
        max_input_tokens=(
            input_token_limit
            if isinstance(input_token_limit, int)
            and not isinstance(input_token_limit, bool)
            else None
        ),
        max_output_tokens=(
            output_token_limit
            if isinstance(output_token_limit, int)
            and not isinstance(output_token_limit, bool)
            else None
        ),
    )
