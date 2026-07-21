"""AgentRuntimeService lifecycle summary tests."""

from datetime import UTC, datetime

from azents.core.enums import (
    RuntimeDesiredState,
    RuntimeProviderConnectionState,
    RuntimeProviderObservedState,
    RuntimeRunnerState,
    RuntimeSummary,
)
from azents.repos.agent_runtime.data import AgentRuntime
from azents.services.agent_runtime.service import AgentRuntimeService


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
        provider_config=None,
        desired_state=desired_state,
        desired_generation=desired_generation,
        last_lifecycle_command=None,
        reset_final_desired_state=None,
        terminal_delete_requested_generation=terminal_delete_requested_generation,
        terminal_delete_acknowledged_generation=None,
        terminal_delete_acknowledged_at=None,
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
