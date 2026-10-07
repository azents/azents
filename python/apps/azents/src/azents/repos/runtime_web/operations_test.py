"""Completed Runtime Web operations preserve authorization and commit boundaries."""

import dataclasses
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta

import pytest
from azcommon.result import Failure, Success
from azents_runtime_control.runtime_stream_session import StreamProtocol

from azents.core.enums import (
    RuntimeDesiredState,
    RuntimeProviderObservedState,
    RuntimeRunnerState,
    WorkspaceUserRole,
)
from azents.rdb.models.agent_runtime import RDBAgentRuntime
from azents.rdb.models.runtime_web import RuntimeWebActorKind, RuntimeWebAuthMode
from azents.rdb.session import SessionManager
from azents.rdb.session_capabilities import WriteSession
from azents.repos.agent import AgentRepository
from azents.repos.agent_admin import AgentAdminRepository
from azents.repos.agent_runtime import AgentRuntimeRepository
from azents.repos.runtime_web.gateway_auth_operations import (
    RuntimeWebGatewayAuthOperationsRepository,
)
from azents.repos.runtime_web.gateway_authority_operations import (
    RuntimeWebGatewayAuthorityOperationsRepository,
)
from azents.repos.runtime_web.gateway_data import RuntimeWebDesiredConfiguration
from azents.repos.runtime_web.gateway_repository import RuntimeWebGatewayRepository
from azents.repos.runtime_web.operations import RuntimeWebOperationsRepository
from azents.repos.runtime_web.repository import (
    RuntimeWebRepository,
    RuntimeWebRepositoryConflict,
)
from azents.repos.runtime_web.repository_test import (
    _authority_fixture,
    _RuntimeWebAuthorityFixture,
)
from azents.repos.session import SessionRepository
from azents.repos.session.data import SessionCreate
from azents.repos.workspace_user import WorkspaceUserRepository
from azents.repos.workspace_user.data import WorkspaceUser, WorkspaceUserCreate
from azents.services.runtime_web.data import (
    RuntimeWebAccessDenied,
    RuntimeWebActor,
    RuntimeWebConflict,
    RuntimeWebOperation,
)
from azents.services.runtime_web.gateway_auth import RuntimeWebGatewayAuthService
from azents.services.runtime_web.gateway_authority import (
    RuntimeWebGatewayAuthorityCode,
    RuntimeWebGatewayAuthorityError,
    RuntimeWebGatewayAuthorityService,
)
from azents.services.runtime_web.service import RuntimeWebService


class _TrackedSessions:
    """Track repository-owned completion around real PostgreSQL scopes."""

    def __init__(self, delegate: SessionManager[WriteSession]) -> None:
        self.delegate = delegate
        self.active = 0
        self.completed = 0

    @asynccontextmanager
    async def __call__(self) -> AsyncIterator[WriteSession]:
        self.active += 1
        try:
            async with self.delegate() as session:
                yield session
        finally:
            self.active -= 1
        self.completed += 1


class _AfterCommitUrls:
    def __init__(self, sessions: _TrackedSessions) -> None:
        self.sessions = sessions
        self.calls = 0

    def resolve(self, hostname_key: str) -> str:
        assert self.sessions.active == 0
        assert self.sessions.completed > 0
        self.calls += 1
        return f"https://{hostname_key}.example.test/"


class _RejectCompletion:
    """Fail before completion through the real rollback boundary."""

    def __init__(self, delegate: SessionManager[WriteSession]) -> None:
        self.delegate = delegate

    @asynccontextmanager
    async def __call__(self) -> AsyncIterator[WriteSession]:
        async with self.delegate() as session:
            yield session
            raise RuntimeError("Database completion rejected")


@dataclasses.dataclass(frozen=True)
class _Fixture:
    authority: _RuntimeWebAuthorityFixture
    member: WorkspaceUser
    auth_session_id: str


