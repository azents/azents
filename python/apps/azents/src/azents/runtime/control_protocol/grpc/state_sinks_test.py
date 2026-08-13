"""Durable Agent Runtime gRPC state sink tests."""

from datetime import UTC, datetime
from typing import cast
from unittest.mock import AsyncMock, Mock

import pytest
import sqlalchemy as sa
from azcommon.result import Success
from azents_runtime_control.provider import (
    RuntimeProviderObservedState as SharedProviderState,
)
from azents_runtime_control.provider import RuntimeProviderReport
from azents_runtime_control.runner import RunnerStateReport
from azents_runtime_control.runner import RuntimeRunnerState as SharedRunnerState
from azents_runtime_control.runtime_configuration import RuntimeConfigurationEvidence
from sqlalchemy.ext.asyncio import AsyncSession

from azents.core.enums import (
    LLMProvider,
    RuntimeDesiredState,
    RuntimeLifecycleCommandType,
    RuntimeProviderAvailabilityMode,
    RuntimeProviderKind,
    RuntimeProviderLifecycleState,
    RuntimeProviderObservedState,
    RuntimeProviderRegistrationMethod,
    RuntimeProviderScope,
    RuntimeRunnerState,
)
from azents.rdb.models.agent import RDBAgent
from azents.rdb.models.agent_runtime import RDBAgentRuntime
from azents.rdb.models.llm_provider_integration import RDBLLMProviderIntegration
from azents.rdb.session import SessionManager
from azents.repos.agent_runtime import AgentRuntimeRepository
from azents.repos.agent_runtime.data import AgentRuntimeFailurePatch
from azents.repos.runtime_profile.repository import RuntimeProfileRepository
from azents.repos.runtime_provider.data import RuntimeProviderCreate
from azents.repos.runtime_provider.repository import RuntimeProviderRepository
from azents.repos.workspace import WorkspaceRepository
from azents.repos.workspace.data import WorkspaceCreate
from azents.runtime.control_protocol.grpc.state_sinks import (
    RuntimeProviderReportRepositorySink,
    RuntimeRunnerStateRepositorySink,
)
from azents.testing.model_selection import make_test_model_selection_dict


async def test_runner_heartbeat_configuration_waits_for_provider_ack(
    rdb_session_manager: SessionManager[AsyncSession],
) -> None:
    runtime_repository = Mock(spec=AgentRuntimeRepository)
    cast(AsyncMock, runtime_repository.get_by_id).return_value = Mock(
        id="runtime-1",
        runtime_provider_resource_id="provider-1",
    )
    profile_repository = Mock(spec=RuntimeProfileRepository)
    cast(
        AsyncMock,
        profile_repository.get_configuration_state,
    ).return_value = Mock(
        desired=Mock(
            sequence=2,
            digest="e" * 64,
            target_generation=5,
            provider_acknowledged_at=None,
            provider_reported_digest=None,
            runner_reported_digest=None,
        ),
        applied=Mock(sequence=1),
    )
    cast(
        AsyncMock,
        profile_repository.configuration_evidence_matches_current,
    ).return_value = True
    sink = RuntimeRunnerStateRepositorySink(
        cast(AgentRuntimeRepository, runtime_repository),
        cast(RuntimeProfileRepository, profile_repository),
        rdb_session_manager,
    )

    evidence = await sink.configuration_evidence_for_runner_heartbeat(
        runtime_id="runtime-1"
    )

    assert evidence is None


