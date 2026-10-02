"""Explicit typed source collaborators for deterministic tests."""

import datetime
import json
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from typing import assert_never

from sqlalchemy.ext.asyncio import AsyncSession

from azents.core.enums import LLMProvider
from azents.core.model_catalog_source import (
    CATALOG_SOURCE_KEY,
    CATALOG_SOURCE_KIND,
    CatalogSourcePayload,
    decode_catalog_source,
)
from azents.core.model_pricing import CapturedModelPricing, normalize_model_pricing
from azents.repos.model_metadata_source import ModelMetadataSourceRepository
from azents.repos.model_metadata_source_data import ModelMetadataSourceSnapshot
from azents.services.model_metadata import ModelMetadataService


class _StaticSourceRepository(ModelMetadataSourceRepository):
    """Return a supplied validated snapshot without database or network I/O."""

    def __init__(self, snapshot: ModelMetadataSourceSnapshot | None) -> None:
        self.snapshot = snapshot

    async def get_current(
        self,
        session: AsyncSession,
        *,
        source_key: str,
    ) -> ModelMetadataSourceSnapshot | None:
        del session
        assert source_key == CATALOG_SOURCE_KEY
        return self.snapshot


@asynccontextmanager
async def _disconnected_session() -> AsyncGenerator[AsyncSession, None]:
    """Provide an explicitly disconnected session to the static repository."""
    async with AsyncSession() as session:
        yield session


def make_test_source_payload(models: dict[str, object]) -> CatalogSourcePayload:
    """Decode explicit raw source records through the production JSON ingress."""
    return decode_catalog_source(json.dumps(models, allow_nan=False).encode())


def make_test_source_snapshot(
    payload: CatalogSourcePayload,
) -> ModelMetadataSourceSnapshot:
    """Wrap validated evidence in a deterministic new-family source snapshot."""
    return ModelMetadataSourceSnapshot(
        id="source-snapshot-1",
        source_key=CATALOG_SOURCE_KEY,
        source_kind=CATALOG_SOURCE_KIND,
        source_schema_version=payload.schema_version,
        source_url="https://source.example.test/models.json",
        source_hash=payload.content_hash,
        producer_name="LiteLLM public catalog",
        producer_version="fixture-data-1",
        provider_count=payload.provider_count,
        model_count=payload.model_count,
        payload=payload,
        created_at=datetime.datetime(2026, 10, 1, tzinfo=datetime.UTC),
    )


def make_test_model_metadata_service(
    *,
    snapshot: ModelMetadataSourceSnapshot | None,
) -> ModelMetadataService:
    """Construct explicit static metadata instead of a global/default fallback."""
    return ModelMetadataService(
        session_manager=_disconnected_session,
        source_snapshot_repository=_StaticSourceRepository(snapshot),
    )


def make_test_model_pricing(
    *,
    provider: LLMProvider,
    model_identifier: str,
) -> CapturedModelPricing:
    """Create exact-scoped deterministic generic token pricing for event tests."""
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
    return normalize_model_pricing(
        provider=provider,
        model_identifier=model_identifier,
        source_snapshot_id="source-snapshot-1",
        source_hash=payload.content_hash,
        source_model=payload.models[0],
        request_timestamp=datetime.datetime(2026, 10, 1, tzinfo=datetime.UTC),
    )
