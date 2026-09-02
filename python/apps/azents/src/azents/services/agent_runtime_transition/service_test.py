"""Explicit Agent Runtime addition and rearm integration tests."""

import dataclasses
import datetime
from unittest.mock import AsyncMock, patch

import pytest
import sqlalchemy as sa
from azcommon.result import Success
from sqlalchemy.ext.asyncio import AsyncSession

from azents.core.enums import (
    AgentRuntimeCapability,
    AgentRuntimeRemovalStage,
    AgentRuntimeRemovalStatus,
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
    RuntimeTerminalDeleteAcknowledgementKind,
)
from azents.core.runtime_profile import (
    RuntimeInfrastructureProfileKind,
    RuntimeProfileLifecycle,
)
from azents.rdb.models.agent import RDBAgent
from azents.rdb.models.agent_runtime_add import RDBAgentRuntimeAddReceipt
from azents.rdb.models.agent_runtime_removal import (
    RDBAgentRuntimeRemovalOperation,
)
from azents.rdb.models.llm_provider_integration import RDBLLMProviderIntegration
from azents.rdb.models.runtime_profile import RDBWorkspaceRuntimeProfile
from azents.rdb.session import SessionManager
from azents.repos.agent import AgentRepository
from azents.repos.agent.data import Agent
from azents.repos.agent_runtime import AgentRuntimeRepository
from azents.repos.agent_runtime.data import AgentRuntime
from azents.repos.agent_runtime_add.repository import (
    AgentRuntimeAddReceiptRepository,
)
from azents.repos.agent_runtime_removal import AgentRuntimeRemovalRepository
from azents.repos.runtime_profile.data import (
    RuntimeInfrastructureProfileCreate,
    WorkspaceRuntimeProfileCreate,
)
from azents.repos.runtime_profile.repository import RuntimeProfileRepository
from azents.repos.runtime_provider.data import RuntimeProviderCreate
from azents.repos.runtime_provider.repository import RuntimeProviderRepository
from azents.repos.runtime_provider_policy.data import (
    RuntimeProviderContractRevisionCreate,
)
from azents.repos.runtime_provider_policy.repository import (
    RuntimeProviderPolicyRepository,
)
from azents.repos.workspace import WorkspaceRepository
from azents.repos.workspace.data import WorkspaceCreate
from azents.services.runtime_profile_resolution.data import (
    RuntimeProfileResolutionResult,
)
from azents.services.runtime_profile_resolution.service import (
    PreparedRuntimeProfileSelection,
    RuntimeProfileResolutionService,
)
from azents.testing.model_selection import make_test_model_selection_dict

from .data import AgentRuntimeAdditionRequest, AgentRuntimeAdditionUnavailable
from .service import AgentRuntimeTransitionService


@dataclasses.dataclass(frozen=True)
class _RuntimeFreeAgentFixture:
    """Exact sources for one Runtime-free Agent addition."""

    workspace_id: str
    agent_id: str
    provider_id: str
    provider_resource_id: str
    infrastructure_profile_id: str
    workspace_runtime_profile_id: str


class _SourceRacingResolutionService(RuntimeProfileResolutionService):
    """Force the exact-source CAS to lose immediately before final attachment."""

    async def attach_prepared_selection(
        self,
        session: AsyncSession,
        *,
        agent: Agent,
        runtime: AgentRuntime,
        prepared: PreparedRuntimeProfileSelection,
        runtime_created: bool,
    ) -> RuntimeProfileResolutionResult | None:
        with patch.object(
            self.runtime_repository,
            "attach_desired_configuration_state",
            AsyncMock(return_value=None),
        ):
            return await super().attach_prepared_selection(
                session,
                agent=agent,
                runtime=runtime,
                prepared=prepared,
                runtime_created=runtime_created,
            )


