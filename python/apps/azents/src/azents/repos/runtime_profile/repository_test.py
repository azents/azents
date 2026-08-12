"""Runtime Profile persistence and durable claim tests."""

import dataclasses
import datetime

import pytest
import sqlalchemy as sa
from azcommon.result import Success
from azents_runtime_control.runtime_configuration import RuntimeConfigurationEvidence
from sqlalchemy.ext.asyncio import AsyncSession

from azents.core.enums import (
    AgentRuntimeCapability,
    LLMProvider,
    RuntimeDesiredState,
    RuntimeLifecycleCommandType,
    RuntimeProviderAvailabilityMode,
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
    RuntimeReconcileSourceKind,
    RuntimeReconcileTaskStatus,
    RuntimeRecreationItemStatus,
    RuntimeRecreationOperationStatus,
    RuntimeRecreationTargetKind,
)
from azents.rdb.models.agent import RDBAgent
from azents.rdb.models.agent_runtime import RDBAgentRuntime
from azents.rdb.models.llm_provider_integration import RDBLLMProviderIntegration
from azents.rdb.models.runtime_profile import (
    RDBRuntimeConfigurationReconcileTask,
    RDBRuntimeConfigurationState,
    RDBRuntimeRecreationOperation,
    RDBRuntimeRecreationOperationItem,
)
from azents.rdb.session import SessionManager
from azents.repos.agent_runtime import AgentRuntimeRepository
from azents.repos.runtime_provider.data import RuntimeProviderCreate
from azents.repos.runtime_provider.repository import RuntimeProviderRepository
from azents.repos.runtime_provider_policy.data import (
    RuntimeProviderContractRevisionCreate,
)
from azents.repos.runtime_provider_policy.repository import (
    RuntimeProviderPolicyRepository,
)
from azents.repos.workspace import WorkspaceRepository
from azents.repos.workspace.data import (
    WorkspaceCreate,
    WorkspaceRuntimeProfileDefaultReplace,
)
from azents.testing.model_selection import make_test_model_selection_dict

from .data import (
    RuntimeConfigurationDesiredStateWrite,
    RuntimeInfrastructureProfileCreate,
    RuntimeInfrastructureProfileReplace,
    WorkspaceRuntimeProfileCreate,
    WorkspaceRuntimeProfileReplace,
)
from .repository import RuntimeProfileRepository


async def _create_provider(
    session: AsyncSession,
    *,
    logical_id: str,
) -> str:
    """Create one Platform Kubernetes Provider for Profile tests."""
    provider = await RuntimeProviderRepository().create(
        session,
        RuntimeProviderCreate(
            provider_id=logical_id,
            scope=RuntimeProviderScope.SYSTEM,
            workspace_id=None,
            kind=RuntimeProviderKind.KUBERNETES,
            display_name=logical_id,
            registration_method=RuntimeProviderRegistrationMethod.ADMIN,
            enabled=True,
            lifecycle_state=RuntimeProviderLifecycleState.ACTIVE,
            availability_mode=RuntimeProviderAvailabilityMode.PLATFORM_WIDE,
            capabilities={},
            config_schema=None,
            metadata=None,
        ),
    )
    return provider.id


def _infrastructure_create(
    provider_id: str,
) -> RuntimeInfrastructureProfileCreate:
    return RuntimeInfrastructureProfileCreate(
        provider_id=provider_id,
        profile_kind=RuntimeInfrastructureProfileKind.KUBERNETES_POD,
        display_name="Standard Pod",
        description="Standard Runtime Pod",
        lifecycle=RuntimeProfileLifecycle.ACTIVE,
        contract_family="kubernetes.pod-profile",
        schema_version=1,
        spec={"schema_version": 1},
        required_capabilities=("kubernetes.pod-profile",),
        digest="a" * 64,
        actor_user_id=None,
    )


async def test_profile_ownership_and_optimistic_replacement(
    rdb_session_manager: SessionManager[AsyncSession],
) -> None:
    """Provider and Workspace ownership remain exact across mutations."""
    repository = RuntimeProfileRepository()
    async with rdb_session_manager() as session:
        provider_id = await _create_provider(
            session,
            logical_id="profile-provider-1",
        )
        other_provider_id = await _create_provider(
            session,
            logical_id="profile-provider-2",
        )
        workspace_repository = WorkspaceRepository()
        workspace_result = await workspace_repository.create(
            session,
            WorkspaceCreate(name="Runtime Profile test", handle="runtime-profile-test"),
        )
        assert isinstance(workspace_result, Success)
        workspace_id = await workspace_repository.resolve_id(
            session, "runtime-profile-test"
        )
        assert workspace_id is not None
        infrastructure = await repository.create_infrastructure_profile(
            session,
            create=_infrastructure_create(provider_id),
        )

        stale = await repository.replace_infrastructure_profile(
            session,
            provider_id=provider_id,
            profile_id=infrastructure.id,
            expected_version=2,
            replacement=RuntimeInfrastructureProfileReplace(
                display_name="Changed",
                description="Changed",
                lifecycle=RuntimeProfileLifecycle.ACTIVE,
                contract_family="kubernetes.pod-profile",
                schema_version=1,
                spec={"schema_version": 1, "changed": True},
                required_capabilities=("kubernetes.pod-profile",),
                digest="b" * 64,
                actor_user_id=None,
            ),
        )
        replaced = await repository.replace_infrastructure_profile(
            session,
            provider_id=provider_id,
            profile_id=infrastructure.id,
            expected_version=1,
            replacement=RuntimeInfrastructureProfileReplace(
                display_name="Changed",
                description="Changed",
                lifecycle=RuntimeProfileLifecycle.ACTIVE,
                contract_family="kubernetes.pod-profile",
                schema_version=1,
                spec={"schema_version": 1, "changed": True},
                required_capabilities=("kubernetes.pod-profile",),
                digest="b" * 64,
                actor_user_id=None,
            ),
        )

        assert stale is None
        assert replaced is not None
        assert replaced.version == 2
        workspace_profile = await repository.create_workspace_runtime_profile(
            session,
            create=WorkspaceRuntimeProfileCreate(
                workspace_id=workspace_id,
                provider_id=provider_id,
                infrastructure_profile_id=infrastructure.id,
                display_name="Workspace Standard",
                description="Workspace Runtime choice",
                lifecycle=RuntimeProfileLifecycle.ACTIVE,
                policy={"schema_version": 1, "network_restriction": None},
                digest="c" * 64,
                actor_workspace_user_id=None,
            ),
        )
        assert workspace_profile.provider_id == infrastructure.provider_id

        with pytest.raises(ValueError, match="does not belong"):
            await repository.create_workspace_runtime_profile(
                session,
                create=WorkspaceRuntimeProfileCreate(
                    workspace_id=workspace_id,
                    provider_id=other_provider_id,
                    infrastructure_profile_id=infrastructure.id,
                    display_name="Invalid",
                    description="Invalid Provider binding",
                    lifecycle=RuntimeProfileLifecycle.ACTIVE,
                    policy={"schema_version": 1, "network_restriction": None},
                    digest="d" * 64,
                    actor_workspace_user_id=None,
                ),
            )


