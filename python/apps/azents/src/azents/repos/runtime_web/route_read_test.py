"""Runtime Web route descriptions do not inherit exact epoch mutation locks."""

import asyncio
import dataclasses
from uuid import uuid4

import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncEngine

from azents.rdb.models.agent import RDBAgent
from azents.rdb.models.agent_runtime import RDBAgentRuntime
from azents.rdb.models.llm_provider_integration import RDBLLMProviderIntegration
from azents.rdb.models.runtime_web import RDBRuntimeWebSessionRoute
from azents.rdb.models.workspace import RDBWorkspace
from azents.rdb.session_capabilities import (
    create_read_only_session_manager,
    create_read_write_session_manager,
)
from azents.repos.runtime_stream_route_test import acquire, digest, route_fixture
from azents.repos.runtime_web.data import RuntimeWebSessionRoute


@pytest.mark.asyncio
@pytest.mark.parametrize("replacement", ["runtime", "route"])
async def test_route_resolution_nonblocking_then_rejects_committed_replacement(
    rdb_engine: AsyncEngine, latest_db_schema: None, replacement: str
) -> None:
    """Held route/Runtime writers permit a description, not future epoch authority."""
    writes = create_read_write_session_manager(rdb_engine)
    reads = create_read_only_session_manager(rdb_engine)
    fixture = None
    writer: asyncio.Task[None] | None = None
    held, release = asyncio.Event(), asyncio.Event()
    try:
        fixture = await route_fixture(writes, f"route-read-{uuid4().hex}")
        route = await acquire(fixture)
        repository = dataclasses.replace(fixture.repository, read_session_manager=reads)

        async def hold() -> None:
            async with writes() as session:
                await session.write_session.execute(
                    sa.select(RDBRuntimeWebSessionRoute.runtime_id)
                    .where(RDBRuntimeWebSessionRoute.runtime_id == fixture.runtime_id)
                    .with_for_update()
                )
                await session.write_session.execute(
                    sa.select(RDBAgentRuntime.id)
                    .where(RDBAgentRuntime.id == fixture.runtime_id)
                    .with_for_update()
                )
                held.set()
                await release.wait()

        writer = asyncio.create_task(hold())
        await asyncio.wait_for(held.wait(), timeout=5)

        async def resolve() -> RuntimeWebSessionRoute | None:
            return await repository.resolve(
                runtime_id=fixture.runtime_id,
                desired_generation=3,
                runner_generation=4,
                protocol_fingerprint=digest("protocol"),
            )

        assert await asyncio.wait_for(resolve(), timeout=5) == route
        assert not release.is_set()
        release.set()
        await writer
        async with writes() as session:
            if replacement == "runtime":
                await session.write_session.execute(
                    sa.update(RDBAgentRuntime)
                    .where(RDBAgentRuntime.id == fixture.runtime_id)
                    .values(runner_generation=5)
                )
            else:
                await session.write_session.execute(
                    sa.update(RDBRuntimeWebSessionRoute)
                    .where(RDBRuntimeWebSessionRoute.runtime_id == fixture.runtime_id)
                    .values(draining_at=sa.func.now())
                )
        assert await resolve() is None
    finally:
        release.set()
        try:
            if writer is not None:
                await writer
        finally:
            if fixture is not None:
                async with writes() as session:
                    await session.write_session.execute(
                        sa.delete(RDBRuntimeWebSessionRoute).where(
                            RDBRuntimeWebSessionRoute.runtime_id == fixture.runtime_id
                        )
                    )
                    await session.write_session.execute(
                        sa.delete(RDBAgentRuntime).where(
                            RDBAgentRuntime.id == fixture.runtime_id
                        )
                    )
                    await session.write_session.execute(
                        sa.delete(RDBAgent).where(RDBAgent.id == fixture.agent_id)
                    )
                    await session.write_session.execute(
                        sa.delete(RDBLLMProviderIntegration).where(
                            RDBLLMProviderIntegration.workspace_id
                            == fixture.workspace_id
                        )
                    )
                    await session.write_session.execute(
                        sa.delete(RDBWorkspace).where(
                            RDBWorkspace.id == fixture.workspace_id
                        )
                    )
