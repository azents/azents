"""Real PostgreSQL foreign-key references must coexist with authorization fences."""

import asyncio
from datetime import UTC, datetime
from uuid import uuid4

import pytest
import sqlalchemy as sa
from psycopg import Error as PsycopgError
from sqlalchemy.exc import OperationalError
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from azents.core.enums import (
    AgentSessionRunState,
    EventKind,
    ExternalChannelActionMode,
    ExternalChannelWorkTaskStatus,
)
from azents.core.external_channel_progress import ExternalChannelWorkTask
from azents.core.session_resource_authority import SessionExecutionOwner
from azents.rdb.models.agent import RDBAgent
from azents.rdb.models.agent_session import RDBAgentSession
from azents.rdb.models.event import RDBEvent
from azents.rdb.models.external_channel import (
    RDBExternalChannelBinding,
    RDBExternalChannelResource,
)
from azents.rdb.session_capabilities import ReadWriteSession
from azents.repos.agent_execution import EventTranscriptRepository
from azents.repos.agent_execution.data import EventCreate
from azents.repos.agent_session import AgentSessionRepository
from azents.repos.external_channel.repository import ExternalChannelRepository
from azents.repos.external_channel.work import ExternalChannelWorkRepository
from azents.repos.external_channel.work_state_test import (
    _cleanup_binding,
    _seed_binding,
)
from azents.repos.session_execution.ownership import fence_owned_session_mutation
from azents.worker.session.idle_continuation_lock_test import _wait_for_database_blocker


def _abort_identity(error: BaseException) -> list[str]:
    """Report only driver class and SQLSTATE, never SQL or bound values."""
    if isinstance(error, OperationalError) and isinstance(error.orig, PsycopgError):
        return [f"{type(error.orig).__name__}:{error.orig.sqlstate}"]
    if isinstance(error, BaseExceptionGroup):
        return [item for nested in error.exceptions for item in _abort_identity(nested)]
    return []


