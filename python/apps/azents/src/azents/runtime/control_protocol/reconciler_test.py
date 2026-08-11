"""Runtime lifecycle reconciler tests."""

import datetime
import logging

import pytest
import sqlalchemy as sa
from azcommon.result import Success
from azents_runtime_control.provider import (
    RuntimeLifecycleCommandType as RuntimeProviderCommandType,
)
from azents_runtime_control.provider import (
    RuntimeProviderObservedState as SharedProviderObservedState,
)
from azents_runtime_control.provider import (
    RuntimeProviderReconciliationEvidence,
    RuntimeProviderReconciliationObservation,
    RuntimeProviderReconciliationStatus,
    RuntimeProviderReport,
)
from azents_runtime_control.runtime_configuration import RuntimeConfigurationEvidence
from cryptography.fernet import Fernet
from sqlalchemy.ext.asyncio import AsyncSession

from azents.core.enums import (
    AgentRuntimeCapability,
    LLMProvider,
    RuntimeDesiredState,
    RuntimeLifecycleCommandType,
    RuntimeProviderAvailabilityMode,
    RuntimeProviderConnectionState,
    RuntimeProviderKind,
    RuntimeProviderLifecycleState,
    RuntimeProviderObservedState,
    RuntimeProviderRegistrationMethod,
    RuntimeProviderScope,
)
from azents.core.runtime_profile import (
    RuntimeConfigurationDocument,
    RuntimeConfigurationStateStatus,
    RuntimeInfrastructureProfileKind,
    RuntimeProfileLifecycle,
)
from azents.core.runtime_runner_credential import RuntimeRunnerCredentialVerifier
from azents.rdb.models.agent import RDBAgent
from azents.rdb.models.agent_runtime import RDBAgentRuntime
from azents.rdb.models.llm_provider_integration import RDBLLMProviderIntegration
from azents.rdb.models.runtime_profile import RDBRuntimeConfigurationState
from azents.rdb.models.runtime_provider_policy import (
    RDBRuntimeProviderContractRevision,
)
from azents.rdb.session import SessionManager
from azents.repos.agent import AgentRepository
from azents.repos.agent_runtime import AgentRuntimeRepository
from azents.repos.agent_runtime.data import AgentRuntime
from azents.repos.runtime_profile.data import (
    RuntimeConfigurationDesiredStateWrite,
    RuntimeConfigurationState,
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


class ReadTrackingAgentRuntimeRepository(AgentRuntimeRepository):
    """Record Runtime reads performed by OBSERVE drift repair."""

    def __init__(self) -> None:
        """Initialize Runtime read tracking."""
        self.read_runtime_ids: list[str] = []

    async def get_by_id(
        self,
        session: AsyncSession,
        runtime_id: str,
    ) -> AgentRuntime | None:
        """Record one lock-free Runtime read."""
        self.read_runtime_ids.append(runtime_id)
        return await super().get_by_id(session, runtime_id)

    async def get_by_id_for_update(
        self,
        session: AsyncSession,
        runtime_id: str,
    ) -> AgentRuntime | None:
        """Record one locked Runtime authority recheck."""
        self.read_runtime_ids.append(runtime_id)
        return await super().get_by_id_for_update(session, runtime_id)


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
        agent_repository=AgentRepository(),
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
        agent_repository=AgentRepository(),
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

    async with rdb_session_manager() as session:
        await session.execute(
            sa.update(RDBAgent)
            .where(RDBAgent.id == agent_id)
            .values(
                runtime_capability=AgentRuntimeCapability.REMOVING,
                runtime_capability_version=RDBAgent.runtime_capability_version + 1,
                runtime_profile_id=None,
                runtime_profile_selection_version=(
                    RDBAgent.runtime_profile_selection_version + 1
                ),
                shell_enabled=False,
            )
        )
        await session.execute(
            sa.update(RDBAgentRuntime)
            .where(RDBAgentRuntime.id == runtime.id)
            .values(
                provider_observed_at=old_observe_at,
                provider_observe_requested_at=old_observe_at,
            )
        )

    blocked_dispatch = await reconciler.reconcile_once(limit=10)
    blocked_request = await control_protocol.claim_next_provider_request(
        provider_id="provider-1",
        generation=accepted.generation,
        consumer_id="provider-worker",
        block_ms=0,
    )

    assert blocked_dispatch == 0
    assert blocked_request is None


async def test_reconciler_repairs_current_network_policy_drift_once(
    rdb_session_manager: SessionManager[AsyncSession],
    caplog: pytest.LogCaptureFixture,
) -> None:
    """One current OBSERVE result dispatches one in-place configuration repair."""
    runtime_repository = ReadTrackingAgentRuntimeRepository()
    profile_repository = RuntimeProfileRepository()
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
        state = await _attach_runtime_configuration(
            session,
            runtime_id=runtime.id,
            target_desired_generation=command.desired_generation,
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
        agent_repository=AgentRepository(),
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

    with caplog.at_level(
        logging.INFO,
        logger="azents.runtime.control_protocol.reconciler",
    ):
        dispatched = await reconciler.reconcile_observe_completion(
            _network_policy_drift_report(
                runtime_id=runtime.id,
                desired_generation=command.desired_generation,
                configuration_sequence=state.desired.sequence,
            )
        )
    claimed = await control_protocol.claim_next_provider_request(
        provider_id="provider-1",
        generation=accepted.generation,
        consumer_id="provider-worker",
        block_ms=0,
    )
    no_retry = await reconciler.reconcile_once(limit=10)

    assert dispatched is True
    assert claimed is not None
    assert claimed.payload["command_type"] == "update_configuration"
    assert no_retry == 0
    assert runtime_repository.read_runtime_ids == [runtime.id, runtime.id]
    handoff_log = next(
        record
        for record in caplog.records
        if record.message == "Runtime NetworkPolicy drift repair handed off"
    )
    dispatch_log = next(
        record
        for record in caplog.records
        if record.message == "Runtime lifecycle command dispatched"
        and record.__dict__["command_type"] == "update_configuration"
    )
    for record in (handoff_log, dispatch_log):
        assert record.__dict__["runtime_id"] == runtime.id
        assert record.__dict__["provider_id"] == "provider-1"
        assert record.__dict__["provider_generation"] == accepted.generation
        assert record.__dict__["desired_generation"] == command.desired_generation
        assert record.__dict__["configuration_sequence"] == state.desired.sequence
        assert record.__dict__["reconciliation_kind"] == "network_policy"
        assert record.__dict__["reconciliation_reason"] == "network_policy_mismatch"


async def test_reconcile_observe_completion_rejects_stale_provider_generation(
    rdb_session_manager: SessionManager[AsyncSession],
) -> None:
    """A reconnect requires a later current OBSERVE before it can repair drift."""
    runtime_repository = AgentRuntimeRepository()
    profile_repository = RuntimeProfileRepository()
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
        state = await _attach_runtime_configuration(
            session,
            runtime_id=runtime.id,
            target_desired_generation=command.desired_generation,
        )
        observed = await runtime_repository.record_provider_observed_state(
            session,
            runtime.id,
            RuntimeProviderObservedState.RUNNING,
            2,
            command.desired_generation,
        )
        assert observed is not None

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
        agent_repository=AgentRepository(),
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

    dispatched = await reconciler.reconcile_observe_completion(
        _network_policy_drift_report(
            runtime_id=runtime.id,
            provider_generation=previous.generation,
            desired_generation=command.desired_generation,
            configuration_sequence=state.desired.sequence,
        )
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


async def test_drift_repair_rechecks_runtime_snapshot_before_dispatch(
    rdb_session_manager: SessionManager[AsyncSession],
) -> None:
    """A desired-state race cannot dispatch an old drift-repair configuration."""
    runtime_repository = AgentRuntimeRepository()
    profile_repository = RuntimeProfileRepository()
    async with rdb_session_manager() as session:
        workspace_id = await _create_workspace(session, "reconciler-drift-race-ws")
        agent_id = await _create_agent(
            session,
            workspace_id,
            "reconciler-drift-race-agent",
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
        state = await _attach_runtime_configuration(
            session,
            runtime_id=runtime.id,
            target_desired_generation=command.desired_generation,
        )
        observed = await runtime_repository.record_provider_observed_state(
            session,
            runtime.id,
            RuntimeProviderObservedState.RUNNING,
            1,
            command.desired_generation,
        )
        assert observed is not None
        stale_runtime = await runtime_repository.get_by_id(session, runtime.id)
        assert stale_runtime is not None
        replacement = await runtime_repository.set_desired_state(
            session,
            runtime.id,
            RuntimeLifecycleCommandType.RESTART,
            RuntimeDesiredState.RUNNING,
        )
        assert replacement is not None

    store = InMemoryRuntimeCoordinationStore()
    control_protocol = RuntimeControlProtocolService(store)
    accepted = await control_protocol.register_provider(
        _provider_registration(),
        registered_at=datetime.datetime.now(datetime.UTC),
    )
    reconciler = RuntimeLifecycleReconciler(
        agent_repository=AgentRepository(),
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

    dispatched = await reconciler._dispatch_runtime_command(
        stale_runtime,
        command_type=RuntimeProviderCommandType.UPDATE_CONFIGURATION,
        claim_lifecycle=False,
        required_provider_generation=accepted.generation,
        required_observed_generation=command.desired_generation,
        required_configuration_sequence=state.desired.sequence,
    )
    claimed = await control_protocol.claim_next_provider_request(
        provider_id="provider-1",
        generation=accepted.generation,
        consumer_id="provider-worker",
        block_ms=0,
    )

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
        initial_state = await _attach_runtime_configuration(
            session,
            runtime_id=runtime.id,
            target_desired_generation=initial.desired_generation,
        )
        restart = await runtime_repository.set_desired_state_if_configuration_current(
            session,
            runtime.id,
            RuntimeLifecycleCommandType.RESTART,
            RuntimeDesiredState.RUNNING,
            expected_configuration_sequence=initial_state.desired.sequence,
            expected_digest=initial_state.desired.digest or "",
            expected_generation=initial.desired_generation,
        )
        assert restart is not None
        await session.execute(
            sa.update(RDBRuntimeConfigurationState)
            .where(RDBRuntimeConfigurationState.runtime_id == runtime.id)
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
        agent_repository=AgentRepository(),
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
    """STOP reuses usable state without rewriting the bounded desired slot."""
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
        source_state = await _attach_runtime_configuration(
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
        agent_repository=AgentRepository(),
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
        repaired_state = await profile_repository.get_configuration_state(
            session,
            runtime_id=runtime.id,
        )

    assert dispatched == 1
    assert claimed is not None
    assert claimed.operation_type == "provider.stop"
    assert claimed.payload["desired_generation"] == stop.desired_generation
    runtime_configuration = claimed.payload["runtime_configuration"]
    assert isinstance(runtime_configuration, dict)
    assert runtime_configuration["desired_generation"] == stop.desired_generation
    assert (
        runtime_configuration["configuration_sequence"] == source_state.desired.sequence
    )
    assert repaired_state is not None
    assert repaired_state.desired.sequence == source_state.desired.sequence
    assert repaired_state.desired.digest == source_state.desired.digest
    assert (
        repaired_state.desired.target_generation
        == source_state.desired.target_generation
    )


async def test_reconciler_rejects_mismatched_resolved_provider_reference(
    rdb_session_manager: SessionManager[AsyncSession],
) -> None:
    """Dispatch validates resolved references against the current state document."""
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
        state = await _attach_runtime_configuration(
            session,
            runtime_id=runtime.id,
            target_desired_generation=command.desired_generation,
        )
        assert state.desired.document is not None
        configuration = dict(state.desired.document.resolved_configuration or {})
        provider_reference = configuration["provider"]
        assert isinstance(provider_reference, dict)
        configuration["provider"] = {
            **provider_reference,
            "id": "mismatched-provider-resource",
        }
        document = state.desired.document.model_copy(
            update={"resolved_configuration": configuration}
        )
        await session.execute(
            sa.update(RDBRuntimeConfigurationState)
            .where(RDBRuntimeConfigurationState.runtime_id == runtime.id)
            .values(desired_document=document.model_dump(mode="json"))
        )
        current = await runtime_repository.get_by_id(session, runtime.id)
        assert current is not None

    store = InMemoryRuntimeCoordinationStore()
    reconciler = RuntimeLifecycleReconciler(
        agent_repository=AgentRepository(),
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
        await reconciler._runtime_configuration(current, locked_session=None)


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
        agent_repository=AgentRepository(),
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
        await session.execute(
            sa.update(RDBAgent)
            .where(RDBAgent.id == agent_id)
            .values(
                runtime_capability=AgentRuntimeCapability.REMOVING,
                runtime_capability_version=RDBAgent.runtime_capability_version + 1,
                runtime_profile_id=None,
                runtime_profile_selection_version=(
                    RDBAgent.runtime_profile_selection_version + 1
                ),
                shell_enabled=False,
            )
        )

    store = InMemoryRuntimeCoordinationStore()
    request_ids = iter(("terminal-request-1", "terminal-request-2"))
    control_protocol = RuntimeControlProtocolService(
        store,
        request_id_factory=lambda: next(request_ids),
    )
    accepted = await control_protocol.register_provider(
        _provider_registration(),
        registered_at=datetime.datetime.now(datetime.UTC),
    )
    reconciler = RuntimeLifecycleReconciler(
        agent_repository=AgentRepository(),
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
            lifecycle_retry_delay=datetime.timedelta(0),
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
        disconnected = await runtime_repository.record_provider_connection_state(
            session,
            runtime.id,
            RuntimeProviderConnectionState.DISCONNECTED,
        )
        assert disconnected is not None
    reconnected = await control_protocol.register_provider(
        _provider_registration(connection_id="provider-connection-2"),
        registered_at=datetime.datetime.now(datetime.UTC),
    )
    redispatched = await reconciler.reconcile_once(limit=10)
    reclaimed = await control_protocol.claim_next_provider_request(
        provider_id="provider-1",
        generation=reconnected.generation,
        consumer_id="provider-worker-2",
        block_ms=0,
    )

    assert dispatched == 1
    assert claimed is not None
    assert claimed.operation_type == "provider.terminal_delete"
    assert claimed.payload["command_type"] == "terminal_delete"
    assert claimed.payload["desired_generation"] == requested.desired_generation
    assert reconnected.generation > accepted.generation
    assert redispatched == 1
    assert reclaimed is not None
    assert reclaimed.operation_type == "provider.terminal_delete"
    assert reclaimed.payload["desired_generation"] == requested.desired_generation
    assert reclaimed.generation == reconnected.generation


def _network_policy_drift_report(
    *,
    runtime_id: str,
    desired_generation: int,
    configuration_sequence: int,
    provider_generation: int = 1,
) -> RuntimeProviderReport:
    """Build one current typed NetworkPolicy drift observation."""
    return RuntimeProviderReport(
        runtime_id=runtime_id,
        provider_id="provider-1",
        provider_generation=provider_generation,
        observed_state=SharedProviderObservedState.RUNNING,
        observed_desired_generation=desired_generation,
        provider_runtime_id="provider-runtime-1",
        reason="network_policy_observed",
        diagnostic={},
        reported_at=datetime.datetime.now(datetime.UTC),
        terminal_delete_acknowledged=False,
        runtime_configuration=RuntimeConfigurationEvidence(
            configuration_sequence=configuration_sequence,
            digest="d" * 64,
            desired_generation=desired_generation,
        ),
        reconciliation=RuntimeProviderReconciliationEvidence(
            observations=(
                RuntimeProviderReconciliationObservation(
                    kind="network_policy",
                    status=RuntimeProviderReconciliationStatus.DRIFTED,
                    reason="network_policy_mismatch",
                    diagnostic={},
                ),
            )
        ),
    )


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
) -> RuntimeConfigurationState:
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
    document = RuntimeConfigurationDocument(
        schema_version=1,
        source_trace={},
        provider_id=provider.id,
        provider_capability_revision_id=contract.id,
        infrastructure_profile_id=infrastructure.id,
        infrastructure_profile_version=infrastructure.version,
        workspace_runtime_profile_id=workspace_profile.id,
        workspace_runtime_profile_version=workspace_profile.version,
        agent_selection_version=1,
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
    )
    await session.execute(
        sa.update(RDBAgentRuntime)
        .where(RDBAgentRuntime.id == runtime_id)
        .values(
            runtime_provider_resource_id=provider.id,
        )
    )
    state = await profile_repository.overwrite_desired_configuration_state(
        session,
        write=RuntimeConfigurationDesiredStateWrite(
            runtime_id=runtime_id,
            status=RuntimeConfigurationStateStatus.READY,
            target_generation=target_desired_generation,
            digest="d" * 64,
            document=document,
            reason_code=None,
        ),
    )
    assert state is not None
    evidence = RuntimeConfigurationEvidence(
        configuration_sequence=state.desired.sequence,
        digest=state.desired.digest or "",
        desired_generation=target_desired_generation,
    )
    acknowledged_at = datetime.datetime.now(datetime.UTC)
    state = await profile_repository.record_provider_configuration_evidence(
        session,
        runtime_id=runtime_id,
        provider_id=provider.id,
        evidence=evidence,
        acknowledged_at=acknowledged_at,
    )
    assert state is not None
    state = await profile_repository.record_runner_configuration_evidence(
        session,
        runtime_id=runtime_id,
        provider_id=provider.id,
        evidence=evidence,
        observed_at=acknowledged_at,
    )
    assert state is not None
    return state
