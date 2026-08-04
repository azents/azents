"""Runtime lifecycle reconciler tests."""

# pyright: reportPrivateUsage=false

import datetime

import pytest
import sqlalchemy as sa
from azcommon.result import Success
from azents_runtime_control.provider import (
    RuntimeLifecycleCommandType as RuntimeProviderCommandType,
)
from cryptography.fernet import Fernet
from sqlalchemy.ext.asyncio import AsyncSession

from azents.core.enums import (
    LLMProvider,
    RuntimeDesiredState,
    RuntimeLifecycleCommandType,
    RuntimeProviderAvailabilityMode,
    RuntimeProviderConnectionState,
    RuntimeProviderKind,
    RuntimeProviderLifecycleState,
    RuntimeProviderObservedState,
    RuntimeProviderReconciliationStatus,
    RuntimeProviderRegistrationMethod,
    RuntimeProviderScope,
)
from azents.core.runtime_profile import (
    RuntimeConfigurationResolutionStatus,
    RuntimeInfrastructureProfileKind,
    RuntimeProfileLifecycle,
)
from azents.core.runtime_runner_credential import RuntimeRunnerCredentialVerifier
from azents.rdb.models.agent import RDBAgent
from azents.rdb.models.agent_runtime import RDBAgentRuntime
from azents.rdb.models.llm_provider_integration import RDBLLMProviderIntegration
from azents.rdb.models.runtime_profile import RDBRuntimeConfigurationRevision
from azents.rdb.models.runtime_provider_policy import (
    RDBRuntimeProviderContractRevision,
)
from azents.rdb.session import SessionManager
from azents.repos.agent_runtime import AgentRuntimeRepository
from azents.repos.runtime_profile.data import (
    RuntimeConfigurationRevision,
    RuntimeConfigurationRevisionCreate,
    RuntimeInfrastructureProfileCreate,
    WorkspaceRuntimeProfileCreate,
)
from azents.repos.runtime_profile.repository import RuntimeProfileRepository
from azents.repos.runtime_provider.data import RuntimeProviderCreate
from azents.repos.runtime_provider.repository import RuntimeProviderRepository
from azents.repos.workspace import WorkspaceRepository
from azents.repos.workspace.data import WorkspaceCreate
from azents.runtime.control_protocol.data import (
    RuntimeProtocolCapabilities,
    RuntimeProviderRegistration,
)
from azents.runtime.control_protocol.reconciler import (
    RuntimeLifecycleDispatchConfig,
    RuntimeLifecycleReconciler,
)
from azents.runtime.control_protocol.service import (
    RuntimeControlProtocolService,
)
from azents.runtime.coordination.memory import (
    InMemoryRuntimeCoordinationStore,
)
from azents.testing.model_selection import make_test_model_selection_dict


async def test_reconciler_refreshes_stale_provider_connection_before_start_timeout(
    rdb_session_manager: SessionManager[AsyncSession],
) -> None:
    """A Control restart must not trust the previous process's connection cache."""
    runtime_repository = AgentRuntimeRepository()
    async with rdb_session_manager() as session:
        workspace_id = await _create_workspace(session, "reconciler-stale-provider-ws")
        agent_id = await _create_agent(
            session,
            workspace_id,
            "reconciler-stale-provider-agent",
        )
        runtime = await runtime_repository.ensure_for_agent(session, agent_id)
        await _bind_runtime_provider(session, runtime.id)
        command = await runtime_repository.set_desired_state(
            session,
            runtime.id,
            RuntimeLifecycleCommandType.START,
            RuntimeDesiredState.RUNNING,
        )
        assert command is not None
        dispatched = await runtime_repository.mark_lifecycle_dispatched(
            session,
            runtime.id,
            command.desired_generation,
        )
        assert dispatched is not None
        observed = await runtime_repository.record_provider_observed_state(
            session,
            runtime.id,
            RuntimeProviderObservedState.STARTING,
            1,
            command.desired_generation,
        )
        assert observed is not None
        connected = await runtime_repository.record_provider_connection_state(
            session,
            runtime.id,
            RuntimeProviderConnectionState.CONNECTED,
        )
        assert connected is not None
        old_state_change_at = datetime.datetime.now(datetime.UTC) - datetime.timedelta(
            minutes=10
        )
        await session.execute(
            sa.update(RDBAgentRuntime)
            .where(RDBAgentRuntime.id == runtime.id)
            .values(last_state_change_at=old_state_change_at)
        )

    store = InMemoryRuntimeCoordinationStore()
    reconciler = RuntimeLifecycleReconciler(
        runtime_repository=runtime_repository,
        profile_repository=RuntimeProfileRepository(),
        session_manager=rdb_session_manager,
        coordination_store=store,
        control_protocol=RuntimeControlProtocolService(store),
        config=RuntimeLifecycleDispatchConfig(
            runner_image="runner:test",
            runner_control_endpoint="runtime-control:9090",
            runner_transfer_endpoint="runtime-transfer:9091",
            runner_credential_identifier=_runner_credential_verifier(),
            runner_control_tls_ca_pem=None,
            allow_insecure_runner_control=True,
            start_timeout=datetime.timedelta(minutes=5),
            lifecycle_retry_delay=datetime.timedelta(minutes=1),
        ),
    )

    dispatched_count = await reconciler.reconcile_once(limit=10)
    async with rdb_session_manager() as session:
        updated = await runtime_repository.get_by_agent_id(session, agent_id)

    assert dispatched_count == 0
    assert updated is not None
    assert (
        updated.provider_connection_state == RuntimeProviderConnectionState.DISCONNECTED
    )
    assert updated.failure_code is None


