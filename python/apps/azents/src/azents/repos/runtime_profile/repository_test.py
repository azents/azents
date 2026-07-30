"""Runtime Profile persistence and durable claim tests."""

import datetime

import pytest
import sqlalchemy as sa
from azcommon.result import Success
from sqlalchemy.ext.asyncio import AsyncSession

from azents.core.enums import (
    LLMProvider,
    RuntimeProviderAvailabilityMode,
    RuntimeProviderKind,
    RuntimeProviderLifecycleState,
    RuntimeProviderRegistrationMethod,
    RuntimeProviderScope,
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
        rdb_operation = await session.get(RDBRuntimeRecreationOperation, operation.id)
        assert rdb_operation is not None
        assert rdb_operation.pending_count == 1
        assert rdb_operation.running_count == 2
