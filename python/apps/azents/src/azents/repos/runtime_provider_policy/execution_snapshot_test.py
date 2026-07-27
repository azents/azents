"""Execution-policy target and applied snapshot repository tests."""

# pyright: reportPrivateUsage=false

import datetime
from unittest.mock import AsyncMock, Mock

from azents_runtime_control.execution_policy import RuntimeExecutionPolicyEvidence
from sqlalchemy.ext.asyncio import AsyncSession

from azents.core.enums import RuntimePolicySnapshotApplicationState
from azents.core.runtime_execution_policy import (
    canonical_runtime_execution_policy,
    canonical_runtime_execution_policy_json,
    digest_runtime_execution_policy,
    standard_runtime_execution_policy,
)

from .data import RuntimePolicySnapshot
from .repository import (
    RuntimeProviderPolicyRepository,
    _snapshot_evidence_matches,
)

_NOW = datetime.datetime.now(datetime.timezone.utc)
_POLICY = standard_runtime_execution_policy()
_POLICY_DOCUMENT = canonical_runtime_execution_policy(_POLICY)
_POLICY_JSON = canonical_runtime_execution_policy_json(_POLICY)
_DIGEST = digest_runtime_execution_policy(_POLICY)
_MODULE_VERSIONS: dict[str, int] = {}
for _value in _POLICY_DOCUMENT.values():
    if not isinstance(_value, dict):
        continue
    _module_id = _value.get("module_id")
    _version = _value.get("version")
    if isinstance(_module_id, str) and isinstance(_version, int):
        _MODULE_VERSIONS[_module_id] = _version


def _snapshot(
    state: RuntimePolicySnapshotApplicationState,
) -> RuntimePolicySnapshot:
    return RuntimePolicySnapshot(
        id="snapshot-1",
        runtime_id="runtime-1",
        provider_id="provider-1",
        contract_revision_id="contract-1",
        config_revision_id=None,
        override_provider_id=None,
        override_version=None,
        execution_profile_id="system-standard",
        execution_profile_version=2,
        execution_workspace_version=3,
        execution_agent_version=4,
        resolved_execution_policy_json=_POLICY_JSON,
        execution_source_trace={},
        execution_provider_compatibility={},
        execution_target_digest=_DIGEST,
        execution_reported_digest=(
            _DIGEST if state is RuntimePolicySnapshotApplicationState.APPLIED else None
        ),
        resolved_config={},
        encrypted_secrets=None,
        secret_metadata={},
        source_trace={},
        digest="b" * 64,
        target_desired_generation=7,
        application_state=state,
        provider_acknowledged_at=(
            _NOW if state is RuntimePolicySnapshotApplicationState.APPLIED else None
        ),
        runtime_observed_at=(
            _NOW if state is RuntimePolicySnapshotApplicationState.APPLIED else None
        ),
        created_at=_NOW,
    )


def _evidence(
    *,
    snapshot_id: str = "snapshot-1",
    digest: str = _DIGEST,
    desired_generation: int = 7,
    module_versions: dict[str, int] | None = None,
    source_versions: dict[str, int] | None = None,
) -> RuntimeExecutionPolicyEvidence:
    return RuntimeExecutionPolicyEvidence(
        snapshot_id=snapshot_id,
        digest=digest,
        desired_generation=desired_generation,
        module_versions=module_versions or _MODULE_VERSIONS,
        source_versions=source_versions
        or {
            "profile": 2,
            "workspace": 3,
            "agent": 4,
        },
    )


def test_snapshot_evidence_requires_exact_digest_generation_and_versions() -> None:
    snapshot = _snapshot(RuntimePolicySnapshotApplicationState.PENDING)

    assert _snapshot_evidence_matches(snapshot, _evidence())
    assert not _snapshot_evidence_matches(
        snapshot,
        _evidence(desired_generation=8),
    )
    assert not _snapshot_evidence_matches(
        snapshot,
        _evidence(source_versions={"profile": 2}),
    )
    assert not _snapshot_evidence_matches(
        snapshot,
        _evidence(module_versions={"docker": 2}),
    )


