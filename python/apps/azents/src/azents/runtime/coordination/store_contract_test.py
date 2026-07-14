"""Runtime coordination store contract tests."""

import asyncio
import json
from collections.abc import AsyncGenerator, Callable
from datetime import datetime, timedelta, timezone
from typing import cast

import pytest
import pytest_asyncio
from redis.asyncio import Redis

from azents.runtime.coordination.data import (
    RuntimeBodyChunk,
    RuntimeConnectionKind,
    RuntimeCoordinationTarget,
    RuntimeOperationMetadata,
    RuntimeOperationStatus,
    RuntimeReplyEvent,
    RuntimeReplyEventType,
    RuntimeRequestEnvelope,
)
from azents.runtime.coordination.memory import (
    InMemoryRuntimeCoordinationStore,
)
from azents.runtime.coordination.redis import (
    RedisRuntimeCoordinationStore,
)
from azents.runtime.coordination.store import (
    RuntimeCoordinationStore,
)


@pytest_asyncio.fixture(params=["memory", "redis"])
async def store(
    request: pytest.FixtureRequest,
) -> AsyncGenerator[RuntimeCoordinationStore, None]:
    """Coordination store backend under contract test."""
    if request.param == "memory":
        yield InMemoryRuntimeCoordinationStore()
        return

    redis_url = request.getfixturevalue("redis_url")
    client = Redis.from_url(str(redis_url))
    await client.flushall()
    try:
        yield RedisRuntimeCoordinationStore(client)
    finally:
        await client.aclose()


class FakeRedisConnectionStore:
    """Minimal Redis command subset for connection generation fencing tests."""

    def __init__(self) -> None:
        self.data: dict[str, str] = {}
        self.after_get: Callable[[str], None] | None = None

    async def incr(self, key: str) -> int:
        value = int(self.data.get(key, "0")) + 1
        self.data[key] = str(value)
        return value

    async def expire(self, key: str, seconds: int) -> bool:
        del key, seconds
        return True

    async def set(self, key: str, value: str, *, ex: int | None = None) -> bool:
        del ex
        self.data[key] = value
        return True

    async def get(self, key: str) -> str | None:
        value = self.data.get(key)
        if self.after_get is not None:
            self.after_get(key)
        return value

    async def delete(self, key: str) -> int:
        existed = key in self.data
        self.data.pop(key, None)
        return int(existed)

    async def eval(
        self,
        script: str,
        numkeys: int,
        *keys_and_args: object,
    ) -> int | str:
        keys = [str(key) for key in keys_and_args[:numkeys]]
        args = keys_and_args[numkeys:]
        if numkeys == 2:
            generation_key, connection_key = keys
            generation = int(self.data.get(generation_key, "0")) + 1
            self.data[generation_key] = str(generation)
            payload = json.loads(str(args[0]))
            payload["generation"] = generation
            encoded = json.dumps(payload)
            self.data[connection_key] = encoded
            return encoded

        key = keys[0]
        raw = self.data.get(key)
        if raw is None:
            return 0
        payload = json.loads(raw)
        if int(payload["generation"]) != int(cast(int, args[0])):
            return 0
        if "DEL" in script:
            self.data.pop(key, None)
            return 1
        if "SET" in script:
            self.data[key] = str(args[1])
            return 1
        return 0


class _CommitAmbiguousConnectionRegistrationRedis:
    """Apply one atomic registration, then lose its command response."""

    def __init__(self) -> None:
        self.data: dict[str, str] = {}
        self.ttls: dict[str, int] = {}
        self.eval_calls = 0
        self.cancelled = asyncio.Event()

    async def eval(
        self,
        script: str,
        numkeys: int,
        *keys_and_args: object,
    ) -> str:
        del script
        assert numkeys == 2
        self.eval_calls += 1
        generation_key = str(keys_and_args[0])
        connection_key = str(keys_and_args[1])
        candidate = json.loads(str(keys_and_args[2]))
        generation = int(self.data.get(generation_key, "0")) + 1
        candidate["generation"] = generation
        encoded = json.dumps(candidate)
        self.data[generation_key] = str(generation)
        self.ttls[generation_key] = int(cast(int, keys_and_args[3]))
        self.data[connection_key] = encoded
        self.ttls[connection_key] = int(cast(int, keys_and_args[4]))
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            self.cancelled.set()
            raise
        raise AssertionError("unreachable")


