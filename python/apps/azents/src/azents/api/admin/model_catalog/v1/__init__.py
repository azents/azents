"""Model catalog v1 Admin API.

Provides operational controls for system-owned model catalog projections.
"""

from textwrap import dedent
from typing import Annotated

from fastapi import APIRouter, Depends

from azents.services.llm_catalog import SystemCatalogProjectionService
from azents.utils.fastapi.route import RouteMounter

from .data import (
    SystemCatalogProvider,
    SystemModelCatalogListResponse,
    SystemModelCatalogRefreshListResponse,
    SystemModelCatalogRefreshResponse,
    SystemModelCatalogResponse,
)

router = APIRouter()


@router.get("/system-catalogs")
async def list_system_model_catalogs(
    service: Annotated[SystemCatalogProjectionService, Depends()],
) -> SystemModelCatalogListResponse:
    """List supported system model catalogs."""
    items = await service.list_system_catalogs()
    return SystemModelCatalogListResponse(
        items=[SystemModelCatalogResponse.convert_from(item) for item in items]
    )


@router.post("/system-catalogs/refresh")
async def refresh_system_model_catalogs(
    service: Annotated[SystemCatalogProjectionService, Depends()],
) -> SystemModelCatalogRefreshListResponse:
    """Refresh all system model catalog projections."""
    summaries = await service.sync_system_catalogs()
    return SystemModelCatalogRefreshListResponse(
        items=[
            SystemModelCatalogRefreshResponse.convert_from(item) for item in summaries
        ]
    )


@router.post("/system-catalogs/{provider}/refresh")
async def refresh_system_model_catalog(
    service: Annotated[SystemCatalogProjectionService, Depends()],
    *,
    provider: SystemCatalogProvider,
) -> SystemModelCatalogRefreshResponse:
    """Refresh one system model catalog projection by provider."""
    summary = await service.sync_system_catalog(provider=provider.to_llm_provider())
    return SystemModelCatalogRefreshResponse.convert_from(summary)


def mount(mounter: RouteMounter) -> None:
    """Mount Model Catalog v1 routes."""
    mounter(
        router,
        prefix="/model-catalog/v1",
        tag="Model Catalog v1",
        description=dedent(
            """
            Model Catalog API (Admin)

            Operational controls for system-owned model catalog refresh.
            """
        ),
    )
