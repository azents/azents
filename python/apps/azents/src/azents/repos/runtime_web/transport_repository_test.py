"""Runtime Web durable transport route repository tests."""

import datetime

import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from azents.rdb.models.agent_runtime import RDBAgentRuntime
from azents.rdb.models.runtime_web import (
    RDBRuntimeWebAdmissionLease,
    RDBRuntimeWebCycle,
    RDBRuntimeWebEndpoint,
    RDBRuntimeWebTunnelRoute,
    RuntimeWebCycleEndReason,
    RuntimeWebRequesterKind,
)
from azents.repos.runtime_web.data import (
    RuntimeWebOperationIdentity,
    RuntimeWebTunnelAuthority,
)
from azents.repos.runtime_web.repository import RuntimeWebRepository
from azents.repos.runtime_web.repository_test import _authority_fixture
from azents.repos.runtime_web.transport_repository import (
    RuntimeWebAdmissionCapacityExceeded,
    RuntimeWebRouteConflict,
    RuntimeWebTransportRepository,
)


async def _active_tunnel(
    session: AsyncSession,
    *,
    port: int = 3000,
) -> RuntimeWebTunnelAuthority:
    workspace_id, agent_id, session_id, user_id = await _authority_fixture(session)
    runtime = RDBAgentRuntime(workspace_id=workspace_id, agent_id=agent_id)
    session.add(runtime)
    await session.flush()
    runtime.desired_generation = 3
    runtime.runner_generation = 4
    authority = RuntimeWebRepository()
    prepared = await authority.prepare_endpoint(
        session,
        workspace_id=workspace_id,
        agent_id=agent_id,
        agent_session_id=session_id,
        port=port,
        label=None,
        operation=RuntimeWebOperationIdentity(
            actor_kind=RuntimeWebRequesterKind.AGENT,
            actor_id=agent_id,
            execution_id="transport-test",
            operation_key=f"prepare-{port}",
        ),
        endpoint_limit=16,
    )
    pending = await authority.request_exposure(
        session,
        endpoint_id=prepared.endpoint.id,
        actor_kind=RuntimeWebRequesterKind.AGENT,
        requester_user_id=None,
        requester_agent_id=agent_id,
        requester_call_id=None,
        label=None,
        operation=RuntimeWebOperationIdentity(
            actor_kind=RuntimeWebRequesterKind.AGENT,
            actor_id=agent_id,
            execution_id="transport-test",
            operation_key=f"request-{port}",
        ),
    )
    assert pending.request is not None
    approved = await authority.approve_request(
        session,
        request_id=pending.request.id,
        expected_revision=pending.request.revision,
        approver_user_id=user_id,
        duration_seconds=7_200,
        duration_configuration_revision=1,
        operation=RuntimeWebOperationIdentity(
            actor_kind=RuntimeWebRequesterKind.USER,
            actor_id=user_id,
            execution_id="transport-test",
            operation_key=f"approve-{port}",
        ),
        active_session_limit=4,
        active_agent_limit=16,
    )
    assert approved.cycle is not None
    now = datetime.datetime.now(datetime.UTC)
    return RuntimeWebTunnelAuthority(
        tunnel_id=f"tunnel-{port}",
        endpoint_id=approved.endpoint.id,
        cycle_id=approved.cycle.id,
        endpoint_authority_revision=approved.endpoint.authority_revision,
        close_barrier=approved.endpoint.close_barrier,
        runtime_id=runtime.id,
        desired_generation=runtime.desired_generation,
        runner_generation=runtime.runner_generation,
        port=port,
        join_nonce=f"join-{port}",
        registration_deadline_at=now + datetime.timedelta(seconds=30),
        approval_deadline_at=approved.cycle.expires_at,
        transport_deadline_at=approved.cycle.expires_at,
    )


async def test_route_accepts_transport_inside_longer_approval_cycle(
    rdb_session: AsyncSession,
) -> None:
    """Keep cycle authority while bounding one finite HTTP transport."""
    authority = await _active_tunnel(rdb_session)
    transport_deadline = datetime.datetime.now(datetime.UTC) + datetime.timedelta(
        minutes=10
    )
    authority = authority.model_copy(
        update={"transport_deadline_at": transport_deadline}
    )

    route = await RuntimeWebTransportRepository().acquire_route(
        rdb_session,
        authority=authority,
        owner_replica_id="control-a",
        owner_boot_id="boot-a",
        owner_address="control-a.internal:8031",
        lease_seconds=30,
        maximum_active_connections=8,
    )

    assert route.authority.approval_deadline_at > transport_deadline
    assert route.authority.transport_deadline_at == transport_deadline


