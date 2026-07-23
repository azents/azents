"""System Settings v1 Admin API."""

from textwrap import dedent
from typing import Annotated, Never

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import ValidationError

from azents.core.auth.deps import SystemAdmin, get_system_admin
from azents.core.system_setting import (
    SystemSettingCandidateExpired,
    SystemSettingCandidateNotFound,
    SystemSettingCandidateNotValidated,
    SystemSettingCandidateReplaced,
    SystemSettingEffectiveGenerationChanged,
    SystemSettingEnvironmentFieldReadOnly,
    SystemSettingImpactChanged,
    SystemSettingSecretAction,
    SystemSettingSection,
    SystemSettingVersionConflict,
)
from azents.services.github_platform_system_setting.service import (
    PlatformGitHubAppSystemSettingService,
)
from azents.services.system_setting.data import (
    SystemSettingMutation,
)
from azents.services.system_setting.service import SystemSettingsService
from azents.utils.fastapi.route import RouteMounter

from .data import (
    ExternalChannelFilesDetailResponse,
    ExternalChannelFilesPatchRequest,
    PlatformGitHubAppConfirmRequest,
    PlatformGitHubAppDetailResponse,
    PlatformGitHubAppPatchRequest,
    SystemSettingAuditEventListResponse,
    SystemSettingAuditEventResponse,
    SystemSettingInventoryItemResponse,
    SystemSettingInventoryResponse,
    SystemSettingVersionConflictResponse,
)

router = APIRouter()

_EXTERNAL_CHANNEL_FILE_LIMIT_FIELDS = (
    "inbound_max_file_bytes",
    "outbound_max_file_bytes",
    "outbound_max_action_bytes",
)


def _raise_system_setting_error(error: Exception) -> Never:
    """Map lifecycle errors to stable sanitized Admin API responses."""
    match error:
        case SystemSettingVersionConflict():
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail={
                    "code": "stale_system_setting_version",
                    "message": "System Settings changed. Reload and try again.",
                    "current_version": error.current_version,
                },
            ) from error
        case SystemSettingEnvironmentFieldReadOnly():
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail={
                    "code": "environment_managed_system_setting_field",
                    "message": "The field is managed by the deployment environment.",
                    "field": error.field_name,
                    "environment_variable": error.environment_variable,
                },
            ) from error
        case SystemSettingCandidateNotFound():
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail={
                    "code": "system_setting_candidate_not_found",
                    "message": "System Settings candidate not found.",
                },
            ) from error
        case SystemSettingCandidateReplaced():
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail={
                    "code": "system_setting_candidate_replaced",
                    "message": "The candidate was replaced. Reload and try again.",
                },
            ) from error
        case SystemSettingCandidateExpired():
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail={
                    "code": "system_setting_candidate_expired",
                    "message": "System Settings candidate expired.",
                },
            ) from error
        case SystemSettingCandidateNotValidated():
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail={
                    "code": "system_setting_candidate_not_validated",
                    "message": "Validate the candidate before confirmation.",
                },
            ) from error
        case SystemSettingEffectiveGenerationChanged():
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail={
                    "code": "candidate_effective_setting_changed",
                    "message": "The effective setting changed. Validate again.",
                },
            ) from error
        case SystemSettingImpactChanged():
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail={
                    "code": "system_setting_impact_changed",
                    "message": "The affected resources changed. Review again.",
                    "impact": error.current_impact,
                },
            ) from error
        case _:
            raise error


@router.get("/sections")
async def list_system_setting_sections(
    service: Annotated[PlatformGitHubAppSystemSettingService, Depends()],
) -> SystemSettingInventoryResponse:
    """List the redacted System Settings inventory."""
    items = await service.list_inventory()
    return SystemSettingInventoryResponse(
        items=[SystemSettingInventoryItemResponse.from_domain(item) for item in items]
    )


@router.get("/sections/external-channel-files")
async def get_external_channel_files_setting(
    service: Annotated[SystemSettingsService, Depends()],
) -> ExternalChannelFilesDetailResponse:
    """Return the effective External Channel file policy."""
    resolved = await service.resolve(SystemSettingSection.EXTERNAL_CHANNEL_FILES)
    return ExternalChannelFilesDetailResponse.from_domain(resolved)


