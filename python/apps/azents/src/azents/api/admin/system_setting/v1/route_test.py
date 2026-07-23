"""System Settings Admin API route tests."""

from typing import Any, cast
from unittest.mock import AsyncMock, Mock

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from azents.core.auth.deps import SystemAdmin
from azents.core.external_channel_file_system_setting import (
    ExternalChannelFilesConfig,
    ExternalChannelFilesSecrets,
)
from azents.core.system_setting import (
    ResolvedSystemSetting,
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
from azents.services.system_setting.data import SystemSettingActivated
from azents.services.system_setting.service import SystemSettingsService

from . import (
    get_external_channel_files_setting,
    patch_external_channel_files_setting,
    patch_platform_github_app_setting,
)
from .data import (
    ExternalChannelFilesDetailResponse,
    ExternalChannelFilesPatchRequest,
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


def _external_channel_files_resolved(
    *,
    admin_version: int = 0,
    inbound_max_file_bytes: int = 25 * 1024 * 1024,
    outbound_max_file_bytes: int = 25 * 1024 * 1024,
    outbound_max_action_bytes: int = 100 * 1024 * 1024,
) -> ResolvedSystemSetting:
    return ResolvedSystemSetting(
        section=SystemSettingSection.EXTERNAL_CHANNEL_FILES,
        schema_version=1,
        admin_version=admin_version,
        config=ExternalChannelFilesConfig(
            inbound_max_file_bytes=inbound_max_file_bytes,
            outbound_max_file_bytes=outbound_max_file_bytes,
            outbound_max_action_bytes=outbound_max_action_bytes,
        ),
        secrets=ExternalChannelFilesSecrets(),
        field_sources={},
        effective_generation="generation-secret",
    )


async def test_get_external_channel_files_returns_effective_bytes() -> None:
    """The dedicated detail contains effective limits but no internal generation."""
    service = cast(Any, Mock())
    service.resolve = AsyncMock(return_value=_external_channel_files_resolved())

    response = await get_external_channel_files_setting(
        service=cast(SystemSettingsService, service)
    )

    assert response == ExternalChannelFilesDetailResponse(
        section="external_channel_files",
        schema_version=1,
        admin_version=0,
        inbound_max_file_bytes=25 * 1024 * 1024,
        outbound_max_file_bytes=25 * 1024 * 1024,
        outbound_max_action_bytes=100 * 1024 * 1024,
    )
    assert "effective_generation" not in response.model_dump_json()


async def test_patch_external_channel_files_activates_partial_update() -> None:
    """A present limit becomes one direct optimistic settings mutation."""
    service = cast(Any, Mock())
    resolved = _external_channel_files_resolved(
        admin_version=4,
        inbound_max_file_bytes=10 * 1024 * 1024,
    )
    service.mutate = AsyncMock(
        return_value=SystemSettingActivated(
            current=Mock(),
            resolved=resolved,
        )
    )

    response = await patch_external_channel_files_setting(
        ExternalChannelFilesPatchRequest(
            expected_version=3,
            inbound_max_file_bytes=10 * 1024 * 1024,
        ),
        system_admin=_admin(),
        service=cast(SystemSettingsService, service),
    )

    await_call = service.mutate.await_args
    assert await_call is not None
    mutation = await_call.args[0]
    assert mutation.section is SystemSettingSection.EXTERNAL_CHANNEL_FILES
    assert mutation.expected_version == 3
    assert mutation.config_patch == {"inbound_max_file_bytes": 10 * 1024 * 1024}
    assert mutation.secret_actions == {}
    assert mutation.actor_user_id == "admin-1"
    assert response.admin_version == 4


@pytest.mark.parametrize(
    "patch_request",
    [
        ExternalChannelFilesPatchRequest(expected_version=0),
        ExternalChannelFilesPatchRequest(
            expected_version=0,
            inbound_max_file_bytes=None,
        ),
    ],
)
async def test_patch_external_channel_files_rejects_empty_or_null_patch(
    patch_request: ExternalChannelFilesPatchRequest,
) -> None:
    """Direct policy mutation requires one concrete non-null limit."""
    service = cast(Any, Mock())
    service.mutate = AsyncMock()

    with pytest.raises(HTTPException) as exc_info:
        await patch_external_channel_files_setting(
            patch_request,
            system_admin=_admin(),
            service=cast(SystemSettingsService, service),
        )

    assert exc_info.value.status_code == 422
    service.mutate.assert_not_awaited()


async def test_patch_external_channel_files_maps_version_conflict() -> None:
    """Stale direct-save versions use the shared stable conflict response."""
    service = cast(Any, Mock())
    service.mutate = AsyncMock(
        side_effect=SystemSettingVersionConflict(
            section=SystemSettingSection.EXTERNAL_CHANNEL_FILES,
            expected_version=1,
            current_version=2,
        )
    )

    with pytest.raises(HTTPException) as exc_info:
        await patch_external_channel_files_setting(
            ExternalChannelFilesPatchRequest(
                expected_version=1,
                outbound_max_file_bytes=10 * 1024 * 1024,
            ),
            system_admin=_admin(),
            service=cast(SystemSettingsService, service),
        )

    assert exc_info.value.status_code == 409
    assert "stale_system_setting_version" in str(exc_info.value.detail)


async def test_patch_external_channel_files_maps_aggregate_validation() -> None:
    """An invalid aggregate produced by merged settings is a sanitized 422."""
    service = cast(Any, Mock())
    service.mutate = AsyncMock(
        side_effect=ValidationError.from_exception_data(
            "ExternalChannelFilesConfig",
            [
                {
                    "type": "value_error",
                    "loc": (),
                    "input": {},
                    "ctx": {
                        "error": ValueError(
                            "Outbound aggregate must cover one outbound file."
                        )
                    },
                }
            ],
        )
    )

    with pytest.raises(HTTPException) as exc_info:
        await patch_external_channel_files_setting(
            ExternalChannelFilesPatchRequest(
                expected_version=1,
                outbound_max_action_bytes=1,
            ),
            system_admin=_admin(),
            service=cast(SystemSettingsService, service),
        )

    assert exc_info.value.status_code == 422
    assert exc_info.value.detail == {
        "code": "invalid_system_setting_payload",
        "message": "The External Channel file policy is invalid.",
    }


@pytest.mark.parametrize(
    ("field_name", "value"),
    [
        ("inbound_max_file_bytes", 0),
        ("outbound_max_file_bytes", 100 * 1024 * 1024 + 1),
        ("outbound_max_action_bytes", 2_000 * 1024 * 1024 + 1),
    ],
)
def test_external_channel_files_patch_rejects_out_of_range_limits(
    field_name: str,
    value: int,
) -> None:
    """The dedicated request schema publishes the configured hard bounds."""
    with pytest.raises(ValidationError):
        ExternalChannelFilesPatchRequest(
            expected_version=0,
            **{field_name: value},
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