async def test_route_lease_rejects_live_owner_and_allows_expired_takeover(
    rdb_session: AsyncSession,
) -> None:
    """One owner remains current until both route and admission leases expire."""
    authority = await _active_tunnel(rdb_session)
    repository = RuntimeWebTransportRepository()
    first = await repository.acquire_route(
        rdb_session,
        authority=authority,
        owner_replica_id="control-a",
        owner_boot_id="boot-a",
        owner_address="control-a.internal:8031",
        lease_seconds=30,
        maximum_active_connections=8,
    )
    with pytest.raises(RuntimeWebRouteConflict, match="already owned"):
        await repository.acquire_route(
            rdb_session,
            authority=authority,
            owner_replica_id="control-b",
            owner_boot_id="boot-b",
            owner_address="control-b.internal:8031",
            lease_seconds=30,
            maximum_active_connections=8,
        )

    await rdb_session.execute(
        sa.update(RDBRuntimeWebTunnelRoute)
        .where(RDBRuntimeWebTunnelRoute.tunnel_id == authority.tunnel_id)
        .values(
            created_at=sa.func.clock_timestamp() - sa.text("INTERVAL '2 seconds'"),
            lease_expires_at=(
                sa.func.clock_timestamp() - sa.text("INTERVAL '1 second'")
            ),
        )
    )
    await rdb_session.execute(
        sa.update(RDBRuntimeWebAdmissionLease)
        .where(RDBRuntimeWebAdmissionLease.tunnel_id == authority.tunnel_id)
        .values(
            created_at=sa.func.clock_timestamp() - sa.text("INTERVAL '2 seconds'"),
            lease_expires_at=(
                sa.func.clock_timestamp() - sa.text("INTERVAL '1 second'")
            ),
        )
    )
    rdb_session.expire_all()

    replacement = await repository.acquire_route(
        rdb_session,
        authority=authority,
        owner_replica_id="control-b",
        owner_boot_id="boot-b",
        owner_address="control-b.internal:8031",
        lease_seconds=30,
        maximum_active_connections=8,
    )

    assert replacement.owner_boot_id == "boot-b"
    assert replacement.route_lease_id != first.route_lease_id
    assert replacement.lease_generation == first.lease_generation + 1


async def test_route_lookup_and_renewal_fail_after_authority_changes(
    rdb_session: AsyncSession,
) -> None:
    """Endpoint revision and lease identity fence lookup and renewal."""
    authority = await _active_tunnel(rdb_session)
    repository = RuntimeWebTransportRepository()
    route = await repository.acquire_route(
        rdb_session,
        authority=authority,
        owner_replica_id="control-a",
        owner_boot_id="boot-a",
        owner_address="control-a.internal:8031",
        lease_seconds=30,
        maximum_active_connections=8,
    )
    live = await repository.get_live_route(
        rdb_session,
        tunnel_id=authority.tunnel_id,
    )
    assert live == route

    with pytest.raises(RuntimeWebRouteConflict, match="stale"):
        await repository.renew_route(
            rdb_session,
            tunnel_id=authority.tunnel_id,
            route_lease_id="wrong-lease",
            owner_boot_id="boot-a",
            lease_generation=route.lease_generation,
            lease_seconds=30,
            allow_replaced_cycle=False,
        )

    await rdb_session.execute(
        sa.text(
            """
            UPDATE runtime_web_endpoints
            SET authority_revision = authority_revision + 1
            WHERE id = :endpoint_id
            """
        ),
        {"endpoint_id": authority.endpoint_id},
    )
    rdb_session.expire_all()

    assert (
        await repository.get_live_route(
            rdb_session,
            tunnel_id=authority.tunnel_id,
        )
        is None
    )


async def test_shared_admission_limit_counts_live_tunnels(
    rdb_session: AsyncSession,
) -> None:
    """A second tunnel is rejected while the shared connection slot is leased."""
    first_authority = await _active_tunnel(rdb_session, port=3000)
    second_authority = first_authority.model_copy(
        update={
            "tunnel_id": "tunnel-second",
            "join_nonce": "join-second",
        }
    )
    repository = RuntimeWebTransportRepository()
    await repository.acquire_route(
        rdb_session,
        authority=first_authority,
        owner_replica_id="control-a",
        owner_boot_id="boot-a",
        owner_address="control-a.internal:8031",
        lease_seconds=30,
        maximum_active_connections=1,
    )

    with pytest.raises(RuntimeWebAdmissionCapacityExceeded):
        await repository.acquire_route(
            rdb_session,
            authority=second_authority,
            owner_replica_id="control-a",
            owner_boot_id="boot-a",
            owner_address="control-a.internal:8031",
            lease_seconds=30,
            maximum_active_connections=1,
        )


async def test_replaced_cycle_allows_only_explicit_finite_http_renewal(
    rdb_session: AsyncSession,
) -> None:
    """Replacement preserves admitted finite HTTP but fences long-lived streams."""
    authority = await _active_tunnel(rdb_session)
    repository = RuntimeWebTransportRepository()
    route = await repository.acquire_route(
        rdb_session,
        authority=authority,
        owner_replica_id="control-a",
        owner_boot_id="boot-a",
        owner_address="control-a.internal:8031",
        lease_seconds=30,
        maximum_active_connections=8,
    )
    await rdb_session.execute(
        sa.update(RDBRuntimeWebCycle)
        .where(RDBRuntimeWebCycle.id == authority.cycle_id)
        .values(
            ended_at=sa.func.clock_timestamp(),
            end_reason=RuntimeWebCycleEndReason.REPLACED,
        )
    )
    await rdb_session.execute(
        sa.update(RDBRuntimeWebEndpoint)
        .where(RDBRuntimeWebEndpoint.id == authority.endpoint_id)
        .values(authority_revision=RDBRuntimeWebEndpoint.authority_revision + 1)
    )
    rdb_session.expire_all()

    with pytest.raises(RuntimeWebRouteConflict, match="renewal authority"):
        await repository.renew_route(
            rdb_session,
            tunnel_id=authority.tunnel_id,
            route_lease_id=route.route_lease_id,
            owner_boot_id=route.owner_boot_id,
            lease_generation=route.lease_generation,
            lease_seconds=30,
            allow_replaced_cycle=False,
        )

    renewed = await repository.renew_route(
        rdb_session,
        tunnel_id=authority.tunnel_id,
        route_lease_id=route.route_lease_id,
        owner_boot_id=route.owner_boot_id,
        lease_generation=route.lease_generation,
        lease_seconds=30,
        allow_replaced_cycle=True,
    )
    assert renewed.route_lease_id == route.route_lease_id
