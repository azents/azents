"""Runtime lifecycle Terminal invalidation tests."""

import datetime
from collections.abc import AsyncGenerator, Callable
from contextlib import asynccontextmanager
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import AsyncMock

from azcommon.result import Success
from sqlalchemy.ext.asyncio import AsyncSession

from azents.core.enums import (
    RuntimeDesiredState,
    RuntimeLifecycleCommandType,
    RuntimeProviderConnectionState,
    RuntimeProviderObservedState,
    RuntimeRunnerState,
    WorkspaceUserRole,
)
from azents.core.runtime_profile import RuntimeConfigurationStateStatus
from azents.repos.agent_runtime.data import (
    AgentRuntime,
    AgentRuntimeLifecycleCommand,
)
from azents.repos.runtime_profile.data import RuntimeConfigurationSlot
from azents.services.agent_runtime.lifecycle_data import (
    AgentRuntimeConfigurationStatus,
    AgentRuntimeLifecyclePresentation,
)
from azents.services.runtime_profile_resolution.data import (
    RuntimeProfileResolutionResult,
)

from .service import AgentRuntimeService

_NOW = datetime.datetime(2026, 9, 1, 12, 0, tzinfo=datetime.UTC)


async def test_reset_invalidates_terminal_after_lifecycle_commit() -> None:
    """RESET publishes Runtime invalidation only after its transaction commits."""
    service = object.__new__(AgentRuntimeService)
    before = _runtime(desired_generation=2)
    after = _runtime(
        desired_generation=3,
        provider_observed_state=RuntimeProviderObservedState.RESETTING,
    )
    before_resolution = _resolution(before)
    after_resolution = _resolution(after)
    service._authorize_agent = AsyncMock(return_value=None)
    service._ensure_runtime_for_agent = AsyncMock(
        side_effect=(before_resolution, after_resolution)
    )
    service._configuration_status = AsyncMock(
        return_value=AgentRuntimeConfigurationStatus.model_construct(
            status="applied",
            desired=after_resolution.desired,
            applied=None,
        )
    )
    service.calculate_lifecycle = cast(
        Any,
        lambda runtime, *, configuration, removing: (
            AgentRuntimeLifecyclePresentation.model_construct(
                target=runtime.desired_state,
                convergence="resetting",
                provider=SimpleNamespace(
                    connection=runtime.provider_connection_state,
                    resource=runtime.provider_observed_state,
                ),
                runner=SimpleNamespace(state=runtime.runner_state),
                availability="transitioning",
                reason_code="runtime_resetting",
                desired_generation=runtime.desired_generation,
            )
        ),
    )
    committed_transactions = 0

    @asynccontextmanager
    async def session_manager() -> AsyncGenerator[AsyncSession, None]:
        nonlocal committed_transactions
        yield cast(AsyncSession, object())
        committed_transactions += 1

    command = AgentRuntimeLifecycleCommand(
        runtime=after,
        command_type=RuntimeLifecycleCommandType.RESET,
        desired_generation=3,
    )
    set_desired_state = AsyncMock(return_value=command)
    service.session_manager = cast(Any, session_manager)
    service.runtime_repository = cast(
        Any,
        SimpleNamespace(
            set_desired_state_if_configuration_current=set_desired_state,
        ),
    )
    service.terminal_invalidation_publisher = cast(
        Any,
        _CommittedPublisher(lambda: committed_transactions),
    )

    result = await service.reset(
        "agent-1",
        final_desired_state=RuntimeDesiredState.RUNNING,
        workspace_id="workspace-1",
        workspace_user_id="workspace-user-1",
        role=WorkspaceUserRole.OWNER,
    )

    assert isinstance(result, Success)
    assert service.terminal_invalidation_publisher.runtime_ids == ["runtime-1"]


class _CommittedPublisher:
    """Record invalidation only after the lifecycle transaction exits."""

    def __init__(self, committed_transactions: Callable[[], int]) -> None:
        self.committed_transactions = committed_transactions
        self.runtime_ids: list[str] = []

    async def publish_runtime_terminal_invalidation(self, runtime_id: str) -> None:
        assert self.committed_transactions() == 1
        self.runtime_ids.append(runtime_id)


def _runtime(
    *,
    desired_generation: int,
    provider_observed_state: RuntimeProviderObservedState = (
        RuntimeProviderObservedState.RUNNING
    ),
) -> AgentRuntime:
    return AgentRuntime.model_construct(
        id="runtime-1",
        workspace_id="workspace-1",
        agent_id="agent-1",
        runtime_provider_id="provider-1",
        desired_state=RuntimeDesiredState.RUNNING,
        desired_generation=desired_generation,
        provider_connection_state=RuntimeProviderConnectionState.CONNECTED,
        provider_observed_state=provider_observed_state,
        provider_observed_generation=desired_generation,
        runner_state=RuntimeRunnerState.READY,
        runner_generation=1,
        terminal_delete_requested_generation=None,
        failure_generation=None,
    )


def _resolution(runtime: AgentRuntime) -> RuntimeProfileResolutionResult:
    return RuntimeProfileResolutionResult(
        runtime=runtime,
        desired=RuntimeConfigurationSlot(
            sequence=1,
            status=RuntimeConfigurationStateStatus.READY,
            target_generation=runtime.desired_generation,
            digest="d" * 64,
            document=None,
            reason_code=None,
            provider_reported_digest=None,
            runner_reported_digest=None,
            provider_acknowledged_at=None,
            runner_observed_at=None,
        ),
        applied=None,
        runtime_created=False,
    )
