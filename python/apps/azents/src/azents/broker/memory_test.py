"""Deterministic single-process broker contract tests."""

import asyncio
from contextlib import suppress
from dataclasses import dataclass
from typing import Literal

import pytest

from azents.broker.memory import InMemoryBroker, InMemoryBrokerState
from azents.broker.types import SessionMailboxActivity, SessionStopSignal, SessionWakeUp


@dataclass
class _Clock:
    now: float

    def __call__(self) -> float:
        return self.now


class _ObservedCondition(asyncio.Condition):
    def __init__(self) -> None:
        super().__init__()
        self.waiting = asyncio.Event()

    async def wait(self) -> Literal[True]:
        self.waiting.set()
        return await super().wait()


@dataclass(frozen=True)
class _Harness:
    clock: _Clock
    state: InMemoryBrokerState
    condition: _ObservedCondition
    api: InMemoryBroker
    first: InMemoryBroker
    second: InMemoryBroker


@pytest.fixture
def harness() -> _Harness:
    clock = _Clock(0)
    state = InMemoryBrokerState(clock=clock)
    condition = _ObservedCondition()
    state.changed = condition
    return _Harness(
        clock,
        state,
        condition,
        InMemoryBroker(state, worker_id=None),
        InMemoryBroker(state, worker_id="first"),
        InMemoryBroker(state, worker_id="second"),
    )


@pytest.mark.asyncio
async def test_ordered_session_drain_and_session_isolation(harness: _Harness) -> None:
    wake = SessionWakeUp("one")
    stop = SessionStopSignal("one")
    other = SessionWakeUp("two")
    await harness.api.send_message(wake)
    await harness.api.send_message(stop)
    await harness.api.send_message(other)
    assert await harness.first.receive_messages() == [wake, stop]
    assert await harness.first.receive_messages() == [other]
    assert not harness.state.messages


@pytest.mark.asyncio
async def test_live_owner_is_not_stolen_and_receives_direct_wake(
    harness: _Harness,
) -> None:
    await harness.api.send_message(SessionWakeUp("s"))
    await harness.first.receive_messages()
    receiver = asyncio.create_task(harness.second.receive_messages())
    await asyncio.wait_for(harness.condition.waiting.wait(), 1)
    try:
        await harness.api.send_message(SessionStopSignal("s"))
        assert await harness.first.receive_messages() == [SessionStopSignal("s")]
        assert harness.state.owners["s"].worker_id == "first"
        assert not receiver.done()
        await harness.second.release_session_lock("s")
        assert harness.state.owners["s"].worker_id == "first"
    finally:
        receiver.cancel()
        with suppress(asyncio.CancelledError):
            await receiver


@pytest.mark.asyncio
async def test_expired_heartbeat_allows_takeover_and_fences_old_renewal(
    harness: _Harness,
) -> None:
    await harness.api.send_message(SessionWakeUp("s"))
    await harness.first.receive_messages()
    harness.clock.now = 121
    await harness.api.send_message(SessionWakeUp("s"))
    assert await harness.second.receive_messages() == [SessionWakeUp("s")]
    before = harness.state.owners["s"].heartbeat_until
    harness.clock.now = 130
    await harness.first.renew_session_owner_heartbeat("s")
    await harness.first.renew_session_ttl("s")
    await harness.first.release_session_lock("s")
    assert harness.state.owners["s"].worker_id == "second"
    assert harness.state.owners["s"].heartbeat_until == before


@pytest.mark.asyncio
async def test_idle_heartbeat_refresh_and_exact_release(harness: _Harness) -> None:
    await harness.api.send_message(SessionWakeUp("s"))
    await harness.first.receive_messages()
    harness.clock.now = 100
    await harness.first.renew_session_owner_heartbeat("s")
    assert harness.state.owners["s"].heartbeat_until == 220
    assert harness.state.owners["s"].lease_until == 1800
    harness.clock.now = 150
    await harness.api.send_message(SessionWakeUp("s"))
    assert await harness.first.receive_messages() == [SessionWakeUp("s")]
    await harness.first.release_session_lock("s")
    assert "s" not in harness.state.owners


@pytest.mark.asyncio
async def test_mailbox_hints_only_reach_live_owners(harness: _Harness) -> None:
    await harness.first.notify_mailbox_activity("idle")
    assert not harness.state.incoming and not harness.state.direct
    await harness.api.send_message(SessionWakeUp("s"))
    await harness.first.receive_messages()
    await harness.second.notify_mailbox_activity("s")
    assert await harness.first.receive_messages() == [SessionMailboxActivity("s")]
    harness.clock.now = 121
    await harness.second.notify_mailbox_activity("s")
    assert not harness.state.direct.get("first")
    with pytest.raises(RuntimeError, match="Worker broker"):
        await harness.api.notify_mailbox_activity("s")