async def test_runner_heartbeat_configuration_stops_after_runner_report(
    rdb_session_manager: SessionManager[AsyncSession],
) -> None:
    runtime_repository = Mock(spec=AgentRuntimeRepository)
    cast(AsyncMock, runtime_repository.get_by_id).return_value = Mock(
        id="runtime-1",
        runtime_provider_resource_id="provider-1",
    )
    state = Mock(
        desired=Mock(
            sequence=2,
            digest="e" * 64,
            target_generation=5,
            provider_acknowledged_at=datetime(2026, 7, 31, tzinfo=UTC),
            provider_reported_digest="e" * 64,
            runner_reported_digest=None,
        ),
        applied=Mock(sequence=1),
    )
    profile_repository = Mock(spec=RuntimeProfileRepository)
    cast(
        AsyncMock,
        profile_repository.get_configuration_state,
    ).return_value = state
    cast(
        AsyncMock,
        profile_repository.configuration_evidence_matches_current,
    ).return_value = True
    sink = RuntimeRunnerStateRepositorySink(
        cast(AgentRuntimeRepository, runtime_repository),
        cast(RuntimeProfileRepository, profile_repository),
        rdb_session_manager,
    )

    evidence = await sink.configuration_evidence_for_runner_heartbeat(
        runtime_id="runtime-1"
    )
    state.desired.runner_reported_digest = "e" * 64
    acknowledged = await sink.configuration_evidence_for_runner_heartbeat(
        runtime_id="runtime-1"
    )

    assert evidence == RuntimeConfigurationEvidence(
        configuration_sequence=2,
        digest="e" * 64,
        desired_generation=5,
    )
    assert acknowledged is None


async def test_runner_heartbeat_configuration_rejects_stale_current_target(
    rdb_session_manager: SessionManager[AsyncSession],
) -> None:
    """Evidence read before a target race is fenced by the current pointer."""
    runtime_repository = Mock(spec=AgentRuntimeRepository)
    cast(AsyncMock, runtime_repository.get_by_id).return_value = Mock(
        id="runtime-1",
        runtime_provider_resource_id="provider-1",
    )
    profile_repository = Mock(spec=RuntimeProfileRepository)
    cast(
        AsyncMock,
        profile_repository.get_configuration_state,
    ).return_value = Mock(
        desired=Mock(
            sequence=2,
            digest="e" * 64,
            target_generation=5,
            provider_acknowledged_at=datetime(2026, 7, 31, tzinfo=UTC),
            provider_reported_digest="e" * 64,
            runner_reported_digest=None,
        ),
        applied=Mock(sequence=1),
    )
    current_match = cast(
        AsyncMock,
        profile_repository.configuration_evidence_matches_current,
    )
    current_match.return_value = False
    sink = RuntimeRunnerStateRepositorySink(
        cast(AgentRuntimeRepository, runtime_repository),
        cast(RuntimeProfileRepository, profile_repository),
        rdb_session_manager,
    )

    evidence = await sink.configuration_evidence_for_runner_heartbeat(
        runtime_id="runtime-1"
    )

    assert evidence is None
    current_match.assert_awaited_once()


async def test_runner_heartbeat_configuration_skips_already_applied_target(
    rdb_session_manager: SessionManager[AsyncSession],
) -> None:
    """No heartbeat evidence is emitted after the applied pointer catches up."""
    runtime_repository = Mock(spec=AgentRuntimeRepository)
    cast(AsyncMock, runtime_repository.get_by_id).return_value = Mock(
        id="runtime-1",
        runtime_provider_resource_id="provider-1",
    )
    profile_repository = Mock(spec=RuntimeProfileRepository)
    cast(
        AsyncMock,
        profile_repository.get_configuration_state,
    ).return_value = Mock(
        desired=Mock(sequence=2, digest="e" * 64),
        applied=Mock(sequence=2),
    )
    sink = RuntimeRunnerStateRepositorySink(
        cast(AgentRuntimeRepository, runtime_repository),
        cast(RuntimeProfileRepository, profile_repository),
        rdb_session_manager,
    )

    evidence = await sink.configuration_evidence_for_runner_heartbeat(
        runtime_id="runtime-1"
    )

    assert evidence is None
    cast(
        AsyncMock,
        profile_repository.configuration_evidence_matches_current,
    ).assert_not_awaited()


