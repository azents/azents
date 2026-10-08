"""Common execution records and Conversation FK invariants over PostgreSQL."""

import asyncio
import datetime
from uuid import uuid4

import pytest
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from azents.core.agent_session_data import AgentSessionCreate
from azents.core.enums import (
    AgentSessionProductMode,
    AgentSessionStatus,
    AgentSessionTitleSource,
    EventKind,
)
from azents.core.session_resource_authority import SessionExecutionOwner
from azents.rdb.models.agent_session import RDBAgentSession
from azents.rdb.models.conversation import RDBConversation
from azents.rdb.models.event import RDBEvent
from azents.rdb.models.session_execution_file import RDBSessionExecutionFile
from azents.rdb.session_capabilities import ReadWriteSession, WriteSession
from azents.repos.agent_session import AgentSessionRepository
from azents.repos.agent_session.repository_test import (
    _create_agent,
    _create_workspace,
)
from azents.repos.session_execution_record import SessionExecutionRecordRepository
from azents.testing.committed_fixture_cleanup import committed_fixture_graph


async def _internal_session(session: WriteSession) -> str:
    """Insert a genuine common identity, with no public profile or tree."""
    suffix = uuid4().hex[:12]
    workspace_id = await _create_workspace(session, f"common-{suffix}")
    agent_id = await _create_agent(session, workspace_id, f"common-{suffix}")
    session_id = uuid4().hex
    await session.write_session.execute(
        insert(RDBAgentSession).values(
            id=session_id,
            workspace_id=workspace_id,
            agent_id=agent_id,
            lifecycle_root_session_id=None,
            status=AgentSessionStatus.ACTIVE,
        )
    )
    return session_id


async def test_profile_free_record_and_owner_do_not_fabricate_public_identity(
    rdb_session: WriteSession,
) -> None:
    session_id = await _internal_session(rdb_session)
    records = SessionExecutionRecordRepository()
    record = await records.get_by_id(rdb_session, session_id)
    assert record is not None
    assert record.lifecycle_root_session_id is None
    assert "handle" not in type(record).model_fields
    assert "title" not in type(record).model_fields
    assert await AgentSessionRepository().get_by_id(rdb_session, session_id) is None
    owner = SessionExecutionOwner(
        session_id=session_id, owner_generation=record.owner_generation
    )
    accepted = await records.fence_owner(rdb_session, owner)
    assert accepted is not None
    assert accepted.id == session_id
    rejected = await records.fence_owner(
        rdb_session,
        SessionExecutionOwner(
            session_id=session_id, owner_generation=record.owner_generation + 1
        ),
    )
    assert rejected is None


async def test_common_purge_cascades_retained_event_and_current_files(
    rdb_session: WriteSession,
) -> None:
    session_id = await _internal_session(rdb_session)
    await rdb_session.write_session.execute(
        insert(RDBEvent).values(
            id=uuid4().hex,
            session_id=session_id,
            kind=EventKind.ASSISTANT_MESSAGE,
            payload={"content": "retained audit record"},
        )
    )
    await rdb_session.write_session.execute(
        insert(RDBSessionExecutionFile).values(
            session_id=session_id,
            path="inputs/summary.md",
            content="provided summary",
            writable=False,
        )
    )
    await rdb_session.write_session.execute(
        sa.update(RDBAgentSession)
        .where(RDBAgentSession.id == session_id)
        .values(status=AgentSessionStatus.ARCHIVED)
    )
    assert (
        await rdb_session.write_session.scalar(
            sa.select(sa.func.count())
            .select_from(RDBSessionExecutionFile)
            .where(RDBSessionExecutionFile.session_id == session_id)
        )
        == 1
    )
    await rdb_session.write_session.execute(
        sa.delete(RDBAgentSession).where(RDBAgentSession.id == session_id)
    )
    assert (
        await rdb_session.write_session.scalar(
            sa.select(sa.func.count())
            .select_from(RDBEvent)
            .where(RDBEvent.session_id == session_id)
        )
        == 0
    )
    assert (
        await rdb_session.write_session.scalar(
            sa.select(sa.func.count())
            .select_from(RDBSessionExecutionFile)
            .where(RDBSessionExecutionFile.session_id == session_id)
        )
        == 0
    )