@pytest.mark.asyncio
async def test_generation_activity_tombstone_and_expiry(harness: _Harness) -> None:
    assert await harness.first.set_session_activity(
        "s", owner_generation=2, run_id="new"
    )
    assert not await harness.second.set_session_activity(
        "s", owner_generation=1, run_id="old"
    )
    assert not await harness.second.clear_session_activity("s", owner_generation=1)
    activity = await harness.api.get_session_activity("s")
    assert activity is not None and activity.run_id == "new"
    assert await harness.first.clear_session_activity("s", owner_generation=2)
    assert await harness.api.get_session_activity("s") is None
    assert not await harness.second.set_session_activity(
        "s", owner_generation=1, run_id="old"
    )
    assert await harness.second.set_session_activity(
        "s", owner_generation=3, run_id="next"
    )
    harness.clock.now = 31
    assert await harness.api.get_session_activity("s") is None
    assert "s" not in harness.state.activities


@pytest.mark.asyncio
async def test_purge_preserves_separately_owned_cutover_barrier(
    harness: _Harness,
) -> None:
    await harness.api.send_message(SessionWakeUp("s"))
    await harness.first.receive_messages()
    await harness.first.set_session_activity("s", owner_generation=1, run_id="r")
    await harness.api.send_message(SessionStopSignal("s"))
    token = await harness.api.acquire_cutover_replay_barrier(("s",))
    await harness.api.purge_session_state("s")
    assert "s" not in harness.state.messages
    assert "s" not in harness.state.owners
    assert "s" not in harness.state.activities
    assert harness.state.barriers["s"].token == token
    await harness.api.release_cutover_replay_barrier(("s",), token)


@pytest.mark.asyncio
async def test_cutover_blocks_receive_until_exact_release(harness: _Harness) -> None:
    token = await harness.api.acquire_cutover_replay_barrier(("s",))
    await harness.api.send_message(SessionWakeUp("s"))
    receiver = asyncio.create_task(harness.first.receive_messages())
    await asyncio.wait_for(harness.condition.waiting.wait(), 1)
    assert "s" not in harness.state.owners
    await harness.api.release_cutover_replay_barrier(("s",), "foreign")
    assert harness.state.barriers["s"].token == token and not receiver.done()
    assert await harness.api.renew_cutover_replay_barrier(("s",), token)
    await harness.api.release_cutover_replay_barrier(("s",), token)
    assert await asyncio.wait_for(receiver, 1) == [SessionWakeUp("s")]


@pytest.mark.asyncio
async def test_failed_batch_acquire_is_atomic_and_expired_token_cannot_adopt(
    harness: _Harness,
) -> None:
    token = await harness.api.acquire_cutover_replay_barrier(("b",))
    with pytest.raises(RuntimeError, match="already active"):
        await harness.api.acquire_cutover_replay_barrier(("a", "b"))
    assert "a" not in harness.state.barriers
    harness.clock.now = 3601
    replacement = await harness.api.acquire_cutover_replay_barrier(("b",))
    assert replacement != token
    assert not await harness.api.renew_cutover_replay_barrier(("b",), token)
    await harness.api.release_cutover_replay_barrier(("b",), token)
    assert harness.state.barriers["b"].token == replacement


@pytest.mark.asyncio
async def test_barrier_expiry_is_observed_without_scheduler_delays(
    harness: _Harness,
) -> None:
    await harness.api.acquire_cutover_replay_barrier(("s",))
    await harness.api.send_message(SessionWakeUp("s"))
    harness.clock.now = 3601
    assert await harness.first.receive_messages() == [SessionWakeUp("s")]
    assert "s" not in harness.state.barriers


@pytest.mark.asyncio
async def test_close_unblocks_receiver_and_rejects_later_operations(
    harness: _Harness,
) -> None:
    receiver = asyncio.create_task(harness.first.receive_messages())
    await asyncio.wait_for(harness.condition.waiting.wait(), 1)
    await harness.state.aclose()
    with pytest.raises(RuntimeError, match="closed"):
        await asyncio.wait_for(receiver, 1)
    with pytest.raises(RuntimeError, match="closed"):
        await harness.api.send_message(SessionWakeUp("s"))


@pytest.mark.asyncio
async def test_cancelled_wait_does_not_consume_subsequent_work(
    harness: _Harness,
) -> None:
    receiver = asyncio.create_task(harness.first.receive_messages())
    await asyncio.wait_for(harness.condition.waiting.wait(), 1)
    receiver.cancel()
    with pytest.raises(asyncio.CancelledError):
        await receiver
    await harness.api.send_message(SessionWakeUp("s"))
    assert await harness.second.receive_messages() == [SessionWakeUp("s")]


@pytest.mark.asyncio
async def test_unused_ephemeral_records_expire(harness: _Harness) -> None:
    await harness.api.send_message(SessionWakeUp("old"))
    await harness.first.set_session_activity("unused", owner_generation=1, run_id="r")
    harness.clock.now = 86401
    assert await harness.api.get_session_activity("unused") is None
    assert not harness.state.messages and not harness.state.activities