async def test_configuration_evidence_promotes_after_provider_and_runner_ack(
    rdb_session_manager: SessionManager[AsyncSession],
) -> None:
    """Current desired state promotes only after exact Provider and Runner evidence."""
    repository = RuntimeProfileRepository()
    runtime_repository = AgentRuntimeRepository()
    async with rdb_session_manager() as session:
        provider_id = await _create_provider(
            session, logical_id="configuration-evidence-provider"
        )
        workspace_repository = WorkspaceRepository()
        workspace_result = await workspace_repository.create(
            session,
            WorkspaceCreate(
                name="Configuration evidence", handle="configuration-evidence"
            ),
        )
        assert isinstance(workspace_result, Success)
        workspace_id = await workspace_repository.resolve_id(
            session, "configuration-evidence"
        )
        assert workspace_id is not None
        infrastructure = await repository.create_infrastructure_profile(
            session, create=_infrastructure_create(provider_id)
        )
        workspace_profile = await repository.create_workspace_runtime_profile(
            session,
            create=WorkspaceRuntimeProfileCreate(
                workspace_id=workspace_id,
                provider_id=provider_id,
                infrastructure_profile_id=infrastructure.id,
                display_name="Evidence",
                description="Configuration evidence",
                lifecycle=RuntimeProfileLifecycle.ACTIVE,
                policy={"schema_version": 1, "network_restriction": None},
                digest="f" * 64,
                actor_workspace_user_id=None,
            ),
        )
        integration = RDBLLMProviderIntegration(
            workspace_id=workspace_id,
            provider=LLMProvider.ANTHROPIC,
            name="configuration-evidence-integration",
            encrypted_credentials="encrypted",
            config=None,
        )
        session.add(integration)
        await session.flush()
        selection = make_test_model_selection_dict(
            integration_id=integration.id,
            provider=LLMProvider.ANTHROPIC,
            model_identifier="model",
        )
        agent = RDBAgent(
            workspace_id=workspace_id,
            name="Configuration evidence Agent",
            model_selection=selection,
            lightweight_model_selection=selection,
        )
        session.add(agent)
        await session.flush()
        runtime = await runtime_repository.ensure_for_agent(session, agent.id)
        await session.execute(
            sa.update(RDBAgentRuntime)
            .where(RDBAgentRuntime.id == runtime.id)
            .values(runtime_provider_resource_id=provider_id)
        )
        document = RuntimeConfigurationDocument(
            schema_version=1,
            source_trace={},
            provider_id=provider_id,
            provider_capability_revision_id=None,
            infrastructure_profile_id=infrastructure.id,
            infrastructure_profile_version=infrastructure.version,
            workspace_runtime_profile_id=workspace_profile.id,
            workspace_runtime_profile_version=workspace_profile.version,
            agent_selection_version=1,
            required_capabilities=(),
            missing_capabilities=(),
            resolved_configuration={"schema_version": 1},
        )
        state = await repository.overwrite_desired_configuration_state(
            session,
            write=RuntimeConfigurationDesiredStateWrite(
                runtime_id=runtime.id,
                status=RuntimeConfigurationStateStatus.READY,
                target_generation=runtime.desired_generation,
                digest="d" * 64,
                document=document,
                reason_code=None,
            ),
        )
        assert state is not None
        evidence = RuntimeConfigurationEvidence(
            configuration_sequence=state.desired.sequence,
            digest="d" * 64,
            desired_generation=runtime.desired_generation,
        )
        assert await repository.configuration_evidence_matches_current(
            session, runtime_id=runtime.id, provider_id=provider_id, evidence=evidence
        )
        acknowledged_at = datetime.datetime(2026, 7, 30, tzinfo=datetime.UTC)
        provider_state = await repository.record_provider_configuration_evidence(
            session,
            runtime_id=runtime.id,
            provider_id=provider_id,
            evidence=evidence,
            acknowledged_at=acknowledged_at,
        )
        assert provider_state is not None
        assert provider_state.desired.provider_reported_digest == "d" * 64
        assert provider_state.applied is None
        observed_at = datetime.datetime(2026, 7, 30, 0, 0, 1, tzinfo=datetime.UTC)
        applied_state = await repository.record_runner_configuration_evidence(
            session,
            runtime_id=runtime.id,
            provider_id=provider_id,
            evidence=evidence,
            observed_at=observed_at,
        )
        assert applied_state is not None
        assert applied_state.applied is not None
        assert applied_state.applied.sequence == state.desired.sequence
        command = await runtime_repository.set_desired_state_if_configuration_current(
            session,
            runtime.id,
            RuntimeLifecycleCommandType.RESTART,
            RuntimeDesiredState.RUNNING,
            expected_configuration_sequence=state.desired.sequence,
            expected_digest="d" * 64,
            expected_generation=runtime.desired_generation,
        )
        assert command is not None
        assert command.desired_generation == runtime.desired_generation + 1
        next_state = await repository.get_configuration_state(
            session, runtime_id=runtime.id
        )
        assert next_state is not None
        assert next_state.desired.sequence > state.desired.sequence
        assert next_state.desired.target_generation == command.desired_generation