async def test_provider_running_report_clears_start_timeout_failure(
    rdb_session_manager: SessionManager[AsyncSession],
) -> None:
    """Late provider RUNNING report recovers a Control start timeout."""
    repo = AgentRuntimeRepository()
    async with rdb_session_manager() as session:
        runtime_id = await _create_runtime(session, "provider-sink-late-running")
        command = await repo.set_desired_state(
            session,
            runtime_id,
            RuntimeLifecycleCommandType.START,
            RuntimeDesiredState.RUNNING,
        )
        assert command is not None
        await repo.record_runtime_failure(
            session,
            runtime_id,
            AgentRuntimeFailurePatch(
                generation=command.desired_generation,
                code="START_TIMEOUT",
                message="Runtime start timed out",
            ),
        )
    sink = RuntimeProviderReportRepositorySink(
        repo,
        _profile_repository(),
        rdb_session_manager,
    )

    await sink.record_provider_report(
        RuntimeProviderReport(
            runtime_id=runtime_id,
            provider_id="system-kubernetes",
            provider_generation=1,
            observed_state=SharedProviderState.RUNNING,
            observed_desired_generation=command.desired_generation,
            provider_runtime_id="pod-runtime",
            reason="ready",
            diagnostic={},
            reported_at=datetime(2026, 5, 25, tzinfo=UTC),
            terminal_delete_acknowledged=False,
            runtime_configuration=_runtime_configuration_evidence(
                command.desired_generation
            ),
            reconciliation=None,
        ),
        configuration_acknowledgement_allowed=True,
    )

    async with rdb_session_manager() as session:
        runtime = await repo.get_by_id(session, runtime_id)
    assert runtime is not None
    assert runtime.provider_observed_state == RuntimeProviderObservedState.RUNNING
    assert runtime.failure_generation is None
    assert runtime.failure_code is None
    assert runtime.failure_message is None


async def test_provider_starting_report_does_not_acknowledge_configuration(
    rdb_session_manager: SessionManager[AsyncSession],
) -> None:
    """Only a ready Provider report can unlock Runner evidence delivery."""
    runtime_repository = Mock(spec=AgentRuntimeRepository)
    runtime = Mock(
        id="runtime-1",
        runtime_provider_resource_id="provider-1",
        desired_generation=3,
    )
    cast(AsyncMock, runtime_repository.get_by_id).return_value = runtime
    cast(
        AsyncMock,
        runtime_repository.provider_report_matches_binding,
    ).return_value = True
    cast(
        AsyncMock,
        runtime_repository.record_provider_observed_state,
    ).return_value = runtime
    cast(
        AsyncMock,
        runtime_repository.record_provider_connection_state,
    ).return_value = runtime
    profile_repository = _profile_repository()
    sink = RuntimeProviderReportRepositorySink(
        cast(AgentRuntimeRepository, runtime_repository),
        profile_repository,
        rdb_session_manager,
    )

    await sink.record_provider_report(
        RuntimeProviderReport(
            runtime_id="runtime-1",
            provider_id="system-kubernetes",
            provider_generation=1,
            observed_state=SharedProviderState.STARTING,
            observed_desired_generation=3,
            provider_runtime_id="pod-runtime",
            reason="pod_starting",
            diagnostic={},
            reported_at=datetime(2026, 7, 31, tzinfo=UTC),
            terminal_delete_acknowledged=False,
            runtime_configuration=_runtime_configuration_evidence(3),
            reconciliation=None,
        ),
        configuration_acknowledgement_allowed=True,
    )

    cast(
        AsyncMock,
        profile_repository.record_provider_configuration_evidence,
    ).assert_not_awaited()


