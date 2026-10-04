"""PostgreSQL contention regression for completed-run idle admission."""

import asyncio
from uuid import uuid4

import pytest
import sqlalchemy as sa
from psycopg.errors import LockNotAvailable
from sqlalchemy.exc import OperationalError
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from azents.core.agent_session_data import AgentSession, AgentSessionCreate
from azents.core.enums import AgentSessionProductMode
from azents.repos.agent_session import AgentSessionRepository
from azents.repos.agent_session.repository_test import (
    _create_agent,
    _create_workspace,
)
from azents.worker.session.idle_continuation_test import (
    _Broker,
    _ContinuationRecorder,
    _EventPublisher,
    _service,
)


class _ObservedSessionRepository(AgentSessionRepository):
    """Observe a real NOWAIT admission collision without altering retry behavior."""

    def __init__(self) -> None:
        self.tree_admission_deferred = asyncio.Event()

    async def lock_execution_by_id(
        self,
        session: AsyncSession,
        agent_session_id: str,
    ) -> AgentSession | None:
        """Record the database's nonblocking tree-admission rejection."""
        try:
            return await super().lock_execution_by_id(session, agent_session_id)
        except OperationalError as error:
            if isinstance(error.orig, LockNotAvailable):
                self.tree_admission_deferred.set()
            raise


async def _wait_for_database_blocker(
    engine: AsyncEngine,
    *,
    blocked_pid: int,
    blocker_pid: int,
) -> None:
    """Observe an actual lock dependency instead of guessing scheduler timing."""
    async with AsyncSession(engine) as observer:
        while True:
            blocked = await observer.scalar(
                sa.text("SELECT :blocker_pid = ANY(pg_blocking_pids(:blocked_pid))"),
                {"blocker_pid": blocker_pid, "blocked_pid": blocked_pid},
            )
            if blocked:
                return


@pytest.mark.asyncio
async def test_idle_admission_yields_to_child_terminal_parent_lock(
    rdb_engine: AsyncEngine,
    latest_db_schema: None,
) -> None:
    """Idle evaluation cannot invert Agent/Session locks held by child execution."""
    del latest_db_schema
    repository = _ObservedSessionRepository()
    suffix = uuid4().hex[:8]
    async with AsyncSession(rdb_engine, expire_on_commit=False) as setup:
        workspace_id = await _create_workspace(setup, f"idle-lock-order-{suffix}")
        agent_id = await _create_agent(
            setup,
            workspace_id,
            f"idle-lock-order-{suffix}",
        )
        root = await repository.create(
            setup,
            AgentSessionCreate(
                workspace_id=workspace_id,
                product_mode=AgentSessionProductMode.TEAM,
                associated_user_id=None,
                agent_id=agent_id,
                title=None,
            ),
        )
        root_node = await repository.get_session_agent_by_session_id(setup, root.id)
        assert root_node is not None
        child = await repository.create_child_session_agent(
            setup,
            parent_session_agent_id=root_node.id,
            name="idle-lock-child",
            agent_type="default",
            title=None,
            last_task_message=None,
        )
        await setup.commit()

    service = _service(
        continuation_recorder=_ContinuationRecorder(),
        event_publisher=_EventPublisher(),
        broker=_Broker(),
        agent_session_repository=repository,
    )
    idle_pid: asyncio.Future[int] = asyncio.get_running_loop().create_future()

    async def evaluate_idle() -> bool:
        async with AsyncSession(rdb_engine, expire_on_commit=False) as idle_session:
            backend_pid = await idle_session.scalar(sa.text("SELECT pg_backend_pid()"))
            assert isinstance(backend_pid, int)
            idle_pid.set_result(backend_pid)
            eligibility = await service.repository._eligibility(
                idle_session,
                root.id,
                "0" * 32,
                owner_generation=root.owner_generation,
            )
            await idle_session.commit()
            return eligibility.eligible

    tasks: list[asyncio.Task[object]] = []
    try:
        async with AsyncSession(rdb_engine, expire_on_commit=False) as terminal_session:
            locked_child = await repository.wait_for_execution_lock_by_id(
                terminal_session,
                child.agent_session_id,
            )
            assert locked_child is not None
            terminal_pid = await terminal_session.scalar(
                sa.text("SELECT pg_backend_pid()")
            )
            assert isinstance(terminal_pid, int)

            idle_task = asyncio.create_task(evaluate_idle())
            tasks.append(idle_task)
            waiting_pid = await asyncio.wait_for(idle_pid, timeout=5)
            deferred = asyncio.create_task(repository.tree_admission_deferred.wait())
            blocked = asyncio.create_task(
                _wait_for_database_blocker(
                    rdb_engine,
                    blocked_pid=waiting_pid,
                    blocker_pid=terminal_pid,
                )
            )
            tasks.extend([deferred, blocked])
            observed, _ = await asyncio.wait(
                [deferred, blocked],
                timeout=5,
                return_when=asyncio.FIRST_COMPLETED,
            )
            assert observed, "Idle admission never reached a database lock boundary"
            for observation in observed:
                observation.result()

            # Terminal finalization reads its parent after canonical child admission.
            # The old idle lock holds Agent while waiting on this same parent Session.
            locked_parent = await asyncio.wait_for(
                repository.lock_by_id(terminal_session, root.id),
                timeout=5,
            )
            assert locked_parent is not None
            await terminal_session.commit()

            assert await asyncio.wait_for(idle_task, timeout=5) is False
            assert repository.tree_admission_deferred.is_set()
    finally:
        for task in tasks:
            if not task.done():
                task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
