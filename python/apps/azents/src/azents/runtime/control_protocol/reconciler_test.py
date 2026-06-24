"""Runtime lifecycle reconciler tests."""

import datetime

import sqlalchemy as sa
from azcommon.result import Success
from sqlalchemy.ext.asyncio import AsyncSession

from azents.core.enums import (
    LLMProvider,
    RuntimeDesiredState,
    RuntimeLifecycleCommandType,
    RuntimeProviderConnectionState,
)
from azents.rdb.models.agent import RDBAgent
from azents.rdb.models.agent_runtime import RDBAgentRuntime
from azents.rdb.models.llm_provider_integration import RDBLLMProviderIntegration
from azents.rdb.session import SessionManager
from azents.repos.agent_runtime import AgentRuntimeRepository
from azents.repos.workspace import WorkspaceRepository
from azents.repos.workspace.data import WorkspaceCreate
from azents.runtime.control_protocol.data import (
    RuntimeProtocolCapabilities,
    RuntimeProviderRegistration,
)
from azents.runtime.control_protocol.reconciler import (
    RuntimeLifecycleDispatchConfig,
    RuntimeLifecycleReconciler,
)
from azents.runtime.control_protocol.service import (
    RuntimeControlProtocolService,
)
from azents.runtime.coordination.memory import (
    InMemoryRuntimeCoordinationStore,
)
from azents.testing.model_selection import make_test_model_selection_dict


async def test_reconciler_dispatches_periodic_provider_observe(
    rdb_session_manager: SessionManager[AsyncSession],
) -> None:
    """Control dispatches OBSERVE for stale desired-running runtimes."""
    runtime_repository = AgentRuntimeRepository()
    async with rdb_session_manager() as session:
        workspace_id = await _create_workspace(session, "reconciler-observe-ws")
        agent_id = await _create_agent(
            session,
            workspace_id,
            "reconciler-observe-agent",
            runtime_provider_id="provider-1",
        )
        runtime = await runtime_repository.ensure_for_agent(session, agent_id)
        runtime = await runtime_repository.record_provider_connection_state(
            session,
            runtime.id,
            RuntimeProviderConnectionState.CONNECTED,
        )
        assert runtime is not None
        command = await runtime_repository.set_desired_state(
            session,
            runtime.id,
            RuntimeLifecycleCommandType.START,
            RuntimeDesiredState.RUNNING,
        )
        assert command is not None
        await runtime_repository.mark_lifecycle_dispatched(
            session,
            runtime.id,
            command.desired_generation,
        )
        old_observe_at = datetime.datetime.now(datetime.UTC) - datetime.timedelta(
            minutes=10
        )
        await session.execute(
            sa.update(RDBAgentRuntime)
            .where(RDBAgentRuntime.id == runtime.id)
            .values(
                provider_observed_at=old_observe_at,
                provider_observe_requested_at=old_observe_at,
            )
        )

    store = InMemoryRuntimeCoordinationStore()
    control_protocol = RuntimeControlProtocolService(
        store,
        request_id_factory=lambda: "request-1",
    )
    accepted = await control_protocol.register_provider(
        _provider_registration(),
        registered_at=datetime.datetime.now(datetime.UTC),
    )
    reconciler = RuntimeLifecycleReconciler(
        runtime_repository=runtime_repository,
        session_manager=rdb_session_manager,
        coordination_store=store,
        control_protocol=control_protocol,
        config=RuntimeLifecycleDispatchConfig(
            runner_image="runner:test",
            runner_control_endpoint="runtime-control:9090",
            observe_interval=datetime.timedelta(minutes=1),
        ),
    )

    dispatched = await reconciler.reconcile_once(limit=10)
    claimed = await control_protocol.claim_next_provider_request(
        provider_id="provider-1",
        generation=accepted.generation,
        consumer_id="provider-worker",
        block_ms=0,
    )
    async with rdb_session_manager() as session:
        updated = await runtime_repository.get_by_agent_id(session, agent_id)

    assert dispatched == 1
    assert claimed is not None
    assert claimed.operation_type == "provider.observe"
    assert claimed.payload["command_type"] == "observe"
    assert updated is not None
    assert updated.provider_observe_requested_at is not None


def _provider_registration() -> RuntimeProviderRegistration:
    return RuntimeProviderRegistration(
        provider_id="provider-1",
        provider_type="kubernetes",
        scope="system",
        workspace_id=None,
        protocol_version="agent-runtime-provider.v1",
        capabilities=RuntimeProtocolCapabilities(("lifecycle",)),
        config_schema_version="v1",
        metadata={},
        auth_credential_id="provider:provider-1",
        connection_id="provider-connection-1",
        owner_replica_id="control-a",
    )


async def _create_workspace(session: AsyncSession, handle: str) -> str:
    repo = WorkspaceRepository()
    result = await repo.create(
        session, WorkspaceCreate(name="Reconciler", handle=handle)
    )
    assert isinstance(result, Success)
    workspace_id = await repo.resolve_id(session, handle)
    assert workspace_id is not None
    return workspace_id


async def _create_agent(
    session: AsyncSession,
    workspace_id: str,
    slug: str,
    *,
    runtime_provider_id: str | None = None,
) -> str:
    integration = RDBLLMProviderIntegration(
        workspace_id=workspace_id,
        provider=LLMProvider.ANTHROPIC,
        name=f"{slug}-integration",
        encrypted_credentials="encrypted-test-value",
        config=None,
    )
    session.add(integration)
    await session.flush()

    agent = RDBAgent(
        workspace_id=workspace_id,
        name="Reconciler test agent",
        model_selection=make_test_model_selection_dict(
            integration_id=integration.id,
            provider=LLMProvider.ANTHROPIC,
            model_identifier=f"{slug}-id",
        ),
        lightweight_model_selection=make_test_model_selection_dict(
            integration_id=integration.id,
            provider=LLMProvider.ANTHROPIC,
            model_identifier=f"{slug}-id",
        ),
        runtime_provider_id=runtime_provider_id,
    )
    session.add(agent)
    await session.flush()
    return agent.id
