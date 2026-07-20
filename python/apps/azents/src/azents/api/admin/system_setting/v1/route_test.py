"""System Settings Admin API route tests."""

from typing import Any, cast
from unittest.mock import AsyncMock, Mock

import pytest
from fastapi import HTTPException

from azents.core.auth.deps import SystemAdmin
from azents.core.system_setting import (
    SystemSettingCandidateReplaced,
    SystemSettingEnvironmentFieldReadOnly,
    SystemSettingFieldSource,
    SystemSettingSection,
    SystemSettingVersionConflict,
)
from azents.services.github_platform_system_setting.data import (
    PlatformGitHubAppDetail,
    PlatformGitHubAppEffectiveStatus,
    PlatformGitHubAppFieldState,
)
from azents.services.github_platform_system_setting.service import (
    PlatformGitHubAppSystemSettingService,
)

from . import patch_platform_github_app_setting
from .data import (
    PlatformGitHubAppDetailResponse,
    PlatformGitHubAppPatchRequest,
)


def _admin() -> SystemAdmin:
    return SystemAdmin(user_id="admin-1", session_id="session-1")


def _detail() -> PlatformGitHubAppDetail:
    return PlatformGitHubAppDetail(
        section="platform_github_app",
        schema_version=1,
        admin_version=0,
        effective_status=PlatformGitHubAppEffectiveStatus.INCOMPLETE,
        fields=(
            PlatformGitHubAppFieldState(
                name="app_id",
                secret=False,
                value="123",
                configured=True,
                source=SystemSettingFieldSource.ADMIN,
                environment_variable="AZ_GITHUB_PLATFORM_APP_ID",
                fallback_configured=True,
                fallback_last_changed_at=None,
            ),
            PlatformGitHubAppFieldState(
                name="private_key",
                secret=True,
                value=None,
                configured=True,
                source=SystemSettingFieldSource.ADMIN,
                environment_variable="AZ_GITHUB_PLATFORM_PRIVATE_KEY",
                fallback_configured=True,
                fallback_last_changed_at=None,
            ),
        ),
        candidate=None,
        health=None,
        binding_impact=None,
        activation_validation_status=None,
        app_slug=None,
    )


async def test_patch_preserves_omitted_vs_explicit_null() -> None:
    """Non-secret null clears a field while omitted fields remain unchanged."""
    service = cast(Any, Mock())
    service.patch = AsyncMock()
    service.get_detail = AsyncMock(return_value=_detail())

    await patch_platform_github_app_setting(
        PlatformGitHubAppPatchRequest(expected_version=0, client_id=None),
        system_admin=_admin(),
        service=cast(PlatformGitHubAppSystemSettingService, service),
    )

    await_call = service.patch.await_args
    assert await_call is not None
    mutation = await_call.args[0]
    assert mutation.section is SystemSettingSection.PLATFORM_GITHUB_APP
    assert mutation.config_patch == {"client_id": None}
    assert mutation.secret_actions == {}


async def test_patch_rejects_null_secret_field_without_action() -> None:
    """Secret fields never overload null as a mutation action."""
    service = cast(Any, Mock())
    service.patch = AsyncMock()

    with pytest.raises(HTTPException) as exc_info:
        await patch_platform_github_app_setting(
            PlatformGitHubAppPatchRequest(expected_version=0, private_key=None),
            system_admin=_admin(),
            service=cast(PlatformGitHubAppSystemSettingService, service),
        )

    assert exc_info.value.status_code == 422
    assert "invalid_system_setting_secret_action" in str(exc_info.value.detail)
    service.patch.assert_not_awaited()


@pytest.mark.parametrize(
    ("error", "code"),
    [
        (
            SystemSettingVersionConflict(
                section=SystemSettingSection.PLATFORM_GITHUB_APP,
                expected_version=1,
                current_version=2,
            ),
            "stale_system_setting_version",
        ),
        (
            SystemSettingEnvironmentFieldReadOnly(
                section=SystemSettingSection.PLATFORM_GITHUB_APP,
                field_name="app_id",
                environment_variable="AZ_GITHUB_PLATFORM_APP_ID",
            ),
            "environment_managed_system_setting_field",
        ),
        (
            SystemSettingCandidateReplaced(
                section=SystemSettingSection.PLATFORM_GITHUB_APP,
                candidate_id="candidate-1",
            ),
            "system_setting_candidate_replaced",
        ),
    ],
)
async def test_patch_maps_stable_conflict_codes(error: Exception, code: str) -> None:
    """Version and deployment ownership conflicts remain distinguishable."""
    service = cast(Any, Mock())
    service.patch = AsyncMock(side_effect=error)

    with pytest.raises(HTTPException) as exc_info:
        await patch_platform_github_app_setting(
            PlatformGitHubAppPatchRequest(expected_version=1, app_id="123"),
            system_admin=_admin(),
            service=cast(PlatformGitHubAppSystemSettingService, service),
        )

    assert exc_info.value.status_code == 409
    assert code in str(exc_info.value.detail)


def test_detail_response_never_serializes_secret_plaintext_or_generation() -> None:
    """The Admin response shape contains only redacted secret state."""
    rendered = PlatformGitHubAppDetailResponse.from_domain(_detail()).model_dump_json()

    assert "private_key" in rendered
    assert "effective_generation" not in rendered
    assert "secret-value" not in rendered
