"""Runtime Provider inventory v1 Admin API."""

from textwrap import dedent
from typing import Annotated, Any, NoReturn

from fastapi import APIRouter, Depends, HTTPException, Query, status

from azents.api.runtime_recreation import (
    RuntimeRecreationCreateRequest,
    RuntimeRecreationOperationResponse,
)
from azents.core.auth.deps import SystemAdmin, get_system_admin
from azents.core.runtime_profile import RuntimeInfrastructureProfileKind
from azents.services.runtime_profile_admin.service import (
    RuntimeProfileAdminService,
    RuntimeProfileAdminUnavailable,
)
from azents.services.runtime_provider_admin.service import (
    RuntimeProviderAdminService,
    RuntimeProviderAdminUnavailable,
)
from azents.services.runtime_provider_binding_admin.service import (
    RuntimeProviderBindingAdminService,
    RuntimeProviderBindingAdminUnavailable,
)
from azents.services.runtime_provider_contract.service import (
    RuntimeProviderContractService,
    RuntimeProviderContractUnavailable,
)
from azents.services.runtime_recreation.service import (
    RuntimeRecreationService,
    RuntimeRecreationUnavailable,
)
from azents.utils.fastapi.route import RouteMounter

from .data import (
    AdminWorkspaceRuntimeProfileDetailResponse,
    RuntimeInfrastructureProfileCreateRequest,
    RuntimeInfrastructureProfileDeleteRequest,
    RuntimeInfrastructureProfileDeleteResponse,
    RuntimeInfrastructureProfileDeletionImpactResponse,
    RuntimeInfrastructureProfileListResponse,
    RuntimeInfrastructureProfileReplaceRequest,
    RuntimeInfrastructureProfileResponse,
    RuntimeProviderAuthenticationBindingAuditEventResponse,
    RuntimeProviderAuthenticationBindingAuditListResponse,
    RuntimeProviderAuthenticationBindingCreateRequest,
    RuntimeProviderAuthenticationBindingListResponse,
    RuntimeProviderAuthenticationBindingResponse,
    RuntimeProviderAuthenticationBindingRevokeRequest,
    RuntimeProviderAuthenticationBindingRotateRequest,
    RuntimeProviderAuthenticationBindingRotateResponse,
    RuntimeProviderAvailabilityRequest,
    RuntimeProviderContractListResponse,
    RuntimeProviderContractResponse,
    RuntimeProviderListResponse,
    RuntimeProviderOperationalDiagnosticsResponse,
    RuntimeProviderPolicyUpdateRequest,
    RuntimeProviderResponse,
)

router = APIRouter()


async def _list_infrastructure_profiles(
    service: RuntimeProfileAdminService,
    *,
    provider_id: str,
    profile_kind: RuntimeInfrastructureProfileKind,
    include_disabled: bool,
) -> RuntimeInfrastructureProfileListResponse:
    try:
        profiles = await service.list_profiles(
            provider_id,
            profile_kind=profile_kind,
            include_disabled=include_disabled,
        )
    except RuntimeProfileAdminUnavailable as error:
        _raise_profile_unavailable(error)
    return RuntimeInfrastructureProfileListResponse(
        items=[
            RuntimeInfrastructureProfileResponse.convert_from(profile)
            for profile in profiles
        ]
    )


async def _get_infrastructure_profile_deletion_impact(
    service: RuntimeProfileAdminService,
    *,
    provider_id: str,
    profile_id: str,
    profile_kind: RuntimeInfrastructureProfileKind,
    offset: int,
    limit: int,
) -> RuntimeInfrastructureProfileDeletionImpactResponse:
    try:
        impact = await service.get_profile_deletion_impact(
            provider_id,
            profile_id,
            profile_kind=profile_kind,
            offset=offset,
            limit=limit,
        )
    except RuntimeProfileAdminUnavailable as error:
        _raise_profile_unavailable(error)
    return RuntimeInfrastructureProfileDeletionImpactResponse.convert_from(impact)


