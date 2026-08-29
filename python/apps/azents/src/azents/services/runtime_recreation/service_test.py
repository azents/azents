"""Runtime recreation orchestration and evidence tests."""

import dataclasses
import datetime
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from unittest.mock import ANY, AsyncMock, MagicMock

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from azents.core.enums import (
    AgentRuntimeCapability,
    RuntimeDesiredState,
    RuntimeProviderConnectionState,
    RuntimeProviderObservedState,
    RuntimeRunnerState,
)
from azents.core.runtime_profile import (
    RuntimeConfigurationDocument,
    RuntimeConfigurationStateStatus,
    RuntimeRecreationItemStatus,
    RuntimeRecreationOperationStatus,
    RuntimeRecreationTargetKind,
)
from azents.repos.agent import AgentRepository
from azents.repos.agent.data import Agent
from azents.repos.agent_runtime import AgentRuntimeRepository
from azents.repos.agent_runtime.data import AgentRuntime
from azents.repos.runtime_profile.data import (
    RuntimeConfigurationAppliedSlot,
    RuntimeConfigurationSlot,
    RuntimeConfigurationState,
    RuntimeRecreationOperation,
    RuntimeRecreationOperationItem,
)
from azents.repos.runtime_profile.repository import RuntimeProfileRepository
from azents.repos.runtime_provider.repository import RuntimeProviderRepository

from .service import (
    RuntimeRecreationReconciler,
    RuntimeRecreationService,
    RuntimeRecreationUnavailable,
)


class _SessionManager:
    """Yield one mock database session per reconciliation boundary."""

    def __init__(self) -> None:
        self.session = AsyncMock(spec=AsyncSession)

    @asynccontextmanager
    async def __call__(self) -> AsyncIterator[AsyncSession]:
        yield self.session


def _operation() -> RuntimeRecreationOperation:
    now = datetime.datetime(2026, 7, 31, tzinfo=datetime.UTC)
    return RuntimeRecreationOperation(
        id="operation-1",
        target_kind=RuntimeRecreationTargetKind.WORKSPACE_RUNTIME_PROFILE,
        target_id="profile-1",
        target_version="2",
        status=RuntimeRecreationOperationStatus.RUNNING,
        concurrency_limit=1,
        actor_user_id=None,
        actor_workspace_user_id="workspace-user-1",
        total_count=1,
        pending_count=0,
        running_count=1,
        succeeded_count=0,
        skipped_count=0,
        failed_count=0,
        created_at=now,
        started_at=now,
        completed_at=None,
    )


def _item(
    *,
    expected_sequence: int = 1,
    expected_digest: str = "a" * 64,
    expected_generation: int = 0,
    dispatched_generation: int | None = None,
    attempt: int = 1,
) -> RuntimeRecreationOperationItem:
    now = datetime.datetime(2026, 7, 31, tzinfo=datetime.UTC)
    return RuntimeRecreationOperationItem(
        id="item-1",
        operation_id="operation-1",
        runtime_id="runtime-1",
        expected_configuration_sequence=expected_sequence,
        expected_configuration_digest=expected_digest,
        expected_desired_generation=expected_generation,
        status=RuntimeRecreationItemStatus.RUNNING,
        attempt=attempt,
        dispatched_generation=dispatched_generation,
        failure_code=None,
        failure_message=None,
        created_at=now,
        updated_at=now,
    )


def _runtime(
    *,
    configuration_sequence: int = 1,
    desired_generation: int = 0,
    provider_observed_state: RuntimeProviderObservedState = (
        RuntimeProviderObservedState.RUNNING
    ),
    provider_observed_generation: int | None = None,
    provider_connection_state: RuntimeProviderConnectionState = (
        RuntimeProviderConnectionState.CONNECTED
    ),
    runner_state: RuntimeRunnerState = RuntimeRunnerState.READY,
    runner_generation: int = 1,
    workspace_path: str | None = "/runtime/workspace",
) -> MagicMock:
    runtime = MagicMock(spec=AgentRuntime)
    runtime.id = "runtime-1"
    runtime.agent_id = "agent-1"
    runtime.workspace_runtime_profile_id = "profile-1"
    runtime.infrastructure_profile_id = "infrastructure-1"
    runtime.runtime_provider_resource_id = "provider-1"
    runtime.terminal_delete_requested_generation = None
    runtime.desired_state = RuntimeDesiredState.RUNNING
    runtime.configuration_sequence = configuration_sequence
    runtime.desired_generation = desired_generation
    runtime.provider_observed_state = provider_observed_state
    runtime.provider_observed_generation = (
        desired_generation
        if provider_observed_generation is None
        else provider_observed_generation
    )
    runtime.provider_connection_state = provider_connection_state
    runtime.runner_state = runner_state
    runtime.runner_generation = runner_generation
    runtime.workspace_path = workspace_path
    runtime.failure_generation = None
    runtime.failure_code = None
    runtime.failure_message = None
    return runtime


