"""Independent PostgreSQL connection/barrier races for Worker model groups."""

import asyncio
import dataclasses
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from typing import Literal
from uuid import uuid4

import pytest
import sqlalchemy as sa
from sqlalchemy.exc import OperationalError
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from azents.core.agent_session_data import AgentSession
from azents.core.enums import ModelCandidateClaimKind
from azents.core.worker_model_profile import ModelQuotaAdvanceResult
from azents.rdb.models.agent import RDBAgent
from azents.rdb.models.agent_runtime import RDBAgentRuntime
from azents.rdb.models.agent_session import RDBAgentSession
from azents.rdb.models.llm_provider_integration import RDBLLMProviderIntegration
from azents.rdb.models.model_candidate_health import RDBModelCandidateHealth
from azents.rdb.models.session_agent import RDBSessionAgent
from azents.rdb.models.session_agent_context import RDBSessionAgentContext
from azents.rdb.models.workspace import RDBWorkspace
from azents.rdb.session import SessionManager
from azents.repos.agent import AgentRepository
from azents.repos.agent.data import Agent
from azents.repos.agent_session import AgentSessionRepository
from azents.repos.session_execution import CanonicalExecutionOwnerGenerationStaleError
from azents.repos.worker_executor_model_test import (
    ModelAgents,
    ModelFault,
    ModelFixture,
    ModelGuard,
    ModelSessions,
    health,
    model_fixture,
    model_rows,
    prepare,
    quota_failure,
    reserve_primary,
    seed_retry,
    selected_profile,
)


@asynccontextmanager
async def independent_manager(
    engine: AsyncEngine,
) -> AsyncIterator[SessionManager[AsyncSession]]:
    """Allocate real independent connections, committing each completed scope."""

    @asynccontextmanager
    async def manager() -> AsyncIterator[AsyncSession]:
        async with AsyncSession(engine, expire_on_commit=False) as session:
            try:
                yield session
            except BaseException:
                await session.rollback()
                raise
            else:
                await session.commit()

    yield manager


async def backend_pid(session: AsyncSession) -> int:
    pid = await session.scalar(sa.text("SELECT pg_backend_pid()"))
    assert isinstance(pid, int)
    return pid


async def wait_blocked(
    manager: SessionManager[AsyncSession], waiter: int, holder: int
) -> None:
    """Use authoritative PostgreSQL blocking state rather than elapsed sleeps."""
    assert waiter != holder
    async with asyncio.timeout(10):
        async with manager() as observer:
            while True:
                blockers = await observer.scalar(
                    sa.text("SELECT pg_blocking_pids(:pid)"), {"pid": waiter}
                )
                if isinstance(blockers, list) and holder in blockers:
                    return


async def cleanup(manager: SessionManager[AsyncSession], fixture: ModelFixture) -> None:
    """Delete exactly this independently committed subject and its health rows."""
    async with manager() as session:
        await session.execute(
            sa.delete(RDBModelCandidateHealth).where(
                RDBModelCandidateHealth.workspace_id == fixture.workspace_id
            )
        )
        context_ids = sa.select(RDBSessionAgentContext.id).where(
            RDBSessionAgentContext.agent_id == fixture.agent_id
        )
        await session.execute(
            sa.update(RDBSessionAgentContext)
            .where(RDBSessionAgentContext.agent_id == fixture.agent_id)
            .values(root_session_agent_id=None)
        )
        await session.execute(
            sa.delete(RDBSessionAgent).where(
                RDBSessionAgent.context_id.in_(context_ids)
            )
        )
        await session.execute(
            sa.delete(RDBAgentSession).where(
                RDBAgentSession.agent_id == fixture.agent_id
            )
        )
        await session.execute(
            sa.delete(RDBSessionAgentContext).where(
                RDBSessionAgentContext.agent_id == fixture.agent_id
            )
        )
        await session.execute(
            sa.delete(RDBAgentRuntime).where(
                RDBAgentRuntime.agent_id == fixture.agent_id
            )
        )
        await session.execute(
            sa.delete(RDBAgent).where(RDBAgent.id == fixture.agent_id)
        )
        await session.execute(
            sa.delete(RDBLLMProviderIntegration).where(
                RDBLLMProviderIntegration.workspace_id == fixture.workspace_id
            )
        )
        await session.execute(
            sa.delete(RDBWorkspace).where(RDBWorkspace.id == fixture.workspace_id)
        )