async def _delete_infrastructure_profile(
    system_admin: SystemAdmin,
    service: RuntimeProfileAdminService,
    request_body: RuntimeInfrastructureProfileDeleteRequest,
    *,
    provider_id: str,
    profile_id: str,
    profile_kind: RuntimeInfrastructureProfileKind,
) -> RuntimeInfrastructureProfileDeleteResponse:
    try:
        deletion = await service.delete_profile(
            provider_id,
            profile_id,
            profile_kind=profile_kind,
            expected_version=request_body.expected_version,
            actor_user_id=system_admin.user_id,
        )
    except RuntimeProfileAdminUnavailable as error:
        _raise_profile_unavailable(error)
    return RuntimeInfrastructureProfileDeleteResponse(
        profile_id=deletion.profile_id,
        superseded_recreation_operation_count=(
            deletion.superseded_recreation_operation_count
        ),
        skipped_recreation_item_count=deletion.skipped_recreation_item_count,
    )


@router.get("/providers/{provider_id}/pod-profiles")
async def list_pod_profiles(
    service: Annotated[RuntimeProfileAdminService, Depends()],
    *,
    provider_id: str,
    include_disabled: bool = False,
) -> RuntimeInfrastructureProfileListResponse:
    """List typed Pod Profiles owned by one Kubernetes Provider."""
    return await _list_infrastructure_profiles(
        service,
        provider_id=provider_id,
        profile_kind=RuntimeInfrastructureProfileKind.KUBERNETES_POD,
        include_disabled=include_disabled,
    )


@router.get("/providers/{provider_id}/container-profiles")
async def list_container_profiles(
    service: Annotated[RuntimeProfileAdminService, Depends()],
    *,
    provider_id: str,
    include_disabled: bool = False,
) -> RuntimeInfrastructureProfileListResponse:
    """List typed Container Profiles owned by one Docker Provider."""
    return await _list_infrastructure_profiles(
        service,
        provider_id=provider_id,
        profile_kind=RuntimeInfrastructureProfileKind.DOCKER_CONTAINER,
        include_disabled=include_disabled,
    )


@router.post(
    "/providers/{provider_id}/pod-profiles",
    status_code=status.HTTP_201_CREATED,
)
async def create_pod_profile(
    system_admin: Annotated[SystemAdmin, Depends(get_system_admin)],
    service: Annotated[RuntimeProfileAdminService, Depends()],
    request_body: RuntimeInfrastructureProfileCreateRequest,
    *,
    provider_id: str,
) -> RuntimeInfrastructureProfileResponse:
    """Create one typed infrastructure Profile under one Provider."""
    try:
        profile = await service.create_profile(
            provider_id,
            profile_kind=RuntimeInfrastructureProfileKind.KUBERNETES_POD,
            display_name=request_body.display_name,
            description=request_body.description,
            lifecycle=request_body.lifecycle,
            spec=request_body.spec,
            actor_user_id=system_admin.user_id,
        )
    except RuntimeProfileAdminUnavailable as error:
        _raise_profile_unavailable(error)
    return RuntimeInfrastructureProfileResponse.convert_from(profile)


@router.post(
    "/providers/{provider_id}/container-profiles",
    status_code=status.HTTP_201_CREATED,
)
async def create_container_profile(
    system_admin: Annotated[SystemAdmin, Depends(get_system_admin)],
    service: Annotated[RuntimeProfileAdminService, Depends()],
    request_body: RuntimeInfrastructureProfileCreateRequest,
    *,
    provider_id: str,
) -> RuntimeInfrastructureProfileResponse:
    """Create one typed Container Profile under one Docker Provider."""
    try:
        profile = await service.create_profile(
            provider_id,
            profile_kind=RuntimeInfrastructureProfileKind.DOCKER_CONTAINER,
            display_name=request_body.display_name,
            description=request_body.description,
            lifecycle=request_body.lifecycle,
            spec=request_body.spec,
            actor_user_id=system_admin.user_id,
        )
    except RuntimeProfileAdminUnavailable as error:
        _raise_profile_unavailable(error)
    return RuntimeInfrastructureProfileResponse.convert_from(profile)


@router.get("/providers/{provider_id}/pod-profiles/{profile_id}")
async def get_pod_profile(
    service: Annotated[RuntimeProfileAdminService, Depends()],
    *,
    provider_id: str,
    profile_id: str,
) -> RuntimeInfrastructureProfileResponse:
    """Inspect one exact Provider-owned infrastructure Profile."""
    try:
        profile = await service.get_profile(
            provider_id,
            profile_id,
            profile_kind=RuntimeInfrastructureProfileKind.KUBERNETES_POD,
        )
    except RuntimeProfileAdminUnavailable as error:
        _raise_profile_unavailable(error)
    return RuntimeInfrastructureProfileResponse.convert_from(profile)


