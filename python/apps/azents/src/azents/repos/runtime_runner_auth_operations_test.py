"""Explicit Runner observation and registration-fence boundary evidence."""

import datetime
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from azents.core.runtime_runner_credential import RuntimeRunnerCredential
from azents.rdb.session_capabilities import (
    ReadSession,
    ReadWriteSession,
    WriteSession,
    create_read_only_session_manager,
)
from azents.repos.agent_runtime import AgentRuntimeRepository
from azents.repos.agent_runtime.data import AgentRuntime
from azents.repos.runtime_runner_auth_operations import (
    RuntimeRunnerAuthenticationOperationRepository,
)


class _RuntimeAuthorityRepository(AgentRuntimeRepository):
    """Record which independently meaningful query owns each authority boundary."""

    def __init__(self) -> None:
        self.reads = 0
        self.fences = 0
        now = datetime.datetime.now(datetime.UTC)
        self.runtime = AgentRuntime(
            id="runtime-1",
            workspace_id="workspace-1",
            agent_id="agent-1",
            terminal_delete_acknowledgement_kind=None,
            desired_generation=4,
            created_at=now,
            updated_at=now,
        )

    async def get_by_id(
        self, session: ReadSession, runtime_id: str
    ) -> AgentRuntime | None:
        assert session.read_session.in_transaction()
        self.reads += 1
        return self.runtime if runtime_id == self.runtime.id else None

    async def get_by_id_for_update(
        self, session: WriteSession, runtime_id: str
    ) -> AgentRuntime | None:
        assert session.write_session.in_transaction()
        self.fences += 1
        return self.runtime if runtime_id == self.runtime.id else None


async def test_runner_observation_does_not_acquire_registration_fence() -> None:
    """Only actual caller-owned acceptance fences the current Runtime generation."""
    active: list[bool] = []

    @asynccontextmanager
    async def sessions() -> AsyncIterator[WriteSession]:
        async with AsyncSession() as session:
            async with session.begin():
                active.append(True)
                try:
                    yield ReadWriteSession(session)
                finally:
                    active.pop()

    runtime = _RuntimeAuthorityRepository()
    owner = RuntimeRunnerAuthenticationOperationRepository(
        session_manager=sessions,
        runtime_repository=runtime,
    )
    credential = RuntimeRunnerCredential(
        credential_id="runner-credential",
        runtime_id="runtime-1",
        desired_generation=4,
    )
    assert await owner.authorize_runner(credential)
    assert not active
    assert runtime.reads == 1
    assert runtime.fences == 0
    async with sessions() as session:
        assert await owner.fence_runner_registration_in_transaction(session, credential)
    assert runtime.fences == 1
    assert not active


async def test_runner_observation_uses_native_read_only_owner(
    rdb_engine: AsyncEngine,
) -> None:
    """The completed authority operation opens native PostgreSQL read-only scope."""

    class _NativeReadEvidenceRepository(_RuntimeAuthorityRepository):
        async def get_by_id(
            self, session: ReadSession, runtime_id: str
        ) -> AgentRuntime | None:
            assert (
                await session.read_session.scalar(sa.text("SHOW transaction_read_only"))
                == "on"
            )
            return await super().get_by_id(session, runtime_id)

    runtime = _NativeReadEvidenceRepository()
    owner = RuntimeRunnerAuthenticationOperationRepository(
        session_manager=create_read_only_session_manager(rdb_engine),
        runtime_repository=runtime,
    )
    assert await owner.authorize_runner(
        RuntimeRunnerCredential(
            credential_id="native-ro", runtime_id="runtime-1", desired_generation=4
        )
    )
    assert runtime.reads == 1
    assert runtime.fences == 0
