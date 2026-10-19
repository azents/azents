"""Real PostgreSQL Session/Channel Work finalization lock ordering."""

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from azents.core.external_channel_ingestion import _PreparedSuccess
from azents.engine.tooling.toolkit_state_test import _create_agent_and_session
from azents.rdb.session_capabilities import ReadWriteSession, WriteSession
from azents.repos.agent_session import AgentSessionRepository
from azents.repos.external_channel.work import ExternalChannelWorkRepository
from azents.repos.toolkit_state import ToolkitStateRepository
from azents.repos.toolkit_state.data import ToolkitStateUpsert
from azents.services.external_channel.ingress_queue_test import (
    _NOW,
    _batch,
    _collaborators,
    _history,
    _item,
    _service,
)
from azents.worker.session.idle_continuation_lock_test import _wait_for_database_blocker


async def test_finalization_serializes_wakeup_before_work_state_update(
    rdb_engine: AsyncEngine,
    latest_db_schema: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A Session-first writer and real ingress transaction must both commit."""
    del latest_db_schema
    sessions = AgentSessionRepository()
    states = ToolkitStateRepository()
    async with AsyncSession(rdb_engine, expire_on_commit=False) as raw:
        setup = ReadWriteSession(raw)
        fixture = await _create_agent_and_session(
            setup, f"ingress-lock-{uuid4().hex[:8]}"
        )
        identity = ToolkitStateUpsert(
            agent_id=fixture.agent_id,
            session_id=fixture.agent_session_id,
            toolkit_namespace="external_channel",
            state_name="ingress-lock-regression",
            state_json={"revision": 0},
            schema_version=1,
            expected_version=None,
        )
        await states.save(setup, identity)
        await raw.commit()

    async def write_work_state(session: WriteSession) -> None:
        current = await states.get(
            session,
            agent_id=fixture.agent_id,
            session_id=fixture.agent_session_id,
            toolkit_namespace=identity.toolkit_namespace,
            state_name=identity.state_name,
        )
        assert current is not None
        await states.save(
            session,
            identity.model_copy(
                update={
                    "expected_version": current.version,
                    "state_json": {"revision": current.version},
                }
            ),
        )

    ingress_pid: asyncio.Future[int] = asyncio.get_running_loop().create_future()
    owner_pid: asyncio.Future[int] = asyncio.get_running_loop().create_future()

    @asynccontextmanager
    async def ingress_session() -> AsyncIterator[WriteSession]:
        async with AsyncSession(rdb_engine, expire_on_commit=False) as raw:
            pid = await raw.scalar(sa.text("SELECT pg_backend_pid()"))
            assert isinstance(pid, int)
            ingress_pid.set_result(pid)
            yield ReadWriteSession(raw)

    item = _item(
        item_id="item-1",
        trigger_key="message-1",
        trigger_position="00000000000000000001",
    )
    collaborators = _collaborators(locked_rows=[SimpleNamespace(id=item.id)])
    agent_sessions = collaborators.agent_session_repository
    agent_sessions.get_by_id = AsyncMock(wraps=sessions.get_by_id)
    agent_sessions.admit_input_wakeup = AsyncMock(wraps=sessions.admit_input_wakeup)
    work = MagicMock(spec=ExternalChannelWorkRepository)

    async def ensure_work(session: WriteSession, **_kwargs: object) -> SimpleNamespace:
        await write_work_state(session)
        return SimpleNamespace(work_cycle_id="work-1")

    work.ensure_active_work = AsyncMock(side_effect=ensure_work)
    work.resume_from_human_input = AsyncMock(
        return_value=SimpleNamespace(work_cycle_id="work-1")
    )
    work.prepare_initial_progress = AsyncMock(return_value=None)
    service = _service(
        session_manager=ingress_session,
        repository=collaborators.repository,
        queue_repository=collaborators.queue_repository,
        mailbox_admission_repository=collaborators.mailbox_admission_repository,
        agent_session_repository=agent_sessions,
        wake_dispatcher=collaborators.wake_dispatcher,
        work_repository=work,
    )
    monkeypatch.setattr(
        service.operations, "_ownership_current", AsyncMock(return_value=True)
    )
    batch = _batch(item).model_copy(update={"session_id": fixture.agent_session_id})

    async def owned_worker_mutation() -> None:
        async with AsyncSession(rdb_engine, expire_on_commit=False) as raw:
            session = ReadWriteSession(raw)
            await sessions.mark_running(session, fixture.agent_session_id)
            pid = await raw.scalar(sa.text("SELECT pg_backend_pid()"))
            assert isinstance(pid, int)
            owner_pid.set_result(pid)
            await _wait_for_database_blocker(
                rdb_engine, blocked_pid=await ingress_pid, blocker_pid=pid
            )
            await write_work_state(session)
            await raw.commit()

    async def finalize() -> None:
        await owner_pid
        result = await service.operations.finalize_batch(
            batch,
            prepared=[
                _PreparedSuccess(
                    item=item,
                    durable_cursor=None,
                    history=_history(
                        trigger_key=item.trigger_provider_message_key,
                        trigger_position=item.trigger_position,
                    ),
                )
            ],
            now=_NOW,
        )
        assert result.committed

    async with asyncio.timeout(15):
        async with asyncio.TaskGroup() as tasks:
            tasks.create_task(owned_worker_mutation())
            tasks.create_task(finalize())
    async with AsyncSession(rdb_engine) as raw:
        final = await states.get(
            ReadWriteSession(raw),
            agent_id=fixture.agent_id,
            session_id=fixture.agent_session_id,
            toolkit_namespace=identity.toolkit_namespace,
            state_name=identity.state_name,
        )
        assert final is not None and final.version == 3
