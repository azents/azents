"""Exact Runtime Profile resolution integration tests."""

import asyncio
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock

import sqlalchemy as sa
from azcommon.result import Success
from azcommon.uuid import uuid7
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from azents.core.enums import (
    LLMProvider,
    RuntimeProviderAvailabilityMode,
    RuntimeProviderBindingOrigin,
    RuntimeProviderKind,
    RuntimeProviderLifecycleState,
    RuntimeProviderRegistrationMethod,
    RuntimeProviderScope,
    SessionWorkingFolderCleanupStatus,
)
from azents.core.runtime_profile import (
    RuntimeConfigurationResolutionStatus,
    RuntimeInfrastructureProfileKind,
    RuntimeProfileLifecycle,
    RuntimeReconcileSourceKind,
)
from azents.rdb.models.agent import RDBAgent
from azents.rdb.models.agent_runtime import RDBAgentRuntime
from azents.rdb.models.llm_provider_integration import RDBLLMProviderIntegration
from azents.rdb.models.runtime_profile import (
    RDBRuntimeConfigurationReconcileTask,
    RDBRuntimeConfigurationRevision,
)
from azents.rdb.models.runtime_provider import RDBRuntimeProvider
from azents.rdb.models.session_agent_context import RDBSessionAgentContext
from azents.rdb.session import SessionManager
from azents.repos.agent import AgentRepository
from azents.repos.agent.data import Agent
from azents.repos.agent_runtime import AgentRuntimeRepository
from azents.repos.agent_runtime.data import AgentRuntime
from azents.repos.runtime_profile.data import (
    RuntimeInfrastructureProfile,
    RuntimeInfrastructureProfileCreate,
    WorkspaceRuntimeProfile,
    WorkspaceRuntimeProfileCreate,
)
from azents.repos.runtime_profile.repository import RuntimeProfileRepository
from azents.repos.runtime_provider.data import RuntimeProvider, RuntimeProviderCreate
from azents.repos.runtime_provider.repository import RuntimeProviderRepository
from azents.repos.runtime_provider_control.repository import (
    RuntimeProviderControlRepository,
)
from azents.repos.runtime_provider_policy.data import (
    RuntimeProviderContractRevisionCreate,
)
from azents.repos.runtime_provider_policy.repository import (
    RuntimeProviderPolicyRepository,
)
from azents.repos.workspace import WorkspaceRepository
from azents.repos.workspace.data import WorkspaceCreate
from azents.services.runtime_profile_reconciliation.service import (
    RuntimeProfileReconciliationService,
)
from azents.testing.model_selection import make_test_model_selection_dict

from .data import RuntimeProfileResolutionUnavailable
from .service import RuntimeProfileResolutionService


class _LockFreeAgentRepository(AgentRepository):
    """Reject the legacy selection source lock during resolution."""

    async def get_runtime_selection_input_for_update(
        self,
        session: AsyncSession,
        agent_id: str,
    ) -> Agent | None:
        del session, agent_id
        raise AssertionError("Resolution must not lock the Agent selection row.")


class _LockFreeRuntimeProfileRepository(RuntimeProfileRepository):
    """Reject source profile locks during resolution."""

    def __init__(
        self,
        *,
        source_read_count: list[int],
    ) -> None:
        self.source_read_count = source_read_count

    async def get_workspace_runtime_profile(
        self,
        session: AsyncSession,
        *,
        workspace_id: str,
        profile_id: str,
        for_update: bool,
    ) -> WorkspaceRuntimeProfile | None:
        assert not for_update
        self.source_read_count[0] += 1
        return await super().get_workspace_runtime_profile(
            session,
            workspace_id=workspace_id,
            profile_id=profile_id,
            for_update=for_update,
        )

    async def get_infrastructure_profile(
        self,
        session: AsyncSession,
        *,
        profile_id: str,
        for_update: bool,
    ) -> RuntimeInfrastructureProfile | None:
        assert not for_update
        self.source_read_count[0] += 1
        return await super().get_infrastructure_profile(
            session,
            profile_id=profile_id,
            for_update=for_update,
        )


class _LockFreeRuntimeProviderRepository(RuntimeProviderRepository):
    """Reject Provider source locks during resolution."""

    async def get_by_id(
        self,
        session: AsyncSession,
        *,
        provider_id: str,
        for_update: bool,
    ) -> RuntimeProvider | None:
        assert not for_update
        return await super().get_by_id(
            session,
            provider_id=provider_id,
            for_update=for_update,
        )


