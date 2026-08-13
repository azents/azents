"""Archived-session retention Admin API E2E tests."""

from typing import Any, cast

import azentsadminclient
import azentspublicclient
import pytest
from azentsadminclient.api.system_v1_api import SystemV1Api
from azentsadminclient.models.archive_retention_preview_request import (
    ArchiveRetentionPreviewRequest,
)
from azentsadminclient.models.file_lifecycle_settings_update_request import (
    FileLifecycleSettingsUpdateRequest,
)

from support.utils import authenticate_user, unique


def _admin_client_for_token(
    *,
    server_url: str,
    access_token: str,
) -> azentsadminclient.ApiClient:
    """Create an Admin API client for one access token."""
    return azentsadminclient.ApiClient(
        configuration=azentsadminclient.Configuration(
            host=server_url,
            access_token=access_token,
        )
    )


def _restore_default(system_api: SystemV1Api) -> None:
    """Restore the global retention policy to the product default."""
    current = system_api.system_v1_get_file_lifecycle_settings()
    if current.archived_session_retention_days == 30:
        return
    system_api.system_v1_update_file_lifecycle_settings(
        FileLifecycleSettingsUpdateRequest(
            expected_revision=current.revision,
            archived_session_retention_days=30,
            application_scope="new_archives_only",
        )
    )


def test_default_retention_permission_and_future_only_update(
    admin_api_client: azentsadminclient.ApiClient,
    public_api_client: azentspublicclient.ApiClient,
    azents_admin_server_url: str,
) -> None:
    """Only system administrators can read and update the 30-day default."""
    system_api = SystemV1Api(admin_api_client)
    initial = system_api.system_v1_get_file_lifecycle_settings()
    assert initial.archived_session_retention_days == 30
    assert initial.active_application is None

    ordinary_token, _, _ = authenticate_user(
        public_api_client,
        admin_api_client,
        email=f"retention-ordinary-{unique()}@example.com",
    )
    with _admin_client_for_token(
        server_url=azents_admin_server_url,
        access_token=ordinary_token,
    ) as ordinary_client:
        with pytest.raises(azentsadminclient.ApiException) as denied:
            SystemV1Api(ordinary_client).system_v1_get_file_lifecycle_settings()
    assert cast(Any, denied.value).status == 403

    preview = system_api.system_v1_preview_archive_retention_update(
        ArchiveRetentionPreviewRequest(archived_session_retention_days=14)
    )
    assert preview.affected_count >= 0
    assert preview.immediately_eligible_count >= 0
    assert preview.excluded_count >= 0

    try:
        updated = system_api.system_v1_update_file_lifecycle_settings(
            FileLifecycleSettingsUpdateRequest(
                expected_revision=initial.revision,
                archived_session_retention_days=14,
                application_scope="new_archives_only",
            )
        )
        assert updated.settings.archived_session_retention_days == 14
        assert updated.settings.revision == initial.revision + 1
        assert updated.application is None
        assert updated.settings.active_application is None
    finally:
        _restore_default(system_api)
