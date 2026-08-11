"""AgentRuntimeService lifecycle summary tests."""

from datetime import UTC, datetime

from azents.core.enums import (
    RuntimeDesiredState,
    RuntimeProviderConnectionState,
    RuntimeProviderObservedState,
    RuntimeRunnerState,
    RuntimeSummary,
)
from azents.core.runtime_profile import (
    RuntimeConfigurationDocument,
    RuntimeConfigurationResolutionStatus,
    RuntimeConfigurationStateStatus,
)
from azents.repos.agent_runtime.data import AgentRuntime
from azents.repos.runtime_profile.data import RuntimeConfigurationSlot
from azents.services.agent_runtime.service import AgentRuntimeService
from azents.services.runtime_profile_resolution.data import (
    RuntimeProfileResolutionResult,
)


def _runtime(
    *,
    desired_state: RuntimeDesiredState = RuntimeDesiredState.STOPPED,
    desired_generation: int = 0,
    provider_observed_state: RuntimeProviderObservedState = (
        RuntimeProviderObservedState.UNKNOWN
    ),
    provider_connection_state: RuntimeProviderConnectionState = (
        RuntimeProviderConnectionState.DISCONNECTED
    ),
    runner_state: RuntimeRunnerState = RuntimeRunnerState.UNKNOWN,
    terminal_delete_requested_generation: int | None = None,
    failure_generation: int | None = None,
    failure_code: str | None = None,
    failure_message: str | None = None,
) -> AgentRuntime:
    """Create Runtime domain model for tests."""
    now = datetime.now(UTC)
    return AgentRuntime(
        id="runtime-id",
        workspace_id="workspace-id",
        agent_id="agent-id",
        runtime_provider_id=None,
        desired_state=desired_state,
        desired_generation=desired_generation,
        last_lifecycle_command=None,
        reset_final_desired_state=None,
        terminal_delete_requested_generation=terminal_delete_requested_generation,
        terminal_delete_acknowledged_generation=None,
        terminal_delete_acknowledged_at=None,
        terminal_delete_acknowledgement_kind=None,
        provider_observed_state=provider_observed_state,
        provider_observed_generation=0,
        provider_connection_state=provider_connection_state,
        runner_state=runner_state,
        runner_generation=0,
        workspace_path=None,
        failure_generation=failure_generation,
        failure_code=failure_code,
        failure_message=failure_message,
        last_state_change_at=None,
        created_at=now,
        updated_at=now,
    )


def _resolution(
    *,
    status: RuntimeConfigurationResolutionStatus,
    reason_code: str | None,
) -> RuntimeProfileResolutionResult:
    """Create one Runtime Profile resolution for lifecycle guard tests."""
    runtime = _runtime()
    document = None
    digest = None
    state_status = RuntimeConfigurationStateStatus.BLOCKED
    if reason_code is None:
        document = RuntimeConfigurationDocument(
            schema_version=1,
            source_trace={},
            provider_id="provider-resource-id",
            provider_capability_revision_id="capability-revision-id",
            infrastructure_profile_id="infrastructure-profile-id",
            infrastructure_profile_version=1,
            workspace_runtime_profile_id="workspace-profile-id",
            workspace_runtime_profile_version=1,
            agent_selection_version=1,
            required_capabilities=(),
            missing_capabilities=(),
            resolved_configuration={},
        )
        digest = "a" * 64
        state_status = RuntimeConfigurationStateStatus.READY
    desired = RuntimeConfigurationSlot(
        sequence=runtime.configuration_sequence,
        status=state_status,
        target_generation=runtime.desired_generation,
        digest=digest,
        document=document,
        reason_code=reason_code,
        provider_reported_digest=None,
        runner_reported_digest=None,
        provider_acknowledged_at=None,
        runner_observed_at=None,
    )
    return RuntimeProfileResolutionResult(
        runtime=runtime,
        desired=desired,
        applied=None,
        runtime_created=False,
    )


