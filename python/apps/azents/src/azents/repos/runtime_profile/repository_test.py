"""Runtime Profile persistence and durable claim tests."""

import datetime

import pytest
import sqlalchemy as sa
from azcommon.result import Success
from azents_runtime_control.runtime_configuration import RuntimeConfigurationEvidence
from sqlalchemy.ext.asyncio import AsyncSession

from azents.core.enums import (
    LLMProvider,
    RuntimeDesiredState,
    RuntimeLifecycleCommandType,
    RuntimeProviderAvailabilityMode,
    RuntimeProviderKind,
    RuntimeProviderLifecycleState,
    RuntimeProviderRegistrationMethod,
    RuntimeProviderScope,
    RuntimeRunnerState,
)
from azents.core.runtime_profile import (
    RuntimeConfigurationResolutionStatus,
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
from azents.repos.workspace.data import WorkspaceCreate
from azents.testing.model_selection import make_test_model_selection_dict

from .data import (
    RuntimeConfigurationRevisionCreate,
    RuntimeInfrastructureProfileCreate,
    RuntimeInfrastructureProfileReplace,
    WorkspaceRuntimeProfileCreate,
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
    """Applied configuration advances only after exact Provider and Runner evidence."""
    repository = RuntimeProfileRepository()
    runtime_repository = AgentRuntimeRepository()
    async with rdb_session_manager() as session:
        provider_id = await _create_provider(
            session,
            logical_id="configuration-evidence-provider",
        )
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
        workspace_repository = WorkspaceRepository()
        workspace_result = await workspace_repository.create(
            session,
            WorkspaceCreate(
                name="Configuration evidence",
                handle="configuration-evidence",
            ),
        )
        assert isinstance(workspace_result, Success)
        workspace_id = await workspace_repository.resolve_id(
            session,
            "configuration-evidence",
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
                display_name="Evidence Profile",
                description="Configuration evidence Profile",
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
            encrypted_credentials="encrypted-test-value",
            config=None,
        )
        session.add(integration)
        await session.flush()
        selection = make_test_model_selection_dict(
            integration_id=integration.id,
            provider=LLMProvider.ANTHROPIC,
            model_identifier="configuration-evidence-model",
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
        revision = await repository.create_configuration_revision(
            session,
            create=RuntimeConfigurationRevisionCreate(
                runtime_id=runtime.id,
                provider_id=provider_id,
                provider_capability_revision_id=contract.id,
                infrastructure_profile_id=infrastructure.id,
                infrastructure_profile_version=infrastructure.version,
                workspace_runtime_profile_id=workspace_profile.id,
                workspace_runtime_profile_version=workspace_profile.version,
                agent_selection_version=1,
                resolution_status=RuntimeConfigurationResolutionStatus.READY,
                reason_code=None,
                required_capabilities=(),
                missing_capabilities=(),
                resolved_configuration={"schema_version": 1},
                source_trace={},
                digest="d" * 64,
                target_desired_generation=runtime.desired_generation,
            ),
        )
        blocked_revision = await repository.create_configuration_revision(
            session,
            create=RuntimeConfigurationRevisionCreate(
                runtime_id=runtime.id,
                provider_id=provider_id,
                provider_capability_revision_id=contract.id,
                infrastructure_profile_id=infrastructure.id,
                infrastructure_profile_version=infrastructure.version,
                workspace_runtime_profile_id=workspace_profile.id,
                workspace_runtime_profile_version=workspace_profile.version,
                agent_selection_version=2,
                resolution_status=RuntimeConfigurationResolutionStatus.BLOCKED,
                reason_code="MISSING_CAPABILITY",
                required_capabilities=("network_policy",),
                missing_capabilities=("network_policy",),
                resolved_configuration=None,
                source_trace={},
                digest="c" * 64,
                target_desired_generation=runtime.desired_generation,
            ),
        )
        await session.execute(
            sa.update(RDBAgentRuntime)
            .where(RDBAgentRuntime.id == runtime.id)
            .values(
                runtime_provider_resource_id=provider_id,
                desired_runtime_configuration_revision_id=revision.id,
            )
        )
        evidence = RuntimeConfigurationEvidence(
            revision_id=revision.id,
            digest=revision.digest,
            desired_generation=runtime.desired_generation,
        )
        stale_evidence = RuntimeConfigurationEvidence(
            revision_id=revision.id,
            digest="0" * 64,
            desired_generation=runtime.desired_generation,
        )

        assert not await repository.configuration_evidence_matches_current(
            session,
            runtime_id=runtime.id,
            provider_id=provider_id,
            evidence=stale_evidence,
        )
        assert await repository.configuration_evidence_matches_current(
            session,
            runtime_id=runtime.id,
            provider_id=provider_id,
            evidence=evidence,
        )
        await session.execute(
            sa.update(RDBAgentRuntime)
            .where(RDBAgentRuntime.id == runtime.id)
            .values(
                desired_runtime_configuration_revision_id=blocked_revision.id,
            )
        )
        assert not await repository.configuration_evidence_matches_current(
            session,
            runtime_id=runtime.id,
            provider_id=provider_id,
            evidence=evidence,
        )
        await session.execute(
            sa.update(RDBAgentRuntime)
            .where(RDBAgentRuntime.id == runtime.id)
            .values(
                desired_runtime_configuration_revision_id=revision.id,
            )
        )
        acknowledged_at = datetime.datetime(2026, 7, 30, tzinfo=datetime.UTC)
        provider_revision = await repository.record_provider_configuration_evidence(
            session,
            runtime_id=runtime.id,
            provider_id=provider_id,
            evidence=evidence,
            acknowledged_at=acknowledged_at,
        )
        provider_runtime = await runtime_repository.get_by_id(session, runtime.id)
        assert provider_revision is not None
        assert provider_revision.provider_reported_digest == evidence.digest
        assert provider_revision.runner_reported_digest is None
        assert provider_revision.provider_acknowledged_at == acknowledged_at
        assert provider_runtime is not None
        assert provider_runtime.applied_runtime_configuration_revision_id is None

        observed_at = datetime.datetime(2026, 7, 30, 0, 0, 1, tzinfo=datetime.UTC)
        persisted_revision = await repository.record_runner_configuration_evidence(
            session,
            runtime_id=runtime.id,
            provider_id=provider_id,
            evidence=evidence,
            observed_at=observed_at,
        )
        persisted_runtime = await runtime_repository.get_by_id(session, runtime.id)

        assert persisted_revision is not None
        assert persisted_revision.provider_reported_digest == evidence.digest
        assert persisted_revision.runner_reported_digest == evidence.digest
        assert persisted_revision.provider_acknowledged_at == acknowledged_at
        assert persisted_revision.runtime_observed_at == observed_at
        assert persisted_runtime is not None
        assert (
            persisted_runtime.applied_runtime_configuration_revision_id == revision.id
        )
        runtime_with_workspace = await runtime_repository.record_runner_state(
            session,
            runtime.id,
            RuntimeRunnerState.READY,
            runner_generation=1,
            expected_desired_generation=runtime.desired_generation,
            workspace_path="/runtime/old-home",
        )
        assert runtime_with_workspace is not None

        command = await runtime_repository.set_desired_state_if_ready(
            session,
            runtime.id,
            RuntimeLifecycleCommandType.RESTART,
            RuntimeDesiredState.RUNNING,
            expected_configuration_revision_id=revision.id,
        )

        assert command is not None
        assert command.desired_generation == runtime.desired_generation + 1
        assert command.runtime.workspace_path is None
        assert command.runtime.desired_runtime_configuration_revision_id != revision.id
        next_revision_id = command.runtime.desired_runtime_configuration_revision_id
        assert next_revision_id is not None
        next_revision = await repository.get_configuration_revision(
            session,
            revision_id=next_revision_id,
        )
        assert next_revision is not None
        assert next_revision.digest == revision.digest
        assert next_revision.target_desired_generation == command.desired_generation
        assert next_revision.provider_reported_digest is None
        assert next_revision.runner_reported_digest is None
        assert (
            await runtime_repository.set_desired_state_if_ready(
                session,
                runtime.id,
                RuntimeLifecycleCommandType.RESTART,
                RuntimeDesiredState.RUNNING,
                expected_configuration_revision_id=revision.id,
            )
            is None
        )


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
        operation_items: list[tuple[str, str]] = []
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
            )
            session.add(runtime)
            await session.flush()
            configuration = await repository.create_configuration_revision(
                session,
                create=RuntimeConfigurationRevisionCreate(
                    runtime_id=runtime.id,
                    provider_id=provider_id,
                    provider_capability_revision_id=contract.id,
                    infrastructure_profile_id=infrastructure.id,
                    infrastructure_profile_version=infrastructure.version,
                    workspace_runtime_profile_id=workspace_profile.id,
                    workspace_runtime_profile_version=workspace_profile.version,
                    agent_selection_version=1,
                    resolution_status=RuntimeConfigurationResolutionStatus.READY,
                    reason_code=None,
                    required_capabilities=(),
                    missing_capabilities=(),
                    resolved_configuration={},
                    source_trace={},
                    digest=str(index + 1) * 64,
                    target_desired_generation=0,
                ),
            )
            operation_items.append((runtime.id, configuration.id))
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
            configuration_revision_id=claimed[0].expected_configuration_revision_id,
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
