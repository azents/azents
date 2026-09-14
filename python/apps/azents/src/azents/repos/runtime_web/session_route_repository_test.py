"""Inactive Runtime Web Owner-session route repository tests."""

import hashlib

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from azents.rdb.models.agent_runtime import RDBAgentRuntime
from azents.repos.runtime_web.repository_test import _authority_fixture
from azents.repos.runtime_web.session_route_repository import (
    RuntimeWebSessionRouteConflict,
    RuntimeWebSessionRouteRepository,
)


async def _runtime(session: AsyncSession) -> RDBAgentRuntime:
    workspace_id, agent_id, _, _ = await _authority_fixture(session)
    runtime = RDBAgentRuntime(workspace_id=workspace_id, agent_id=agent_id)
    session.add(runtime)
    await session.flush()
    runtime.desired_generation = 3
    runtime.runner_generation = 4
    await session.flush()
    return runtime


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


async def test_session_route_acquire_renew_drain_and_release(
    rdb_session: AsyncSession,
) -> None:
    runtime = await _runtime(rdb_session)
    repository = RuntimeWebSessionRouteRepository()
    route = await repository.acquire(
        rdb_session,
        runtime_id=runtime.id,
        desired_generation=3,
        runner_generation=4,
        owner_replica_id="control-a",
        owner_boot_id="boot-a",
        owner_address="control-a.internal:8032",
        join_nonce_hash=_digest("nonce-a"),
        protocol_fingerprint=_digest("protocol"),
        lease_seconds=30,
    )

    renewed = await repository.renew(
        rdb_session,
        runtime_id=runtime.id,
        owner_boot_id=route.owner_boot_id,
        session_lease_id=route.session_lease_id,
        lease_generation=route.lease_generation,
        protocol_fingerprint=route.protocol_fingerprint,
        lease_seconds=60,
    )
    assert renewed.lease_expires_at > route.lease_expires_at

    draining = await repository.mark_draining(
        rdb_session,
        runtime_id=runtime.id,
        owner_boot_id=route.owner_boot_id,
        session_lease_id=route.session_lease_id,
        lease_generation=route.lease_generation,
    )
    assert draining.draining_at is not None

    assert await repository.release(
        rdb_session,
        runtime_id=runtime.id,
        owner_boot_id=route.owner_boot_id,
        session_lease_id=route.session_lease_id,
        lease_generation=route.lease_generation,
    )


async def test_session_route_rejects_live_second_owner(
    rdb_session: AsyncSession,
) -> None:
    runtime = await _runtime(rdb_session)
    repository = RuntimeWebSessionRouteRepository()
    await repository.acquire(
        rdb_session,
        runtime_id=runtime.id,
        desired_generation=3,
        runner_generation=4,
        owner_replica_id="control-a",
        owner_boot_id="boot-a",
        owner_address="control-a.internal:8032",
        join_nonce_hash=_digest("nonce-a"),
        protocol_fingerprint=_digest("protocol"),
        lease_seconds=30,
    )

    with pytest.raises(RuntimeWebSessionRouteConflict):
        await repository.acquire(
            rdb_session,
            runtime_id=runtime.id,
            desired_generation=3,
            runner_generation=4,
            owner_replica_id="control-a",
            owner_boot_id="boot-b",
            owner_address="control-a.internal:8032",
            join_nonce_hash=_digest("nonce-b"),
            protocol_fingerprint=_digest("protocol"),
            lease_seconds=30,
        )


async def test_session_route_rejects_replaced_runner_generation(
    rdb_session: AsyncSession,
) -> None:
    runtime = await _runtime(rdb_session)
    repository = RuntimeWebSessionRouteRepository()
    route = await repository.acquire(
        rdb_session,
        runtime_id=runtime.id,
        desired_generation=3,
        runner_generation=4,
        owner_replica_id="control-a",
        owner_boot_id="boot-a",
        owner_address="control-a.internal:8032",
        join_nonce_hash=_digest("nonce-a"),
        protocol_fingerprint=_digest("protocol"),
        lease_seconds=30,
    )
    runtime.runner_generation = 5
    await rdb_session.flush()

    assert (
        await repository.resolve(
            rdb_session,
            runtime_id=runtime.id,
            desired_generation=3,
            runner_generation=4,
            protocol_fingerprint=route.protocol_fingerprint,
        )
        is None
    )
    with pytest.raises(RuntimeWebSessionRouteConflict):
        await repository.renew(
            rdb_session,
            runtime_id=runtime.id,
            owner_boot_id=route.owner_boot_id,
            session_lease_id=route.session_lease_id,
            lease_generation=route.lease_generation,
            protocol_fingerprint=route.protocol_fingerprint,
            lease_seconds=30,
        )


async def test_session_route_resolve_rejects_draining_route(
    rdb_session: AsyncSession,
) -> None:
    runtime = await _runtime(rdb_session)
    repository = RuntimeWebSessionRouteRepository()
    route = await repository.acquire(
        rdb_session,
        runtime_id=runtime.id,
        desired_generation=3,
        runner_generation=4,
        owner_replica_id="control-a",
        owner_boot_id="boot-a",
        owner_address="control-a.internal:8032",
        join_nonce_hash=_digest("nonce-a"),
        protocol_fingerprint=_digest("protocol"),
        lease_seconds=30,
    )
    assert await repository.resolve(
        rdb_session,
        runtime_id=runtime.id,
        desired_generation=3,
        runner_generation=4,
        protocol_fingerprint=route.protocol_fingerprint,
    )

    await repository.mark_draining(
        rdb_session,
        runtime_id=runtime.id,
        owner_boot_id=route.owner_boot_id,
        session_lease_id=route.session_lease_id,
        lease_generation=route.lease_generation,
    )

    assert (
        await repository.resolve(
            rdb_session,
            runtime_id=runtime.id,
            desired_generation=3,
            runner_generation=4,
            protocol_fingerprint=route.protocol_fingerprint,
        )
        is None
    )


async def test_session_route_join_nonce_is_consumed_once(
    rdb_session: AsyncSession,
) -> None:
    runtime = await _runtime(rdb_session)
    repository = RuntimeWebSessionRouteRepository()
    route = await repository.acquire(
        rdb_session,
        runtime_id=runtime.id,
        desired_generation=3,
        runner_generation=4,
        owner_replica_id="control-a",
        owner_boot_id="boot-a",
        owner_address="control-a.internal:8032",
        join_nonce_hash=_digest("nonce-a"),
        protocol_fingerprint=_digest("protocol"),
        lease_seconds=30,
    )
    await repository.consume_join(
        rdb_session,
        runtime_id=runtime.id,
        owner_boot_id=route.owner_boot_id,
        session_lease_id=route.session_lease_id,
        lease_generation=route.lease_generation,
        protocol_fingerprint=route.protocol_fingerprint,
        join_nonce_hash=_digest("nonce-a"),
        join_deadline_at=route.lease_expires_at,
    )

    with pytest.raises(RuntimeWebSessionRouteConflict):
        await repository.consume_join(
            rdb_session,
            runtime_id=runtime.id,
            owner_boot_id=route.owner_boot_id,
            session_lease_id=route.session_lease_id,
            lease_generation=route.lease_generation,
            protocol_fingerprint=route.protocol_fingerprint,
            join_nonce_hash=_digest("nonce-a"),
            join_deadline_at=route.lease_expires_at,
        )
