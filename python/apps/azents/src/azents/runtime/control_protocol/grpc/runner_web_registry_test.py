"""Process-local Runtime Web owner registry tests."""

import dataclasses
import datetime

import pytest
from azents_runtime_control.runner_web import (
    RunnerWebBodyChunk,
    RunnerWebHeader,
    RunnerWebProtocol,
    RunnerWebRequestHead,
    RunnerWebResponseHead,
    RunnerWebStreamEnd,
    RunnerWebStreamErrorCode,
)

from azents.repos.runtime_web.data import (
    RuntimeWebTunnelAuthority,
    RuntimeWebTunnelRoute,
)
from azents.runtime.control_protocol.grpc.runner_web_registry import (
    RuntimeWebOwnerRegistry,
    RuntimeWebTunnelAdmissionError,
    _runner_identity,
)


def _route(now: datetime.datetime) -> RuntimeWebTunnelRoute:
    return RuntimeWebTunnelRoute(
        authority=RuntimeWebTunnelAuthority(
            tunnel_id="tunnel-1",
            endpoint_id="endpoint-1",
            cycle_id="cycle-1",
            endpoint_authority_revision=4,
            close_barrier=2,
            runtime_id="runtime-1",
            desired_generation=3,
            runner_generation=5,
            port=3000,
            join_nonce="nonce-1",
            registration_deadline_at=now + datetime.timedelta(seconds=30),
            approval_deadline_at=now + datetime.timedelta(minutes=5),
            transport_deadline_at=now + datetime.timedelta(minutes=5),
        ),
        owner_replica_id="control-a",
        owner_boot_id="boot-a",
        owner_address="control-a.internal:8032",
        route_lease_id="lease-1",
        lease_generation=1,
        lease_expires_at=now + datetime.timedelta(seconds=30),
        admission_lease_id="admission-1",
    )


async def test_registry_relays_ordered_http_frames_without_storage() -> None:
    """Owner and Runner halves preserve request and response ordering."""
    now = datetime.datetime(2026, 9, 12, 12, tzinfo=datetime.UTC)
    route = _route(now)
    registry = RuntimeWebOwnerRegistry(clock=lambda: now)
    owner = await registry.create_owner(route)
    runner = await registry.join_runner(_runner_identity(route))

    await owner.send(
        RunnerWebRequestHead(
            identity=_runner_identity(route),
            protocol=RunnerWebProtocol.HTTP,
            method=b"POST",
            target=b"/events",
            headers=(RunnerWebHeader(b"content-type", b"text/plain"),),
        )
    )
    await owner.send(RunnerWebBodyChunk(sequence=1, data=b"request"))
    await owner.send(RunnerWebStreamEnd(final_sequence=1))
    controls = runner.control_frames().__aiter__()

    assert isinstance(await anext(controls), RunnerWebRequestHead)
    assert await anext(controls) == RunnerWebBodyChunk(sequence=1, data=b"request")
    assert await anext(controls) == RunnerWebStreamEnd(final_sequence=1)

    await runner.receive(RunnerWebResponseHead(status=200, headers=()))
    assert owner.allows_replaced_cycle
    await runner.receive(RunnerWebBodyChunk(sequence=1, data=b"response"))
    await runner.receive(RunnerWebStreamEnd(final_sequence=1))
    events = owner.events().__aiter__()

    assert await anext(events) == RunnerWebResponseHead(status=200, headers=())
    assert await anext(events) == RunnerWebBodyChunk(sequence=1, data=b"response")
    assert await anext(events) == RunnerWebStreamEnd(final_sequence=1)
    with pytest.raises(StopAsyncIteration):
        await anext(events)


async def test_registry_rejects_duplicate_and_stale_runner_joins() -> None:
    """Only the exact route identity can join once."""
    now = datetime.datetime(2026, 9, 12, 12, tzinfo=datetime.UTC)
    route = _route(now)
    registry = RuntimeWebOwnerRegistry(clock=lambda: now)
    await registry.create_owner(route)
    identity = _runner_identity(route)
    await registry.join_runner(identity)

    with pytest.raises(RuntimeWebTunnelAdmissionError) as duplicate:
        await registry.join_runner(identity)
    assert duplicate.value.code is RunnerWebStreamErrorCode.DUPLICATE_JOIN

    stale = dataclasses.replace(
        identity,
        runner_generation=identity.runner_generation + 1,
    )
    with pytest.raises(RuntimeWebTunnelAdmissionError) as rejected:
        await registry.join_runner(stale)
    assert rejected.value.code is RunnerWebStreamErrorCode.STALE_AUTHORITY


async def test_registry_rejects_sequence_gaps() -> None:
    """Frame gaps terminate admission instead of silently reordering bytes."""
    now = datetime.datetime(2026, 9, 12, 12, tzinfo=datetime.UTC)
    route = _route(now)
    registry = RuntimeWebOwnerRegistry(clock=lambda: now)
    owner = await registry.create_owner(route)
    await registry.join_runner(_runner_identity(route))
    await owner.send(
        RunnerWebRequestHead(
            identity=_runner_identity(route),
            protocol=RunnerWebProtocol.HTTP,
            method=b"POST",
            target=b"/",
            headers=(),
        )
    )

    with pytest.raises(RuntimeWebTunnelAdmissionError) as rejected:
        await owner.send(RunnerWebBodyChunk(sequence=2, data=b"gap"))
    assert rejected.value.code is RunnerWebStreamErrorCode.PROTOCOL_VIOLATION


async def test_server_sent_events_does_not_survive_cycle_replacement() -> None:
    """SSE is long-lived HTTP and must not use finite-response replacement grace."""
    now = datetime.datetime(2026, 9, 12, 12, tzinfo=datetime.UTC)
    route = _route(now)
    registry = RuntimeWebOwnerRegistry(clock=lambda: now)
    owner = await registry.create_owner(route)
    runner = await registry.join_runner(_runner_identity(route))
    await owner.send(
        RunnerWebRequestHead(
            identity=_runner_identity(route),
            protocol=RunnerWebProtocol.HTTP,
            method=b"GET",
            target=b"/events",
            headers=(),
        )
    )
    await runner.receive(
        RunnerWebResponseHead(
            status=200,
            headers=(
                RunnerWebHeader(
                    name=b"Content-Type",
                    value=b"text/event-stream; charset=utf-8",
                ),
            ),
        )
    )

    assert not owner.allows_replaced_cycle
