"""Scheduled task registry tests."""

import datetime
from typing import Any, cast
from unittest.mock import AsyncMock, Mock

import pytest

from azents.scheduler import registry
from azents.scheduler.types import TaskContext
from azents.services.chat import ChatSessionService
from azents.services.file_lifecycle_cleanup import (
    FileLifecycleCleanupService,
    FileLifecycleCleanupSummary,
)
from azents.services.scheduled_task.service import (
    ScheduledTaskDispatcher,
    ScheduledTaskDispatchSummary,
)

from .user_scheduled_task_dispatch import (
    get_user_scheduled_task_dispatcher,
    user_scheduled_task_dispatch_handler,
)


class _Container:
    """Container test double that resolves one lifecycle cleanup service."""

    def __init__(self, service: FileLifecycleCleanupService) -> None:
        self.service = service

    async def solve(self, target: type[object]) -> object:
        """Return the configured lifecycle cleanup service."""
        assert target is FileLifecycleCleanupService
        return self.service


class _AutoArchiveContainer:
    """Container test double that resolves the chat session service."""

    def __init__(self, service: ChatSessionService) -> None:
        self.service = service

    async def solve(self, target: type[object]) -> object:
        """Return the configured chat session service."""
        assert target is ChatSessionService
        return self.service


class _ScheduledTaskDispatchContainer:
    """Container test double that resolves the user Task dispatcher."""

    def __init__(self, dispatcher: ScheduledTaskDispatcher) -> None:
        self.dispatcher = dispatcher

    async def solve(self, target: object) -> object:
        """Return the configured dispatcher composition."""
        assert target is get_user_scheduled_task_dispatcher
        return self.dispatcher


@pytest.mark.asyncio
async def test_session_auto_archive_handler_returns_batch_summary() -> None:
    """Auto-archive task delegates one bounded pass to the chat service."""
    service = cast(Any, Mock())
    service.auto_archive_once = AsyncMock(
        return_value={"scanned": 5, "archived": 2, "skipped": 3}
    )
    now = datetime.datetime(2026, 7, 26, tzinfo=datetime.UTC)
    context = TaskContext(
        task_key="session_auto_archive",
        attempt_started_at=now,
        lease_owner="scheduler-1",
        deadline=now + datetime.timedelta(minutes=10),
        manual_triggered=False,
        container=cast(Any, _AutoArchiveContainer(service)),
    )

    result = await registry.session_auto_archive_handler(context)

    assert result.summary == {
        "task_key": "session_auto_archive",
        "attempt_started_at": now.isoformat(),
        "manual_triggered": False,
        "scanned": 5,
        "archived": 2,
        "skipped": 3,
    }
    service.auto_archive_once.assert_awaited_once_with()


@pytest.mark.asyncio
async def test_user_scheduled_task_dispatch_handler_returns_aggregate_summary() -> None:
    """The registered handler passes the Scheduler lease owner to the dispatcher."""
    summary = ScheduledTaskDispatchSummary(
        claimed=5,
        admitted=2,
        coalesced=1,
        skipped=2,
        wake_failed=1,
    )
    dispatcher = cast(Any, Mock())
    dispatcher.dispatch_once = AsyncMock(return_value=summary)
    now = datetime.datetime(2026, 8, 16, tzinfo=datetime.UTC)
    context = TaskContext(
        task_key="user_scheduled_task_dispatch",
        attempt_started_at=now,
        lease_owner="scheduler-1",
        deadline=now + datetime.timedelta(minutes=2),
        manual_triggered=False,
        container=cast(
            Any,
            _ScheduledTaskDispatchContainer(dispatcher),
        ),
    )

    result = await user_scheduled_task_dispatch_handler(context)

    assert result.summary == {
        "task_key": "user_scheduled_task_dispatch",
        "attempt_started_at": now.isoformat(),
        "manual_triggered": False,
        "claimed": 5,
        "admitted": 2,
        "coalesced": 1,
        "skipped": 2,
        "wake_failed": 1,
    }
    dispatcher.dispatch_once.assert_awaited_once_with(lease_owner="scheduler-1")


def test_user_scheduled_task_dispatch_is_registered_once() -> None:
    """The existing Scheduler registry owns one bounded user Task dispatcher."""
    definitions = registry.get_task_definitions()
    matches = [
        definition
        for definition in definitions
        if definition.key == "user_scheduled_task_dispatch"
    ]

    assert matches == [registry.USER_SCHEDULED_TASK_DISPATCH_TASK]
    definition = matches[0]
    assert definition.interval == datetime.timedelta(seconds=10)
    assert definition.timeout == datetime.timedelta(minutes=2)
    assert definition.retry_policy.kind == "bounded_backoff"
    assert definition.enabled_by_default is True


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
        avatar_cleanup_attempted=11,
        avatar_cleanup_completed=12,
        avatar_cleanup_failed=13,
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
    service.cleanup_once.assert_awaited_once_with(lease_owner="scheduler-1")
