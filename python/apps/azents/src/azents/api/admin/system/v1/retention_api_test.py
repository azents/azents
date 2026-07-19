"""System Admin archive-retention API tests."""

import datetime
from typing import Any, cast
from unittest.mock import AsyncMock, Mock

import pytest
from fastapi import HTTPException

from azents.core.auth.deps import SystemAdmin
from azents.core.enums import ArchivedSessionRetentionApplicationStatus
from azents.repos.archived_session_retention.data import (
    ArchivedSessionRetentionApplication,
    RetentionImpactPreview,
    SystemFileLifecycleSettings,
)
from azents.services.archived_session_retention import (
    ArchivedSessionRetentionService,
    RetentionApplicationInProgress,
    RetentionRevisionConflict,
    RetentionSettingsReadResult,
    RetentionSettingsUpdateResult,
)

from . import (
    get_archive_retention_application,
    get_file_lifecycle_settings,
    preview_archive_retention_update,
    update_file_lifecycle_settings,
)
from .data import (
    ArchiveRetentionPreviewRequest,
    FileLifecycleSettingsUpdateRequest,
)


def _admin() -> SystemAdmin:
    return SystemAdmin(user_id="admin-1", session_id="auth-session-1")


def _settings(now: datetime.datetime) -> SystemFileLifecycleSettings:
    return SystemFileLifecycleSettings(
        archived_session_retention_days=30,
        revision=2,
        updated_by_user_id="admin-1",
        created_at=now,
        updated_at=now,
    )


def _application(now: datetime.datetime) -> ArchivedSessionRetentionApplication:
    return ArchivedSessionRetentionApplication(
        id="application-1",
        target_revision=3,
        target_retention_days=7,
        requested_by_user_id="admin-1",
        status=ArchivedSessionRetentionApplicationStatus.PENDING,
        cursor_session_id=None,
        affected_count=0,
        immediately_eligible_count=0,
        cancelled_count=0,
        scheduled_count=0,
        skipped_count=0,
        attempt_count=0,
        lease_owner=None,
        lease_until=None,
        next_attempt_at=None,
        last_error_kind=None,
        last_error_summary=None,
        started_at=None,
        completed_at=None,
        created_at=now,
        updated_at=now,
    )


async def test_get_and_preview_file_lifecycle_settings() -> None:
    """Admin reads settings and previews existing-archive impact."""
    now = datetime.datetime(2026, 7, 19, tzinfo=datetime.UTC)
    application = _application(now)
    service = cast(Any, Mock())
    service.get_settings_state = AsyncMock(
        return_value=RetentionSettingsReadResult(
            settings=_settings(now),
            active_application=application,
        )
    )
    service.preview = AsyncMock(
        return_value=RetentionImpactPreview(
            affected_count=4,
            immediately_eligible_count=1,
            cancelled_count=0,
            scheduled_count=4,
            excluded_count=2,
        )
    )

    settings = await get_file_lifecycle_settings(
        _system_admin=_admin(),
        retention_service=cast(ArchivedSessionRetentionService, service),
    )
    preview = await preview_archive_retention_update(
        ArchiveRetentionPreviewRequest(archived_session_retention_days=7),
        _system_admin=_admin(),
        retention_service=cast(ArchivedSessionRetentionService, service),
    )

    assert settings.archived_session_retention_days == 30
    assert settings.revision == 2
    assert settings.active_application is not None
    assert settings.active_application.id == application.id
    assert preview.affected_count == 4
    assert preview.excluded_count == 2
    service.preview.assert_awaited_once_with(7)


async def test_update_returns_durable_application() -> None:
    """Existing-archive scope returns the application ID and initial state."""
    now = datetime.datetime(2026, 7, 19, tzinfo=datetime.UTC)
    application = _application(now)
    updated_settings = _settings(now).model_copy(
        update={"archived_session_retention_days": 7, "revision": 3}
    )
    service = cast(Any, Mock())
    service.update_settings = AsyncMock(
        return_value=RetentionSettingsUpdateResult(
            settings=updated_settings,
            application=application,
        )
    )

    response = await update_file_lifecycle_settings(
        FileLifecycleSettingsUpdateRequest(
            expected_revision=2,
            archived_session_retention_days=7,
            application_scope="recalculate_existing",
        ),
        system_admin=_admin(),
        retention_service=cast(ArchivedSessionRetentionService, service),
    )

    assert response.settings.revision == 3
    assert response.application is not None
    assert response.application.id == "application-1"
    service.update_settings.assert_awaited_once_with(
        expected_revision=2,
        retention_days=7,
        application_scope="recalculate_existing",
        user_id="admin-1",
    )


@pytest.mark.parametrize(
    ("error", "code"),
    [
        (RetentionRevisionConflict(), "retention_revision_conflict"),
        (RetentionApplicationInProgress(), "retention_application_in_progress"),
    ],
)
async def test_update_maps_conflicts(error: Exception, code: str) -> None:
    """Optimistic and active-application conflicts remain distinguishable."""
    service = cast(Any, Mock())
    service.update_settings = AsyncMock(side_effect=error)

    with pytest.raises(HTTPException) as exc_info:
        await update_file_lifecycle_settings(
            FileLifecycleSettingsUpdateRequest(
                expected_revision=2,
                archived_session_retention_days=None,
                application_scope="new_archives_only",
            ),
            system_admin=_admin(),
            retention_service=cast(ArchivedSessionRetentionService, service),
        )

    assert exc_info.value.status_code == 409
    assert code in str(exc_info.value.detail)


async def test_get_application_returns_not_found() -> None:
    """Unknown durable application IDs return not-found semantics."""
    service = cast(Any, Mock())
    service.get_application = AsyncMock(return_value=None)

    with pytest.raises(HTTPException) as exc_info:
        await get_archive_retention_application(
            "missing",
            _system_admin=_admin(),
            retention_service=cast(ArchivedSessionRetentionService, service),
        )

    assert exc_info.value.status_code == 404
