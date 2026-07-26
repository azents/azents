"""Runtime execution-policy application and convergence tests."""

# pyright: reportPrivateUsage=false

import dataclasses
import datetime
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, Mock

import pytest

from azents.core.enums import (
    RuntimeDesiredState,
    RuntimeLifecycleCommandType,
    RuntimePolicySnapshotApplicationState,
    WorkspaceUserRole,
)
from azents.core.runtime_execution_policy import (
    RuntimeExecutionBooleanModule,
    RuntimeExecutionChangeDirection,
    RuntimeExecutionModuleId,
    RuntimeExecutionNetworkMode,
    RuntimeExecutionNetworkModule,
    RuntimeExecutionSourceVersions,
    RuntimeExecutionStorageMode,
    classify_runtime_execution_change,
    digest_runtime_execution_policy,
    empty_runtime_execution_restriction,
    resolve_runtime_execution_policy,
    standard_runtime_execution_policy,
)
from azents.repos.agent_runtime.data import AgentRuntime
from azents.repos.runtime_provider_policy.data import RuntimePolicySnapshot

from .application_service import (
    RuntimeExecutionPolicyApplicationService,
    RuntimeExecutionPolicyApplicationUnavailable,
    _automatic_convergence_source_allowed,
    _phase_three_provider_capabilities,
    _ResolvedRuntimePolicy,
    _restrictive_projection,
)

_NOW = datetime.datetime.now(datetime.timezone.utc)


@asynccontextmanager
async def _session_manager() -> AsyncIterator[Mock]:
    yield Mock()


def _runtime() -> AgentRuntime:
    return AgentRuntime(
        id="runtime-1",
        workspace_id="workspace-1",
        agent_id="agent-1",
        runtime_provider_id="provider-logical-1",
        runtime_provider_resource_id="provider-1",
        runtime_policy_snapshot_id="snapshot-1",
        desired_state=RuntimeDesiredState.RUNNING,
        desired_generation=2,
        created_at=_NOW,
        updated_at=_NOW,
    )


def _snapshot() -> RuntimePolicySnapshot:
    return RuntimePolicySnapshot(
        id="snapshot-1",
        runtime_id="runtime-1",
        provider_id="provider-1",
        contract_revision_id="contract-1",
        config_revision_id=None,
        override_provider_id=None,
        override_version=None,
        execution_profile_id=None,
        execution_platform_version=None,
        execution_profile_version=None,
        execution_workspace_version=None,
        execution_agent_version=None,
        resolved_execution_policy=None,
        execution_source_trace=None,
        execution_provider_compatibility=None,
        execution_target_digest=None,
        execution_reported_digest=None,
        resolved_config={},
        encrypted_secrets=None,
        secret_metadata={},
        source_trace={},
        digest="a" * 64,
        target_desired_generation=2,
        application_state=RuntimePolicySnapshotApplicationState.PENDING,
        provider_acknowledged_at=None,
        runtime_observed_at=None,
        created_at=_NOW,
    )


def _resolved() -> _ResolvedRuntimePolicy:
    standard = standard_runtime_execution_policy()
    resolution = resolve_runtime_execution_policy(
        platform_policy=standard,
        profile_policy=standard,
        workspace_restriction=empty_runtime_execution_restriction(),
        agent_restriction=empty_runtime_execution_restriction(),
        source_versions=RuntimeExecutionSourceVersions(
            platform=1,
            profile=2,
            workspace=3,
            agent=4,
        ),
        provider_capabilities=_phase_three_provider_capabilities(),
        profile_active=True,
        profile_allowed=True,
        applied_policy=None,
    )
    assert resolution.available
    return _ResolvedRuntimePolicy(
        runtime=_runtime(),
        target_snapshot=_snapshot(),
        applied_snapshot=None,
        profile_id="system-standard",
        resolution=resolution,
    )


