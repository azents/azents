"""Scheduled task registry tests."""

import datetime
from typing import Any, cast
from unittest.mock import AsyncMock, Mock

import pytest

from azents.scheduler import registry
from azents.scheduler.types import TaskContext
from azents.services.file_lifecycle_cleanup import (
    FileLifecycleCleanupService,
    FileLifecycleCleanupSummary,
)


class _Container:
    """Container test double that resolves one lifecycle cleanup service."""

    def __init__(self, service: FileLifecycleCleanupService) -> None:
        self.service = service

    async def solve(self, target: type[object]) -> object:
        """Return the configured lifecycle cleanup service."""
        assert target is FileLifecycleCleanupService
        return self.service


@pytest.mark.asyncio
async def test_file_lifecycle_cleanup_handler_logs_structured_summary(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Lifecycle cleanup emits searchable result counts after a successful pass."""
    summary = FileLifecycleCleanupSummary(
        artifacts_expired=1,
        exchange_files_expired=2,
        model_files_deleted=3,
        stale_pins_released=4,
        sessions_advanced=5,
        artifact_blobs_deleted=6,
        exchange_file_blobs_deleted=7,
        model_file_blobs_deleted=8,
        pending_blob_deletion_attempts=9,
        blob_delete_failed=10,
    )
    service = cast(Any, Mock())
    service.cleanup_once = AsyncMock(return_value=summary)
    logger_info = Mock()
    monkeypatch.setattr(registry.logger, "info", logger_info)
    now = datetime.datetime(2026, 7, 18, tzinfo=datetime.UTC)
    context = TaskContext(
        task_key="file_lifecycle_cleanup",
        attempt_started_at=now,
        lease_owner="scheduler-1",
        deadline=now + datetime.timedelta(minutes=2),
        manual_triggered=False,
        container=cast(Any, _Container(service)),
    )

    result = await registry.file_lifecycle_cleanup_handler(context)

    expected_summary = {
        "task_key": "file_lifecycle_cleanup",
        "attempt_started_at": now.isoformat(),
        "manual_triggered": False,
        **summary.to_dict(),
    }
    assert result.summary == expected_summary
    logger_info.assert_called_once_with(
        "File lifecycle cleanup completed",
        extra={
            "task_key": "file_lifecycle_cleanup",
            "manual_triggered": False,
            **summary.to_dict(),
        },
    )