async def test_primary_archive_cascade_preserves_role_and_restore_uniqueness(
    rdb_session: WriteSession,
) -> None:
    suffix = uuid4().hex[:12]
    workspace_id = await _create_workspace(rdb_session, f"primary-{suffix}")
    agent_id = await _create_agent(rdb_session, workspace_id, f"primary-{suffix}")
    public = AgentSessionRepository()
    first = (
        await public.ensure_team_primary_for_agent(
            rdb_session, workspace_id=workspace_id, agent_id=agent_id
        )
    ).session
    await public.archive(
        rdb_session, first.id, ended_at=datetime.datetime.now(datetime.UTC)
    )
    historical = await public.get_by_id(rdb_session, first.id)
    assert historical is not None
    assert historical.primary_kind == first.primary_kind
    assert historical.status is AgentSessionStatus.ARCHIVED
    projected_status = await rdb_session.write_session.scalar(
        sa.select(RDBConversation.session_status).where(
            RDBConversation.session_id == first.id
        )
    )
    assert projected_status is AgentSessionStatus.ARCHIVED
    second = (
        await public.ensure_team_primary_for_agent(
            rdb_session, workspace_id=workspace_id, agent_id=agent_id
        )
    ).session
    assert first.id != second.id
    with pytest.raises(IntegrityError):
        async with rdb_session.write_session.begin_nested():
            await rdb_session.write_session.execute(
                sa.update(RDBAgentSession)
                .where(RDBAgentSession.id == first.id)
                .values(status=AgentSessionStatus.ACTIVE)
            )
    assert (
        await rdb_session.write_session.scalar(
            sa.select(RDBAgentSession.status).where(RDBAgentSession.id == first.id)
        )
        is AgentSessionStatus.ARCHIVED
    )
    current = await public.get_team_primary_by_agent_id(rdb_session, agent_id)
    assert current is not None
    assert current.id == second.id
    with pytest.raises(IntegrityError):
        async with rdb_session.write_session.begin_nested():
            await rdb_session.write_session.execute(
                sa.update(RDBConversation)
                .where(RDBConversation.session_id == first.id)
                .values(session_status=AgentSessionStatus.ACTIVE)
            )


async def test_profile_mutation_waits_on_common_gate_before_archive_cascade(
    rdb_engine: AsyncEngine, latest_db_schema: None
) -> None:
    """No profile-first deadlock against a common status/FK cascade mutation."""
    del latest_db_schema
    metadata = sa.MetaData()
    async with rdb_engine.connect() as connection:
        await connection.run_sync(metadata.reflect)
    async with committed_fixture_graph(rdb_engine, metadata):
        async with AsyncSession(rdb_engine, expire_on_commit=False) as raw:
            session = ReadWriteSession(raw)
            suffix = uuid4().hex[:12]
            workspace_id = await _create_workspace(session, f"gate-{suffix}")
            agent_id = await _create_agent(session, workspace_id, f"gate-{suffix}")
            created = await AgentSessionRepository().create(
                session,
                AgentSessionCreate(
                    workspace_id=workspace_id,
                    agent_id=agent_id,
                    product_mode=AgentSessionProductMode.TEAM,
                    associated_user_id=None,
                    title=None,
                ),
            )
            await raw.commit()
        pid: asyncio.Future[int] = asyncio.get_running_loop().create_future()

        async def mutate_title() -> None:
            async with AsyncSession(rdb_engine, expire_on_commit=False) as raw:
                backend_id = await raw.scalar(sa.text("SELECT pg_backend_pid()"))
                assert isinstance(backend_id, int)
                pid.set_result(backend_id)
                changed = await AgentSessionRepository().update_title(
                    ReadWriteSession(raw),
                    session_id=created.id,
                    title="After common gate",
                    title_source=None,
                )
                assert changed is not None
                assert changed.title == "After common gate"
                await raw.commit()

        async with AsyncSession(rdb_engine, expire_on_commit=False) as holder:
            await holder.execute(
                sa.select(RDBAgentSession.id)
                .where(RDBAgentSession.id == created.id)
                .with_for_update(of=RDBAgentSession)
            )
            writer = asyncio.create_task(mutate_title())
            try:
                backend_id = await pid
                async with asyncio.timeout(3):
                    while not await holder.scalar(
                        sa.text(
                            "SELECT EXISTS (SELECT 1 FROM pg_locks "
                            "WHERE pid=:pid AND NOT granted)"
                        ),
                        {"pid": backend_id},
                    ):
                        pass
                await asyncio.wait_for(
                    holder.execute(
                        sa.update(RDBAgentSession)
                        .where(RDBAgentSession.id == created.id)
                        .values(status=AgentSessionStatus.ARCHIVED)
                    ),
                    timeout=3,
                )
                await holder.commit()
                await asyncio.wait_for(writer, timeout=3)
            finally:
                if not writer.done():
                    writer.cancel()
                await asyncio.gather(writer, return_exceptions=True)