async def test_reconcile_enqueue_is_idempotent_and_claimed_once(
    rdb_session_manager: SessionManager[AsyncSession],
) -> None:
    """One source version produces one durable claimable task."""
    repository = RuntimeProfileRepository()
    now = datetime.datetime(2026, 7, 30, 12, tzinfo=datetime.UTC)
    async with rdb_session_manager() as session:
        first = await repository.enqueue_reconcile_task(
            session,
            source_type=RuntimeReconcileSourceKind.PROVIDER_CAPABILITY,
            source_id="provider-1",
            source_version="digest-1",
            available_at=now,
        )
        repeated = await repository.enqueue_reconcile_task(
            session,
            source_type=RuntimeReconcileSourceKind.PROVIDER_CAPABILITY,
            source_id="provider-1",
            source_version="digest-1",
            available_at=now,
        )

        assert repeated.id == first.id
        claimed = await repository.claim_reconcile_tasks(
            session,
            available_before=now,
            reclaim_running_before=now - datetime.timedelta(minutes=5),
            limit=10,
        )
        second_claim = await repository.claim_reconcile_tasks(
            session,
            available_before=now,
            reclaim_running_before=now - datetime.timedelta(minutes=5),
            limit=10,
        )

        assert len(claimed) == 1
        assert claimed[0].status is RuntimeReconcileTaskStatus.RUNNING
        assert claimed[0].attempt == 1
        assert second_claim == []
        await session.execute(
            sa.update(RDBRuntimeConfigurationReconcileTask)
            .where(RDBRuntimeConfigurationReconcileTask.id == claimed[0].id)
            .values(updated_at=now - datetime.timedelta(minutes=10))
        )
        reclaimed = await repository.claim_reconcile_tasks(
            session,
            available_before=now,
            reclaim_running_before=now - datetime.timedelta(minutes=5),
            limit=10,
        )
        assert len(reclaimed) == 1
        assert reclaimed[0].id == claimed[0].id
        assert reclaimed[0].attempt == 2
        assert not await repository.complete_reconcile_task(
            session,
            task_id=claimed[0].id,
            expected_attempt=claimed[0].attempt,
            cursor="stale-runtime",
        )
        assert await repository.complete_reconcile_task(
            session,
            task_id=reclaimed[0].id,
            expected_attempt=reclaimed[0].attempt,
            cursor="runtime-100",
        )


async def test_affected_agent_queries_follow_exact_profile_bindings(
    rdb_session_manager: SessionManager[AsyncSession],
) -> None:
    """Every source fan-out reaches only Agents with the exact stored path."""
    repository = RuntimeProfileRepository()
    async with rdb_session_manager() as session:
        provider_id = await _create_provider(
            session,
            logical_id="affected-agent-provider",
        )
        workspace_repository = WorkspaceRepository()
        workspace_result = await workspace_repository.create(
            session,
            WorkspaceCreate(
                name="Affected Agent queries",
                handle="affected-agent-queries",
            ),
        )
        assert isinstance(workspace_result, Success)
        workspace_id = await workspace_repository.resolve_id(
            session,
            "affected-agent-queries",
        )
        assert workspace_id is not None
        infrastructure = await repository.create_infrastructure_profile(
            session,
            create=_infrastructure_create(provider_id),
        )
        workspace_profile = await repository.create_workspace_runtime_profile(
            session,
            create=WorkspaceRuntimeProfileCreate(
                workspace_id=workspace_id,
                provider_id=provider_id,
                infrastructure_profile_id=infrastructure.id,
                display_name="Affected Profile",
                description="Affected Agent query Profile",
                lifecycle=RuntimeProfileLifecycle.ACTIVE,
                policy={"schema_version": 1, "network_restriction": None},
                digest="9" * 64,
                actor_workspace_user_id=None,
            ),
        )
        integration = RDBLLMProviderIntegration(
            workspace_id=workspace_id,
            provider=LLMProvider.ANTHROPIC,
            name="affected-agent-integration",
            encrypted_credentials="encrypted-test-value",
            config=None,
        )
        session.add(integration)
        await session.flush()
        selected_agent_ids: set[str] = set()
        for index in range(2):
            selection = make_test_model_selection_dict(
                integration_id=integration.id,
                provider=LLMProvider.ANTHROPIC,
                model_identifier=f"affected-agent-{index}",
            )
            agent = RDBAgent(
                workspace_id=workspace_id,
                name=f"Affected Agent {index}",
                model_selection=selection,
                lightweight_model_selection=selection,
                runtime_profile_id=workspace_profile.id,
            )
            session.add(agent)
            await session.flush()
            selected_agent_ids.add(agent.id)
        unconfigured_selection = make_test_model_selection_dict(
            integration_id=integration.id,
            provider=LLMProvider.ANTHROPIC,
            model_identifier="affected-agent-unconfigured",
        )
        unconfigured = RDBAgent(
            workspace_id=workspace_id,
            name="Unconfigured Agent",
            model_selection=unconfigured_selection,
            lightweight_model_selection=unconfigured_selection,
            runtime_profile_id=None,
        )
        session.add(unconfigured)
        await session.flush()

        for source_type, source_id in (
            (RuntimeReconcileSourceKind.PROVIDER, provider_id),
            (RuntimeReconcileSourceKind.PROVIDER_CAPABILITY, provider_id),
            (
                RuntimeReconcileSourceKind.INFRASTRUCTURE_PROFILE,
                infrastructure.id,
            ),
            (
                RuntimeReconcileSourceKind.WORKSPACE_RUNTIME_PROFILE,
                workspace_profile.id,
            ),
        ):
            affected = await repository.list_affected_agent_ids(
                session,
                source_type=source_type,
                source_id=source_id,
                after_agent_id=None,
                limit=10,
            )
            assert set(affected) == selected_agent_ids
            assert unconfigured.id not in affected

        selected_agent_id = next(iter(selected_agent_ids))
        assert await repository.list_affected_agent_ids(
            session,
            source_type=RuntimeReconcileSourceKind.AGENT_SELECTION,
            source_id=selected_agent_id,
            after_agent_id=None,
            limit=10,
        ) == [selected_agent_id]


