"""Agent Runtime removal service tests."""

import datetime
from typing import NoReturn
from uuid import uuid4

import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from azents.broker.types import SessionStopSignal
from azents.core.enums import (
    ActionExecutionStatus,
    AgentRunPhase,
    AgentRunStatus,
    AgentRuntimeCapability,
    AgentRuntimeRemovalStatus,
    AgentSessionKind,
    AgentSessionProductMode,
    AgentSessionStartReason,
    AgentSessionStatus,
    RuntimeProviderBindingOrigin,
    RuntimeProviderConnectionState,
    RuntimeProviderKind,
    RuntimeProviderObservedState,
    RuntimeProviderScope,
    RuntimeRunnerState,
    RuntimeTerminalDeleteAcknowledgementKind,
)
from azents.core.runtime_profile import RuntimeConfigurationStateStatus
from azents.rdb.models.action_execution import RDBActionExecution
from azents.rdb.models.agent import RDBAgent
from azents.rdb.models.agent_automatic_project_setting import (
    RDBAgentAutomaticProjectSetting,
)
from azents.rdb.models.agent_run import RDBAgentRun
from azents.rdb.models.agent_runtime import RDBAgentRuntime
from azents.rdb.models.agent_runtime_removal import (
    RDBAgentRuntimeRemovalOperation,
)
from azents.rdb.models.agent_session import RDBAgentSession
from azents.rdb.models.runtime_profile import RDBRuntimeConfigurationState
from azents.rdb.models.runtime_provider import RDBRuntimeProvider
from azents.rdb.models.workspace import RDBWorkspace
from azents.rdb.session import SessionManager
from azents.repos.agent import AgentRepository
from azents.repos.agent_runtime import AgentRuntimeRepository
from azents.repos.agent_runtime_removal import AgentRuntimeRemovalRepository
from azents.repos.agent_runtime_removal_finalizer import (
    AgentRuntimeRemovalFinalizerRepository,
)
from azents.repos.agent_runtime_removal_scope import (
    AgentRuntimeRemovalScopeRepository,
)
from azents.testing.model_selection import make_test_model_selection_dict

from . import AgentRuntimeRemovalService
from .data import (
    AgentRuntimeRemovalConfirmationRequest,
    AgentRuntimeRemovalUnavailable,
)


class _Broker:
    """Record best-effort stop wake-ups."""

    def __init__(self) -> None:
        self.signals: list[SessionStopSignal] = []

    async def send_message(self, signal: SessionStopSignal) -> None:
        """Record one wake-up."""
        self.signals.append(signal)


async def _seed_managed_agent(
    session: AsyncSession,
    *,
    handle: str,
) -> tuple[str, str]:
    """Create one managed-unconfigured Agent."""
    workspace = RDBWorkspace(name="Runtime removal", handle=handle)
    session.add(workspace)
    await session.flush()
    selection = make_test_model_selection_dict()
    agent = RDBAgent(
        workspace_id=workspace.id,
        name="Managed Agent",
        model_selection=selection,
        lightweight_model_selection=selection,
        runtime_capability=AgentRuntimeCapability.MANAGED,
        shell_enabled=True,
    )
    session.add(agent)
    await session.flush()
    session.add(RDBAgentAutomaticProjectSetting(agent_id=agent.id))
    await session.flush()
    return workspace.id, agent.id


def _service(
    session_manager: SessionManager[AsyncSession],
    *,
    removal_repository: AgentRuntimeRemovalRepository | None = None,
) -> AgentRuntimeRemovalService:
    """Build the concrete internal removal service."""
    scope_repository = AgentRuntimeRemovalScopeRepository()
    return AgentRuntimeRemovalService(
        session_manager=session_manager,
        agent_repository=AgentRepository(),
        runtime_repository=AgentRuntimeRepository(),
        removal_repository=removal_repository or AgentRuntimeRemovalRepository(),
        scope_repository=scope_repository,
        finalizer_repository=AgentRuntimeRemovalFinalizerRepository(
            scope_repository=scope_repository
        ),
        broker=_Broker(),
    )