def _unavailable_resolved() -> _ResolvedRuntimePolicy:
    policy = standard_runtime_execution_policy()
    unavailable = resolve_runtime_execution_policy(
        platform_policy=policy,
        profile_policy=policy,
        workspace_restriction=empty_runtime_execution_restriction(),
        agent_restriction=empty_runtime_execution_restriction(),
        source_versions=RuntimeExecutionSourceVersions(
            platform=1,
            profile=2,
            workspace=3,
            agent=4,
        ),
        provider_capabilities=_phase_three_provider_capabilities(),
        profile_active=False,
        profile_allowed=True,
        applied_policy=policy,
    )
    assert not unavailable.available
    resolved = _resolved()
    return dataclasses.replace(
        resolved,
        target_snapshot=dataclasses.replace(
            resolved.target_snapshot,
            execution_profile_id="system-standard",
            execution_platform_version=1,
            execution_profile_version=2,
            execution_workspace_version=3,
            execution_agent_version=4,
            resolved_execution_policy=policy.model_dump(mode="json"),
            execution_source_trace={},
            execution_provider_compatibility={},
            execution_target_digest=digest_runtime_execution_policy(policy),
        ),
        resolution=unavailable,
    )


async def test_apply_requires_existing_agent_management_authority() -> None:
    policy_repository = Mock()
    policy_repository.get_agent_workspace_id = AsyncMock(return_value="workspace-1")
    agent_admin_repository = Mock()
    agent_admin_repository.is_admin = AsyncMock(return_value=False)
    service = RuntimeExecutionPolicyApplicationService(
        session_manager=_session_manager,
        policy_repository=policy_repository,
        snapshot_repository=Mock(),
        runtime_repository=Mock(),
        agent_admin_repository=agent_admin_repository,
    )

    with pytest.raises(
        RuntimeExecutionPolicyApplicationUnavailable,
        match="agent_access_denied",
    ):
        await service.apply_agent_for_manager(
            agent_id="agent-1",
            workspace_id="workspace-1",
            workspace_user_id="workspace-user-1",
            role=WorkspaceUserRole.MEMBER,
            actor_workspace_user_id="workspace-user-1",
            correlation_id="apply-1",
        )


async def test_explicit_apply_creates_next_generation_target_atomically() -> None:
    policy_repository = Mock()
    policy_repository.append_audit_event = AsyncMock()
    snapshot_repository = Mock()
    created_snapshot = _snapshot()
    created_snapshot = dataclasses.replace(
        created_snapshot,
        id="snapshot-2",
        target_desired_generation=3,
        execution_target_digest="b" * 64,
    )
    snapshot_repository.create_and_advance_target_snapshot = AsyncMock(
        return_value=created_snapshot
    )
    service = RuntimeExecutionPolicyApplicationService(
        session_manager=Mock(),
        policy_repository=policy_repository,
        snapshot_repository=snapshot_repository,
        runtime_repository=Mock(),
        agent_admin_repository=Mock(),
    )
    resolved = _resolved()

    result = await service._target_resolution(
        Mock(),
        resolved=resolved,
        effective_policy=resolved.resolution.effective_policy,
        classification=RuntimeExecutionChangeDirection.APPLICATION,
        actor_workspace_user_id="workspace-user-1",
        correlation_id="apply-1",
        system_authority=False,
        reason_code="agent_apply",
    )

    assert result.created
    call = snapshot_repository.create_and_advance_target_snapshot.await_args
    assert call.kwargs["create"].target_desired_generation == 3
    assert call.kwargs["expected_target_snapshot_id"] == "snapshot-1"
    assert call.kwargs["lifecycle_command"] is RuntimeLifecycleCommandType.RESTART
    policy_repository.append_audit_event.assert_awaited_once()