@pytest.mark.parametrize("kind", ["title", "command"])
async def test_conditional_profile_write_rechecks_target_after_common_wait(
    rdb_engine: AsyncEngine,
    latest_db_schema: None,
    kind: str,
) -> None:
    """Title and command target predicates cannot reuse a pre-wait join snapshot."""
    del latest_db_schema
    metadata = sa.MetaData()
    async with rdb_engine.connect() as connection:
        await connection.run_sync(metadata.reflect)
    async with committed_fixture_graph(rdb_engine, metadata):
        old_command, new_command = uuid4().hex, uuid4().hex
        async with AsyncSession(rdb_engine, expire_on_commit=False) as raw:
            session = ReadWriteSession(raw)
            suffix = uuid4().hex[:12]
            workspace_id = await _create_workspace(session, f"cas-{suffix}")
            agent_id = await _create_agent(session, workspace_id, f"cas-{suffix}")
            created = await AgentSessionRepository().create(
                session,
                AgentSessionCreate(
                    workspace_id=workspace_id,
                    agent_id=agent_id,
                    product_mode=AgentSessionProductMode.TEAM,
                    associated_user_id=None,
                    title=None,
                ),
            )
            if kind == "command":
                assert (
                    await AgentSessionRepository().enqueue_pending_command(
                        session,
                        session_id=created.id,
                        command_id=old_command,
                        command_name="old",
                        payload={"requested": "old"},
                        requester_user_id=None,
                    )
                    is not None
                )
            await raw.commit()
        pid: asyncio.Future[int] = asyncio.get_running_loop().create_future()
        accepted_title: list[bool] = []

        async def conditional_writer() -> None:
            async with AsyncSession(rdb_engine, expire_on_commit=False) as raw:
                backend_id = await raw.scalar(sa.text("SELECT pg_backend_pid()"))
                assert isinstance(backend_id, int)
                pid.set_result(backend_id)
                repository = AgentSessionRepository()
                if kind == "title":
                    changed = await repository.set_initial_auto_title_if_unset(
                        ReadWriteSession(raw),
                        session_id=created.id,
                        title="stale generated title",
                        event_id=None,
                    )
                    accepted_title.append(changed is not None)
                else:
                    await repository.clear_pending_command(
                        ReadWriteSession(raw),
                        session_id=created.id,
                        command_id=old_command,
                    )
                await raw.commit()

        async with AsyncSession(rdb_engine, expire_on_commit=False) as holder:
            await holder.execute(
                sa.select(RDBAgentSession.id)
                .where(RDBAgentSession.id == created.id)
                .with_for_update(of=RDBAgentSession)
            )
            holder_pid = await holder.scalar(sa.text("SELECT pg_backend_pid()"))
            writer = asyncio.create_task(conditional_writer())
            try:
                backend_id = await pid
                assert backend_id != holder_pid
                async with asyncio.timeout(3):
                    while not await holder.scalar(
                        sa.text("SELECT :holder = ANY(pg_blocking_pids(:writer))"),
                        {"holder": holder_pid, "writer": backend_id},
                    ):
                        pass
                if kind == "title":
                    await holder.execute(
                        sa.update(RDBConversation)
                        .where(RDBConversation.session_id == created.id)
                        .values(
                            title="Authoritative manual title",
                            title_source=AgentSessionTitleSource.MANUAL,
                        )
                    )
                else:
                    await holder.execute(
                        sa.update(RDBConversation)
                        .where(RDBConversation.session_id == created.id)
                        .values(
                            pending_command_id=new_command,
                            pending_command_name="new",
                            pending_command_payload={"requested": "new"},
                        )
                    )
                await holder.commit()
                await asyncio.wait_for(writer, timeout=3)
            finally:
                if not writer.done():
                    writer.cancel()
                await asyncio.gather(writer, return_exceptions=True)
        async with AsyncSession(rdb_engine, expire_on_commit=False) as raw:
            current = await AgentSessionRepository().get_by_id(
                ReadWriteSession(raw), created.id
            )
            assert current is not None
            if kind == "title":
                assert accepted_title == [False]
                assert current.title == "Authoritative manual title"
                assert current.title_source is AgentSessionTitleSource.MANUAL
            else:
                assert current.pending_command_id == new_command
                assert current.pending_command_name == "new"
