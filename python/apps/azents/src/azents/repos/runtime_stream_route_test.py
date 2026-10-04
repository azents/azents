"""Real PostgreSQL route transactions, exact epochs and independent races."""

import asyncio
import dataclasses
import hashlib
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import datetime, timedelta
from uuid import uuid4

import pytest
import sqlalchemy as sa
from sqlalchemy import event
from sqlalchemy.engine import Connection, ExecutionContext
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from azents.rdb.models.agent import RDBAgent
from azents.rdb.models.agent_runtime import RDBAgentRuntime
from azents.rdb.models.runtime_web import RDBRuntimeWebSessionRoute
from azents.rdb.models.workspace import RDBWorkspace
from azents.rdb.session import SessionManager
from azents.rdb.session_capabilities import ReadWriteSession, WriteSession
from azents.repos.agent_session.repository_test import _create_agent, _create_workspace
from azents.repos.runtime_stream_route import RuntimeStreamRouteOperationRepository
from azents.repos.runtime_stream_route_data import RuntimeStreamRouteEpoch
from azents.repos.runtime_web.data import RuntimeWebSessionRoute
from azents.repos.runtime_web.session_route_repository import (
    RuntimeWebSessionRouteConflict,
    RuntimeWebSessionRouteRepository,
)


def digest(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def epoch(route: RuntimeWebSessionRoute) -> RuntimeStreamRouteEpoch:
    return RuntimeStreamRouteEpoch(
        route.runtime_id,
        route.owner_boot_id,
        route.session_lease_id,
        route.lease_generation,
    )


class RouteManager:
    """Observe real sessions and authoritative transaction timestamps."""

    def __init__(self, manager: SessionManager[WriteSession]) -> None:
        self.manager = manager
        self.active = False
        self.sessions: list[WriteSession] = []
        self.server_times: list[datetime] = []

    @asynccontextmanager
    async def __call__(self) -> AsyncIterator[WriteSession]:
        assert not self.active, "No nesting of completed route operations"
        self.active = True
        try:
            async with self.manager() as session:
                self.sessions.append(session)
                server_time = await session.write_session.scalar(
                    sa.select(sa.func.now())
                )
                assert isinstance(server_time, datetime)
                self.server_times.append(server_time)
                yield session
        finally:
            self.active = False

    def assert_closed(self) -> None:
        assert not self.active
        assert all(
            not session.write_session.in_transaction() for session in self.sessions
        )


@dataclasses.dataclass(frozen=True)
class RouteFixture:
    runtime_id: str
    workspace_id: str
    agent_id: str
    manager: RouteManager
    repository: RuntimeStreamRouteOperationRepository


async def route_fixture(
    manager: SessionManager[WriteSession],
    name: str,
) -> RouteFixture:
    observed = RouteManager(manager)
    async with manager() as session:
        workspace_id = await _create_workspace(session, name)
        agent_id = await _create_agent(
            session, workspace_id, name, create_runtime=False
        )
        runtime = RDBAgentRuntime(workspace_id=workspace_id, agent_id=agent_id)
        runtime.desired_generation = 3
        runtime.runner_generation = 4
        session.write_session.add(runtime)
        await session.write_session.flush()
        runtime_id = runtime.id
    return RouteFixture(
        runtime_id,
        workspace_id,
        agent_id,
        observed,
        RuntimeStreamRouteOperationRepository(
            observed, RuntimeWebSessionRouteRepository()
        ),
    )


async def acquire(
    fixture: RouteFixture,
    *,
    repository: RuntimeStreamRouteOperationRepository | None = None,
    boot: str = "owner-a",
    lease_seconds: float = 90,
) -> RuntimeWebSessionRoute:
    operation = fixture.repository if repository is None else repository
    return await operation.acquire(
        runtime_id=fixture.runtime_id,
        desired_generation=3,
        runner_generation=4,
        owner_replica_id="replica-a",
        owner_boot_id=boot,
        owner_address="replica-a.internal:8032",
        join_nonce_hash=digest("nonce"),
        protocol_fingerprint=digest("protocol"),
        lease_seconds=lease_seconds,
    )


async def stored_route(fixture: RouteFixture) -> RuntimeWebSessionRoute | None:
    async with fixture.manager.manager() as session:
        row = await session.write_session.get(
            RDBRuntimeWebSessionRoute, fixture.runtime_id
        )
        return None if row is None else RuntimeWebSessionRouteRepository._route(row)


async def expire(fixture: RouteFixture) -> None:
    async with fixture.manager.manager() as session:
        await session.write_session.execute(
            sa.update(RDBRuntimeWebSessionRoute)
            .where(RDBRuntimeWebSessionRoute.runtime_id == fixture.runtime_id)
            .values(
                created_at=sa.func.now() - timedelta(seconds=3),
                lease_expires_at=sa.func.now() - timedelta(seconds=1),
                draining_at=sa.case(
                    (
                        RDBRuntimeWebSessionRoute.draining_at.is_not(None),
                        sa.func.now() - timedelta(seconds=2),
                    ),
                    else_=None,
                ),
            )
        )


async def resolve(fixture: RouteFixture) -> RuntimeWebSessionRoute | None:
    return await fixture.repository.resolve(
        runtime_id=fixture.runtime_id,
        desired_generation=3,
        runner_generation=4,
        protocol_fingerprint=digest("protocol"),
    )


async def consume(
    fixture: RouteFixture,
    route: RuntimeWebSessionRoute,
    *,
    repository: RuntimeStreamRouteOperationRepository | None = None,
) -> RuntimeWebSessionRoute:
    operation = fixture.repository if repository is None else repository
    return await operation.consume_join(
        epoch=epoch(route),
        protocol_fingerprint=route.protocol_fingerprint,
        join_nonce_hash=route.join_nonce_hash,
        join_deadline_at=route.lease_expires_at,
    )


async def test_completed_routes_preserve_sql_clock_and_atomic_nonce(
    rdb_session_manager: SessionManager[WriteSession],
) -> None:
    fixture = await route_fixture(rdb_session_manager, "completed-route-clock")
    route = await acquire(fixture, lease_seconds=30)
    assert route.lease_expires_at == fixture.manager.server_times[-1] + timedelta(
        seconds=30
    )
    assert await resolve(fixture) == route
    renewed = await fixture.repository.renew(
        epoch=epoch(route),
        protocol_fingerprint=route.protocol_fingerprint,
        lease_seconds=60,
    )
    assert renewed.lease_expires_at == fixture.manager.server_times[-1] + timedelta(
        seconds=60
    )
    consumed = await consume(fixture, renewed)
    assert consumed.join_nonce_hash == digest(
        f"consumed:{route.session_lease_id}:{route.lease_generation}"
    )
    with pytest.raises(RuntimeWebSessionRouteConflict):
        await consume(fixture, renewed)
    assert await stored_route(fixture) == consumed
    draining = await fixture.repository.mark_draining(epoch(route))
    assert draining.draining_at == fixture.manager.server_times[-1]
    assert await fixture.repository.mark_draining(epoch(route)) == draining
    assert await resolve(fixture) is None
    assert await fixture.repository.release(epoch(route))
    assert not await fixture.repository.release(epoch(route))
    fixture.manager.assert_closed()


@pytest.mark.parametrize(
    "part", ["owner_boot_id", "session_lease_id", "lease_generation"]
)
async def test_stale_epoch_never_changes_current_route(
    rdb_session_manager: SessionManager[WriteSession],
    part: str,
) -> None:
    fixture = await route_fixture(rdb_session_manager, f"completed-route-stale-{part}")
    route = await acquire(fixture)
    replacement: object = 2 if part == "lease_generation" else "stale"
    stale = dataclasses.replace(epoch(route), **{part: replacement})
    with pytest.raises(RuntimeWebSessionRouteConflict):
        await fixture.repository.renew(
            epoch=stale,
            protocol_fingerprint=route.protocol_fingerprint,
            lease_seconds=60,
        )
    with pytest.raises(RuntimeWebSessionRouteConflict):
        await fixture.repository.consume_join(
            epoch=stale,
            protocol_fingerprint=route.protocol_fingerprint,
            join_nonce_hash=route.join_nonce_hash,
            join_deadline_at=route.lease_expires_at,
        )
    with pytest.raises(RuntimeWebSessionRouteConflict):
        await fixture.repository.mark_draining(stale)
    assert not await fixture.repository.release(stale)
    assert await stored_route(fixture) == route
    fixture.manager.assert_closed()


async def test_expired_replacement_increments_generation_and_release_has_no_ttl_guard(
    rdb_session_manager: SessionManager[WriteSession],
) -> None:
    fixture = await route_fixture(rdb_session_manager, "completed-route-replace")
    old = await acquire(fixture)
    with pytest.raises(RuntimeWebSessionRouteConflict, match="already owned"):
        await acquire(fixture, boot="owner-b")
    await expire(fixture)
    assert await resolve(fixture) is None
    with pytest.raises(RuntimeWebSessionRouteConflict):
        await fixture.repository.renew(
            epoch=epoch(old),
            protocol_fingerprint=old.protocol_fingerprint,
            lease_seconds=60,
        )
    new = await acquire(fixture, boot="owner-b")
    assert new.lease_generation == old.lease_generation + 1
    assert new.session_lease_id != old.session_lease_id
    assert not await fixture.repository.release(epoch(old))
    await fixture.repository.mark_draining(epoch(new))
    await expire(fixture)
    assert await fixture.repository.release(epoch(new))
    fixture.manager.assert_closed()


@pytest.mark.parametrize("generation", ["desired_generation", "runner_generation"])
@pytest.mark.parametrize("operation", ["renew", "consume", "resolve"])
async def test_changed_runtime_generation_keeps_current_route_unchanged(
    rdb_session_manager: SessionManager[WriteSession],
    generation: str,
    operation: str,
) -> None:
    fixture = await route_fixture(
        rdb_session_manager, f"completed-route-{generation}-{operation}"
    )
    route = await acquire(fixture)
    async with rdb_session_manager() as session:
        await session.write_session.execute(
            sa.update(RDBAgentRuntime)
            .where(RDBAgentRuntime.id == fixture.runtime_id)
            .values(**{generation: 5})
        )
    if operation == "resolve":
        assert await resolve(fixture) is None
    else:
        with pytest.raises(RuntimeWebSessionRouteConflict):
            if operation == "renew":
                await fixture.repository.renew(
                    epoch=epoch(route),
                    protocol_fingerprint=route.protocol_fingerprint,
                    lease_seconds=60,
                )
            else:
                await consume(fixture, route)
    assert await stored_route(fixture) == route
    assert await fixture.repository.release(epoch(route)), (
        "Release adds no generation check"
    )
    fixture.manager.assert_closed()


@pytest.mark.parametrize("field", ["protocol", "nonce", "deadline", "draining"])
async def test_join_exact_authority_mismatch_does_not_consume_nonce(
    rdb_session_manager: SessionManager[WriteSession],
    field: str,
) -> None:
    fixture = await route_fixture(rdb_session_manager, f"completed-join-{field}")
    route = await acquire(fixture)
    if field == "draining":
        route = await fixture.repository.mark_draining(epoch(route))
    with pytest.raises(RuntimeWebSessionRouteConflict):
        await fixture.repository.consume_join(
            epoch=epoch(route),
            protocol_fingerprint=digest("wrong")
            if field == "protocol"
            else route.protocol_fingerprint,
            join_nonce_hash=digest("wrong")
            if field == "nonce"
            else route.join_nonce_hash,
            join_deadline_at=fixture.manager.server_times[0]
            if field == "deadline"
            else route.lease_expires_at,
        )
    assert await stored_route(fixture) == route
    fixture.manager.assert_closed()


async def test_route_lock_order_retains_existing_asymmetry(
    rdb_session_manager: SessionManager[WriteSession],
) -> None:
    fixture = await route_fixture(rdb_session_manager, "completed-route-locks")
    statements: list[str] = []

    def observe(
        connection: Connection,
        cursor: object,
        statement: str,
        parameters: object,
        context: ExecutionContext,
        executemany: bool,
    ) -> None:
        del connection, cursor, parameters, context, executemany
        normalized = " ".join(statement.lower().split())
        if normalized.startswith("select") and "for update" in normalized:
            statements.append(normalized)

    @asynccontextmanager
    async def manager() -> AsyncIterator[WriteSession]:
        async with fixture.manager() as session:
            connection = await session.write_session.connection()
            event.listen(connection.sync_connection, "before_cursor_execute", observe)
            try:
                yield session
            finally:
                event.remove(
                    connection.sync_connection, "before_cursor_execute", observe
                )

    repository = RuntimeStreamRouteOperationRepository(
        manager, RuntimeWebSessionRouteRepository()
    )
    route = await acquire(fixture, repository=repository)
    assert len(statements) == 2
    assert "from agent_runtimes" in statements[0]
    assert "from runtime_web_session_routes" in statements[1]
    for operation in ("renew", "resolve", "consume"):
        statements.clear()
        if operation == "renew":
            await repository.renew(
                epoch=epoch(route),
                protocol_fingerprint=route.protocol_fingerprint,
                lease_seconds=90,
            )
        elif operation == "resolve":
            await repository.resolve(
                runtime_id=fixture.runtime_id,
                desired_generation=3,
                runner_generation=4,
                protocol_fingerprint=route.protocol_fingerprint,
            )
        else:
            await consume(fixture, route, repository=repository)
        assert len(statements) == 2
        assert "from runtime_web_session_routes" in statements[0]
        assert "from agent_runtimes" in statements[1]
    fixture.manager.assert_closed()


class RouteWriteFault(RuntimeWebSessionRouteRepository):
    """Fail after the real narrow primitive flushed its selected mutation."""

    def __init__(self, stage: str, error: BaseException) -> None:
        self.stage = stage
        self.error = error

    async def acquire(
        self,
        session: WriteSession,
        *,
        runtime_id: str,
        desired_generation: int,
        runner_generation: int,
        owner_replica_id: str,
        owner_boot_id: str,
        owner_address: str,
        join_nonce_hash: str,
        protocol_fingerprint: str,
        lease_seconds: float,
    ) -> RuntimeWebSessionRoute:
        result = await super().acquire(
            session,
            runtime_id=runtime_id,
            desired_generation=desired_generation,
            runner_generation=runner_generation,
            owner_replica_id=owner_replica_id,
            owner_boot_id=owner_boot_id,
            owner_address=owner_address,
            join_nonce_hash=join_nonce_hash,
            protocol_fingerprint=protocol_fingerprint,
            lease_seconds=lease_seconds,
        )
        if self.stage == "acquire":
            assert session.read_session.in_transaction()
            raise self.error
        return result

    async def renew(
        self,
        session: WriteSession,
        *,
        runtime_id: str,
        owner_boot_id: str,
        session_lease_id: str,
        lease_generation: int,
        protocol_fingerprint: str,
        lease_seconds: float,
    ) -> RuntimeWebSessionRoute:
        result = await super().renew(
            session,
            runtime_id=runtime_id,
            owner_boot_id=owner_boot_id,
            session_lease_id=session_lease_id,
            lease_generation=lease_generation,
            protocol_fingerprint=protocol_fingerprint,
            lease_seconds=lease_seconds,
        )
        if self.stage == "renew":
            assert session.read_session.in_transaction()
            raise self.error
        return result

    async def consume_join(
        self,
        session: WriteSession,
        *,
        runtime_id: str,
        owner_boot_id: str,
        session_lease_id: str,
        lease_generation: int,
        protocol_fingerprint: str,
        join_nonce_hash: str,
        join_deadline_at: datetime,
    ) -> RuntimeWebSessionRoute:
        result = await super().consume_join(
            session,
            runtime_id=runtime_id,
            owner_boot_id=owner_boot_id,
            session_lease_id=session_lease_id,
            lease_generation=lease_generation,
            protocol_fingerprint=protocol_fingerprint,
            join_nonce_hash=join_nonce_hash,
            join_deadline_at=join_deadline_at,
        )
        if self.stage == "consume_join":
            assert session.read_session.in_transaction()
            raise self.error
        return result

    async def mark_draining(
        self,
        session: WriteSession,
        *,
        runtime_id: str,
        owner_boot_id: str,
        session_lease_id: str,
        lease_generation: int,
    ) -> RuntimeWebSessionRoute:
        result = await super().mark_draining(
            session,
            runtime_id=runtime_id,
            owner_boot_id=owner_boot_id,
            session_lease_id=session_lease_id,
            lease_generation=lease_generation,
        )
        if self.stage == "mark_draining":
            assert session.read_session.in_transaction()
            raise self.error
        return result

    async def release(
        self,
        session: WriteSession,
        *,
        runtime_id: str,
        owner_boot_id: str,
        session_lease_id: str,
        lease_generation: int,
    ) -> bool:
        result = await super().release(
            session,
            runtime_id=runtime_id,
            owner_boot_id=owner_boot_id,
            session_lease_id=session_lease_id,
            lease_generation=lease_generation,
        )
        if self.stage == "release":
            assert session.read_session.in_transaction()
            raise self.error
        return result


@pytest.mark.parametrize(
    "operation", ["acquire", "renew", "consume_join", "mark_draining", "release"]
)
@pytest.mark.parametrize("cancel", [False, True])
async def test_real_route_write_fault_or_cancellation_rolls_back_exact_mutation(
    rdb_session_manager: SessionManager[WriteSession],
    operation: str,
    cancel: bool,
) -> None:
    fixture = await route_fixture(
        rdb_session_manager, f"route-rollback-{operation}-{cancel}"
    )
    route = await acquire(fixture)
    if operation == "acquire":
        await expire(fixture)
    before = await stored_route(fixture)
    error = (
        asyncio.CancelledError("after real route write")
        if cancel
        else RuntimeError("after real route write")
    )
    repository = RuntimeStreamRouteOperationRepository(
        fixture.manager, RouteWriteFault(operation, error)
    )
    with pytest.raises(type(error), match="after real route write"):
        if operation == "acquire":
            await acquire(fixture, repository=repository, boot="replacement")
        elif operation == "renew":
            await repository.renew(
                epoch=epoch(route),
                protocol_fingerprint=route.protocol_fingerprint,
                lease_seconds=120,
            )
        elif operation == "consume_join":
            await consume(fixture, route, repository=repository)
        elif operation == "mark_draining":
            await repository.mark_draining(epoch(route))
        else:
            await repository.release(epoch(route))
    fixture.manager.assert_closed()
    assert await stored_route(fixture) == before


async def test_resolve_only_suppresses_existing_runtime_route_conflict(
    rdb_session_manager: SessionManager[WriteSession],
) -> None:
    fixture = await route_fixture(rdb_session_manager, "route-resolve-error")
    route = await acquire(fixture)

    class FailedRuntimeValidation(RuntimeWebSessionRouteRepository):
        async def _validate_runtime(
            self,
            session: WriteSession,
            *,
            runtime_id: str,
            desired_generation: int,
            runner_generation: int,
        ) -> None:
            await super()._validate_runtime(
                session,
                runtime_id=runtime_id,
                desired_generation=desired_generation,
                runner_generation=runner_generation,
            )
            raise RuntimeError("validation database failure")

    repository = RuntimeStreamRouteOperationRepository(
        fixture.manager, FailedRuntimeValidation()
    )
    with pytest.raises(RuntimeError, match="validation database failure"):
        await repository.resolve(
            runtime_id=fixture.runtime_id,
            desired_generation=3,
            runner_generation=4,
            protocol_fingerprint=route.protocol_fingerprint,
        )
    assert await stored_route(fixture) == route
    fixture.manager.assert_closed()


async def cleanup_committed_route(
    manager: SessionManager[WriteSession], fixture: RouteFixture
) -> None:
    """Delete only the independent race's committed fixture identity graph."""
    async with manager() as session:
        await session.write_session.execute(
            sa.delete(RDBAgentRuntime).where(RDBAgentRuntime.id == fixture.runtime_id)
        )
        await session.write_session.execute(
            sa.delete(RDBAgent).where(RDBAgent.id == fixture.agent_id)
        )
        await session.write_session.execute(
            sa.delete(RDBWorkspace).where(RDBWorkspace.id == fixture.workspace_id)
        )


@pytest.mark.parametrize("operation", ["nonce", "acquire", "replacement"])
async def test_independent_route_transactions_have_exactly_one_winner(
    rdb_engine: AsyncEngine,
    latest_db_schema: None,
    operation: str,
) -> None:
    """A real two-connection barrier proves nonce/CAS serialization, not mocks."""
    del latest_db_schema

    @asynccontextmanager
    async def manager() -> AsyncIterator[WriteSession]:
        async with AsyncSession(rdb_engine, expire_on_commit=False) as _raw_session:
            session = ReadWriteSession(_raw_session)
            try:
                yield session
            except BaseException:
                await session.write_session.rollback()
                raise
            else:
                await session.write_session.commit()

    fixture = await route_fixture(manager, f"route-race-{uuid4().hex[:12]}")
    route: RuntimeWebSessionRoute | None = None
    barrier = asyncio.Barrier(2)
    pids: list[int] = []
    tasks: list[asyncio.Task[RuntimeWebSessionRoute]] = []

    @asynccontextmanager
    async def contender_manager() -> AsyncIterator[WriteSession]:
        async with manager() as session:
            pid = await session.read_session.scalar(sa.text("SELECT pg_backend_pid()"))
            assert isinstance(pid, int)
            pids.append(pid)
            await barrier.wait()
            yield session

    async def contender(boot: str) -> RuntimeWebSessionRoute:
        repository = RuntimeStreamRouteOperationRepository(
            contender_manager, RuntimeWebSessionRouteRepository()
        )
        if operation == "nonce":
            assert route is not None
            return await consume(fixture, route, repository=repository)
        return await acquire(fixture, repository=repository, boot=boot)

    try:
        if operation in {"nonce", "replacement"}:
            route = await acquire(fixture)
            if operation == "replacement":
                await expire(fixture)
        tasks = [
            asyncio.create_task(contender("owner-a")),
            asyncio.create_task(contender("owner-b")),
        ]
        results = await asyncio.wait_for(
            asyncio.gather(*tasks, return_exceptions=True), timeout=10
        )
        winners = [
            result for result in results if isinstance(result, RuntimeWebSessionRoute)
        ]
        losers = [
            result
            for result in results
            if isinstance(result, RuntimeWebSessionRouteConflict)
        ]
        assert len(winners) == len(losers) == 1
        assert len(pids) == 2 and pids[0] != pids[1]
        stored = await stored_route(fixture)
        assert stored is not None
        assert stored == winners[0]
        if operation == "replacement":
            assert route is not None
            assert stored.lease_generation == route.lease_generation + 1
            assert stored.session_lease_id != route.session_lease_id
        elif operation == "nonce":
            assert route is not None
            assert stored.join_nonce_hash != route.join_nonce_hash
        fixture.manager.assert_closed()
    finally:
        for task in tasks:
            if not task.done():
                task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        await cleanup_committed_route(manager, fixture)


@pytest.mark.parametrize(
    "change",
    [
        "generation-renew",
        "generation-resolve",
        "generation-consume",
        "expired-renew",
        "replacement-release",
    ],
)
async def test_independent_uncommitted_authority_change_blocks_exact_contender(
    rdb_engine: AsyncEngine,
    latest_db_schema: None,
    change: str,
) -> None:
    """Distinct PIDs and PostgreSQL blocking identify real lock/CAS boundaries."""
    del latest_db_schema

    @asynccontextmanager
    async def manager() -> AsyncIterator[WriteSession]:
        async with AsyncSession(rdb_engine, expire_on_commit=False) as _raw_session:
            session = ReadWriteSession(_raw_session)
            try:
                yield session
            except BaseException:
                await session.write_session.rollback()
                raise
            else:
                await session.write_session.commit()

    fixture = await route_fixture(manager, f"route-block-{uuid4().hex[:12]}")
    route = await acquire(fixture)
    if change == "replacement-release":
        await expire(fixture)
    first_locked = asyncio.Event()
    second_started = asyncio.Event()
    release = asyncio.Event()
    pids: list[int] = []
    opened: list[WriteSession] = []
    replacement: list[RuntimeWebSessionRoute] = []

    async def first() -> None:
        async with manager() as session:
            opened.append(session)
            pid = await session.read_session.scalar(sa.text("SELECT pg_backend_pid()"))
            assert isinstance(pid, int)
            pids.append(pid)
            if change.startswith("generation"):
                await session.write_session.execute(
                    sa.update(RDBAgentRuntime)
                    .where(RDBAgentRuntime.id == fixture.runtime_id)
                    .values(desired_generation=4)
                )
            elif change == "expired-renew":
                await session.write_session.execute(
                    sa.update(RDBRuntimeWebSessionRoute)
                    .where(RDBRuntimeWebSessionRoute.runtime_id == fixture.runtime_id)
                    .values(
                        created_at=sa.func.now() - timedelta(seconds=3),
                        lease_expires_at=sa.func.now() - timedelta(seconds=1),
                    )
                )
            else:
                replacement.append(
                    await RuntimeWebSessionRouteRepository().acquire(
                        session,
                        runtime_id=fixture.runtime_id,
                        desired_generation=3,
                        runner_generation=4,
                        owner_replica_id="replica-b",
                        owner_boot_id="owner-b",
                        owner_address="replica-b.internal:8032",
                        join_nonce_hash=digest("replacement"),
                        protocol_fingerprint=route.protocol_fingerprint,
                        lease_seconds=90,
                    )
                )
            first_locked.set()
            await release.wait()

    @asynccontextmanager
    async def second_manager() -> AsyncIterator[WriteSession]:
        await first_locked.wait()
        async with manager() as session:
            opened.append(session)
            pid = await session.read_session.scalar(sa.text("SELECT pg_backend_pid()"))
            assert isinstance(pid, int)
            pids.append(pid)
            second_started.set()
            yield session

    async def second() -> None:
        repository = RuntimeStreamRouteOperationRepository(
            second_manager, RuntimeWebSessionRouteRepository()
        )
        if change == "generation-resolve":
            assert (
                await repository.resolve(
                    runtime_id=fixture.runtime_id,
                    desired_generation=3,
                    runner_generation=4,
                    protocol_fingerprint=route.protocol_fingerprint,
                )
                is None
            )
        elif change == "replacement-release":
            assert not await repository.release(epoch(route))
        else:
            with pytest.raises(RuntimeWebSessionRouteConflict):
                if change == "generation-consume":
                    await consume(fixture, route, repository=repository)
                else:
                    await repository.renew(
                        epoch=epoch(route),
                        protocol_fingerprint=route.protocol_fingerprint,
                        lease_seconds=120,
                    )

    tasks: list[asyncio.Task[None]] = []
    try:
        tasks = [asyncio.create_task(first()), asyncio.create_task(second())]
        await asyncio.wait_for(second_started.wait(), timeout=10)
        assert len(pids) == 2 and pids[0] != pids[1]
        async with asyncio.timeout(10):
            async with manager() as observer:
                while True:
                    blockers = await observer.write_session.scalar(
                        sa.text("SELECT pg_blocking_pids(:pid)"), {"pid": pids[1]}
                    )
                    if pids[0] in blockers:
                        break
                    await asyncio.sleep(0.01)
        assert not tasks[1].done()
        release.set()
        await asyncio.wait_for(asyncio.gather(*tasks), timeout=10)
        current = await stored_route(fixture)
        assert current is not None
        if change == "replacement-release":
            assert current == replacement[0]
            assert current.lease_generation == route.lease_generation + 1
        elif change.startswith("generation"):
            assert current == route
        else:
            assert current.session_lease_id == route.session_lease_id
            assert current.lease_expires_at < route.lease_expires_at
            assert current.join_nonce_hash == route.join_nonce_hash
        assert all(not session.read_session.in_transaction() for session in opened)
        fixture.manager.assert_closed()
    finally:
        release.set()
        for task in tasks:
            if not task.done():
                task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        await cleanup_committed_route(manager, fixture)