class _HungReadRedis:
    """Redis stub whose read never returns unless its caller is cancelled."""

    def __init__(self) -> None:
        self.started = asyncio.Event()
        self.cancelled = asyncio.Event()

    async def get(self, key: str) -> None:
        del key
        self.started.set()
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            self.cancelled.set()
            raise


class _CommitAmbiguousAppendRedis:
    """Redis stub that applies XADD but loses the command response."""

    def __init__(self) -> None:
        self.eval_calls = 0
        self.committed_payloads: list[str] = []

    async def eval(
        self,
        script: str,
        numkeys: int,
        key: str,
        payload: str,
        ttl_seconds: int,
    ) -> str:
        del script, numkeys, key, ttl_seconds
        self.eval_calls += 1
        self.committed_payloads.append(payload)
        await asyncio.Event().wait()
        raise AssertionError("unreachable")


class _BlockingReadRedis:
    """Redis stub for validating XREADGROUP block-aware deadlines."""

    def __init__(self, *, return_after_block: bool) -> None:
        self.return_after_block = return_after_block
        self.received_block_ms: int | None = None

    async def expire(self, key: str, seconds: int) -> bool:
        del key, seconds
        return True

    async def xgroup_create(
        self,
        key: str,
        group_name: str,
        *,
        id: str,
        mkstream: bool,
    ) -> bool:
        del key, group_name, id, mkstream
        return True

    async def xreadgroup(
        self,
        group_name: str,
        consumer_id: str,
        streams: dict[str, str],
        *,
        count: int,
        block: int | None,
    ) -> list[object]:
        del group_name, consumer_id, streams, count
        self.received_block_ms = block
        if block is not None:
            await asyncio.sleep(block / 1000)
        if self.return_after_block:
            return []
        await asyncio.Event().wait()
        raise AssertionError("unreachable")


@pytest_asyncio.fixture
async def redis_store(
    redis_url: str,
) -> AsyncGenerator[tuple[RedisRuntimeCoordinationStore, Redis], None]:
    """Store and client for validating Redis implementation details."""
    client = Redis.from_url(str(redis_url))
    await client.flushall()
    try:
        yield (
            RedisRuntimeCoordinationStore(
                client,
                stream_ttl_seconds=3600,
                connection_generation_ttl_seconds=604800,
            ),
            client,
        )
    finally:
        await client.aclose()


@pytest.mark.asyncio
async def test_redis_operation_deadline_bounds_hung_read() -> None:
    """A Redis read cannot wedge a Runtime operation indefinitely."""
    fake_redis = _HungReadRedis()
    store = RedisRuntimeCoordinationStore(
        cast(Redis, fake_redis),
        redis_operation_timeout_seconds=0.01,
    )

    with pytest.raises(TimeoutError):
        await asyncio.wait_for(store.get_operation("operation:req-1"), timeout=0.2)

    assert fake_redis.started.is_set()
    assert fake_redis.cancelled.is_set()


@pytest.mark.asyncio
async def test_redis_operation_deadline_preserves_caller_cancellation() -> None:
    """Caller cancellation is not translated into a Redis timeout."""
    fake_redis = _HungReadRedis()
    store = RedisRuntimeCoordinationStore(
        cast(Redis, fake_redis),
        redis_operation_timeout_seconds=60,
    )
    operation = asyncio.create_task(store.get_operation("operation:req-1"))
    await asyncio.wait_for(fake_redis.started.wait(), timeout=0.2)

    operation.cancel()
    with pytest.raises(asyncio.CancelledError):
        await asyncio.wait_for(operation, timeout=0.2)

    assert fake_redis.cancelled.is_set()