@pytest.mark.parametrize(
    "provider_observed_state",
    [
        RuntimeProviderObservedState.STARTING,
        RuntimeProviderObservedState.RUNNING,
    ],
)
async def test_reconciler_observes_active_runtime_without_restarting_it(
    rdb_session_manager: SessionManager[AsyncSession],
    provider_observed_state: RuntimeProviderObservedState,
) -> None:
    """Control observes a starting/running Runtime without repeating START."""
    runtime_repository = AgentRuntimeRepository()
    async with rdb_session_manager() as session:
        workspace_id = await _create_workspace(session, "reconciler-observe-ws")
        agent_id = await _create_agent(
            session,
            workspace_id,
            "reconciler-observe-agent",
        )
        runtime = await runtime_repository.ensure_for_agent(session, agent_id)
        await _bind_runtime_provider(session, runtime.id)
        runtime = await runtime_repository.record_provider_connection_state(
            session,
            runtime.id,
            RuntimeProviderConnectionState.CONNECTED,
        )
        assert runtime is not None
        command = await runtime_repository.set_desired_state(
            session,
            runtime.id,
            RuntimeLifecycleCommandType.START,
            RuntimeDesiredState.RUNNING,
        )
        assert command is not None
        revision = await _attach_runtime_configuration(
            session,
            runtime_id=runtime.id,
            target_desired_generation=command.desired_generation,
        )
        await session.execute(
            sa.update(RDBAgentRuntime)
            .where(RDBAgentRuntime.id == runtime.id)
            .values(applied_runtime_configuration_revision_id=revision.id)
        )
        await runtime_repository.mark_lifecycle_dispatched(
            session,
            runtime.id,
            command.desired_generation,
        )
        observed = await runtime_repository.record_provider_observed_state(
            session,
            runtime.id,
            provider_observed_state,
            1,
            command.desired_generation,
        )
        assert observed is not None
        old_observe_at = datetime.datetime.now(datetime.UTC) - datetime.timedelta(
            minutes=10
        )
        await session.execute(
            sa.update(RDBAgentRuntime)
            .where(RDBAgentRuntime.id == runtime.id)
            .values(
                provider_observed_at=old_observe_at,
                provider_observe_requested_at=old_observe_at,
            )
        )
    store = InMemoryRuntimeCoordinationStore()
    control_protocol = RuntimeControlProtocolService(
        store,
        request_id_factory=lambda: "request-1",
    )
    accepted = await control_protocol.register_provider(
        _provider_registration(),
        registered_at=datetime.datetime.now(datetime.UTC),
    )
    reconciler = RuntimeLifecycleReconciler(
        runtime_repository=runtime_repository,
        profile_repository=RuntimeProfileRepository(),
        session_manager=rdb_session_manager,
        coordination_store=store,
        control_protocol=control_protocol,
        config=RuntimeLifecycleDispatchConfig(
            runner_image="runner:test",
            runner_control_endpoint="runtime-control:9090",
            runner_transfer_endpoint="runtime-transfer:9091",
            runner_credential_identifier=_runner_credential_verifier(),
            runner_control_tls_ca_pem=None,
            allow_insecure_runner_control=True,
            observe_interval=datetime.timedelta(minutes=1),
        ),
    )

    dispatched = await reconciler.reconcile_once(limit=10)
    claimed = await control_protocol.claim_next_provider_request(
        provider_id="provider-1",
        generation=accepted.generation,
        consumer_id="provider-worker",
        block_ms=0,
    )
    async with rdb_session_manager() as session:
        updated = await runtime_repository.get_by_agent_id(session, agent_id)

    assert dispatched == 1
    assert claimed is not None
    assert claimed.operation_type == "provider.observe"
    assert claimed.payload["command_type"] == "observe"
    payload = claimed.payload["payload"]
    assert isinstance(payload, dict)
    auth = payload["auth"]
    assert isinstance(auth, dict)
    assert isinstance(auth["runner_auth_credential_id"], str)
    assert auth["transfer_endpoint"] == "runtime-transfer:9091"
    assert "runner_auth_token" not in auth
    assert "control_token" not in auth
    assert updated is not None
    assert updated.provider_observe_requested_at is not None