async def test_delete_workspace_profile_clears_live_authority_and_retains_applied(
    rdb_session_manager: SessionManager[AsyncSession],
) -> None:
    """Hard delete is atomic and preserves the running Runtime snapshot."""
    repository = RuntimeProfileRepository()
    workspace_repository = WorkspaceRepository()
    async with rdb_session_manager() as session:
        provider_id = await _create_provider(
            session,
            logical_id="profile-hard-delete-provider",
        )
        workspace_result = await workspace_repository.create(
            session,
            WorkspaceCreate(
                name="Profile hard delete",
                handle="profile-hard-delete",
            ),
        )
        assert isinstance(workspace_result, Success)
        workspace_id = await workspace_repository.resolve_id(
            session,
            "profile-hard-delete",
        )
        assert workspace_id is not None
        infrastructure = await repository.create_infrastructure_profile(
            session,
            create=_infrastructure_create(provider_id),
        )
        profile = await repository.create_workspace_runtime_profile(
            session,
            create=WorkspaceRuntimeProfileCreate(
                workspace_id=workspace_id,
                provider_id=provider_id,
                infrastructure_profile_id=infrastructure.id,
                display_name="Delete me",
                description="Selected Profile",
                lifecycle=RuntimeProfileLifecycle.ACTIVE,
                policy={"schema_version": 1, "network_restriction": None},
                digest="b" * 64,
                actor_workspace_user_id=None,
            ),
        )
        default = await workspace_repository.replace_runtime_profile_default(
            session,
            workspace_id,
            WorkspaceRuntimeProfileDefaultReplace(
                expected_version=1,
                runtime_profile_id=profile.id,
            ),
        )
        assert default is not None
        integration = RDBLLMProviderIntegration(
            workspace_id=workspace_id,
            provider=LLMProvider.ANTHROPIC,
            name="profile-hard-delete-integration",
            encrypted_credentials="encrypted-test-value",
            config=None,
        )
        session.add(integration)
        await session.flush()
        agent_ids: list[str] = []
        for index in range(2):
            selection = make_test_model_selection_dict(
                integration_id=integration.id,
                provider=LLMProvider.ANTHROPIC,
                model_identifier=f"profile-hard-delete-{index}",
            )
            agent = RDBAgent(
                workspace_id=workspace_id,
                name=f"Selected Agent {index}",
                model_selection=selection,
                lightweight_model_selection=selection,
                runtime_profile_id=profile.id,
                runtime_capability=AgentRuntimeCapability.MANAGED,
                shell_enabled=True,
            )
            session.add(agent)
            await session.flush()
            agent_ids.append(agent.id)
        runtime = RDBAgentRuntime(
            workspace_id=workspace_id,
            agent_id=agent_ids[0],
            runtime_provider_id="profile-hard-delete-provider",
            runtime_provider_resource_id=provider_id,
        )
        session.add(runtime)
        await session.flush()
        runtime.provider_observed_state = RuntimeProviderObservedState.RUNNING
        runtime.configuration_sequence = 1
        document = RuntimeConfigurationDocument(
            schema_version=1,
            source_trace={},
            provider_id=provider_id,
            provider_capability_revision_id=None,
            infrastructure_profile_id=infrastructure.id,
            infrastructure_profile_version=infrastructure.version,
            workspace_runtime_profile_id=profile.id,
            workspace_runtime_profile_version=profile.version,
            agent_selection_version=1,
            required_capabilities=(),
            missing_capabilities=(),
            resolved_configuration={"workspace": "preserved"},
        ).model_dump(mode="json")
        now = datetime.datetime.now(datetime.UTC)
        session.add(
            RDBRuntimeConfigurationState(
                runtime_id=runtime.id,
                desired_sequence=1,
                desired_status=RuntimeConfigurationStateStatus.READY,
                desired_target_generation=0,
                desired_digest="c" * 64,
                desired_document=document,
                desired_reason_code=None,
                provider_reported_digest="c" * 64,
                runner_reported_digest="c" * 64,
                provider_acknowledged_at=now,
                runner_observed_at=now,
                applied_sequence=1,
                applied_target_generation=0,
                applied_digest="c" * 64,
                applied_document=document,
                applied_at=now,
            )
        )
        operation = await repository.create_recreation_operation(
            session,
            target_kind=RuntimeRecreationTargetKind.WORKSPACE_RUNTIME_PROFILE,
            target_id=profile.id,
            target_version=str(profile.version),
            concurrency_limit=1,
            actor_user_id=None,
            actor_workspace_user_id=None,
        )
        await repository.add_recreation_items(
            session,
            operation_id=operation.id,
            items=[(runtime.id, 1, "c" * 64, 0)],
        )

        outcome = await repository.delete_workspace_runtime_profile(
            session,
            workspace_id=workspace_id,
            profile_id=profile.id,
            expected_version=profile.version,
        )

        workspace = await workspace_repository.get_by_id(session, workspace_id)
        selected_agents = [
            await session.get(RDBAgent, agent_id) for agent_id in agent_ids
        ]
        retained_runtime = await AgentRuntimeRepository().get_by_id(
            session,
            runtime.id,
        )
        state = await repository.get_configuration_state(
            session,
            runtime_id=runtime.id,
        )
        deleted_profile = await repository.get_workspace_runtime_profile(
            session,
            workspace_id=workspace_id,
            profile_id=profile.id,
            for_update=False,
        )
        completed_operation = await repository.get_recreation_operation(
            session,
            operation_id=operation.id,
        )
        skipped_items = await repository.list_recreation_items(
            session,
            operation_id=operation.id,
            offset=0,
            limit=10,
        )

    assert outcome.deletion is not None
    assert outcome.deletion.cleared_workspace_default is True
    assert outcome.deletion.cleared_agent_count == 2
    assert outcome.deletion.affected_running_runtime_count == 1
    assert outcome.deletion.superseded_recreation_operation_count == 1
    assert workspace is not None
    assert workspace.default_runtime_profile_id is None
    assert workspace.default_runtime_profile_version == 3
    assert all(agent is not None for agent in selected_agents)
    assert all(agent.runtime_profile_id is None for agent in selected_agents if agent)
    assert all(
        agent.runtime_profile_selection_version == 2
        for agent in selected_agents
        if agent
    )
    assert retained_runtime is not None
    assert retained_runtime.configuration_sequence == 2
    assert retained_runtime.runtime_provider_resource_id == provider_id
    assert state is not None
    assert state.desired.status is RuntimeConfigurationStateStatus.UNCONFIGURED
    assert state.desired.sequence == 2
    assert state.desired.reason_code == "runtime_profile_required"
    assert state.applied is not None
    assert state.applied.sequence == 1
    assert state.applied.document.workspace_runtime_profile_id == profile.id
    assert deleted_profile is None
    assert completed_operation is not None
    assert completed_operation.status is RuntimeRecreationOperationStatus.COMPLETED
    assert completed_operation.pending_count == 0
    assert completed_operation.skipped_count == 1
    assert len(skipped_items) == 1
    skipped_item = skipped_items[0]
    assert skipped_item.status is RuntimeRecreationItemStatus.SKIPPED
    assert skipped_item.failure_code == "target_deleted"