async def test_stale_provider_evidence_does_not_mutate_snapshot() -> None:
    repository = RuntimeProviderPolicyRepository()
    repository._lock_current_evidence_target = AsyncMock(return_value=None)
    session = AsyncMock(spec=AsyncSession)

    recorded = await repository.record_provider_execution_policy_evidence(
        session,
        runtime_id="runtime-1",
        provider_id="provider-1",
        evidence=_evidence(snapshot_id="stale"),
        acknowledged_at=_NOW,
    )

    assert recorded is None
    session.execute.assert_not_awaited()


async def test_provider_evidence_alone_keeps_snapshot_pending() -> None:
    repository = RuntimeProviderPolicyRepository()
    pending = _snapshot(RuntimePolicySnapshotApplicationState.PENDING)
    repository._lock_current_evidence_target = AsyncMock(return_value=pending)
    repository._promote_if_complete = AsyncMock(return_value=None)
    repository.get_snapshot = AsyncMock(return_value=pending)
    session = AsyncMock(spec=AsyncSession)

    recorded = await repository.record_provider_execution_policy_evidence(
        session,
        runtime_id="runtime-1",
        provider_id="provider-1",
        evidence=_evidence(),
        acknowledged_at=_NOW,
    )

    assert recorded is pending
    statement = session.execute.await_args.args[0]
    compiled = statement.compile()
    assert compiled.params["execution_reported_digest"] == _DIGEST
    assert compiled.params["provider_acknowledged_at"] == _NOW
    assert "runtime_observed_at" not in compiled.params


async def test_runner_evidence_alone_keeps_snapshot_pending() -> None:
    repository = RuntimeProviderPolicyRepository()
    pending = _snapshot(RuntimePolicySnapshotApplicationState.PENDING)
    repository._lock_current_evidence_target = AsyncMock(return_value=pending)
    repository._promote_if_complete = AsyncMock(return_value=None)
    repository.get_snapshot = AsyncMock(return_value=pending)
    session = AsyncMock(spec=AsyncSession)

    recorded = await repository.record_runner_execution_policy_evidence(
        session,
        runtime_id="runtime-1",
        provider_id="provider-1",
        evidence=_evidence(),
        observed_at=_NOW,
    )

    assert recorded is pending
    statement = session.execute.await_args.args[0]
    compiled = statement.compile()
    assert compiled.params["runtime_observed_at"] == _NOW
    assert "provider_acknowledged_at" not in compiled.params


async def test_promotion_requires_both_independent_evidence_timestamps() -> None:
    repository = RuntimeProviderPolicyRepository()
    applied = _snapshot(RuntimePolicySnapshotApplicationState.APPLIED)
    snapshot_result = Mock()
    snapshot_result.scalar_one_or_none.return_value = Mock(**applied.__dict__)
    runtime_result = Mock()
    runtime_result.scalar_one_or_none.return_value = "runtime-1"
    session = AsyncMock(spec=AsyncSession)
    session.execute.side_effect = [snapshot_result, runtime_result]

    promoted = await repository._promote_if_complete(
        session,
        runtime_id="runtime-1",
        provider_id="provider-1",
        evidence=_evidence(),
    )

    assert promoted is not None
    assert promoted.id == "snapshot-1"
    snapshot_statement = str(session.execute.await_args_list[0].args[0])
    assert "runtime_policy_snapshots.provider_acknowledged_at IS NOT NULL" in (
        snapshot_statement
    )
    assert "runtime_policy_snapshots.runtime_observed_at IS NOT NULL" in (
        snapshot_statement
    )
    runtime_statement = str(session.execute.await_args_list[1].args[0])
    assert "agent_runtimes.runtime_policy_snapshot_id" in runtime_statement
    assert "agent_runtimes.runtime_provider_resource_id" in runtime_statement
    assert "agent_runtimes.desired_generation" in runtime_statement
    session.flush.assert_awaited_once()
