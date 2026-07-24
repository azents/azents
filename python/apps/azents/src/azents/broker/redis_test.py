"""RedisBroker integration tests."""

from collections.abc import AsyncGenerator
from typing import Any, cast
from unittest.mock import AsyncMock, call

import pytest
import pytest_asyncio
from redis.asyncio import Redis

from .redis import (
    RedisBroker,
    decode_broker_message,
    decode_session_wake_up,
    encode_session_wake_up,
)
from .types import SessionStopSignal, SessionWakeUp


@pytest_asyncio.fixture
async def redis(redis_url: str) -> AsyncGenerator[Redis, None]:
    """Redis client for tests."""
    client = Redis.from_url(redis_url)
    await client.flushall()
    try:
        yield client
    finally:
        await client.aclose()


class TestSessionWakeUpEncoding:
    """SessionWakeUp encoding tests."""

    def test_roundtrip(self) -> None:
        """Verify serialization/deserialization roundtrip."""
        message = SessionWakeUp(session_id="session-1")

        decoded = decode_session_wake_up(encode_session_wake_up(message))

        assert decoded == message

    @pytest.mark.parametrize(
        "raw",
        [
            b'{"session_id":"session-1","type":"session_wake_up","agent_id":"agent-1"}',
            b'{"session_id":"session-1","type":"session_wake_up","user_id":"user-1"}',
            b'{"session_id":"session-1","type":"session_wake_up","sender_user_id":"user-1"}',
            b'{"session_id":"session-1","type":"session_wake_up","pending_command":{"name":"resume"}}',
        ],
    )
    def test_rejects_rich_legacy_payload(self, raw: bytes) -> None:
        """Legacy wake-up fields cannot bypass the routing-only contract."""
        with pytest.raises(ValueError, match="only session_id and type"):
            decode_session_wake_up(raw)


@pytest.mark.parametrize(
    "raw",
    [
        b'{"session_id":"session-1","type":"session_wake_up","workspace_id":"workspace-1"}',
        b'{"session_id":"session-1","type":"session_stop_signal","user_id":"user-1"}',
    ],
)
def test_decode_broker_message_rejects_rich_legacy_payload(raw: bytes) -> None:
    """Wake-up and stop signals reject deprecated execution identity fields."""
    with pytest.raises(ValueError, match="only session_id and type"):
        decode_broker_message(raw)


class TestRedisBrokerSetup:
    """setup() tests."""

    async def test_setup_creates_consumer_group(self, redis: Redis) -> None:
        """Consumer group is created."""
        broker = RedisBroker(redis)

        await broker.setup()

        groups = await redis.xinfo_groups("azents:incoming")
        assert len(groups) == 1

    async def test_setup_idempotent(self, redis: Redis) -> None:
        """setup() is safe to call multiple times."""
        broker = RedisBroker(redis)

        await broker.setup()
        await broker.setup()

        groups = await redis.xinfo_groups("azents:incoming")
        assert len(groups) == 1


async def test_purge_session_state_avoids_cross_slot_delete() -> None:
    """Cluster-incompatible key groups are deleted in separate commands."""
    redis = AsyncMock()
    broker = RedisBroker(cast(Redis, redis))

    await broker.purge_session_state("session-1")

    assert redis.delete.await_args_list == [
        call("azents:session:session-1:messages"),
        call(
            "azents:session:{session-1}:lock",
            "azents:session:{session-1}:owner-heartbeat",
        ),
        call("azents:session:session-1:activity"),
    ]


class TestRedisBrokerMessages:
    """Broker wake/signal send/receive tests."""

    async def test_send_and_receive_session_wake_up(self, redis: Redis) -> None:
        """Worker receives SessionWakeUp."""
        sender = RedisBroker(redis)
        worker = RedisBroker(redis, worker_id="worker-1")
        await worker.setup()
        message = SessionWakeUp(session_id="session-1")

        await sender.send_message(message)
        received = await worker.receive_messages()

        assert received == [message]

    async def test_send_and_receive_stop_signal(self, redis: Redis) -> None:
        """Worker receives SessionStopSignal."""
        sender = RedisBroker(redis)
        worker = RedisBroker(redis, worker_id="worker-1")
        await worker.setup()
        message = SessionStopSignal(session_id="session-1")

        await sender.send_message(message)
        received = await worker.receive_messages()

        assert received == [message]

    async def test_cutover_barrier_blocks_new_session_ownership(
        self,
        redis: Redis,
    ) -> None:
        """Workers cannot acquire Session ownership during replay fencing."""
        operator = RedisBroker(redis)
        worker = RedisBroker(redis, worker_id="worker-1")
        worker_any = cast(Any, worker)

        token = await operator.acquire_cutover_replay_barrier(("session-1",))
        blocked = await worker_any._acquire_or_find_owner("session-1")
        assert await operator.renew_cutover_replay_barrier(
            ("session-1",),
            token,
        )
        await operator.release_cutover_replay_barrier(("session-1",), token)
        acquired = await worker_any._acquire_or_find_owner("session-1")

        assert blocked.status == "cutover"
        assert acquired.status == "acquired"

    async def test_recreates_missing_direct_stream_group(self, redis: Redis) -> None:
        """Worker recreates a missing owner direct stream group and receives."""
        sender = RedisBroker(redis)
        worker = RedisBroker(redis, worker_id="worker-1")
        await worker.setup()
        first = SessionWakeUp(session_id="session-1")
        second = SessionWakeUp(session_id=first.session_id)

        await sender.send_message(first)
        assert await worker.receive_messages() == [first]

        await redis.delete("azents:worker:worker-1:incoming")
        await sender.send_message(second)

        assert await worker.receive_messages() == [second]
