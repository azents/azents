"""Apply releases partial fences for real inverse-order web/archive writers."""

import asyncio
from datetime import UTC, datetime
from unittest.mock import patch

import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncEngine

from azents.core.enums import ExternalChannelAppMode
from azents.core.external_model_settings import (
    ExternalModelEditorReady,
    ExternalModelRejected,
    ExternalModelStale,
)
from azents.rdb.models.agent import RDBAgent
from azents.rdb.models.external_model_settings import RDBExternalModelMutation
from azents.rdb.session_capabilities import (
    WriteSession,
    create_read_write_session_manager,
)
from azents.repos.agent.data import Agent
from azents.repos.external_account_oauth.configuration_fence_test import (
    _wait_for_blocked,
)
from azents.repos.external_channel.final_authority_fence_test import (
    _authority,
    _local_option_repository,
)
from azents.repos.external_channel.lifecycle import ExternalChannelLifecycleRepository


@pytest.mark.parametrize("writer", ["web_profile", "archive"])
async def test_apply_rolls_back_for_inverse_order_writer_then_reauthorizes(
    rdb_engine: AsyncEngine, latest_db_schema: None, writer: str
) -> None:
    """Existing Apply timeout releases Agent/Binding so the owning writer commits."""
    writes = create_read_write_session_manager(rdb_engine)
    repository = _local_option_repository(rdb_engine)
    profiles = repository.session_model_profile_repository
    roots = repository.agent_session_repository
    ready, release = asyncio.Event(), asyncio.Event()
    holder_pid: int | None = None
    actual_agent_lock = profiles.agent_repository.lock_by_id

    async def paused_agent_lock(session: WriteSession, agent_id: str) -> Agent | None:
        # Web owns Session already; pause before its actual Agent acquisition.
        ready.set()
        await release.wait()
        return await actual_agent_lock(session, agent_id)

    async with _authority(
        rdb_engine, app_mode=ExternalChannelAppMode.SINGLE
    ) as fixture:
        now = datetime.now(UTC)
        opened = await repository.open_editor(
            actor=fixture.actor,
            target=fixture.target,
            owner_interaction_key="inverse-open",
            now=now,
            offset=0,
            limit=10,
        )
        assert isinstance(opened, ExternalModelEditorReady)

        async def mutate() -> None:
            nonlocal holder_pid
            async with writes() as session:
                pid = await session.write_session.scalar(
                    sa.select(sa.func.pg_backend_pid())
                )
                assert isinstance(pid, int)
                holder_pid = pid
                if writer == "web_profile":
                    label = await session.read_session.scalar(
                        sa.select(RDBAgent.main_model_label).where(
                            RDBAgent.id == fixture.agent_id
                        )
                    )
                    assert isinstance(label, str)
                    await profiles.lock_writable_root(
                        session,
                        agent_id=fixture.agent_id,
                        session_id=fixture.target.session_id,
                        user_id=fixture.user_id,
                    )
                    await roots.set_applied_inference_profile(
                        session,
                        session_id=fixture.target.session_id,
                        model_target_label=label,
                        reasoning_effort=None,
                        enabled_execution_options=[],
                    )
                else:
                    tree = await roots.lock_root_tree_sessions(
                        session, root_session_id=fixture.target.session_id
                    )
                    session_ids = [root.id for root in tree]
                    assert session_ids == [fixture.target.session_id]
                    ready.set()
                    await release.wait()
                    await ExternalChannelLifecycleRepository().terminate_session_tree(
                        session,
                        session_ids=session_ids,
                        now=now,
                    )
                    await roots.archive_tree(
                        session,
                        root_session_id=fixture.target.session_id,
                        session_ids=session_ids,
                        archived_at=now,
                        purge_after=None,
                        policy_revision=1,
                        retention_days=None,
                    )

        changed = pending = None
        with patch.object(profiles.agent_repository, "lock_by_id", paused_agent_lock):
            try:
                changed = asyncio.create_task(mutate())
                await asyncio.wait_for(ready.wait(), timeout=3)
                assert holder_pid is not None
                pending = asyncio.create_task(
                    repository.apply_draft(
                        actor=fixture.actor,
                        draft_id=opened.editor.draft.id,
                        expected_selection_fingerprint=opened.editor.draft.selection_fingerprint,
                        apply_interaction_key="inverse-apply",
                        now=now,
                    )
                )
                # Apply owns Agent/Binding and waits for the writer's Session.
                await _wait_for_blocked(rdb_engine, holder_pid)
                # Writer now asks for that actual Agent/Binding. Apply's 250ms
                # transaction timeout releases its partial fences, then retries.
                release.set()
                await asyncio.wait_for(changed, timeout=3)
                commit = await asyncio.wait_for(pending, timeout=3)
                if writer == "web_profile":
                    assert isinstance(commit.result, ExternalModelStale)
                    assert (
                        commit.result.editor.current_generation
                        == opened.editor.current_generation + 1
                    )
                else:
                    assert isinstance(commit.result, ExternalModelRejected)
                assert commit.notice_plan is None
            finally:
                release.set()
                for task in (changed, pending):
                    if task is not None and not task.done():
                        task.cancel()
                        await asyncio.gather(task, return_exceptions=True)
        async with writes() as observer:
            assert (
                await observer.read_session.scalar(
                    sa.select(sa.func.count())
                    .select_from(RDBExternalModelMutation)
                    .where(
                        RDBExternalModelMutation.session_id == fixture.target.session_id
                    )
                )
                == 0
            )