async def test_reconciler_repairs_current_network_policy_drift_once(
    rdb_session_manager: SessionManager[AsyncSession],
) -> None:
    """Current exact evidence dispatches one in-place configuration repair."""
    runtime_repository = AgentRuntimeRepository()
    observed_at = datetime.datetime.now(datetime.UTC)
    async with rdb_session_manager() as session:
        workspace_id = await _create_workspace(session, "reconciler-drift-ws")
        agent_id = await _create_agent(
            session,
            workspace_id,
            "reconciler-drift-agent",
        )
        runtime = await runtime_repository.ensure_for_agent(session, agent_id)
        await _bind_runtime_provider(session, runtime.id)
        command = await runtime_repository.set_desired_state(
            session,
            runtime.id,
            RuntimeLifecycleCommandType.START,
            RuntimeDesiredState.RUNNING,
        )
        assert command is not None
        revision = await _attach_runtime_configuration(
            session,
            runtime_id=runtime.id,
            target_desired_generation=command.desired_generation,
        )
        await session.execute(
            sa.update(RDBAgentRuntime)
            .where(RDBAgentRuntime.id == runtime.id)
            .values(applied_runtime_configuration_revision_id=revision.id)
        )
        dispatched = await runtime_repository.mark_lifecycle_dispatched(
            session,
            runtime.id,
            command.desired_generation,
        )
        assert dispatched is not None
        running = await runtime_repository.record_provider_observed_state(
            session,
            runtime.id,
            RuntimeProviderObservedState.RUNNING,
            1,
            command.desired_generation,
        )
        assert running is not None
        evidence = await runtime_repository.record_provider_reconciliation_observation(
            session,
            runtime_id=runtime.id,
            status=RuntimeProviderReconciliationStatus.DRIFTED,
            kind="network_policy",
            reason="network_policy_mismatch",
            provider_generation=1,
            observed_generation=command.desired_generation,
            configuration_revision_id=revision.id,
            observed_at=observed_at,
        )
        assert evidence is not None
        stale = await runtime_repository.record_provider_reconciliation_observation(
            session,
            runtime_id=runtime.id,
            status=RuntimeProviderReconciliationStatus.DRIFTED,
            kind="network_policy",
            reason="network_policy_mismatch",
            provider_generation=0,
            observed_generation=command.desired_generation,
            configuration_revision_id=revision.id,
            observed_at=observed_at,
        )
        assert stale is None

    store = InMemoryRuntimeCoordinationStore()
    control_protocol = RuntimeControlProtocolService(
        store,
        request_id_factory=lambda: "request-network-policy-repair",
    )
    accepted = await control_protocol.register_provider(
        _provider_registration(),
        registered_at=datetime.datetime.now(datetime.UTC),
    )
    reconciler = RuntimeLifecycleReconciler(
        runtime_repository=runtime_repository,
        profile_repository=RuntimeProfileRepository(),
        session_manager=rdb_session_manager,
        coordination_store=store,
        control_protocol=control_protocol,
        config=RuntimeLifecycleDispatchConfig(
            runner_image="runner:test",
            runner_control_endpoint="runtime-control:9090",
            runner_transfer_endpoint="runtime-transfer:9091",
            runner_credential_identifier=_runner_credential_verifier(),
            runner_control_tls_ca_pem=None,
            allow_insecure_runner_control=True,
        ),
    )

    first_dispatched = await reconciler.reconcile_once(limit=10)
    claimed = await control_protocol.claim_next_provider_request(
        provider_id="provider-1",
        generation=accepted.generation,
        consumer_id="provider-worker",
        block_ms=0,
    )
    second_dispatched = await reconciler.reconcile_once(limit=10)
    async with rdb_session_manager() as session:
        await session.execute(
            sa.update(RDBAgentRuntime)
            .where(RDBAgentRuntime.agent_id == agent_id)
            .values(
                provider_reconciliation_requested_at=(
                    datetime.datetime.now(datetime.UTC) - datetime.timedelta(minutes=1)
                )
            )
        )
    retry_dispatched = await reconciler.reconcile_once(limit=10)
    async with rdb_session_manager() as session:
        runtime = await runtime_repository.get_by_agent_id(session, agent_id)
        assert runtime is not None
        in_sync = await runtime_repository.record_provider_reconciliation_observation(
            session,
            runtime_id=runtime.id,
            status=RuntimeProviderReconciliationStatus.IN_SYNC,
            kind="network_policy",
            reason="network_policy_in_sync",
            provider_generation=1,
            observed_generation=command.desired_generation,
            configuration_revision_id=revision.id,
            observed_at=observed_at + datetime.timedelta(seconds=1),
        )
        assert in_sync is not None
    in_sync_dispatched = await reconciler.reconcile_once(limit=10)
    async with rdb_session_manager() as session:
        updated = await runtime_repository.get_by_agent_id(session, agent_id)

    assert first_dispatched == 1
    assert claimed is not None
    assert claimed.payload["command_type"] == "update_configuration"
    assert second_dispatched == 0
    assert retry_dispatched == 1
    assert in_sync_dispatched == 0
    assert updated is not None
    assert (
        updated.provider_reconciliation_status
        is RuntimeProviderReconciliationStatus.IN_SYNC
    )
    assert updated.provider_reconciliation_requested_at is None


async def test_reconciliation_dispatch_rechecks_provider_generation(
    rdb_session_manager: SessionManager[AsyncSession],
) -> None:
    """A reconnect after evidence claim cannot receive the stale repair."""
    runtime_repository = AgentRuntimeRepository()
    async with rdb_session_manager() as session:
        workspace_id = await _create_workspace(
            session,
            "reconciler-drift-generation-ws",
        )
        agent_id = await _create_agent(
            session,
            workspace_id,
            "reconciler-drift-generation-agent",
        )
        runtime = await runtime_repository.ensure_for_agent(session, agent_id)
        await _bind_runtime_provider(session, runtime.id)
        command = await runtime_repository.set_desired_state(
            session,
            runtime.id,
            RuntimeLifecycleCommandType.START,
            RuntimeDesiredState.RUNNING,
        )
        assert command is not None
        await _attach_runtime_configuration(
            session,
            runtime_id=runtime.id,
            target_desired_generation=command.desired_generation,
        )
        runtime = await runtime_repository.get_by_id(session, runtime.id)
        assert runtime is not None

    store = InMemoryRuntimeCoordinationStore()
    control_protocol = RuntimeControlProtocolService(
        store,
        request_id_factory=lambda: "request-stale-network-policy-repair",
    )
    previous = await control_protocol.register_provider(
        _provider_registration(connection_id="provider-connection-1"),
        registered_at=datetime.datetime.now(datetime.UTC),
    )
    current = await control_protocol.register_provider(
        _provider_registration(connection_id="provider-connection-2"),
        registered_at=datetime.datetime.now(datetime.UTC),
    )
    reconciler = RuntimeLifecycleReconciler(
        runtime_repository=runtime_repository,
        profile_repository=RuntimeProfileRepository(),
        session_manager=rdb_session_manager,
        coordination_store=store,
        control_protocol=control_protocol,
        config=RuntimeLifecycleDispatchConfig(
            runner_image="runner:test",
            runner_control_endpoint="runtime-control:9090",
            runner_transfer_endpoint="runtime-transfer:9091",
            runner_credential_identifier=_runner_credential_verifier(),
            runner_control_tls_ca_pem=None,
            allow_insecure_runner_control=True,
        ),
    )

    dispatched = await reconciler._dispatch_runtime_command(
        runtime,
        command_type=RuntimeProviderCommandType.UPDATE_CONFIGURATION,
        claim_lifecycle=False,
        required_provider_generation=previous.generation,
    )
    claimed = await control_protocol.claim_next_provider_request(
        provider_id="provider-1",
        generation=current.generation,
        consumer_id="provider-worker",
        block_ms=0,
    )

    assert current.generation > previous.generation
    assert dispatched is False
    assert claimed is None