async def test_provider_running_report_without_enforcement_ack_skips_configuration(
    rdb_session_manager: SessionManager[AsyncSession],
) -> None:
    """Lifecycle-only or drifted v3 reports cannot acknowledge configuration."""
    runtime_repository = Mock(spec=AgentRuntimeRepository)
    runtime = Mock(
        id="runtime-1",
        runtime_provider_resource_id="provider-1",
        desired_generation=3,
        failure_code=None,
    )
    cast(AsyncMock, runtime_repository.get_by_id).return_value = runtime
    cast(
        AsyncMock,
        runtime_repository.provider_report_matches_binding,
    ).return_value = True
    cast(
        AsyncMock,
        runtime_repository.record_provider_observed_state,
    ).return_value = runtime
    cast(
        AsyncMock,
        runtime_repository.record_provider_connection_state,
    ).return_value = runtime
    profile_repository = _profile_repository()
    sink = RuntimeProviderReportRepositorySink(
        cast(AgentRuntimeRepository, runtime_repository),
        profile_repository,
        rdb_session_manager,
    )

    await sink.record_provider_report(
        RuntimeProviderReport(
            runtime_id="runtime-1",
            provider_id="system-kubernetes",
            provider_generation=1,
            observed_state=SharedProviderState.RUNNING,
            observed_desired_generation=3,
            provider_runtime_id="pod-runtime",
            reason="network_enforcement_mismatch",
            diagnostic={},
            reported_at=datetime(2026, 8, 12, tzinfo=UTC),
            terminal_delete_acknowledged=False,
            runtime_configuration=_runtime_configuration_evidence(3),
            reconciliation=None,
        ),
        configuration_acknowledgement_allowed=False,
    )

    cast(
        AsyncMock,
        profile_repository.record_provider_configuration_evidence,
    ).assert_not_awaited()
    cast(
        AsyncMock,
        runtime_repository.record_provider_observed_state,
    ).assert_awaited_once()


async def test_provider_report_ignores_finalized_runtime(
    rdb_session_manager: SessionManager[AsyncSession],
) -> None:
    """A late orphan report cannot interrupt the shared Provider stream."""
    repo = AgentRuntimeRepository()
    profile_repository = _profile_repository()
    sink = RuntimeProviderReportRepositorySink(
        repo,
        profile_repository,
        rdb_session_manager,
    )

    await sink.record_provider_report(
        RuntimeProviderReport(
            runtime_id="0198a534-12f0-7da1-8ee5-7f4bc60854c4",
            provider_id="system-kubernetes",
            provider_generation=1,
            observed_state=SharedProviderState.RUNNING,
            observed_desired_generation=0,
            provider_runtime_id="orphan-provider-runtime",
            reason="late_observation",
            diagnostic={},
            reported_at=datetime(2026, 7, 30, tzinfo=UTC),
            terminal_delete_acknowledged=False,
            runtime_configuration=_runtime_configuration_evidence(),
            reconciliation=None,
        ),
        configuration_acknowledgement_allowed=True,
    )

    transport_match = cast(
        AsyncMock,
        profile_repository.configuration_evidence_matches_current,
    )
    transport_match.assert_not_awaited()


async def test_provider_report_rejects_bound_runtime_provider_mismatch(
    rdb_session_manager: SessionManager[AsyncSession],
) -> None:
    """A bound Runtime accepts reports only from its selected Provider."""
    repo = AgentRuntimeRepository()
    async with rdb_session_manager() as session:
        runtime_id = await _create_runtime(session, "provider-sink-binding-mismatch")
        await session.execute(
            sa.update(RDBAgentRuntime)
            .where(RDBAgentRuntime.id == runtime_id)
            .values(runtime_provider_id="provider-bound")
        )
    sink = RuntimeProviderReportRepositorySink(
        repo,
        _profile_repository(),
        rdb_session_manager,
    )

    with pytest.raises(ValueError, match="immutable Runtime Provider binding"):
        await sink.record_provider_report(
            RuntimeProviderReport(
                runtime_id=runtime_id,
                provider_id="provider-other",
                provider_generation=1,
                observed_state=SharedProviderState.RUNNING,
                observed_desired_generation=0,
                provider_runtime_id="provider-runtime",
                reason="mismatch",
                diagnostic={},
                reported_at=datetime.now(UTC),
                terminal_delete_acknowledged=False,
                runtime_configuration=_runtime_configuration_evidence(),
                reconciliation=None,
            ),
            configuration_acknowledgement_allowed=True,
        )