async def test_terminal_delete_targets_next_generation_with_bound_snapshot() -> None:
    """Terminal deletion advances one exact snapshot generation atomically."""
    resolved = _resolved()
    snapshot_repository = Mock()
    snapshot_repository.create_and_advance_target_snapshot = AsyncMock(
        return_value=dataclasses.replace(
            _snapshot(),
            id="snapshot-2",
            target_desired_generation=3,
        )
    )
    runtime_repository = Mock()
    runtime_repository.get_by_id = AsyncMock(
        return_value=resolved.runtime.model_copy(
            update={
                "runtime_policy_snapshot_id": "snapshot-2",
                "desired_state": RuntimeDesiredState.STOPPED,
                "desired_generation": 3,
                "terminal_delete_requested_generation": 3,
            }
        )
    )
    service = RuntimeExecutionPolicyApplicationService(
        session_manager=_session_manager,
        policy_repository=Mock(),
        snapshot_repository=snapshot_repository,
        runtime_repository=runtime_repository,
        agent_admin_repository=Mock(),
    )
    service._resolve_locked = AsyncMock(return_value=resolved)

    command = await service.target_lifecycle_command(
        agent_id="agent-1",
        command_type=RuntimeLifecycleCommandType.STOP,
        desired_state=RuntimeDesiredState.STOPPED,
        reset_final_desired_state=None,
        terminal_delete_requested=True,
    )

    call = snapshot_repository.create_and_advance_target_snapshot.await_args
    assert call.kwargs["create"].provider_id == "provider-1"
    assert call.kwargs["create"].target_desired_generation == 3
    assert call.kwargs["expected_target_snapshot_id"] == "snapshot-1"
    assert call.kwargs["lifecycle_command"] is RuntimeLifecycleCommandType.STOP
    assert call.kwargs["desired_state"] is RuntimeDesiredState.STOPPED
    assert call.kwargs["reset_final_desired_state"] is None
    assert call.kwargs["terminal_delete_requested"] is True
    assert command.desired_generation == 3
    assert command.runtime.terminal_delete_requested_generation == 3


async def test_terminal_delete_retry_reuses_current_generation() -> None:
    """Retrying terminal deletion never creates a newer target snapshot."""
    resolved = _resolved()
    resolved = dataclasses.replace(
        resolved,
        runtime=resolved.runtime.model_copy(
            update={
                "terminal_delete_requested_generation": (
                    resolved.runtime.desired_generation
                )
            }
        ),
    )
    snapshot_repository = Mock()
    snapshot_repository.create_and_advance_target_snapshot = AsyncMock()
    service = RuntimeExecutionPolicyApplicationService(
        session_manager=_session_manager,
        policy_repository=Mock(),
        snapshot_repository=snapshot_repository,
        runtime_repository=Mock(),
        agent_admin_repository=Mock(),
    )
    service._resolve_locked = AsyncMock(return_value=resolved)

    command = await service.target_lifecycle_command(
        agent_id="agent-1",
        command_type=RuntimeLifecycleCommandType.STOP,
        desired_state=RuntimeDesiredState.STOPPED,
        reset_final_desired_state=None,
        terminal_delete_requested=True,
    )

    assert command.desired_generation == resolved.runtime.desired_generation
    assert command.runtime.runtime_policy_snapshot_id == "snapshot-1"
    snapshot_repository.create_and_advance_target_snapshot.assert_not_awaited()


def test_automatic_convergence_requires_unchanged_profile_and_agent_intent() -> None:
    """Only lower-layer version changes may be converged automatically."""
    resolved = _resolved()
    matching = dataclasses.replace(
        resolved,
        target_snapshot=dataclasses.replace(
            resolved.target_snapshot,
            execution_profile_version=2,
            execution_agent_version=4,
        ),
    )

    assert _automatic_convergence_source_allowed(matching)
    assert not _automatic_convergence_source_allowed(
        dataclasses.replace(
            matching,
            target_snapshot=dataclasses.replace(
                matching.target_snapshot,
                execution_profile_version=1,
            ),
        )
    )
    assert not _automatic_convergence_source_allowed(
        dataclasses.replace(
            matching,
            target_snapshot=dataclasses.replace(
                matching.target_snapshot,
                execution_agent_version=3,
            ),
        )
    )