@router.get("/providers/{provider_id}/container-profiles/{profile_id}")
async def get_container_profile(
    service: Annotated[RuntimeProfileAdminService, Depends()],
    *,
    provider_id: str,
    profile_id: str,
) -> RuntimeInfrastructureProfileResponse:
    """Inspect one exact Docker Provider-owned Container Profile."""
    try:
        profile = await service.get_profile(
            provider_id,
            profile_id,
            profile_kind=RuntimeInfrastructureProfileKind.DOCKER_CONTAINER,
        )
    except RuntimeProfileAdminUnavailable as error:
        _raise_profile_unavailable(error)
    return RuntimeInfrastructureProfileResponse.convert_from(profile)


@router.get("/providers/{provider_id}/pod-profiles/{profile_id}/deletion-impact")
async def get_pod_profile_deletion_impact(
    service: Annotated[RuntimeProfileAdminService, Depends()],
    *,
    provider_id: str,
    profile_id: str,
    offset: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
) -> RuntimeInfrastructureProfileDeletionImpactResponse:
    """Preview current references before deleting one Pod Profile."""
    return await _get_infrastructure_profile_deletion_impact(
        service,
        provider_id=provider_id,
        profile_id=profile_id,
        profile_kind=RuntimeInfrastructureProfileKind.KUBERNETES_POD,
        offset=offset,
        limit=limit,
    )


@router.get("/providers/{provider_id}/container-profiles/{profile_id}/deletion-impact")
async def get_container_profile_deletion_impact(
    service: Annotated[RuntimeProfileAdminService, Depends()],
    *,
    provider_id: str,
    profile_id: str,
    offset: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
) -> RuntimeInfrastructureProfileDeletionImpactResponse:
    """Preview current references before deleting one Container Profile."""
    return await _get_infrastructure_profile_deletion_impact(
        service,
        provider_id=provider_id,
        profile_id=profile_id,
        profile_kind=RuntimeInfrastructureProfileKind.DOCKER_CONTAINER,
        offset=offset,
        limit=limit,
    )


@router.delete("/providers/{provider_id}/pod-profiles/{profile_id}")
async def delete_pod_profile(
    system_admin: Annotated[SystemAdmin, Depends(get_system_admin)],
    service: Annotated[RuntimeProfileAdminService, Depends()],
    request_body: RuntimeInfrastructureProfileDeleteRequest,
    *,
    provider_id: str,
    profile_id: str,
) -> RuntimeInfrastructureProfileDeleteResponse:
    """Permanently delete one exact unreferenced Pod Profile."""
    return await _delete_infrastructure_profile(
        system_admin,
        service,
        request_body,
        provider_id=provider_id,
        profile_id=profile_id,
        profile_kind=RuntimeInfrastructureProfileKind.KUBERNETES_POD,
    )


@router.delete("/providers/{provider_id}/container-profiles/{profile_id}")
async def delete_container_profile(
    system_admin: Annotated[SystemAdmin, Depends(get_system_admin)],
    service: Annotated[RuntimeProfileAdminService, Depends()],
    request_body: RuntimeInfrastructureProfileDeleteRequest,
    *,
    provider_id: str,
    profile_id: str,
) -> RuntimeInfrastructureProfileDeleteResponse:
    """Permanently delete one exact unreferenced Container Profile."""
    return await _delete_infrastructure_profile(
        system_admin,
        service,
        request_body,
        provider_id=provider_id,
        profile_id=profile_id,
        profile_kind=RuntimeInfrastructureProfileKind.DOCKER_CONTAINER,
    )


@router.get("/workspaces/{handle}/runtime-profiles/{profile_id}")
async def get_workspace_profile_admin_detail(
    service: Annotated[RuntimeProfileAdminService, Depends()],
    *,
    handle: str,
    profile_id: str,
) -> AdminWorkspaceRuntimeProfileDetailResponse:
    """Inspect one Workspace Runtime Profile with System Admin authority."""
    try:
        detail = await service.get_workspace_profile_admin_detail(handle, profile_id)
    except RuntimeProfileAdminUnavailable as error:
        _raise_profile_unavailable(error)
    return AdminWorkspaceRuntimeProfileDetailResponse.convert_from(detail)