@pytest.mark.asyncio
async def test_redis_operation_deadline_does_not_retry_ambiguous_append() -> None:
    """A timed-out mutation remains commit-ambiguous and is never retried."""
    fake_redis = _CommitAmbiguousAppendRedis()
    store = RedisRuntimeCoordinationStore(
        cast(Redis, fake_redis),
        redis_operation_timeout_seconds=0.01,
    )

    with pytest.raises(TimeoutError):
        await asyncio.wait_for(
            store.append_request("runner:runtime-1", _request_envelope("req-1")),
            timeout=0.2,
        )

    assert fake_redis.eval_calls == 1
    assert len(fake_redis.committed_payloads) == 1


@pytest.mark.asyncio
async def test_connection_registration_timeout_cannot_leave_partial_state() -> None:
    """Generation, its TTL, and the connection commit in one Redis mutation."""
    fake_redis = _CommitAmbiguousConnectionRegistrationRedis()
    store = RedisRuntimeCoordinationStore(
        cast(Redis, fake_redis),
        connection_generation_ttl_seconds=604800,
        redis_operation_timeout_seconds=0.01,
    )
    connected_at = _now()

    with pytest.raises(TimeoutError):
        await asyncio.wait_for(
            store.register_connection(
                kind=RuntimeConnectionKind.RUNNER,
                subject_id="runtime-1",
                connection_id="runner-a",
                owner_replica_id="control-a",
                connected_at=connected_at,
                heartbeat_at=connected_at,
                ttl_seconds=60,
                metadata={"workspace_path": "/workspace/agent"},
            ),
            timeout=0.2,
        )

    generation_key = (
        "azents:agent-runtime:coordination:connection-generation:runner:runtime-1"
    )
    connection_key = "azents:agent-runtime:coordination:connection:runner:runtime-1"
    assert fake_redis.eval_calls == 1
    assert fake_redis.cancelled.is_set()
    assert fake_redis.data[generation_key] == "1"
    assert fake_redis.ttls[generation_key] == 604800
    record = json.loads(fake_redis.data[connection_key])
    assert record["generation"] == 1
    assert record["connection_id"] == "runner-a"
    assert fake_redis.ttls[connection_key] == 60


@pytest.mark.asyncio
async def test_redis_claim_deadline_allows_configured_stream_block() -> None:
    """The claim deadline includes the requested XREADGROUP block interval."""
    fake_redis = _BlockingReadRedis(return_after_block=True)
    store = RedisRuntimeCoordinationStore(
        cast(Redis, fake_redis),
        redis_operation_timeout_seconds=0.01,
    )

    claimed = await asyncio.wait_for(
        store.claim_next_request(
            "runner:runtime-1",
            consumer_group="runtime-1:generation-1",
            consumer_id="replica-a",
            block_ms=30,
        ),
        timeout=0.2,
    )

    assert claimed is None
    assert fake_redis.received_block_ms == 30


@pytest.mark.asyncio
async def test_redis_claim_deadline_bounds_hung_blocking_read() -> None:
    """A lost XREADGROUP response times out after its block plus overhead."""
    fake_redis = _BlockingReadRedis(return_after_block=False)
    store = RedisRuntimeCoordinationStore(
        cast(Redis, fake_redis),
        redis_operation_timeout_seconds=0.01,
    )

    with pytest.raises(TimeoutError):
        await asyncio.wait_for(
            store.claim_next_request(
                "runner:runtime-1",
                consumer_group="runtime-1:generation-1",
                consumer_id="replica-a",
                block_ms=30,
            ),
            timeout=0.2,
        )

    assert fake_redis.received_block_ms == 30