def _agent(
    *,
    runtime_capability: AgentRuntimeCapability = AgentRuntimeCapability.MANAGED,
) -> MagicMock:
    agent = MagicMock(spec=Agent)
    agent.runtime_capability = runtime_capability
    return agent


def _blocked_state(
    *, sequence: int = 2, target_generation: int = 0
) -> RuntimeConfigurationState:
    return RuntimeConfigurationState(
        runtime_id="runtime-1",
        desired=RuntimeConfigurationSlot(
            sequence=sequence,
            status=RuntimeConfigurationStateStatus.BLOCKED,
            target_generation=target_generation,
            digest=None,
            document=None,
            reason_code="provider_disabled",
            provider_reported_digest=None,
            runner_reported_digest=None,
            provider_acknowledged_at=None,
            runner_observed_at=None,
        ),
        applied=None,
        created_at=datetime.datetime(2026, 7, 31, tzinfo=datetime.UTC),
        updated_at=datetime.datetime(2026, 7, 31, tzinfo=datetime.UTC),
    )


def _ready_state(
    *,
    sequence: int = 1,
    digest: str = "a" * 64,
    target_generation: int = 0,
    applied: bool = True,
) -> RuntimeConfigurationState:
    document = RuntimeConfigurationDocument(
        schema_version=1,
        source_trace={},
        provider_id="provider-1",
        provider_capability_revision_id=None,
        infrastructure_profile_id="infrastructure-1",
        infrastructure_profile_version=1,
        workspace_runtime_profile_id="profile-1",
        workspace_runtime_profile_version=1,
        agent_selection_version=1,
        required_capabilities=(),
        missing_capabilities=(),
        resolved_configuration={"schema_version": 1},
    )
    desired = RuntimeConfigurationSlot(
        sequence=sequence,
        status=RuntimeConfigurationStateStatus.READY,
        target_generation=target_generation,
        digest=digest,
        document=document,
        reason_code=None,
        provider_reported_digest=None,
        runner_reported_digest=None,
        provider_acknowledged_at=None,
        runner_observed_at=None,
    )
    return RuntimeConfigurationState(
        runtime_id="runtime-1",
        desired=desired,
        applied=(
            RuntimeConfigurationAppliedSlot(
                sequence=sequence,
                target_generation=target_generation,
                digest=digest,
                document=document,
                applied_at=datetime.datetime(2026, 7, 31, tzinfo=datetime.UTC),
            )
            if applied
            else None
        ),
        created_at=datetime.datetime(2026, 7, 31, tzinfo=datetime.UTC),
        updated_at=datetime.datetime(2026, 7, 31, tzinfo=datetime.UTC),
    )


def _reconciler() -> tuple[
    RuntimeRecreationReconciler,
    AsyncMock,
    AsyncMock,
    AsyncMock,
]:
    profile_repository = AsyncMock(spec=RuntimeProfileRepository)
    profile_repository.get_recreation_target_version.return_value = "2"
    runtime_repository = AsyncMock(spec=AgentRuntimeRepository)
    agent_repository = AsyncMock(spec=AgentRepository)
    agent_repository.lock_by_id.return_value = _agent()
    reconciler = RuntimeRecreationReconciler(
        session_manager=_SessionManager(),
        profile_repository=profile_repository,
        runtime_repository=runtime_repository,
        agent_repository=agent_repository,
        operation_limit=1,
        item_limit=1,
        maximum_attempts=3,
    )
    return reconciler, profile_repository, runtime_repository, agent_repository


def _authority_service() -> tuple[
    RuntimeRecreationService,
    AsyncMock,
    AsyncMock,
]:
    profile_repository = AsyncMock(spec=RuntimeProfileRepository)
    provider_repository = AsyncMock(spec=RuntimeProviderRepository)
    service = RuntimeRecreationService(
        session_manager=_SessionManager(),
        profile_repository=profile_repository,
        provider_repository=provider_repository,
    )
    return service, profile_repository, provider_repository


