"""Binding-selected Work admission through completed database operations."""

import datetime
from typing import Literal
from uuid import uuid4

import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncEngine

from azents.core.enums import ExternalChannelActionMode, ExternalChannelWorkStatus
from azents.rdb.models.external_channel import RDBExternalChannelResource
from azents.rdb.session_capabilities import (
    create_read_only_session_manager,
    create_read_write_session_manager,
)
from azents.repos.external_channel.action_operations import (
    ExternalChannelActionOperations,
)
from azents.repos.external_channel.work import ExternalChannelWorkRepository
from azents.repos.external_channel.work_state import ChannelWorkStateMutation
from azents.repos.external_channel.work_state_test import (
    _cleanup_binding,
    _seed_binding,
    _work,
)


@pytest.mark.parametrize("existing", ["absent", "active", "finished"])
async def test_binding_selected_action_resolves_current_work_in_write_scope(
    rdb_engine: AsyncEngine,
    latest_db_schema: None,
    existing: Literal["absent", "active", "finished"],
) -> None:
    """Ordinary callers select a binding and preserve its active Work identity."""
    del latest_db_schema
    writes = create_read_write_session_manager(rdb_engine)
    seeded = await _seed_binding(rdb_engine, suffix=uuid4().hex[:10])
    repository = ExternalChannelWorkRepository()
    operations = ExternalChannelActionOperations(
        session_manager=writes,
        read_only_session_manager=create_read_only_session_manager(rdb_engine),
        repository=repository,
        execution_owner=None,
    )
    initial = _work(seeded.binding_id)
    now = datetime.datetime.now(datetime.UTC)
    if existing == "finished":
        initial.status = ExternalChannelWorkStatus.FINISHED
        initial.finished_at = now
    try:
        async with writes() as session:
            await session.write_session.execute(
                sa.update(RDBExternalChannelResource)
                .where(RDBExternalChannelResource.id == seeded.resource_id)
                .values(labels={"channel_id": "C1", "thread_ts": "1.0"})
            )
            if existing != "absent":
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
        result = await operations.commit_direct_action(
            links=(),
            session_id=seeded.owner_session_id,
            agent_id=seeded.owner_agent_id,
            run_id=None,
            client_tool_call_id="binding-selected-publication",
            binding_id=seeded.binding_id,
            mode=ExternalChannelActionMode.FINISH,
            message="Completed binding-selected work.",
            title=None,
            tasks=None,
            files=(),
            now=now,
        )
        assert result.work_status is ExternalChannelWorkStatus.FINISHED
        assert result.effects
        assert (result.work_id == initial.work_cycle_id) == (existing == "active")
        async with writes() as session:
            saved = await repository.work_state_store.load(
                session,
                agent_id=seeded.owner_agent_id,
                session_id=seeded.owner_session_id,
                binding_id=seeded.binding_id,
            )
        assert saved is not None
        assert saved.work_cycle_id == result.work_id
        assert saved.status is ExternalChannelWorkStatus.FINISHED
    finally:
        await _cleanup_binding(rdb_engine, seeded)