@pytest.mark.asyncio
async def test_request_stream_can_be_claimed_and_acked(
    store: RuntimeCoordinationStore,
) -> None:
    """Request stream entries can be consumed by an owner group."""
    envelope = _request_envelope("req-1")

    cursor = await store.append_request("runner:runtime-1", envelope)
    claimed = await store.claim_next_request(
        "runner:runtime-1",
        consumer_group="runtime-1:generation-1",
        consumer_id="replica-a",
        block_ms=0,
    )

    assert claimed is not None
    assert claimed.cursor == cursor
    assert claimed.envelope == envelope

    await store.ack_request(
        "runner:runtime-1",
        consumer_group="runtime-1:generation-1",
        cursor=cursor,
    )
    assert (
        await store.claim_next_request(
            "runner:runtime-1",
            consumer_group="runtime-1:generation-1",
            consumer_id="replica-a",
            block_ms=0,
        )
        is None
    )


@pytest.mark.asyncio
async def test_unacked_request_can_be_reclaimed(
    store: RuntimeCoordinationStore,
) -> None:
    """Pending request entries can be reclaimed by a replacement consumer."""
    envelope = _request_envelope("req-1")

    cursor = await store.append_request("runner:runtime-1", envelope)
    first = await store.claim_next_request(
        "runner:runtime-1",
        consumer_group="runtime-1:generation-1",
        consumer_id="replica-a",
        block_ms=0,
        reclaim_idle_seconds=60,
    )
    blocked = await store.claim_next_request(
        "runner:runtime-1",
        consumer_group="runtime-1:generation-1",
        consumer_id="replica-b",
        block_ms=0,
        reclaim_idle_seconds=60,
    )
    reclaimed = await store.claim_next_request(
        "runner:runtime-1",
        consumer_group="runtime-1:generation-1",
        consumer_id="replica-b",
        block_ms=0,
        reclaim_idle_seconds=0,
    )

    assert first is not None
    assert first.cursor == cursor
    assert blocked is None
    assert reclaimed is not None
    assert reclaimed.cursor == cursor
    assert reclaimed.envelope == envelope

    await store.ack_request(
        "runner:runtime-1",
        consumer_group="runtime-1:generation-1",
        cursor=cursor,
    )
    assert (
        await store.claim_next_request(
            "runner:runtime-1",
            consumer_group="runtime-1:generation-1",
            consumer_id="replica-c",
            block_ms=0,
            reclaim_idle_seconds=0,
        )
        is None
    )


@pytest.mark.asyncio
async def test_reply_stream_cursor_resume(
    store: RuntimeCoordinationStore,
) -> None:
    """Reply streams support cursor-based resume."""
    first_cursor = await store.append_reply("reply:req-1", _reply("req-1", "accepted"))
    await store.append_reply("reply:req-1", _reply("req-1", "progress"))
    final_cursor = await store.append_reply(
        "reply:req-1",
        _reply("req-1", "final_success", final=True),
    )

    first_batch = await store.read_replies(
        "reply:req-1",
        after_cursor=None,
        limit=2,
    )
    resumed = await store.read_replies(
        "reply:req-1",
        after_cursor=first_cursor,
        limit=10,
    )

    assert [record.event.payload["message"] for record in first_batch] == [
        "accepted",
        "progress",
    ]
    assert [record.event.payload["message"] for record in resumed] == [
        "progress",
        "final_success",
    ]
    assert resumed[-1].cursor == final_cursor
    assert resumed[-1].event.final is True


@pytest.mark.asyncio
async def test_request_body_stream_preserves_binary_chunks(
    store: RuntimeCoordinationStore,
) -> None:
    """Body streams preserve binary chunk payloads and cursor order."""
    first = RuntimeBodyChunk(
        request_id="req-1",
        chunk_id=1,
        data=b"\x00hello",
        created_at=_now(),
        final=False,
    )
    second = RuntimeBodyChunk(
        request_id="req-1",
        chunk_id=2,
        data=b"\xffworld",
        created_at=_now(),
        final=True,
    )

    cursor = await store.append_body_chunk("body:req-1", first)
    await store.append_body_chunk("body:req-1", second)
    chunks = await store.read_body_chunks(
        "body:req-1",
        after_cursor=cursor,
        limit=10,
    )

    assert [record.chunk for record in chunks] == [second]