async def test_workspace_operation_hides_foreign_profile_target() -> None:
    """A foreign Workspace cannot infer whether an operation exists."""
    service, profiles, _providers = _authority_service()
    profiles.get_recreation_operation.return_value = _operation()
    profiles.get_workspace_runtime_profile.return_value = None

    with pytest.raises(RuntimeRecreationUnavailable) as error:
        await service.get_workspace_operation(
            "foreign-workspace",
            "operation-1",
            offset=0,
            limit=50,
        )

    assert error.value.code == "operation_not_found"
    profiles.get_workspace_runtime_profile.assert_awaited_once_with(
        ANY,
        workspace_id="foreign-workspace",
        profile_id="profile-1",
        for_update=False,
    )
    profiles.list_recreation_items.assert_not_awaited()


async def test_workspace_operation_projects_bounded_failure_page() -> None:
    """An owned operation returns only the requested bounded failure page."""
    service, profiles, _providers = _authority_service()
    failure = dataclasses.replace(
        _item(),
        status=RuntimeRecreationItemStatus.FAILED,
        failure_code="recreation_failed",
        failure_message="Runtime recreation failed.",
    )
    profiles.get_recreation_operation.return_value = _operation()
    profiles.get_workspace_runtime_profile.return_value = MagicMock()
    profiles.list_recreation_items.return_value = [failure]

    projection = await service.get_workspace_operation(
        "workspace-1",
        "operation-1",
        offset=2,
        limit=3,
    )

    assert projection.operation.id == "operation-1"
    assert projection.items == (failure,)
    profiles.list_recreation_items.assert_awaited_once()
    call = profiles.list_recreation_items.await_args
    assert call.kwargs == {
        "operation_id": "operation-1",
        "offset": 2,
        "limit": 3,
        "statuses": (
            RuntimeRecreationItemStatus.SKIPPED,
            RuntimeRecreationItemStatus.FAILED,
        ),
    }


async def test_workspace_recreation_create_rejects_stale_target_version() -> None:
    """Workspace operation creation is fenced by the exact Profile version."""
    service, profiles, _providers = _authority_service()
    profile = MagicMock()
    profile.version = 8
    profiles.get_workspace_runtime_profile.return_value = profile

    with pytest.raises(RuntimeRecreationUnavailable) as error:
        await service.create_workspace_profile_operation(
            "workspace-1",
            "profile-1",
            expected_version=7,
            concurrency_limit=3,
            actor_workspace_user_id="workspace-user-1",
        )

    assert error.value.code == "target_version_conflict"
    assert error.value.current_version == 8
    profiles.create_recreation_operation.assert_not_awaited()


async def test_workspace_recreation_create_persists_locked_target_version() -> None:
    """Operation creation stores the repository's exact target snapshot."""
    service, profiles, _providers = _authority_service()
    profile = MagicMock()
    profile.id = "profile-1"
    profile.version = 2
    profiles.get_workspace_runtime_profile.return_value = profile
    profiles.get_recreation_target_version.return_value = "2"
    profiles.create_recreation_operation.return_value = _operation()
    profiles.list_recreation_target_items.return_value = []
    profiles.complete_empty_recreation_operation.return_value = True
    completed = dataclasses.replace(
        _operation(),
        status=RuntimeRecreationOperationStatus.COMPLETED,
        pending_count=0,
        running_count=0,
    )
    profiles.get_recreation_operation.return_value = completed

    operation = await service.create_workspace_profile_operation(
        "workspace-1",
        "profile-1",
        expected_version=2,
        concurrency_limit=3,
        actor_workspace_user_id="workspace-user-1",
    )

    assert operation.status is RuntimeRecreationOperationStatus.COMPLETED
    profiles.get_recreation_target_version.assert_awaited_once_with(
        ANY,
        target_kind=RuntimeRecreationTargetKind.WORKSPACE_RUNTIME_PROFILE,
        target_id="profile-1",
        for_share=False,
    )
    create = profiles.create_recreation_operation.await_args.kwargs
    assert create["target_version"] == "2"
    profiles.complete_empty_recreation_operation.assert_awaited_once()