@pytest.mark.parametrize("by_resource", [False, True])
async def test_ingress_binding_fence_allows_owned_transcript_mutation(
    rdb_engine: AsyncEngine, latest_db_schema: None, by_resource: bool
) -> None:
    """Ingress wake and the real owner-fence/transcript prefix must both commit."""
    del latest_db_schema
    seeded = await _seed_binding(rdb_engine, suffix=uuid4().hex[:8])
    channels = ExternalChannelRepository()
    sessions = AgentSessionRepository()
    worker_ready: asyncio.Future[int] = asyncio.get_running_loop().create_future()
    ingress_pid: asyncio.Future[int] = asyncio.get_running_loop().create_future()
    try:
        async with rdb_engine.begin() as setup:
            await setup.execute(
                sa.update(RDBAgentSession)
                .where(RDBAgentSession.id == seeded.owner_session_id)
                .values(primary_channel_binding_id=seeded.binding_id)
            )

        async def worker() -> None:
            async with AsyncSession(rdb_engine, expire_on_commit=False) as raw:
                session = ReadWriteSession(raw)
                generation = await raw.scalar(
                    sa.select(RDBAgentSession.owner_generation).where(
                        RDBAgentSession.id == seeded.owner_session_id
                    )
                )
                assert isinstance(generation, int)
                await fence_owned_session_mutation(
                    session, SessionExecutionOwner(seeded.owner_session_id, generation)
                )
                pid = await raw.scalar(sa.text("SELECT pg_backend_pid()"))
                assert isinstance(pid, int)
                worker_ready.set_result(pid)
                await _wait_for_database_blocker(
                    rdb_engine, blocked_pid=await ingress_pid, blocker_pid=pid
                )
                # EngineEventOperationRepository.append_user_messages uses this
                # exact owned prefix. Transcript append touches Session activity;
                # its FK recheck must not wait for the ingress Binding fence.
                await EventTranscriptRepository().append(
                    session,
                    EventCreate(
                        session_id=seeded.owner_session_id,
                        kind=EventKind.USER_MESSAGE,
                        payload={
                            "content": "lock regression",
                            "sender_user_id": None,
                        },
                    ),
                )
                await raw.commit()

        async def ingress() -> None:
            await worker_ready
            async with AsyncSession(rdb_engine, expire_on_commit=False) as raw:
                session = ReadWriteSession(raw)
                pid = await raw.scalar(sa.text("SELECT pg_backend_pid()"))
                assert isinstance(pid, int)
                ingress_pid.set_result(pid)
                if by_resource:
                    binding = await channels.lock_connected_binding_by_resource(
                        session, resource_id=seeded.resource_id
                    )
                else:
                    binding = await channels.lock_binding(
                        session, binding_id=seeded.binding_id
                    )
                assert binding is not None
                admitted = await sessions.admit_input_wakeup(
                    session, seeded.owner_session_id
                )
                assert admitted is not None
                await raw.commit()

        try:
            async with asyncio.timeout(15), asyncio.TaskGroup() as tasks:
                tasks.create_task(worker())
                tasks.create_task(ingress())
        except* OperationalError as errors:
            pytest.fail(
                "Owned transcript/ingress aborted: "
                + ", ".join(_abort_identity(errors)),
                pytrace=False,
            )
        async with rdb_engine.connect() as connection:
            state = (
                await connection.execute(
                    sa.select(
                        RDBAgentSession.run_state,
                        RDBAgentSession.primary_channel_binding_id,
                        RDBAgentSession.owner_generation,
                    ).where(RDBAgentSession.id == seeded.owner_session_id)
                )
            ).one()
            assert state == (AgentSessionRunState.RUNNING, seeded.binding_id, 0)
            assert (
                await connection.scalar(
                    sa.select(sa.func.count())
                    .select_from(RDBEvent)
                    .where(RDBEvent.session_id == seeded.owner_session_id)
                )
                == 1
            )
    finally:
        await _cleanup_binding(rdb_engine, seeded)


async def test_route_agent_fence_allows_binding_owned_work_commit(
    rdb_engine: AsyncEngine, latest_db_schema: None
) -> None:
    """Real Work commit and route/Binding resolution must not form an FK cycle."""
    del latest_db_schema
    seeded = await _seed_binding(rdb_engine, suffix=uuid4().hex[:8])
    channels = ExternalChannelRepository()
    work = ExternalChannelWorkRepository()
    work_ready: asyncio.Future[int] = asyncio.get_running_loop().create_future()
    route_pid: asyncio.Future[int] = asyncio.get_running_loop().create_future()
    try:
        async with rdb_engine.begin() as setup:
            await setup.execute(
                sa.update(RDBExternalChannelResource)
                .where(RDBExternalChannelResource.id == seeded.resource_id)
                .values(labels={"channel_id": "channel-lock", "thread_ts": "1.0"})
            )
        async with rdb_engine.connect() as connection:
            deferred = (
                await connection.execute(
                    sa.text(
                        "SELECT condeferrable, condeferred FROM pg_constraint "
                        "WHERE conname = 'toolkit_states_agent_id_fkey'"
                    )
                )
            ).one()
            assert deferred == (True, True)

        async def commit_work() -> None:
            async with AsyncSession(rdb_engine, expire_on_commit=False) as raw:
                session = ReadWriteSession(raw)
                await work.commit_direct_action(
                    session,
                    links=[],
                    session_id=seeded.owner_session_id,
                    agent_id=seeded.owner_agent_id,
                    run_id=None,
                    client_tool_call_id=f"lock-{uuid4().hex}",
                    binding_id=seeded.binding_id,
                    mode=ExternalChannelActionMode.CONTINUE,
                    message=None,
                    title="Lock regression…",
                    tasks=[
                        ExternalChannelWorkTask(
                            id="task",
                            title="Validate lock compatibility",
                            status=ExternalChannelWorkTaskStatus.IN_PROGRESS,
                            details=None,
                            output=None,
                            sources=[],
                        )
                    ],
                    files=[],
                    now=datetime.now(UTC),
                )
                pid = await raw.scalar(sa.text("SELECT pg_backend_pid()"))
                assert isinstance(pid, int)
                work_ready.set_result(pid)
                await _wait_for_database_blocker(
                    rdb_engine, blocked_pid=await route_pid, blocker_pid=pid
                )
                await raw.commit()

        async def resolve_route() -> None:
            await work_ready
            async with AsyncSession(rdb_engine, expire_on_commit=False) as raw:
                session = ReadWriteSession(raw)
                pid = await raw.scalar(sa.text("SELECT pg_backend_pid()"))
                assert isinstance(pid, int)
                route_pid.set_result(pid)
                route = await channels.get_routable_route_by_id(
                    session, route_id=seeded.route_id
                )
                assert route is not None
                binding = await channels.lock_connected_binding_by_resource(
                    session, resource_id=seeded.resource_id
                )
                assert binding is not None
                await raw.commit()

        try:
            async with asyncio.timeout(15), asyncio.TaskGroup() as tasks:
                tasks.create_task(commit_work())
                tasks.create_task(resolve_route())
        except* OperationalError as errors:
            pytest.fail(
                "Work/route admission aborted: " + ", ".join(_abort_identity(errors)),
                pytrace=False,
            )
    finally:
        await _cleanup_binding(rdb_engine, seeded)


