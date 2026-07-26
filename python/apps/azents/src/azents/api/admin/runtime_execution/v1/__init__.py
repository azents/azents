"""Runtime Execution v1 Admin API."""

from textwrap import dedent
from typing import Annotated, NoReturn

from azcommon.uuid import uuid7
from fastapi import APIRouter, Depends, HTTPException, Query, status

from azents.core.auth.deps import SystemAdmin, get_system_admin
from azents.core.runtime_execution_policy import (
    RuntimeExecutionManagementLayer,
    RuntimeExecutionRestrictionExpansion,
)
from azents.services.runtime_execution_policy.service import (
    RuntimeExecutionPlatformMutation,
    RuntimeExecutionPolicyService,
    RuntimeExecutionPolicyUnavailable,
    RuntimeExecutionPolicyVersionConflict,
    RuntimeExecutionProfileMutation,
)
from azents.utils.fastapi.route import RouteMounter

from .data import (
    RuntimeExecutionManagementCapabilitiesResponse,
    RuntimeExecutionPlatformPolicyReplaceRequest,
    RuntimeExecutionPlatformPolicyResponse,
    RuntimeExecutionPolicyAuditEventResponse,
    RuntimeExecutionPolicyAuditListResponse,
    RuntimeExecutionProfileCreateRequest,
    RuntimeExecutionProfileListResponse,
    RuntimeExecutionProfileReplaceRequest,
    RuntimeExecutionProfileResponse,
    RuntimeExecutionProfileRetireRequest,
)

router = APIRouter()


@router.get("/platform-policy")
async def get_platform_policy(
    service: Annotated[RuntimeExecutionPolicyService, Depends()],
) -> RuntimeExecutionPlatformPolicyResponse:
    """Return the installation-wide execution-policy ceiling."""
    try:
        platform = await service.get_platform()
    except RuntimeExecutionPolicyUnavailable as error:
        _raise_policy_error(error)
    return RuntimeExecutionPlatformPolicyResponse.convert_from(
        platform,
        capabilities=service.get_management_capabilities(),
    )


@router.put("/platform-policy")
async def replace_platform_policy(
    system_admin: Annotated[SystemAdmin, Depends(get_system_admin)],
    service: Annotated[RuntimeExecutionPolicyService, Depends()],
    request_body: RuntimeExecutionPlatformPolicyReplaceRequest,
) -> RuntimeExecutionPlatformPolicyResponse:
    """Replace the Platform execution-policy ceiling."""
    try:
        platform = await service.replace_platform(
            RuntimeExecutionPlatformMutation(
                expected_version=request_body.expected_version,
                policy=request_body.policy,
                actor_user_id=system_admin.user_id,
                correlation_id=uuid7().hex,
            )
        )
    except (
        RuntimeExecutionPolicyUnavailable,
        RuntimeExecutionPolicyVersionConflict,
        RuntimeExecutionRestrictionExpansion,
    ) as error:
        _raise_policy_error(error)
    return RuntimeExecutionPlatformPolicyResponse.convert_from(
        platform,
        capabilities=service.get_management_capabilities(),
    )


@router.get("/profiles")
async def list_profiles(
    service: Annotated[RuntimeExecutionPolicyService, Depends()],
    *,
    include_retired: bool = False,
    offset: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
) -> RuntimeExecutionProfileListResponse:
    """List stable execution Profiles."""
    profiles = await service.list_profiles(
        include_retired=include_retired,
        offset=offset,
        limit=limit,
    )
    return RuntimeExecutionProfileListResponse(
        items=[RuntimeExecutionProfileResponse.convert_from(item) for item in profiles],
        capabilities=(
            RuntimeExecutionManagementCapabilitiesResponse.convert_from(
                service.get_management_capabilities()
            )
        ),
    )


@router.post("/profiles", status_code=status.HTTP_201_CREATED)
async def create_profile(
    system_admin: Annotated[SystemAdmin, Depends(get_system_admin)],
    service: Annotated[RuntimeExecutionPolicyService, Depends()],
    request_body: RuntimeExecutionProfileCreateRequest,
) -> RuntimeExecutionProfileResponse:
    """Create one ordinary active execution Profile."""
    try:
        profile = await service.create_profile(
            profile_id=request_body.profile_id,
            display_name=request_body.display_name,
            description=request_body.description,
            policy=request_body.policy,
            actor_user_id=system_admin.user_id,
            correlation_id=uuid7().hex,
        )
    except (
        RuntimeExecutionPolicyUnavailable,
        RuntimeExecutionRestrictionExpansion,
    ) as error:
        _raise_policy_error(error)
    return RuntimeExecutionProfileResponse.convert_from(profile)


