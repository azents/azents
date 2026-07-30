"""Bounded Runtime Profile reconciliation worker tests."""

import dataclasses
import datetime
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from unittest.mock import ANY, AsyncMock, MagicMock

from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from azents.core.runtime_profile import (
    RuntimeConfigurationResolutionStatus,
    RuntimeReconcileSourceKind,
    RuntimeReconcileTaskStatus,
)
from azents.repos.runtime_profile.data import RuntimeConfigurationReconcileTask
from azents.repos.runtime_profile.repository import RuntimeProfileRepository
from azents.services.runtime_profile_resolution.service import (
    RuntimeProfileResolutionService,
)

from .service import RuntimeProfileReconciliationService


class _SessionManager:
    """Yield one mock database session for worker orchestration tests."""

    def __init__(self) -> None:
        self.session = AsyncMock(spec=AsyncSession)

    @asynccontextmanager
    async def __call__(self) -> AsyncIterator[AsyncSession]:
        yield self.session


@dataclasses.dataclass(frozen=True)
class _Harness:
    """Reconciliation service and its mocked collaborators."""

    service: RuntimeProfileReconciliationService
    repository: AsyncMock
    resolution_service: AsyncMock


def _task(
    *,
    cursor: str | None,
    source_version: str = "1",
) -> RuntimeConfigurationReconcileTask:
    now = datetime.datetime(2026, 7, 30, 12, tzinfo=datetime.UTC)
    return RuntimeConfigurationReconcileTask(
        id="task-1",
        source_type=RuntimeReconcileSourceKind.WORKSPACE_RUNTIME_PROFILE,
        source_id="profile-1",
        source_version=source_version,
        cursor=cursor,
        status=RuntimeReconcileTaskStatus.RUNNING,
        attempt=1,
        available_at=now,
        failure_code=None,
        created_at=now,
        updated_at=now,
    )


def _service() -> _Harness:
    repository = AsyncMock(spec=RuntimeProfileRepository)
    resolution_service = AsyncMock(spec=RuntimeProfileResolutionService)
    return _Harness(
        service=RuntimeProfileReconciliationService(
            session_manager=_SessionManager(),
            profile_repository=repository,
            resolution_service=resolution_service,
        ),
        repository=repository,
        resolution_service=resolution_service,
    )


async def test_reconcile_persists_cursor_and_completes_next_page() -> None:
    """One task processes one bounded page and resumes from its cursor."""
    harness = _service()
    service = harness.service
    repository = harness.repository
    resolution_service = harness.resolution_service
    resolution = MagicMock()
    resolution.desired_revision.resolution_status = (
        RuntimeConfigurationResolutionStatus.READY
    )
    resolution_service.ensure_for_agent.return_value = resolution
    repository.get_reconcile_source_version.return_value = "1"
    repository.continue_reconcile_task.return_value = True
    repository.complete_reconcile_task.return_value = True

    repository.claim_reconcile_tasks.return_value = [_task(cursor=None)]
    repository.list_affected_agent_ids.return_value = ["agent-1", "agent-2"]
    first = await service.reconcile_once(task_limit=1, page_size=1)

    assert first.claimed_tasks == 1
    assert first.reconciled_agents == 1
    assert first.continued_tasks == 1
    repository.continue_reconcile_task.assert_awaited_once()
    assert repository.continue_reconcile_task.await_args.kwargs["cursor"] == "agent-1"

    repository.reset_mock()
    resolution_service.reset_mock()
    resolution_service.ensure_for_agent.return_value = resolution
    repository.get_reconcile_source_version.return_value = "1"
    repository.complete_reconcile_task.return_value = True
    repository.claim_reconcile_tasks.return_value = [_task(cursor="agent-1")]
    repository.list_affected_agent_ids.return_value = ["agent-2"]
    second = await service.reconcile_once(task_limit=1, page_size=1)

    assert second.claimed_tasks == 1
    assert second.reconciled_agents == 1
    assert second.continued_tasks == 0
    repository.complete_reconcile_task.assert_awaited_once_with(
        ANY,
        task_id="task-1",
        expected_attempt=1,
        cursor="agent-2",
    )


async def test_reconcile_completes_stale_source_without_agent_work() -> None:
    """A superseded source version is discarded before Agent fan-out."""
    harness = _service()
    service = harness.service
    repository = harness.repository
    resolution_service = harness.resolution_service
    repository.claim_reconcile_tasks.return_value = [
        _task(cursor="agent-1", source_version="1")
    ]
    repository.get_reconcile_source_version.return_value = "2"
    repository.complete_reconcile_task.return_value = True

    result = await service.reconcile_once(task_limit=1, page_size=10)

    assert result.stale_tasks == 1
    resolution_service.ensure_for_agent.assert_not_awaited()
    repository.list_affected_agent_ids.assert_not_awaited()
    repository.complete_reconcile_task.assert_awaited_once()


async def test_reconcile_retries_database_failure_from_last_cursor() -> None:
    """A database failure returns the durable task to bounded retry wait."""
    harness = _service()
    service = harness.service
    repository = harness.repository
    resolution_service = harness.resolution_service
    repository.claim_reconcile_tasks.return_value = [_task(cursor="agent-1")]
    repository.get_reconcile_source_version.return_value = "1"
    repository.list_affected_agent_ids.return_value = ["agent-2"]
    repository.retry_reconcile_task.return_value = True
    resolution_service.ensure_for_agent.side_effect = SQLAlchemyError(
        "database unavailable"
    )

    result = await service.reconcile_once(task_limit=1, page_size=10)

    assert result.retried_tasks == 1
    assert result.reconciled_agents == 0
    repository.retry_reconcile_task.assert_awaited_once()
    retry = repository.retry_reconcile_task.await_args.kwargs
    assert retry["cursor"] == "agent-1"
    assert retry["expected_attempt"] == 1
    assert retry["failure_code"] == "database_unavailable"


async def test_reconcile_does_not_advance_cursor_after_claim_is_reclaimed() -> None:
    """A stale worker cannot overwrite a newer attempt's cursor."""
    harness = _service()
    repository = harness.repository
    resolution = MagicMock()
    resolution.desired_revision.resolution_status = (
        RuntimeConfigurationResolutionStatus.READY
    )
    harness.resolution_service.ensure_for_agent.return_value = resolution
    repository.claim_reconcile_tasks.return_value = [_task(cursor=None)]
    repository.get_reconcile_source_version.return_value = "1"
    repository.list_affected_agent_ids.return_value = ["agent-1", "agent-2"]
    repository.continue_reconcile_task.return_value = False

    result = await harness.service.reconcile_once(task_limit=1, page_size=1)

    assert result.reconciled_agents == 1
    assert result.continued_tasks == 0
    assert result.stale_tasks == 1
    repository.continue_reconcile_task.assert_awaited_once_with(
        ANY,
        task_id="task-1",
        expected_attempt=1,
        cursor="agent-1",
        available_at=ANY,
    )