async def test_infrastructure_profile_impact_and_hard_delete_preserve_runtime(
    rdb_session_manager: SessionManager[AsyncSession],
) -> None:
    """Only current Workspace references block infrastructure Profile deletion."""
    repository = RuntimeProfileRepository()
    async with rdb_session_manager() as session:
        provider_id = await _create_provider(
            session,
            logical_id="infrastructure-hard-delete-provider",
        )
        workspace_repository = WorkspaceRepository()
        workspace_result = await workspace_repository.create(
            session,
            WorkspaceCreate(
                name="Infrastructure hard delete",
                handle="infrastructure-hard-delete",
            ),
        )
        assert isinstance(workspace_result, Success)
        workspace_id = await workspace_repository.resolve_id(
            session,
            "infrastructure-hard-delete",
        )
        assert workspace_id is not None
        deleted_infrastructure = await repository.create_infrastructure_profile(
            session,
            create=_infrastructure_create(provider_id),
        )
        replacement_infrastructure = await repository.create_infrastructure_profile(
            session,
            create=dataclasses.replace(
                _infrastructure_create(provider_id),
                display_name="Replacement Pod",
                digest="b" * 64,
            ),
        )
        workspace_profile = await repository.create_workspace_runtime_profile(
            session,
            create=WorkspaceRuntimeProfileCreate(
                workspace_id=workspace_id,
                provider_id=provider_id,
                infrastructure_profile_id=deleted_infrastructure.id,
                display_name="Selected Profile",
                description="Current blocking reference",
                lifecycle=RuntimeProfileLifecycle.DISABLED,
                policy={"schema_version": 1, "network_restriction": None},
                digest="c" * 64,
                actor_workspace_user_id=None,
            ),
        )
        integration = RDBLLMProviderIntegration(
            workspace_id=workspace_id,
            provider=LLMProvider.ANTHROPIC,
            name="infrastructure-hard-delete-integration",
            encrypted_credentials="encrypted-test-value",
            config=None,
        )
        session.add(integration)
        await session.flush()
        selection = make_test_model_selection_dict(
            integration_id=integration.id,
            provider=LLMProvider.ANTHROPIC,
            model_identifier="infrastructure-hard-delete",
        )
        agent = RDBAgent(
            workspace_id=workspace_id,
            name="Infrastructure hard delete Agent",
            model_selection=selection,
            lightweight_model_selection=selection,
            runtime_profile_id=workspace_profile.id,
            runtime_capability=AgentRuntimeCapability.MANAGED,
        )
        session.add(agent)
        await session.flush()
        runtime = RDBAgentRuntime(
            workspace_id=workspace_id,
            agent_id=agent.id,
            runtime_provider_id="infrastructure-hard-delete-provider",
            runtime_provider_resource_id=provider_id,
        )
        session.add(runtime)
        await session.flush()
        runtime.provider_observed_state = RuntimeProviderObservedState.RUNNING
        runtime.workspace_path = "/workspace/agent"
        runtime.configuration_sequence = 1
        document = RuntimeConfigurationDocument(
            schema_version=1,
            source_trace={},
            provider_id=provider_id,
            provider_capability_revision_id=None,
            infrastructure_profile_id=deleted_infrastructure.id,
            infrastructure_profile_version=deleted_infrastructure.version,
            workspace_runtime_profile_id=workspace_profile.id,
            workspace_runtime_profile_version=workspace_profile.version,
            agent_selection_version=1,
            required_capabilities=(),
            missing_capabilities=(),
            resolved_configuration={"workspace": "preserved"},
        ).model_dump(mode="json")
        now = datetime.datetime.now(datetime.UTC)
        session.add(
            RDBRuntimeConfigurationState(
                runtime_id=runtime.id,
                desired_sequence=1,
                desired_status=RuntimeConfigurationStateStatus.READY,
                desired_target_generation=0,
                desired_digest="d" * 64,
                desired_document=document,
                desired_reason_code=None,
                provider_reported_digest="d" * 64,
                runner_reported_digest="d" * 64,
                provider_acknowledged_at=now,
                runner_observed_at=now,
                applied_sequence=1,
                applied_target_generation=0,
                applied_digest="d" * 64,
                applied_document=document,
                applied_at=now,
            )
        )
        await session.flush()

        blocked_impact = await repository.get_infrastructure_profile_deletion_impact(
            session,
            profile_id=deleted_infrastructure.id,
            offset=0,
            limit=10,
        )
        blocked_delete = await repository.delete_infrastructure_profile(
            session,
            provider_id=provider_id,
            profile_id=deleted_infrastructure.id,
            expected_version=deleted_infrastructure.version,
        )

        assert blocked_impact.blocking_reference_count == 1
        assert blocked_impact.applied_only_running_runtime_count == 0
        assert len(blocked_impact.references) == 1
        reference = blocked_impact.references[0]
        assert reference.workspace_name == "Infrastructure hard delete"
        assert reference.workspace_handle == "infrastructure-hard-delete"
        assert reference.workspace_runtime_profile_lifecycle is (
            RuntimeProfileLifecycle.DISABLED
        )
        assert reference.selected_agent_count == 1
        assert reference.running_runtime_count == 1
        assert blocked_delete.deletion is None
        assert blocked_delete.blocking_reference_count == 1

        replaced_workspace_profile = await repository.replace_workspace_runtime_profile(
            session,
            workspace_id=workspace_id,
            profile_id=workspace_profile.id,
            expected_version=workspace_profile.version,
            replacement=WorkspaceRuntimeProfileReplace(
                provider_id=provider_id,
                infrastructure_profile_id=replacement_infrastructure.id,
                display_name=workspace_profile.display_name,
                description=workspace_profile.description,
                lifecycle=workspace_profile.lifecycle,
                policy=workspace_profile.policy,
                digest="e" * 64,
                actor_workspace_user_id=None,
            ),
        )
        assert replaced_workspace_profile is not None
        operation = await repository.create_recreation_operation(
            session,
            target_kind=RuntimeRecreationTargetKind.INFRASTRUCTURE_PROFILE,
            target_id=deleted_infrastructure.id,
            target_version=str(deleted_infrastructure.version),
            concurrency_limit=1,
            actor_user_id=None,
            actor_workspace_user_id=None,
        )
        await repository.add_recreation_items(
            session,
            operation_id=operation.id,
            items=[(runtime.id, 1, "d" * 64, 0)],
        )
        claimed = await repository.claim_recreation_items(
            session,
            operation_id=operation.id,
            limit=1,
        )
        assert len(claimed) == 1

        ready_impact = await repository.get_infrastructure_profile_deletion_impact(
            session,
            profile_id=deleted_infrastructure.id,
            offset=0,
            limit=10,
        )
        outcome = await repository.delete_infrastructure_profile(
            session,
            provider_id=provider_id,
            profile_id=deleted_infrastructure.id,
            expected_version=deleted_infrastructure.version,
        )
        retained_runtime = (
            await session.execute(
                sa.select(
                    RDBAgentRuntime.provider_observed_state,
                    RDBAgentRuntime.workspace_path,
                    RDBAgentRuntime.configuration_sequence,
                ).where(RDBAgentRuntime.id == runtime.id)
            )
        ).one_or_none()
        retained_state = await repository.get_configuration_state(
            session,
            runtime_id=runtime.id,
        )
        retained_agent = await session.get(RDBAgent, agent.id)
        retained_workspace_profile = await repository.get_workspace_runtime_profile(
            session,
            workspace_id=workspace_id,
            profile_id=workspace_profile.id,
            for_update=False,
        )
        completed_operation = await repository.get_recreation_operation(
            session,
            operation_id=operation.id,
        )
        skipped_items = await repository.list_recreation_items(
            session,
            operation_id=operation.id,
            offset=0,
            limit=10,
        )
        recreated_name = await repository.create_infrastructure_profile(
            session,
            create=dataclasses.replace(
                _infrastructure_create(provider_id),
                digest="f" * 64,
            ),
        )

    assert ready_impact.blocking_reference_count == 0
    assert ready_impact.references == ()
    assert ready_impact.applied_only_running_runtime_count == 1
    assert outcome.deletion is not None
    assert outcome.deletion.superseded_recreation_operation_count == 1
    assert outcome.deletion.skipped_recreation_item_count == 1
    assert retained_runtime is not None
    assert retained_runtime.provider_observed_state is (
        RuntimeProviderObservedState.RUNNING
    )
    assert retained_runtime.workspace_path == "/workspace/agent"
    assert retained_runtime.configuration_sequence == 1
    assert retained_state is not None
    assert retained_state.desired.sequence == 1
    assert retained_state.applied is not None
    assert (
        retained_state.applied.document.infrastructure_profile_id
        == deleted_infrastructure.id
    )
    assert retained_agent is not None
    assert retained_agent.runtime_profile_id == workspace_profile.id
    assert retained_workspace_profile is not None
    assert (
        retained_workspace_profile.infrastructure_profile_id
        == replacement_infrastructure.id
    )
    assert completed_operation is not None
    assert completed_operation.status is RuntimeRecreationOperationStatus.COMPLETED
    assert completed_operation.running_count == 0
    assert completed_operation.skipped_count == 1
    assert len(skipped_items) == 1
    assert skipped_items[0].status is RuntimeRecreationItemStatus.SKIPPED
    assert skipped_items[0].failure_code == "target_deleted"
    assert recreated_name.display_name == deleted_infrastructure.display_name
    assert recreated_name.id != deleted_infrastructure.id