@router.patch(
    "/sections/external-channel-files",
    responses={
        status.HTTP_409_CONFLICT: {
            "model": SystemSettingVersionConflictResponse,
            "description": "The expected System Settings version is stale.",
        }
    },
)
async def patch_external_channel_files_setting(
    request: ExternalChannelFilesPatchRequest,
    system_admin: Annotated[SystemAdmin, Depends(get_system_admin)],
    service: Annotated[SystemSettingsService, Depends()],
) -> ExternalChannelFilesDetailResponse:
    """Directly activate an optimistic External Channel file policy patch."""
    config_patch: dict[str, int] = {}
    for field_name in _EXTERNAL_CHANNEL_FILE_LIMIT_FIELDS:
        if field_name not in request.model_fields_set:
            continue
        value = getattr(request, field_name)
        if value is None:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail={
                    "code": "invalid_system_setting_payload",
                    "message": "External Channel file limits cannot be null.",
                },
            )
        config_patch[field_name] = value
    if not config_patch:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail={
                "code": "empty_system_setting_patch",
                "message": "At least one External Channel file limit is required.",
            },
        )
    try:
        result = await service.mutate(
            SystemSettingMutation(
                section=SystemSettingSection.EXTERNAL_CHANNEL_FILES,
                expected_version=request.expected_version,
                config_patch=config_patch,
                secret_actions={},
                actor_user_id=system_admin.user_id,
            )
        )
    except ValidationError as error:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail={
                "code": "invalid_system_setting_payload",
                "message": "The External Channel file policy is invalid.",
            },
        ) from error
    except SystemSettingVersionConflict as error:
        _raise_system_setting_error(error)
    return ExternalChannelFilesDetailResponse.from_domain(result.resolved)


@router.get("/sections/platform-github-app")
async def get_platform_github_app_setting(
    service: Annotated[PlatformGitHubAppSystemSettingService, Depends()],
) -> PlatformGitHubAppDetailResponse:
    """Return the redacted Platform GitHub App detail."""
    return PlatformGitHubAppDetailResponse.from_domain(await service.get_detail())


@router.patch("/sections/platform-github-app")
async def patch_platform_github_app_setting(
    request: PlatformGitHubAppPatchRequest,
    system_admin: Annotated[SystemAdmin, Depends(get_system_admin)],
    service: Annotated[PlatformGitHubAppSystemSettingService, Depends()],
) -> PlatformGitHubAppDetailResponse:
    """Patch the Admin base and validate the resulting candidate."""
    config_patch = {
        field_name: getattr(request, field_name)
        for field_name in ("app_id", "client_id")
        if field_name in request.model_fields_set
    }
    secret_actions: dict[str, SystemSettingSecretAction] = {}
    for field_name in ("private_key", "client_secret"):
        if field_name not in request.model_fields_set:
            continue
        action = getattr(request, field_name)
        if action is None:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail={
                    "code": "invalid_system_setting_secret_action",
                    "message": "Secret fields require an explicit action object.",
                },
            )
        secret_actions[field_name] = SystemSettingSecretAction(
            action=action.action,
            value=action.value,
        )
    try:
        await service.patch(
            SystemSettingMutation(
                section=SystemSettingSection.PLATFORM_GITHUB_APP,
                expected_version=request.expected_version,
                config_patch=config_patch,
                secret_actions=secret_actions,
                actor_user_id=system_admin.user_id,
            )
        )
    except ValidationError as error:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail={
                "code": "invalid_system_setting_payload",
                "message": "The Platform GitHub App setting is invalid.",
            },
        ) from error
    except (
        SystemSettingVersionConflict,
        SystemSettingEnvironmentFieldReadOnly,
        SystemSettingCandidateNotFound,
        SystemSettingCandidateReplaced,
        SystemSettingCandidateExpired,
        SystemSettingEffectiveGenerationChanged,
    ) as error:
        _raise_system_setting_error(error)
    return PlatformGitHubAppDetailResponse.from_domain(await service.get_detail())