async def test_reconciler_fences_adoption_then_finishes_restart_replacement(
    rdb_session_manager: SessionManager[AsyncSession],
) -> None:
    """Configuration adoption and restart convergence never compete."""
    runtime_repository = AgentRuntimeRepository()
    async with rdb_session_manager() as session:
        workspace_id = await _create_workspace(session, "reconciler-restart-ws")
        agent_id = await _create_agent(
            session,
            workspace_id,
            "reconciler-restart-agent",
        )
        runtime = await runtime_repository.ensure_for_agent(session, agent_id)
        await _bind_runtime_provider(session, runtime.id)
        initial = await runtime_repository.set_desired_state(
            session,
            runtime.id,
            RuntimeLifecycleCommandType.START,
            RuntimeDesiredState.RUNNING,
        )
        assert initial is not None
        initial_revision = await _attach_runtime_configuration(
            session,
            runtime_id=runtime.id,
            target_desired_generation=initial.desired_generation,
        )
        await session.execute(
            sa.update(RDBAgentRuntime)
            .where(RDBAgentRuntime.id == runtime.id)
            .values(applied_runtime_configuration_revision_id=initial_revision.id)
        )
        restart = await runtime_repository.set_desired_state_if_ready(
            session,
            runtime.id,
            RuntimeLifecycleCommandType.RESTART,
            RuntimeDesiredState.RUNNING,
            expected_configuration_revision_id=initial_revision.id,
        )
        assert restart is not None
        desired_revision_id = restart.runtime.desired_runtime_configuration_revision_id
        assert desired_revision_id is not None
        await session.execute(
            sa.update(RDBRuntimeConfigurationRevision)
            .where(RDBRuntimeConfigurationRevision.id == desired_revision_id)
            .values(
                provider_reported_digest="d" * 64,
                provider_acknowledged_at=datetime.datetime.now(datetime.UTC),
            )
        )
        dispatched = await runtime_repository.mark_lifecycle_dispatched(
            session,
            runtime.id,
            restart.desired_generation,
        )
        assert dispatched is not None
        running = await runtime_repository.record_provider_observed_state(
            session,
            runtime.id,
            RuntimeProviderObservedState.RUNNING,
            1,
            restart.desired_generation,
        )
        assert running is not None
        drift = await runtime_repository.record_provider_reconciliation_observation(
            session,
            runtime_id=runtime.id,
            status=RuntimeProviderReconciliationStatus.DRIFTED,
            kind="network_policy",
            reason="network_policy_mismatch",
            provider_generation=1,
            observed_generation=restart.desired_generation,
            configuration_revision_id=desired_revision_id,
            observed_at=datetime.datetime.now(datetime.UTC),
        )
        assert drift is not None
        drift_candidates = (
            await runtime_repository.find_provider_reconciliation_candidates(
                session,
                limit=10,
            )
        )
        assert drift_candidates == []
        old_observe_at = datetime.datetime.now(datetime.UTC) - datetime.timedelta(
            minutes=10
        )
        await session.execute(
            sa.update(RDBAgentRuntime)
            .where(RDBAgentRuntime.id == runtime.id)
            .values(
                provider_observed_at=old_observe_at,
                provider_observe_requested_at=old_observe_at,
            )
        )

    store = InMemoryRuntimeCoordinationStore()
    control_protocol = RuntimeControlProtocolService(
        store,
        request_id_factory=lambda: "request-restart-replacement",
    )
    accepted = await control_protocol.register_provider(
        _provider_registration(),
        registered_at=datetime.datetime.now(datetime.UTC),
    )
    reconciler = RuntimeLifecycleReconciler(
        runtime_repository=runtime_repository,
        profile_repository=RuntimeProfileRepository(),
        session_manager=rdb_session_manager,
        coordination_store=store,
        control_protocol=control_protocol,
        config=RuntimeLifecycleDispatchConfig(
            runner_image="runner:test",
            runner_control_endpoint="runtime-control:9090",
            runner_transfer_endpoint="runtime-transfer:9091",
            runner_credential_identifier=_runner_credential_verifier(),
            runner_control_tls_ca_pem=None,
            allow_insecure_runner_control=True,
            observe_interval=datetime.timedelta(minutes=1),
        ),
    )

    guarded = await reconciler._dispatch_periodic_reconcile(running)
    fenced = await reconciler.reconcile_once(limit=10)
    competing = await control_protocol.claim_next_provider_request(
        provider_id="provider-1",
        generation=accepted.generation,
        consumer_id="provider-worker",
        block_ms=0,
    )
    async with rdb_session_manager() as session:
        observed = await runtime_repository.record_provider_observed_state(
            session,
            runtime.id,
            RuntimeProviderObservedState.STARTING,
            1,
            restart.desired_generation,
        )
        assert observed is not None
        await session.execute(
            sa.update(RDBAgentRuntime)
            .where(RDBAgentRuntime.id == runtime.id)
            .values(
                provider_observed_at=old_observe_at,
                provider_observe_requested_at=old_observe_at,
            )
        )

    reconciled = await reconciler.reconcile_once(limit=10)
    claimed = await control_protocol.claim_next_provider_request(
        provider_id="provider-1",
        generation=accepted.generation,
        consumer_id="provider-worker",
        block_ms=0,
    )

    assert not guarded
    assert fenced == 0
    assert competing is None
    assert reconciled == 1
    assert claimed is not None
    assert claimed.operation_type == "provider.observe"
    assert claimed.payload["command_type"] == "observe"
    runtime_configuration = claimed.payload["runtime_configuration"]
    assert isinstance(runtime_configuration, dict)
    assert runtime_configuration["desired_generation"] == restart.desired_generation