async def _seed(manager: SessionManager[WriteSession]) -> _Fixture:
    now = datetime.now(UTC)
    async with manager() as session:
        authority = await _authority_fixture(session)
        membership = await WorkspaceUserRepository().create(
            session,
            WorkspaceUserCreate(
                workspace_id=authority.workspace_id,
                user_id=authority.user_id,
                name="Runtime Web owner",
                role=WorkspaceUserRole.OWNER,
            ),
        )
        assert isinstance(membership, Success)
        auth_session = await SessionRepository().create(
            session,
            SessionCreate(
                user_id=authority.user_id,
                refresh_token="operation-test-refresh",
                expires_at=now + timedelta(hours=1),
                max_expires_at=None,
                user_agent="Operation boundary test",
                ip_address="127.0.0.1",
            ),
        )
        runtime = RDBAgentRuntime(
            workspace_id=authority.workspace_id,
            agent_id=authority.agent_id,
        )
        runtime.desired_state = RuntimeDesiredState.RUNNING
        runtime.desired_generation = 3
        runtime.provider_observed_state = RuntimeProviderObservedState.RUNNING
        runtime.provider_observed_generation = 3
        runtime.runner_state = RuntimeRunnerState.READY
        runtime.runner_generation = 987654
        session.write_session.add(runtime)
        return _Fixture(authority, membership.value, auth_session.id)


def _service(sessions: _TrackedSessions, urls: _AfterCommitUrls) -> RuntimeWebService:
    return RuntimeWebService(
        operations=RuntimeWebOperationsRepository(
            session_manager=sessions,
            repository=RuntimeWebRepository(),
            agent_repository=AgentRepository(),
            agent_admin_repository=AgentAdminRepository(),
            workspace_user_repository=WorkspaceUserRepository(),
        ),
        url_resolver=urls,
    )


def _actor(fixture: _Fixture) -> RuntimeWebActor:
    return RuntimeWebActor(
        kind=RuntimeWebActorKind.USER,
        actor_id=fixture.authority.user_id,
        execution_id=fixture.auth_session_id,
        call_id=None,
    )


async def test_service_projects_after_commit_and_keeps_exact_cas(
    rdb_session_manager: SessionManager[WriteSession],
) -> None:
    fixture = await _seed(rdb_session_manager)
    sessions = _TrackedSessions(rdb_session_manager)
    urls = _AfterCommitUrls(sessions)
    service = _service(sessions, urls)
    created = await service.create_service(
        workspace_id=fixture.authority.workspace_id,
        agent_id=fixture.authority.agent_id,
        user_id=fixture.authority.user_id,
        workspace_user_id=fixture.member.id,
        role=fixture.member.role,
        port=8080,
        label="After commit",
        selected_duration_seconds=3600,
        turn_on=False,
        actor=_actor(fixture),
        operation=RuntimeWebOperation(operation_key="create"),
    )
    assert isinstance(created, Success)
    assert not created.value.on
    assert sessions.completed == 1
    assert urls.calls == 1

    # Opaque-ID membership discovery and exact On CAS share one completed scope.
    activated = await service.turn_on_by_id_for_user(
        service_id=created.value.id,
        user_id=fixture.authority.user_id,
        expected_revision=created.value.revision,
        selected_duration_seconds=3600,
        actor=_actor(fixture),
        operation=RuntimeWebOperation(operation_key="activate"),
    )
    assert isinstance(activated, Success)
    assert activated.value.on
    assert sessions.completed == 2
    assert urls.calls == 2
    assert activated.value.observed_at.tzinfo is not None

    stale = await service.turn_off(
        workspace_id=fixture.authority.workspace_id,
        agent_id=fixture.authority.agent_id,
        service_id=created.value.id,
        user_id=fixture.authority.user_id,
        workspace_user_id=fixture.member.id,
        role=fixture.member.role,
        expected_revision=created.value.revision,
        actor=_actor(fixture),
        operation=RuntimeWebOperation(operation_key="stale-off"),
    )
    assert isinstance(stale, Failure)
    assert isinstance(stale.error, RuntimeWebConflict)
    assert sessions.active == 0
    assert urls.calls == 2
    retained = await service.get_service_by_id_for_user(
        service_id=created.value.id, user_id=fixture.authority.user_id
    )
    assert isinstance(retained, Success)
    assert retained.value.on
    assert retained.value.revision == activated.value.revision

    # Unauthorized callers retain the error contract, not early receipt validation.
    denied = await service.request_service(
        workspace_id=fixture.authority.workspace_id,
        agent_id=fixture.authority.agent_id,
        port=8081,
        label=None,
        actor=RuntimeWebActor(
            kind=RuntimeWebActorKind.USER,
            actor_id=fixture.authority.user_id,
            execution_id="",
            call_id=None,
        ),
        operation=RuntimeWebOperation(operation_key=""),
    )
    assert isinstance(denied, Failure)
    assert isinstance(denied.error, RuntimeWebAccessDenied)