@router.put("/providers/{provider_id}/pod-profiles/{profile_id}")
async def replace_pod_profile(
    system_admin: Annotated[SystemAdmin, Depends(get_system_admin)],
    service: Annotated[RuntimeProfileAdminService, Depends()],
    request_body: RuntimeInfrastructureProfileReplaceRequest,
    *,
    provider_id: str,
    profile_id: str,
) -> RuntimeInfrastructureProfileResponse:
    """Replace one infrastructure Profile with optimistic version fencing."""
    try:
        profile = await service.replace_profile(
            provider_id,
            profile_id,
            profile_kind=RuntimeInfrastructureProfileKind.KUBERNETES_POD,
            expected_version=request_body.expected_version,
            display_name=request_body.display_name,
            description=request_body.description,
            lifecycle=request_body.lifecycle,
            spec=request_body.spec,
            actor_user_id=system_admin.user_id,
        )
    except RuntimeProfileAdminUnavailable as error:
        _raise_profile_unavailable(error)
    return RuntimeInfrastructureProfileResponse.convert_from(profile)


@router.put("/providers/{provider_id}/container-profiles/{profile_id}")
async def replace_container_profile(
    system_admin: Annotated[SystemAdmin, Depends(get_system_admin)],
    service: Annotated[RuntimeProfileAdminService, Depends()],
    request_body: RuntimeInfrastructureProfileReplaceRequest,
    *,
    provider_id: str,
    profile_id: str,
) -> RuntimeInfrastructureProfileResponse:
    """Replace one Container Profile with optimistic version fencing."""
    try:
        profile = await service.replace_profile(
            provider_id,
            profile_id,
            profile_kind=RuntimeInfrastructureProfileKind.DOCKER_CONTAINER,
            expected_version=request_body.expected_version,
            display_name=request_body.display_name,
            description=request_body.description,
            lifecycle=request_body.lifecycle,
            spec=request_body.spec,
            actor_user_id=system_admin.user_id,
        )
    except RuntimeProfileAdminUnavailable as error:
        _raise_profile_unavailable(error)
    return RuntimeInfrastructureProfileResponse.convert_from(profile)


async def _create_infrastructure_profile_recreation(
    system_admin: SystemAdmin,
    service: RuntimeRecreationService,
    request_body: RuntimeRecreationCreateRequest,
    *,
    provider_id: str,
    profile_id: str,
    profile_kind: RuntimeInfrastructureProfileKind,
) -> RuntimeRecreationOperationResponse:
    try:
        operation = await service.create_infrastructure_profile_operation(
            provider_id,
            profile_id,
            profile_kind=profile_kind,
            expected_version=request_body.expected_version,
            concurrency_limit=request_body.concurrency_limit,
            actor_user_id=system_admin.user_id,
        )
    except RuntimeRecreationUnavailable as error:
        _raise_recreation_unavailable(error)
    return RuntimeRecreationOperationResponse.convert_operation(operation)


@router.post(
    "/providers/{provider_id}/pod-profiles/{profile_id}/recreation-operations",
    status_code=status.HTTP_201_CREATED,
)
async def create_pod_profile_recreation(
    system_admin: Annotated[SystemAdmin, Depends(get_system_admin)],
    service: Annotated[RuntimeRecreationService, Depends()],
    request_body: RuntimeRecreationCreateRequest,
    *,
    provider_id: str,
    profile_id: str,
) -> RuntimeRecreationOperationResponse:
    """Start bounded recreation for one Kubernetes Pod Profile."""
    return await _create_infrastructure_profile_recreation(
        system_admin,
        service,
        request_body,
        provider_id=provider_id,
        profile_id=profile_id,
        profile_kind=RuntimeInfrastructureProfileKind.KUBERNETES_POD,
    )


@router.post(
    "/providers/{provider_id}/container-profiles/{profile_id}/recreation-operations",
    status_code=status.HTTP_201_CREATED,
)
async def create_container_profile_recreation(
    system_admin: Annotated[SystemAdmin, Depends(get_system_admin)],
    service: Annotated[RuntimeRecreationService, Depends()],
    request_body: RuntimeRecreationCreateRequest,
    *,
    provider_id: str,
    profile_id: str,
) -> RuntimeRecreationOperationResponse:
    """Start bounded recreation for one Docker Container Profile."""
    return await _create_infrastructure_profile_recreation(
        system_admin,
        service,
        request_body,
        provider_id=provider_id,
        profile_id=profile_id,
        profile_kind=RuntimeInfrastructureProfileKind.DOCKER_CONTAINER,
    )