async def test_provider_terminal_delete_acknowledgement_clears_runtime_path(
    rdb_session_manager: SessionManager[AsyncSession],
) -> None:
    """A terminal Provider acknowledgement becomes the finalization precondition."""
    repo = AgentRuntimeRepository()
    async with rdb_session_manager() as session:
        runtime_id = await _create_runtime(session, "provider-sink-terminal-delete")
        requested = await repo.request_terminal_delete(session, runtime_id)
        assert requested is not None
    sink = RuntimeProviderReportRepositorySink(
        repo,
        _profile_repository(),
        rdb_session_manager,
    )

    await sink.record_provider_report(
        RuntimeProviderReport(
            runtime_id=runtime_id,
            provider_id="system-kubernetes",
            provider_generation=1,
            observed_state=SharedProviderState.STOPPED,
            observed_desired_generation=requested.desired_generation,
            provider_runtime_id=None,
            reason="terminal_resources_absent",
            diagnostic={},
            reported_at=datetime(2026, 7, 21, tzinfo=UTC),
            terminal_delete_acknowledged=True,
            runtime_configuration=_runtime_configuration_evidence(),
            reconciliation=None,
        ),
        configuration_acknowledgement_allowed=True,
    )

    async with rdb_session_manager() as session:
        runtime = await repo.get_terminal_delete_acknowledged(session, runtime_id)
    assert runtime is not None
    assert runtime.workspace_path is None
    assert (
        runtime.terminal_delete_acknowledged_generation == requested.desired_generation
    )
    assert runtime.terminal_delete_acknowledged_at is not None


async def test_runner_state_sink_persists_runner_workspace_path(
    rdb_session_manager: SessionManager[AsyncSession],
) -> None:
    """Runner report owns the persisted Agent Workspace path."""
    repo = AgentRuntimeRepository()
    async with rdb_session_manager() as session:
        runtime_id = await _create_runtime(session, "runner-sink-workspace")
    sink = RuntimeRunnerStateRepositorySink(
        repo,
        _profile_repository(),
        rdb_session_manager,
    )

    await sink.record_runner_state(_report(runtime_id, "/runtime/home"))

    async with rdb_session_manager() as session:
        runtime = await repo.get_by_id(session, runtime_id)
    assert runtime is not None
    assert runtime.runner_state == RuntimeRunnerState.READY
    assert runtime.workspace_path == "/runtime/home"
    assert runtime.failure_code is None


async def test_runner_state_sink_rejects_missing_workspace_path(
    rdb_session_manager: SessionManager[AsyncSession],
) -> None:
    """Runner readiness requires Agent Workspace path evidence."""
    repo = AgentRuntimeRepository()
    async with rdb_session_manager() as session:
        runtime_id = await _create_runtime(session, "runner-sink-missing-workspace")
    sink = RuntimeRunnerStateRepositorySink(
        repo,
        _profile_repository(),
        rdb_session_manager,
    )

    await sink.record_runner_state(_report(runtime_id, ""))

    async with rdb_session_manager() as session:
        runtime = await repo.get_by_id(session, runtime_id)
    assert runtime is not None
    assert runtime.runner_state == RuntimeRunnerState.FAILED
    assert runtime.workspace_path is None
    assert runtime.failure_code == "RUNNER_WORKSPACE_PATH_MISSING"


