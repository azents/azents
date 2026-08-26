"""AgentRuntimeService lifecycle summary tests."""

from datetime import UTC, datetime

import pytest

from azents.core.enums import (
    RuntimeDesiredState,
    RuntimeProviderConnectionState,
    RuntimeProviderObservedState,
    RuntimeRunnerState,
)
from azents.core.runtime_profile import (
    RuntimeConfigurationDocument,
    RuntimeConfigurationResolutionStatus,
    RuntimeConfigurationStateStatus,
)
from azents.repos.agent_runtime.data import AgentRuntime
from azents.repos.runtime_profile.data import (
    RuntimeConfigurationAppliedSlot,
    RuntimeConfigurationSlot,
)
from azents.services.agent_runtime.lifecycle_data import (
    AgentRuntimeConfigurationStatus,
)
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


def _resolution_with_previous_applied(
    runtime: AgentRuntime,
) -> RuntimeProfileResolutionResult:
    """Create a ready desired slot that differs from a previous applied slot."""
    resolution = _resolution(
        status=RuntimeConfigurationResolutionStatus.READY,
        reason_code=None,
    )
    desired = resolution.desired
    assert desired.digest is not None
    assert desired.document is not None
    return RuntimeProfileResolutionResult(
        runtime=runtime,
        desired=desired,
        applied=RuntimeConfigurationAppliedSlot(
            sequence=desired.sequence + 1,
            target_generation=desired.target_generation,
            digest=desired.digest,
            document=desired.document,
            applied_at=datetime.now(UTC),
        ),
        runtime_created=True,
    )


