"""RedisBroker integration tests."""

import dataclasses
from collections.abc import AsyncGenerator

import pytest_asyncio
from redis.asyncio import Redis

from .redis import RedisBroker, decode_session_wake_up, encode_session_wake_up
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
        message = SessionWakeUp(
            agent_id="agent-1",
            session_id="session-1",
            user_id="user-1",
            additional_system_prompt=None,
            interface=None,
            workspace_id="workspace-1",
            workspace_handle=None,
        )

        decoded = decode_session_wake_up(encode_session_wake_up(message))

        assert decoded == message


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


class TestRedisBrokerMessages:
    """Broker wake/signal send/receive tests."""

    async def test_send_and_receive_session_wake_up(self, redis: Redis) -> None:
        """Worker receives SessionWakeUp."""
        sender = RedisBroker(redis)
        worker = RedisBroker(redis, worker_id="worker-1")
        await worker.setup()
        message = SessionWakeUp(
            agent_id="agent-1",
            session_id="session-1",
            user_id="user-1",
            additional_system_prompt=None,
            interface=None,
            workspace_id="workspace-1",
            workspace_handle=None,
        )

        await sender.send_message(message)
        received = await worker.receive_messages()

        assert received == [message]

    async def test_send_and_receive_stop_signal(self, redis: Redis) -> None:
        """Worker receives SessionStopSignal."""
        sender = RedisBroker(redis)
        worker = RedisBroker(redis, worker_id="worker-1")
        await worker.setup()
        message = SessionStopSignal(session_id="session-1", user_id="user-1")

        await sender.send_message(message)
        received = await worker.receive_messages()

        assert received == [message]

    async def test_recreates_missing_direct_stream_group(self, redis: Redis) -> None:
        """Worker recreates a missing owner direct stream group and receives."""
        sender = RedisBroker(redis)
        worker = RedisBroker(redis, worker_id="worker-1")
        await worker.setup()
        first = SessionWakeUp(
            agent_id="agent-1",
            session_id="session-1",
            user_id="user-1",
            additional_system_prompt=None,
            interface=None,
            workspace_id="workspace-1",
            workspace_handle=None,
        )
        second = dataclasses.replace(first, user_id="user-2")

        await sender.send_message(first)
        assert await worker.receive_messages() == [first]

        await redis.delete("azents:worker:worker-1:incoming")
        await sender.send_message(second)

        assert await worker.receive_messages() == [second]
