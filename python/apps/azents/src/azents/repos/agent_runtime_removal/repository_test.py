"""Agent Runtime removal repository tests."""

import datetime
from typing import NamedTuple
from uuid import uuid4

import pytest

from azents.core.enums import (
    AgentRuntimeRemovalStage,
    AgentRuntimeRemovalStatus,
    RuntimeTerminalDeleteAcknowledgementKind,
)
from azents.rdb.models.agent import RDBAgent
from azents.rdb.models.workspace import RDBWorkspace
from azents.rdb.session_capabilities import WriteSession
from azents.repos.agent_runtime_removal_finalizer import (
    AgentRuntimeRemovalFinalizerRepository,
)
from azents.repos.agent_runtime_removal_scope import AgentRuntimeRemovalScopeRepository
from azents.testing.model_selection import (
    make_test_model_selection_dict,
    make_test_selectable_model_option_dicts,
)

from . import AgentRuntimeRemovalRepository
from .data import AgentRuntimeRemovalCreateResult


class _AgentFixture(NamedTuple):
    """Field-named result for ``_create_agent``."""

    workspace_id: str
    agent_id: str


async def _create_agent(session: WriteSession) -> _AgentFixture:
    """Create one Workspace and Agent for removal repository tests."""
    suffix = uuid4().hex[:8]
    workspace = RDBWorkspace(
        name="Runtime removal test",
        handle=f"runtime-removal-{suffix}",
    )
    session.write_session.add(workspace)
    await session.write_session.flush()
    agent = RDBAgent(
        workspace_id=workspace.id,
        name="Runtime removal Agent",
        model_selection=make_test_model_selection_dict(),
        lightweight_model_selection=make_test_model_selection_dict(),
        selectable_model_options=make_test_selectable_model_option_dicts(
            model_selection=(make_test_model_selection_dict()),
            lightweight_model_selection=(make_test_model_selection_dict()),
        ),
        main_model_label="default",
        lightweight_model_label="lightweight",
    )
    session.write_session.add(agent)
    await session.write_session.flush()
    return _AgentFixture(
        workspace_id=workspace.id,
        agent_id=agent.id,
    )


