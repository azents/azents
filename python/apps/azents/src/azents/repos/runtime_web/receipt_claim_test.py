"""Real competing Runtime Web operation identities publish one durable receipt."""

import asyncio
from uuid import uuid4

import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncEngine

from azents.rdb.models.agent import RDBAgent
from azents.rdb.models.llm_provider_integration import RDBLLMProviderIntegration
from azents.rdb.models.runtime_web import (
    RDBRuntimeWebOperationReceipt,
    RDBRuntimeWebService,
)
from azents.rdb.models.user import RDBUser
from azents.rdb.models.workspace import RDBWorkspace
from azents.rdb.session_capabilities import create_read_write_session_manager
from azents.repos.runtime_web.repository import (
    RuntimeWebRepository,
    RuntimeWebRepositoryConflict,
)
from azents.repos.runtime_web.repository_test import _authority_fixture, _operation


@pytest.mark.asyncio
async def test_competing_receipts_replay_one_result_and_reject_changed_input(
    rdb_engine: AsyncEngine, latest_db_schema: None
) -> None:
    """Same actor/execution/key/kind has one receipt, not two quota allocations."""
    writes = create_read_write_session_manager(rdb_engine)
    fixture = None
    winner: asyncio.Task[str] | None = None
    loser: asyncio.Task[str] | None = None
    held, attempting, release = asyncio.Event(), asyncio.Event(), asyncio.Event()
    repository = RuntimeWebRepository()
    try:
        suffix = uuid4().hex
        async with writes() as session:
            fixture = await _authority_fixture(
                session, handle=suffix, email=f"{suffix}@example.test"
            )
        operation = _operation(
            f"same-operation-{uuid4().hex}", actor_id=fixture.agent_id
        )

        async def request(first: bool) -> str:
            async with writes() as session:
                if not first:
                    await held.wait()
                    attempting.set()
                result = await repository.request_service(
                    session,
                    workspace_id=fixture.workspace_id,
                    agent_id=fixture.agent_id,
                    port=3456,
                    label="One preview",
                    operation=operation,
                    service_limit=16,
                )
                if first:
                    held.set()
                    await release.wait()
                return result.service.id

        winner = asyncio.create_task(request(True))
        loser = asyncio.create_task(request(False))
        await asyncio.wait_for(attempting.wait(), timeout=5)
        release.set()
        results = await asyncio.wait_for(asyncio.gather(winner, loser), timeout=5)
        assert len(set(results)) == 1
        async with writes() as session:
            assert (
                await session.read_session.scalar(
                    sa.select(sa.func.count())
                    .select_from(RDBRuntimeWebOperationReceipt)
                    .where(
                        RDBRuntimeWebOperationReceipt.actor_id == fixture.agent_id,
                        RDBRuntimeWebOperationReceipt.operation_key
                        == operation.operation_key,
                    )
                )
                == 1
            )
            assert (
                await session.read_session.scalar(
                    sa.select(sa.func.count())
                    .select_from(RDBRuntimeWebService)
                    .where(RDBRuntimeWebService.agent_id == fixture.agent_id)
                )
                == 1
            )
        with pytest.raises(
            RuntimeWebRepositoryConflict, match="Idempotency input changed"
        ):
            async with writes() as session:
                await repository.request_service(
                    session,
                    workspace_id=fixture.workspace_id,
                    agent_id=fixture.agent_id,
                    port=3456,
                    label="Changed input",
                    operation=operation,
                    service_limit=16,
                )
    finally:
        release.set()
        try:
            tasks = [task for task in (winner, loser) if task is not None]
            if tasks:
                await asyncio.gather(*tasks)
        finally:
            if fixture is not None:
                async with writes() as session:
                    await session.write_session.execute(
                        sa.delete(RDBRuntimeWebOperationReceipt).where(
                            RDBRuntimeWebOperationReceipt.actor_id == fixture.agent_id
                        )
                    )
                    await session.write_session.execute(
                        sa.delete(RDBRuntimeWebService).where(
                            RDBRuntimeWebService.agent_id == fixture.agent_id
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
                    await session.write_session.execute(
                        sa.delete(RDBUser).where(RDBUser.id == fixture.user_id)
                    )