async def test_completed_gateway_ticket_and_current_runtime_authority(
    rdb_session_manager: SessionManager[WriteSession],
) -> None:
    fixture = await _seed(rdb_session_manager)
    sessions = _TrackedSessions(rdb_session_manager)
    service = _service(sessions, _AfterCommitUrls(sessions))
    created = await service.create_service(
        workspace_id=fixture.authority.workspace_id,
        agent_id=fixture.authority.agent_id,
        user_id=fixture.authority.user_id,
        workspace_user_id=fixture.member.id,
        role=fixture.member.role,
        port=8080,
        label=None,
        selected_duration_seconds=3600,
        turn_on=True,
        actor=_actor(fixture),
        operation=RuntimeWebOperation(operation_key="gateway-create"),
    )
    assert isinstance(created, Success)
    gateway_repository = RuntimeWebGatewayRepository()
    auth = RuntimeWebGatewayAuthService(
        operations=RuntimeWebGatewayAuthOperationsRepository(
            session_manager=sessions,
            repository=gateway_repository,
            agent_repository=AgentRepository(),
            agent_admin_repository=AgentAdminRepository(),
            workspace_user_repository=WorkspaceUserRepository(),
        ),
        identity_lifetime=timedelta(minutes=30),
        desired_configuration=RuntimeWebDesiredConfiguration(
            enabled=True,
            mode=RuntimeWebAuthMode.SEPARATE_DOMAIN,
            fingerprint="f" * 64,
        ),
    )
    now = datetime.now(UTC)
    binding = await auth.initiate_separate_domain(
        user_id=fixture.authority.user_id,
        auth_session_id=fixture.auth_session_id,
        service_id=created.value.id,
        now=now,
    )
    assert sessions.active == 0
    broker = await auth.bind_broker(
        initiation_id=binding.binding.initiation_id, now=now
    )
    await auth.mark_broker_bound(
        initiation_id=binding.binding.initiation_id,
        main_binding_secret=binding.main_binding_secret,
        user_id=fixture.authority.user_id,
        auth_session_id=fixture.auth_session_id,
        now=now,
    )
    ticket = await auth.issue_ticket(
        initiation_id=binding.binding.initiation_id,
        main_binding_secret=binding.main_binding_secret,
        user_id=fixture.authority.user_id,
        auth_session_id=fixture.auth_session_id,
        now=now,
    )
    assert ticket.expires_at == now + timedelta(seconds=30)
    redeemed = await auth.redeem_ticket(
        ticket_secret=ticket.ticket_secret,
        broker_binding_secret=broker.broker_binding_secret,
        now=now,
    )
    assert sessions.active == 0
    assert redeemed.service_id == created.value.id
    with pytest.raises(RuntimeWebRepositoryConflict):
        await auth.redeem_ticket(
            ticket_secret=ticket.ticket_secret,
            broker_binding_secret=broker.broker_binding_secret,
            now=now,
        )
    identity = await auth.authenticate(secret=redeemed.secret, now=now)
    assert identity is not None
    authority_service = RuntimeWebGatewayAuthorityService(
        operations=RuntimeWebGatewayAuthorityOperationsRepository(
            session_manager=sessions,
            gateway_repository=gateway_repository,
            runtime_web_repository=RuntimeWebRepository(),
            agent_repository=AgentRepository(),
            agent_admin_repository=AgentAdminRepository(),
            workspace_user_repository=WorkspaceUserRepository(),
            runtime_repository=AgentRuntimeRepository(),
        )
    )
    resolved = await authority_service.resolve_service_by_id(
        service_id=created.value.id
    )
    assert resolved is not None
    authority = await authority_service.authorize(
        hostname_key=resolved.hostname_key,
        identity_secret=redeemed.secret,
        protocol=StreamProtocol.HTTP,
    )
    assert sessions.active == 0
    assert authority.runner_generation == 987654
    assert await authority_service.identity_and_access_current(authority=authority)
    async with rdb_session_manager() as session:
        runtime = await session.write_session.get(RDBAgentRuntime, authority.runtime_id)
        assert runtime is not None
        runtime.runner_generation += 1
    assert not await authority_service.identity_and_access_current(authority=authority)
    replacement = await authority_service.authorize(
        hostname_key=resolved.hostname_key,
        identity_secret=redeemed.secret,
        protocol=StreamProtocol.HTTP,
    )
    assert replacement.runner_generation == authority.runner_generation + 1
    assert await authority_service.identity_and_access_current(authority=replacement)
    assert await auth.revoke(
        secret=redeemed.secret,
        user_id=fixture.authority.user_id,
        auth_session_id=fixture.auth_session_id,
        now=now,
    )
    assert not await authority_service.identity_and_access_current(authority=authority)
    with pytest.raises(RuntimeWebGatewayAuthorityError) as rejected:
        await authority_service.authorize(
            hostname_key=resolved.hostname_key,
            identity_secret=redeemed.secret,
            protocol=StreamProtocol.HTTP,
        )
    assert rejected.value.code is RuntimeWebGatewayAuthorityCode.UNAUTHENTICATED


