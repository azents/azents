"""Owner lifecycle repository tests."""

import datetime

from sqlalchemy.ext.asyncio import AsyncSession

from azents.core.enums import OwnerLifecycleStatus
from azents.rdb.session import SessionManager
from azents.repos.owner_lifecycle import OwnerLifecycleRepository


class TestOwnerLifecycleRepository:
    """Durable owner-lifecycle job repository tests."""

    async def test_membership_archive_reopens_completed_job(
        self,
        rdb_session_manager: SessionManager[AsyncSession],
    ) -> None:
        """Requeue a completed membership-archive job for a later membership loss."""
        repo = OwnerLifecycleRepository()
        async with rdb_session_manager() as session:
            first = await repo.create_or_get_membership_archive(
                session,
                workspace_id="workspace-reopen-1",
                user_id="user-reopen-1",
            )
            now = datetime.datetime.now(datetime.UTC)
            assert (
                await repo.mark_completed(
                    session,
                    job_id=first.id,
                    lease_owner="test-owner",
                    now=now,
                )
                is False
            )
            # Complete without lease by direct status path: claim then complete.
            claimed = await repo.claim_due(
                session,
                now=now,
                lease_owner="test-owner",
                lease_until=now + datetime.timedelta(minutes=5),
            )
            assert claimed is not None
            assert claimed.id == first.id
            assert await repo.mark_completed(
                session,
                job_id=first.id,
                lease_owner="test-owner",
                now=now,
            )
            second = await repo.create_or_get_membership_archive(
                session,
                workspace_id="workspace-reopen-1",
                user_id="user-reopen-1",
            )
            assert second.id == first.id
            assert second.status is OwnerLifecycleStatus.PENDING
            assert second.completed_at is None