def _contract_payload() -> dict[str, object]:
    return {
        "schema_version": 1,
        "implementation_key": "kubernetes",
        "implementation_version": "test",
        "protocol_version": "agent-runtime-provider-kubernetes-v2",
        "core_lifecycle_operations": [
            "start",
            "stop",
            "restart",
            "reset",
            "observe",
            "terminal_delete",
        ],
        "optional_capabilities": [],
        "persistence": {
            "kind": "persistent",
            "reset_destroys_workspace": True,
            "terminal_delete_destroys_workspace": True,
        },
        "configuration_fields": [],
        "profile_contracts": [
            {
                "profile_kind": "kubernetes_pod",
                "contract_family": "kubernetes.pod-profile",
                "schema_versions": [1],
                "capabilities": [
                    "kubernetes.pod-profile",
                    "runtime.resources",
                    "workspace.persistent-volume",
                    "runtime.network-policy",
                ],
                "constraints": {},
            }
        ],
    }


def _profile_spec() -> dict[str, object]:
    return {
        "profile_kind": "kubernetes_pod",
        "contract_family": "kubernetes.pod-profile",
        "schema_version": 1,
        "runner_resources": {
            "cpu_request_millicores": 500,
            "cpu_limit_millicores": 1000,
            "memory_request_bytes": 536_870_912,
            "memory_limit_bytes": 1_073_741_824,
        },
        "workspace_volume": {
            "storage_class_name": "standard",
            "storage_request_bytes": 10_737_418_240,
        },
        "network_policy": {
            "allowed_cidrs": ["10.0.0.0/8"],
            "denied_cidrs": [],
        },
        "service_account_name": None,
        "scheduling": {"node_selector": {}, "tolerations": []},
        "dind": None,
    }


async def _create_profile(
    session: AsyncSession,
    *,
    workspace_id: str,
    key: str,
) -> tuple[str, str, str, str]:
    provider = await RuntimeProviderRepository().create(
        session,
        RuntimeProviderCreate(
            provider_id=f"{key}-provider",
            scope=RuntimeProviderScope.SYSTEM,
            workspace_id=None,
            kind=RuntimeProviderKind.KUBERNETES,
            display_name=f"{key} Provider",
            registration_method=RuntimeProviderRegistrationMethod.ADMIN,
            enabled=True,
            lifecycle_state=RuntimeProviderLifecycleState.ACTIVE,
            availability_mode=RuntimeProviderAvailabilityMode.PLATFORM_WIDE,
            capabilities={},
            config_schema=None,
            metadata=None,
        ),
    )
    await RuntimeProviderPolicyRepository().create_contract(
        session,
        create=RuntimeProviderContractRevisionCreate(
            provider_id=provider.id,
            digest="a" * 64,
            implementation_version="test",
            protocol_version="agent-runtime-provider-kubernetes-v2",
            contract=_contract_payload(),
            compatibility={},
        ),
    )
    profile_repository = RuntimeProfileRepository()
    infrastructure = await profile_repository.create_infrastructure_profile(
        session,
        create=RuntimeInfrastructureProfileCreate(
            provider_id=provider.id,
            profile_kind=RuntimeInfrastructureProfileKind.KUBERNETES_POD,
            display_name=f"{key} Infrastructure",
            description="Runtime transition test infrastructure Profile",
            lifecycle=RuntimeProfileLifecycle.ACTIVE,
            contract_family="kubernetes.pod-profile",
            schema_version=1,
            spec=_profile_spec(),
            required_capabilities=(
                "kubernetes.pod-profile",
                "runtime.network-policy",
                "runtime.resources",
                "workspace.persistent-volume",
            ),
            terminal_enabled=True,
            digest="b" * 64,
            actor_user_id=None,
        ),
    )
    profile = await profile_repository.create_workspace_runtime_profile(
        session,
        create=WorkspaceRuntimeProfileCreate(
            workspace_id=workspace_id,
            provider_id=provider.id,
            infrastructure_profile_id=infrastructure.id,
            display_name=f"{key} Workspace Profile",
            description="Runtime transition test Workspace Profile",
            lifecycle=RuntimeProfileLifecycle.ACTIVE,
            policy={
                "schema_version": 1,
                "network_restriction": {
                    "allowed_cidrs": ["10.10.0.0/16"],
                    "denied_cidrs": ["10.10.1.0/24"],
                },
            },
            terminal_enabled=True,
            digest="c" * 64,
            actor_workspace_user_id=None,
        ),
    )
    return (
        provider.provider_id,
        provider.id,
        infrastructure.id,
        profile.id,
    )