def _request(
    *,
    workspace_id: str,
    agent_id: str,
    idempotency_key: str = "remove-runtime",
    expected_capability_version: int = 1,
    expected_runtime_profile_selection_version: int = 1,
) -> AgentRuntimeRemovalConfirmationRequest:
    """Build one exact final-confirmation request."""
    return AgentRuntimeRemovalConfirmationRequest(
        agent_id=agent_id,
        workspace_id=workspace_id,
        requested_by_workspace_user_id="workspace-user-1",
        idempotency_key=idempotency_key,
        expected_capability_version=expected_capability_version,
        expected_runtime_profile_selection_version=(
            expected_runtime_profile_selection_version
        ),
    )


async def test_confirmation_records_private_tree_aggregate_and_exact_replay(
    rdb_session_manager: SessionManager[AsyncSession],
) -> None:
    """Confirmation stores only content-free Agent-wide impact counts."""
    async with rdb_session_manager() as session:
        workspace_id, agent_id = await _seed_managed_agent(
            session,
            handle=f"removal-impact-{uuid4().hex[:8]}",
        )
        root_id = uuid4().hex
        subagent_id = uuid4().hex
        await session.execute(
            sa.insert(RDBAgentSession),
            [
                {
                    "id": root_id,
                    "workspace_id": workspace_id,
                    "agent_id": agent_id,
                    "handle": f"root-{uuid4().hex[:8]}",
                    "session_kind": AgentSessionKind.ROOT,
                    "status": AgentSessionStatus.ACTIVE,
                    "product_mode": AgentSessionProductMode.TEAM,
                    "associated_user_id": None,
                    "start_reason": AgentSessionStartReason.INITIAL,
                },
                {
                    "id": subagent_id,
                    "workspace_id": workspace_id,
                    "agent_id": agent_id,
                    "handle": f"subagent-{uuid4().hex[:8]}",
                    "session_kind": AgentSessionKind.SUBAGENT,
                    "status": AgentSessionStatus.ACTIVE,
                    "product_mode": None,
                    "associated_user_id": None,
                    "start_reason": AgentSessionStartReason.INITIAL,
                },
            ],
        )
        await session.execute(
            sa.insert(RDBAgentRun).values(
                id=uuid4().hex,
                session_id=subagent_id,
                run_index=1,
                parent_agent_run_id=None,
                phase=AgentRunPhase.IDLE,
                status=AgentRunStatus.RUNNING,
            )
        )
        await session.execute(
            sa.insert(RDBActionExecution).values(
                id=uuid4().hex,
                session_id=root_id,
                mailbox_item_id=uuid4().hex,
                sender_user_id=None,
                action_type="create_git_worktree",
                action={"type": "create_git_worktree"},
                owner_generation=0,
                status=ActionExecutionStatus.PENDING,
            )
        )

    service = _service(rdb_session_manager)
    request = _request(workspace_id=workspace_id, agent_id=agent_id)
    confirmed = await service.confirm(request)
    replayed = await service.confirm(request)
    with pytest.raises(AgentRuntimeRemovalUnavailable) as mismatched_replay:
        await service.confirm(
            _request(
                workspace_id=workspace_id,
                agent_id=agent_id,
                expected_runtime_profile_selection_version=2,
            )
        )

    assert confirmed.replayed is False
    assert replayed.replayed is True
    assert mismatched_replay.value.code == "runtime_remove_conflict"
    assert replayed.operation.id == confirmed.operation.id
    assert confirmed.impact.active_root_session_count == 1
    assert confirmed.impact.active_subagent_count == 1
    assert confirmed.impact.active_run_count == 1
    assert confirmed.impact.queued_runtime_action_count == 1
    dumped = confirmed.operation.model_dump(mode="json")
    assert root_id not in str(dumped)
    assert subagent_id not in str(dumped)
    assert "title" not in dumped
    assert "associated_user_id" not in dumped


async def test_confirmation_rejects_stale_and_competing_requests(
    rdb_session_manager: SessionManager[AsyncSession],
) -> None:
    """Version fences and one active operation serialize confirmation."""
    async with rdb_session_manager() as session:
        workspace_id, agent_id = await _seed_managed_agent(
            session,
            handle=f"removal-conflict-{uuid4().hex[:8]}",
        )
    service = _service(rdb_session_manager)

    with pytest.raises(AgentRuntimeRemovalUnavailable) as stale:
        await service.confirm(
            _request(
                workspace_id=workspace_id,
                agent_id=agent_id,
                expected_capability_version=2,
            )
        )
    assert stale.value.code == "runtime_capability_version_conflict"

    await service.confirm(_request(workspace_id=workspace_id, agent_id=agent_id))
    with pytest.raises(AgentRuntimeRemovalUnavailable) as competing:
        await service.confirm(
            _request(
                workspace_id=workspace_id,
                agent_id=agent_id,
                idempotency_key="different-removal",
            )
        )
    assert competing.value.code == "runtime_remove_conflict"


