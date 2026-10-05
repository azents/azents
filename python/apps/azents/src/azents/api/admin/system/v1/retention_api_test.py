"""System Admin archive-retention API tests."""

import dataclasses
import datetime

import pytest
from fastapi import HTTPException

from azents.core.archived_session_retention_data import (
    RetentionApplicationInProgress,
    RetentionRevisionConflict,
    RetentionSettingsReadResult,
    RetentionSettingsUpdateResult,
)
from azents.core.auth.deps import SystemAdmin
from azents.core.enums import ArchivedSessionRetentionApplicationStatus
from azents.repos.archived_session_retention.data import (
    ArchivedSessionRetentionApplication,
    RetentionApplicationScope,
    RetentionImpactPreview,
    SystemFileLifecycleSettings,
)
from azents.services.archived_session_retention import ArchivedSessionRetentionService

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


@dataclasses.dataclass(frozen=True)
class _RetentionUpdateCall:
    expected_revision: int
    retention_days: int | None
    application_scope: RetentionApplicationScope
    user_id: str


class _RetentionServiceFake(ArchivedSessionRetentionService):
    """Implement the route's service contract without database dependencies."""

    def __init__(
        self,
        *,
        read_result: RetentionSettingsReadResult | None,
        preview_result: RetentionImpactPreview | None,
        update_result: RetentionSettingsUpdateResult | None,
        update_error: Exception | None,
    ) -> None:
        self.read_result = read_result
        self.preview_result = preview_result
        self.update_result = update_result
        self.update_error = update_error
        self.preview_calls: list[int | None] = []
        self.update_calls: list[_RetentionUpdateCall] = []

    async def get_settings_state(self) -> RetentionSettingsReadResult:
        assert self.read_result is not None
        return self.read_result

    async def preview(self, retention_days: int | None) -> RetentionImpactPreview:
        self.preview_calls.append(retention_days)
        assert self.preview_result is not None
        return self.preview_result

    async def update_settings(
        self,
        *,
        expected_revision: int,
        retention_days: int | None,
        application_scope: RetentionApplicationScope,
        user_id: str,
    ) -> RetentionSettingsUpdateResult:
        self.update_calls.append(
            _RetentionUpdateCall(
                expected_revision=expected_revision,
                retention_days=retention_days,
                application_scope=application_scope,
                user_id=user_id,
            )
        )
        if self.update_error is not None:
            raise self.update_error
        assert self.update_result is not None
        return self.update_result

    async def get_application(
        self, *, application_id: str
    ) -> ArchivedSessionRetentionApplication | None:
        return None


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
    service = _RetentionServiceFake(
        read_result=RetentionSettingsReadResult(
            settings=_settings(now),
            active_application=application,
        ),
        preview_result=RetentionImpactPreview(
            affected_count=4,
            immediately_eligible_count=1,
            cancelled_count=0,
            scheduled_count=4,
            excluded_count=2,
        ),
        update_result=None,
        update_error=None,
    )

    settings = await get_file_lifecycle_settings(
        _system_admin=_admin(),
        retention_service=service,
    )
    preview = await preview_archive_retention_update(
        ArchiveRetentionPreviewRequest(archived_session_retention_days=7),
        _system_admin=_admin(),
        retention_service=service,
    )

    assert settings.archived_session_retention_days == 30
    assert settings.revision == 2
    assert settings.active_application is not None
    assert settings.active_application.id == application.id
    assert preview.affected_count == 4
    assert preview.excluded_count == 2
    assert service.preview_calls == [7]


async def test_update_returns_durable_application() -> None:
    """Existing-archive scope returns the application ID and initial state."""
    now = datetime.datetime(2026, 7, 19, tzinfo=datetime.UTC)
    application = _application(now)
    updated_settings = _settings(now).model_copy(
        update={"archived_session_retention_days": 7, "revision": 3}
    )
    service = _RetentionServiceFake(
        read_result=None,
        preview_result=None,
        update_result=RetentionSettingsUpdateResult(
            settings=updated_settings,
            application=application,
        ),
        update_error=None,
    )

    response = await update_file_lifecycle_settings(
        FileLifecycleSettingsUpdateRequest(
            expected_revision=2,
            archived_session_retention_days=7,
            application_scope="recalculate_existing",
        ),
        system_admin=_admin(),
        retention_service=service,
    )

    assert response.settings.revision == 3
    assert response.application is not None
    assert response.application.id == "application-1"
    assert service.update_calls == [
        _RetentionUpdateCall(
            expected_revision=2,
            retention_days=7,
            application_scope="recalculate_existing",
            user_id="admin-1",
        )
    ]


@pytest.mark.parametrize(
    ("error", "code"),
    [
        (RetentionRevisionConflict(), "retention_revision_conflict"),
        (RetentionApplicationInProgress(), "retention_application_in_progress"),
    ],
)
async def test_update_maps_conflicts(error: Exception, code: str) -> None:
    """Optimistic and active-application conflicts remain distinguishable."""
    service = _RetentionServiceFake(
        read_result=None,
        preview_result=None,
        update_result=None,
        update_error=error,
    )

    with pytest.raises(HTTPException) as exc_info:
        await update_file_lifecycle_settings(
            FileLifecycleSettingsUpdateRequest(
                expected_revision=2,
                archived_session_retention_days=None,
                application_scope="new_archives_only",
            ),
            system_admin=_admin(),
            retention_service=service,
        )

    assert exc_info.value.status_code == 409
    assert code in str(exc_info.value.detail)


async def test_get_application_returns_not_found() -> None:
    """Unknown durable application IDs return not-found semantics."""
    service = _RetentionServiceFake(
        read_result=None,
        preview_result=None,
        update_result=None,
        update_error=None,
    )

    with pytest.raises(HTTPException) as exc_info:
        await get_archive_retention_application(
            "missing",
            _system_admin=_admin(),
            retention_service=service,
        )

    assert exc_info.value.status_code == 404
