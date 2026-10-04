"""Runner authorization observations do not inherit connection acceptance locks."""

import asyncio

import pytest
import sqlalchemy as sa
from cryptography.fernet import Fernet
from sqlalchemy.ext.asyncio import AsyncEngine

from azents.core.runtime_runner_credential import RuntimeRunnerCredentialVerifier
from azents.rdb.models.agent import RDBAgent
from azents.rdb.models.agent_runtime import RDBAgentRuntime
from azents.rdb.models.workspace import RDBWorkspace
from azents.rdb.session_capabilities import create_read_write_session_manager
from azents.repos.agent_runtime import AgentRuntimeRepository
from azents.repos.agent_runtime_removal.repository_test import _create_agent
from azents.services.runtime_runner_auth.service import (
    RuntimeRunnerAuthenticationService,
)


@pytest.mark.asyncio
async def test_runner_poll_nonblocking_and_registration_rejects_replaced_generation(
    rdb_engine: AsyncEngine, latest_db_schema: None
) -> None:
    """Committed credential reads may lag; acceptance waits for exact Runtime state."""
    writes = create_read_write_session_manager(rdb_engine)
    repository = AgentRuntimeRepository()
    async with writes() as session:
        fixture = await _create_agent(session)
        runtime = await repository.ensure_for_agent(session, fixture.agent_id)
    verifier = RuntimeRunnerCredentialVerifier(Fernet.generate_key().decode())
    issued = verifier.issue(
        runtime_id=runtime.id, desired_generation=runtime.desired_generation
    )
    credential = verifier.verify(issued.token)
    service = RuntimeRunnerAuthenticationService(
        session_manager=writes, runtime_repository=repository, verifier=verifier
    )
    held, attempting, release = asyncio.Event(), asyncio.Event(), asyncio.Event()

    async def replace() -> None:
        async with writes() as session:
            await session.write_session.execute(
                sa.update(RDBAgentRuntime)
                .where(RDBAgentRuntime.id == runtime.id)
                .values(desired_generation=RDBAgentRuntime.desired_generation + 1)
            )
            held.set()
            await release.wait()

    async def register() -> bool:
        async with writes() as session:
            attempting.set()
            return await service.fence_runner_registration_in_transaction(
                session, credential
            )

    writer = asyncio.create_task(replace())
    registration: asyncio.Task[bool] | None = None
    try:
        await asyncio.wait_for(held.wait(), timeout=5)
        assert await asyncio.wait_for(service.authorize_runner(credential), timeout=5)
        registration = asyncio.create_task(register())
        await asyncio.wait_for(attempting.wait(), timeout=5)
        assert not release.is_set()
        release.set()
        await writer
        assert not await asyncio.wait_for(registration, timeout=5)
        assert not await service.authorize_runner(credential)
    finally:
        release.set()
        await writer
        if registration is not None:
            await registration
        async with writes() as session:
            await session.write_session.execute(
                sa.delete(RDBAgentRuntime).where(RDBAgentRuntime.id == runtime.id)
            )
            await session.write_session.execute(
                sa.delete(RDBAgent).where(RDBAgent.id == fixture.agent_id)
            )
            await session.write_session.execute(
                sa.delete(RDBWorkspace).where(RDBWorkspace.id == fixture.workspace_id)
            )