async def test_recreation_target_items_match_exact_document_profile_fields(
    rdb_session_manager: SessionManager[AsyncSession],
) -> None:
    """Profile targets ignore matching IDs in unrelated document fields."""
    repository = RuntimeProfileRepository()
    async with rdb_session_manager() as session:
        provider_id = await _create_provider(
            session,
            logical_id="recreation-exact-target-provider",
        )
        workspace_result = await WorkspaceRepository().create(
            session,
            WorkspaceCreate(
                name="Recreation exact target",
                handle="recreation-exact-target",
            ),
        )
        assert isinstance(workspace_result, Success)
        workspace_id = await WorkspaceRepository().resolve_id(
            session,
            "recreation-exact-target",
        )
        assert workspace_id is not None
        infrastructure = await repository.create_infrastructure_profile(
            session,
            create=_infrastructure_create(provider_id),
        )
        workspace_profile = await repository.create_workspace_runtime_profile(
            session,
            create=WorkspaceRuntimeProfileCreate(
                workspace_id=workspace_id,
                provider_id=provider_id,
                infrastructure_profile_id=infrastructure.id,
                display_name="Exact target Profile",
                description="Exact recreation target Profile",
                lifecycle=RuntimeProfileLifecycle.ACTIVE,
                policy={"schema_version": 1, "network_restriction": None},
                digest="b" * 64,
                actor_workspace_user_id=None,
            ),
        )
        integration = RDBLLMProviderIntegration(
            workspace_id=workspace_id,
            provider=LLMProvider.ANTHROPIC,
            name="recreation-exact-target-integration",
            encrypted_credentials="encrypted-test-value",
            config=None,
        )
        session.add(integration)
        await session.flush()
        runtime_ids: list[str] = []
        for index, (infrastructure_id, workspace_profile_id, source_trace) in enumerate(
            (
                (infrastructure.id, workspace_profile.id, {}),
                (
                    "unrelated-infrastructure",
                    "unrelated-workspace-profile",
                    {"collision": (f"{infrastructure.id}:{workspace_profile.id}")},
                ),
            )
        ):
            selection = make_test_model_selection_dict(
                integration_id=integration.id,
                provider=LLMProvider.ANTHROPIC,
                model_identifier=f"recreation-exact-target-{index}",
            )
            agent = RDBAgent(
                workspace_id=workspace_id,
                name=f"Recreation exact target {index}",
                model_selection=selection,
                lightweight_model_selection=selection,
            )
            session.add(agent)
            await session.flush()
            runtime = RDBAgentRuntime(
                workspace_id=workspace_id,
                agent_id=agent.id,
                runtime_provider_resource_id=provider_id,
            )
            session.add(runtime)
            await session.flush()
            runtime.configuration_sequence = 1
            document = RuntimeConfigurationDocument(
                schema_version=1,
                source_trace=source_trace,
                provider_id=provider_id,
                provider_capability_revision_id=None,
                infrastructure_profile_id=infrastructure_id,
                infrastructure_profile_version=1,
                workspace_runtime_profile_id=workspace_profile_id,
                workspace_runtime_profile_version=1,
                agent_selection_version=1,
                required_capabilities=(),
                missing_capabilities=(),
                resolved_configuration={"collision": source_trace},
            ).model_dump(mode="json")
            now = datetime.datetime.now(datetime.UTC)
            digest = str(index + 1) * 64
            session.add(
                RDBRuntimeConfigurationState(
                    runtime_id=runtime.id,
                    desired_sequence=1,
                    desired_status=RuntimeConfigurationStateStatus.READY,
                    desired_target_generation=0,
                    desired_digest=digest,
                    desired_document=document,
                    desired_reason_code=None,
                    provider_reported_digest=digest,
                    runner_reported_digest=digest,
                    provider_acknowledged_at=now,
                    runner_observed_at=now,
                    applied_sequence=1,
                    applied_target_generation=0,
                    applied_digest=digest,
                    applied_document=document,
                    applied_at=now,
                )
            )
            runtime_ids.append(runtime.id)
        await session.flush()

        infrastructure_items = await repository.list_recreation_target_items(
            session,
            target_kind=RuntimeRecreationTargetKind.INFRASTRUCTURE_PROFILE,
            target_id=infrastructure.id,
        )
        workspace_items = await repository.list_recreation_target_items(
            session,
            target_kind=RuntimeRecreationTargetKind.WORKSPACE_RUNTIME_PROFILE,
            target_id=workspace_profile.id,
        )

    assert [item[0] for item in infrastructure_items] == [runtime_ids[0]]
    assert [item[0] for item in workspace_items] == [runtime_ids[0]]