@pytest.mark.parametrize("fence", ["agent", "binding", "resource_binding"])
async def test_authorization_fences_still_exclude_mutations(
    rdb_engine: AsyncEngine, latest_db_schema: None, fence: str
) -> None:
    """Allowing FK references must retain exact Agent/Binding writer exclusion."""
    del latest_db_schema
    seeded = await _seed_binding(rdb_engine, suffix=uuid4().hex[:8])
    channels = ExternalChannelRepository()
    writer_pid: asyncio.Future[int] = asyncio.get_running_loop().create_future()
    try:
        async with AsyncSession(rdb_engine) as holder:
            session = ReadWriteSession(holder)
            if fence == "agent":
                assert (
                    await channels.get_routable_route_by_id(
                        session, route_id=seeded.route_id
                    )
                    is not None
                )
                mutation = (
                    sa.update(RDBAgent)
                    .where(RDBAgent.id == seeded.owner_agent_id)
                    .values(enabled=False)
                )
            else:
                if fence == "binding":
                    assert (
                        await channels.lock_binding(
                            session, binding_id=seeded.binding_id
                        )
                        is not None
                    )
                else:
                    assert (
                        await channels.lock_connected_binding_by_resource(
                            session, resource_id=seeded.resource_id
                        )
                        is not None
                    )
                mutation = (
                    sa.update(RDBExternalChannelBinding)
                    .where(RDBExternalChannelBinding.id == seeded.binding_id)
                    .values(disconnected_at=datetime.now(UTC))
                )
            holder_pid = await holder.scalar(sa.text("SELECT pg_backend_pid()"))
            assert isinstance(holder_pid, int)

            async def mutate() -> None:
                async with AsyncSession(rdb_engine) as raw:
                    pid = await raw.scalar(sa.text("SELECT pg_backend_pid()"))
                    assert isinstance(pid, int)
                    writer_pid.set_result(pid)
                    await raw.execute(mutation)
                    await raw.rollback()

            async with asyncio.timeout(15), asyncio.TaskGroup() as tasks:
                task = tasks.create_task(mutate())
                await _wait_for_database_blocker(
                    rdb_engine,
                    blocked_pid=await writer_pid,
                    blocker_pid=holder_pid,
                )
                assert not task.done()
                await holder.rollback()
    finally:
        await _cleanup_binding(rdb_engine, seeded)
