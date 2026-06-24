"""Runtime coordination store contract tests."""

from collections.abc import AsyncGenerator
from datetime import datetime, timedelta, timezone

import pytest
import pytest_asyncio
from redis.asyncio import Redis

from azents.runtime.coordination.data import (
    RuntimeBackgroundCompletionClaimStatus,
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
        background=False,
        background_context=None,
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
async def test_background_completion_claim_is_exclusive_until_published(
    store: RuntimeCoordinationStore,
) -> None:
    """Background completion claims are exclusive and markable as published."""
    claimed_at = _now()

    first = await store.claim_background_completion(
        operation_id="op-1",
        claimant_id="worker-a",
        claimed_at=claimed_at,
        ttl_seconds=60,
    )
    second = await store.claim_background_completion(
        operation_id="op-1",
        claimant_id="worker-b",
        claimed_at=claimed_at,
        ttl_seconds=60,
    )
    repeat = await store.claim_background_completion(
        operation_id="op-1",
        claimant_id="worker-a",
        claimed_at=claimed_at,
        ttl_seconds=60,
    )
    published = await store.mark_background_completion_published(
        operation_id="op-1",
        claimant_id="worker-a",
        published_at=claimed_at + timedelta(seconds=1),
    )

    assert first is not None
    assert second is None
    assert repeat == first
    assert published is not None
    assert published.status == RuntimeBackgroundCompletionClaimStatus.PUBLISHED
    assert (
        await store.mark_background_completion_published(
            operation_id="op-1",
            claimant_id="worker-b",
            published_at=claimed_at + timedelta(seconds=2),
        )
        is None
    )

    await store.delete_background_completion_claim("op-1")
    assert await store.get_background_completion_claim("op-1") is None


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