class _SelectionRacingAgentRuntimeRepository(AgentRuntimeRepository):
    """Commit one replacement selection immediately before the first pointer CAS."""

    def __init__(
        self,
        session_manager: SessionManager[AsyncSession],
        replacement_profile_id: str,
    ) -> None:
        self.session_manager = session_manager
        self.replacement_profile_id = replacement_profile_id
        self.raced = False

    async def attach_desired_configuration_revision(
        self,
        session: AsyncSession,
        *,
        runtime_id: str,
        expected_revision_id: str | None,
        expected_desired_generation: int,
        agent_id: str,
        workspace_id: str,
        agent_selection_version: int,
        provider_logical_id: str,
        provider_resource_id: str,
        provider_admin_version: int,
        provider_capability_revision_id: str | None,
        binding_origin: RuntimeProviderBindingOrigin,
        binding_evidence: dict[str, object],
        infrastructure_profile_id: str,
        infrastructure_profile_version: int,
        workspace_runtime_profile_id: str,
        workspace_runtime_profile_version: int,
        configuration_revision_id: str,
    ) -> AgentRuntime | None:
        if not self.raced:
            self.raced = True
            async with self.session_manager() as race_session:
                await race_session.execute(
                    sa.update(RDBAgent)
                    .where(RDBAgent.id == agent_id)
                    .values(
                        runtime_profile_id=self.replacement_profile_id,
                        runtime_profile_selection_version=(
                            RDBAgent.runtime_profile_selection_version + 1
                        ),
                    )
                )
        return await super().attach_desired_configuration_revision(
            session,
            runtime_id=runtime_id,
            expected_revision_id=expected_revision_id,
            expected_desired_generation=expected_desired_generation,
            agent_id=agent_id,
            workspace_id=workspace_id,
            agent_selection_version=agent_selection_version,
            provider_logical_id=provider_logical_id,
            provider_resource_id=provider_resource_id,
            provider_admin_version=provider_admin_version,
            provider_capability_revision_id=provider_capability_revision_id,
            binding_origin=binding_origin,
            binding_evidence=binding_evidence,
            infrastructure_profile_id=infrastructure_profile_id,
            infrastructure_profile_version=infrastructure_profile_version,
            workspace_runtime_profile_id=workspace_runtime_profile_id,
            workspace_runtime_profile_version=workspace_runtime_profile_version,
            configuration_revision_id=configuration_revision_id,
        )