async def test_runner_state_sink_normalizes_workspace_path(
    rdb_session_manager: SessionManager[AsyncSession],
) -> None:
    """Runner workspace evidence is normalized before persistence."""
    repo = AgentRuntimeRepository()
    async with rdb_session_manager() as session:
        runtime_id = await _create_runtime(session, "runner-sink-normalized-workspace")
    sink = RuntimeRunnerStateRepositorySink(
        repo,
        _profile_repository(),
        rdb_session_manager,
    )

    await sink.record_runner_state(_report(runtime_id, "/runtime/home/../agent"))

    async with rdb_session_manager() as session:
        runtime = await repo.get_by_id(session, runtime_id)
    assert runtime is not None
    assert runtime.runner_state == RuntimeRunnerState.READY
    assert runtime.workspace_path == "/runtime/agent"
    assert runtime.failure_code is None


async def test_runner_state_sink_rejects_relative_workspace_path(
    rdb_session_manager: SessionManager[AsyncSession],
) -> None:
    """Runner workspace evidence must be absolute."""
    repo = AgentRuntimeRepository()
    async with rdb_session_manager() as session:
        runtime_id = await _create_runtime(session, "runner-sink-relative-workspace")
    profile_repository = _profile_repository()
    cast(
        AsyncMock,
        profile_repository.record_runner_configuration_evidence,
    ).return_value = None
    sink = RuntimeRunnerStateRepositorySink(
        repo,
        profile_repository,
        rdb_session_manager,
    )

    await sink.record_runner_state(_report(runtime_id, "runtime/home"))

    async with rdb_session_manager() as session:
        runtime = await repo.get_by_id(session, runtime_id)
    assert runtime is not None
    assert runtime.runner_state == RuntimeRunnerState.FAILED
    assert runtime.workspace_path is None
    assert runtime.failure_code == "RUNNER_WORKSPACE_PATH_INVALID"


async def test_runner_state_sink_treats_busy_runner_as_ready(
    rdb_session_manager: SessionManager[AsyncSession],
) -> None:
    """An active Runner operation keeps the Runtime available."""
    repo = AgentRuntimeRepository()
    async with rdb_session_manager() as session:
        runtime_id = await _create_runtime(session, "runner-sink-busy")
        await repo.record_provider_observed_state(
            session,
            runtime_id,
            RuntimeProviderObservedState.RUNNING,
            1,
            3,
        )
    sink = RuntimeRunnerStateRepositorySink(
        repo,
        _profile_repository(),
        rdb_session_manager,
    )

    await sink.record_runner_state(
        _report(runtime_id, "/workspace/provider", state=SharedRunnerState.BUSY)
    )

    async with rdb_session_manager() as session:
        runtime = await repo.get_by_id(session, runtime_id)
    assert runtime is not None
    assert runtime.runner_state == RuntimeRunnerState.READY
    assert runtime.failure_code is None


async def test_runner_state_sink_records_runner_stream_closed_as_disconnected(
    rdb_session_manager: SessionManager[AsyncSession],
) -> None:
    """Runner stream close makes route unavailability visible in durable state."""
    repo = AgentRuntimeRepository()
    async with rdb_session_manager() as session:
        runtime_id = await _create_runtime(session, "runner-sink-disconnected")
        await repo.record_provider_observed_state(
            session,
            runtime_id,
            RuntimeProviderObservedState.RUNNING,
            1,
            3,
        )
    sink = RuntimeRunnerStateRepositorySink(
        repo,
        _profile_repository(),
        rdb_session_manager,
    )

    await sink.record_runner_state(
        _report(
            runtime_id,
            "/workspace/provider",
            state=SharedRunnerState.UNKNOWN,
            diagnostic={"reason": "runner_stream_closed"},
        )
    )

    async with rdb_session_manager() as session:
        runtime = await repo.get_by_id(session, runtime_id)
    assert runtime is not None
    assert runtime.runner_state == RuntimeRunnerState.DISCONNECTED
    assert runtime.failure_code is None