async def test_reconciler_repairs_stale_stop_configuration_generation(
    rdb_session_manager: SessionManager[AsyncSession],
) -> None:
    """STOP clones usable configuration evidence for its desired generation."""
    runtime_repository = AgentRuntimeRepository()
    profile_repository = RuntimeProfileRepository()
    async with rdb_session_manager() as session:
        workspace_id = await _create_workspace(session, "reconciler-stop-repair-ws")
        agent_id = await _create_agent(
            session,
            workspace_id,
            "reconciler-stop-repair-agent",
        )
        runtime = await runtime_repository.ensure_for_agent(session, agent_id)
        await _bind_runtime_provider(session, runtime.id)
        start = await runtime_repository.set_desired_state(
            session,
            runtime.id,
            RuntimeLifecycleCommandType.START,
            RuntimeDesiredState.RUNNING,
        )
        assert start is not None
        source_revision = await _attach_runtime_configuration(
            session,
            runtime_id=runtime.id,
            target_desired_generation=start.desired_generation,
        )
        stop = await runtime_repository.set_desired_state(
            session,
            runtime.id,
            RuntimeLifecycleCommandType.STOP,
            RuntimeDesiredState.STOPPED,
        )
        assert stop is not None
        repeated = await runtime_repository.set_desired_state(
            session,
            runtime.id,
            RuntimeLifecycleCommandType.STOP,
            RuntimeDesiredState.STOPPED,
        )
        assert repeated is not None
        assert repeated.desired_generation == stop.desired_generation

    store = InMemoryRuntimeCoordinationStore()
    control_protocol = RuntimeControlProtocolService(
        store,
        request_id_factory=lambda: "stop-repair-request",
    )
    accepted = await control_protocol.register_provider(
        _provider_registration(),
        registered_at=datetime.datetime.now(datetime.UTC),
    )
    reconciler = RuntimeLifecycleReconciler(
        runtime_repository=runtime_repository,
        profile_repository=profile_repository,
        session_manager=rdb_session_manager,
        coordination_store=store,
        control_protocol=control_protocol,
        config=RuntimeLifecycleDispatchConfig(
            runner_image="runner:test",
            runner_control_endpoint="runtime-control:9090",
            runner_transfer_endpoint="runtime-transfer:9091",
            runner_credential_identifier=_runner_credential_verifier(),
            runner_control_tls_ca_pem=None,
            allow_insecure_runner_control=True,
        ),
    )

    dispatched = await reconciler.reconcile_once(limit=10)
    claimed = await control_protocol.claim_next_provider_request(
        provider_id="provider-1",
        generation=accepted.generation,
        consumer_id="provider-worker",
        block_ms=0,
    )
    async with rdb_session_manager() as session:
        updated = await runtime_repository.get_by_agent_id(session, agent_id)
        assert updated is not None
        revision_id = updated.desired_runtime_configuration_revision_id
        assert revision_id is not None
        repaired_revision = await profile_repository.get_configuration_revision(
            session,
            revision_id=revision_id,
        )

    assert dispatched == 1
    assert claimed is not None
    assert claimed.operation_type == "provider.stop"
    assert claimed.payload["desired_generation"] == stop.desired_generation
    runtime_configuration = claimed.payload["runtime_configuration"]
    assert isinstance(runtime_configuration, dict)
    assert runtime_configuration["desired_generation"] == stop.desired_generation
    assert repaired_revision is not None
    assert repaired_revision.id != source_revision.id
    assert repaired_revision.digest == source_revision.digest
    assert repaired_revision.target_desired_generation == stop.desired_generation


