"""Competing retention roots bind an Exchange source/preview family atomically."""

import asyncio
from uuid import uuid4

import pytest
import sqlalchemy as sa
from azcommon.result import Failure, Success
from sqlalchemy.ext.asyncio import AsyncEngine

from azents.core.enums import (
    AgentSessionKind,
    AgentSessionProductMode,
    AgentSessionStartReason,
)
from azents.rdb.models.agent import RDBAgent
from azents.rdb.models.agent_session import RDBAgentSession
from azents.rdb.models.exchange_file import RDBExchangeFile
from azents.rdb.models.exchange_upload_operation import RDBExchangeUploadOperation
from azents.rdb.models.user import RDBUser
from azents.rdb.models.workspace import RDBWorkspace
from azents.rdb.session_capabilities import create_read_write_session_manager
from azents.repos.exchange_file import ExchangeFileRepository
from azents.repos.exchange_file.data import ExchangeFileClaimOwnerConflict
from azents.repos.exchange_file.upload_operations_test import (
    _NOW,
    _batch,
    _claim,
    _harness,
    _prepare,
)


@pytest.mark.asyncio
async def test_competing_retention_roots_bind_source_and_preview_to_one_winner(
    rdb_engine: AsyncEngine, latest_db_schema: None
) -> None:
    """An old-root competitor cannot partially claim the same source/preview family."""
    writes = create_read_write_session_manager(rdb_engine)
    harness = await _harness(writes)
    roots = [uuid4().hex, uuid4().hex]
    winner: asyncio.Task[None] | None = None
    loser: asyncio.Task[None] | None = None
    held, attempting, release = asyncio.Event(), asyncio.Event(), asyncio.Event()
    try:
        operation = await _prepare(harness)
        await _claim(harness, operation, claim_id="publication", now=_NOW)
        publication = await harness.repository.finalize_agent_upload_operation(
            agent_id=harness.agent_id,
            user_id=harness.user_id,
            upload_id=operation.upload_id,
            claim_id="publication",
            now=_NOW,
            batch=_batch(operation, preview=True),
        )
        assert isinstance(publication, Success)
        async with writes() as session:
            for root in roots:
                await session.write_session.execute(
                    sa.insert(RDBAgentSession).values(
                        id=root,
                        workspace_id=harness.workspace_id,
                        agent_id=harness.agent_id,
                        handle=f"retention-{uuid4().hex}",
                        session_kind=AgentSessionKind.ROOT,
                        product_mode=AgentSessionProductMode.TEAM,
                        associated_user_id=None,
                        start_reason=AgentSessionStartReason.INITIAL,
                    )
                )
        repository = ExchangeFileRepository()

        async def claim(first: bool) -> None:
            async with writes() as session:
                if not first:
                    await held.wait()
                    attempting.set()
                result = await repository.claim_for_retention_root(
                    session,
                    object_keys=[publication.value.object_key],
                    workspace_id=harness.workspace_id,
                    agent_id=harness.agent_id,
                    retention_root_session_id=roots[0 if first else 1],
                    bound_at=_NOW,
                )
                if first:
                    assert isinstance(result, Success)
                    held.set()
                    await release.wait()
                else:
                    assert isinstance(result, Failure)
                    assert isinstance(result.error, ExchangeFileClaimOwnerConflict)

        winner = asyncio.create_task(claim(True))
        loser = asyncio.create_task(claim(False))
        await asyncio.wait_for(attempting.wait(), timeout=5)
        release.set()
        await asyncio.wait_for(asyncio.gather(winner, loser), timeout=5)
        async with writes() as session:
            family = (
                await session.read_session.scalars(
                    sa.select(RDBExchangeFile).where(
                        RDBExchangeFile.id.in_(
                            [operation.publication_id, operation.preview_file_id]
                        )
                    )
                )
            ).all()
            assert len(family) == 2
            assert {row.retention_root_session_id for row in family} == {roots[0]}
            assert {row.retention_bound_at for row in family} == {_NOW}
            # A later wrong-root claim leaves every family field untouched.
            repeated = await repository.claim_for_retention_root(
                session,
                object_keys=[publication.value.object_key],
                workspace_id=harness.workspace_id,
                agent_id=harness.agent_id,
                retention_root_session_id=roots[1],
                bound_at=_NOW,
            )
            assert isinstance(repeated, Failure)
    finally:
        release.set()
        try:
            tasks = [task for task in (winner, loser) if task is not None]
            if tasks:
                await asyncio.gather(*tasks)
        finally:
            async with writes() as session:
                await session.write_session.execute(
                    sa.delete(RDBExchangeFile).where(
                        RDBExchangeFile.workspace_id == harness.workspace_id
                    )
                )
                await session.write_session.execute(
                    sa.delete(RDBExchangeUploadOperation).where(
                        RDBExchangeUploadOperation.workspace_id == harness.workspace_id
                    )
                )
                await session.write_session.execute(
                    sa.delete(RDBAgentSession).where(RDBAgentSession.id.in_(roots))
                )
                await session.write_session.execute(
                    sa.delete(RDBAgent).where(RDBAgent.id == harness.agent_id)
                )
                await session.write_session.execute(
                    sa.delete(RDBWorkspace).where(
                        RDBWorkspace.id == harness.workspace_id
                    )
                )
                await session.write_session.execute(
                    sa.delete(RDBUser).where(
                        RDBUser.id.in_([harness.user_id, harness.other_user_id])
                    )
                )