async def test_runner_state_sink_ignores_stale_report_with_lower_generation(
    rdb_session_manager: SessionManager[AsyncSession],
) -> None:
    """Stale Runner reports do not overwrite newer durable generations."""
    repo = AgentRuntimeRepository()
    async with rdb_session_manager() as session:
        runtime_id = await _create_runtime(session, "runner-sink-lower-generation")
        await repo.record_provider_observed_state(
            session,
            runtime_id,
            RuntimeProviderObservedState.RUNNING,
            1,
            3,
        )
        await repo.record_runner_state(
            session,
            runtime_id,
            RuntimeRunnerState.READY,
            2,
            expected_desired_generation=0,
            workspace_path="/runtime/home",
        )
    sink = RuntimeRunnerStateRepositorySink(
        repo,
        _profile_repository(),
        rdb_session_manager,
    )

    await sink.record_runner_state(
        _report(
            runtime_id,
            "/workspace/provider",
            state=SharedRunnerState.UNKNOWN,
            runner_generation=1,
            diagnostic={"reason": "runner_stream_closed"},
        )
    )

    async with rdb_session_manager() as session:
        runtime = await repo.get_by_id(session, runtime_id)
    assert runtime is not None
    assert runtime.runner_state == RuntimeRunnerState.READY
    assert runtime.runner_generation == 2


async def test_runner_state_sink_ignores_previous_desired_generation(
    rdb_session_manager: SessionManager[AsyncSession],
) -> None:
    """A replaced Runner cannot fail the next desired Runtime generation."""
    repo = AgentRuntimeRepository()
    async with rdb_session_manager() as session:
        runtime_id = await _create_runtime(session, "runner-sink-stale-desired")
        command = await repo.set_desired_state(
            session,
            runtime_id,
            RuntimeLifecycleCommandType.RESTART,
            RuntimeDesiredState.RUNNING,
        )
        assert command is not None
        await repo.record_provider_observed_state(
            session,
            runtime_id,
            RuntimeProviderObservedState.STARTING,
            1,
            command.desired_generation,
        )
    profile_repository = _profile_repository()
    sink = RuntimeRunnerStateRepositorySink(
        repo,
        profile_repository,
        rdb_session_manager,
    )

    await sink.record_runner_state(
        _report(
            runtime_id,
            "/workspace/provider",
            state=SharedRunnerState.FAILED,
            runner_generation=99,
            policy_desired_generation=command.desired_generation - 1,
        )
    )

    async with rdb_session_manager() as session:
        runtime = await repo.get_by_id(session, runtime_id)
    assert runtime is not None
    assert runtime.runner_state == RuntimeRunnerState.UNKNOWN
    assert runtime.runner_generation == 0
    assert runtime.failure_generation is None
    assert runtime.failure_code is None


async def test_runner_state_sink_fences_generation_changed_during_validation(
    rdb_session_manager: SessionManager[AsyncSession],
) -> None:
    """A report cannot mutate state after its desired generation is replaced."""
    repo = AgentRuntimeRepository()
    async with rdb_session_manager() as session:
        runtime_id = await _create_runtime(session, "runner-sink-raced-desired")
        await repo.record_provider_observed_state(
            session,
            runtime_id,
            RuntimeProviderObservedState.RUNNING,
            1,
            0,
        )
    profile_repository = _profile_repository()

    async def replace_generation(
        session: AsyncSession,
        **_: object,
    ) -> bool:
        command = await repo.set_desired_state(
            session,
            runtime_id,
            RuntimeLifecycleCommandType.RESTART,
            RuntimeDesiredState.RUNNING,
        )
        assert command is not None
        return False

    evidence_record = cast(
        AsyncMock,
        profile_repository.record_runner_configuration_evidence,
    )
    evidence_record.side_effect = replace_generation
    sink = RuntimeRunnerStateRepositorySink(
        repo,
        profile_repository,
        rdb_session_manager,
    )

    await sink.record_runner_state(
        _report(
            runtime_id,
            "/workspace/provider",
            state=SharedRunnerState.FAILED,
            runner_generation=99,
            policy_desired_generation=0,
        )
    )

    async with rdb_session_manager() as session:
        runtime = await repo.get_by_id(session, runtime_id)
    assert runtime is not None
    assert runtime.desired_generation == 1
    assert runtime.runner_state == RuntimeRunnerState.UNKNOWN
    assert runtime.runner_generation == 0
    assert runtime.failure_generation is None
    assert runtime.failure_code is None