async def test_create_claim_progress_complete_and_recreate(
    rdb_session: WriteSession,
) -> None:
    """Persist one active operation and retain completed history."""
    workspace_id, agent_id = await _create_agent(rdb_session)
    repository = AgentRuntimeRemovalRepository()
    confirmed_at = datetime.datetime.now(datetime.UTC)

    async def create(
        idempotency_key: str,
        expected_version: int,
    ) -> AgentRuntimeRemovalCreateResult:
        return await repository.create_or_get_active(
            rdb_session,
            agent_id=agent_id,
            workspace_id=workspace_id,
            requested_by_workspace_user_id="workspace-user-1",
            idempotency_key=idempotency_key,
            expected_capability_version=expected_version,
            committed_capability_version=expected_version + 1,
            agent_runtime_id=None,
            confirmed_at=confirmed_at,
            destructive_scope_version=1,
            active_root_session_count=3,
            active_subagent_count=2,
            active_run_count=1,
            queued_runtime_action_count=4,
        )

    created = await create("remove-1", 1)
    repeated = await create("remove-1", 1)
    competing = await create("remove-competing", 1)

    assert created.idempotency_match is True
    assert repeated.idempotency_match is True
    assert competing.idempotency_match is False
    assert repeated.operation.id == created.operation.id
    assert competing.operation.id == created.operation.id
    assert created.operation.status is AgentRuntimeRemovalStatus.PENDING
    assert created.operation.stage is AgentRuntimeRemovalStage.FENCING
    assert created.operation.active_root_session_count == 3

    claimed_at = confirmed_at + datetime.timedelta(seconds=1)
    claimed = await repository.claim_due(
        rdb_session,
        now=claimed_at,
        lease_owner="worker-1",
        lease_until=claimed_at + datetime.timedelta(minutes=1),
    )
    assert claimed is not None
    assert claimed.id == created.operation.id
    assert claimed.status is AgentRuntimeRemovalStatus.RUNNING
    assert claimed.attempt_count == 1

    assert await repository.set_stage(
        rdb_session,
        operation_id=claimed.id,
        lease_owner="worker-1",
        expected_attempt=claimed.attempt_count,
        stage=AgentRuntimeRemovalStage.CLEANING_PRODUCT_STATE,
        now=claimed_at,
    )
    with pytest.raises(ValueError, match="cannot decrease"):
        await repository.record_cleanup_progress(
            rdb_session,
            operation_id=claimed.id,
            lease_owner="worker-1",
            expected_attempt=claimed.attempt_count,
            expected_cursor_context_id=None,
            cursor_context_id="context-1",
            scanned_count=-1,
            invalidated_count=0,
            completed=False,
            now=claimed_at,
        )
    with pytest.raises(ValueError, match="cannot exceed"):
        await repository.record_cleanup_progress(
            rdb_session,
            operation_id=claimed.id,
            lease_owner="worker-1",
            expected_attempt=claimed.attempt_count,
            expected_cursor_context_id=None,
            cursor_context_id="context-1",
            scanned_count=1,
            invalidated_count=2,
            completed=False,
            now=claimed_at,
        )
    assert await repository.record_cleanup_progress(
        rdb_session,
        operation_id=claimed.id,
        lease_owner="worker-1",
        expected_attempt=claimed.attempt_count,
        expected_cursor_context_id=None,
        cursor_context_id="context-2",
        scanned_count=2,
        invalidated_count=1,
        completed=False,
        now=claimed_at,
    )
    assert not await repository.record_cleanup_progress(
        rdb_session,
        operation_id=claimed.id,
        lease_owner="worker-1",
        expected_attempt=claimed.attempt_count,
        expected_cursor_context_id=None,
        cursor_context_id="context-2",
        scanned_count=2,
        invalidated_count=1,
        completed=False,
        now=claimed_at,
    )
    with pytest.raises(ValueError, match="cannot regress"):
        await repository.record_cleanup_progress(
            rdb_session,
            operation_id=claimed.id,
            lease_owner="worker-1",
            expected_attempt=claimed.attempt_count,
            expected_cursor_context_id="context-2",
            cursor_context_id="context-1",
            scanned_count=1,
            invalidated_count=0,
            completed=False,
            now=claimed_at,
        )
    assert await repository.record_cleanup_progress(
        rdb_session,
        operation_id=claimed.id,
        lease_owner="worker-1",
        expected_attempt=claimed.attempt_count,
        expected_cursor_context_id="context-2",
        cursor_context_id="context-3",
        scanned_count=1,
        invalidated_count=1,
        completed=True,
        now=claimed_at,
    )
    assert not await repository.record_cleanup_progress(
        rdb_session,
        operation_id=claimed.id,
        lease_owner="worker-1",
        expected_attempt=claimed.attempt_count,
        expected_cursor_context_id="context-3",
        cursor_context_id="context-3",
        scanned_count=0,
        invalidated_count=0,
        completed=True,
        now=claimed_at,
    )
    assert await repository.record_physical_delete_target(
        rdb_session,
        operation_id=claimed.id,
        lease_owner="worker-1",
        expected_attempt=claimed.attempt_count,
        required=False,
        target_generation=None,
        requested_at=None,
        now=claimed_at,
    )
    assert not await repository.record_physical_delete_acknowledgement(
        rdb_session,
        operation_id=claimed.id,
        lease_owner="worker-1",
        expected_attempt=claimed.attempt_count,
        acknowledgement_kind=(
            RuntimeTerminalDeleteAcknowledgementKind.NO_PHYSICAL_BINDING
        ),
        acknowledged_at=claimed_at,
    )
    assert await repository.set_stage(
        rdb_session,
        operation_id=claimed.id,
        lease_owner="worker-1",
        expected_attempt=claimed.attempt_count,
        stage=AgentRuntimeRemovalStage.FINALIZING,
        now=claimed_at,
    )
    assert await repository.mark_completed(
        rdb_session,
        operation_id=claimed.id,
        lease_owner="worker-1",
        expected_attempt=claimed.attempt_count,
        now=claimed_at,
    )

    completed = await repository.get_by_id(rdb_session, claimed.id)
    assert completed is not None
    assert completed.status is AgentRuntimeRemovalStatus.COMPLETED
    assert completed.stage is AgentRuntimeRemovalStage.COMPLETED
    assert completed.cleanup_scanned_context_count == 3
    assert completed.cleanup_invalidated_context_count == 2
    assert completed.physical_delete_acknowledgement_kind is None
    latest_completed = await repository.get_latest_completed_by_agent_id(
        rdb_session,
        agent_id,
    )
    assert latest_completed is not None
    assert latest_completed.id == completed.id

    with pytest.raises(RuntimeError, match="creation failed"):
        await create("remove-1", 3)

    next_operation = await create("remove-2", 3)
    assert next_operation.idempotency_match is True
    assert next_operation.operation.id != claimed.id

    next_claimed_at = claimed_at + datetime.timedelta(seconds=1)
    next_claimed = await repository.claim_due(
        rdb_session,
        now=next_claimed_at,
        lease_owner="worker-2",
        lease_until=next_claimed_at + datetime.timedelta(minutes=1),
    )
    assert next_claimed is not None
    assert await repository.record_physical_delete_target(
        rdb_session,
        operation_id=next_claimed.id,
        lease_owner="worker-2",
        expected_attempt=next_claimed.attempt_count,
        required=True,
        target_generation=4,
        requested_at=next_claimed_at,
        now=next_claimed_at,
    )
    assert await repository.record_physical_delete_acknowledgement(
        rdb_session,
        operation_id=next_claimed.id,
        lease_owner="worker-2",
        expected_attempt=next_claimed.attempt_count,
        acknowledgement_kind=(
            RuntimeTerminalDeleteAcknowledgementKind.NO_PHYSICAL_BINDING
        ),
        acknowledged_at=next_claimed_at,
    )
    assert not await repository.record_physical_delete_acknowledgement(
        rdb_session,
        operation_id=next_claimed.id,
        lease_owner="worker-2",
        expected_attempt=next_claimed.attempt_count,
        acknowledgement_kind=(RuntimeTerminalDeleteAcknowledgementKind.PROVIDER_REPORT),
        acknowledged_at=next_claimed_at + datetime.timedelta(seconds=1),
    )
    persisted = await repository.get_by_id(rdb_session, next_claimed.id)
    assert persisted is not None
    assert persisted.physical_delete_acknowledgement_kind is (
        RuntimeTerminalDeleteAcknowledgementKind.NO_PHYSICAL_BINDING
    )


