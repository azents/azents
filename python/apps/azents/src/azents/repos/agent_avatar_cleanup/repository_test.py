"""Durable superseded Agent avatar cleanup repository tests."""

import asyncio
import datetime
from uuid import uuid4

import pytest
import sqlalchemy as sa
from azcommon.result import Success
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from azents.rdb.models.agent import RDBAgent
from azents.rdb.models.agent_avatar_cleanup import RDBAgentAvatarCleanupJob
from azents.rdb.models.workspace import RDBWorkspace
from azents.repos.agent import AgentRepository
from azents.services.uploads.schema import (
    StoredImage,
    StoredImageFile,
    StoredImageThumbnails,
)
from azents.testing.model_selection import make_test_model_selection_dict

from . import AgentAvatarCleanupRepository


def _avatar(key: str) -> StoredImage:
    """Create one stored avatar snapshot."""
    file = StoredImageFile(
        key=key,
        content_type="image/webp",
        size_bytes=1,
        width=512,
        height=512,
    )
    return StoredImage(
        filename="avatar.webp",
        default=file,
        thumbnails=StoredImageThumbnails(large=file),
        original=None,
        uploaded_at=datetime.datetime.now(datetime.UTC),
    )


async def _create_agent(
    session: AsyncSession,
    *,
    avatar: StoredImage | None,
) -> RDBAgent:
    """Persist a minimal Agent suitable for avatar cleanup tests."""
    suffix = uuid4().hex[:8]
    workspace = RDBWorkspace(
        name="Avatar cleanup test",
        handle=f"avatar-cleanup-{suffix}",
    )
    session.add(workspace)
    await session.flush()
    agent = RDBAgent(
        workspace_id=workspace.id,
        name="Avatar cleanup Agent",
        model_selection=make_test_model_selection_dict(),
        lightweight_model_selection=make_test_model_selection_dict(),
        avatar=avatar.model_dump(mode="json") if avatar is not None else None,
    )
    session.add(agent)
    await session.flush()
    return agent


async def test_update_avatar_enqueues_each_actual_superseded_snapshot(
    rdb_session: AsyncSession,
) -> None:
    """Sequential serialized mutations never enqueue the final current avatar."""
    old_avatar = _avatar("public/avatar/agent-1/large/old.webp")
    middle_avatar = _avatar("public/avatar/agent-1/large/middle.webp")
    current_avatar = _avatar("public/avatar/agent-1/large/current.webp")
    agent = await _create_agent(rdb_session, avatar=old_avatar)
    agent_repository = AgentRepository()

    first = await agent_repository.update_avatar(
        rdb_session,
        agent.id,
        middle_avatar,
    )
    second = await agent_repository.update_avatar(
        rdb_session,
        agent.id,
        current_avatar,
    )

    assert isinstance(first, Success)
    assert isinstance(second, Success)
    jobs = list(
        (
            await rdb_session.scalars(
                sa.select(RDBAgentAvatarCleanupJob).order_by(
                    RDBAgentAvatarCleanupJob.created_at,
                    RDBAgentAvatarCleanupJob.id,
                )
            )
        ).all()
    )
    assert [job.avatar for job in jobs] == [
        old_avatar.model_dump(mode="json"),
        middle_avatar.model_dump(mode="json"),
    ]
    assert all(job.agent_id == agent.id for job in jobs)
    current = await rdb_session.get(RDBAgent, agent.id)
    assert current is not None
    assert current.avatar == current_avatar.model_dump(mode="json")


