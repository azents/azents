"""Exact Work selectors fence replacements and duplicate new publications."""

import datetime
from uuid import uuid4

import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncEngine

from azents.core.enums import ExternalChannelActionMode, ExternalChannelWorkStatus
from azents.rdb.models.external_channel import RDBExternalChannelResource
from azents.rdb.session_capabilities import create_read_write_session_manager
from azents.repos.external_channel.work import ExternalChannelWorkRepository
from azents.repos.external_channel.work_data import ChannelActionTransition
from azents.repos.external_channel.work_state import ChannelWorkStateMutation
from azents.repos.external_channel.work_state_test import (
    _cleanup_binding,
    _seed_binding,
    _work,
)


async def test_exact_selector_and_new_publication_replay(
    rdb_engine: AsyncEngine,
    latest_db_schema: None,
) -> None:
    del latest_db_schema
    writes = create_read_write_session_manager(rdb_engine)
    seeded = await _seed_binding(rdb_engine, suffix=uuid4().hex[:10])
    repository = ExternalChannelWorkRepository()
    initial = _work(seeded.binding_id)

    async def finish(selector: str | None, call_id: str) -> ChannelActionTransition:
        async with writes() as session:
            return await repository.commit_direct_action(
                session,
                links=(),
                session_id=seeded.owner_session_id,
                agent_id=seeded.owner_agent_id,
                run_id=None,
                client_tool_call_id=call_id,
                binding_id=seeded.binding_id,
                expected_work_cycle_id=selector,
                mode=ExternalChannelActionMode.FINISH,
                message="Verified final publication",
                title=None,
                tasks=None,
                files=(),
                now=datetime.datetime.now(datetime.UTC),
            )

    try:
        async with writes() as session:
            await session.write_session.execute(
                sa.update(RDBExternalChannelResource)
                .where(RDBExternalChannelResource.id == seeded.resource_id)
                .values(labels={"channel_id": "C1", "thread_ts": "1.0"})
            )
            await repository.work_state_store.update(
                session,
                agent_id=seeded.owner_agent_id,
                session_id=seeded.owner_session_id,
                binding_id=seeded.binding_id,
                default_factory=lambda: initial,
                mutator=lambda current: ChannelWorkStateMutation(
                    state=current, result=None
                ),
            )
        with pytest.raises(ValueError, match="changed before admission"):
            await finish(None, "must-not-select-active")
        with pytest.raises(ValueError, match="no longer active"):
            await finish("stale-work", "must-not-select-replacement")
        async with writes() as session:
            unchanged = await repository.work_state_store.load(
                session,
                agent_id=seeded.owner_agent_id,
                session_id=seeded.owner_session_id,
                binding_id=seeded.binding_id,
            )
            assert unchanged == initial
        completed = await finish(initial.work_cycle_id, "finish-initial")
        assert completed.work_id == initial.work_cycle_id
        assert completed.work_status is ExternalChannelWorkStatus.FINISHED
        assert completed.effects
        with pytest.raises(ValueError, match="no longer active"):
            await finish(initial.work_cycle_id, "must-not-recreate-finished")
        publication = await finish(None, "ordinary-new-publication")
        assert publication.work_id != initial.work_cycle_id
        assert publication.work_status is ExternalChannelWorkStatus.FINISHED
        assert publication.effects
        replay = await finish(None, "ordinary-new-publication")
        assert replay.work_id == publication.work_id
        assert replay.work_status is ExternalChannelWorkStatus.FINISHED
        assert replay.effects == ()
    finally:
        await _cleanup_binding(rdb_engine, seeded)
