"""Explicit null/static source metadata collaborators for deterministic tests."""

import datetime
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from decimal import Decimal

from sqlalchemy.ext.asyncio import AsyncSession

from azents.core.enums import LLMProvider
from azents.core.model_metadata_source import (
    SourceEqualsClause,
    SourceModelRecord,
    SourcePriceSet,
    SourceProviderRecord,
    SourceScalarPrice,
)
from azents.core.model_pricing import GenAIModelPricing, normalize_genai_model_pricing
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
        assert source_key == "genai_prices"
        return self.snapshot


@asynccontextmanager
async def _disconnected_session() -> AsyncGenerator[AsyncSession, None]:
    """Provide an explicitly disconnected session to the static repository."""
    async with AsyncSession() as session:
        yield session


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
) -> GenAIModelPricing:
    """Create deterministic generic token pricing for event tests."""
    model = SourceModelRecord(
        id=model_identifier,
        name=model_identifier,
        match=SourceEqualsClause(value=model_identifier),
        context_window=128_000,
        deprecated=False,
        prices=[
            SourcePriceSet(
                constraint=None,
                prices={
                    "input_mtok": SourceScalarPrice(value=Decimal("100000")),
                    "output_mtok": SourceScalarPrice(value=Decimal("200000")),
                    "cache_read_mtok": SourceScalarPrice(value=Decimal("10000")),
                    "cache_write_mtok": SourceScalarPrice(value=Decimal("150000")),
                },
            )
        ],
    )
    source_provider = SourceProviderRecord(
        id=provider.value,
        name=provider.value,
        api_pattern=f"https://{provider.value}.example/.*",
        model_match=None,
        provider_match=None,
        fallback_model_providers=None,
        models=[model],
    )
    return normalize_genai_model_pricing(
        provider=provider,
        model_identifier=model_identifier,
        source_snapshot_id="source-snapshot-1",
        source_hash="source-hash-1",
        source_provider=source_provider,
        source_model=model,
        request_timestamp=datetime.datetime(2026, 10, 1, tzinfo=datetime.UTC),
    )