async def test_recreation_claim_respects_existing_global_concurrency(
    rdb_session_manager: SessionManager[AsyncSession],
) -> None:
    """A claim fills only the operation slots not already running."""
    repository = RuntimeProfileRepository()
    async with rdb_session_manager() as session:
        provider_id = await _create_provider(
            session,
            logical_id="recreation-concurrency-provider",
        )
        workspace_repository = WorkspaceRepository()
        workspace_result = await workspace_repository.create(
            session,
            WorkspaceCreate(
                name="Recreation concurrency",
                handle="recreation-concurrency",
            ),
        )
        assert isinstance(workspace_result, Success)
        workspace_id = await workspace_repository.resolve_id(
            session,
            "recreation-concurrency",
        )
        assert workspace_id is not None
        contract = await RuntimeProviderPolicyRepository().create_contract(
            session,
            create=RuntimeProviderContractRevisionCreate(
                provider_id=provider_id,
                digest="e" * 64,
                implementation_version="1",
                protocol_version="1",
                contract={},
                compatibility={},
            ),
        )
        infrastructure = await repository.create_infrastructure_profile(
            session,
            create=_infrastructure_create(provider_id),
        )
        workspace_profile = await repository.create_workspace_runtime_profile(
            session,
            create=WorkspaceRuntimeProfileCreate(
                workspace_id=workspace_id,
                provider_id=provider_id,
                infrastructure_profile_id=infrastructure.id,
                display_name="Concurrency Profile",
                description="Concurrency test Profile",
                lifecycle=RuntimeProfileLifecycle.ACTIVE,
                policy={"schema_version": 1, "network_restriction": None},
                digest="f" * 64,
                actor_workspace_user_id=None,
            ),
        )
        provider_target_version = await repository.get_recreation_target_version(
            session,
            target_kind=RuntimeRecreationTargetKind.PROVIDER,
            target_id=provider_id,
            for_share=True,
        )
        infrastructure_target_version = await repository.get_recreation_target_version(
            session,
            target_kind=RuntimeRecreationTargetKind.INFRASTRUCTURE_PROFILE,
            target_id=infrastructure.id,
            for_share=True,
        )
        workspace_target_version = await repository.get_recreation_target_version(
            session,
            target_kind=RuntimeRecreationTargetKind.WORKSPACE_RUNTIME_PROFILE,
            target_id=workspace_profile.id,
            for_share=True,
        )
        assert provider_target_version is not None
        assert provider_target_version.endswith(f":{contract.id}")
        assert infrastructure_target_version == str(infrastructure.version)
        assert workspace_target_version == str(workspace_profile.version)
        integration = RDBLLMProviderIntegration(
            workspace_id=workspace_id,
            provider=LLMProvider.ANTHROPIC,
            name="recreation-concurrency-integration",
            encrypted_credentials="encrypted-test-value",
            config=None,
        )
        session.add(integration)
        await session.flush()
        operation_items: list[tuple[str, int, str, int]] = []
        for index in range(3):
            selection = make_test_model_selection_dict(
                integration_id=integration.id,
                provider=LLMProvider.ANTHROPIC,
                model_identifier=f"recreation-concurrency-{index}",
            )
            agent = RDBAgent(
                workspace_id=workspace_id,
                name=f"Recreation concurrency {index}",
                model_selection=selection,
                lightweight_model_selection=selection,
            )
            session.add(agent)
            await session.flush()
            runtime = RDBAgentRuntime(
                workspace_id=workspace_id,
                agent_id=agent.id,
                runtime_provider_resource_id=provider_id,
            )
            session.add(runtime)
            await session.flush()
            document = RuntimeConfigurationDocument(
                schema_version=1,
                source_trace={},
                provider_id=provider_id,
                provider_capability_revision_id=contract.id,
                infrastructure_profile_id=infrastructure.id,
                infrastructure_profile_version=infrastructure.version,
                workspace_runtime_profile_id=workspace_profile.id,
                workspace_runtime_profile_version=workspace_profile.version,
                agent_selection_version=1,
                required_capabilities=(),
                missing_capabilities=(),
                resolved_configuration={},
            )
            state = await repository.overwrite_desired_configuration_state(
                session,
                write=RuntimeConfigurationDesiredStateWrite(
                    runtime_id=runtime.id,
                    status=RuntimeConfigurationStateStatus.READY,
                    target_generation=0,
                    digest=str(index + 1) * 64,
                    document=document,
                    reason_code=None,
                ),
            )
            assert state is not None
            operation_items.append(
                (runtime.id, state.desired.sequence, state.desired.digest or "", 0)
            )
        operation = await repository.create_recreation_operation(
            session,
            target_kind=RuntimeRecreationTargetKind.PROVIDER,
            target_id=provider_id,
            target_version=contract.id,
            concurrency_limit=2,
            actor_user_id=None,
            actor_workspace_user_id=None,
        )
        created_items = await repository.add_recreation_items(
            session,
            operation_id=operation.id,
            items=operation_items,
        )
        await session.execute(
            sa.update(RDBRuntimeRecreationOperationItem)
            .where(RDBRuntimeRecreationOperationItem.id == created_items[0].id)
            .values(status=RuntimeRecreationItemStatus.RUNNING)
        )
        await session.execute(
            sa.update(RDBRuntimeRecreationOperation)
            .where(RDBRuntimeRecreationOperation.id == operation.id)
            .values(
                status=RuntimeRecreationOperationStatus.RUNNING,
                pending_count=2,
                running_count=1,
            )
        )

        claimed = await repository.claim_recreation_items(
            session,
            operation_id=operation.id,
            limit=10,
        )

        assert len(claimed) == 1
        assert claimed[0].status is RuntimeRecreationItemStatus.RUNNING
        locked = await repository.lock_recreation_item(
            session,
            item_id=claimed[0].id,
            expected_attempt=claimed[0].attempt,
        )
        assert locked == claimed[0]
        rdb_operation = await session.get(RDBRuntimeRecreationOperation, operation.id)
        assert rdb_operation is not None
        assert rdb_operation.pending_count == 1
        assert rdb_operation.running_count == 2

        assert await repository.update_recreation_item_dispatch(
            session,
            item_id=claimed[0].id,
            expected_attempt=claimed[0].attempt,
            configuration_sequence=claimed[0].expected_configuration_sequence,
            configuration_digest=claimed[0].expected_configuration_digest,
            desired_generation=claimed[0].expected_desired_generation,
            dispatched_generation=1,
        )
        assert await repository.finish_recreation_item(
            session,
            item_id=claimed[0].id,
            expected_attempt=claimed[0].attempt,
            status=RuntimeRecreationItemStatus.SUCCEEDED,
            failure_code=None,
            failure_message=None,
        )
        assert await repository.finish_recreation_item(
            session,
            item_id=created_items[0].id,
            expected_attempt=0,
            status=RuntimeRecreationItemStatus.SKIPPED,
            failure_code="runtime_not_running",
            failure_message="Runtime is stopped.",
        )
        final_claim = await repository.claim_recreation_items(
            session,
            operation_id=operation.id,
            limit=10,
        )
        assert len(final_claim) == 1
        assert await repository.finish_recreation_item(
            session,
            item_id=final_claim[0].id,
            expected_attempt=final_claim[0].attempt,
            status=RuntimeRecreationItemStatus.FAILED,
            failure_code="provider_failed",
            failure_message="Provider failed.",
        )
        completed = await repository.get_recreation_operation(
            session,
            operation_id=operation.id,
        )
        assert completed is not None
        assert (
            completed.status is RuntimeRecreationOperationStatus.COMPLETED_WITH_FAILURES
        )
        assert completed.pending_count == 0
        assert completed.running_count == 0
        assert completed.succeeded_count == 1
        assert completed.skipped_count == 1
        assert completed.failed_count == 1