async def _seed_runtime_free_agent(
    session: AsyncSession,
    *,
    handle: str,
) -> _RuntimeFreeAgentFixture:
    workspace_result = await WorkspaceRepository().create(
        session,
        WorkspaceCreate(name="Runtime transition", handle=handle),
    )
    assert isinstance(workspace_result, Success)
    workspace_id = await WorkspaceRepository().resolve_id(session, handle)
    assert workspace_id is not None
    (
        provider_id,
        provider_resource_id,
        infrastructure_profile_id,
        workspace_runtime_profile_id,
    ) = await _create_profile(
        session,
        workspace_id=workspace_id,
        key=handle,
    )
    integration = RDBLLMProviderIntegration(
        workspace_id=workspace_id,
        provider=LLMProvider.ANTHROPIC,
        name=f"{handle}-integration",
        encrypted_credentials="encrypted-test-value",
        config=None,
    )
    session.add(integration)
    await session.flush()
    selection = make_test_model_selection_dict(
        integration_id=integration.id,
        provider=LLMProvider.ANTHROPIC,
        model_identifier=f"{handle}-model",
    )
    agent = RDBAgent(
        workspace_id=workspace_id,
        name="Runtime-free Agent",
        model_selection=selection,
        lightweight_model_selection=selection,
        runtime_capability=AgentRuntimeCapability.NONE,
        shell_enabled=False,
    )
    session.add(agent)
    await session.flush()
    return _RuntimeFreeAgentFixture(
        workspace_id=workspace_id,
        agent_id=agent.id,
        provider_id=provider_id,
        provider_resource_id=provider_resource_id,
        infrastructure_profile_id=infrastructure_profile_id,
        workspace_runtime_profile_id=workspace_runtime_profile_id,
    )


def _resolution_service(
    session_manager: SessionManager[AsyncSession],
) -> RuntimeProfileResolutionService:
    return RuntimeProfileResolutionService(
        session_manager=session_manager,
        agent_repository=AgentRepository(),
        runtime_repository=AgentRuntimeRepository(),
        profile_repository=RuntimeProfileRepository(),
        provider_repository=RuntimeProviderRepository(),
        provider_policy_repository=RuntimeProviderPolicyRepository(),
    )


def _transition_service(
    session_manager: SessionManager[AsyncSession],
    *,
    resolution_service: RuntimeProfileResolutionService | None = None,
) -> AgentRuntimeTransitionService:
    return AgentRuntimeTransitionService(
        session_manager=session_manager,
        agent_repository=AgentRepository(),
        runtime_repository=AgentRuntimeRepository(),
        removal_repository=AgentRuntimeRemovalRepository(),
        add_receipt_repository=AgentRuntimeAddReceiptRepository(),
        profile_repository=RuntimeProfileRepository(),
        resolution_service=resolution_service
        if resolution_service is not None
        else _resolution_service(session_manager),
    )


def _request(
    fixture: _RuntimeFreeAgentFixture,
    *,
    idempotency_key: str,
    profile_id: str | None = None,
    expected_capability_version: int = 1,
    expected_selection_version: int = 1,
) -> AgentRuntimeAdditionRequest:
    return AgentRuntimeAdditionRequest(
        agent_id=fixture.agent_id,
        workspace_runtime_profile_id=(
            fixture.workspace_runtime_profile_id if profile_id is None else profile_id
        ),
        expected_capability_version=expected_capability_version,
        expected_runtime_profile_selection_version=expected_selection_version,
        idempotency_key=idempotency_key,
    )