def _contract_payload() -> dict[str, object]:
    return {
        "schema_version": 1,
        "implementation_key": "kubernetes",
        "implementation_version": "0.1.0",
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


async def _seed_selected_agent(
    session: AsyncSession,
    *,
    handle: str,
) -> tuple[str, str]:
    workspace_repository = WorkspaceRepository()
    workspace_result = await workspace_repository.create(
        session,
        WorkspaceCreate(name="Runtime resolution", handle=handle),
    )
    assert isinstance(workspace_result, Success)
    workspace_id = await workspace_repository.resolve_id(session, handle)
    assert workspace_id is not None

    provider = await RuntimeProviderRepository().create(
        session,
        RuntimeProviderCreate(
            provider_id=f"{handle}-provider",
            scope=RuntimeProviderScope.SYSTEM,
            workspace_id=None,
            kind=RuntimeProviderKind.KUBERNETES,
            display_name="Runtime resolution Provider",
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
            implementation_version="0.1.0",
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
            display_name="Standard Pod",
            description="Resolution test Pod Profile",
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
            digest="b" * 64,
            actor_user_id=None,
        ),
    )
    workspace_profile = await profile_repository.create_workspace_runtime_profile(
        session,
        create=WorkspaceRuntimeProfileCreate(
            workspace_id=workspace_id,
            provider_id=provider.id,
            infrastructure_profile_id=infrastructure.id,
            display_name="Workspace Standard",
            description="Resolution test Workspace Profile",
            lifecycle=RuntimeProfileLifecycle.ACTIVE,
            policy={
                "schema_version": 1,
                "network_restriction": {
                    "allowed_cidrs": ["10.10.0.0/16"],
                    "denied_cidrs": ["10.10.1.0/24"],
                },
            },
            digest="c" * 64,
            actor_workspace_user_id=None,
        ),
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
        name="Runtime resolution Agent",
        model_selection=selection,
        lightweight_model_selection=selection,
        runtime_profile_id=workspace_profile.id,
    )
    session.add(agent)
    await session.flush()
    return agent.id, provider.id


def _service(
    session_manager: SessionManager[AsyncSession],
) -> RuntimeProfileResolutionService:
    control_repository = RuntimeProviderControlRepository()
    control_repository.has_connected_connection = AsyncMock(return_value=True)
    return RuntimeProfileResolutionService(
        session_manager=session_manager,
        agent_repository=AgentRepository(),
        runtime_repository=AgentRuntimeRepository(),
        profile_repository=RuntimeProfileRepository(),
        provider_repository=RuntimeProviderRepository(),
        control_repository=control_repository,
        provider_policy_repository=RuntimeProviderPolicyRepository(),
    )


async def _cleanup_independent_resolution_fixture(
    session: AsyncSession,
    *,
    agent_id: str,
) -> None:
    """Delete rows committed by an independent-session integration test."""
    runtime_ids = sa.select(RDBAgentRuntime.id).where(
        RDBAgentRuntime.agent_id == agent_id
    )
    await session.execute(
        sa.delete(RDBSessionAgentContext).where(
            RDBSessionAgentContext.agent_runtime_id.in_(runtime_ids)
        )
    )
    await session.execute(
        sa.update(RDBAgentRuntime)
        .where(RDBAgentRuntime.agent_id == agent_id)
        .values(
            desired_runtime_configuration_revision_id=None,
            applied_runtime_configuration_revision_id=None,
        )
    )
    await session.execute(
        sa.delete(RDBRuntimeConfigurationRevision).where(
            RDBRuntimeConfigurationRevision.runtime_id.in_(runtime_ids)
        )
    )
    await session.execute(
        sa.delete(RDBAgentRuntime).where(RDBAgentRuntime.agent_id == agent_id)
    )
    await session.execute(
        sa.delete(RDBRuntimeConfigurationReconcileTask).where(
            RDBRuntimeConfigurationReconcileTask.source_type
            == RuntimeReconcileSourceKind.AGENT_SELECTION,
            RDBRuntimeConfigurationReconcileTask.source_id == agent_id,
        )
    )
    await session.execute(sa.delete(RDBAgent).where(RDBAgent.id == agent_id))


async def test_resolution_creates_ready_revision_and_reuses_same_digest(
    rdb_session_manager: SessionManager[AsyncSession],
) -> None:
    async with rdb_session_manager() as session:
        agent_id, _ = await _seed_selected_agent(
            session,
            handle="runtime-resolution-ready",
        )

    service = _service(rdb_session_manager)
    first = await service.ensure_for_agent(agent_id)
    repeated = await service.ensure_for_agent(agent_id)

    assert first.desired_revision.resolution_status is (
        RuntimeConfigurationResolutionStatus.READY
    )
    assert first.desired_revision.resolved_configuration is not None
    effective = first.desired_revision.resolved_configuration["effective_profile"]
    assert effective["network_policy"] == {
        "allowed_cidrs": ["10.10.0.0/16"],
        "denied_cidrs": ["10.10.1.0/24"],
    }
    assert repeated.desired_revision.id == first.desired_revision.id
    assert repeated.runtime.desired_runtime_configuration_revision_id == (
        first.desired_revision.id
    )


async def test_resolution_reads_sources_without_row_locks(
    rdb_session_manager: SessionManager[AsyncSession],
) -> None:
    """Resolution reads each mutable source as a lock-free snapshot."""
    async with rdb_session_manager() as session:
        agent_id, _ = await _seed_selected_agent(
            session,
            handle="runtime-resolution-lock-free-sources",
        )

    source_read_count = [0]
    service = _service(rdb_session_manager)
    service.agent_repository = _LockFreeAgentRepository()
    service.profile_repository = _LockFreeRuntimeProfileRepository(
        source_read_count=source_read_count
    )
    service.provider_repository = _LockFreeRuntimeProviderRepository()

    resolution = await service.ensure_for_agent(agent_id)

    assert resolution.desired_revision.resolution_status is (
        RuntimeConfigurationResolutionStatus.READY
    )
    assert source_read_count == [2]


async def test_runtime_resolution_lock_allows_session_context_fk_reference(
    rdb_engine: AsyncEngine,
    latest_db_schema: None,
) -> None:
    """Runtime binding locks do not block Session context FK references."""
    del latest_db_schema

    @asynccontextmanager
    async def independent_session_manager() -> AsyncGenerator[AsyncSession]:
        async with AsyncSession(rdb_engine, expire_on_commit=False) as session:
            try:
                yield session
            except Exception:
                await session.rollback()
                raise
            else:
                await session.commit()

    async with independent_session_manager() as session:
        agent_id, _ = await _seed_selected_agent(
            session,
            handle="runtime-resolution-session-context-fk",
        )

    service = _service(independent_session_manager)
    ready = await service.ensure_for_agent(agent_id)
    runtime_repository = AgentRuntimeRepository()

    async with independent_session_manager() as lock_session:
        locked = await runtime_repository.get_by_agent_id_for_update(
            lock_session,
            agent_id,
        )
        assert locked is not None

        async with independent_session_manager() as context_session:
            context = RDBSessionAgentContext(
                agent_id=agent_id,
                workspace_id=ready.runtime.workspace_id,
                agent_runtime_id=ready.runtime.id,
                working_folder_path="/workspace/agent/.azents/sessions/test",
                working_folder_cleanup_status=(
                    SessionWorkingFolderCleanupStatus.NOT_ATTEMPTED
                ),
                working_folder_cleanup_summary=None,
                working_folder_cleanup_completed_at=None,
                root_session_agent_id=None,
            )
            context.id = uuid7().hex
            context_session.add(context)
            await asyncio.wait_for(context_session.flush(), timeout=5)
    async with independent_session_manager() as session:
        await _cleanup_independent_resolution_fixture(session, agent_id=agent_id)


async def test_runtime_reconciliation_lock_allows_session_context_fk_reference(
    rdb_engine: AsyncEngine,
    latest_db_schema: None,
) -> None:
    """Runtime reconciliation locks do not block Session context FK references."""
    del latest_db_schema

    @asynccontextmanager
    async def independent_session_manager() -> AsyncGenerator[AsyncSession]:
        async with AsyncSession(rdb_engine, expire_on_commit=False) as session:
            try:
                yield session
            except Exception:
                await session.rollback()
                raise
            else:
                await session.commit()

    async with independent_session_manager() as session:
        agent_id, _ = await _seed_selected_agent(
            session,
            handle="runtime-reconciliation-session-context-fk",
        )

    service = _service(independent_session_manager)
    ready = await service.ensure_for_agent(agent_id)
    runtime_repository = AgentRuntimeRepository()

    async with independent_session_manager() as lock_session:
        locked = await runtime_repository.get_by_id_for_update(
            lock_session,
            ready.runtime.id,
        )
        assert locked is not None

        async with independent_session_manager() as context_session:
            context = RDBSessionAgentContext(
                agent_id=agent_id,
                workspace_id=ready.runtime.workspace_id,
                agent_runtime_id=ready.runtime.id,
                working_folder_path="/workspace/agent/.azents/sessions/reconciliation",
                working_folder_cleanup_status=(
                    SessionWorkingFolderCleanupStatus.NOT_ATTEMPTED
                ),
                working_folder_cleanup_summary=None,
                working_folder_cleanup_completed_at=None,
                root_session_agent_id=None,
            )
            context.id = uuid7().hex
            context_session.add(context)
            await asyncio.wait_for(context_session.flush(), timeout=5)
    async with independent_session_manager() as session:
        await _cleanup_independent_resolution_fixture(session, agent_id=agent_id)


async def test_resolution_selection_cas_loss_retries_and_reconcile_converges(
    rdb_engine: AsyncEngine,
    latest_db_schema: None,
) -> None:
    """A stale selection snapshot cannot overwrite the current desired pointer."""
    del latest_db_schema

    @asynccontextmanager
    async def independent_session_manager() -> AsyncGenerator[AsyncSession]:
        async with AsyncSession(rdb_engine, expire_on_commit=False) as session:
            try:
                yield session
            except Exception:
                await session.rollback()
                raise
            else:
                await session.commit()

    agent_id: str | None = None
    try:
        async with independent_session_manager() as session:
            agent_id, _ = await _seed_selected_agent(
                session,
                handle="runtime-resolution-selection-cas",
            )
            agent = await AgentRepository().get_by_id(session, agent_id)
            assert agent is not None
            profile_repository = RuntimeProfileRepository()
            selected = await profile_repository.get_workspace_runtime_profile(
                session,
                workspace_id=agent.workspace_id,
                profile_id=agent.runtime_profile_id or "",
                for_update=False,
            )
            assert selected is not None
            replacement = await profile_repository.create_workspace_runtime_profile(
                session,
                create=WorkspaceRuntimeProfileCreate(
                    workspace_id=selected.workspace_id,
                    provider_id=selected.provider_id,
                    infrastructure_profile_id=selected.infrastructure_profile_id,
                    display_name="Replacement Runtime Profile",
                    description="Selection CAS replacement Profile",
                    lifecycle=selected.lifecycle,
                    policy=selected.policy,
                    digest="d" * 64,
                    actor_workspace_user_id=None,
                ),
            )

        ready = await _service(independent_session_manager).ensure_for_agent(agent_id)
        service = _service(independent_session_manager)
        racing_repository = _SelectionRacingAgentRuntimeRepository(
            independent_session_manager,
            replacement.id,
        )
        service.runtime_repository = racing_repository

        resolution = await service.ensure_for_agent(agent_id)

        assert racing_repository.raced
        assert resolution.desired_revision.id != ready.desired_revision.id
        assert (
            resolution.desired_revision.workspace_runtime_profile_id == replacement.id
        )
        assert resolution.desired_revision.agent_selection_version == 2

        async with independent_session_manager() as session:
            task = await session.scalar(
                sa.select(RDBRuntimeConfigurationReconcileTask).where(
                    RDBRuntimeConfigurationReconcileTask.source_type
                    == RuntimeReconcileSourceKind.AGENT_SELECTION,
                    RDBRuntimeConfigurationReconcileTask.source_id == agent_id,
                    RDBRuntimeConfigurationReconcileTask.source_version == "2",
                )
            )
            assert task is not None

        reconciliation = RuntimeProfileReconciliationService(
            session_manager=independent_session_manager,
            profile_repository=RuntimeProfileRepository(),
            resolution_service=_service(independent_session_manager),
        )
        outcome = await reconciliation.reconcile_once(task_limit=1, page_size=1)

        assert outcome.reconciled_agents == 1
        async with independent_session_manager() as session:
            runtime = await AgentRuntimeRepository().get_by_agent_id(session, agent_id)
            assert runtime is not None
            desired = await RuntimeProfileRepository().get_configuration_revision(
                session,
                revision_id=runtime.desired_runtime_configuration_revision_id or "",
            )
            assert desired is not None
            assert desired.workspace_runtime_profile_id == replacement.id
    finally:
        if agent_id is not None:
            async with independent_session_manager() as session:
                await _cleanup_independent_resolution_fixture(
                    session,
                    agent_id=agent_id,
                )


async def test_resolution_records_blocked_revision_without_losing_prior_desired(
    rdb_session_manager: SessionManager[AsyncSession],
) -> None:
    async with rdb_session_manager() as session:
        agent_id, provider_id = await _seed_selected_agent(
            session,
            handle="runtime-resolution-blocked",
        )

    service = _service(rdb_session_manager)
    ready = await service.ensure_for_agent(agent_id)
    async with rdb_session_manager() as session:
        await session.execute(
            sa.update(RDBRuntimeProvider)
            .where(RDBRuntimeProvider.id == provider_id)
            .values(enabled=False)
        )

    blocked = await service.ensure_for_agent(agent_id)

    assert blocked.desired_revision.id != ready.desired_revision.id
    assert blocked.desired_revision.resolution_status is (
        RuntimeConfigurationResolutionStatus.BLOCKED
    )
    assert blocked.desired_revision.reason_code == "provider_disabled"
    assert blocked.desired_revision.resolved_configuration is None
    assert blocked.runtime.applied_runtime_configuration_revision_id is None


async def test_resolution_requires_explicit_agent_profile(
    rdb_session_manager: SessionManager[AsyncSession],
) -> None:
    async with rdb_session_manager() as session:
        agent_id, _ = await _seed_selected_agent(
            session,
            handle="runtime-resolution-required",
        )
        await session.execute(
            sa.update(RDBAgent)
            .where(RDBAgent.id == agent_id)
            .values(runtime_profile_id=None)
        )

    service = _service(rdb_session_manager)
    try:
        await service.ensure_for_agent(agent_id)
    except RuntimeProfileResolutionUnavailable as error:
        assert error.code == "runtime_profile_required"
    else:
        raise AssertionError("Missing Runtime Profile selection was accepted.")
