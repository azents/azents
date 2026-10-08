"""Explicit current source and narrow context collaborators for tests."""

import datetime
import json
from collections.abc import Sequence
from typing import assert_never

from azents.core.enums import LLMProvider
from azents.core.model_catalog_identity import catalog_source_keys
from azents.core.model_catalog_source import (
    CATALOG_SOURCE_KEY,
    CATALOG_SOURCE_KIND,
    CatalogSourcePayload,
    decode_catalog_source,
)
from azents.core.model_metadata_collection_data import CurrentSourceModel
from azents.core.model_pricing import (
    CapturedModelPricing,
    capture_model_pricing,
    normalize_model_pricing,
)
from azents.repos.model_metadata_read import ModelMetadataReadRepository
from azents.repos.model_metadata_source_data import (
    CapturedContextSource,
    ContextModelMetadata,
    ContextModelRequest,
    ModelMetadataSource,
)
from azents.services.model_metadata import ModelMetadataService


class _StaticMetadataReadRepository(ModelMetadataReadRepository):
    """Return supplied current data without database or network I/O."""

    def __init__(self, source: ModelMetadataSource | None) -> None:
        self.source = source

    async def capture_current(self) -> ModelMetadataSource | None:
        return self.source

    async def capture_for_context(
        self, *, requests: Sequence[ContextModelRequest]
    ) -> CapturedContextSource:
        models: list[ContextModelMetadata] = []
        for request in requests:
            maximum = None
            if self.source is not None:
                for key in catalog_source_keys(
                    provider=request.provider,
                    model_identifier=request.model_identifier,
                ):
                    found = next(
                        (
                            row.model
                            for row in self.source.models
                            if row.model.provider == key.provider
                            and row.model.source_key == key.source_model_key
                        ),
                        None,
                    )
                    if found is not None:
                        maximum = found.facts.max_input_tokens.value
                        break
            models.append(
                ContextModelMetadata(
                    provider=request.provider,
                    model_identifier=request.model_identifier,
                    max_input_tokens=maximum,
                )
            )
        return CapturedContextSource(models=tuple(models))


def make_test_source_payload(models: dict[str, object]) -> CatalogSourcePayload:
    """Decode explicit raw records through production JSON ingress."""
    return decode_catalog_source(json.dumps(models, allow_nan=False).encode())


def make_test_source(payload: CatalogSourcePayload) -> ModelMetadataSource:
    """Wrap typed evidence and normalized prices in current per-model data."""
    collected_at = datetime.datetime(2026, 10, 1, tzinfo=datetime.UTC)
    return ModelMetadataSource(
        source_key=CATALOG_SOURCE_KEY,
        source_kind=CATALOG_SOURCE_KIND,
        source_schema_version=payload.schema_version,
        source_url="https://source.example.test/models.json",
        producer_name="LiteLLM public catalog",
        producer_version="fixture-data-1",
        provider_count=payload.provider_count,
        model_count=payload.model_count,
        payload=payload,
        collected_at=collected_at,
        models=tuple(
            CurrentSourceModel(
                model=model,
                pricing=normalize_model_pricing(
                    source_key=CATALOG_SOURCE_KEY,
                    source_model=model,
                    collected_at=collected_at,
                ),
                collected_at=collected_at,
            )
            for model in payload.models
        ),
    )


def make_test_model_metadata_service(
    *, source: ModelMetadataSource | None
) -> ModelMetadataService:
    """Construct a static narrow reader instead of an implicit fallback."""
    return ModelMetadataService(repository=_StaticMetadataReadRepository(source))


def make_test_model_pricing(
    *, provider: LLMProvider, model_identifier: str
) -> CapturedModelPricing:
    """Create exact-scoped deterministic token pricing for event tests."""
    match provider:
        case LLMProvider.OPENAI:
            namespace, key = "openai", model_identifier
        case LLMProvider.ANTHROPIC:
            namespace, key = "anthropic", model_identifier
        case LLMProvider.GOOGLE_GEMINI:
            namespace, key = "gemini", f"gemini/{model_identifier}"
        case LLMProvider.AWS_BEDROCK:
            namespace, key = "bedrock_converse", model_identifier
        case LLMProvider.GOOGLE_VERTEX_AI:
            namespace, key = "vertex_ai", f"vertex_ai/{model_identifier}"
        case LLMProvider.CHATGPT_OAUTH:
            namespace, key = "chatgpt", f"chatgpt/{model_identifier}"
        case LLMProvider.XAI:
            namespace, key = "xai", f"xai/{model_identifier}"
        case LLMProvider.XAI_OAUTH:
            namespace, key = "xai_oauth", f"xai_oauth/{model_identifier}"
        case LLMProvider.KIMI_OAUTH:
            namespace, key = "kimi_oauth", f"kimi_oauth/{model_identifier}"
        case LLMProvider.OPENROUTER:
            namespace, key = "openrouter", f"openrouter/{model_identifier}"
        case _ as unreachable:
            assert_never(unreachable)
    payload = make_test_source_payload(
        {
            key: {
                "litellm_provider": namespace,
                "max_input_tokens": 128_000,
                "input_cost_per_token": 0.1,
                "output_cost_per_token": 0.2,
                "cache_read_input_token_cost": 0.01,
                "cache_creation_input_token_cost": 0.15,
            }
        }
    )
    collected_at = datetime.datetime(2026, 10, 1, tzinfo=datetime.UTC)
    return capture_model_pricing(
        provider=provider,
        model_identifier=model_identifier,
        definition=normalize_model_pricing(
            source_key=CATALOG_SOURCE_KEY,
            source_model=payload.models[0],
            collected_at=collected_at,
        ),
        request_timestamp=collected_at,
    )