async def _create_runtime(session: AsyncSession, slug: str) -> str:
    workspace_repo = WorkspaceRepository()
    result = await workspace_repo.create(
        session,
        WorkspaceCreate(name=f"{slug} workspace", handle=f"{slug}-ws"),
    )
    assert isinstance(result, Success)
    workspace_id = await workspace_repo.resolve_id(session, f"{slug}-ws")
    assert workspace_id is not None

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
        name=f"{slug} agent",
        model_selection=make_test_model_selection_dict(
            integration_id=integration.id,
            provider=LLMProvider.ANTHROPIC,
            model_identifier=f"{slug}-model-id",
        ),
        lightweight_model_selection=make_test_model_selection_dict(
            integration_id=integration.id,
            provider=LLMProvider.ANTHROPIC,
            model_identifier=f"{slug}-model-id",
        ),
    )
    session.add(agent)
    await session.flush()

    provider = await RuntimeProviderRepository().create(
        session,
        RuntimeProviderCreate(
            provider_id="system-kubernetes",
            scope=RuntimeProviderScope.SYSTEM,
            workspace_id=None,
            kind=RuntimeProviderKind.KUBERNETES,
            display_name="State Sink Test Provider",
            registration_method=RuntimeProviderRegistrationMethod.ADMIN,
            enabled=True,
            lifecycle_state=RuntimeProviderLifecycleState.ACTIVE,
            availability_mode=RuntimeProviderAvailabilityMode.PLATFORM_WIDE,
            capabilities={},
            config_schema=None,
            metadata=None,
        ),
    )
    runtime = await AgentRuntimeRepository().ensure_for_agent(session, agent.id)
    await session.execute(
        sa.update(RDBAgentRuntime)
        .where(RDBAgentRuntime.id == runtime.id)
        .values(runtime_provider_resource_id=provider.id)
    )
    return runtime.id


def _report(
    runtime_id: str,
    workspace_path: str,
    *,
    state: SharedRunnerState = SharedRunnerState.READY,
    runner_generation: int = 1,
    diagnostic: dict[str, str] | None = None,
    policy_desired_generation: int = 0,
) -> RunnerStateReport:
    return RunnerStateReport(
        runtime_id=runtime_id,
        runner_id="runner-1",
        runner_generation=runner_generation,
        runner_state=state,
        capabilities=("bash", "file.read"),
        active_operation_ids=(),
        health="ok",
        diagnostic=diagnostic or {},
        workspace_path=workspace_path,
        reported_at=datetime(2026, 5, 25, tzinfo=UTC),
        runtime_configuration=_runtime_configuration_evidence(
            policy_desired_generation
        ),
    )


def _profile_repository() -> RuntimeProfileRepository:
    repository = Mock(spec=RuntimeProfileRepository)
    repository.record_provider_configuration_evidence = AsyncMock(return_value=Mock())
    repository.record_runner_configuration_evidence = AsyncMock(return_value=Mock())
    repository.configuration_evidence_matches_current = AsyncMock(return_value=True)
    return cast(RuntimeProfileRepository, repository)


def _runtime_configuration_evidence(
    desired_generation: int = 0,
) -> RuntimeConfigurationEvidence:
    return RuntimeConfigurationEvidence(
        configuration_sequence=1,
        digest="d" * 64,
        desired_generation=desired_generation,
    )