async def test_reconciler_rejects_mismatched_resolved_provider_reference(
    rdb_session_manager: SessionManager[AsyncSession],
) -> None:
    """Dispatch validates resolved references against the immutable revision row."""
    runtime_repository = AgentRuntimeRepository()
    async with rdb_session_manager() as session:
        workspace_id = await _create_workspace(
            session,
            "reconciler-provider-reference-ws",
        )
        agent_id = await _create_agent(
            session,
            workspace_id,
            "reconciler-provider-reference-agent",
        )
        runtime = await runtime_repository.ensure_for_agent(session, agent_id)
        await _bind_runtime_provider(session, runtime.id)
        command = await runtime_repository.set_desired_state(
            session,
            runtime.id,
            RuntimeLifecycleCommandType.START,
            RuntimeDesiredState.RUNNING,
        )
        assert command is not None
        revision = await _attach_runtime_configuration(
            session,
            runtime_id=runtime.id,
            target_desired_generation=command.desired_generation,
        )
        configuration = dict(revision.resolved_configuration or {})
        provider_reference = configuration["provider"]
        assert isinstance(provider_reference, dict)
        configuration["provider"] = {
            **provider_reference,
            "id": "mismatched-provider-resource",
        }
        await session.execute(
            sa.update(RDBRuntimeConfigurationRevision)
            .where(RDBRuntimeConfigurationRevision.id == revision.id)
            .values(resolved_configuration=configuration)
        )
        current = await runtime_repository.get_by_id(session, runtime.id)
        assert current is not None

    store = InMemoryRuntimeCoordinationStore()
    reconciler = RuntimeLifecycleReconciler(
        runtime_repository=runtime_repository,
        profile_repository=RuntimeProfileRepository(),
        session_manager=rdb_session_manager,
        coordination_store=store,
        control_protocol=RuntimeControlProtocolService(store),
        config=RuntimeLifecycleDispatchConfig(
            runner_image="runner:test",
            runner_control_endpoint="runtime-control:9090",
            runner_transfer_endpoint="runtime-transfer:9091",
            runner_credential_identifier=_runner_credential_verifier(),
            runner_control_tls_ca_pem=None,
            allow_insecure_runner_control=True,
        ),
    )

    with pytest.raises(ValueError, match="Provider reference"):
        await reconciler._runtime_configuration(current)


async def test_reconciler_observes_stopping_runtime_after_provider_reconnect(
    rdb_session_manager: SessionManager[AsyncSession],
) -> None:
    """A reconnected Provider reconciles a stopped-desired Runtime."""
    runtime_repository = AgentRuntimeRepository()
    async with rdb_session_manager() as session:
        workspace_id = await _create_workspace(
            session,
            "reconciler-disconnected-stopping-ws",
        )
        agent_id = await _create_agent(
            session,
            workspace_id,
            "reconciler-disconnected-stopping-agent",
        )
        runtime = await runtime_repository.ensure_for_agent(session, agent_id)
        await _bind_runtime_provider(session, runtime.id)
        command = await runtime_repository.set_desired_state(
            session,
            runtime.id,
            RuntimeLifecycleCommandType.STOP,
            RuntimeDesiredState.STOPPED,
        )
        assert command is not None
        await _attach_runtime_configuration(
            session,
            runtime_id=runtime.id,
            target_desired_generation=command.desired_generation,
        )
        await runtime_repository.mark_lifecycle_dispatched(
            session,
            runtime.id,
            command.desired_generation,
        )
        runtime = await runtime_repository.record_provider_observed_state(
            session,
            runtime.id,
            RuntimeProviderObservedState.STOPPING,
            1,
            command.desired_generation,
        )
        assert runtime is not None
        old_observe_at = datetime.datetime.now(datetime.UTC) - datetime.timedelta(
            minutes=10
        )
        await session.execute(
            sa.update(RDBAgentRuntime)
            .where(RDBAgentRuntime.id == runtime.id)
            .values(
                provider_connection_state=RuntimeProviderConnectionState.DISCONNECTED,
                provider_observed_at=old_observe_at,
                provider_observe_requested_at=old_observe_at,
            )
        )

    store = InMemoryRuntimeCoordinationStore()
    control_protocol = RuntimeControlProtocolService(
        store,
        request_id_factory=lambda: "request-disconnected-stopping",
    )
    reconciler = RuntimeLifecycleReconciler(
        runtime_repository=runtime_repository,
        profile_repository=RuntimeProfileRepository(),
        session_manager=rdb_session_manager,
        coordination_store=store,
        control_protocol=control_protocol,
        config=RuntimeLifecycleDispatchConfig(
            runner_image="runner:test",
            runner_control_endpoint="runtime-control:9090",
            runner_transfer_endpoint="runtime-transfer:9091",
            runner_credential_identifier=_runner_credential_verifier(),
            runner_control_tls_ca_pem=None,
            allow_insecure_runner_control=True,
            observe_interval=datetime.timedelta(minutes=1),
        ),
    )

    unavailable = await reconciler.reconcile_once(limit=10)
    throttled = await reconciler.reconcile_once(limit=10)
    async with rdb_session_manager() as session:
        waiting = await runtime_repository.get_by_agent_id(session, agent_id)
        await session.execute(
            sa.update(RDBAgentRuntime)
            .where(RDBAgentRuntime.id == runtime.id)
            .values(provider_observe_requested_at=old_observe_at)
        )
    accepted = await control_protocol.register_provider(
        _provider_registration(),
        registered_at=datetime.datetime.now(datetime.UTC),
    )
    dispatched = await reconciler.reconcile_once(limit=10)
    claimed = await control_protocol.claim_next_provider_request(
        provider_id="provider-1",
        generation=accepted.generation,
        consumer_id="provider-worker",
        block_ms=0,
    )
    async with rdb_session_manager() as session:
        updated = await runtime_repository.get_by_agent_id(session, agent_id)

    assert unavailable == 0
    assert throttled == 0
    assert waiting is not None
    assert (
        waiting.provider_connection_state == RuntimeProviderConnectionState.DISCONNECTED
    )
    assert waiting.provider_observe_requested_at is not None
    assert dispatched == 1
    assert claimed is not None
    assert claimed.operation_type == "provider.observe"
    assert claimed.payload["command_type"] == "observe"
    assert updated is not None
    assert updated.provider_connection_state == RuntimeProviderConnectionState.CONNECTED
    assert updated.provider_observe_requested_at is not None


