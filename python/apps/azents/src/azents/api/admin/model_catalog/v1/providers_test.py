"""Admin system model catalog provider tests."""

from unittest.mock import AsyncMock, MagicMock

from azents.core.enums import LLMProvider
from azents.services.llm_catalog import (
    SystemCatalogProjectionService,
    SystemCatalogProjectionSummary,
)

from . import refresh_system_model_catalog


async def test_xai_api_key_supports_system_catalog_refresh() -> None:
    """Allow refreshing the stable xAI API key system catalog independently."""
    service = MagicMock(spec=SystemCatalogProjectionService)
    service.sync_system_catalog = AsyncMock(
        return_value=SystemCatalogProjectionSummary(
            provider=LLMProvider.XAI,
            catalog_id="catalog-id",
            snapshot_id="snapshot-id",
            visible_count=1,
            hidden_count=0,
        )
    )

    response = await refresh_system_model_catalog(
        service,
        provider=LLMProvider.XAI,
    )

    service.sync_system_catalog.assert_awaited_once_with(provider=LLMProvider.XAI)
    assert response.provider == LLMProvider.XAI
    assert response.catalog_id == "catalog-id"
