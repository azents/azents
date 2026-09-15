"""Tests for the inactive accepting-Control Runtime Web broker."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta

import pytest
from azents_runtime_control.runtime_web_capacity import (
    ActiveCapacityStream,
    CapacityProfile,
    InMemoryRuntimeWebCapacityCoordinator,
)
from azents_runtime_control.runtime_web_session import (
    OwnerSessionEpoch,
    StreamAuthority,
    StreamProtocol,
)

from azents.runtime.web_session_broker import (
    BrokerStreamKey,
    BrokerTarget,
    RuntimeWebSessionBroker,
)


def _owner(*, desired_generation: int = 1) -> OwnerSessionEpoch:
    return OwnerSessionEpoch(
        owner_boot_id="owner",
        session_lease_id="lease",
        lease_generation=1,
        runtime_id="runtime",
        desired_generation=desired_generation,
        runner_generation=1,
    )


def _authority() -> StreamAuthority:
    now = datetime.now(UTC)
    return StreamAuthority(
        correlation_id="correlation",
        endpoint_id="endpoint",
        cycle_id="cycle",
        endpoint_authority_revision=1,
        close_barrier=1,
        identity_id="identity",
        authentication_session_id="authentication",
        user_id="user",
        agent_session_id="agent-session",
        runtime_id="runtime",
        desired_generation=1,
        runner_generation=1,
        port=6006,
        open_deadline_at=now + timedelta(seconds=10),
        transport_deadline_at=now + timedelta(minutes=1),
        approval_deadline_at=now + timedelta(hours=1),
    )


class _Router:
    def __init__(self, target: BrokerTarget | None) -> None:
        self.target = target

    async def resolve(self, authority: StreamAuthority) -> BrokerTarget | None:
        assert authority.runtime_id == "runtime"
        assert authority.desired_generation == 1
        assert authority.runner_generation == 1
        return self.target


def _profile(*, maximum_active_streams: int = 2) -> CapacityProfile:
    return CapacityProfile(
        maximum_active_streams=maximum_active_streams,
        maximum_sse_streams=1,
        maximum_websocket_streams=1,
        maximum_pending_opens=2,
        maximum_buffer_bytes=1024,
        inbound_bytes_per_second=1024,
        outbound_bytes_per_second=1024,
        burst_bytes=1024,
    )


def _capacity(
    *, maximum_active_streams: int = 2
) -> InMemoryRuntimeWebCapacityCoordinator:
    return InMemoryRuntimeWebCapacityCoordinator(
        epoch="epoch",
        profile=_profile(maximum_active_streams=maximum_active_streams),
        monotonic_clock_milliseconds=lambda: 0,
    )


@pytest.mark.parametrize(
    ("local", "relay_count"),
    [(True, 1), (False, 0), (True, 2), (False, 2)],
)
def test_broker_target_rejects_invalid_relay_topology(
    local: bool, relay_count: int
) -> None:
    with pytest.raises(ValueError, match="topology"):
        BrokerTarget(owner=_owner(), local=local, relay_count=relay_count)


@pytest.mark.asyncio
async def test_broker_scopes_capacity_by_source_session_and_releases_exactly() -> None:
    capacity = _capacity()
    target = BrokerTarget(owner=_owner(), local=False, relay_count=1)
    broker = RuntimeWebSessionBroker(router=_Router(target), capacity=capacity)
    first_key = BrokerStreamKey("gateway-a", 1)
    second_key = BrokerStreamKey("gateway-b", 1)

    first = await broker.admit(
        key=first_key,
        authority=_authority(),
        protocol=StreamProtocol.HTTP,
    )
    second = await broker.admit(
        key=second_key,
        authority=_authority(),
        protocol=StreamProtocol.WEBSOCKET,
    )
    assert first is not None
    assert second is not None
    assert first.target == target
    assert first.capacity_stream_id != second.capacity_stream_id
    assert (await capacity.snapshot()).active_streams == 2
    assert await broker.release(first_key)
    assert not await broker.release(first_key)
    assert (await capacity.snapshot()).active_streams == 1
    with pytest.raises(ValueError, match="not reusable"):
        await broker.admit(
            key=first_key,
            authority=_authority(),
            protocol=StreamProtocol.HTTP,
        )


@pytest.mark.asyncio
async def test_broker_rejects_missing_stale_and_exhausted_targets() -> None:
    capacity = _capacity(maximum_active_streams=1)
    missing = RuntimeWebSessionBroker(router=_Router(None), capacity=capacity)
    assert (
        await missing.admit(
            key=BrokerStreamKey("gateway", 1),
            authority=_authority(),
            protocol=StreamProtocol.HTTP,
        )
        is None
    )
    stale = RuntimeWebSessionBroker(
        router=_Router(
            BrokerTarget(
                owner=_owner(desired_generation=2),
                local=True,
                relay_count=0,
            )
        ),
        capacity=capacity,
    )
    with pytest.raises(ValueError, match="Owner epoch"):
        await stale.admit(
            key=BrokerStreamKey("gateway", 2),
            authority=_authority(),
            protocol=StreamProtocol.HTTP,
        )
    admitted = RuntimeWebSessionBroker(
        router=_Router(BrokerTarget(owner=_owner(), local=True, relay_count=0)),
        capacity=capacity,
    )
    assert await admitted.admit(
        key=BrokerStreamKey("gateway", 3),
        authority=_authority(),
        protocol=StreamProtocol.HTTP,
    )
    exhausted_key = BrokerStreamKey("gateway", 4)
    assert (
        await admitted.admit(
            key=exhausted_key,
            authority=_authority(),
            protocol=StreamProtocol.HTTP,
        )
        is None
    )
    assert exhausted_key in admitted.tombstone_set


class _FailingCapacity(InMemoryRuntimeWebCapacityCoordinator):
    def __init__(self, *, cancelled: bool) -> None:
        super().__init__(
            epoch="epoch",
            profile=_profile(),
            monotonic_clock_milliseconds=lambda: 0,
        )
        self.cancelled = cancelled

    async def accept_open(self, stream: ActiveCapacityStream) -> bool:
        if self.cancelled:
            raise asyncio.CancelledError
        raise RuntimeError("capacity failed")


@pytest.mark.asyncio
@pytest.mark.parametrize("cancelled", [False, True])
async def test_broker_rolls_back_pending_capacity_on_failure(
    cancelled: bool,
) -> None:
    capacity = _FailingCapacity(cancelled=cancelled)
    broker = RuntimeWebSessionBroker(
        router=_Router(BrokerTarget(owner=_owner(), local=True, relay_count=0)),
        capacity=capacity,
    )
    key = BrokerStreamKey("gateway", 1)
    expected = asyncio.CancelledError if cancelled else RuntimeError
    with pytest.raises(expected):
        await broker.admit(
            key=key,
            authority=_authority(),
            protocol=StreamProtocol.HTTP,
        )
    snapshot = await capacity.snapshot()
    assert snapshot.pending_opens == 0
    assert snapshot.active_streams == 0
    assert key in broker.tombstone_set