async def test_add_runtime_commits_stopped_revision_and_exact_replay(
    rdb_session_manager: SessionManager[AsyncSession],
) -> None:
    """First add is lazy, durable, and replayed only from exact evidence."""
    async with rdb_session_manager() as session:
        fixture = await _seed_runtime_free_agent(
            session,
            handle="runtime-transition-first-add",
        )

    service = _transition_service(rdb_session_manager)
    request = _request(fixture, idempotency_key="add-first")
    added = await service.add_runtime(request)
    replayed = await service.add_runtime(request)

    assert added.replayed is False
    assert replayed.replayed is True
    assert replayed.receipt.id == added.receipt.id
    assert replayed.runtime.id == added.runtime.id
    assert added.agent.runtime_capability is AgentRuntimeCapability.MANAGED
    assert added.agent.runtime_capability_version == 2
    assert added.agent.runtime_profile_selection_version == 2
    assert added.agent.runtime_profile_id == fixture.workspace_runtime_profile_id
    assert added.agent.shell_enabled is False
    assert added.runtime.desired_state is RuntimeDesiredState.STOPPED
    assert added.runtime.desired_generation == 0
    assert added.runtime.last_lifecycle_command is None
    assert added.runtime.last_lifecycle_dispatch_generation == 0
    assert added.runtime.workspace_path is None
    assert added.runtime.configuration_sequence == added.desired.sequence
    assert added.desired.target_generation == 0
    assert added.receipt.expected_capability_version == 1
    assert added.receipt.committed_capability_version == 2
    assert added.receipt.committed_runtime_profile_selection_version == 2

    conflicting_selection_version = _request(
        fixture,
        idempotency_key="add-first",
        expected_selection_version=2,
    )
    with pytest.raises(AgentRuntimeAdditionUnavailable) as conflict:
        await service.add_runtime(conflicting_selection_version)
    assert conflict.value.code == "runtime_add_idempotency_conflict"

    async with rdb_session_manager() as session:
        advanced = await AgentRuntimeRepository().set_desired_state(
            session,
            added.runtime.id,
            RuntimeLifecycleCommandType.START,
            RuntimeDesiredState.RUNNING,
        )
        assert advanced is not None

    with pytest.raises(AgentRuntimeAdditionUnavailable) as stale:
        await service.add_runtime(request)
    assert stale.value.code == "runtime_add_idempotency_evidence_missing"


async def test_add_runtime_source_race_rolls_back_all_transition_state(
    rdb_session_manager: SessionManager[AsyncSession],
) -> None:
    """A changed Profile source cannot leave capability, Runtime, or receipt state."""
    async with rdb_session_manager() as session:
        fixture = await _seed_runtime_free_agent(
            session,
            handle="runtime-transition-source-race",
        )
        profile = await session.get(
            RDBWorkspaceRuntimeProfile,
            fixture.workspace_runtime_profile_id,
        )
        assert profile is not None
        original_profile_version = profile.version

    base_resolution = _resolution_service(rdb_session_manager)
    racing_resolution = _SourceRacingResolutionService(
        session_manager=base_resolution.session_manager,
        agent_repository=base_resolution.agent_repository,
        runtime_repository=base_resolution.runtime_repository,
        profile_repository=base_resolution.profile_repository,
        provider_repository=base_resolution.provider_repository,
        provider_policy_repository=base_resolution.provider_policy_repository,
    )
    service = _transition_service(
        rdb_session_manager,
        resolution_service=racing_resolution,
    )

    with pytest.raises(AgentRuntimeAdditionUnavailable) as unavailable:
        await service.add_runtime(_request(fixture, idempotency_key="add-raced"))
    assert unavailable.value.code == "runtime_profile_source_changed"

    async with rdb_session_manager() as session:
        agent = await AgentRepository().get_by_id(session, fixture.agent_id)
        runtime = await AgentRuntimeRepository().get_by_agent_id(
            session,
            fixture.agent_id,
        )
        receipt_count = await session.scalar(
            sa.select(sa.func.count())
            .select_from(RDBAgentRuntimeAddReceipt)
            .where(RDBAgentRuntimeAddReceipt.agent_id == fixture.agent_id)
        )
        profile = await session.get(
            RDBWorkspaceRuntimeProfile,
            fixture.workspace_runtime_profile_id,
        )

    assert agent is not None
    assert agent.runtime_capability is AgentRuntimeCapability.NONE
    assert agent.runtime_capability_version == 1
    assert agent.runtime_profile_id is None
    assert agent.runtime_profile_selection_version == 1
    assert runtime is None
    assert receipt_count == 0
    assert profile is not None
    assert profile.version == original_profile_version