async def test_reconciler_dispatches_terminal_delete_until_acknowledged(
    rdb_session_manager: SessionManager[AsyncSession],
) -> None:
    """Terminal deletion uses the internal Provider command rather than STOP."""
    runtime_repository = AgentRuntimeRepository()
    async with rdb_session_manager() as session:
        workspace_id = await _create_workspace(session, "reconciler-terminal-ws")
        agent_id = await _create_agent(
            session,
            workspace_id,
            "reconciler-terminal-agent",
        )
        runtime = await runtime_repository.ensure_for_agent(session, agent_id)
        await _bind_runtime_provider(session, runtime.id)
        requested = await runtime_repository.request_terminal_delete(
            session,
            runtime.id,
        )
        assert requested is not None
        await _attach_runtime_configuration(
            session,
            runtime_id=runtime.id,
            target_desired_generation=requested.desired_generation,
        )
        connected = await runtime_repository.record_provider_connection_state(
            session,
            runtime.id,
            RuntimeProviderConnectionState.CONNECTED,
        )
        assert connected is not None

    store = InMemoryRuntimeCoordinationStore()
    control_protocol = RuntimeControlProtocolService(
        store,
        request_id_factory=lambda: "terminal-request",
    )
    accepted = await control_protocol.register_provider(
        _provider_registration(),
        registered_at=datetime.datetime.now(datetime.UTC),
    )
    reconciler = RuntimeLifecycleReconciler(
        runtime_repository=runtime_repository,
        profile_repository=RuntimeProfileRepository(),
        session_manager=rdb_session_manager,
        coordination_store=store,
        control_protocol=control_protocol,
        config=RuntimeLifecycleDispatchConfig(
            runner_image="runner:test",
            runner_control_endpoint="runtime-control:9090",
            runner_transfer_endpoint="runtime-transfer:9091",
            runner_credential_identifier=_runner_credential_verifier(),
            runner_control_tls_ca_pem=None,
            allow_insecure_runner_control=True,
        ),
    )

    dispatched = await reconciler.reconcile_once(limit=10)
    claimed = await control_protocol.claim_next_provider_request(
        provider_id="provider-1",
        generation=accepted.generation,
        consumer_id="provider-worker",
        block_ms=0,
    )

    assert dispatched == 1
    assert claimed is not None
    assert claimed.operation_type == "provider.terminal_delete"
    assert claimed.payload["command_type"] == "terminal_delete"
    assert claimed.payload["desired_generation"] == requested.desired_generation


def _provider_registration(
    *,
    connection_id: str = "provider-connection-1",
) -> RuntimeProviderRegistration:
    return RuntimeProviderRegistration(
        provider_id="provider-1",
        provider_type="kubernetes",
        scope="system",
        workspace_id=None,
        protocol_version="agent-runtime-provider-kubernetes-v2",
        capabilities=RuntimeProtocolCapabilities(("lifecycle",)),
        config_schema_version="v1",
        metadata={},
        capability_contract={"schema_version": 1},
        auth_credential_id="provider:provider-1",
        connection_id=connection_id,
        owner_replica_id="control-a",
    )


def _runner_credential_verifier() -> RuntimeRunnerCredentialVerifier:
    return RuntimeRunnerCredentialVerifier(Fernet.generate_key().decode())


async def _create_workspace(session: AsyncSession, handle: str) -> str:
    repo = WorkspaceRepository()
    result = await repo.create(
        session, WorkspaceCreate(name="Reconciler", handle=handle)
    )
    assert isinstance(result, Success)
    workspace_id = await repo.resolve_id(session, handle)
    assert workspace_id is not None
    return workspace_id


async def _create_agent(
    session: AsyncSession,
    workspace_id: str,
    slug: str,
) -> str:
    integration = RDBLLMProviderIntegration(
        workspace_id=workspace_id,
        provider=LLMProvider.ANTHROPIC,
        name=f"{slug}-integration",
        encrypted_credentials="encrypted-test-value",
        config=None,
    )
    session.add(integration)
    await session.flush()

    agent = RDBAgent(
        workspace_id=workspace_id,
        name="Reconciler test agent",
        model_selection=make_test_model_selection_dict(
            integration_id=integration.id,
            provider=LLMProvider.ANTHROPIC,
            model_identifier=f"{slug}-id",
        ),
        lightweight_model_selection=make_test_model_selection_dict(
            integration_id=integration.id,
            provider=LLMProvider.ANTHROPIC,
            model_identifier=f"{slug}-id",
        ),
    )
    session.add(agent)
    await session.flush()
    return agent.id


async def _bind_runtime_provider(
    session: AsyncSession,
    runtime_id: str,
) -> None:
    """Bind the legacy dispatch fixture at the Runtime ownership layer."""
    await session.execute(
        sa.update(RDBAgentRuntime)
        .where(RDBAgentRuntime.id == runtime_id)
        .values(runtime_provider_id="provider-1")
    )


