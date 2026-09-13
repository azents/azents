"""Runtime Web Gateway authentication repository tests."""

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from azents.rdb.models.runtime_web import (
    RuntimeWebAuthMode,
    RuntimeWebRequesterKind,
)
from azents.repos.runtime_web.data import (
    RuntimeWebOperationIdentity,
)
from azents.repos.runtime_web.gateway_data import (
    RuntimeWebAdmissionLimits,
    RuntimeWebDesiredConfiguration,
)
from azents.repos.runtime_web.gateway_repository import (
    RuntimeWebGatewayCapacityExceeded,
    RuntimeWebGatewayRepository,
)
from azents.repos.runtime_web.repository import (
    RuntimeWebRepository,
    RuntimeWebRepositoryConflict,
)
from azents.repos.runtime_web.repository_test import _authority_fixture
from azents.repos.session import SessionRepository
from azents.repos.session.data import SessionCreate


def _operation(agent_id: str) -> RuntimeWebOperationIdentity:
    return RuntimeWebOperationIdentity(
        actor_kind=RuntimeWebRequesterKind.AGENT,
        actor_id=agent_id,
        execution_id="gateway-test-run",
        operation_key="gateway-test-prepare",
    )


async def test_separate_domain_ticket_is_bound_single_use_and_epoch_fenced(
    rdb_session: AsyncSession,
) -> None:
    """A broker ticket settles exactly one protected Gateway identity."""
    now = datetime.now(UTC)
    workspace_id, agent_id, agent_session_id, user_id = await _authority_fixture(
        rdb_session,
        handle="runtime-web-gateway-auth",
        email="runtime-web-gateway-auth@example.com",
    )
    auth_session = await SessionRepository().create(
        rdb_session,
        SessionCreate(
            user_id=user_id,
            refresh_token="runtime-web-gateway-refresh",
            expires_at=now + timedelta(hours=1),
            max_expires_at=None,
            user_agent="Chromium 152",
            ip_address="127.0.0.1",
        ),
    )
    endpoint = await RuntimeWebRepository().prepare_endpoint(
        rdb_session,
        workspace_id=workspace_id,
        agent_id=agent_id,
        agent_session_id=agent_session_id,
        port=8080,
        label="Gateway",
        operation=_operation(agent_id),
        endpoint_limit=16,
    )
    repository = RuntimeWebGatewayRepository()
    epoch = await repository.synchronize_configuration(
        rdb_session,
        desired=RuntimeWebDesiredConfiguration(
            enabled=True,
            mode=RuntimeWebAuthMode.SEPARATE_DOMAIN,
            configuration_version=2,
            fingerprint="a" * 64,
            active_duration_seconds=3_600,
        ),
    )
    issued = await repository.create_binding(
        rdb_session,
        initiation_id="i" * 32,
        main_binding_hash="m" * 64,
        user_id=user_id,
        auth_session_id=auth_session.id,
        endpoint_id=endpoint.endpoint.id,
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
        user_id=user_id,
        auth_session_id=auth_session.id,
        now=now,
    )
    ticket = await repository.issue_ticket(
        rdb_session,
        initiation_id=issued.binding.initiation_id,
        main_binding_hash="m" * 64,
        user_id=user_id,
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
        browser_profile="chromium-152",
        identity_expires_at=now + timedelta(minutes=30),
        now=now,
    )

    assert epoch == 2
    assert broker.binding.broker_bound is False
    assert ticket.endpoint_id == endpoint.endpoint.id
    assert identity.secret == "identity-secret"
    assert (
        await repository.authenticate_identity(
            rdb_session,
            secret_hash="g" * 64,
            browser_profile="chromium-152",
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
            browser_profile="chromium-152",
            identity_expires_at=now + timedelta(minutes=30),
            now=now,
        )


async def test_configuration_requires_monotonic_version_for_security_change(
    rdb_session: AsyncSession,
) -> None:
    repository = RuntimeWebGatewayRepository()
    configured = await RuntimeWebRepository().get_configuration(rdb_session)
    assert configured is not None
    current = await repository.synchronize_configuration(
        rdb_session,
        desired=RuntimeWebDesiredConfiguration(
            enabled=configured.enabled,
            mode=configured.mode,
            configuration_version=configured.configuration_version,
            fingerprint=configured.fingerprint,
            active_duration_seconds=configured.active_duration_seconds,
        ),
    )
    assert current == configured.active_epoch

    with pytest.raises(RuntimeWebRepositoryConflict):
        await repository.synchronize_configuration(
            rdb_session,
            desired=RuntimeWebDesiredConfiguration(
                enabled=not configured.enabled,
                mode=configured.mode,
                configuration_version=configured.configuration_version,
                fingerprint="1" * 64,
                active_duration_seconds=configured.active_duration_seconds,
            ),
        )


async def test_gateway_admission_enforces_and_releases_shared_scope_limits(
    rdb_session: AsyncSession,
) -> None:
    now = datetime.now(UTC)
    workspace_id, agent_id, agent_session_id, user_id = await _authority_fixture(
        rdb_session,
        handle="runtime-web-gateway-quota",
        email="runtime-web-gateway-quota@example.com",
    )
    endpoint = await RuntimeWebRepository().prepare_endpoint(
        rdb_session,
        workspace_id=workspace_id,
        agent_id=agent_id,
        agent_session_id=agent_session_id,
        port=8081,
        label="Quota",
        operation=RuntimeWebOperationIdentity(
            actor_kind=RuntimeWebRequesterKind.AGENT,
            actor_id=agent_id,
            execution_id="gateway-quota-run",
            operation_key="gateway-quota-prepare",
        ),
        endpoint_limit=16,
    )
    repository = RuntimeWebGatewayRepository()
    limits = RuntimeWebAdmissionLimits(endpoint=1, user=2, agent=2)
    await repository.acquire_admission(
        rdb_session,
        tunnel_id="tunnel-one",
        endpoint_id=endpoint.endpoint.id,
        user_id=user_id,
        agent_id=agent_id,
        websocket=False,
        lease_expires_at=now + timedelta(minutes=1),
        now=now,
        limits=limits,
    )

    with pytest.raises(RuntimeWebGatewayCapacityExceeded) as captured:
        await repository.acquire_admission(
            rdb_session,
            tunnel_id="tunnel-two",
            endpoint_id=endpoint.endpoint.id,
            user_id=user_id,
            agent_id=agent_id,
            websocket=False,
            lease_expires_at=now + timedelta(minutes=1),
            now=now,
            limits=limits,
        )
    assert captured.value.scope == "endpoint"

    await repository.release_admission(rdb_session, tunnel_id="tunnel-one")
    await repository.acquire_admission(
        rdb_session,
        tunnel_id="tunnel-two",
        endpoint_id=endpoint.endpoint.id,
        user_id=user_id,
        agent_id=agent_id,
        websocket=False,
        lease_expires_at=now + timedelta(minutes=1),
        now=now,
        limits=limits,
    )
