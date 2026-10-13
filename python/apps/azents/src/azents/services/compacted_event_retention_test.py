"""API and scheduled maintenance contract tests for compacted-event retention."""

import datetime
from unittest.mock import AsyncMock, Mock

import pytest
from azcommon import di
from fastapi import HTTPException

from azents.api.admin.system.v1 import update_compacted_event_retention
from azents.api.admin.system.v1.data import CompactedEventRetentionUpdateRequest
from azents.api.admin.system.v1.retention_api_test import _admin, _settings
from azents.core.archived_session_retention_data import RetentionRevisionConflict
from azents.repos.compacted_event_retention import CompactedEventCleanupSummary
from azents.scheduler import registry
from azents.scheduler.types import TaskContext
from azents.services.compacted_event_retention import CompactedEventRetentionService
from azents.testing.types import require_instance


async def test_admin_mutation_passes_explicit_unlimited_policy() -> None:
    now = datetime.datetime(2026, 10, 13, tzinfo=datetime.UTC)
    settings = _settings(now)
    mock = Mock(spec=CompactedEventRetentionService)
    mock.update_settings = AsyncMock(return_value=settings)
    response = await update_compacted_event_retention(
        request=CompactedEventRetentionUpdateRequest(
            expected_revision=2, compacted_event_retention_days=None
        ),
        system_admin=_admin(),
        retention_service=require_instance(mock, CompactedEventRetentionService),
    )
    assert response.compacted_event_retention_days is None
    assert response.archived_session_retention_days == 30
    mock.update_settings.assert_awaited_once_with(
        expected_revision=2, retention_days=None, user_id="admin-1"
    )


async def test_admin_mutation_revision_conflict_is_409() -> None:
    mock = Mock(spec=CompactedEventRetentionService)
    mock.update_settings = AsyncMock(side_effect=RetentionRevisionConflict)
    with pytest.raises(HTTPException) as error:
        await update_compacted_event_retention(
            request=CompactedEventRetentionUpdateRequest(
                expected_revision=1, compacted_event_retention_days=0
            ),
            system_admin=_admin(),
            retention_service=require_instance(mock, CompactedEventRetentionService),
        )
    assert error.value.status_code == 409
    detail = error.value.detail
    assert isinstance(detail, dict)
    assert detail["code"] == "retention_revision_conflict"


async def test_scheduler_returns_bounded_cleanup_summary() -> None:
    service = Mock(spec=CompactedEventRetentionService)
    service.cleanup_once = AsyncMock(
        return_value=CompactedEventCleanupSummary(
            deleted_count=1000, limit_reached=True, unlimited=False
        )
    )
    container = Mock(spec=di.Container)
    container.solve = AsyncMock(return_value=service)
    now = datetime.datetime(2026, 10, 13, tzinfo=datetime.UTC)
    context = TaskContext(
        task_key="compacted_event_cleanup",
        attempt_started_at=now,
        lease_owner="test-scheduler",
        deadline=now + datetime.timedelta(minutes=2),
        manual_triggered=False,
        container=require_instance(container, di.Container),
    )
    result = await registry.compacted_event_cleanup_handler(context)
    assert result.summary == {
        "task_key": context.task_key,
        "attempt_started_at": now.isoformat(),
        "manual_triggered": False,
        "deleted_count": 1000,
        "limit_reached": True,
        "unlimited": False,
    }
    container.solve.assert_awaited_once_with(CompactedEventRetentionService)
    service.cleanup_once.assert_awaited_once_with()


def test_cleanup_is_independent_five_minute_task() -> None:
    task = registry.COMPACTED_EVENT_CLEANUP_TASK
    assert task in registry.get_task_definitions()
    assert task.key != registry.ARCHIVED_SESSION_PURGE_TASK.key
    assert task.interval == datetime.timedelta(minutes=5)
    assert task.enabled_by_default
    assert task.retry_policy.kind == "bounded_backoff"