async def test_recreation_dispatches_exact_next_generation() -> None:
    """A claimed item stores one atomic restart and its exact new revision."""
    reconciler, profiles, runtimes, _agents = _reconciler()
    item = _item()
    profiles.list_active_recreation_operation_ids.return_value = ["operation-1"]
    profiles.list_recreation_items.return_value = []
    profiles.claim_recreation_items.return_value = [item]
    profiles.lock_recreation_item.return_value = item
    profiles.get_recreation_operation.return_value = _operation()
    profiles.get_configuration_state.return_value = _ready_state()
    profiles.update_recreation_item_dispatch.return_value = True
    runtimes.get_by_id.return_value = _runtime()
    command = MagicMock()
    command.desired_generation = 1
    command.runtime.configuration_sequence = 1
    runtimes.set_desired_state_if_configuration_current.return_value = command

    result = await reconciler.reconcile_once()

    assert result.dispatched_items == 1
    assert result.completed_items == 0
    runtimes.set_desired_state_if_configuration_current.assert_awaited_once()
    dispatch = profiles.update_recreation_item_dispatch.await_args.kwargs
    assert dispatch["configuration_sequence"] == 1
    assert dispatch["configuration_digest"] == "a" * 64
    assert dispatch["dispatched_generation"] == 1


async def test_recreation_skips_dispatch_after_runtime_removal_fence() -> None:
    """A removal capability fence wins before a recreation restart dispatch."""
    reconciler, profiles, runtimes, agents = _reconciler()
    item = _item()
    profiles.list_active_recreation_operation_ids.return_value = ["operation-1"]
    profiles.list_recreation_items.return_value = []
    profiles.claim_recreation_items.return_value = [item]
    profiles.lock_recreation_item.return_value = item
    profiles.get_recreation_operation.return_value = _operation()
    profiles.get_configuration_state.return_value = _ready_state()
    profiles.finish_recreation_item.return_value = True
    runtimes.get_by_id.return_value = _runtime()
    agents.lock_by_id.return_value = _agent(
        runtime_capability=AgentRuntimeCapability.REMOVING
    )

    result = await reconciler.reconcile_once()

    assert result.dispatched_items == 0
    assert result.completed_items == 1
    runtimes.set_desired_state_if_configuration_current.assert_not_awaited()
    finish = profiles.finish_recreation_item.await_args.kwargs
    assert finish["status"] is RuntimeRecreationItemStatus.SKIPPED
    assert finish["failure_code"] == "runtime_capability_unavailable"


async def test_recreation_completes_only_after_exact_availability() -> None:
    """A dispatched item succeeds only after configuration and service are ready."""
    reconciler, profiles, runtimes, _agents = _reconciler()
    item = _item(expected_sequence=1, dispatched_generation=1, expected_generation=1)
    profiles.list_active_recreation_operation_ids.return_value = ["operation-1"]
    profiles.list_recreation_items.return_value = [item]
    profiles.claim_recreation_items.return_value = []
    profiles.lock_recreation_item.return_value = item
    profiles.get_recreation_operation.return_value = _operation()
    profiles.get_configuration_state.return_value = _ready_state(target_generation=1)
    profiles.finish_recreation_item.return_value = True
    runtimes.get_by_id.return_value = _runtime(
        configuration_sequence=1,
        desired_generation=1,
    )

    result = await reconciler.reconcile_once()

    assert result.dispatched_items == 0
    assert result.completed_items == 1
    runtimes.set_desired_state_if_configuration_current.assert_not_awaited()
    finish = profiles.finish_recreation_item.await_args.kwargs
    assert finish["status"] is RuntimeRecreationItemStatus.SUCCEEDED
    assert finish["failure_code"] is None


async def test_recreation_holds_slot_while_runner_is_unavailable() -> None:
    """Exact applied configuration alone does not complete disruption."""
    reconciler, profiles, runtimes, _agents = _reconciler()
    item = _item(expected_sequence=1, dispatched_generation=1, expected_generation=1)
    profiles.list_active_recreation_operation_ids.return_value = ["operation-1"]
    profiles.list_recreation_items.return_value = [item]
    profiles.claim_recreation_items.return_value = []
    profiles.lock_recreation_item.return_value = item
    profiles.get_recreation_operation.return_value = _operation()
    profiles.get_configuration_state.return_value = _ready_state(target_generation=1)
    runtimes.get_by_id.return_value = _runtime(
        configuration_sequence=1,
        desired_generation=1,
        runner_state=RuntimeRunnerState.DISCONNECTED,
        runner_generation=0,
        workspace_path=None,
    )

    result = await reconciler.reconcile_once()

    assert result.dispatched_items == 0
    assert result.completed_items == 0
    profiles.finish_recreation_item.assert_not_awaited()