@pytest.mark.asyncio
async def test_operation_metadata_heartbeat_status_and_delete(
    store: RuntimeCoordinationStore,
) -> None:
    """Operation metadata supports heartbeat, final status, and cleanup."""
    created_at = _now()
    metadata = RuntimeOperationMetadata(
        operation_id="op-1",
        runtime_id="runtime-1",
        target=RuntimeCoordinationTarget.RUNNER,
        request_stream_id="runner:runtime-1",
        reply_stream_id="reply:req-1",
        status=RuntimeOperationStatus.ACTIVE,
        created_at=created_at,
        updated_at=created_at,
        deadline_at=created_at + timedelta(seconds=30),
        body_stream_id=None,
        last_heartbeat_at=None,
        last_event_at=None,
        cancel_requested_at=None,
        final_event_cursor=None,
    )

    await store.put_operation(metadata, ttl_seconds=60)
    heartbeat_at = created_at + timedelta(seconds=1)
    heartbeat = await store.heartbeat_operation("op-1", heartbeat_at=heartbeat_at)
    final = await store.update_operation_status(
        "op-1",
        status=RuntimeOperationStatus.FINAL,
        updated_at=heartbeat_at + timedelta(seconds=1),
        final_event_cursor="3",
    )

    assert heartbeat is not None
    assert heartbeat.last_heartbeat_at == heartbeat_at
    assert final is not None
    assert final.status == RuntimeOperationStatus.FINAL
    assert final.final_event_cursor == "3"

    await store.delete_operation("op-1")
    assert await store.get_operation("op-1") is None


@pytest.mark.asyncio
@pytest.mark.asyncio
async def test_try_start_operation_is_atomic(
    store: RuntimeCoordinationStore,
) -> None:
    """Only one concurrent start claim may transition ACTIVE to RUNNING."""
    created_at = _now()
    metadata = RuntimeOperationMetadata(
        operation_id="op-start-1",
        runtime_id="runtime-1",
        target=RuntimeCoordinationTarget.RUNNER,
        request_stream_id="runner:runtime-1",
        reply_stream_id="reply:req-start",
        status=RuntimeOperationStatus.ACTIVE,
        created_at=created_at,
        updated_at=created_at,
        deadline_at=created_at + timedelta(seconds=30),
        body_stream_id=None,
        last_heartbeat_at=None,
        last_event_at=None,
        cancel_requested_at=None,
        final_event_cursor=None,
    )
    await store.put_operation(metadata, ttl_seconds=60)

    first = await store.try_start_operation(
        "op-start-1",
        updated_at=created_at + timedelta(seconds=1),
    )
    second = await store.try_start_operation(
        "op-start-1",
        updated_at=created_at + timedelta(seconds=2),
    )
    canceled = await store.update_operation_status(
        "op-start-1",
        status=RuntimeOperationStatus.FINAL,
        updated_at=created_at + timedelta(seconds=3),
        final_event_cursor="cancel-cursor",
    )
    after_final = await store.try_start_operation(
        "op-start-1",
        updated_at=created_at + timedelta(seconds=4),
    )

    assert first is not None
    assert first.status is RuntimeOperationStatus.RUNNING
    assert second is None
    assert canceled is not None
    assert canceled.status is RuntimeOperationStatus.FINAL
    assert canceled.final_event_cursor == "cancel-cursor"
    assert after_final is None