async def _complete_removal(
    session: AsyncSession,
    *,
    fixture: _RuntimeFreeAgentFixture,
    runtime: AgentRuntime,
) -> AgentRuntime:
    runtime_repository = AgentRuntimeRepository()
    requested = await runtime_repository.request_terminal_delete(
        session,
        runtime.id,
    )
    assert requested is not None
    acknowledged = await runtime_repository.record_terminal_delete_acknowledgement(
        session,
        runtime.id,
        provider_generation=3,
        acknowledged_generation=requested.desired_generation,
    )
    assert acknowledged is not None
    now = datetime.datetime.now(datetime.UTC)
    created = await AgentRuntimeRemovalRepository().create_or_get_active(
        session,
        agent_id=fixture.agent_id,
        workspace_id=fixture.workspace_id,
        requested_by_workspace_user_id="workspace-user-1",
        idempotency_key="remove-before-readd",
        expected_capability_version=2,
        committed_capability_version=3,
        agent_runtime_id=runtime.id,
        confirmed_at=now,
        destructive_scope_version=1,
        active_root_session_count=0,
        active_subagent_count=0,
        active_run_count=0,
        queued_runtime_action_count=0,
    )
    await session.execute(
        sa.update(RDBAgentRuntimeRemovalOperation)
        .where(RDBAgentRuntimeRemovalOperation.id == created.operation.id)
        .values(
            status=AgentRuntimeRemovalStatus.COMPLETED,
            stage=AgentRuntimeRemovalStage.COMPLETED,
            product_cleanup_completed_at=now,
            physical_deletion_required=True,
            target_terminal_delete_generation=requested.desired_generation,
            physical_delete_requested_at=now,
            physical_delete_acknowledgement_kind=(
                RuntimeTerminalDeleteAcknowledgementKind.PROVIDER_REPORT
            ),
            physical_delete_acknowledged_at=now,
            completed_at=now,
        )
    )
    await session.execute(
        sa.update(RDBAgent)
        .where(RDBAgent.id == fixture.agent_id)
        .values(
            runtime_capability=AgentRuntimeCapability.NONE,
            runtime_capability_version=3,
            runtime_profile_id=None,
            runtime_profile_selection_version=3,
            shell_enabled=False,
        )
    )
    return acknowledged


