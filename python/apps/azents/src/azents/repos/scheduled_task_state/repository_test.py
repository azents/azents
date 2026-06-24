"""ScheduledTaskStateRepository tests."""

import datetime

from sqlalchemy.ext.asyncio import AsyncSession

from azents.core.enums import ScheduledTaskStatus
from azents.repos.scheduled_task_state import ScheduledTaskStateRepository


def _dt(minutes: int) -> datetime.datetime:
    return datetime.datetime(2026, 1, 1, 0, minutes, tzinfo=datetime.UTC)


class TestScheduledTaskStateRepository:
    """Scheduled task state repository tests."""

    async def test_claim_due_allows_only_one_lease_owner(
        self,
        rdb_session: AsyncSession,
    ) -> None:
        """Concurrent claim semantics allow only one lease owner."""
        repo = ScheduledTaskStateRepository()
        await repo.ensure_state(
            rdb_session,
            task_key="test-task",
            next_run_at=_dt(0),
        )

        first = await repo.claim_due(
            rdb_session,
            task_key="test-task",
            now=_dt(1),
            lease_owner="owner-1",
            lease_until=_dt(2),
        )
        second = await repo.claim_due(
            rdb_session,
            task_key="test-task",
            now=_dt(1),
            lease_owner="owner-2",
            lease_until=_dt(2),
        )

        assert first is not None
        assert first.lease_owner == "owner-1"
        assert first.latest_status == ScheduledTaskStatus.RUNNING
        assert second is None

    async def test_claim_due_reclaims_expired_lease(
        self,
        rdb_session: AsyncSession,
    ) -> None:
        """Expired lease can be claimed by another owner."""
        repo = ScheduledTaskStateRepository()
        await repo.ensure_state(
            rdb_session,
            task_key="test-expired",
            next_run_at=_dt(0),
        )
        first = await repo.claim_due(
            rdb_session,
            task_key="test-expired",
            now=_dt(1),
            lease_owner="owner-1",
            lease_until=_dt(2),
        )
        assert first is not None

        second = await repo.claim_due(
            rdb_session,
            task_key="test-expired",
            now=_dt(3),
            lease_owner="owner-2",
            lease_until=_dt(4),
        )

        assert second is not None
        assert second.lease_owner == "owner-2"

    async def test_mark_success_releases_lease_and_resets_failure(
        self,
        rdb_session: AsyncSession,
    ) -> None:
        """Success releases lease and stores result summary."""
        repo = ScheduledTaskStateRepository()
        await repo.ensure_state(
            rdb_session,
            task_key="test-success",
            next_run_at=_dt(0),
        )
        claimed = await repo.claim_due(
            rdb_session,
            task_key="test-success",
            now=_dt(1),
            lease_owner="owner-1",
            lease_until=_dt(2),
        )
        assert claimed is not None

        state = await repo.mark_success(
            rdb_session,
            task_key="test-success",
            lease_owner="owner-1",
            finished_at=_dt(1),
            next_run_at=_dt(2),
            result_summary={"ok": True},
        )

        assert state is not None
        assert state.latest_status == ScheduledTaskStatus.SUCCEEDED
        assert state.lease_owner is None
        assert state.failure_streak == 0
        assert state.latest_result_summary == {"ok": True}

    async def test_trigger_marks_task_due(
        self,
        rdb_session: AsyncSession,
    ) -> None:
        """Manual trigger marks next_run_at as requested time."""
        repo = ScheduledTaskStateRepository()
        await repo.ensure_state(
            rdb_session,
            task_key="test-trigger",
            next_run_at=_dt(10),
        )

        state = await repo.trigger(
            rdb_session,
            task_key="test-trigger",
            now=_dt(1),
        )

        assert state is not None
        assert state.next_run_at == _dt(1)
        assert state.manual_requested_at == _dt(1)