async def test_confirmation_rolls_back_agent_fence_when_operation_creation_fails(
    rdb_session_manager: SessionManager[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Agent capability and operation creation share one transaction."""
    async with rdb_session_manager() as session:
        workspace_id, agent_id = await _seed_managed_agent(
            session,
            handle=f"removal-rollback-{uuid4().hex[:8]}",
        )
    repository = AgentRuntimeRemovalRepository()

    async def fail_create(*args: object, **kwargs: object) -> NoReturn:
        raise RuntimeError("injected operation failure")

    monkeypatch.setattr(repository, "create_or_get_active", fail_create)
    with pytest.raises(RuntimeError, match="injected operation failure"):
        await _service(
            rdb_session_manager,
            removal_repository=repository,
        ).confirm(_request(workspace_id=workspace_id, agent_id=agent_id))

    async with rdb_session_manager() as session:
        agent = await AgentRepository().get_by_id(session, agent_id)
        operation = await AgentRuntimeRemovalRepository().get_active_by_agent_id(
            session,
            agent_id,
        )
    assert agent is not None
    assert agent.runtime_capability is AgentRuntimeCapability.MANAGED
    assert agent.runtime_capability_version == 1
    assert agent.runtime_profile_selection_version == 1
    assert agent.shell_enabled is True
    assert operation is None


async def test_completed_idempotency_key_cannot_fence_readded_agent(
    rdb_session_manager: SessionManager[AsyncSession],
) -> None:
    """A historical removal key cannot replay after a later Runtime add."""
    async with rdb_session_manager() as session:
        workspace_id, agent_id = await _seed_managed_agent(
            session,
            handle=f"removal-reused-key-{uuid4().hex[:8]}",
        )
    service = _service(rdb_session_manager)
    request = _request(workspace_id=workspace_id, agent_id=agent_id)
    await service.confirm(request)
    summary = await service.coordinate_once(
        lease_owner="removal-worker-reused-key",
        deadline=datetime.datetime.now(datetime.UTC) + datetime.timedelta(minutes=10),
    )
    assert summary.completed_count == 1

    async with rdb_session_manager() as session:
        await session.execute(
            sa.update(RDBAgent)
            .where(RDBAgent.id == agent_id)
            .values(
                runtime_capability=AgentRuntimeCapability.MANAGED,
                runtime_capability_version=4,
                runtime_profile_selection_version=3,
                runtime_profile_id=None,
                shell_enabled=False,
            )
        )

    with pytest.raises(AgentRuntimeRemovalUnavailable) as reused:
        await service.confirm(
            _request(
                workspace_id=workspace_id,
                agent_id=agent_id,
                expected_capability_version=4,
                expected_runtime_profile_selection_version=3,
            )
        )
    assert reused.value.code == "runtime_remove_conflict"

    async with rdb_session_manager() as session:
        agent = await AgentRepository().get_by_id(session, agent_id)
        active = await AgentRuntimeRemovalRepository().get_active_by_agent_id(
            session,
            agent_id,
        )
    assert agent is not None
    assert agent.runtime_capability is AgentRuntimeCapability.MANAGED
    assert agent.runtime_capability_version == 4
    assert agent.runtime_profile_selection_version == 3
    assert active is None


async def test_coordinator_completes_no_runtime_removal_and_preserves_agent(
    rdb_session_manager: SessionManager[AsyncSession],
) -> None:
    """A managed-unconfigured Agent becomes Runtime-free without deletion."""
    async with rdb_session_manager() as session:
        workspace_id, agent_id = await _seed_managed_agent(
            session,
            handle=f"removal-complete-{uuid4().hex[:8]}",
        )
    service = _service(rdb_session_manager)
    confirmed = await service.confirm(
        _request(workspace_id=workspace_id, agent_id=agent_id)
    )

    summary = await service.coordinate_once(
        lease_owner="removal-worker-1",
        deadline=datetime.datetime.now(datetime.UTC) + datetime.timedelta(minutes=10),
    )

    assert summary.claimed_count == 1
    assert summary.completed_count == 1
    async with rdb_session_manager() as session:
        agent = await AgentRepository().get_by_id(session, agent_id)
        operation = await AgentRuntimeRemovalRepository().get_by_id(
            session,
            confirmed.operation.id,
        )
        workspace = await session.get(RDBWorkspace, workspace_id)
    assert agent is not None
    assert workspace is not None
    assert agent.runtime_capability is AgentRuntimeCapability.NONE
    assert agent.runtime_capability_version == 3
    assert agent.runtime_profile_selection_version == 2
    assert agent.runtime_profile_id is None
    assert agent.shell_enabled is False
    assert operation is not None
    assert operation.status is AgentRuntimeRemovalStatus.COMPLETED
    assert operation.physical_deletion_required is False


async def test_coordinator_records_locked_no_physical_binding_authority(
    rdb_session_manager: SessionManager[AsyncSession],
) -> None:
    """An empty logical Runtime is terminalized by repository-owned proof."""
    async with rdb_session_manager() as session:
        workspace_id, agent_id = await _seed_managed_agent(
            session,
            handle=f"removal-no-binding-{uuid4().hex[:8]}",
        )
        runtime = RDBAgentRuntime(
            workspace_id=workspace_id,
            agent_id=agent_id,
            runtime_provider_id=None,
            runtime_provider_resource_id=None,
            provider_binding_origin=None,
            provider_binding_evidence=None,
        )
        session.add(runtime)
        await session.flush()
        runtime_id = runtime.id
    service = _service(rdb_session_manager)
    confirmed = await service.confirm(
        _request(workspace_id=workspace_id, agent_id=agent_id)
    )
    async with rdb_session_manager() as session:
        before_delete = await AgentRuntimeRepository().get_by_id(session, runtime_id)
    assert before_delete is not None
    assert before_delete.runtime_provider_id is None
    assert before_delete.runtime_provider_resource_id is None
    assert before_delete.provider_binding_origin is None
    assert before_delete.provider_binding_evidence is None
    assert before_delete.configuration_sequence == 0
    assert before_delete.provider_generation == 0
    assert before_delete.provider_observed_state is RuntimeProviderObservedState.UNKNOWN
    assert before_delete.provider_observed_generation == 0
    assert before_delete.provider_observed_at is None
    assert before_delete.provider_observe_requested_at is None
    assert before_delete.last_lifecycle_dispatch_generation == 0
    assert (
        before_delete.provider_connection_state
        is RuntimeProviderConnectionState.DISCONNECTED
    )
    assert before_delete.runner_state is RuntimeRunnerState.UNKNOWN
    assert before_delete.runner_generation == 0
    assert before_delete.workspace_path is None
    assert before_delete.failure_generation is None
    assert before_delete.failure_code is None
    assert before_delete.failure_message is None
    assert before_delete.terminal_delete_requested_generation is None
    assert before_delete.terminal_delete_acknowledged_generation is None
    assert before_delete.terminal_delete_acknowledged_at is None
    assert before_delete.terminal_delete_acknowledgement_kind is None

    summary = await service.coordinate_once(
        lease_owner="removal-worker-no-binding",
        deadline=datetime.datetime.now(datetime.UTC) + datetime.timedelta(minutes=10),
    )

    assert summary.completed_count == 1
    async with rdb_session_manager() as session:
        runtime = await AgentRuntimeRepository().get_by_id(session, runtime_id)
        operation = await AgentRuntimeRemovalRepository().get_by_id(
            session,
            confirmed.operation.id,
        )
    assert runtime is not None
    assert operation is not None
    assert runtime.terminal_delete_requested_generation == runtime.desired_generation
    assert runtime.terminal_delete_acknowledged_generation == runtime.desired_generation
    assert runtime.terminal_delete_acknowledgement_kind is (
        RuntimeTerminalDeleteAcknowledgementKind.NO_PHYSICAL_BINDING
    )
    assert operation.physical_deletion_required is False
    assert operation.target_terminal_delete_generation is None
    assert operation.physical_delete_acknowledgement_kind is None


async def test_coordinator_waits_for_exact_provider_acknowledgement(
    rdb_session_manager: SessionManager[AsyncSession],
) -> None:
    """Provider disconnection alone never completes physical deletion."""
    async with rdb_session_manager() as session:
        workspace_id, agent_id = await _seed_managed_agent(
            session,
            handle=f"removal-provider-ack-{uuid4().hex[:8]}",
        )
        provider = RDBRuntimeProvider(
            provider_id=f"provider-{uuid4().hex[:8]}",
            scope=RuntimeProviderScope.SYSTEM,
            kind=RuntimeProviderKind.DOCKER,
            display_name="Removal Provider",
            enabled=True,
            capabilities={},
            current_contract_revision_id=None,
            active_config_revision_id=None,
            config_schema=None,
            metadata_=None,
            workspace_id=None,
        )
        session.add(provider)
        await session.flush()
        runtime = RDBAgentRuntime(
            workspace_id=workspace_id,
            agent_id=agent_id,
            runtime_provider_id=provider.provider_id,
            runtime_provider_resource_id=provider.id,
            provider_binding_origin=RuntimeProviderBindingOrigin.PLATFORM_DEFAULT,
            provider_binding_evidence={"source": "test"},
        )
        session.add(runtime)
        await session.flush()
        runtime.configuration_sequence = 1
        document = {"schema_version": 1, "resolved_configuration": {"cpu": 1}}
        now = datetime.datetime.now(datetime.UTC)
        session.add(
            RDBRuntimeConfigurationState(
                runtime_id=runtime.id,
                desired_sequence=1,
                desired_status=RuntimeConfigurationStateStatus.READY,
                desired_target_generation=0,
                desired_digest="a" * 64,
                desired_document=document,
                desired_reason_code=None,
                provider_reported_digest="a" * 64,
                runner_reported_digest="a" * 64,
                provider_acknowledged_at=now,
                runner_observed_at=now,
                applied_sequence=1,
                applied_target_generation=0,
                applied_digest="a" * 64,
                applied_document=document,
                applied_at=now,
            )
        )
        await session.flush()
        runtime_id = runtime.id
    service = _service(rdb_session_manager)
    confirmed = await service.confirm(
        _request(workspace_id=workspace_id, agent_id=agent_id)
    )

    waiting = await service.coordinate_once(
        lease_owner="removal-worker-provider",
        deadline=datetime.datetime.now(datetime.UTC) + datetime.timedelta(minutes=10),
    )

    assert waiting.claimed_count == 1
    assert waiting.completed_count == 0
    async with rdb_session_manager() as session:
        operation = await AgentRuntimeRemovalRepository().get_by_id(
            session,
            confirmed.operation.id,
        )
        agent = await AgentRepository().get_by_id(session, agent_id)
    assert operation is not None
    assert agent is not None
    assert operation.physical_deletion_required is True
    assert operation.target_terminal_delete_generation is not None
    assert operation.physical_delete_acknowledged_at is None
    assert agent.runtime_capability is AgentRuntimeCapability.REMOVING

    async with rdb_session_manager() as session:
        acknowledged = (
            await AgentRuntimeRepository().record_terminal_delete_acknowledgement(
                session,
                runtime_id,
                provider_generation=1,
                acknowledged_generation=(operation.target_terminal_delete_generation),
            )
        )
        assert acknowledged is not None
        await session.execute(
            sa.update(RDBAgentRuntimeRemovalOperation)
            .where(RDBAgentRuntimeRemovalOperation.id == confirmed.operation.id)
            .values(
                next_attempt_at=datetime.datetime.now(datetime.UTC)
                - datetime.timedelta(seconds=1)
            )
        )

    completed = await service.coordinate_once(
        lease_owner="removal-worker-provider",
        deadline=datetime.datetime.now(datetime.UTC) + datetime.timedelta(minutes=10),
    )

    assert completed.completed_count == 1
    async with rdb_session_manager() as session:
        operation = await AgentRuntimeRemovalRepository().get_by_id(
            session,
            confirmed.operation.id,
        )
        agent = await AgentRepository().get_by_id(session, agent_id)
        runtime = await AgentRuntimeRepository().get_by_id(session, runtime_id)
        configuration_state = await session.get(
            RDBRuntimeConfigurationState,
            runtime_id,
        )
    assert operation is not None
    assert agent is not None
    assert runtime is not None
    assert runtime.configuration_sequence == 1
    assert configuration_state is None
    assert operation.physical_delete_acknowledgement_kind is (
        RuntimeTerminalDeleteAcknowledgementKind.PROVIDER_REPORT
    )
    assert operation.physical_delete_acknowledged_at is not None
    assert agent.runtime_capability is AgentRuntimeCapability.NONE
