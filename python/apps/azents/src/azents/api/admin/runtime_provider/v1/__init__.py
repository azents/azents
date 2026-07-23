"""Runtime Provider inventory v1 Admin API."""

from textwrap import dedent
from typing import Annotated, NoReturn

from fastapi import APIRouter, Depends, HTTPException, status

from azents.services.runtime_provider_admin.service import (
    RuntimeProviderAdminService,
    RuntimeProviderAdminUnavailable,
)
from azents.utils.fastapi.route import RouteMounter

from .data import (
    RuntimeProviderAvailabilityRequest,
    RuntimeProviderListResponse,
    RuntimeProviderPolicyUpdateRequest,
    RuntimeProviderResponse,
)

router = APIRouter()


@router.get("/providers")
async def list_runtime_providers(
    service: Annotated[RuntimeProviderAdminService, Depends()],
) -> RuntimeProviderListResponse:
    """List all durable Runtime Providers for System Admin operations."""
    providers = await service.list_providers()
    return RuntimeProviderListResponse(
        items=[RuntimeProviderResponse.convert_from(provider) for provider in providers]
    )


@router.get("/providers/{provider_id}")
async def get_runtime_provider(
    service: Annotated[RuntimeProviderAdminService, Depends()],
    *,
    provider_id: str,
) -> RuntimeProviderResponse:
    """Inspect one durable Runtime Provider."""
    try:
        provider = await service.get_provider(provider_id)
    except RuntimeProviderAdminUnavailable as error:
        _raise_unavailable(error)
    return RuntimeProviderResponse.convert_from(provider)


@router.patch("/providers/{provider_id}/policy")
async def update_runtime_provider_policy(
    service: Annotated[RuntimeProviderAdminService, Depends()],
    request_body: RuntimeProviderPolicyUpdateRequest,
    *,
    provider_id: str,
) -> RuntimeProviderResponse:
    """Update mutable Provider policy without moving existing Runtimes."""
    try:
        provider = await service.update_policy(
            provider_id,
            enabled=request_body.enabled,
            lifecycle_state=request_body.lifecycle_state,
            availability_mode=request_body.availability_mode,
        )
    except RuntimeProviderAdminUnavailable as error:
        _raise_unavailable(error)
    return RuntimeProviderResponse.convert_from(provider)


@router.put("/providers/{provider_id}/availability")
async def replace_runtime_provider_availability(
    service: Annotated[RuntimeProviderAdminService, Depends()],
    request_body: RuntimeProviderAvailabilityRequest,
    *,
    provider_id: str,
) -> RuntimeProviderResponse:
    """Replace selected-Workspace availability for one Provider."""
    try:
        provider = await service.replace_workspace_availability(
            provider_id,
            workspace_ids=request_body.workspace_ids,
        )
    except RuntimeProviderAdminUnavailable as error:
        _raise_unavailable(error)
    return RuntimeProviderResponse.convert_from(provider)


def _raise_unavailable(error: RuntimeProviderAdminUnavailable) -> NoReturn:
    """Convert service-level Provider failures to API errors."""
    if error.code == "provider_not_found":
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Runtime Provider was not found.",
        ) from None
    raise HTTPException(
        status_code=status.HTTP_409_CONFLICT,
        detail="Runtime Provider operation is unavailable.",
    ) from None


def mount(mounter: RouteMounter) -> None:
    """Mount Runtime Provider inventory routes."""
    mounter(
        router,
        prefix="/runtime-provider/v1",
        tag="Runtime Provider v1",
        description=dedent(
            """
            Runtime Provider API (Admin)

            Inventory and mutable administrative policy for durable Runtime Providers.
            """
        ),
    )