async def test_add_runtime_rearms_exact_completed_runtime_without_starting(
    rdb_session_manager: SessionManager[AsyncSession],
) -> None:
    """Re-add reuses the logical Runtime and clears deleted-incarnation state."""
    async with rdb_session_manager() as session:
        fixture = await _seed_runtime_free_agent(
            session,
            handle="runtime-transition-rearm",
        )
    service = _transition_service(rdb_session_manager)
    first = await service.add_runtime(_request(fixture, idempotency_key="add-initial"))
    async with rdb_session_manager() as session:
        terminated = await _complete_removal(
            session,
            fixture=fixture,
            runtime=first.runtime,
        )

    rearmed = await service.add_runtime(
        _request(
            fixture,
            idempotency_key="add-rearmed",
            expected_capability_version=3,
            expected_selection_version=3,
        )
    )

    assert rearmed.runtime.id == first.runtime.id
    assert rearmed.runtime.desired_generation == terminated.desired_generation + 1
    assert rearmed.runtime.desired_state is RuntimeDesiredState.STOPPED
    assert rearmed.runtime.last_lifecycle_command is None
    assert rearmed.runtime.last_lifecycle_dispatch_generation == (
        rearmed.runtime.desired_generation
    )
    assert rearmed.runtime.terminal_delete_requested_generation is None
    assert rearmed.runtime.terminal_delete_acknowledged_generation is None
    assert rearmed.runtime.terminal_delete_acknowledgement_kind is None
    assert rearmed.runtime.provider_observed_state is (
        RuntimeProviderObservedState.UNKNOWN
    )
    assert rearmed.runtime.provider_observed_generation == 0
    assert rearmed.runtime.runner_state is RuntimeRunnerState.UNKNOWN
    assert rearmed.runtime.workspace_path is None
    assert rearmed.runtime.configuration_sequence == rearmed.desired.sequence
    assert rearmed.desired.target_generation == rearmed.runtime.desired_generation
    assert rearmed.agent.runtime_capability is AgentRuntimeCapability.MANAGED
    assert rearmed.agent.runtime_capability_version == 4
    assert rearmed.agent.runtime_profile_selection_version == 4
    assert rearmed.agent.shell_enabled is False


async def test_add_runtime_rearm_rejects_provider_reassignment(
    rdb_session_manager: SessionManager[AsyncSession],
) -> None:
    """A retained logical Runtime cannot be rearmed onto another Provider."""
    async with rdb_session_manager() as session:
        fixture = await _seed_runtime_free_agent(
            session,
            handle="runtime-transition-provider-conflict",
        )
        _, _, _, conflicting_profile_id = await _create_profile(
            session,
            workspace_id=fixture.workspace_id,
            key="runtime-transition-provider-conflict-other",
        )
    service = _transition_service(rdb_session_manager)
    first = await service.add_runtime(_request(fixture, idempotency_key="add-original"))
    async with rdb_session_manager() as session:
        terminated = await _complete_removal(
            session,
            fixture=fixture,
            runtime=first.runtime,
        )

    with pytest.raises(AgentRuntimeAdditionUnavailable) as unavailable:
        await service.add_runtime(
            _request(
                fixture,
                idempotency_key="add-conflicting-provider",
                profile_id=conflicting_profile_id,
                expected_capability_version=3,
                expected_selection_version=3,
            )
        )
    assert unavailable.value.code == "runtime_rearm_conflict"

    async with rdb_session_manager() as session:
        agent = await AgentRepository().get_by_id(session, fixture.agent_id)
        runtime = await AgentRuntimeRepository().get_by_agent_id(
            session,
            fixture.agent_id,
        )
        receipt = await AgentRuntimeAddReceiptRepository().get_by_agent_idempotency_key(
            session,
            agent_id=fixture.agent_id,
            idempotency_key="add-conflicting-provider",
        )

    assert agent is not None
    assert agent.runtime_capability is AgentRuntimeCapability.NONE
    assert agent.runtime_capability_version == 3
    assert agent.runtime_profile_id is None
    assert runtime is not None
    assert runtime.id == first.runtime.id
    assert runtime.runtime_provider_id == fixture.provider_id
    assert runtime.runtime_provider_resource_id == fixture.provider_resource_id
    assert runtime.desired_generation == terminated.desired_generation
    assert runtime.terminal_delete_requested_generation == terminated.desired_generation
    assert runtime.terminal_delete_acknowledged_generation == (
        terminated.desired_generation
    )
    assert receipt is None