@router.post("/sections/platform-github-app/candidate/validate")
async def validate_platform_github_app_candidate(
    service: Annotated[PlatformGitHubAppSystemSettingService, Depends()],
) -> PlatformGitHubAppDetailResponse:
    """Retry external validation for the current candidate."""
    try:
        await service.retry_candidate_validation()
    except (
        SystemSettingVersionConflict,
        SystemSettingCandidateNotFound,
        SystemSettingCandidateReplaced,
        SystemSettingCandidateExpired,
        SystemSettingEffectiveGenerationChanged,
    ) as error:
        _raise_system_setting_error(error)
    return PlatformGitHubAppDetailResponse.from_domain(await service.get_detail())


@router.post("/sections/platform-github-app/candidate/confirm")
async def confirm_platform_github_app_candidate(
    request: PlatformGitHubAppConfirmRequest,
    system_admin: Annotated[SystemAdmin, Depends(get_system_admin)],
    service: Annotated[PlatformGitHubAppSystemSettingService, Depends()],
) -> PlatformGitHubAppDetailResponse:
    """Confirm unchanged impact and activate a valid candidate."""
    try:
        await service.confirm_candidate(
            candidate_id=request.candidate_id,
            expected_version=request.expected_version,
            confirmation_action=request.confirmation_action,
            actor_user_id=system_admin.user_id,
        )
    except ValueError as error:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail={
                "code": "invalid_system_setting_confirmation_action",
                "message": "The confirmation action is not supported.",
            },
        ) from error
    except (
        SystemSettingVersionConflict,
        SystemSettingCandidateNotFound,
        SystemSettingCandidateExpired,
        SystemSettingCandidateNotValidated,
        SystemSettingEffectiveGenerationChanged,
        SystemSettingImpactChanged,
    ) as error:
        _raise_system_setting_error(error)
    return PlatformGitHubAppDetailResponse.from_domain(await service.get_detail())


@router.delete(
    "/sections/platform-github-app/candidate",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def cancel_platform_github_app_candidate(
    candidate_id: str,
    system_admin: Annotated[SystemAdmin, Depends(get_system_admin)],
    service: Annotated[PlatformGitHubAppSystemSettingService, Depends()],
) -> None:
    """Cancel the current candidate and delete its ciphertext."""
    try:
        await service.cancel_candidate(
            candidate_id=candidate_id,
            actor_user_id=system_admin.user_id,
        )
    except (SystemSettingCandidateNotFound, SystemSettingCandidateExpired) as error:
        _raise_system_setting_error(error)


@router.post("/sections/platform-github-app/health-check")
async def check_platform_github_app_health(
    system_admin: Annotated[SystemAdmin, Depends(get_system_admin)],
    service: Annotated[PlatformGitHubAppSystemSettingService, Depends()],
) -> PlatformGitHubAppDetailResponse:
    """Run an explicit health check for the current effective setting."""
    try:
        detail = await service.check_health(actor_user_id=system_admin.user_id)
    except SystemSettingEffectiveGenerationChanged as error:
        _raise_system_setting_error(error)
    return PlatformGitHubAppDetailResponse.from_domain(detail)


@router.get("/audit-events")
async def list_system_setting_audit_events(
    service: Annotated[PlatformGitHubAppSystemSettingService, Depends()],
    *,
    offset: int = 0,
    limit: int = 50,
) -> SystemSettingAuditEventListResponse:
    """List metadata-only System Settings audit events."""
    page = await service.list_audit_events(offset=offset, limit=limit)
    return SystemSettingAuditEventListResponse(
        items=[
            SystemSettingAuditEventResponse.from_domain(item) for item in page.items
        ],
        total=page.total,
    )


def mount(mounter: RouteMounter) -> None:
    """Mount System Settings v1 Admin routes."""
    mounter(
        router,
        prefix="/system-setting/v1",
        tag="System Settings v1",
        description=dedent(
            """
            System Settings API (Admin)

            Redacted instance-wide operational configuration management.
            """
        ),
    )