async def test_incompatible_convergence_stops_with_a_new_exact_target() -> None:
    """Fail-closed stopping never advances generation without a target snapshot."""
    resolved = _unavailable_resolved()
    canonical_policy = resolved.target_snapshot.resolved_execution_policy
    assert canonical_policy is not None
    created_snapshot = dataclasses.replace(
        resolved.target_snapshot,
        id="snapshot-2",
        target_desired_generation=3,
    )
    snapshot_repository = Mock()
    snapshot_repository.create_and_advance_target_snapshot = AsyncMock(
        return_value=created_snapshot
    )
    runtime_repository = Mock()
    runtime_repository.get_by_id_for_update = AsyncMock(return_value=resolved.runtime)
    runtime_repository.get_by_id = AsyncMock(
        return_value=resolved.runtime.model_copy(
            update={
                "runtime_policy_snapshot_id": "snapshot-2",
                "desired_state": RuntimeDesiredState.STOPPED,
                "desired_generation": 3,
            }
        )
    )
    runtime_repository.set_desired_state = AsyncMock()
    policy_repository = Mock()
    policy_repository.append_audit_event = AsyncMock()
    service = RuntimeExecutionPolicyApplicationService(
        session_manager=_session_manager,
        policy_repository=policy_repository,
        snapshot_repository=snapshot_repository,
        runtime_repository=runtime_repository,
        agent_admin_repository=Mock(),
    )
    service._resolve_locked = AsyncMock(return_value=resolved)

    outcome = await service._converge_runtime("runtime-1")

    assert outcome == "stopped"
    call = snapshot_repository.create_and_advance_target_snapshot.await_args
    assert call.kwargs["create"].target_desired_generation == 3
    assert call.kwargs["create"].resolved_execution_policy == canonical_policy
    assert call.kwargs["lifecycle_command"] is RuntimeLifecycleCommandType.STOP
    assert call.kwargs["desired_state"] is RuntimeDesiredState.STOPPED
    assert call.kwargs["terminal_delete_requested"] is False
    runtime_repository.set_desired_state.assert_not_awaited()
    policy_repository.append_audit_event.assert_awaited_once()


async def test_unavailable_agent_intent_change_remains_pending_apply() -> None:
    """Agent Profile changes cannot trigger automatic fail-closed lifecycle."""
    resolved = _unavailable_resolved()
    resolved = dataclasses.replace(
        resolved,
        target_snapshot=dataclasses.replace(
            resolved.target_snapshot,
            execution_profile_version=1,
        ),
    )
    snapshot_repository = Mock()
    snapshot_repository.create_and_advance_target_snapshot = AsyncMock()
    runtime_repository = Mock()
    runtime_repository.get_by_id_for_update = AsyncMock(return_value=resolved.runtime)
    runtime_repository.set_desired_state = AsyncMock()
    policy_repository = Mock()
    policy_repository.append_audit_event = AsyncMock()
    service = RuntimeExecutionPolicyApplicationService(
        session_manager=_session_manager,
        policy_repository=policy_repository,
        snapshot_repository=snapshot_repository,
        runtime_repository=runtime_repository,
        agent_admin_repository=Mock(),
    )
    service._resolve_locked = AsyncMock(return_value=resolved)

    outcome = await service._converge_runtime("runtime-1")

    assert outcome == "pending_expansion"
    snapshot_repository.create_and_advance_target_snapshot.assert_not_awaited()
    runtime_repository.set_desired_state.assert_not_awaited()
    policy_repository.append_audit_event.assert_not_awaited()


def test_mixed_convergence_copies_only_restrictive_fields() -> None:
    standard = standard_runtime_execution_policy()
    applied = standard.model_copy(
        update={
            "image_build": RuntimeExecutionBooleanModule(
                module_id=RuntimeExecutionModuleId.IMAGE_BUILD,
                version=1,
                enabled=True,
            )
        }
    )
    current = standard.model_copy(
        update={
            "network_egress": RuntimeExecutionNetworkModule(
                module_id=RuntimeExecutionModuleId.NETWORK_EGRESS,
                version=1,
                mode=RuntimeExecutionNetworkMode.DIRECT,
                allowed_destinations=frozenset(),
                denied_destinations=frozenset(),
            )
        }
    )
    change = classify_runtime_execution_change(applied, current)
    assert change.direction is RuntimeExecutionChangeDirection.MIXED

    projected = _restrictive_projection(applied, current, change)

    assert projected.image_build.enabled is False
    assert projected.network_egress.mode is RuntimeExecutionNetworkMode.NONE


def test_phase_three_capabilities_cannot_grant_engine_or_network_authority() -> None:
    capabilities = _phase_three_provider_capabilities()

    assert not capabilities.privileged_engine
    assert capabilities.storage_modes == {RuntimeExecutionStorageMode.NONE}
    assert capabilities.network_modes == {RuntimeExecutionNetworkMode.NONE}