@pytest.mark.asyncio
async def test_append_reply_for_operation_rejects_late_final(
    store: RuntimeCoordinationStore,
) -> None:
    """Late Runner finals must not replace an authoritative canceled cursor."""
    created_at = _now()
    metadata = RuntimeOperationMetadata(
        operation_id="op-final-1",
        runtime_id="runtime-1",
        target=RuntimeCoordinationTarget.RUNNER,
        request_stream_id="runner:runtime-1",
        reply_stream_id="reply:req-final",
        status=RuntimeOperationStatus.ACTIVE,
        created_at=created_at,
        updated_at=created_at,
        deadline_at=created_at + timedelta(seconds=30),
        body_stream_id=None,
        last_heartbeat_at=None,
        last_event_at=None,
        cancel_requested_at=None,
        final_event_cursor=None,
    )
    await store.put_operation(metadata, ttl_seconds=60)
    canceled = await store.append_reply_for_operation(
        "reply:req-final",
        _reply("req-final", "canceled", final=True),
        operation_id="op-final-1",
    )
    late = await store.append_reply_for_operation(
        "reply:req-final",
        _reply("req-final", "late-success", final=True),
        operation_id="op-final-1",
    )

    assert canceled is not None
    cursor, updated = canceled
    assert updated.status is RuntimeOperationStatus.FINAL
    assert updated.final_event_cursor == cursor
    assert late is None
    current = await store.get_operation("op-final-1")
    assert current is not None
    assert current.final_event_cursor == cursor
    replies = await store.read_replies("reply:req-final", after_cursor=None, limit=10)
    assert len(replies) == 1
    assert replies[0].event.payload["message"] == "canceled"


async def test_connection_registry_issues_generation_fences(
    store: RuntimeCoordinationStore,
) -> None:
    """A newer connection generation fences out stale heartbeats and revokes."""
    connected_at = _now()
    first = await store.register_connection(
        kind=RuntimeConnectionKind.RUNNER,
        subject_id="runtime-1",
        connection_id="runner-a",
        owner_replica_id="control-a",
        connected_at=connected_at,
        heartbeat_at=connected_at,
        ttl_seconds=60,
        metadata={"workspace_path": "/workspace/agent"},
    )
    second = await store.register_connection(
        kind=RuntimeConnectionKind.RUNNER,
        subject_id="runtime-1",
        connection_id="runner-b",
        owner_replica_id="control-b",
        connected_at=connected_at,
        heartbeat_at=connected_at,
        ttl_seconds=60,
        metadata={"workspace_path": "/workspace/agent"},
    )

    assert first.generation == 1
    assert second.generation == 2
    assert (
        await store.heartbeat_connection(
            kind=RuntimeConnectionKind.RUNNER,
            subject_id="runtime-1",
            generation=first.generation,
            heartbeat_at=connected_at + timedelta(seconds=1),
            ttl_seconds=60,
        )
        is False
    )
    assert (
        await store.heartbeat_connection(
            kind=RuntimeConnectionKind.RUNNER,
            subject_id="runtime-1",
            generation=second.generation,
            heartbeat_at=connected_at + timedelta(seconds=1),
            ttl_seconds=60,
        )
        is True
    )

    current = await store.get_connection(
        kind=RuntimeConnectionKind.RUNNER,
        subject_id="runtime-1",
    )
    assert current is not None
    assert current.connection_id == "runner-b"
    assert (
        await store.revoke_connection(
            kind=RuntimeConnectionKind.RUNNER,
            subject_id="runtime-1",
            generation=first.generation,
        )
        is False
    )
    assert (
        await store.revoke_connection(
            kind=RuntimeConnectionKind.RUNNER,
            subject_id="runtime-1",
            generation=second.generation,
        )
        is True
    )
    assert (
        await store.get_connection(
            kind=RuntimeConnectionKind.RUNNER,
            subject_id="runtime-1",
        )
        is None
    )


