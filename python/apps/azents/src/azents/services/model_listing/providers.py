"""Provider-visible model listing adapters for user catalogs."""

from __future__ import annotations

import asyncio
import json
from collections.abc import Sequence
from datetime import datetime, timezone

import boto3
import google.auth.transport.requests
import httpx
from botocore.exceptions import BotoCoreError, ClientError
from google.auth.exceptions import GoogleAuthError
from google.oauth2 import service_account
from pydantic import TypeAdapter

from azents.core.credentials import AwsConfig, AwsSecrets, GcpConfig, GcpSecrets
from azents.core.enums import LLMModelDeveloper, LLMProvider
from azents.core.llm_catalog import (
    ModelCapabilities,
    ModelCompatibilityCapabilities,
    ModelContextWindow,
    ModelModalities,
    ModelModality,
    ModelToolCallingCapabilities,
)
from azents.repos.llm_provider_integration.data import (
    LLMProviderIntegrationWithSecrets,
)

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

_BEDROCK_MODEL_SUMMARY_ADAPTER = TypeAdapter[dict[str, object]](dict[str, object])
_VERTEX_MODEL_ADAPTER = TypeAdapter[dict[str, object]](dict[str, object])


class ListingProviderError(Exception):
    """Provider listing adapter failure."""


async def list_bedrock_models_for_integration(
    integration: LLMProviderIntegrationWithSecrets,
) -> ModelListingOutput:
    """Fetch provider listing of AWS Bedrock integration."""
    try:
        return await _list_bedrock_models(integration)
    except (BotoCoreError, ClientError, ValueError) as exc:
        raise ListingProviderError("AWS Bedrock model listing failed.") from exc


async def list_vertex_models_for_integration(
    integration: LLMProviderIntegrationWithSecrets,
) -> ModelListingOutput:
    """Fetch provider listing of Google Vertex AI integration."""
    try:
        return await _list_vertex_models(integration)
    except (GoogleAuthError, httpx.HTTPError, json.JSONDecodeError, ValueError) as exc:
        raise ListingProviderError("Google Vertex AI model listing failed.") from exc


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