class TestAgentRuntimeLifecyclePresentation:
    """Agent Runtime lifecycle presentation calculation tests."""

    def setup_method(self) -> None:
        """Create service under test."""
        self.service = object.__new__(AgentRuntimeService)

    def test_stopped_default_presentation(self) -> None:
        """Default state returns stable stopped availability."""
        runtime = _runtime(
            provider_connection_state=RuntimeProviderConnectionState.CONNECTED
        )
        lifecycle = self.service.calculate_lifecycle(
            runtime,
            configuration=None,
            removing=False,
        )
        actions = self.service._calculate_actions(runtime)

        assert lifecycle.convergence == "stable"
        assert lifecycle.availability == "stopped"
        assert lifecycle.target is RuntimeDesiredState.STOPPED
        assert actions.start is True
        assert actions.use_runner is False

    def test_stopped_runtime_without_provider_authority_has_no_host_actions(
        self,
    ) -> None:
        """Disconnected Provider state cannot authorize host management."""
        actions = self.service._calculate_actions(_runtime())

        assert actions.start is False
        assert actions.stop is False
        assert actions.restart is False
        assert actions.reset is False

    def test_stopped_target_ignores_configuration_recreation_wait(self) -> None:
        """A stopped Runtime adopts its desired configuration on the next start."""
        runtime = _runtime(
            desired_generation=3,
            provider_observed_state=RuntimeProviderObservedState.STOPPED,
            provider_connection_state=RuntimeProviderConnectionState.CONNECTED,
            runner_state=RuntimeRunnerState.DISCONNECTED,
        )
        configuration = AgentRuntimeConfigurationStatus(
            status="waiting_for_recreation",
            desired=None,
            applied=None,
        )

        lifecycle = self.service.calculate_lifecycle(
            runtime,
            configuration=configuration,
            removing=False,
        )

        assert lifecycle.convergence == "stable"
        assert lifecycle.availability == "stopped"
        assert lifecycle.reason_code is None

    def test_stopping_target_ignores_configuration_recreation_wait(self) -> None:
        """A cleanup-only Stop reports transition instead of configuration blocking."""
        runtime = _runtime(
            desired_state=RuntimeDesiredState.STOPPED,
            desired_generation=3,
            provider_observed_state=RuntimeProviderObservedState.RUNNING,
            provider_connection_state=RuntimeProviderConnectionState.CONNECTED,
            runner_state=RuntimeRunnerState.READY,
        )
        configuration = AgentRuntimeConfigurationStatus(
            status="waiting_for_recreation",
            desired=None,
            applied=None,
        )

        lifecycle = self.service.calculate_lifecycle(
            runtime,
            configuration=configuration,
            removing=False,
        )

        assert lifecycle.convergence == "stopping"
        assert lifecycle.availability == "transitioning"
        assert lifecycle.reason_code == "runtime_stopping"
        actions = self.service._calculate_actions(runtime)
        assert actions.start is False
        assert actions.stop is False
        assert actions.restart is False

    def test_provider_disconnected_when_desired_running(self) -> None:
        """Running target while Provider is disconnected is blocked."""
        runtime = _runtime(desired_state=RuntimeDesiredState.RUNNING)
        lifecycle = self.service.calculate_lifecycle(
            runtime,
            configuration=None,
            removing=False,
        )

        assert lifecycle.convergence == "blocked"
        assert lifecycle.availability == "provider_disconnected"
        assert lifecycle.reason_code == "provider_disconnected"
        assert self.service._calculate_actions(runtime).reset is False

    def test_connected_stopped_provider_with_running_desired_is_starting(self) -> None:
        """Provider stopped after a start request is transitioning."""
        runtime = _runtime(
            desired_state=RuntimeDesiredState.RUNNING,
            provider_observed_state=RuntimeProviderObservedState.STOPPED,
            provider_connection_state=RuntimeProviderConnectionState.CONNECTED,
        )
        lifecycle = self.service.calculate_lifecycle(
            runtime,
            configuration=None,
            removing=False,
        )

        assert lifecycle.convergence == "starting"
        assert lifecycle.availability == "transitioning"
        actions = self.service._calculate_actions(runtime)
        assert actions.stop is True
        assert actions.restart is False
        assert actions.use_runner is False

    def test_running_with_ready_runner(self) -> None:
        """Provider running plus Runner ready is available."""
        runtime = _runtime(
            desired_state=RuntimeDesiredState.RUNNING,
            provider_observed_state=RuntimeProviderObservedState.RUNNING,
            provider_connection_state=RuntimeProviderConnectionState.CONNECTED,
            runner_state=RuntimeRunnerState.READY,
        )
        lifecycle = self.service.calculate_lifecycle(
            runtime,
            configuration=None,
            removing=False,
        )

        assert lifecycle.convergence == "stable"
        assert lifecycle.availability == "ready"
        assert lifecycle.provider.connection is RuntimeProviderConnectionState.CONNECTED
        assert lifecycle.provider.resource is RuntimeProviderObservedState.RUNNING
        assert lifecycle.runner.state is RuntimeRunnerState.READY
        assert self.service._calculate_actions(runtime).use_runner is True

    def test_running_backend_with_unavailable_runner(self) -> None:
        """Backend running without Runner is runner_unavailable."""
        runtime = _runtime(
            desired_state=RuntimeDesiredState.RUNNING,
            provider_observed_state=RuntimeProviderObservedState.RUNNING,
            provider_connection_state=RuntimeProviderConnectionState.CONNECTED,
            runner_state=RuntimeRunnerState.DISCONNECTED,
        )
        lifecycle = self.service.calculate_lifecycle(
            runtime,
            configuration=None,
            removing=False,
        )
        actions = self.service._calculate_actions(runtime)

        assert lifecycle.convergence == "stable"
        assert lifecycle.availability == "runner_unavailable"
        assert lifecycle.reason_code == "runner_disconnected"
        assert actions.stop is True
        assert actions.restart is True
        assert actions.reset is True
        assert actions.use_runner is False

    def test_current_generation_failure_wins(self) -> None:
        """Current-generation failure wins presentation precedence."""
        lifecycle = self.service.calculate_lifecycle(
            _runtime(
                desired_state=RuntimeDesiredState.RUNNING,
                desired_generation=2,
                failure_generation=2,
                failure_code="start_failed",
                failure_message="Start failed",
            ),
            configuration=None,
            removing=False,
        )

        assert lifecycle.convergence == "failed"
        assert lifecycle.availability == "failed"
        assert lifecycle.reason_code == "runtime_failed"

    def test_old_generation_failure_is_ignored(self) -> None:
        """Previous-generation failure does not replace current presentation."""
        lifecycle = self.service.calculate_lifecycle(
            _runtime(
                desired_state=RuntimeDesiredState.RUNNING,
                desired_generation=2,
                provider_connection_state=RuntimeProviderConnectionState.CONNECTED,
                failure_generation=1,
                failure_code="old_failed",
                failure_message="Old failure",
            ),
            configuration=None,
            removing=False,
        )

        assert lifecycle.convergence == "starting"
        assert lifecycle.availability == "transitioning"

    def test_terminal_deletion_disables_all_runtime_actions(self) -> None:
        """Terminal deletion does not expose lifecycle actions."""
        runtime = _runtime(terminal_delete_requested_generation=3)
        lifecycle = self.service.calculate_lifecycle(
            runtime,
            configuration=None,
            removing=False,
        )
        actions = self.service._calculate_actions(runtime)

        assert lifecycle.availability == "removing"
        assert actions.start is False
        assert actions.stop is False
        assert actions.restart is False
        assert actions.reset is False
        assert actions.use_runner is False

    def test_active_removal_disables_shared_lifecycle_actions(self) -> None:
        """An active removal suppresses Workspace and Runtime lifecycle actions."""
        runtime = _runtime(
            desired_state=RuntimeDesiredState.RUNNING,
            provider_observed_state=RuntimeProviderObservedState.RUNNING,
            provider_connection_state=RuntimeProviderConnectionState.CONNECTED,
            runner_state=RuntimeRunnerState.READY,
        )

        actions = self.service._calculate_lifecycle_actions(
            runtime,
            configuration=None,
            removing=True,
        )

        assert actions.start is False
        assert actions.stop is False
        assert actions.restart is False
        assert actions.reset is False
        assert actions.use_runner is False

    def test_blocked_configuration_disables_creation_actions(self) -> None:
        """Blocked configuration suppresses actions that can create resources."""
        resolution = _resolution(
            status=RuntimeConfigurationResolutionStatus.BLOCKED,
            reason_code="provider_disabled",
        )
        runtime = _runtime(
            provider_connection_state=RuntimeProviderConnectionState.CONNECTED
        )
        configuration = AgentRuntimeConfigurationStatus(
            status="configuration_blocked",
            desired=resolution.desired,
            applied=None,
        )

        actions = self.service._calculate_lifecycle_actions(
            runtime,
            configuration=configuration,
            removing=False,
        )

        assert actions.start is False
        assert actions.restart is False
        assert actions.reset is False

    def test_ready_runner_remains_available_while_configuration_update_waits(
        self,
    ) -> None:
        """A connected Runner remains usable while a new configuration waits."""
        runtime = _runtime(
            desired_state=RuntimeDesiredState.RUNNING,
            provider_observed_state=RuntimeProviderObservedState.RUNNING,
            provider_connection_state=RuntimeProviderConnectionState.CONNECTED,
            runner_state=RuntimeRunnerState.READY,
        )
        configuration = AgentRuntimeConfigurationStatus(
            status="waiting_for_recreation",
            desired=None,
            applied=None,
        )

        lifecycle = self.service.calculate_lifecycle(
            runtime,
            configuration=configuration,
            removing=False,
        )

        assert lifecycle.convergence == "stable"
        assert lifecycle.availability == "ready"
        assert lifecycle.reason_code is None

    @pytest.mark.asyncio
    async def test_stopped_runtime_applies_selected_configuration_on_next_start(
        self,
    ) -> None:
        """A stopped resource is not blocked by its previously applied revision."""
        runtime = _runtime(
            desired_state=RuntimeDesiredState.STOPPED,
            provider_observed_state=RuntimeProviderObservedState.UNKNOWN,
            provider_connection_state=RuntimeProviderConnectionState.CONNECTED,
            runner_state=RuntimeRunnerState.DISCONNECTED,
        )
        resolution = _resolution_with_previous_applied(runtime)

        configuration = await self.service._configuration_status(resolution)
        actions = self.service._calculate_lifecycle_actions(
            runtime,
            configuration=configuration,
            removing=False,
        )

        assert configuration.status == "configured_not_created"
        assert actions.start is True

    @pytest.mark.asyncio
    async def test_ready_runner_keeps_configuration_difference_visible(
        self,
    ) -> None:
        """A usable Runtime reports selected and applied revisions separately."""
        runtime = _runtime(
            desired_state=RuntimeDesiredState.RUNNING,
            provider_observed_state=RuntimeProviderObservedState.UNKNOWN,
            provider_connection_state=RuntimeProviderConnectionState.DISCONNECTED,
            runner_state=RuntimeRunnerState.READY,
        )
        resolution = _resolution_with_previous_applied(runtime)

        configuration = await self.service._configuration_status(resolution)
        lifecycle = self.service.calculate_lifecycle(
            runtime,
            configuration=configuration,
            removing=False,
        )

        assert configuration.status == "waiting_for_recreation"
        assert lifecycle.availability == "ready"

    def test_ready_runner_remains_available_when_provider_disconnects(self) -> None:
        """Provider control loss does not hide a connected Runtime."""
        runtime = _runtime(
            desired_state=RuntimeDesiredState.RUNNING,
            provider_observed_state=RuntimeProviderObservedState.UNKNOWN,
            provider_connection_state=RuntimeProviderConnectionState.DISCONNECTED,
            runner_state=RuntimeRunnerState.READY,
        )

        lifecycle = self.service.calculate_lifecycle(
            runtime,
            configuration=None,
            removing=False,
        )
        actions = self.service._calculate_actions(runtime)

        assert lifecycle.availability == "ready"
        assert actions.start is False
        assert actions.stop is False
        assert actions.restart is False
        assert actions.reset is False
        assert actions.use_runner is True

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