async def _attach_runtime_configuration(
    session: AsyncSession,
    *,
    runtime_id: str,
    target_desired_generation: int,
) -> RuntimeConfigurationRevision:
    runtime = await session.get(RDBAgentRuntime, runtime_id)
    assert runtime is not None
    provider = await RuntimeProviderRepository().create(
        session,
        RuntimeProviderCreate(
            provider_id="provider-1",
            scope=RuntimeProviderScope.SYSTEM,
            workspace_id=None,
            kind=RuntimeProviderKind.KUBERNETES,
            display_name="Reconciler Test Provider",
            registration_method=RuntimeProviderRegistrationMethod.ADMIN,
            enabled=True,
            lifecycle_state=RuntimeProviderLifecycleState.ACTIVE,
            availability_mode=RuntimeProviderAvailabilityMode.PLATFORM_WIDE,
            capabilities={},
            config_schema=None,
            metadata=None,
        ),
    )
    contract = RDBRuntimeProviderContractRevision(
        provider_id=provider.id,
        digest="c" * 64,
        implementation_version="test",
        protocol_version="agent-runtime-provider-kubernetes-v2",
        contract={
            "schema_version": 1,
            "implementation_key": "kubernetes",
            "implementation_version": "test",
            "protocol_version": "agent-runtime-provider-kubernetes-v2",
            "core_lifecycle_operations": [
                "observe",
                "reset",
                "restart",
                "start",
                "stop",
                "terminal_delete",
            ],
            "optional_capabilities": [],
            "persistence": {
                "kind": "persistent",
                "reset_destroys_workspace": True,
                "terminal_delete_destroys_workspace": True,
            },
            "configuration_fields": [],
            "profile_contracts": [],
        },
        compatibility={},
    )
    session.add(contract)
    await session.flush()

    effective_profile = {
        "profile_kind": "kubernetes_pod",
        "contract_family": "kubernetes.pod-profile",
        "schema_version": 1,
        "runner_resources": {
            "cpu_request_millicores": None,
            "cpu_limit_millicores": None,
            "memory_request_bytes": None,
            "memory_limit_bytes": None,
        },
        "workspace_volume": {
            "storage_class_name": "standard",
            "storage_request_bytes": 1_073_741_824,
        },
        "network_policy": {"allowed_cidrs": [], "denied_cidrs": []},
        "service_account_name": None,
        "scheduling": {"node_selector": {}, "tolerations": []},
        "dind": None,
    }
    profile_repository = RuntimeProfileRepository()
    infrastructure = await profile_repository.create_infrastructure_profile(
        session,
        create=RuntimeInfrastructureProfileCreate(
            provider_id=provider.id,
            profile_kind=RuntimeInfrastructureProfileKind.KUBERNETES_POD,
            display_name="Test Pod Profile",
            description="Reconciler test infrastructure",
            lifecycle=RuntimeProfileLifecycle.ACTIVE,
            contract_family="kubernetes.pod-profile",
            schema_version=1,
            spec=effective_profile,
            required_capabilities=(
                "kubernetes.pod-profile",
                "runtime.resources",
                "workspace.persistent-volume",
                "runtime.network-policy",
            ),
            digest="a" * 64,
            actor_user_id=None,
        ),
    )
    workspace_profile = await profile_repository.create_workspace_runtime_profile(
        session,
        create=WorkspaceRuntimeProfileCreate(
            workspace_id=runtime.workspace_id,
            provider_id=provider.id,
            infrastructure_profile_id=infrastructure.id,
            display_name="Test Runtime Profile",
            description="Reconciler test Workspace Profile",
            lifecycle=RuntimeProfileLifecycle.ACTIVE,
            policy={"schema_version": 1, "network_restriction": None},
            digest="b" * 64,
            actor_workspace_user_id=None,
        ),
    )
    revision = await profile_repository.create_configuration_revision(
        session,
        create=RuntimeConfigurationRevisionCreate(
            runtime_id=runtime_id,
            provider_id=provider.id,
            provider_capability_revision_id=contract.id,
            infrastructure_profile_id=infrastructure.id,
            infrastructure_profile_version=infrastructure.version,
            workspace_runtime_profile_id=workspace_profile.id,
            workspace_runtime_profile_version=workspace_profile.version,
            agent_selection_version=1,
            resolution_status=RuntimeConfigurationResolutionStatus.READY,
            reason_code=None,
            required_capabilities=infrastructure.required_capabilities,
            missing_capabilities=(),
            resolved_configuration={
                "schema_version": 1,
                "provider": {
                    "id": provider.id,
                    "logical_id": provider.provider_id,
                    "kind": provider.kind.value,
                    "capability_revision_id": contract.id,
                    "capability_digest": contract.digest,
                },
                "infrastructure_profile": {
                    "id": infrastructure.id,
                    "version": infrastructure.version,
                    "digest": infrastructure.digest,
                },
                "workspace_runtime_profile": {
                    "id": workspace_profile.id,
                    "version": workspace_profile.version,
                    "digest": workspace_profile.digest,
                },
                "effective_profile": effective_profile,
            },
            source_trace={},
            digest="d" * 64,
            target_desired_generation=target_desired_generation,
        ),
    )
    await session.execute(
        sa.update(RDBAgentRuntime)
        .where(RDBAgentRuntime.id == runtime_id)
        .values(
            runtime_provider_resource_id=provider.id,
            infrastructure_profile_id=infrastructure.id,
            workspace_runtime_profile_id=workspace_profile.id,
            desired_runtime_configuration_revision_id=revision.id,
        )
    )
    return revision