async def test_concurrent_avatar_updates_enqueue_each_committed_prior_snapshot(
    rdb_engine: AsyncEngine,
    latest_db_schema: None,
) -> None:
    """A blocked second updater snapshots the first committed avatar after its lock."""
    del latest_db_schema
    original_avatar = _avatar("public/avatar/agent-1/large/original.webp")
    intermediate_avatar = _avatar("public/avatar/agent-1/large/intermediate.webp")
    final_avatar = _avatar("public/avatar/agent-1/large/final.webp")
    session_factory = async_sessionmaker(rdb_engine, expire_on_commit=False)
    async with session_factory() as setup_session:
        agent = await _create_agent(setup_session, avatar=original_avatar)
        agent_id = agent.id
        workspace_id = agent.workspace_id
        await setup_session.commit()

    first_lock_acquired = asyncio.Event()
    allow_first_commit = asyncio.Event()
    second_started = asyncio.Event()

    async def replace_with_intermediate() -> object:
        async with session_factory() as first_session:
            result = await AgentRepository().update_avatar(
                first_session,
                agent_id,
                intermediate_avatar,
            )
            first_lock_acquired.set()
            await allow_first_commit.wait()
            await first_session.commit()
            return result

    async def replace_with_final() -> object:
        async with session_factory() as second_session:
            second_started.set()
            result = await AgentRepository().update_avatar(
                second_session,
                agent_id,
                final_avatar,
            )
            await second_session.commit()
            return result

    first_task = asyncio.create_task(replace_with_intermediate())
    second_task: asyncio.Task[object] | None = None
    try:
        try:
            await asyncio.wait_for(first_lock_acquired.wait(), timeout=5)
            second_task = asyncio.create_task(replace_with_final())
            await asyncio.wait_for(second_started.wait(), timeout=5)
            with pytest.raises(TimeoutError):
                await asyncio.wait_for(asyncio.shield(second_task), timeout=0.2)

            allow_first_commit.set()
            first = await asyncio.wait_for(first_task, timeout=5)
            second = await asyncio.wait_for(second_task, timeout=5)
        finally:
            allow_first_commit.set()
            pending_tasks = [
                task
                for task in (first_task, second_task)
                if task is not None and not task.done()
            ]
            for task in pending_tasks:
                task.cancel()
            if pending_tasks:
                await asyncio.gather(*pending_tasks, return_exceptions=True)

        assert isinstance(first, Success)
        assert isinstance(second, Success)
        async with session_factory() as verification_session:
            current = await verification_session.get(RDBAgent, agent_id)
            jobs = list(
                (
                    await verification_session.scalars(
                        sa.select(RDBAgentAvatarCleanupJob)
                        .where(RDBAgentAvatarCleanupJob.agent_id == agent_id)
                        .order_by(
                            RDBAgentAvatarCleanupJob.created_at,
                            RDBAgentAvatarCleanupJob.id,
                        )
                    )
                ).all()
            )

        assert current is not None
        assert current.avatar == final_avatar.model_dump(mode="json")
        cleanup_avatars = [job.avatar for job in jobs]
        assert cleanup_avatars.count(original_avatar.model_dump(mode="json")) == 1
        assert cleanup_avatars.count(intermediate_avatar.model_dump(mode="json")) == 1
        assert final_avatar.model_dump(mode="json") not in cleanup_avatars
        assert len(cleanup_avatars) == 2
    finally:
        async with session_factory() as cleanup_session:
            await cleanup_session.execute(
                sa.delete(RDBAgentAvatarCleanupJob).where(
                    RDBAgentAvatarCleanupJob.agent_id == agent_id
                )
            )
            await cleanup_session.execute(
                sa.delete(RDBAgent).where(RDBAgent.id == agent_id)
            )
            await cleanup_session.execute(
                sa.delete(RDBWorkspace).where(RDBWorkspace.id == workspace_id)
            )
            await cleanup_session.commit()


async def test_avatar_cleanup_job_survives_agent_deletion(
    rdb_session: AsyncSession,
) -> None:
    """Agent deletion clears only the optional diagnostic relationship."""
    old_avatar = _avatar("public/avatar/agent-1/large/old.webp")
    agent = await _create_agent(rdb_session, avatar=old_avatar)

    result = await AgentRepository().update_avatar(rdb_session, agent.id, None)

    assert isinstance(result, Success)
    await rdb_session.delete(agent)
    await rdb_session.flush()
    jobs = list((await rdb_session.scalars(sa.select(RDBAgentAvatarCleanupJob))).all())
    assert len(jobs) == 1
    assert jobs[0].agent_id is None
    assert jobs[0].avatar == old_avatar.model_dump(mode="json")