async def test_recreation_skips_blocked_latest_configuration() -> None:
    """A blocked superseding revision is explicit and never recreated."""
    reconciler, profiles, runtimes, _agents = _reconciler()
    item = _item(expected_sequence=1, expected_digest="a" * 64, expected_generation=0)
    profiles.list_active_recreation_operation_ids.return_value = ["operation-1"]
    profiles.list_recreation_items.return_value = []
    profiles.claim_recreation_items.return_value = [item]
    profiles.lock_recreation_item.return_value = item
    profiles.get_recreation_operation.return_value = _operation()
    profiles.get_configuration_state.return_value = _blocked_state()
    profiles.finish_recreation_item.return_value = True
    runtimes.get_by_id.return_value = _runtime(configuration_sequence=1)

    result = await reconciler.reconcile_once()

    assert result.completed_items == 1
    runtimes.set_desired_state_if_configuration_current.assert_not_awaited()
    finish = profiles.finish_recreation_item.await_args.kwargs
    assert finish["status"] is RuntimeRecreationItemStatus.SKIPPED
    assert finish["failure_code"] == "target_no_longer_matches"


async def test_recreation_skips_configuration_changed_after_snapshot() -> None:
    """An undispatched item never adopts a different configuration target."""
    reconciler, profiles, runtimes, _agents = _reconciler()
    item = _item(expected_sequence=1, expected_digest="a" * 64, expected_generation=0)
    profiles.list_active_recreation_operation_ids.return_value = ["operation-1"]
    profiles.list_recreation_items.return_value = []
    profiles.claim_recreation_items.return_value = [item]
    profiles.lock_recreation_item.return_value = item
    profiles.get_recreation_operation.return_value = _operation()
    profiles.get_configuration_state.return_value = _ready_state(sequence=2)
    profiles.finish_recreation_item.return_value = True
    runtimes.get_by_id.return_value = _runtime(configuration_sequence=2)

    result = await reconciler.reconcile_once()

    assert result.completed_items == 1
    runtimes.set_desired_state_if_configuration_current.assert_not_awaited()
    profiles.get_configuration_state.assert_awaited_once()
    finish = profiles.finish_recreation_item.await_args.kwargs
    assert finish["status"] is RuntimeRecreationItemStatus.SKIPPED
    assert finish["failure_code"] == "configuration_target_changed"


async def test_recreation_skips_changed_authority_target_before_dispatch() -> None:
    """A newer source version cannot dispatch the operation's old snapshot."""
    reconciler, profiles, runtimes, _agents = _reconciler()
    item = _item(expected_sequence=1, expected_digest="a" * 64, expected_generation=0)
    profiles.list_active_recreation_operation_ids.return_value = ["operation-1"]
    profiles.list_recreation_items.return_value = []
    profiles.claim_recreation_items.return_value = [item]
    profiles.lock_recreation_item.return_value = item
    profiles.get_recreation_operation.return_value = _operation()
    profiles.get_recreation_target_version.return_value = "3"
    profiles.get_configuration_state.return_value = _ready_state()
    profiles.finish_recreation_item.return_value = True
    runtimes.get_by_id.return_value = _runtime(configuration_sequence=1)

    result = await reconciler.reconcile_once()

    assert result.completed_items == 1
    profiles.get_recreation_target_version.assert_awaited_once_with(
        ANY,
        target_kind=RuntimeRecreationTargetKind.WORKSPACE_RUNTIME_PROFILE,
        target_id="profile-1",
        for_share=True,
    )
    runtimes.set_desired_state_if_configuration_current.assert_not_awaited()
    profiles.get_configuration_state.assert_awaited_once()
    finish = profiles.finish_recreation_item.await_args.kwargs
    assert finish["status"] is RuntimeRecreationItemStatus.SKIPPED
    assert finish["failure_code"] == "target_version_changed"