class _PidAgents(ModelAgents):
    def __init__(
        self, fault: ModelFault, pids: list[int], entered: asyncio.Event
    ) -> None:
        super().__init__(fault)
        self.pids = pids
        self.entered = entered

    async def lock_by_id(self, session: AsyncSession, agent_id: str) -> Agent | None:
        self.pids.append(await backend_pid(session))
        self.entered.set()
        return await super().lock_by_id(session, agent_id)


@dataclasses.dataclass(frozen=True)
class _PidGuard(ModelGuard):
    pids: list[int]
    entered: asyncio.Event

    async def assert_owner_generation_in_session(
        self, session: AsyncSession, *, session_id: str, owner_generation: int
    ) -> None:
        self.pids.append(await backend_pid(session))
        self.entered.set()
        await super().assert_owner_generation_in_session(
            session, session_id=session_id, owner_generation=owner_generation
        )


class _ConflictSessions(ModelSessions):
    """Observe an actual existing NOWAIT contention attempt, then re-raise it."""

    def __init__(self, fault: ModelFault, conflicted: asyncio.Event) -> None:
        super().__init__(fault)
        self.conflicted = conflicted

    async def lock_execution_by_id(
        self, session: AsyncSession, agent_session_id: str
    ) -> AgentSession | None:
        try:
            return await super().lock_execution_by_id(session, agent_session_id)
        except OperationalError:
            self.conflicted.set()
            raise


async def finish_tasks(tasks: list[asyncio.Task[None]], release: asyncio.Event) -> None:
    release.set()
    for task in tasks:
        if not task.done():
            task.cancel()
    await asyncio.gather(*tasks, return_exceptions=True)


@pytest.mark.parametrize("first", ["selection", "configuration"])
async def test_profile_agent_lock_serializes_configuration_on_distinct_connections(
    rdb_engine: AsyncEngine,
    latest_db_schema: None,
    first: Literal["selection", "configuration"],
    record_property: Callable[[str, object], None],
) -> None:
    del latest_db_schema
    async with independent_manager(rdb_engine) as manager:
        fixture = await model_fixture(manager, f"model-profile-race-{uuid4().hex[:10]}")
        locked, release, entered = asyncio.Event(), asyncio.Event(), asyncio.Event()
        holder_pids: list[int] = []
        waiter_pids: list[int] = []
        selected_labels: list[str] = []
        tasks: list[asyncio.Task[None]] = []

        async def configuration(hold: bool) -> None:
            async with manager() as session:
                pid = await backend_pid(session)
                if hold:
                    holder_pids.append(pid)
                else:
                    waiter_pids.append(pid)
                    entered.set()
                assert (
                    await AgentRepository().lock_by_id(session, fixture.agent_id)
                    is not None
                )
                await session.execute(
                    sa.update(RDBAgent)
                    .where(RDBAgent.id == fixture.agent_id)
                    .values(main_model_label="alternate")
                )
                if hold:
                    locked.set()
                    await release.wait()

        async def selection() -> None:
            result = await fixture.repository.select_requested_profile(
                agent_id=fixture.agent_id,
                session_id=fixture.session_id,
                explicit_profile=None,
            )
            selected_labels.append(result.profile.model_target_label)

        try:
            if first == "selection":
                fixture.fault.stage = "agent_lock"
                fixture.fault.pause = True
                tasks.append(asyncio.create_task(selection()))
                await asyncio.wait_for(fixture.fault.reached.wait(), timeout=10)
                holder_pids.append(await backend_pid(fixture.manager.sessions[-1]))
                tasks.append(asyncio.create_task(configuration(False)))
                await asyncio.wait_for(entered.wait(), timeout=10)
            else:
                tasks.append(asyncio.create_task(configuration(True)))
                await asyncio.wait_for(locked.wait(), timeout=10)
                fixture = dataclasses.replace(
                    fixture,
                    repository=dataclasses.replace(
                        fixture.repository,
                        agent_repository=_PidAgents(
                            fixture.fault, waiter_pids, entered
                        ),
                    ),
                )
                tasks.append(asyncio.create_task(selection()))
                await asyncio.wait_for(entered.wait(), timeout=10)
            await wait_blocked(manager, waiter_pids[0], holder_pids[0])
            assert not tasks[1].done()
            release.set()
            fixture.fault.release.set()
            await asyncio.wait_for(asyncio.gather(*tasks), timeout=10)
            assert selected_labels == [
                "default" if first == "selection" else "alternate"
            ]
            fixture.fault.stage = None
            fixture.fault.pause = False
            assert (
                await selected_profile(fixture)
            ).profile.model_target_label == "alternate"
            fixture.manager.assert_closed()
            record_property("holder_backend_pid", holder_pids[0])
            record_property("contender_backend_pid", waiter_pids[0])
            record_property("lock_witness", "pg_blocking_pids")
        finally:
            fixture.fault.release.set()
            await finish_tasks(tasks, release)
            await cleanup(manager, fixture)