@pytest.mark.asyncio
async def test_redis_connection_revoke_is_generation_fenced() -> None:
    """Redis stale revokes must not delete a newer connection generation."""
    fake_redis = FakeRedisConnectionStore()
    store = RedisRuntimeCoordinationStore(cast(Redis, fake_redis))
    connected_at = _now()
    first = await store.register_connection(
        kind=RuntimeConnectionKind.RUNNER,
        subject_id="runtime-1",
        connection_id="runner-a",
        owner_replica_id="control-a",
        connected_at=connected_at,
        heartbeat_at=connected_at,
        ttl_seconds=60,
        metadata={"workspace_path": "/workspace/agent"},
    )
    second = await store.register_connection(
        kind=RuntimeConnectionKind.RUNNER,
        subject_id="runtime-1",
        connection_id="runner-b",
        owner_replica_id="control-a",
        connected_at=connected_at,
        heartbeat_at=connected_at,
        ttl_seconds=60,
        metadata={"workspace_path": "/workspace/agent"},
    )

    stale_revoked = await store.revoke_connection(
        kind=RuntimeConnectionKind.RUNNER,
        subject_id="runtime-1",
        generation=first.generation,
    )
    current = await store.get_connection(
        kind=RuntimeConnectionKind.RUNNER,
        subject_id="runtime-1",
    )

    assert stale_revoked is False
    assert current is not None
    assert current.generation == second.generation
    assert current.connection_id == "runner-b"


@pytest.mark.asyncio
async def test_redis_connection_heartbeat_is_generation_fenced() -> None:
    """Redis stale heartbeats must not overwrite a newer connection generation."""
    fake_redis = FakeRedisConnectionStore()
    store = RedisRuntimeCoordinationStore(cast(Redis, fake_redis))
    connected_at = _now()
    first = await store.register_connection(
        kind=RuntimeConnectionKind.RUNNER,
        subject_id="runtime-1",
        connection_id="runner-a",
        owner_replica_id="control-a",
        connected_at=connected_at,
        heartbeat_at=connected_at,
        ttl_seconds=60,
        metadata={"workspace_path": "/workspace/agent"},
    )
    second = await store.register_connection(
        kind=RuntimeConnectionKind.RUNNER,
        subject_id="runtime-1",
        connection_id="runner-b",
        owner_replica_id="control-a",
        connected_at=connected_at,
        heartbeat_at=connected_at,
        ttl_seconds=60,
        metadata={"workspace_path": "/workspace/agent"},
    )

    stale_heartbeat = await store.heartbeat_connection(
        kind=RuntimeConnectionKind.RUNNER,
        subject_id="runtime-1",
        generation=first.generation,
        heartbeat_at=connected_at + timedelta(seconds=1),
        ttl_seconds=60,
    )
    current = await store.get_connection(
        kind=RuntimeConnectionKind.RUNNER,
        subject_id="runtime-1",
    )

    assert stale_heartbeat is False
    assert current is not None
    assert current.generation == second.generation
    assert current.connection_id == "runner-b"


@pytest.mark.asyncio
async def test_redis_get_connection_does_not_delete_reconnected_generation() -> None:
    """Expired-record cleanup must not delete a concurrent reconnect."""
    fake_redis = FakeRedisConnectionStore()
    store = RedisRuntimeCoordinationStore(cast(Redis, fake_redis))
    key = "azents:agent-runtime:coordination:connection:runner:runtime-1"
    now = _now()
    fake_redis.data[key] = _fake_connection_json(
        generation=1,
        connection_id="runner-a",
        expires_at=now - timedelta(seconds=1),
    )

    def reconnect_after_stale_get(requested_key: str) -> None:
        if requested_key != key:
            return
        fake_redis.data[key] = _fake_connection_json(
            generation=2,
            connection_id="runner-b",
            expires_at=now + timedelta(seconds=60),
        )

    fake_redis.after_get = reconnect_after_stale_get
    stale = await store.get_connection(
        kind=RuntimeConnectionKind.RUNNER,
        subject_id="runtime-1",
    )
    fake_redis.after_get = None
    current = await store.get_connection(
        kind=RuntimeConnectionKind.RUNNER,
        subject_id="runtime-1",
    )

    assert stale is None
    assert current is not None
    assert current.generation == 2
    assert current.connection_id == "runner-b"