@pytest.mark.parametrize("operation", ["service", "identity"])
async def test_failed_completion_does_not_publish_projection_or_secret(
    rdb_session_manager: SessionManager[WriteSession],
    operation: str,
) -> None:
    fixture = await _seed(rdb_session_manager)
    sessions = _TrackedSessions(_RejectCompletion(rdb_session_manager))
    urls = _AfterCommitUrls(sessions)
    with pytest.raises(RuntimeError, match="Database completion rejected"):
        if operation == "service":
            await _service(sessions, urls).request_service(
                workspace_id=fixture.authority.workspace_id,
                agent_id=fixture.authority.agent_id,
                port=8080,
                label=None,
                actor=RuntimeWebActor(
                    kind=RuntimeWebActorKind.AGENT,
                    actor_id=fixture.authority.agent_id,
                    execution_id="failed-completion",
                    call_id=None,
                ),
                operation=RuntimeWebOperation(operation_key="rollback-request"),
            )
        else:
            auth = RuntimeWebGatewayAuthService(
                operations=RuntimeWebGatewayAuthOperationsRepository(
                    session_manager=sessions,
                    repository=RuntimeWebGatewayRepository(),
                    agent_repository=AgentRepository(),
                    agent_admin_repository=AgentAdminRepository(),
                    workspace_user_repository=WorkspaceUserRepository(),
                ),
                identity_lifetime=timedelta(minutes=30),
                desired_configuration=None,
            )
            await auth.issue_shared_identity(
                user_id=fixture.authority.user_id,
                auth_session_id=fixture.auth_session_id,
                now=datetime.now(UTC),
            )
    assert sessions.active == 0
    assert sessions.completed == 0
    assert urls.calls == 0
    service = _service(
        _TrackedSessions(rdb_session_manager),
        _AfterCommitUrls(sessions),
    )
    if operation == "service":
        listing = await service.operations.list_services(
            workspace_id=fixture.authority.workspace_id,
            agent_id=fixture.authority.agent_id,
            user_id=fixture.authority.user_id,
            workspace_user_id=fixture.member.id,
            role=fixture.member.role,
            offset=0,
            limit=16,
            operation=None,
        )
        assert isinstance(listing, Success)
        assert listing.value.total_count == 0