@router.get("/profiles/{profile_id}")
async def get_profile(
    service: Annotated[RuntimeExecutionPolicyService, Depends()],
    *,
    profile_id: str,
) -> RuntimeExecutionProfileResponse:
    """Return one stable execution Profile."""
    try:
        profile = await service.get_profile(profile_id)
    except RuntimeExecutionPolicyUnavailable as error:
        _raise_policy_error(error)
    return RuntimeExecutionProfileResponse.convert_from(profile)


@router.put("/profiles/{profile_id}")
async def replace_profile(
    system_admin: Annotated[SystemAdmin, Depends(get_system_admin)],
    service: Annotated[RuntimeExecutionPolicyService, Depends()],
    request_body: RuntimeExecutionProfileReplaceRequest,
    *,
    profile_id: str,
) -> RuntimeExecutionProfileResponse:
    """Replace Profile metadata and policy content."""
    try:
        profile = await service.replace_profile(
            profile_id,
            RuntimeExecutionProfileMutation(
                expected_version=request_body.expected_version,
                display_name=request_body.display_name,
                description=request_body.description,
                policy=request_body.policy,
                actor_user_id=system_admin.user_id,
                correlation_id=uuid7().hex,
            ),
        )
    except (
        RuntimeExecutionPolicyUnavailable,
        RuntimeExecutionPolicyVersionConflict,
        RuntimeExecutionRestrictionExpansion,
    ) as error:
        _raise_policy_error(error)
    return RuntimeExecutionProfileResponse.convert_from(profile)


@router.post("/profiles/{profile_id}/retire")
async def retire_profile(
    system_admin: Annotated[SystemAdmin, Depends(get_system_admin)],
    service: Annotated[RuntimeExecutionPolicyService, Depends()],
    request_body: RuntimeExecutionProfileRetireRequest,
    *,
    profile_id: str,
) -> RuntimeExecutionProfileResponse:
    """Retire one ordinary Profile."""
    try:
        profile = await service.retire_profile(
            profile_id,
            expected_version=request_body.expected_version,
            actor_user_id=system_admin.user_id,
            correlation_id=uuid7().hex,
        )
    except (
        RuntimeExecutionPolicyUnavailable,
        RuntimeExecutionPolicyVersionConflict,
    ) as error:
        _raise_policy_error(error)
    return RuntimeExecutionProfileResponse.convert_from(profile)


@router.get("/audit-events")
async def list_audit_events(
    service: Annotated[RuntimeExecutionPolicyService, Depends()],
    *,
    management_layer: RuntimeExecutionManagementLayer | None = None,
    target_id: str | None = None,
    workspace_id: str | None = None,
    agent_id: str | None = None,
    offset: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
) -> RuntimeExecutionPolicyAuditListResponse:
    """List metadata-only execution-policy audit history."""
    events = await service.list_admin_audit_events(
        management_layer=management_layer,
        target_id=target_id,
        workspace_id=workspace_id,
        agent_id=agent_id,
        offset=offset,
        limit=limit,
    )
    return RuntimeExecutionPolicyAuditListResponse(
        items=[
            RuntimeExecutionPolicyAuditEventResponse.convert_from(event)
            for event in events
        ]
    )


def _raise_policy_error(error: Exception) -> NoReturn:
    """Map bounded execution-policy failures to safe Admin responses."""
    if isinstance(error, RuntimeExecutionPolicyVersionConflict):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "stale_execution_policy_version",
                "current_version": error.current_version,
            },
        ) from error
    if isinstance(error, RuntimeExecutionRestrictionExpansion):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "execution_policy_expansion_rejected",
                "path": error.path,
                "governing_layer": error.governing_layer.value,
            },
        ) from error
    if isinstance(error, RuntimeExecutionPolicyUnavailable):
        status_code = (
            status.HTTP_404_NOT_FOUND
            if error.code in {"platform_policy_missing", "profile_not_found"}
            else status.HTTP_409_CONFLICT
        )
        raise HTTPException(
            status_code=status_code,
            detail={"code": error.code},
        ) from error
    raise error


def mount(mounter: RouteMounter) -> None:
    """Mount Runtime Execution Admin routes."""
    mounter(
        router,
        prefix="/runtime-execution/v1",
        tag="Runtime Execution v1",
        description=dedent(
            """
            Runtime Execution API (Admin)

            Platform execution-policy and reusable Profile management.
            """
        ),
    )