@pytest.mark.asyncio
async def test_redis_streams_have_ttl(
    redis_store: tuple[RedisRuntimeCoordinationStore, Redis],
) -> None:
    """TTL is set on Redis coordination stream key."""
    store, redis = redis_store

    await store.append_request("runner:runtime-1", _request_envelope("req-1"))
    await store.append_reply("reply:req-1", _reply("req-1", "accepted"))
    await store.append_body_chunk(
        "body:req-1",
        RuntimeBodyChunk(
            request_id="req-1",
            chunk_id=1,
            data=b"hello",
            created_at=_now(),
            final=True,
        ),
    )

    assert (
        await redis.ttl(
            "azents:agent-runtime:coordination:stream:request:runner:runtime-1"
        )
        > 0
    )
    assert (
        await redis.ttl("azents:agent-runtime:coordination:stream:reply:reply:req-1")
        > 0
    )
    assert (
        await redis.ttl("azents:agent-runtime:coordination:stream:body:body:req-1") > 0
    )


@pytest.mark.asyncio
async def test_redis_empty_request_stream_created_by_group_has_ttl(
    redis_store: tuple[RedisRuntimeCoordinationStore, Redis],
) -> None:
    """TTL is also set on empty request stream created by consumer group creation."""
    store, redis = redis_store

    claimed = await store.claim_next_request(
        "runner:runtime-1",
        consumer_group="runtime-1:generation-1",
        consumer_id="replica-a",
        block_ms=0,
    )

    assert claimed is None
    assert (
        await redis.ttl(
            "azents:agent-runtime:coordination:stream:request:runner:runtime-1"
        )
        > 0
    )


@pytest.mark.asyncio
async def test_redis_connection_generation_has_ttl(
    redis_store: tuple[RedisRuntimeCoordinationStore, Redis],
) -> None:
    """TTL is set on connection generation counter."""
    store, redis = redis_store
    connected_at = _now()

    await store.register_connection(
        kind=RuntimeConnectionKind.RUNNER,
        subject_id="runtime-1",
        connection_id="runner-a",
        owner_replica_id="control-a",
        connected_at=connected_at,
        heartbeat_at=connected_at,
        ttl_seconds=60,
        metadata={"workspace_path": "/workspace/agent"},
    )

    assert (
        await redis.ttl(
            "azents:agent-runtime:coordination:connection-generation:runner:runtime-1"
        )
        > 0
    )


def _fake_connection_json(
    *,
    generation: int,
    connection_id: str,
    expires_at: datetime,
) -> str:
    now = _now()
    return json.dumps(
        {
            "kind": RuntimeConnectionKind.RUNNER.value,
            "subject_id": "runtime-1",
            "connection_id": connection_id,
            "owner_replica_id": "control-a",
            "generation": generation,
            "connected_at": now.isoformat(),
            "heartbeat_at": now.isoformat(),
            "expires_at": expires_at.isoformat(),
            "metadata": {"workspace_path": "/workspace/agent"},
        }
    )


def _request_envelope(request_id: str) -> RuntimeRequestEnvelope:
    return RuntimeRequestEnvelope(
        request_id=request_id,
        runtime_id="runtime-1",
        target=RuntimeCoordinationTarget.RUNNER,
        generation=1,
        operation_type="bash",
        payload={"command": "echo ok"},
        reply_stream_id=f"reply:{request_id}",
        deadline_at=_now() + timedelta(seconds=30),
        body_stream_id=None,
    )


def _reply(request_id: str, message: str, *, final: bool = False) -> RuntimeReplyEvent:
    event_type = (
        RuntimeReplyEventType.FINAL_SUCCESS if final else RuntimeReplyEventType.PROGRESS
    )
    if message == "accepted":
        event_type = RuntimeReplyEventType.ACCEPTED
    return RuntimeReplyEvent(
        request_id=request_id,
        runtime_id="runtime-1",
        generation=1,
        event_type=event_type,
        payload={"message": message},
        created_at=_now(),
        final=final,
    )


def _now() -> datetime:
    return datetime.now(timezone.utc)