async def test_claim_retry_and_delete_completed_cleanup_job(
    rdb_session: AsyncSession,
) -> None:
    """Claiming uses tokens and success deletes the cleanup job."""
    now = datetime.datetime.now(datetime.UTC)
    first_token = "scheduler-1:claim-1"
    second_token = "scheduler-1:claim-2"
    row = RDBAgentAvatarCleanupJob(
        avatar=_avatar("public/avatar/agent-1/large/old.webp").model_dump(mode="json"),
        agent_id=None,
    )
    row.next_attempt_at = now
    rdb_session.add(row)
    await rdb_session.flush()
    repository = AgentAvatarCleanupRepository()

    first = await repository.claim_due(
        rdb_session,
        now=now,
        lease_token=first_token,
        lease_until=now + datetime.timedelta(minutes=5),
        limit=10,
    )

    assert len(first) == 1
    assert first[0].id == row.id
    assert first[0].attempt_count == 1
    assert first[0].lease_token == first_token
    retry_at = now + datetime.timedelta(minutes=1)
    assert await repository.mark_retry(
        rdb_session,
        job_id=row.id,
        lease_token=first_token,
        next_attempt_at=retry_at,
        failure_kind="RuntimeError",
        now=now,
    )
    assert (
        await repository.claim_due(
            rdb_session,
            now=now + datetime.timedelta(seconds=30),
            lease_token=second_token,
            lease_until=now + datetime.timedelta(minutes=6),
            limit=10,
        )
        == []
    )

    second = await repository.claim_due(
        rdb_session,
        now=retry_at,
        lease_token=second_token,
        lease_until=retry_at + datetime.timedelta(minutes=5),
        limit=10,
    )

    assert len(second) == 1
    assert second[0].attempt_count == 2
    assert second[0].lease_token == second_token
    assert second[0].last_failure_kind == "RuntimeError"
    assert not await repository.delete_completed(
        rdb_session,
        job_id=row.id,
        lease_token=first_token,
    )
    assert await repository.delete_completed(
        rdb_session,
        job_id=row.id,
        lease_token=second_token,
    )
    assert (
        await repository.claim_due(
            rdb_session,
            now=retry_at + datetime.timedelta(minutes=1),
            lease_token="scheduler-1:claim-3",
            lease_until=retry_at + datetime.timedelta(minutes=6),
            limit=10,
        )
        == []
    )
    assert await rdb_session.get(RDBAgentAvatarCleanupJob, row.id) is None


async def test_expired_claim_token_cannot_settle_reclaimed_avatar_cleanup_jobs(
    rdb_session: AsyncSession,
) -> None:
    """A stale token cannot retry or delete jobs reclaimed by the same scheduler."""
    now = datetime.datetime.now(datetime.UTC)
    first_token = "scheduler-1:claim-1"
    second_token = "scheduler-1:claim-2"
    retry_row = RDBAgentAvatarCleanupJob(
        avatar=_avatar("public/avatar/agent-1/large/retry.webp").model_dump(
            mode="json"
        ),
        agent_id=None,
    )
    delete_row = RDBAgentAvatarCleanupJob(
        avatar=_avatar("public/avatar/agent-1/large/delete.webp").model_dump(
            mode="json"
        ),
        agent_id=None,
    )
    retry_row.next_attempt_at = now
    delete_row.next_attempt_at = now
    rdb_session.add_all([retry_row, delete_row])
    await rdb_session.flush()
    repository = AgentAvatarCleanupRepository()

    first = await repository.claim_due(
        rdb_session,
        now=now,
        lease_token=first_token,
        lease_until=now + datetime.timedelta(minutes=1),
        limit=2,
    )
    reclaimed_at = now + datetime.timedelta(minutes=1, seconds=1)
    second = await repository.claim_due(
        rdb_session,
        now=reclaimed_at,
        lease_token=second_token,
        lease_until=reclaimed_at + datetime.timedelta(minutes=5),
        limit=2,
    )

    assert {job.id for job in first} == {retry_row.id, delete_row.id}
    assert {job.id for job in second} == {retry_row.id, delete_row.id}
    assert all(job.lease_token == second_token for job in second)
    retry_at = reclaimed_at + datetime.timedelta(minutes=1)
    assert not await repository.mark_retry(
        rdb_session,
        job_id=retry_row.id,
        lease_token=first_token,
        next_attempt_at=retry_at,
        failure_kind="RuntimeError",
        now=reclaimed_at,
    )
    assert await repository.mark_retry(
        rdb_session,
        job_id=retry_row.id,
        lease_token=second_token,
        next_attempt_at=retry_at,
        failure_kind="RuntimeError",
        now=reclaimed_at,
    )
    assert not await repository.delete_completed(
        rdb_session,
        job_id=delete_row.id,
        lease_token=first_token,
    )
    assert await repository.delete_completed(
        rdb_session,
        job_id=delete_row.id,
        lease_token=second_token,
    )

    retried = await rdb_session.get(RDBAgentAvatarCleanupJob, retry_row.id)
    assert retried is not None
    assert retried.lease_token is None
    assert retried.next_attempt_at == retry_at
    assert await rdb_session.get(RDBAgentAvatarCleanupJob, delete_row.id) is None