async def test_same_lease_owner_reclaim_rejects_old_attempt_mutations(
    rdb_session: WriteSession,
) -> None:
    """A stable Worker identity never grants completion to a reclaimed attempt."""
    workspace_id, agent_id = await _create_agent(rdb_session)
    repository = AgentRuntimeRemovalRepository()
    now = datetime.datetime.now(datetime.UTC)
    created = await repository.create_or_get_active(
        rdb_session,
        agent_id=agent_id,
        workspace_id=workspace_id,
        requested_by_workspace_user_id="workspace-user-1",
        idempotency_key="same-owner-reclaim",
        expected_capability_version=1,
        committed_capability_version=2,
        agent_runtime_id=None,
        confirmed_at=now,
        destructive_scope_version=1,
        active_root_session_count=0,
        active_subagent_count=0,
        active_run_count=0,
        queued_runtime_action_count=0,
    )
    first = await repository.claim_due(
        rdb_session,
        now=now,
        lease_owner="stable-worker",
        lease_until=now + datetime.timedelta(seconds=1),
    )
    assert first is not None
    reclaimed_at = now + datetime.timedelta(seconds=2)
    winner = await repository.claim_due(
        rdb_session,
        now=reclaimed_at,
        lease_owner="stable-worker",
        lease_until=reclaimed_at + datetime.timedelta(minutes=1),
    )
    assert winner is not None
    assert winner.id == first.id == created.operation.id
    assert winner.lease_owner == first.lease_owner
    assert winner.attempt_count == first.attempt_count + 1
    assert not await repository.set_stage(
        rdb_session,
        operation_id=first.id,
        lease_owner="stable-worker",
        expected_attempt=first.attempt_count,
        stage=AgentRuntimeRemovalStage.FINALIZING,
        now=reclaimed_at,
    )
    assert not await repository.record_cleanup_progress(
        rdb_session,
        operation_id=first.id,
        lease_owner="stable-worker",
        expected_attempt=first.attempt_count,
        expected_cursor_context_id=None,
        cursor_context_id="obsolete-context",
        scanned_count=1,
        invalidated_count=1,
        completed=True,
        now=reclaimed_at,
    )
    assert not await repository.record_physical_delete_target(
        rdb_session,
        operation_id=first.id,
        lease_owner="stable-worker",
        expected_attempt=first.attempt_count,
        required=True,
        target_generation=4,
        requested_at=reclaimed_at,
        now=reclaimed_at,
    )
    assert not await repository.record_physical_delete_acknowledgement(
        rdb_session,
        operation_id=first.id,
        lease_owner="stable-worker",
        expected_attempt=first.attempt_count,
        acknowledgement_kind=RuntimeTerminalDeleteAcknowledgementKind.PROVIDER_REPORT,
        acknowledged_at=reclaimed_at,
    )
    assert not await repository.mark_retry(
        rdb_session,
        operation_id=first.id,
        lease_owner="stable-worker",
        expected_attempt=first.attempt_count,
        next_attempt_at=reclaimed_at,
        error_kind="obsolete",
        error_summary="Obsolete attempt.",
        now=reclaimed_at,
    )
    assert not await repository.mark_completed(
        rdb_session,
        operation_id=first.id,
        lease_owner="stable-worker",
        expected_attempt=first.attempt_count,
        now=reclaimed_at,
    )
    assert await repository.set_stage(
        rdb_session,
        operation_id=winner.id,
        lease_owner="stable-worker",
        expected_attempt=winner.attempt_count,
        stage=AgentRuntimeRemovalStage.FINALIZING,
        now=reclaimed_at,
    )
    finalizer = AgentRuntimeRemovalFinalizerRepository(
        scope_repository=AgentRuntimeRemovalScopeRepository()
    )
    assert not await finalizer.finalize(
        rdb_session,
        operation_id=first.id,
        lease_owner="stable-worker",
        expected_attempt=first.attempt_count,
        now=reclaimed_at,
    )
    current = await repository.get_by_id(rdb_session, winner.id)
    assert current is not None
    assert current.status is AgentRuntimeRemovalStatus.RUNNING
    assert current.attempt_count == winner.attempt_count
    assert current.cleanup_cursor_context_id is None
    assert current.physical_deletion_required is None
