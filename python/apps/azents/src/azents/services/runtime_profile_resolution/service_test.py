"""Exact Runtime Profile resolution integration tests."""

import asyncio
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager, suppress
from unittest.mock import AsyncMock

import sqlalchemy as sa
from azcommon.result import Success
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

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
)
from azents.rdb.models.agent import RDBAgent
from azents.rdb.models.agent_runtime import RDBAgentRuntime
from azents.rdb.models.llm_provider_integration import RDBLLMProviderIntegration
from azents.rdb.models.runtime_profile import RDBRuntimeConfigurationRevision
from azents.rdb.models.runtime_provider import RDBRuntimeProvider
from azents.rdb.session import SessionManager
from azents.repos.agent import AgentRepository
from azents.repos.agent_runtime import AgentRuntimeRepository
from azents.repos.agent_runtime.data import AgentRuntime
from azents.repos.runtime_profile.data import (
    RuntimeInfrastructureProfileCreate,
    WorkspaceRuntimeProfileCreate,
)
from azents.repos.runtime_profile.repository import RuntimeProfileRepository
from azents.repos.runtime_provider.data import RuntimeProviderCreate
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
from azents.testing.model_selection import make_test_model_selection_dict

from .data import RuntimeProfileResolutionResult, RuntimeProfileResolutionUnavailable
from .service import RuntimeProfileResolutionService


class _SignalingAgentRuntimeRepository(AgentRuntimeRepository):
    """Signal when resolution reaches the existing Runtime lock."""

    def __init__(self, lock_attempted: asyncio.Event) -> None:
        self.lock_attempted = lock_attempted

    async def get_by_agent_id_for_update(
        self,
        session: AsyncSession,
        agent_id: str,
    ) -> AgentRuntime | None:
        self.lock_attempted.set()
        return await super().get_by_agent_id_for_update(session, agent_id)


def _contract_payload() -> dict[str, object]:
    return {
        "schema_version": 1,
        "implementation_key": "kubernetes",
        "implementation_version": "0.1.0",
        "protocol_version": "agent-runtime-provider-kubernetes-v1",
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
            protocol_version="agent-runtime-provider-kubernetes-v1",
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


async def test_resolution_avoids_lifecycle_configuration_fk_deadlock(
    rdb_engine: AsyncEngine,
    latest_db_schema: None,
) -> None:
    """Resolution waits on Runtime before locking revision FK source rows."""
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
            handle="runtime-resolution-lifecycle-lock-order",
        )

    service = _service(independent_session_manager)
    ready = await service.ensure_for_agent(agent_id)
    lock_attempted = asyncio.Event()
    service.runtime_repository = _SignalingAgentRuntimeRepository(lock_attempted)
    resolution_task: asyncio.Task[RuntimeProfileResolutionResult] | None = None

    try:
        async with independent_session_manager() as lifecycle_session:
            locked_runtime = await lifecycle_session.scalar(
                sa.select(RDBAgentRuntime)
                .where(RDBAgentRuntime.id == ready.runtime.id)
                .with_for_update()
            )
            assert locked_runtime is not None

            resolution_task = asyncio.create_task(service.ensure_for_agent(agent_id))
            await asyncio.wait_for(lock_attempted.wait(), timeout=5)
            await asyncio.sleep(0)
            assert not resolution_task.done()

            revision = ready.desired_revision
            lifecycle_session.add(
                RDBRuntimeConfigurationRevision(
                    runtime_id=revision.runtime_id,
                    provider_id=revision.provider_id,
                    provider_capability_revision_id=(
                        revision.provider_capability_revision_id
                    ),
                    infrastructure_profile_id=revision.infrastructure_profile_id,
                    infrastructure_profile_version=(
                        revision.infrastructure_profile_version
                    ),
                    workspace_runtime_profile_id=(
                        revision.workspace_runtime_profile_id
                    ),
                    workspace_runtime_profile_version=(
                        revision.workspace_runtime_profile_version
                    ),
                    agent_selection_version=revision.agent_selection_version,
                    resolution_status=revision.resolution_status,
                    required_capabilities=list(revision.required_capabilities),
                    missing_capabilities=list(revision.missing_capabilities),
                    source_trace=revision.source_trace,
                    digest=revision.digest,
                    target_desired_generation=(revision.target_desired_generation + 1),
                    reason_code=revision.reason_code,
                    resolved_configuration=revision.resolved_configuration,
                )
            )
            await asyncio.wait_for(lifecycle_session.flush(), timeout=5)

        repeated = await asyncio.wait_for(resolution_task, timeout=5)
        assert repeated.runtime.id == ready.runtime.id
    finally:
        if resolution_task is not None and not resolution_task.done():
            resolution_task.cancel()
            with suppress(asyncio.CancelledError):
                await resolution_task


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