class TestAgentRuntimeLifecycleSummary:
    """Agent Runtime lifecycle summary calculation tests."""

    def setup_method(self) -> None:
        """Create service under test."""
        self.service = object.__new__(AgentRuntimeService)

    def test_stopped_default_summary(self) -> None:
        """Default state returns stopped summary."""
        state = self.service.calculate_state(_runtime())

        assert state.summary == RuntimeSummary.STOPPED
        assert state.actions.start is True
        assert state.actions.use_runner is False

    def test_provider_disconnected_when_desired_running(self) -> None:
        """start desired state while Provider is disconnected is blocked summary."""
        state = self.service.calculate_state(
            _runtime(desired_state=RuntimeDesiredState.RUNNING)
        )

        assert state.summary == RuntimeSummary.PROVIDER_DISCONNECTED
        assert state.actions.reset is False

    def test_connected_stopped_provider_with_running_desired_is_starting(self) -> None:
        """Provider observed stopped after start request is starting summary."""
        state = self.service.calculate_state(
            _runtime(
                desired_state=RuntimeDesiredState.RUNNING,
                provider_observed_state=RuntimeProviderObservedState.STOPPED,
                provider_connection_state=RuntimeProviderConnectionState.CONNECTED,
            )
        )

        assert state.summary == RuntimeSummary.STARTING
        assert state.actions.use_runner is False

    def test_running_with_ready_runner(self) -> None:
        """Provider running + Runner ready is running/use_runner state."""
        state = self.service.calculate_state(
            _runtime(
                desired_state=RuntimeDesiredState.RUNNING,
                provider_observed_state=RuntimeProviderObservedState.RUNNING,
                provider_connection_state=RuntimeProviderConnectionState.CONNECTED,
                runner_state=RuntimeRunnerState.READY,
            )
        )

        assert state.summary == RuntimeSummary.RUNNING
        assert state.actions.use_runner is True

    def test_running_backend_with_unavailable_runner(self) -> None:
        """Backend running without Runner is runner_unavailable."""
        state = self.service.calculate_state(
            _runtime(
                desired_state=RuntimeDesiredState.RUNNING,
                provider_observed_state=RuntimeProviderObservedState.RUNNING,
                provider_connection_state=RuntimeProviderConnectionState.CONNECTED,
                runner_state=RuntimeRunnerState.DISCONNECTED,
            )
        )

        assert state.summary == RuntimeSummary.RUNNER_UNAVAILABLE
        assert state.actions.stop is True
        assert state.actions.restart is True
        assert state.actions.reset is True
        assert state.actions.use_runner is False

    def test_current_generation_failure_wins(self) -> None:
        """Current generation failure is reflected as failed summary."""
        state = self.service.calculate_state(
            _runtime(
                desired_state=RuntimeDesiredState.RUNNING,
                desired_generation=2,
                failure_generation=2,
                failure_code="start_failed",
                failure_message="Start failed",
            )
        )

        assert state.summary == RuntimeSummary.FAILED
        assert state.failure is not None
        assert state.failure.code == "start_failed"

    def test_old_generation_failure_is_ignored(self) -> None:
        """Previous generation failure is not reflected in summary."""
        state = self.service.calculate_state(
            _runtime(
                desired_state=RuntimeDesiredState.RUNNING,
                desired_generation=2,
                provider_connection_state=RuntimeProviderConnectionState.CONNECTED,
                failure_generation=1,
                failure_code="old_failed",
                failure_message="Old failure",
            )
        )

        assert state.summary == RuntimeSummary.STARTING
        assert state.failure is None

    def test_terminal_deletion_disables_all_runtime_actions(self) -> None:
        """Terminal deletion does not expose lifecycle actions."""
        state = self.service.calculate_state(
            _runtime(terminal_delete_requested_generation=3)
        )

        assert state.actions.start is False
        assert state.actions.stop is False
        assert state.actions.restart is False
        assert state.actions.reset is False
        assert state.actions.use_runner is False

    def test_blocked_configuration_rejects_creation_commands(self) -> None:
        """A blocked desired revision cannot create a new Runtime incarnation."""
        error = self.service.configuration_blocking_error(
            _resolution(
                status=RuntimeConfigurationResolutionStatus.BLOCKED,
                reason_code="provider_disabled",
            )
        )

        assert error is not None
        assert error.code == "provider_disabled"

    def test_ready_configuration_allows_creation_commands(self) -> None:
        """A ready desired revision passes the lifecycle configuration guard."""
        error = self.service.configuration_blocking_error(
            _resolution(
                status=RuntimeConfigurationResolutionStatus.READY,
                reason_code=None,
            )
        )

        assert error is None
