"""Agent decommission coordinator tests."""

import datetime
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from typing import cast

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from azents.core.enums import AgentDecommissionStatus
from azents.repos.agent_decommission.data import AgentDecommissionJob
from azents.services.agent_decommission import AgentDecommissionService


@asynccontextmanager
async def _session_manager() -> AsyncGenerator[AsyncSession, None]:
    """Yield a placeholder session for repository doubles."""
    yield cast(AsyncSession, object())


def _job(*, job_id: str, attempt_count: int = 1) -> AgentDecommissionJob:
    """Build one durable job projection."""
    now = datetime.datetime.now(datetime.UTC)
    return AgentDecommissionJob(
        id=job_id,
        agent_id=f"agent-{job_id}",
        workspace_id=f"workspace-{job_id}",
        requested_by_workspace_user_id="workspace-user-1",
        status=AgentDecommissionStatus.PENDING,
        attempt_count=attempt_count,
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


class _DecommissionRepositoryDouble:
    """Claim and retry recorder for coordinator tests."""

    def __init__(self, jobs: list[AgentDecommissionJob]) -> None:
        self.jobs = jobs
        self.retries: list[tuple[str, str]] = []

    async def claim_due(
        self,
        session: AsyncSession,
        *,
        now: datetime.datetime,
        lease_owner: str,
        lease_until: datetime.datetime,
    ) -> AgentDecommissionJob | None:
        """Return one queued job per claim."""
        del session, now, lease_owner, lease_until
        return self.jobs.pop(0) if self.jobs else None

    async def mark_retry(
        self,
        session: AsyncSession,
        *,
        job_id: str,
        lease_owner: str,
        next_attempt_at: datetime.datetime,
        error_kind: str,
        error_summary: str,
        now: datetime.datetime,
    ) -> bool:
        """Record retry attribution."""
        del session, lease_owner, next_attempt_at, error_summary, now
        self.retries.append((job_id, error_kind))
        return True


class _FailureIsolatingCoordinator(AgentDecommissionService):
    """Coordinator double with deterministic per-job outcomes."""

    async def _advance(
        self,
        *,
        job: AgentDecommissionJob,
        lease_owner: str,
    ) -> tuple[bool, bool]:
        """Fail the first job and complete the second one."""
        del lease_owner
        if job.id == "failed":
            raise RuntimeError("provider unavailable")
        return True, False


@pytest.mark.asyncio
async def test_decommission_continues_after_one_job_retries() -> None:
    """One failed Agent decommission does not prevent a later completion."""
    repository = _DecommissionRepositoryDouble(
        [_job(job_id="failed"), _job(job_id="ok")]
    )
    service = object.__new__(_FailureIsolatingCoordinator)
    service.session_manager = _session_manager
    service.decommission_repository = repository  # type: ignore[assignment]

    summary = await service.decommission_once(
        lease_owner="scheduler-1",
        deadline=datetime.datetime.now(datetime.UTC) + datetime.timedelta(minutes=5),
    )

    assert summary.claimed_count == 2
    assert summary.completed_count == 1
    assert summary.retry_scheduled_count == 1
    assert repository.retries == [("failed", "RuntimeError")]
