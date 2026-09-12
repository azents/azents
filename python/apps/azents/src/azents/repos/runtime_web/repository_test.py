"""Runtime Web durable authority repository tests."""

import asyncio

import pytest
from azcommon.result import Success
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from azents.core.enums import (
    AgentRuntimeCapability,
    AgentSessionProductMode,
    LLMProvider,
)
from azents.rdb.models.agent import RDBAgent
from azents.rdb.models.llm_provider_integration import RDBLLMProviderIntegration
from azents.rdb.models.runtime_web import (
    RDBRuntimeWebAuthConfiguration,
    RuntimeWebRequesterKind,
    RuntimeWebRequestState,
)
from azents.repos.agent_session import AgentSessionRepository
from azents.repos.agent_session.data import AgentSessionCreate
from azents.repos.runtime_web.data import (
    RuntimeWebOperationIdentity,
    derived_operation_key,
)
from azents.repos.runtime_web.repository import (
    RuntimeWebRepository,
    RuntimeWebRepositoryConflict,
    RuntimeWebRepositoryQuotaExceeded,
)
from azents.repos.user import UserRepository
from azents.repos.user.data import UserCreate
from azents.repos.workspace import WorkspaceRepository
from azents.repos.workspace.data import WorkspaceCreate
from azents.testing.model_selection import make_test_model_selection_dict


async def _authority_fixture(
    session: AsyncSession,
    *,
    handle: str = "runtime-web",
    email: str = "runtime-web@example.com",
) -> tuple[str, str, str, str]:
    workspace_result = await WorkspaceRepository().create(
        session,
        WorkspaceCreate(name="Runtime Web", handle=handle),
    )
    assert isinstance(workspace_result, Success)
    workspace_id = await WorkspaceRepository().resolve_id(session, handle)
    assert workspace_id is not None
    integration = RDBLLMProviderIntegration(
        workspace_id=workspace_id,
        provider=LLMProvider.ANTHROPIC,
        name="Runtime Web integration",
        encrypted_credentials="encrypted-test-value",
        config=None,
    )
    session.add(integration)
    await session.flush()
    agent = RDBAgent(
        workspace_id=workspace_id,
        name="Runtime Web agent",
        runtime_capability=AgentRuntimeCapability.NONE,
        model_selection=make_test_model_selection_dict(
            integration_id=integration.id,
            provider=LLMProvider.ANTHROPIC,
            model_identifier="runtime-web-model",
        ),
        lightweight_model_selection=make_test_model_selection_dict(
            integration_id=integration.id,
            provider=LLMProvider.ANTHROPIC,
            model_identifier="runtime-web-model",
        ),
    )
    session.add(agent)
    await session.flush()
    agent_session = await AgentSessionRepository().create(
        session,
        AgentSessionCreate(
            workspace_id=workspace_id,
            product_mode=AgentSessionProductMode.TEAM,
            associated_user_id=None,
            agent_id=agent.id,
            title=None,
        ),
    )
    user = await UserRepository().create(
        session,
        UserCreate(email=email),
    )
    configuration = await session.get(RDBRuntimeWebAuthConfiguration, 1)
    assert configuration is not None
    configuration.enabled = True
    await session.flush()
    return workspace_id, agent.id, agent_session.id, user.id


def _operation(key: str, *, actor_id: str = "agent-id") -> RuntimeWebOperationIdentity:
    return RuntimeWebOperationIdentity(
        actor_kind=RuntimeWebRequesterKind.AGENT,
        actor_id=actor_id,
        execution_id="run-id",
        operation_key=key,
    )


def test_derived_operation_key_uses_the_complete_parent_key() -> None:
    """Composite operation keys do not collide on a shared long prefix."""
    prefix = "a" * 118

    assert derived_operation_key(f"{prefix}first", "prepare") != (
        derived_operation_key(f"{prefix}second", "prepare")
    )


async def test_concurrent_identical_prepare_replays_one_committed_result(
    rdb_engine: AsyncEngine,
    latest_db_schema: None,
) -> None:
    """Concurrent identical operations serialize before receipt lookup."""
    del latest_db_schema
    async with AsyncSession(rdb_engine, expire_on_commit=False) as setup:
        workspace_id, agent_id, session_id, _ = await _authority_fixture(
            setup,
            handle="runtime-web-concurrent",
            email="runtime-web-concurrent@example.com",
        )
        await setup.commit()

    repository = RuntimeWebRepository()
    operation = _operation("concurrent-prepare", actor_id=agent_id)

    async def prepare() -> str:
        async with AsyncSession(rdb_engine, expire_on_commit=False) as session:
            result = await repository.prepare_endpoint(
                session,
                workspace_id=workspace_id,
                agent_id=agent_id,
                agent_session_id=session_id,
                port=3000,
                label="Concurrent",
                operation=operation,
                endpoint_limit=16,
            )
            await session.commit()
            return result.endpoint.id

    try:
        first, second = await asyncio.gather(prepare(), prepare())
        assert first == second
    finally:
        async with AsyncSession(rdb_engine) as cleanup:
            configuration = await cleanup.get(RDBRuntimeWebAuthConfiguration, 1)
            assert configuration is not None
            configuration.enabled = False
            await cleanup.commit()