@router.post(
    "/providers/{provider_id}/recreation-operations",
    status_code=status.HTTP_201_CREATED,
)
async def create_provider_recreation(
    system_admin: Annotated[SystemAdmin, Depends(get_system_admin)],
    service: Annotated[RuntimeRecreationService, Depends()],
    request_body: RuntimeRecreationCreateRequest,
    *,
    provider_id: str,
) -> RuntimeRecreationOperationResponse:
    """Start bounded recreation for one exact Runtime Provider."""
    try:
        operation = await service.create_provider_operation(
            provider_id,
            expected_admin_version=request_body.expected_version,
            concurrency_limit=request_body.concurrency_limit,
            actor_user_id=system_admin.user_id,
        )
    except RuntimeRecreationUnavailable as error:
        _raise_recreation_unavailable(error)
    return RuntimeRecreationOperationResponse.convert_operation(operation)


@router.get("/recreation-operations/{operation_id}")
async def get_platform_recreation(
    service: Annotated[RuntimeRecreationService, Depends()],
    *,
    operation_id: str,
    offset: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
) -> RuntimeRecreationOperationResponse:
    """Read Platform-scoped recreation progress and bounded failures."""
    try:
        projection = await service.get_platform_operation(
            operation_id,
            offset=offset,
            limit=limit,
        )
    except RuntimeRecreationUnavailable as error:
        _raise_recreation_unavailable(error)
    return RuntimeRecreationOperationResponse.convert_projection(projection)


@router.get("/providers/{provider_id}/contracts")
async def list_contracts(
    service: Annotated[RuntimeProviderContractService, Depends()],
    *,
    provider_id: str,
) -> RuntimeProviderContractListResponse:
    """List immutable Provider capability advertisement history."""
    try:
        contracts = await service.list_contracts(provider_id)
    except RuntimeProviderContractUnavailable as error:
        _raise_contract_unavailable(error)
    return RuntimeProviderContractListResponse(
        items=[RuntimeProviderContractResponse.convert_from(item) for item in contracts]
    )


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


@router.get("/providers/{provider_id}/operational-diagnostics")
async def get_provider_diagnostics(
    service: Annotated[RuntimeProviderAdminService, Depends()],
    *,
    provider_id: str,
) -> RuntimeProviderOperationalDiagnosticsResponse:
    """Inspect warning-only diagnostics from the active Provider connection."""
    try:
        projection = await service.get_operational_diagnostics(provider_id)
    except RuntimeProviderAdminUnavailable as error:
        _raise_unavailable(error)
    return RuntimeProviderOperationalDiagnosticsResponse.convert_from(projection)


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


def _raise_profile_unavailable(
    error: RuntimeProfileAdminUnavailable,
) -> NoReturn:
    """Convert infrastructure Profile failures to bounded Admin API errors."""
    if error.code in {
        "provider_not_found",
        "profile_not_found",
        "workspace_profile_not_found",
    }:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": error.code},
        ) from None
    if error.code in {"profile_kind_mismatch", "profile_document_invalid"}:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail={"code": error.code},
        ) from None
    detail: dict[str, Any] = {"code": error.code}
    if error.current_profile is not None:
        detail["current_version"] = error.current_profile.version
    if error.blocking_reference_count is not None:
        detail["blocking_reference_count"] = error.blocking_reference_count
    raise HTTPException(
        status_code=status.HTTP_409_CONFLICT,
        detail=detail,
    ) from None


def _raise_recreation_unavailable(
    error: RuntimeRecreationUnavailable,
) -> NoReturn:
    """Convert scoped recreation failures to bounded Admin API errors."""
    if error.code in {
        "provider_not_found",
        "profile_not_found",
        "operation_not_found",
    }:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": error.code},
        ) from None
    if error.code == "profile_kind_mismatch":
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail={"code": error.code},
        ) from None
    detail: dict[str, object] = {"code": error.code}
    if error.current_version is not None:
        detail["current_version"] = error.current_version
    raise HTTPException(
        status_code=status.HTTP_409_CONFLICT,
        detail=detail,
    ) from None


def _raise_contract_unavailable(
    error: RuntimeProviderContractUnavailable,
) -> NoReturn:
    """Convert contract lifecycle failures to bounded Admin API errors."""
    if error.code == "provider_not_found":
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": error.code},
        ) from None
    if error.code == "contract_invalid":
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail={"code": error.code},
        ) from None
    raise HTTPException(
        status_code=status.HTTP_409_CONFLICT,
        detail={
            "code": error.code,
            "current_admin_version": error.current_admin_version,
        },
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