@pytest.mark.parametrize("first", ["quota", "takeover"])
async def test_quota_guard_and_takeover_serialize_real_health_writes_on_distinct_pids(
    rdb_engine: AsyncEngine,
    latest_db_schema: None,
    first: Literal["quota", "takeover"],
    record_property: Callable[[str, object], None],
) -> None:
    del latest_db_schema
    async with independent_manager(rdb_engine) as manager:
        fixture = await model_fixture(manager, f"model-owner-race-{uuid4().hex[:10]}")
        prepared = await prepare(fixture)
        await seed_retry(fixture)
        before = await model_rows(fixture)
        locked, release, entered = asyncio.Event(), asyncio.Event(), asyncio.Event()
        conflicted = asyncio.Event()
        holder_pids: list[int] = []
        waiter_pids: list[int] = []
        results: list[ModelQuotaAdvanceResult] = []
        tasks: list[asyncio.Task[None]] = []

        async def takeover(hold: bool) -> None:
            async with manager() as session:
                pid = await backend_pid(session)
                if hold:
                    holder_pids.append(pid)
                else:
                    waiter_pids.append(pid)
                    entered.set()
                assert (
                    await AgentSessionRepository().claim_owner_generation(
                        session, fixture.session_id
                    )
                    == fixture.generation + 1
                )
                if hold:
                    locked.set()
                    await release.wait()

        async def quota() -> None:
            if first == "takeover":
                with pytest.raises(CanonicalExecutionOwnerGenerationStaleError):
                    await fixture.repository.advance_after_quota(
                        session_id=fixture.session_id,
                        run_id=fixture.run_id,
                        owner_generation=fixture.generation,
                        workspace_id=fixture.workspace_id,
                        failure=quota_failure(prepared.selection.operation, "sampling"),
                    )
            else:
                results.append(
                    await fixture.repository.advance_after_quota(
                        session_id=fixture.session_id,
                        run_id=fixture.run_id,
                        owner_generation=fixture.generation,
                        workspace_id=fixture.workspace_id,
                        failure=quota_failure(prepared.selection.operation, "sampling"),
                    )
                )

        try:
            if first == "quota":
                fixture.fault.stage = "renew"
                fixture.fault.pause = True
                tasks.append(asyncio.create_task(quota()))
                await asyncio.wait_for(fixture.fault.reached.wait(), timeout=10)
                holder_pids.append(await backend_pid(fixture.manager.sessions[-1]))
                tasks.append(asyncio.create_task(takeover(False)))
                await asyncio.wait_for(entered.wait(), timeout=10)
            else:
                tasks.append(asyncio.create_task(takeover(True)))
                await asyncio.wait_for(locked.wait(), timeout=10)
                original = fixture.repository.worker_session_repository
                assert isinstance(original, ModelGuard)
                guard = _PidGuard(
                    original.session_manager,
                    _ConflictSessions(original.fault, conflicted),
                    original.agent_run_repository,
                    original.mailbox_item_repository,
                    original.terminal_finalization_repository,
                    original.fault,
                    waiter_pids,
                    entered,
                )
                fixture = dataclasses.replace(
                    fixture,
                    repository=dataclasses.replace(
                        fixture.repository, worker_session_repository=guard
                    ),
                )
                tasks.append(asyncio.create_task(quota()))
                await asyncio.wait_for(entered.wait(), timeout=10)
            if first == "takeover":
                await asyncio.wait_for(conflicted.wait(), timeout=10)
                assert waiter_pids[0] != holder_pids[0]
            else:
                await wait_blocked(manager, waiter_pids[0], holder_pids[0])
            assert not tasks[1].done()
            release.set()
            fixture.fault.release.set()
            await asyncio.wait_for(asyncio.gather(*tasks), timeout=10)
            current, run = await model_rows(fixture)
            assert current.owner_generation == fixture.generation + 1
            if first == "quota":
                assert len(results) == 1 and not results[0].exhausted
                assert (
                    run.model_operation_state is not None
                    and run.model_operation_state.foreground == results[0].operation
                )
                assert run.retry_state is None and run.model_call_started_at is None
                assert (await health(fixture, fixture.primary)).health is not None
            else:
                assert (
                    run == before.run
                    and (await health(fixture, fixture.primary)).health is None
                )
            fixture.manager.assert_closed()
            record_property("holder_backend_pid", holder_pids[0])
            record_property("contender_backend_pid", waiter_pids[0])
            record_property(
                "lock_witness",
                "NOWAIT OperationalError"
                if first == "takeover"
                else "pg_blocking_pids",
            )
        finally:
            fixture.fault.release.set()
            await finish_tasks(tasks, release)
            await cleanup(manager, fixture)


