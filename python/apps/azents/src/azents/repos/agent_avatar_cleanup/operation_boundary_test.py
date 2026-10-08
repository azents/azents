"""Deterministic PostgreSQL avatar cleanup claim and stale settlement proofs."""

import asyncio
import datetime
from uuid import uuid4

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncEngine

from azents.rdb.models.agent_avatar_cleanup import RDBAgentAvatarCleanupJob
from azents.rdb.session_capabilities import create_read_write_session_manager
from azents.repos.agent_avatar_cleanup import AgentAvatarCleanupRepository
from azents.repos.agent_avatar_cleanup.repository_test import _avatar


async def test_held_avatar_claim_skips_competitor_and_fences_reclaimed_tokens(
    rdb_engine: AsyncEngine,
    latest_db_schema: None,
) -> None:
    """A held winner excludes another connection and old tokens cannot settle."""
    del latest_db_schema
    writes = create_read_write_session_manager(rdb_engine)
    repository = AgentAvatarCleanupRepository()
    now = datetime.datetime.now(datetime.UTC)
    suffix = uuid4().hex
    first_token = f"{suffix}:first"
    replacement_token = f"{suffix}:replacement"
    async with writes() as setup:
        rows = [
            RDBAgentAvatarCleanupJob(
                agent_id=None,
                avatar=_avatar(f"public/avatar/{suffix}/{kind}.webp").model_dump(
                    mode="json"
                ),
            )
            for kind in ("retry", "complete")
        ]
        for row in rows:
            row.next_attempt_at = now
        setup.write_session.add_all(rows)
        await setup.write_session.flush()
        job_ids = {row.id for row in rows}

    try:
        async with writes() as winner:
            winner_pid = await winner.read_session.scalar(
                sa.select(sa.func.pg_backend_pid())
            )
            claimed = await repository.claim_due(
                winner,
                now=now,
                lease_token=first_token,
                lease_until=now + datetime.timedelta(minutes=1),
                limit=2,
            )
            assert {job.id for job in claimed} == job_ids
            assert all(job.attempt_count == 1 for job in claimed)

            async def compete() -> None:
                async with writes() as competitor:
                    competitor_pid = await competitor.read_session.scalar(
                        sa.select(sa.func.pg_backend_pid())
                    )
                    assert competitor_pid != winner_pid
                    skipped = await repository.claim_due(
                        competitor,
                        now=now,
                        lease_token=f"{suffix}:competitor",
                        lease_until=now + datetime.timedelta(minutes=1),
                        limit=2,
                    )
                    assert skipped == []

            await asyncio.wait_for(compete(), timeout=5)

        async with writes() as observer:
            committed = list(
                (
                    await observer.read_session.scalars(
                        sa.select(RDBAgentAvatarCleanupJob).where(
                            RDBAgentAvatarCleanupJob.id.in_(job_ids)
                        )
                    )
                ).all()
            )
            assert {row.id for row in committed} == job_ids
            assert all(row.lease_token == first_token for row in committed)
            assert all(row.attempt_count == 1 for row in committed)

        reclaimed_at = now + datetime.timedelta(minutes=2)
        async with writes() as replacement:
            reclaimed = await repository.claim_due(
                replacement,
                now=reclaimed_at,
                lease_token=replacement_token,
                lease_until=reclaimed_at + datetime.timedelta(minutes=1),
                limit=2,
            )
            assert {job.id for job in reclaimed} == job_ids
            assert all(job.attempt_count == 2 for job in reclaimed)
            assert all(job.lease_token == replacement_token for job in reclaimed)

        retry_id, complete_id = sorted(job_ids)
        async with writes() as stale:
            assert not await repository.mark_retry(
                stale,
                job_id=retry_id,
                lease_token=first_token,
                next_attempt_at=reclaimed_at + datetime.timedelta(minutes=1),
                failure_kind="StaleWorker",
                now=reclaimed_at,
            )
            assert not await repository.delete_completed(
                stale, job_id=complete_id, lease_token=first_token
            )

        async with writes() as observer:
            retained = list(
                (
                    await observer.read_session.scalars(
                        sa.select(RDBAgentAvatarCleanupJob).where(
                            RDBAgentAvatarCleanupJob.id.in_(job_ids)
                        )
                    )
                ).all()
            )
            assert len(retained) == 2
            assert all(row.lease_token == replacement_token for row in retained)
            assert all(row.attempt_count == 2 for row in retained)
            assert all(row.last_failure_kind is None for row in retained)

        async with writes() as current:
            assert await repository.mark_retry(
                current,
                job_id=retry_id,
                lease_token=replacement_token,
                next_attempt_at=reclaimed_at + datetime.timedelta(minutes=1),
                failure_kind="CurrentWorker",
                now=reclaimed_at,
            )
            assert await repository.delete_completed(
                current, job_id=complete_id, lease_token=replacement_token
            )
        async with writes() as observer:
            assert (
                await observer.read_session.get(RDBAgentAvatarCleanupJob, complete_id)
                is None
            )
            retry = await observer.read_session.get(RDBAgentAvatarCleanupJob, retry_id)
            assert retry is not None
            assert retry.lease_token is None
            assert retry.attempt_count == 2
            assert retry.last_failure_kind == "CurrentWorker"
    finally:
        async with writes() as cleanup:
            await cleanup.write_session.execute(
                sa.delete(RDBAgentAvatarCleanupJob).where(
                    RDBAgentAvatarCleanupJob.id.in_(job_ids)
                )
            )
