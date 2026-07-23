"""Runtime Provider inventory v1 Admin API."""

from textwrap import dedent
from typing import Annotated, Any, NoReturn

from fastapi import APIRouter, Depends, HTTPException, Query, status

from azents.core.auth.deps import SystemAdmin, get_system_admin
from azents.services.runtime_provider_admin.service import (
    RuntimeProviderAdminService,
    RuntimeProviderAdminUnavailable,
)
from azents.services.runtime_provider_binding_admin.service import (
    RuntimeProviderBindingAdminService,
    RuntimeProviderBindingAdminUnavailable,
)
from azents.utils.fastapi.route import RouteMounter

from .data import (
    RuntimeProviderAuthenticationBindingAuditEventResponse,
    RuntimeProviderAuthenticationBindingAuditListResponse,
    RuntimeProviderAuthenticationBindingCreateRequest,
    RuntimeProviderAuthenticationBindingListResponse,
    RuntimeProviderAuthenticationBindingResponse,
    RuntimeProviderAuthenticationBindingRevokeRequest,
    RuntimeProviderAuthenticationBindingRotateRequest,
    RuntimeProviderAuthenticationBindingRotateResponse,
    RuntimeProviderAvailabilityRequest,
    RuntimeProviderListResponse,
    RuntimeProviderPolicyUpdateRequest,
    RuntimeProviderResponse,
)

router = APIRouter()


@router.get("/providers/{provider_id}/authentication-bindings")
async def list_auth_bindings(
    service: Annotated[RuntimeProviderBindingAdminService, Depends()],
    *,
    provider_id: str,
) -> RuntimeProviderAuthenticationBindingListResponse:
    """List secret-safe authentication bindings for one Provider."""
    try:
        bindings = await service.list_bindings(provider_id)
    except RuntimeProviderBindingAdminUnavailable as error:
        _raise_binding_unavailable(error)
    return RuntimeProviderAuthenticationBindingListResponse(
        items=[
            RuntimeProviderAuthenticationBindingResponse.convert_from(binding)
            for binding in bindings
        ]
    )


@router.post(
    "/providers/{provider_id}/authentication-bindings",
    status_code=status.HTTP_201_CREATED,
)
async def create_auth_binding(
    system_admin: Annotated[SystemAdmin, Depends(get_system_admin)],
    service: Annotated[RuntimeProviderBindingAdminService, Depends()],
    request_body: RuntimeProviderAuthenticationBindingCreateRequest,
    *,
    provider_id: str,
) -> RuntimeProviderAuthenticationBindingResponse:
    """Create one Admin-owned issued-token authentication binding."""
    try:
        binding = await service.create_binding(
            provider_id,
            auth_method=request_body.auth_method,
            subject=request_body.subject,
            config=request_body.config,
            actor_user_id=system_admin.user_id,
        )
    except RuntimeProviderBindingAdminUnavailable as error:
        _raise_binding_unavailable(error)
    return RuntimeProviderAuthenticationBindingResponse.convert_from(binding)


@router.get("/authentication-bindings/{binding_id}")
async def get_auth_binding(
    service: Annotated[RuntimeProviderBindingAdminService, Depends()],
    *,
    binding_id: str,
) -> RuntimeProviderAuthenticationBindingResponse:
    """Inspect one secret-safe authentication binding."""
    try:
        binding = await service.get_binding(binding_id)
    except RuntimeProviderBindingAdminUnavailable as error:
        _raise_binding_unavailable(error)
    return RuntimeProviderAuthenticationBindingResponse.convert_from(binding)


@router.post("/authentication-bindings/{binding_id}/rotate")
async def rotate_auth_binding(
    system_admin: Annotated[SystemAdmin, Depends(get_system_admin)],
    service: Annotated[RuntimeProviderBindingAdminService, Depends()],
    request_body: RuntimeProviderAuthenticationBindingRotateRequest,
    *,
    binding_id: str,
) -> RuntimeProviderAuthenticationBindingRotateResponse:
    """Rotate binding-scoped enrollment authority and return its secret once."""
    try:
        rotation = await service.rotate_binding(
            binding_id,
            expected_admin_version=request_body.expected_admin_version,
            expires_at=request_body.expires_at,
            actor_user_id=system_admin.user_id,
        )
    except RuntimeProviderBindingAdminUnavailable as error:
        _raise_binding_unavailable(error)
    return RuntimeProviderAuthenticationBindingRotateResponse.convert_from(rotation)


@router.post("/authentication-bindings/{binding_id}/revoke")
async def revoke_auth_binding(
    system_admin: Annotated[SystemAdmin, Depends(get_system_admin)],
    service: Annotated[RuntimeProviderBindingAdminService, Depends()],
    request_body: RuntimeProviderAuthenticationBindingRevokeRequest,
    *,
    binding_id: str,
) -> RuntimeProviderAuthenticationBindingResponse:
    """Revoke one binding and all retained Provider authority."""
    try:
        binding = await service.revoke_binding(
            binding_id,
            expected_admin_version=request_body.expected_admin_version,
            reason=request_body.reason,
            actor_user_id=system_admin.user_id,
        )
    except RuntimeProviderBindingAdminUnavailable as error:
        _raise_binding_unavailable(error)
    return RuntimeProviderAuthenticationBindingResponse.convert_from(binding)


@router.get("/authentication-bindings/{binding_id}/audit-events")
async def list_auth_binding_audit_events(
    service: Annotated[RuntimeProviderBindingAdminService, Depends()],
    *,
    binding_id: str,
    offset: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
) -> RuntimeProviderAuthenticationBindingAuditListResponse:
    """List metadata-only binding audit history."""
    try:
        events = await service.list_audit_events(
            binding_id,
            offset=offset,
            limit=limit,
        )
    except RuntimeProviderBindingAdminUnavailable as error:
        _raise_binding_unavailable(error)
    return RuntimeProviderAuthenticationBindingAuditListResponse(
        items=[
            RuntimeProviderAuthenticationBindingAuditEventResponse.convert_from(event)
            for event in events
        ]
    )


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


def _raise_binding_unavailable(
    error: RuntimeProviderBindingAdminUnavailable,
) -> NoReturn:
    """Convert binding lifecycle failures to bounded Admin API errors."""
    if error.code in {"provider_not_found", "binding_not_found"}:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": error.code},
        ) from None
    if error.code in {
        "binding_config_invalid",
        "binding_subject_invalid",
        "grant_expiry_invalid",
    }:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail={"code": error.code},
        ) from None
    detail: dict[str, Any] = {"code": error.code}
    if error.current_binding is not None:
        detail["current_binding"] = (
            RuntimeProviderAuthenticationBindingResponse.convert_from(
                error.current_binding
            ).model_dump(mode="json")
        )
    raise HTTPException(
        status_code=status.HTTP_409_CONFLICT,
        detail=detail,
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
