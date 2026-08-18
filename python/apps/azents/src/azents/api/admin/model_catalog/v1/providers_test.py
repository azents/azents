"""Admin system model catalog provider tests."""

from unittest.mock import AsyncMock, MagicMock

from azents.core.enums import LLMProvider
from azents.services.llm_catalog import (
    SystemCatalogProjectionService,
    SystemCatalogProjectionSummary,
)

from . import refresh_system_model_catalog
from .data import SystemCatalogProvider


async def test_anthropic_supports_system_catalog_refresh() -> None:
    """Allow refreshing a system-owned provider catalog independently."""
    service = MagicMock(spec=SystemCatalogProjectionService)
    service.sync_system_catalog = AsyncMock(
        return_value=SystemCatalogProjectionSummary(
            provider=LLMProvider.ANTHROPIC,
            catalog_id="catalog-id",
            snapshot_id="snapshot-id",
            visible_count=1,
            hidden_count=0,
        )
    )

    response = await refresh_system_model_catalog(
        service,
        provider=SystemCatalogProvider.ANTHROPIC,
    )

    service.sync_system_catalog.assert_awaited_once_with(provider=LLMProvider.ANTHROPIC)
    assert response.provider == SystemCatalogProvider.ANTHROPIC
    assert response.catalog_id == "catalog-id"