async def test_endpoint_request_cycle_and_rerequest_are_orthogonal(
    rdb_session: AsyncSession,
) -> None:
    """Persist stable endpoint, one pending request, and active plus pending state."""
    workspace_id, agent_id, session_id, user_id = await _authority_fixture(rdb_session)
    repository = RuntimeWebRepository()

    prepared = await repository.prepare_endpoint(
        rdb_session,
        workspace_id=workspace_id,
        agent_id=agent_id,
        agent_session_id=session_id,
        port=3000,
        label="Preview",
        operation=_operation("prepare", actor_id=agent_id),
        endpoint_limit=16,
    )
    replay = await repository.prepare_endpoint(
        rdb_session,
        workspace_id=workspace_id,
        agent_id=agent_id,
        agent_session_id=session_id,
        port=3000,
        label="Preview",
        operation=_operation("prepare", actor_id=agent_id),
        endpoint_limit=16,
    )
    assert replay.endpoint.id == prepared.endpoint.id
    assert replay.endpoint.hostname_key == prepared.endpoint.hostname_key

    pending = await repository.request_exposure(
        rdb_session,
        endpoint_id=prepared.endpoint.id,
        actor_kind=RuntimeWebRequesterKind.AGENT,
        requester_user_id=None,
        requester_agent_id=agent_id,
        requester_call_id="call-request",
        label="Preview",
        operation=_operation("request", actor_id=agent_id),
    )
    duplicate_request = await repository.request_exposure(
        rdb_session,
        endpoint_id=prepared.endpoint.id,
        actor_kind=RuntimeWebRequesterKind.AGENT,
        requester_user_id=None,
        requester_agent_id=agent_id,
        requester_call_id="call-request-2",
        label="Preview",
        operation=_operation("request-2", actor_id=agent_id),
    )
    assert pending.request is not None
    assert duplicate_request.request is not None
    assert duplicate_request.request.id == pending.request.id

    approved = await repository.approve_request(
        rdb_session,
        request_id=pending.request.id,
        expected_revision=pending.request.revision,
        approver_user_id=user_id,
        duration_seconds=7_200,
        duration_configuration_revision=1,
        operation=_operation("approve", actor_id=user_id),
        active_session_limit=4,
        active_agent_limit=16,
    )
    assert approved.request is not None
    assert approved.request.state is RuntimeWebRequestState.APPROVED
    assert approved.cycle is not None

    rerequest = await repository.request_exposure(
        rdb_session,
        endpoint_id=prepared.endpoint.id,
        actor_kind=RuntimeWebRequesterKind.AGENT,
        requester_user_id=None,
        requester_agent_id=agent_id,
        requester_call_id="call-rerequest",
        label="Preview",
        operation=_operation("rerequest", actor_id=agent_id),
    )
    assert rerequest.request is not None
    assert rerequest.request.state is RuntimeWebRequestState.PENDING
    assert rerequest.cycle is not None
    assert rerequest.cycle.id == approved.cycle.id

    closed = await repository.close_cycle(
        rdb_session,
        cycle_id=approved.cycle.id,
        expected_endpoint_revision=rerequest.endpoint.authority_revision,
        operation=_operation("close", actor_id=agent_id),
    )
    assert closed.cycle is not None
    assert closed.cycle.ended_at is not None
    assert closed.request is not None
    assert closed.request.id == rerequest.request.id


async def test_stale_duration_revision_and_endpoint_quota_fail_closed(
    rdb_session: AsyncSession,
) -> None:
    """Reject stale approval configuration and bounded endpoint overflow."""
    workspace_id, agent_id, session_id, user_id = await _authority_fixture(rdb_session)
    repository = RuntimeWebRepository()
    prepared = await repository.prepare_endpoint(
        rdb_session,
        workspace_id=workspace_id,
        agent_id=agent_id,
        agent_session_id=session_id,
        port=3000,
        label=None,
        operation=_operation("prepare-one", actor_id=agent_id),
        endpoint_limit=1,
    )
    pending = await repository.request_exposure(
        rdb_session,
        endpoint_id=prepared.endpoint.id,
        actor_kind=RuntimeWebRequesterKind.AGENT,
        requester_user_id=None,
        requester_agent_id=agent_id,
        requester_call_id=None,
        label=None,
        operation=_operation("request-one", actor_id=agent_id),
    )
    assert pending.request is not None

    with pytest.raises(RuntimeWebRepositoryConflict, match="Duration"):
        await repository.approve_request(
            rdb_session,
            request_id=pending.request.id,
            expected_revision=pending.request.revision,
            approver_user_id=user_id,
            duration_seconds=7_200,
            duration_configuration_revision=2,
            operation=_operation("approve-stale", actor_id=user_id),
            active_session_limit=4,
            active_agent_limit=16,
        )

    with pytest.raises(RuntimeWebRepositoryQuotaExceeded) as raised:
        await repository.prepare_endpoint(
            rdb_session,
            workspace_id=workspace_id,
            agent_id=agent_id,
            agent_session_id=session_id,
            port=4000,
            label=None,
            operation=_operation("prepare-two", actor_id=agent_id),
            endpoint_limit=1,
        )
    assert raised.value.scope == "session_endpoints"


