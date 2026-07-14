"""RedisBroker integration tests."""

import asyncio
import dataclasses
from collections.abc import AsyncGenerator
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import AsyncMock

import pytest
import pytest_asyncio
from redis.asyncio import Redis
from redis.crc import key_slot
from redis.exceptions import RedisError

from . import redis as redis_module
from .redis import (
    RedisBroker,
    decode_session_wake_up,
    encode_broker_message,
    encode_session_wake_up,
)
from .types import (
    BrokerMessage,
    SessionOwnershipLostError,
    SessionStopSignal,
    SessionWakeUp,
)


@pytest_asyncio.fixture
async def redis(redis_url: str) -> AsyncGenerator[Redis, None]:
    """Redis client for tests."""
    client = Redis.from_url(redis_url)
    await client.flushall()
    try:
        yield client
    finally:
        await client.aclose()


async def _enqueue_legacy_message(redis: Redis, message: BrokerMessage) -> None:
    """Seed the rolling-deploy LIST/Stream protocol for compatibility tests."""
    message_key = f"azents:session:{message.session_id}:messages"
    await redis.rpush(message_key, encode_broker_message(message))
    await redis.expire(message_key, RedisBroker._MESSAGE_TTL)  # pyright: ignore[reportPrivateUsage]  # Compatibility fixture mirrors the old producer.
    broker = RedisBroker(redis)
    await broker._publish_wake_up(message.session_id)  # pyright: ignore[reportPrivateUsage]  # Compatibility fixture mirrors the old producer.


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

    async def test_worker_setup_uses_dedicated_atomic_group(self) -> None:
        """A legacy consumer group can never consume complete v2 entries."""
        redis = AsyncMock()
        broker = RedisBroker(cast(Redis, redis), worker_id="worker-1")

        await broker.setup()

        group_calls = redis.xgroup_create.await_args_list
        assert [call.args[:2] for call in group_calls] == [
            ("azents:incoming", "engine-workers"),
            ("azents:worker:worker-1:incoming", "engine-workers"),
            ("azents:incoming:v2", "engine-workers-v2"),
        ]
        assert all(call.kwargs == {"id": "0", "mkstream": True} for call in group_calls)
        redis.set.assert_awaited_once_with(
            "azents:worker:worker-1:broker-v2",
            "1",
            ex=RedisBroker._OWNER_HEARTBEAT_TTL,  # pyright: ignore[reportPrivateUsage]
        )

    def test_multikey_lease_scripts_share_one_cluster_slot(self) -> None:
        """Every key used together by a lease script has the Session hash tag."""
        session_id = "session-1"
        prefix = RedisBroker._SESSION_PREFIX  # pyright: ignore[reportPrivateUsage]
        keys = (
            redis_module._session_lock_key(prefix, session_id),  # pyright: ignore[reportPrivateUsage]
            redis_module._session_owner_heartbeat_key(prefix, session_id),  # pyright: ignore[reportPrivateUsage]
            redis_module._session_activity_key(prefix, session_id),  # pyright: ignore[reportPrivateUsage]
            redis_module._session_activity_migration_key(prefix, session_id),  # pyright: ignore[reportPrivateUsage]
        )

        assert len({key_slot(key.encode()) for key in keys}) == 1


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

    async def test_atomic_authority_publish_is_one_single_key_mutation(self) -> None:
        """Complete-message publication stays atomic and Redis Cluster-safe."""
        redis = AsyncMock()
        broker = RedisBroker(cast(Redis, redis))
        message = SessionWakeUp(
            agent_id="agent-1",
            session_id="session-1",
            user_id="user-1",
            additional_system_prompt=None,
            interface=None,
            workspace_id="workspace-1",
            workspace_handle=None,
        )
        encoded = encode_broker_message(message)

        await broker._publish_atomic_message(message, encoded, b"legacy-copy")  # pyright: ignore[reportPrivateUsage]

        redis.xadd.assert_awaited_once()
        call = redis.xadd.await_args
        assert call.args == (
            "azents:incoming:v2",
            {
                "session_id": "session-1",
                "message": encoded,
                "legacy_message": b"legacy-copy",
            },
        )
        assert call.kwargs["approximate"] is False
        assert isinstance(call.kwargs["minid"], str)
        redis.eval.assert_not_awaited()
        redis.rpush.assert_not_awaited()

    async def test_v2_and_legacy_polling_are_fair_without_duplicate_backlog(
        self,
        redis: Redis,
    ) -> None:
        """A v2 handoff removes its exact copy before the next legacy poll."""
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
        await sender.send_message(second)

        assert await worker.receive_messages() == [first]
        assert await worker.receive_messages() == [second]

    async def test_send_and_receive_stop_signal(self, redis: Redis) -> None:
        """Worker receives SessionStopSignal."""
        sender = RedisBroker(redis)
        worker = RedisBroker(redis, worker_id="worker-1")
        await worker.setup()
        message = SessionStopSignal(
            session_id="session-1",
            user_id="user-1",
            stop_request_id=None,
        )

        await sender.send_message(message)
        received = await worker.receive_messages()

        assert received == [message]

    async def test_new_sender_reaches_legacy_only_owner_during_rollback(
        self,
        redis: Redis,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """The compatibility copy works before any v2-capable Worker remains."""
        owner = RedisBroker(redis, worker_id="worker-old")
        await owner.setup()
        await redis.delete("azents:worker:worker-old:broker-v2")
        await redis.set("azents:session:{session-1}:lock", "worker-old", ex=60)
        await redis.set(
            "azents:session:{session-1}:owner-heartbeat",
            "worker-old",
            ex=60,
        )
        sender = RedisBroker(redis)
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
        monkeypatch.setattr(
            owner,
            "_try_read_atomic_wake_up",
            AsyncMock(return_value=None),
        )

        assert await asyncio.wait_for(owner.receive_messages(), timeout=1) == [message]

    async def test_cancelled_detached_send_is_bounded_without_redis_fixture(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """The detached-send deadline bounds both independent delivery paths."""
        monkeypatch.setattr(redis_module, "_SEND_ATTEMPT_TIMEOUT_SECONDS", 0.01)
        monkeypatch.setattr(redis_module, "_REDIS_OPERATION_TIMEOUT_SECONDS", 0.01)
        redis = AsyncMock()
        broker = RedisBroker(cast(Redis, redis))
        message = SessionWakeUp(
            agent_id="agent-1",
            session_id="session-1",
            user_id="user-1",
            additional_system_prompt=None,
            interface=None,
            workspace_id="workspace-1",
            workspace_handle=None,
        )
        xadd_started = asyncio.Event()

        async def stuck_xadd(*args: object, **kwargs: object) -> None:
            del args, kwargs
            xadd_started.set()
            await asyncio.Event().wait()

        redis.xadd.side_effect = stuck_xadd
        send = asyncio.create_task(broker.send_message(message))
        await asyncio.wait_for(xadd_started.wait(), timeout=1)

        with pytest.raises(TimeoutError):
            await asyncio.wait_for(send, timeout=0.001)

        async def wait_for_detached_cleanup() -> None:
            while broker._detached_sends:  # pyright: ignore[reportPrivateUsage]
                await asyncio.sleep(0.005)

        await asyncio.wait_for(wait_for_detached_cleanup(), timeout=0.2)

        assert not broker._detached_sends  # pyright: ignore[reportPrivateUsage]
        assert redis.xadd.await_count >= 2
        redis.rpush.assert_awaited_once()
        redis.lrem.assert_awaited_once()

    async def test_receive_hard_bounds_hanging_redis_reclaim(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """A dead Redis connection cannot pin the Worker receive loop forever."""
        monkeypatch.setattr(redis_module, "_REDIS_OPERATION_TIMEOUT_SECONDS", 0.01)
        redis = AsyncMock()

        async def hang(*args: object, **kwargs: object) -> None:
            del args, kwargs
            await asyncio.Event().wait()

        redis.xautoclaim.side_effect = hang
        broker = RedisBroker(cast(Redis, redis), worker_id="worker-1")
        started_at = asyncio.get_running_loop().time()

        with pytest.raises(TimeoutError):
            await asyncio.wait_for(broker.receive_messages(), timeout=0.5)

        assert asyncio.get_running_loop().time() - started_at < 0.2
        redis.xautoclaim.assert_awaited_once()

    async def test_atomic_ack_happens_only_after_message_handoff(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """An ambiguous deferred XACK cannot withhold the in-memory body."""
        redis = AsyncMock()
        broker = RedisBroker(cast(Redis, redis), worker_id="worker-1")
        message = SessionWakeUp(
            agent_id="agent-1",
            session_id="session-1",
            user_id="user-1",
            additional_system_prompt=None,
            interface=None,
            workspace_id="workspace-1",
            workspace_handle=None,
        )
        wake_up = redis_module._AtomicWakeUp(  # pyright: ignore[reportPrivateUsage]  # Exercise the handoff/ACK protocol boundary.
            stream_name="azents:incoming:v2",
            entry_id="1-0",
            message=message,
            legacy_encoded=None,
        )
        monkeypatch.setattr(
            broker,
            "_acquire_or_find_owner",
            AsyncMock(return_value=SimpleNamespace(status="owned", owner="worker-1")),
        )

        assert await broker._route_atomic_wake_up(wake_up) == [message]  # pyright: ignore[reportPrivateUsage]  # Verify the internal handoff boundary.
        redis.xack.assert_not_awaited()

        redis.xack.side_effect = TimeoutError
        await broker._ack_handed_off_atomic_wake()  # pyright: ignore[reportPrivateUsage]  # Simulate the next receive boundary.

        redis.xack.assert_awaited_once_with(
            "azents:incoming:v2",
            "engine-workers-v2",
            "1-0",
        )
        assert broker._handed_off_atomic_wake is None  # pyright: ignore[reportPrivateUsage]

    async def test_trimmed_atomic_pending_reference_is_acknowledged(self) -> None:
        """A retention-trimmed null PEL body cannot poison the receive loop."""
        redis = AsyncMock()
        broker = RedisBroker(cast(Redis, redis), worker_id="worker-1")

        decoded = await broker._decode_atomic_wake_up(  # pyright: ignore[reportPrivateUsage]
            "azents:incoming:v2",
            ("1-0", None),
        )

        assert decoded is None
        redis.xack.assert_awaited_once_with(
            "azents:incoming:v2",
            "engine-workers-v2",
            "1-0",
        )

    async def test_atomic_live_owner_receives_claimed_pending_entry(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """XCLAIM owner routing is paired with an immediate own-PEL read."""
        redis = AsyncMock()
        router = RedisBroker(cast(Redis, redis), worker_id="worker-router")
        message = SessionWakeUp(
            agent_id="agent-1",
            session_id="session-1",
            user_id="user-1",
            additional_system_prompt=None,
            interface=None,
            workspace_id="workspace-1",
            workspace_handle=None,
        )
        wake_up = redis_module._AtomicWakeUp(  # pyright: ignore[reportPrivateUsage]
            stream_name="azents:incoming:v2",
            entry_id="1-0",
            message=message,
            legacy_encoded=None,
        )
        monkeypatch.setattr(
            router,
            "_acquire_or_find_owner",
            AsyncMock(
                return_value=SimpleNamespace(
                    status="live_owner",
                    owner="worker-owner",
                )
            ),
        )
        redis.get.return_value = b"1"

        assert await router._route_atomic_wake_up(wake_up) is None  # pyright: ignore[reportPrivateUsage]

        redis.xclaim.assert_awaited_once_with(
            "azents:incoming:v2",
            "engine-workers-v2",
            "worker-owner",
            min_idle_time=0,
            message_ids=["1-0"],
        )
        redis.xack.assert_not_awaited()

        owner = RedisBroker(cast(Redis, redis), worker_id="worker-owner")
        redis.xreadgroup.return_value = [
            (
                b"azents:incoming:v2",
                [
                    (
                        b"1-0",
                        {
                            b"session_id": b"session-1",
                            b"message": encode_broker_message(message),
                        },
                    )
                ],
            )
        ]

        claimed = await owner._try_read_atomic_wake_up()  # pyright: ignore[reportPrivateUsage]

        assert claimed is not None
        assert claimed.message == message
        redis.xautoclaim.assert_not_awaited()

    async def test_legacy_bridge_keeps_v2_authority_on_append_ambiguity(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """An old-owner bridge never ACKs v2 after an ambiguous LIST append."""
        redis = AsyncMock()
        broker = RedisBroker(cast(Redis, redis), worker_id="worker-router")
        message = SessionWakeUp(
            agent_id="agent-1",
            session_id="session-1",
            user_id="user-1",
            additional_system_prompt=None,
            interface=None,
            workspace_id="workspace-1",
            workspace_handle=None,
        )
        wake_up = redis_module._AtomicWakeUp(  # pyright: ignore[reportPrivateUsage]
            stream_name="azents:incoming:v2",
            entry_id="1-0",
            message=message,
            legacy_encoded=None,
        )
        monkeypatch.setattr(
            broker,
            "_acquire_or_find_owner",
            AsyncMock(
                return_value=SimpleNamespace(
                    status="live_owner",
                    owner="worker-old",
                )
            ),
        )
        redis.get.return_value = None
        redis.rpush.side_effect = RedisError("append response lost")

        with pytest.raises(RedisError, match="append response lost"):
            await broker._route_atomic_wake_up(wake_up)  # pyright: ignore[reportPrivateUsage]

        redis.rpush.assert_awaited_once()
        redis.xack.assert_not_awaited()

    async def test_legacy_bridge_acks_only_after_delivery_authority(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """A mixed-version bridge retains v2 until the legacy wake commits."""
        redis = AsyncMock()
        redis.eval.return_value = False
        legacy_wake_committed = False

        async def commit_legacy_wake(*args: object, **kwargs: object) -> bytes:
            nonlocal legacy_wake_committed
            del args, kwargs
            legacy_wake_committed = True
            return b"2-0"

        async def ack_v2(*args: object, **kwargs: object) -> int:
            del args, kwargs
            assert legacy_wake_committed
            return 1

        redis.xadd.side_effect = commit_legacy_wake
        redis.xack.side_effect = ack_v2
        broker = RedisBroker(cast(Redis, redis), worker_id="worker-router")
        message = SessionWakeUp(
            agent_id="agent-1",
            session_id="session-1",
            user_id="user-1",
            additional_system_prompt=None,
            interface=None,
            workspace_id="workspace-1",
            workspace_handle=None,
        )
        wake_up = redis_module._AtomicWakeUp(  # pyright: ignore[reportPrivateUsage]
            stream_name="azents:incoming:v2",
            entry_id="1-0",
            message=message,
            legacy_encoded=None,
        )
        monkeypatch.setattr(
            broker,
            "_acquire_or_find_owner",
            AsyncMock(
                return_value=SimpleNamespace(
                    status="live_owner",
                    owner="worker-old",
                )
            ),
        )
        redis.get.return_value = None

        assert await broker._route_atomic_wake_up(wake_up) is None  # pyright: ignore[reportPrivateUsage]

        redis.rpush.assert_awaited_once()
        redis.expire.assert_awaited_once()
        redis.xadd.assert_awaited_once()
        redis.xack.assert_awaited_once()

    async def test_quarantine_failure_cannot_restore_poison_to_source_queue(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Invalid recovery candidates are dropped before quarantine I/O."""
        redis = AsyncMock()
        message = SessionWakeUp(
            agent_id="agent-1",
            session_id="session-1",
            user_id="user-1",
            additional_system_prompt=None,
            interface=None,
            workspace_id="workspace-1",
            workspace_handle=None,
        )
        malformed = b'{"type":"unknown-envelope"}'
        redis.lpop.side_effect = [encode_broker_message(message), malformed, None]
        redis.eval.side_effect = RedisError("quarantine append failed")
        broker = RedisBroker(cast(Redis, redis), worker_id="worker-1")
        monkeypatch.setattr(
            broker,
            "_read_wake_up",
            AsyncMock(
                return_value=SimpleNamespace(
                    stream_name="azents:incoming",
                    entry_id="1-0",
                    session_id="session-1",
                )
            ),
        )
        monkeypatch.setattr(
            broker,
            "_acquire_or_find_owner",
            AsyncMock(return_value=SimpleNamespace(status="owned", owner="worker-1")),
        )
        ack = AsyncMock()
        monkeypatch.setattr(broker, "_ack_wake_up", ack)
        monkeypatch.setattr(
            broker,
            "_try_read_atomic_wake_up",
            AsyncMock(return_value=None),
        )

        assert await broker.receive_messages() == [message]

        redis.lpush.assert_not_awaited()
        redis.eval.assert_awaited_once_with(
            redis_module._APPEND_WITH_TTL_SCRIPT,  # pyright: ignore[reportPrivateUsage]  # Verify the atomic quarantine mutation.
            1,
            "azents:session:{session-1}:invalid-messages",
            str(RedisBroker._MESSAGE_TTL),  # pyright: ignore[reportPrivateUsage]
            malformed,
        )
        redis.rpush.assert_not_awaited()
        redis.expire.assert_not_awaited()
        ack.assert_awaited_once()

    async def test_atomic_send_response_loss_falls_back_without_retry(self) -> None:
        """An ambiguous v2 XADD uses the independent legacy delivery once."""
        redis = AsyncMock()
        redis.eval.return_value = False

        async def lose_atomic_response(
            stream_key: str,
            *args: object,
            **kwargs: object,
        ) -> bytes:
            del args, kwargs
            if stream_key == "azents:incoming:v2":
                raise RedisError("response lost")
            return b"1-0"

        redis.xadd.side_effect = lose_atomic_response
        sender = RedisBroker(cast(Redis, redis))
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

        assert redis.xadd.await_count == 2
        redis.rpush.assert_awaited_once()
        redis.expire.assert_awaited_once()
        redis.lrem.assert_not_awaited()

    async def test_send_does_not_retry_when_both_protocols_fail(self) -> None:
        """Failures get one duplicate-safe legacy repair wake, never a v2 retry."""
        redis = AsyncMock()
        redis.eval.return_value = False
        redis.xadd.side_effect = RedisError("atomic response lost")
        redis.rpush.side_effect = RedisError("legacy response lost")
        sender = RedisBroker(cast(Redis, redis))
        message = SessionWakeUp(
            agent_id="agent-1",
            session_id="session-1",
            user_id="user-1",
            additional_system_prompt=None,
            interface=None,
            workspace_id="workspace-1",
            workspace_handle=None,
        )

        with pytest.raises(RedisError, match="atomic response lost"):
            await sender.send_message(message)

        assert redis.xadd.await_count == 2
        redis.rpush.assert_awaited_once()
        redis.expire.assert_not_awaited()
        redis.lrem.assert_not_awaited()

    async def test_legacy_expire_failure_publishes_one_repair_wake(self) -> None:
        """A committed compatibility body gets a wake instead of mutation retry."""
        redis = AsyncMock()
        redis.eval.return_value = False
        redis.expire.side_effect = RedisError("expiry response lost")
        sender = RedisBroker(cast(Redis, redis))
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

        redis.rpush.assert_awaited_once()
        redis.expire.assert_awaited_once()
        assert redis.xadd.await_count == 2
        redis.lrem.assert_not_awaited()

    async def test_cancelled_send_finishes_wake_publication(
        self,
        redis: Redis,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Caller cancellation lets the complete-message XADD finish."""
        sender = RedisBroker(redis)
        message = SessionWakeUp(
            agent_id="agent-1",
            session_id="session-1",
            user_id="user-1",
            additional_system_prompt=None,
            interface=None,
            workspace_id="workspace-1",
            workspace_handle=None,
        )
        xadd_started = asyncio.Event()
        release_xadd = asyncio.Event()
        xadd_completed = asyncio.Event()
        original_xadd = redis.xadd

        async def controlled_xadd(*args: object, **kwargs: object) -> object:
            xadd_started.set()
            await release_xadd.wait()
            result = await cast(Any, original_xadd)(
                *args,
                **kwargs,
            )
            xadd_completed.set()
            return result

        monkeypatch.setattr(redis, "xadd", controlled_xadd)
        send = asyncio.create_task(sender.send_message(message))
        await asyncio.wait_for(xadd_started.wait(), timeout=1)
        send.cancel()
        with pytest.raises(asyncio.CancelledError):
            await send

        release_xadd.set()
        await asyncio.wait_for(xadd_completed.wait(), timeout=1)
        worker = RedisBroker(redis, worker_id="worker-1")
        await worker.setup()
        assert await asyncio.wait_for(worker.receive_messages(), timeout=1) == [message]

    async def test_cancelled_send_detach_is_hard_bounded(
        self,
        redis: Redis,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """A stuck atomic XADD cannot retain a detached send forever."""
        monkeypatch.setattr(redis_module, "_SEND_ATTEMPT_TIMEOUT_SECONDS", 0.02)
        monkeypatch.setattr(redis_module, "_REDIS_OPERATION_TIMEOUT_SECONDS", 0.01)
        sender = RedisBroker(redis)
        message = SessionWakeUp(
            agent_id="agent-1",
            session_id="session-1",
            user_id="user-1",
            additional_system_prompt=None,
            interface=None,
            workspace_id="workspace-1",
            workspace_handle=None,
        )
        xadd_started = asyncio.Event()

        async def stuck_xadd(*args: object, **kwargs: object) -> None:
            del args, kwargs
            xadd_started.set()
            await asyncio.Event().wait()

        monkeypatch.setattr(redis, "xadd", stuck_xadd)
        send = asyncio.create_task(sender.send_message(message))
        await asyncio.wait_for(xadd_started.wait(), timeout=1)
        send.cancel()

        with pytest.raises(asyncio.CancelledError):
            await send

        async def wait_for_detached_cleanup() -> None:
            while sender._detached_sends:  # pyright: ignore[reportPrivateUsage]
                await asyncio.sleep(0.005)

        await asyncio.wait_for(wait_for_detached_cleanup(), timeout=0.2)

        assert not sender._detached_sends  # pyright: ignore[reportPrivateUsage]
        assert await redis.lrange("azents:session:session-1:messages", 0, -1) == []

    async def test_cancelled_partial_drain_restores_messages_in_order(
        self,
        redis: Redis,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Cancellation restores popped envelopes, owner lock, and global wake."""
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
        await _enqueue_legacy_message(redis, first)
        await _enqueue_legacy_message(redis, second)

        original_lpop = Redis.lpop
        original_lpush = Redis.lpush
        lpop_calls = 0
        lpush_calls = 0
        second_lpop_started = asyncio.Event()

        async def controlled_lpop(client: Redis, name: str) -> bytes | None:
            nonlocal lpop_calls
            lpop_calls += 1
            if lpop_calls == 2:
                second_lpop_started.set()
                await asyncio.Event().wait()
            return await original_lpop(client, name)

        async def flaky_lpush(
            client: Redis,
            name: str,
            *values: bytes,
        ) -> int:
            nonlocal lpush_calls
            lpush_calls += 1
            if lpush_calls == 1:
                raise RuntimeError("transient restore failure")
            return await original_lpush(client, name, *values)

        monkeypatch.setattr(Redis, "lpop", controlled_lpop)
        monkeypatch.setattr(Redis, "lpush", flaky_lpush)
        receive = asyncio.create_task(worker.receive_messages())
        await asyncio.wait_for(second_lpop_started.wait(), timeout=1)

        receive.cancel()
        with pytest.raises(asyncio.CancelledError):
            await receive

        msg_key = "azents:session:session-1:messages"
        assert await redis.lrange(msg_key, 0, -1) == [
            encode_broker_message(first),
            encode_broker_message(second),
        ]
        assert await redis.get("azents:session:{session-1}:lock") is None
        assert await redis.get("azents:session:{session-1}:owner-heartbeat") is None
        assert lpush_calls == 2

        monkeypatch.setattr(Redis, "lpop", original_lpop)
        monkeypatch.setattr(Redis, "lpush", original_lpush)
        replacement = RedisBroker(redis, worker_id="worker-2")
        await replacement.setup()
        assert await asyncio.wait_for(replacement.receive_messages(), timeout=1) == [
            first,
            second,
        ]

    async def test_redis_failure_before_wake_ack_republishes_message(
        self,
        redis: Redis,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """A transient ownership lookup failure cannot orphan a pending wake."""
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
        original_acquire = worker._acquire_or_find_owner  # pyright: ignore[reportPrivateUsage]  # Exercise the pre-XACK recovery boundary.
        attempts = 0

        async def flaky_acquire(session_id: str) -> object:
            nonlocal attempts
            attempts += 1
            if attempts == 1:
                raise RedisError("transient ownership failure")
            return await original_acquire(session_id)

        monkeypatch.setattr(worker, "_acquire_or_find_owner", flaky_acquire)

        with pytest.raises(RedisError, match="transient ownership failure"):
            await worker.receive_messages()

        assert await asyncio.wait_for(worker.receive_messages(), timeout=1) == [message]

    async def test_crashed_consumer_wake_is_reclaimed_before_body_drain(
        self,
        redis: Redis,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """An unacked wake survives a crash before its queued body is drained."""
        sender = RedisBroker(redis)
        crashed = RedisBroker(redis, worker_id="worker-crashed")
        await crashed.setup()
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

        pending = await crashed._try_read_atomic_wake_up()  # pyright: ignore[reportPrivateUsage]  # Simulate a crash after Stream delivery but before owner admission.
        assert pending is not None
        assert pending.message == message
        monkeypatch.setattr(RedisBroker, "_WAKE_RECLAIM_IDLE_MS", 0)
        replacement = RedisBroker(redis, worker_id="worker-replacement")
        await replacement.setup()

        assert await asyncio.wait_for(replacement.receive_messages(), timeout=1) == [
            message
        ]

    async def test_receive_recovery_preserves_preexisting_owner_lock(
        self,
        redis: Redis,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """A failed receive must not release a lock owned by an active runner."""
        sender = RedisBroker(redis)
        worker = RedisBroker(redis, worker_id="worker-1")
        await worker.setup()
        await redis.set("azents:session:{session-1}:lock", "worker-1", ex=60)
        await redis.set(
            "azents:session:{session-1}:owner-heartbeat",
            "worker-1",
            ex=60,
        )
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
        original_acquire = worker._acquire_or_find_owner  # pyright: ignore[reportPrivateUsage]  # Exercise recovery before ownership lookup returns.
        attempts = 0

        async def flaky_acquire(session_id: str) -> object:
            nonlocal attempts
            attempts += 1
            if attempts == 1:
                raise RedisError("transient ownership failure")
            return await original_acquire(session_id)

        monkeypatch.setattr(worker, "_acquire_or_find_owner", flaky_acquire)

        with pytest.raises(RedisError, match="transient ownership failure"):
            await worker.receive_messages()

        assert await redis.get("azents:session:{session-1}:lock") == b"worker-1"
        assert (
            await redis.get("azents:session:{session-1}:owner-heartbeat") == b"worker-1"
        )
        assert await asyncio.wait_for(worker.receive_messages(), timeout=1) == [message]

    async def test_empty_duplicate_releases_newly_acquired_lock(
        self,
        redis: Redis,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """A body-less duplicate wake cannot strand an owner without a runner."""
        worker = RedisBroker(redis, worker_id="worker-1")
        await worker.setup()
        await redis.xadd("azents:incoming", {"session_id": "session-1"})
        original_read = worker._read_wake_up  # pyright: ignore[reportPrivateUsage]  # Stop after one duplicate-wake iteration.
        attempts = 0

        async def read_once() -> object:
            nonlocal attempts
            attempts += 1
            if attempts == 1:
                return await original_read()
            raise RedisError("test receive complete")

        monkeypatch.setattr(worker, "_read_wake_up", read_once)

        with pytest.raises(RedisError, match="test receive complete"):
            await worker.receive_messages()

        assert await redis.get("azents:session:{session-1}:lock") is None
        assert await redis.get("azents:session:{session-1}:owner-heartbeat") is None

    async def test_redis_failure_during_partial_drain_restores_fifo(
        self,
        redis: Redis,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """A transient LIST failure restores every popped message in FIFO order."""
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
        await _enqueue_legacy_message(redis, first)
        await _enqueue_legacy_message(redis, second)
        original_lpop = Redis.lpop
        lpop_calls = 0

        async def flaky_lpop(client: Redis, name: str) -> bytes | None:
            nonlocal lpop_calls
            lpop_calls += 1
            if lpop_calls == 2:
                raise RedisError("transient list failure")
            return await original_lpop(client, name)

        monkeypatch.setattr(Redis, "lpop", flaky_lpop)

        with pytest.raises(RedisError, match="transient list failure"):
            await worker.receive_messages()

        replacement = RedisBroker(redis, worker_id="worker-2")
        await replacement.setup()
        assert await asyncio.wait_for(replacement.receive_messages(), timeout=1) == [
            first,
            second,
        ]

    async def test_malformed_batch_quarantines_invalid_and_returns_valid(
        self,
        redis: Redis,
    ) -> None:
        """One invalid envelope cannot destroy the valid envelopes around it."""
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
        message_key = "azents:session:session-1:messages"
        malformed = b'{"type":"unknown-envelope"}'
        await _enqueue_legacy_message(redis, first)
        await redis.rpush(message_key, malformed)
        await _enqueue_legacy_message(redis, second)

        assert await worker.receive_messages() == [first, second]

        assert await redis.lrange(message_key, 0, -1) == []
        invalid_key = "azents:session:{session-1}:invalid-messages"
        assert await redis.lrange(invalid_key, 0, -1) == [malformed]
        assert await redis.ttl(invalid_key) > 0
        assert await redis.get("azents:session:{session-1}:lock") == b"worker-1"
        assert (
            await redis.get("azents:session:{session-1}:owner-heartbeat") == b"worker-1"
        )

    async def test_quarantine_append_sets_ttl_atomically(self, redis: Redis) -> None:
        """A poison append cannot commit without its bounded retention TTL."""
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
        message_key = "azents:session:session-1:messages"
        invalid_key = "azents:session:{session-1}:invalid-messages"
        malformed = b'{"type":"unknown-envelope"}'
        await _enqueue_legacy_message(redis, message)
        await redis.rpush(message_key, malformed)

        assert await worker.receive_messages() == [message]

        assert await redis.lrange(message_key, 0, -1) == []
        assert await redis.lrange(invalid_key, 0, -1) == [malformed]
        assert await redis.ttl(invalid_key) > 0

    async def test_repeated_receive_cancellation_does_not_orphan_recovery(
        self,
        redis: Redis,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """A second cancel leaves destructive-read recovery running and observed."""
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
        await _enqueue_legacy_message(redis, message)

        original_lpop = Redis.lpop
        original_lpush = Redis.lpush
        second_lpop_started = asyncio.Event()
        recovery_started = asyncio.Event()
        release_recovery = asyncio.Event()
        message_restored = asyncio.Event()
        lpop_calls = 0

        async def controlled_lpop(client: Redis, name: str) -> bytes | None:
            nonlocal lpop_calls
            lpop_calls += 1
            if lpop_calls == 2:
                second_lpop_started.set()
                await asyncio.Event().wait()
            return await original_lpop(client, name)

        async def controlled_lpush(
            client: Redis,
            name: str,
            *values: bytes,
        ) -> int:
            recovery_started.set()
            await release_recovery.wait()
            restored_count = await original_lpush(client, name, *values)
            message_restored.set()
            return restored_count

        monkeypatch.setattr(Redis, "lpop", controlled_lpop)
        monkeypatch.setattr(Redis, "lpush", controlled_lpush)
        receive = asyncio.create_task(worker.receive_messages())
        await asyncio.wait_for(second_lpop_started.wait(), timeout=1)
        receive.cancel()
        await asyncio.wait_for(recovery_started.wait(), timeout=1)
        receive.cancel()
        with pytest.raises(asyncio.CancelledError):
            await receive

        release_recovery.set()
        await asyncio.wait_for(message_restored.wait(), timeout=1)
        await asyncio.sleep(0)

        assert await redis.lrange(
            "azents:session:session-1:messages",
            0,
            -1,
        ) == [encode_broker_message(message)]

    async def test_recreates_missing_direct_stream_group(self, redis: Redis) -> None:
        """Worker recreates a missing owner direct stream group and receives."""
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

        await _enqueue_legacy_message(redis, first)
        assert await worker.receive_messages() == [first]

        await redis.delete("azents:worker:worker-1:incoming")
        await _enqueue_legacy_message(redis, second)

        assert await worker.receive_messages() == [second]


class TestRedisBrokerActivity:
    """Session activity authority tests."""

    async def test_clear_for_run_preserves_newer_activity(self, redis: Redis) -> None:
        """An old Run finalizer cannot delete another Run's activity."""
        broker = RedisBroker(redis)
        await broker.set_session_activity("session-1", run_id="run-new")

        await broker.clear_session_activity_for_run(
            "session-1",
            run_id="run-old",
        )

        activity = await broker.get_session_activity("session-1")
        assert activity is not None
        assert activity.run_id == "run-new"

        await broker.clear_session_activity_for_run(
            "session-1",
            run_id="run-new",
        )

        assert await broker.get_session_activity("session-1") is None

    async def test_reads_legacy_activity_during_rolling_deploy(
        self,
        redis: Redis,
    ) -> None:
        """New readers retain bounded compatibility with the old activity key."""
        broker = RedisBroker(redis)
        await redis.set(
            "azents:session:session-1:activity",
            b'{"run_id":"run-legacy","phase":null}',
            ex=60,
        )

        activity = await broker.get_session_activity("session-1")

        assert activity is not None
        assert activity.run_id == "run-legacy"

    async def test_migration_marker_suppresses_stale_legacy_activity(
        self,
        redis: Redis,
    ) -> None:
        """A cleared new projection cannot resurrect from an old worker's key."""
        broker = RedisBroker(redis)
        await broker.set_session_activity("session-1", run_id="run-new")
        await broker.clear_session_activity_for_run(
            "session-1",
            run_id="run-new",
        )
        await redis.set(
            "azents:session:session-1:activity",
            b'{"run_id":"run-stale","phase":null}',
            ex=60,
        )

        assert await broker.get_session_activity("session-1") is None

    async def test_new_owner_marker_does_not_hide_later_legacy_owner_activity(
        self,
        redis: Redis,
    ) -> None:
        """A later old-version owner remains visible during a rolling deploy."""
        broker = RedisBroker(redis)
        await redis.set(
            "azents:session:{session-1}:activity-migrated",
            "worker-new",
            ex=60,
        )
        await redis.set(
            "azents:session:{session-1}:lock",
            "worker-old",
            ex=60,
        )
        await redis.set(
            "azents:session:session-1:activity",
            b'{"run_id":"run-old","phase":null}',
            ex=60,
        )

        activity = await broker.get_session_activity("session-1")

        assert activity is not None
        assert activity.run_id == "run-old"

    async def test_later_legacy_owner_wins_over_stale_new_activity(
        self,
        redis: Redis,
    ) -> None:
        """Authority selects the old-version owner's projection, not a stale new key."""
        broker = RedisBroker(redis)
        await redis.set(
            "azents:session:{session-1}:activity",
            b'{"run_id":"run-stale","phase":null}',
            ex=60,
        )
        await redis.set(
            "azents:session:{session-1}:activity-migrated",
            "worker-new",
            ex=60,
        )
        await redis.set(
            "azents:session:{session-1}:lock",
            "worker-old",
            ex=60,
        )
        await redis.set(
            "azents:session:session-1:activity",
            b'{"run_id":"run-current","phase":null}',
            ex=60,
        )

        activity = await broker.get_session_activity("session-1")

        assert activity is not None
        assert activity.run_id == "run-current"

    async def test_tagged_legacy_activity_is_hidden_after_owner_handoff(
        self,
        redis: Redis,
    ) -> None:
        """A late cross-slot legacy write cannot revive the previous owner."""
        owner = RedisBroker(redis, worker_id="worker-old")
        reader = RedisBroker(redis)
        await redis.set("azents:session:{session-1}:lock", "worker-old", ex=60)
        await owner.set_session_activity("session-1", run_id="run-old")
        late_value = await redis.get("azents:session:session-1:activity")
        assert late_value is not None

        await redis.set("azents:session:{session-1}:lock", "worker-new", ex=60)
        await redis.set("azents:session:session-1:activity", late_value, ex=60)

        assert await reader.get_session_activity("session-1") is None


class TestRedisBrokerOwnershipRenewal:
    """Session lease renewal tests."""

    async def test_owner_heartbeat_renewal_reports_lost_ownership(
        self,
        redis: Redis,
    ) -> None:
        """A failed compare-and-renew must fence the stale worker."""
        broker = RedisBroker(redis, worker_id="worker-old")
        await redis.set("azents:session:{session-1}:lock", "worker-new")

        with pytest.raises(SessionOwnershipLostError, match="session-1"):
            await broker.renew_session_owner_heartbeat("session-1")

    async def test_lease_renewal_reports_lost_ownership(
        self,
        redis: Redis,
    ) -> None:
        """Event publication cannot silently renew activity after lease loss."""
        broker = RedisBroker(redis, worker_id="worker-old")
        interface_broker = RedisBroker(redis)
        await interface_broker.set_session_activity("session-1", run_id="run-1")
        await redis.set("azents:session:{session-1}:lock", "worker-new")

        with pytest.raises(SessionOwnershipLostError, match="session-1"):
            await broker.renew_session_ttl("session-1")

    async def test_lease_validation_error_fails_closed_before_metadata_refresh(
        self,
    ) -> None:
        """An unavailable compare-and-renew cannot authorize event projection."""
        redis = AsyncMock()
        redis.eval.side_effect = RedisError("lease validation unavailable")
        broker = RedisBroker(cast(Redis, redis), worker_id="worker-old")

        with pytest.raises(RedisError, match="lease validation unavailable"):
            await broker.renew_session_ttl("session-1")

        redis.expire.assert_not_awaited()

    async def test_owner_heartbeat_hard_bounds_hanging_authority_check(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """A hung owner fence fails closed within the broker deadline."""
        monkeypatch.setattr(redis_module, "_REDIS_OPERATION_TIMEOUT_SECONDS", 0.01)
        redis = AsyncMock()

        async def hang(*args: object, **kwargs: object) -> None:
            del args, kwargs
            await asyncio.Event().wait()

        redis.eval.side_effect = hang
        broker = RedisBroker(cast(Redis, redis), worker_id="worker-old")
        started_at = asyncio.get_running_loop().time()

        with pytest.raises(TimeoutError):
            await asyncio.wait_for(
                broker.renew_session_owner_heartbeat("session-1"),
                timeout=0.5,
            )

        assert asyncio.get_running_loop().time() - started_at < 0.2
        redis.eval.assert_awaited_once()

    async def test_owner_heartbeat_preserves_external_cancellation(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """The broker does not normalize caller cancellation as an I/O timeout."""
        monkeypatch.setattr(redis_module, "_REDIS_OPERATION_TIMEOUT_SECONDS", 1.0)
        redis = AsyncMock()
        started = asyncio.Event()

        async def hang(*args: object, **kwargs: object) -> None:
            del args, kwargs
            started.set()
            await asyncio.Event().wait()

        redis.eval.side_effect = hang
        broker = RedisBroker(cast(Redis, redis), worker_id="worker-old")
        heartbeat = asyncio.create_task(
            broker.renew_session_owner_heartbeat("session-1")
        )
        await asyncio.wait_for(started.wait(), timeout=0.5)

        heartbeat.cancel()

        with pytest.raises(asyncio.CancelledError):
            await asyncio.wait_for(heartbeat, timeout=0.2)

    async def test_startup_activity_hard_bounds_hanging_owner_fence(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Run startup cannot hang before model execution on activity Redis I/O."""
        monkeypatch.setattr(redis_module, "_REDIS_OPERATION_TIMEOUT_SECONDS", 0.01)
        redis = AsyncMock()
        eval_calls = 0

        async def hang_owner_fence(*args: object, **kwargs: object) -> int:
            nonlocal eval_calls
            del args, kwargs
            eval_calls += 1
            if eval_calls == 1:
                await asyncio.Event().wait()
            return 1

        redis.eval.side_effect = hang_owner_fence
        broker = RedisBroker(cast(Redis, redis), worker_id="worker-old")
        started_at = asyncio.get_running_loop().time()

        with pytest.raises(TimeoutError):
            await asyncio.wait_for(
                broker.set_session_activity("session-1", run_id="run-1"),
                timeout=0.5,
            )

        assert asyncio.get_running_loop().time() - started_at < 0.2
        # The authority mutation is never retried after its outcome becomes
        # ambiguous. The second EVAL is an exact-value compatibility cleanup.
        assert eval_calls == 2

    async def test_legacy_activity_timeout_is_best_effort_after_owner_fence(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Compatibility projection failure cannot replace owner authority."""
        monkeypatch.setattr(redis_module, "_REDIS_OPERATION_TIMEOUT_SECONDS", 0.01)
        redis = AsyncMock()

        async def hang(*args: object, **kwargs: object) -> None:
            del args, kwargs
            await asyncio.Event().wait()

        redis.set.side_effect = hang
        redis.eval.return_value = 1
        broker = RedisBroker(cast(Redis, redis), worker_id="worker-old")

        await asyncio.wait_for(
            broker.set_session_activity("session-1", run_id="run-1"),
            timeout=0.5,
        )

        redis.eval.assert_awaited_once()

    async def test_activity_ttl_timeout_is_best_effort_after_verified_lease(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Hung projection TTL refreshes cannot stall verified event dispatch."""
        monkeypatch.setattr(redis_module, "_REDIS_OPERATION_TIMEOUT_SECONDS", 0.01)
        redis = AsyncMock()

        async def hang(*args: object, **kwargs: object) -> None:
            del args, kwargs
            await asyncio.Event().wait()

        redis.eval.return_value = 1
        redis.expire.side_effect = hang
        broker = RedisBroker(cast(Redis, redis), worker_id="worker-old")
        started_at = asyncio.get_running_loop().time()

        await asyncio.wait_for(broker.renew_session_ttl("session-1"), timeout=0.5)

        assert asyncio.get_running_loop().time() - started_at < 0.2
        assert redis.expire.await_count == 3

    async def test_activity_ttl_errors_are_best_effort_after_verified_lease(
        self,
    ) -> None:
        """Projection metadata failure cannot invalidate a verified owner."""
        redis = AsyncMock()
        redis.eval.return_value = 1
        redis.expire.side_effect = [RedisError("activity unavailable"), True, True]
        broker = RedisBroker(cast(Redis, redis), worker_id="worker-old")

        await broker.renew_session_ttl("session-1")

        assert redis.expire.await_count == 3

    async def test_stale_owner_cannot_overwrite_new_activity(
        self,
        redis: Redis,
    ) -> None:
        """Activity projection writes are fenced by current Redis ownership."""
        interface_broker = RedisBroker(redis)
        stale_worker = RedisBroker(redis, worker_id="worker-old")
        await interface_broker.set_session_activity("session-1", run_id="run-new")
        await redis.set("azents:session:{session-1}:lock", "worker-new")

        with pytest.raises(SessionOwnershipLostError, match="session-1"):
            await stale_worker.set_session_activity("session-1", run_id="run-old")

        activity = await interface_broker.get_session_activity("session-1")
        assert activity is not None
        assert activity.run_id == "run-new"

    async def test_stale_owner_cannot_clear_recovered_run_activity(
        self,
        redis: Redis,
    ) -> None:
        """Run-id matching alone cannot authorize a stale worker's cleanup."""
        interface_broker = RedisBroker(redis)
        stale_worker = RedisBroker(redis, worker_id="worker-old")
        await interface_broker.set_session_activity("session-1", run_id="run-shared")
        await redis.set("azents:session:{session-1}:lock", "worker-new")

        with pytest.raises(SessionOwnershipLostError, match="session-1"):
            await stale_worker.clear_session_activity_for_run(
                "session-1",
                run_id="run-shared",
            )

        activity = await interface_broker.get_session_activity("session-1")
        assert activity is not None
        assert activity.run_id == "run-shared"
