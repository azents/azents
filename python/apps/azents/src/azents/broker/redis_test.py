"""RedisBroker integration tests."""

from collections.abc import AsyncGenerator
from typing import Any, cast
from unittest.mock import AsyncMock, call

import pytest
import pytest_asyncio
from redis.asyncio import Redis

from .redis import (
    RedisBroker,
    _decode_wake_up_response,
    decode_broker_message,
    decode_session_wake_up,
    encode_session_wake_up,
)
from .types import SessionMailboxActivity, SessionStopSignal, SessionWakeUp


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


@pytest.mark.parametrize(
    ("message_type", "expected_signal"),
    [
        (None, SessionWakeUp(session_id="session-1")),
        (b"mailbox_activity", SessionMailboxActivity(session_id="session-1")),
    ],
)
def test_decode_resp2_wake_up_response(
    message_type: bytes | None,
    expected_signal: SessionWakeUp | SessionMailboxActivity,
) -> None:
    """RESP2 XREADGROUP responses decode into typed broker wake-ups."""
    fields = {b"session_id": b"session-1"}
    if message_type is not None:
        fields[b"type"] = message_type

    wake_up = _decode_wake_up_response([[b"azents:incoming", [(b"123-0", fields)]]])

    assert wake_up.stream_name == b"azents:incoming"
    assert wake_up.entry_id == b"123-0"
    assert wake_up.session_id == "session-1"
    assert wake_up.signal == expected_signal


def test_decode_wake_up_response_rejects_resp3_mapping() -> None:
    """RESP3 mappings with legacy_responses=False fail clearly outside the factory."""
    with pytest.raises(RuntimeError, match="must contain one stream"):
        _decode_wake_up_response(
            {b"azents:incoming": [(b"123-0", {b"session_id": b"session-1"})]}
        )


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

    async def test_mailbox_activity_routes_to_existing_owner(
        self,
        redis: Redis,
    ) -> None:
        """Mailbox activity reaches a live owner without creating a wake-up."""
        sender = RedisBroker(redis)
        worker = RedisBroker(redis, worker_id="worker-1")
        await worker.setup()
        wake_up = SessionWakeUp(session_id="session-1")

        await sender.send_message(wake_up)
        assert await worker.receive_messages() == [wake_up]

        await worker.notify_mailbox_activity(wake_up.session_id)

        assert await worker.receive_messages() == [
            SessionMailboxActivity(session_id=wake_up.session_id)
        ]

    async def test_mailbox_activity_is_dropped_without_live_owner(
        self,
        redis: Redis,
    ) -> None:
        """Idle sessions do not receive mailbox-only activity signals."""
        worker = RedisBroker(redis, worker_id="worker-1")
        await worker.setup()

        await worker.notify_mailbox_activity("session-1")

        assert await redis.xlen("azents:worker:worker-1:incoming") == 0

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