async def test_direct_create_is_atomic_and_replays_completed_result(
    rdb_session: AsyncSession,
) -> None:
    """Direct creation rolls back partial state and replays one completed cycle."""
    workspace_id, agent_id, session_id, user_id = await _authority_fixture(rdb_session)
    repository = RuntimeWebRepository()
    stale_operation = RuntimeWebOperationIdentity(
        actor_kind=RuntimeWebRequesterKind.USER,
        actor_id=user_id,
        execution_id="browser-session",
        operation_key="direct-stale",
    )

    with pytest.raises(RuntimeWebRepositoryConflict):
        await repository.direct_create(
            rdb_session,
            workspace_id=workspace_id,
            agent_id=agent_id,
            agent_session_id=session_id,
            port=4000,
            label="Failed preview",
            requester_user_id=user_id,
            requester_call_id=None,
            duration_seconds=7_200,
            duration_configuration_revision=2,
            operation=stale_operation,
            endpoint_limit=16,
            active_session_limit=4,
            active_agent_limit=16,
        )
    assert (
        await repository.get_endpoint(
            rdb_session,
            agent_session_id=session_id,
            port=4000,
        )
        is None
    )

    operation = stale_operation.model_copy(update={"operation_key": "direct-success"})
    created = await repository.direct_create(
        rdb_session,
        workspace_id=workspace_id,
        agent_id=agent_id,
        agent_session_id=session_id,
        port=4000,
        label="Preview",
        requester_user_id=user_id,
        requester_call_id=None,
        duration_seconds=7_200,
        duration_configuration_revision=1,
        operation=operation,
        endpoint_limit=16,
        active_session_limit=4,
        active_agent_limit=16,
    )
    replay = await repository.direct_create(
        rdb_session,
        workspace_id=workspace_id,
        agent_id=agent_id,
        agent_session_id=session_id,
        port=4000,
        label="Preview",
        requester_user_id=user_id,
        requester_call_id=None,
        duration_seconds=7_200,
        duration_configuration_revision=1,
        operation=operation,
        endpoint_limit=16,
        active_session_limit=4,
        active_agent_limit=16,
    )

    assert created.request is not None
    assert created.cycle is not None
    assert replay.endpoint.id == created.endpoint.id
    assert replay.request is not None
    assert replay.request.id == created.request.id
    assert replay.cycle is not None
    assert replay.cycle.id == created.cycle.id


async def test_stale_close_does_not_terminate_current_cycle(
    rdb_session: AsyncSession,
) -> None:
    """Fence delayed closure by the endpoint revision the caller observed."""
    workspace_id, agent_id, session_id, user_id = await _authority_fixture(rdb_session)
    repository = RuntimeWebRepository()
    prepared = await repository.prepare_endpoint(
        rdb_session,
        workspace_id=workspace_id,
        agent_id=agent_id,
        agent_session_id=session_id,
        port=3000,
        label=None,
        operation=_operation("prepare", actor_id=agent_id),
        endpoint_limit=16,
    )
    pending = await repository.request_exposure(
        rdb_session,
        endpoint_id=prepared.endpoint.id,
        actor_kind=RuntimeWebRequesterKind.AGENT,
        requester_user_id=None,
        requester_agent_id=agent_id,
        requester_call_id=None,
        label=None,
        operation=_operation("request", actor_id=agent_id),
    )
    assert pending.request is not None
    approved = await repository.approve_request(
        rdb_session,
        request_id=pending.request.id,
        expected_revision=pending.request.revision,
        approver_user_id=user_id,
        duration_seconds=7_200,
        duration_configuration_revision=1,
        operation=_operation("approve", actor_id=user_id),
        active_session_limit=4,
        active_agent_limit=16,
    )
    assert approved.cycle is not None

    with pytest.raises(RuntimeWebRepositoryConflict, match="Current cycle"):
        await repository.close_cycle(
            rdb_session,
            cycle_id=approved.cycle.id,
            expected_endpoint_revision=approved.endpoint.authority_revision - 1,
            operation=_operation("stale-close", actor_id=agent_id),
        )