async def test_recreation_skips_superseded_exact_dispatch() -> None:
    """A later Runtime command cannot cause an implicit second restart."""
    reconciler, profiles, runtimes, _agents = _reconciler()
    item = _item(
        expected_sequence=1,
        expected_digest="a" * 64,
        expected_generation=0,
        dispatched_generation=4,
    )
    profiles.list_active_recreation_operation_ids.return_value = ["operation-1"]
    profiles.list_recreation_items.return_value = [item]
    profiles.claim_recreation_items.return_value = []
    profiles.lock_recreation_item.return_value = item
    profiles.get_recreation_operation.return_value = _operation()
    profiles.get_configuration_state.return_value = _ready_state(
        sequence=2,
        target_generation=5,
    )
    profiles.finish_recreation_item.return_value = True
    runtimes.get_by_id.return_value = _runtime(
        configuration_sequence=2,
        desired_generation=5,
    )

    result = await reconciler.reconcile_once()

    assert result.completed_items == 1
    runtimes.set_desired_state_if_configuration_current.assert_not_awaited()
    profiles.get_configuration_state.assert_awaited_once()
    finish = profiles.finish_recreation_item.await_args.kwargs
    assert finish["status"] is RuntimeRecreationItemStatus.SKIPPED
    assert finish["failure_code"] == "recreation_dispatch_superseded"


async def test_recreation_ignores_item_locked_by_peer_worker() -> None:
    """A peer-held item cannot be processed after target authority is fenced."""
    reconciler, profiles, runtimes, _agents = _reconciler()
    item = _item()
    profiles.list_active_recreation_operation_ids.return_value = ["operation-1"]
    profiles.list_recreation_items.return_value = [item]
    profiles.claim_recreation_items.return_value = []
    profiles.lock_recreation_item.return_value = None
    profiles.get_recreation_operation.return_value = _operation()

    result = await reconciler.reconcile_once()

    assert result.processed_items == 1
    assert result.dispatched_items == 0
    assert result.completed_items == 0
    profiles.get_recreation_target_version.assert_awaited_once_with(
        ANY,
        target_kind=RuntimeRecreationTargetKind.WORKSPACE_RUNTIME_PROFILE,
        target_id="profile-1",
        for_share=True,
    )
    runtimes.get_by_id.assert_not_awaited()


async def test_recreation_does_not_dispatch_after_target_deletion() -> None:
    """An absent target cannot authorize item processing or restart dispatch."""
    reconciler, profiles, runtimes, _agents = _reconciler()
    item = _item()
    profiles.list_active_recreation_operation_ids.return_value = ["operation-1"]
    profiles.list_recreation_items.return_value = [item]
    profiles.claim_recreation_items.return_value = []
    profiles.get_recreation_operation.return_value = _operation()
    profiles.get_recreation_target_version.return_value = None
    profiles.lock_recreation_item.return_value = None

    result = await reconciler.reconcile_once()

    assert result.processed_items == 1
    assert result.dispatched_items == 0
    assert result.completed_items == 0
    profiles.get_recreation_target_version.assert_awaited_once()
    profiles.lock_recreation_item.assert_awaited_once_with(
        ANY,
        item_id="item-1",
        expected_attempt=1,
    )
    runtimes.set_desired_state_if_configuration_current.assert_not_awaited()


async def test_recreation_failure_becomes_terminal_at_maximum_attempts() -> None:
    """An exact dispatched failure is bounded by the durable attempt count."""
    reconciler, profiles, runtimes, _agents = _reconciler()
    item = _item(
        expected_sequence=1,
        expected_digest="a" * 64,
        expected_generation=0,
        dispatched_generation=4,
        attempt=3,
    )
    profiles.list_active_recreation_operation_ids.return_value = ["operation-1"]
    profiles.list_recreation_items.return_value = [item]
    profiles.claim_recreation_items.return_value = []
    profiles.lock_recreation_item.return_value = item
    profiles.get_recreation_operation.return_value = _operation()
    profiles.get_configuration_state.return_value = _ready_state(applied=False)
    profiles.retry_recreation_item.return_value = True
    runtime = _runtime(configuration_sequence=1, desired_generation=4)
    runtime.failure_generation = 4
    runtime.failure_code = "PROVIDER_RESTART_FAILED"
    runtime.failure_message = "Provider restart failed."
    runtimes.get_by_id.return_value = runtime

    result = await reconciler.reconcile_once()

    assert result.completed_items == 1
    profiles.retry_recreation_item.assert_awaited_once_with(
        ANY,
        item_id="item-1",
        expected_attempt=3,
        maximum_attempts=3,
        failure_code="PROVIDER_RESTART_FAILED",
        failure_message="Provider restart failed.",
    )
    runtimes.set_desired_state_if_configuration_current.assert_not_awaited()
