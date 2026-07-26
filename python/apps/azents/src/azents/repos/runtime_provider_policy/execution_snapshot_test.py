"""Execution-policy target and applied snapshot repository tests."""

import datetime
from unittest.mock import AsyncMock, Mock

from sqlalchemy.ext.asyncio import AsyncSession

from azents.core.enums import RuntimePolicySnapshotApplicationState

from .repository import RuntimeProviderPolicyRepository

_NOW = datetime.datetime.now(datetime.timezone.utc)


def _applied_snapshot() -> Mock:
    snapshot = Mock()
    snapshot.id = "snapshot-1"
    snapshot.runtime_id = "runtime-1"
    snapshot.provider_id = "provider-1"
    snapshot.contract_revision_id = "contract-1"
    snapshot.config_revision_id = None
    snapshot.override_provider_id = None
    snapshot.override_version = None
    snapshot.execution_profile_id = "system-standard"
    snapshot.execution_platform_version = 1
    snapshot.execution_profile_version = 1
    snapshot.execution_workspace_version = 1
    snapshot.execution_agent_version = 1
    snapshot.resolved_execution_policy = {"schema_version": 1}
    snapshot.execution_source_trace = {}
    snapshot.execution_provider_compatibility = {}
    snapshot.execution_target_digest = "a" * 64
    snapshot.execution_reported_digest = "a" * 64
    snapshot.resolved_config = {}
    snapshot.encrypted_secrets = None
    snapshot.secret_metadata = {}
    snapshot.source_trace = {}
    snapshot.digest = "b" * 64
    snapshot.target_desired_generation = 7
    snapshot.application_state = RuntimePolicySnapshotApplicationState.APPLIED
    snapshot.provider_acknowledged_at = _NOW
    snapshot.runtime_observed_at = _NOW
    snapshot.created_at = _NOW
    return snapshot


async def test_stale_snapshot_cannot_be_promoted_to_applied() -> None:
    """A non-current target stops before any snapshot state mutation."""
    session = AsyncMock(spec=AsyncSession)
    runtime_result = Mock()
    runtime_result.scalar_one_or_none.return_value = None
    session.execute.return_value = runtime_result

    promoted = (
        await RuntimeProviderPolicyRepository().promote_target_snapshot_to_applied(
            session,
            runtime_id="runtime-1",
            provider_id="provider-1",
            snapshot_id="snapshot-stale",
            target_desired_generation=7,
            reported_execution_digest="a" * 64,
            provider_acknowledged_at=_NOW,
            runtime_observed_at=_NOW,
        )
    )

    assert promoted is None
    session.execute.assert_awaited_once()
    statement = str(session.execute.await_args.args[0])
    assert "agent_runtimes.runtime_policy_snapshot_id" in statement
    assert "agent_runtimes.runtime_provider_resource_id" in statement
    assert "agent_runtimes.desired_generation" in statement
    assert "runtime_policy_snapshots.execution_target_digest" in statement


async def test_exact_target_promotion_updates_only_application_evidence() -> None:
    """Exact evidence advances the applied pointer and immutable evidence fields."""
    session = AsyncMock(spec=AsyncSession)
    runtime_result = Mock()
    runtime_result.scalar_one_or_none.return_value = "runtime-1"
    snapshot = _applied_snapshot()
    snapshot_result = Mock()
    snapshot_result.scalar_one_or_none.return_value = snapshot
    session.execute.side_effect = [runtime_result, snapshot_result]

    promoted = (
        await RuntimeProviderPolicyRepository().promote_target_snapshot_to_applied(
            session,
            runtime_id="runtime-1",
            provider_id="provider-1",
            snapshot_id="snapshot-1",
            target_desired_generation=7,
            reported_execution_digest="a" * 64,
            provider_acknowledged_at=_NOW,
            runtime_observed_at=_NOW,
        )
    )

    assert promoted is not None
    assert promoted.id == "snapshot-1"
    assert promoted.application_state is RuntimePolicySnapshotApplicationState.APPLIED
    assert session.execute.await_count == 2
    snapshot_statement = session.execute.await_args_list[1].args[0]
    compiled = snapshot_statement.compile()
    assert (
        compiled.params["application_state"]
        is RuntimePolicySnapshotApplicationState.APPLIED
    )
    assert compiled.params["execution_reported_digest"] == "a" * 64
    session.flush.assert_awaited_once()


async def test_repeated_exact_applied_acknowledgement_is_idempotent() -> None:
    """A repeated exact acknowledgement returns immutable applied evidence."""
    session = AsyncMock(spec=AsyncSession)
    runtime_result = Mock()
    runtime_result.scalar_one_or_none.return_value = "runtime-1"
    pending_update_result = Mock()
    pending_update_result.scalar_one_or_none.return_value = None
    applied_snapshot = _applied_snapshot()
    applied_select_result = Mock()
    applied_select_result.scalar_one_or_none.return_value = applied_snapshot
    session.execute.side_effect = [
        runtime_result,
        pending_update_result,
        applied_select_result,
    ]

    promoted = (
        await RuntimeProviderPolicyRepository().promote_target_snapshot_to_applied(
            session,
            runtime_id="runtime-1",
            provider_id="provider-1",
            snapshot_id="snapshot-1",
            target_desired_generation=7,
            reported_execution_digest="a" * 64,
            provider_acknowledged_at=_NOW + datetime.timedelta(seconds=1),
            runtime_observed_at=_NOW + datetime.timedelta(seconds=1),
        )
    )

    assert promoted is not None
    assert promoted.id == "snapshot-1"
    assert promoted.provider_acknowledged_at == _NOW
    assert promoted.runtime_observed_at == _NOW
    assert session.execute.await_count == 3
    applied_statement = str(session.execute.await_args_list[2].args[0])
    assert "runtime_policy_snapshots.execution_reported_digest" in applied_statement
    assert "runtime_policy_snapshots.application_state" in applied_statement
    session.flush.assert_awaited_once()
