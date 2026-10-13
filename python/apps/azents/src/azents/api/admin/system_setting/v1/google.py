"""Google operator preparation under existing Admin System Settings authority."""

from typing import Annotated, Never

from fastapi import APIRouter, Depends, HTTPException
from pydantic import Field, ValidationError
from typing_extensions import Required, TypedDict

from azents.core.auth.deps import SystemAdmin, get_system_admin
from azents.core.google_system_setting import (
    GoogleApplicationConfigPatch,
    GoogleApplicationDetail,
)
from azents.core.system_setting import (
    SystemSettingEnvironmentFieldReadOnly,
    SystemSettingSecretAction,
    SystemSettingVersionConflict,
)
from azents.services.google_application.service import GoogleApplicationService

from .data import SystemSettingSecretActionRequest

router = APIRouter()
Application = Annotated[GoogleApplicationService, Depends()]


class GoogleApplicationPatchRequest(TypedDict, total=False, closed=True):
    """Partial local preparation with explicit secret replace/clear actions."""

    expected_version: Required[Annotated[int, Field(ge=0, strict=True)]]
    client_id: str | None
    client_secret: SystemSettingSecretActionRequest


def _setting_error(
    error: SystemSettingVersionConflict | SystemSettingEnvironmentFieldReadOnly,
) -> Never:
    if isinstance(error, SystemSettingVersionConflict):
        raise HTTPException(
            409,
            detail={
                "code": "stale_system_setting_version",
                "message": "System Settings changed. Reload and try again.",
                "current_version": error.current_version,
            },
        ) from None
    raise HTTPException(
        409,
        detail={
            "code": "environment_managed_system_setting_field",
            "message": "The field is managed by the deployment environment.",
            "field": error.field_name,
            "environment_variable": error.environment_variable,
        },
    ) from None


@router.get("/sections/google-oauth")
async def get_google_oauth_setting(
    service: Application,
    system_admin: Annotated[SystemAdmin, Depends(get_system_admin)],
) -> GoogleApplicationDetail:
    """Describe current local preparation without secrets or false live health."""
    del system_admin
    return await service.detail()


@router.patch("/sections/google-oauth")
async def patch_google_oauth_setting(
    service: Application,
    system_admin: Annotated[SystemAdmin, Depends(get_system_admin)],
    request: GoogleApplicationPatchRequest,
) -> GoogleApplicationDetail:
    """Directly activate a version-fenced operator registration mutation."""
    patch: GoogleApplicationConfigPatch = {}
    if "client_id" in request:
        patch["client_id"] = request["client_id"]
    action = request.get("client_secret")
    if not patch and action is None:
        raise HTTPException(
            422,
            detail={
                "code": "empty_system_setting_patch",
                "message": "At least one Google application field is required.",
            },
        )
    try:
        return await service.patch(
            expected_version=request["expected_version"],
            config_patch=patch,
            secret_action=None
            if action is None
            else SystemSettingSecretAction(
                action=action.action,
                value=action.value,
            ),
            actor_user_id=system_admin.user_id,
        )
    except (
        SystemSettingVersionConflict,
        SystemSettingEnvironmentFieldReadOnly,
    ) as error:
        _setting_error(error)
    except ValidationError:
        raise HTTPException(
            422,
            detail={
                "code": "invalid_system_setting_payload",
                "message": "The Google application configuration is invalid.",
            },
        ) from None
