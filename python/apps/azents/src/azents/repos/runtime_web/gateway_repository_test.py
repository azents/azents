"""Runtime Web Gateway authentication repository tests."""

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from azents.rdb.models.runtime_web import RuntimeWebActorKind, RuntimeWebAuthMode
from azents.repos.runtime_web.data import RuntimeWebOperationIdentity
from azents.repos.runtime_web.gateway_data import RuntimeWebDesiredConfiguration
from azents.repos.runtime_web.gateway_repository import RuntimeWebGatewayRepository
from azents.repos.runtime_web.repository import (
    RuntimeWebRepository,
    RuntimeWebRepositoryConflict,
)
from azents.repos.runtime_web.repository_test import _authority_fixture
from azents.repos.session import SessionRepository
from azents.repos.session.data import SessionCreate


def _operation(agent_id: str) -> RuntimeWebOperationIdentity:
    return RuntimeWebOperationIdentity(
        actor_kind=RuntimeWebActorKind.AGENT,
        actor_id=agent_id,
        execution_id="gateway-test-run",
        operation_key="gateway-test-request",
    )


async def test_separate_domain_ticket_is_service_bound_and_single_use(
    rdb_session: AsyncSession,
) -> None:
    now = datetime.now(UTC)
    fixture = await _authority_fixture(
        rdb_session,
        handle="runtime-web-gateway-auth",
        email="runtime-web-gateway-auth@example.com",
    )
    auth_session = await SessionRepository().create(
        rdb_session,
        SessionCreate(
            user_id=fixture.user_id,
            refresh_token="runtime-web-gateway-refresh",
            expires_at=now + timedelta(hours=1),
            max_expires_at=None,
            user_agent="Chromium 152",
            ip_address="127.0.0.1",
        ),
    )
    service = await RuntimeWebRepository().request_service(
        rdb_session,
        workspace_id=fixture.workspace_id,
        agent_id=fixture.agent_id,
        port=8080,
        label="Gateway",
        operation=_operation(fixture.agent_id),
        service_limit=16,
    )
    repository = RuntimeWebGatewayRepository()
    await repository.synchronize_configuration(
        rdb_session,
        desired=RuntimeWebDesiredConfiguration(
            enabled=True,
            mode=RuntimeWebAuthMode.SEPARATE_DOMAIN,
            fingerprint="a" * 64,
        ),
    )
    issued = await repository.create_binding(
        rdb_session,
        initiation_id="i" * 32,
        main_binding_hash="m" * 64,
        user_id=fixture.user_id,
        auth_session_id=auth_session.id,
        service_id=service.service.id,
        expires_at=now + timedelta(minutes=2),
        now=now,
        main_binding_secret="main-secret",
    )
    broker = await repository.bind_broker(
        rdb_session,
        initiation_id=issued.binding.initiation_id,
        broker_binding_hash="b" * 64,
        broker_binding_secret="broker-secret",
        now=now,
    )
    await repository.mark_broker_bound(
        rdb_session,
        initiation_id=issued.binding.initiation_id,
        main_binding_hash="m" * 64,
        user_id=fixture.user_id,
        auth_session_id=auth_session.id,
        now=now,
    )
    ticket = await repository.issue_ticket(
        rdb_session,
        initiation_id=issued.binding.initiation_id,
        main_binding_hash="m" * 64,
        user_id=fixture.user_id,
        auth_session_id=auth_session.id,
        ticket_hash="t" * 64,
        ticket_secret="ticket-secret",
        issued_at=now,
        expires_at=now + timedelta(seconds=30),
    )
    identity = await repository.redeem_ticket(
        rdb_session,
        ticket_hash="t" * 64,
        broker_binding_hash="b" * 64,
        identity_hash="g" * 64,
        identity_secret="identity-secret",
        identity_expires_at=now + timedelta(minutes=30),
        now=now,
    )

    assert broker.binding.broker_bound is False
    assert ticket.service_id == service.service.id
    assert identity.service_id == service.service.id
    assert identity.secret == "identity-secret"
    assert (
        await repository.authenticate_identity(
            rdb_session,
            secret_hash="g" * 64,
            now=now,
        )
        is not None
    )

    with pytest.raises(RuntimeWebRepositoryConflict):
        await repository.redeem_ticket(
            rdb_session,
            ticket_hash="t" * 64,
            broker_binding_hash="b" * 64,
            identity_hash="h" * 64,
            identity_secret="second-identity",
            identity_expires_at=now + timedelta(minutes=30),
            now=now,
        )


async def test_configuration_change_invalidates_existing_identity(
    rdb_session: AsyncSession,
) -> None:
    repository = RuntimeWebGatewayRepository()
    await repository.synchronize_configuration(
        rdb_session,
        desired=RuntimeWebDesiredConfiguration(
            enabled=False,
            mode=RuntimeWebAuthMode.SHARED_COOKIE,
            fingerprint="1" * 64,
        ),
    )
    updated = await RuntimeWebRepository().get_configuration(rdb_session)
    assert updated is not None
    assert updated.enabled is False
    assert updated.fingerprint == "1" * 64