async def test_reservation_transfer_clear_excludes_stale_cas_on_distinct_pids(
    rdb_engine: AsyncEngine,
    latest_db_schema: None,
    record_property: Callable[[str, object], None],
) -> None:
    del latest_db_schema
    async with independent_manager(rdb_engine) as manager:
        fixture = await model_fixture(
            manager, f"model-reservation-race-{uuid4().hex[:10]}"
        )
        reservation = await reserve_primary(fixture)
        selected = await selected_profile(fixture)
        fixture.fault.stage = "transfer"
        fixture.fault.pause = True
        entered, release = asyncio.Event(), asyncio.Event()
        contender_pids: list[int] = []
        changed: list[bool] = []
        tasks: list[asyncio.Task[None]] = []

        async def prepare_reserved() -> None:
            result = await fixture.repository.prepare_fresh(
                agent_id=fixture.agent_id,
                session_id=fixture.session_id,
                run_id=fixture.run_id,
                owner_generation=fixture.generation,
                selected=selected,
                override=None,
                replace_operation=False,
            )
            assert result.success

        async def clear_stale() -> None:
            async with manager() as session:
                contender_pids.append(await backend_pid(session))
                entered.set()
                result = await AgentSessionRepository().set_primary_model_reservation(
                    session,
                    session_id=fixture.session_id,
                    reservation=None,
                    expected_reservation_generation=reservation.reservation_generation,
                )
                changed.append(result is not None)

        try:
            tasks.append(asyncio.create_task(prepare_reserved()))
            await asyncio.wait_for(fixture.fault.reached.wait(), timeout=10)
            holder_pid = await backend_pid(fixture.manager.sessions[-1])
            tasks.append(asyncio.create_task(clear_stale()))
            await asyncio.wait_for(entered.wait(), timeout=10)
            await wait_blocked(manager, contender_pids[0], holder_pid)
            assert not tasks[1].done()
            fixture.fault.release.set()
            await asyncio.wait_for(asyncio.gather(*tasks), timeout=10)
            assert changed == [False]
            current, run = await model_rows(fixture)
            assert current.primary_model_reservation is None
            assert (
                run.model_operation_state is not None
                and run.model_operation_state.foreground is not None
            )
            observation = await health(fixture, fixture.primary)
            assert (
                observation.health is not None
                and observation.health.claim_kind is ModelCandidateClaimKind.PROBE
            )
            assert (
                observation.health.claim_owner_id
                == run.model_operation_state.foreground.operation_id
            )
            fixture.manager.assert_closed()
            record_property("holder_backend_pid", holder_pid)
            record_property("contender_backend_pid", contender_pids[0])
            record_property("lock_witness", "pg_blocking_pids")
        finally:
            fixture.fault.release.set()
            await finish_tasks(tasks, release)
            await cleanup(manager, fixture)
