"""Runtime coordination store contract tests."""

import asyncio
import dataclasses
import json
from collections.abc import AsyncGenerator, Callable
from datetime import datetime, timedelta, timezone
from typing import cast

import pytest
import pytest_asyncio
from azents_runtime_control.system_metrics import (
    RunnerSystemMetricAvailability,
    RunnerSystemMetricObservation,
    RunnerSystemMetricsScope,
)
from redis.asyncio import Redis

from azents.runtime.coordination.data import (
    RuntimeBodyChunk,
    RuntimeConnectionKind,
    RuntimeConnectionRecord,
    RuntimeCoordinationTarget,
    RuntimeFencedMutationStatus,
    RuntimeOperationMetadata,
    RuntimeOperationStatus,
    RuntimeOperationTransferDirection,
    RuntimeReplyEvent,
    RuntimeReplyEventType,
    RuntimeRequestEnvelope,
    RuntimeSystemMetricsSample,
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
        *args: object,
    ) -> int | str:
        keys = [str(value) for value in args[:numkeys]]
        values = args[numkeys:]
        if "INCR" in script:
            generation_key, connection_key = keys
            generation = int(self.data.get(generation_key, "0")) + 1
            self.data[generation_key] = str(generation)
            payload = json.loads(str(values[0]))
            payload["generation"] = generation
            encoded = json.dumps(payload)
            self.data[connection_key] = encoded
            return encoded
        key = keys[0]
        raw = self.data.get(key)
        if raw is None:
            return 0
        payload = json.loads(raw)
        if int(payload["generation"]) != int(cast(int, values[0])):
            return 0
        if "DEL" in script:
            self.data.pop(key, None)
            return 1
        if "SET" in script:
            self.data[key] = str(values[1])
            return 1
        return 0


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
        request_id="req-1",
        runtime_id="runtime-1",
        target=RuntimeCoordinationTarget.RUNNER,
        target_subject_id="runtime-1",
        generation=1,
        operation_type="test.operation",
        transfer_id=None,
        transfer_attempt_id=None,
        transfer_dispatch_id=None,
        transfer_direction=None,
        request_stream_id="runner:runtime-1",
        request_cursor=None,
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
async def test_ensure_operation_metadata_is_atomic_and_fences_conflicts(
    store: RuntimeCoordinationStore,
) -> None:
    """Compatible concurrent creation is idempotent without replacing a final."""
    created_at = _now()
    metadata = RuntimeOperationMetadata(
        operation_id="transfer-operation",
        request_id="transfer-request",
        runtime_id="runtime-1",
        target=RuntimeCoordinationTarget.RUNNER,
        target_subject_id="runtime-1",
        generation=3,
        operation_type="file.transfer.v1",
        transfer_id="transfer-1",
        transfer_attempt_id="attempt-1",
        transfer_dispatch_id="dispatch-1",
        transfer_direction=RuntimeOperationTransferDirection.DOWNLOAD,
        request_stream_id="runner:runtime-1:generation:3",
        request_cursor=None,
        reply_stream_id="reply:transfer-operation",
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
    ensured = await asyncio.gather(
        *(store.ensure_operation_metadata(metadata, ttl_seconds=60) for _ in range(2))
    )

    assert ensured == [metadata, metadata]
    conflicting = dataclasses.replace(metadata, generation=4)
    assert await store.ensure_operation_metadata(conflicting, ttl_seconds=60) is None
    conflicting_subject = dataclasses.replace(
        metadata,
        target_subject_id="runtime-2",
    )
    assert (
        await store.ensure_operation_metadata(conflicting_subject, ttl_seconds=60)
        is None
    )
    conflicting_request = dataclasses.replace(metadata, request_id="other-request")
    assert (
        await store.ensure_operation_metadata(conflicting_request, ttl_seconds=60)
        is None
    )
    conflicting_direction = dataclasses.replace(
        metadata,
        transfer_direction=RuntimeOperationTransferDirection.UPLOAD,
    )
    assert (
        await store.ensure_operation_metadata(conflicting_direction, ttl_seconds=60)
        is None
    )
    final = await store.update_operation_status(
        metadata.operation_id,
        status=RuntimeOperationStatus.FINAL,
        updated_at=created_at + timedelta(seconds=1),
        final_event_cursor="1",
    )
    assert final is not None
    assert await store.ensure_operation_metadata(metadata, ttl_seconds=60) is None


@pytest.mark.asyncio
@pytest.mark.asyncio
async def test_try_start_operation_is_atomic(
    store: RuntimeCoordinationStore,
) -> None:
    """Only one concurrent start claim may transition ACTIVE to RUNNING."""
    created_at = _now()
    metadata = RuntimeOperationMetadata(
        operation_id="op-start-1",
        request_id="req-start",
        runtime_id="runtime-1",
        target=RuntimeCoordinationTarget.RUNNER,
        target_subject_id="runtime-1",
        generation=1,
        operation_type="test.operation",
        transfer_id=None,
        transfer_attempt_id=None,
        transfer_dispatch_id=None,
        transfer_direction=None,
        request_stream_id="runner:runtime-1",
        request_cursor=None,
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
async def test_cancel_requested_status_records_timestamp_and_blocks_start(
    store: RuntimeCoordinationStore,
) -> None:
    """Cancellation status preserves its request time and rejects start claims."""
    created_at = _now()
    cancel_requested_at = created_at + timedelta(seconds=1)
    metadata = RuntimeOperationMetadata(
        operation_id="op-cancel-1",
        request_id="req-cancel",
        runtime_id="runtime-1",
        target=RuntimeCoordinationTarget.RUNNER,
        target_subject_id="runtime-1",
        generation=1,
        operation_type="test.operation",
        transfer_id=None,
        transfer_attempt_id=None,
        transfer_dispatch_id=None,
        transfer_direction=None,
        request_stream_id="runner:runtime-1",
        request_cursor=None,
        reply_stream_id="reply:req-cancel",
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

    canceled = await store.update_operation_status(
        "op-cancel-1",
        status=RuntimeOperationStatus.CANCEL_REQUESTED,
        updated_at=cancel_requested_at,
        final_event_cursor=None,
    )
    started = await store.try_start_operation(
        "op-cancel-1",
        updated_at=cancel_requested_at + timedelta(seconds=1),
    )

    assert canceled is not None
    assert canceled.status is RuntimeOperationStatus.CANCEL_REQUESTED
    assert canceled.cancel_requested_at == cancel_requested_at
    assert started is None


@pytest.mark.asyncio
async def test_append_reply_for_operation_rejects_late_final(
    store: RuntimeCoordinationStore,
) -> None:
    """Late Runner finals must not replace an authoritative canceled cursor."""
    created_at = _now()
    metadata = RuntimeOperationMetadata(
        operation_id="op-final-1",
        request_id="req-final",
        runtime_id="runtime-1",
        target=RuntimeCoordinationTarget.RUNNER,
        target_subject_id="runtime-1",
        generation=1,
        operation_type="test.operation",
        transfer_id=None,
        transfer_attempt_id=None,
        transfer_dispatch_id=None,
        transfer_direction=None,
        request_stream_id="runner:runtime-1",
        request_cursor=None,
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


@pytest.mark.asyncio
async def test_concurrent_registration_keeps_highest_generation_current(
    store: RuntimeCoordinationStore,
) -> None:
    """Concurrent registration cannot restore a lower current generation."""
    connected_at = _now()
    registered = await asyncio.gather(
        *(
            store.register_connection(
                kind=RuntimeConnectionKind.RUNNER,
                subject_id="runtime-1",
                connection_id=f"runner-{index}",
                owner_replica_id=f"control-{index}",
                connected_at=connected_at,
                heartbeat_at=connected_at,
                ttl_seconds=60,
                metadata={},
            )
            for index in range(20)
        )
    )

    current = await store.get_connection(
        kind=RuntimeConnectionKind.RUNNER,
        subject_id="runtime-1",
    )

    assert current is not None
    assert current.generation == max(record.generation for record in registered)


@pytest.mark.asyncio
async def test_operation_request_append_rejects_replaced_connection(
    store: RuntimeCoordinationStore,
) -> None:
    """A replaced generation cannot create metadata or append a request."""
    connected_at = _now()
    first = await _register_runner(store, connected_at=connected_at)
    envelope = _operation_envelope("req-stale", generation=first.generation)
    metadata = _operation_metadata(envelope)
    await _register_runner(
        store,
        connected_at=connected_at + timedelta(seconds=1),
    )

    result = await store.append_operation_request_if_connection_current(
        connection_kind=RuntimeConnectionKind.RUNNER,
        connection_subject_id="runtime-1",
        connection_generation=first.generation,
        metadata=metadata,
        envelope=envelope,
        ttl_seconds=60,
    )

    assert result.status is RuntimeFencedMutationStatus.STALE_GENERATION
    assert result.value is None
    assert await store.get_operation(metadata.operation_id) is None
    assert (
        await store.claim_next_request(
            metadata.request_stream_id,
            consumer_group="runtime-1:generation-1",
            consumer_id="control-a",
            block_ms=0,
        )
        is None
    )


@pytest.mark.asyncio
async def test_operation_request_append_is_idempotent(
    store: RuntimeCoordinationStore,
) -> None:
    """Retrying one exact admitted request preserves a single stream entry."""
    connected_at = _now()
    accepted = await _register_runner(store, connected_at=connected_at)
    envelope = _operation_envelope("req-idempotent", generation=accepted.generation)
    metadata = _operation_metadata(envelope)

    first = await store.append_operation_request_if_connection_current(
        connection_kind=RuntimeConnectionKind.RUNNER,
        connection_subject_id="runtime-1",
        connection_generation=accepted.generation,
        metadata=metadata,
        envelope=envelope,
        ttl_seconds=60,
    )
    second = await store.append_operation_request_if_connection_current(
        connection_kind=RuntimeConnectionKind.RUNNER,
        connection_subject_id="runtime-1",
        connection_generation=accepted.generation,
        metadata=metadata,
        envelope=envelope,
        ttl_seconds=60,
    )
    claimed = await store.claim_next_request(
        metadata.request_stream_id,
        consumer_group="runtime-1:generation-1",
        consumer_id="control-a",
        block_ms=0,
    )
    duplicate = await store.claim_next_request(
        metadata.request_stream_id,
        consumer_group="runtime-1:generation-1",
        consumer_id="control-a",
        block_ms=0,
    )

    assert first.status is RuntimeFencedMutationStatus.APPLIED
    assert second.status is RuntimeFencedMutationStatus.APPLIED
    assert first.value is not None
    assert second.value is not None
    assert first.value.request_cursor == second.value.request_cursor
    assert claimed is not None
    assert claimed.envelope == envelope
    assert duplicate is None


@pytest.mark.asyncio
async def test_cancel_start_and_reply_reject_replaced_connection(
    store: RuntimeCoordinationStore,
) -> None:
    """A replaced Runner cannot cancel, start, or finalize its operation."""
    connected_at = _now()
    first = await _register_runner(store, connected_at=connected_at)
    envelope = _operation_envelope("req-fenced", generation=first.generation)
    metadata = _operation_metadata(envelope)
    appended = await store.append_operation_request_if_connection_current(
        connection_kind=RuntimeConnectionKind.RUNNER,
        connection_subject_id="runtime-1",
        connection_generation=first.generation,
        metadata=metadata,
        envelope=envelope,
        ttl_seconds=60,
    )
    assert appended.status is RuntimeFencedMutationStatus.APPLIED
    await _register_runner(
        store,
        connected_at=connected_at + timedelta(seconds=1),
    )
    mutation_at = connected_at + timedelta(seconds=2)
    cancellation = await store.request_operation_cancel_if_connection_current(
        connection_kind=RuntimeConnectionKind.RUNNER,
        connection_subject_id="runtime-1",
        connection_generation=first.generation,
        operation_id=metadata.operation_id,
        expected_runtime_id="runtime-1",
        expected_target=RuntimeCoordinationTarget.RUNNER,
        envelope=RuntimeRequestEnvelope(
            request_id="req-cancel",
            runtime_id="runtime-1",
            target=RuntimeCoordinationTarget.RUNNER,
            generation=first.generation,
            operation_type="operation.cancel",
            payload={"operation_id": metadata.operation_id},
            reply_stream_id=metadata.reply_stream_id,
            deadline_at=metadata.deadline_at,
            body_stream_id=None,
        ),
        updated_at=mutation_at,
    )
    started = await store.try_start_operation_if_connection_current(
        connection_kind=RuntimeConnectionKind.RUNNER,
        connection_subject_id="runtime-1",
        connection_generation=first.generation,
        operation_id=metadata.operation_id,
        expected_runtime_id="runtime-1",
        expected_target=RuntimeCoordinationTarget.RUNNER,
        updated_at=mutation_at,
    )
    replied = await store.append_operation_reply_if_connection_current(
        connection_kind=RuntimeConnectionKind.RUNNER,
        connection_subject_id="runtime-1",
        connection_generation=first.generation,
        operation_id=metadata.operation_id,
        expected_runtime_id="runtime-1",
        expected_target=RuntimeCoordinationTarget.RUNNER,
        stream_id=metadata.reply_stream_id,
        event=RuntimeReplyEvent(
            request_id=metadata.request_id,
            runtime_id=metadata.runtime_id,
            generation=metadata.generation,
            event_type=RuntimeReplyEventType.FINAL_SUCCESS,
            payload={"success": True},
            created_at=mutation_at,
            final=True,
        ),
    )
    current = await store.get_operation(metadata.operation_id)
    replies = await store.read_replies(
        metadata.reply_stream_id,
        after_cursor=None,
        limit=10,
    )

    assert cancellation.status is RuntimeFencedMutationStatus.STALE_GENERATION
    assert started.status is RuntimeFencedMutationStatus.STALE_GENERATION
    assert replied.status is RuntimeFencedMutationStatus.STALE_GENERATION
    assert current is not None
    assert current.status is RuntimeOperationStatus.ACTIVE
    assert replies == []


@pytest.mark.asyncio
async def test_system_metrics_series_rejects_non_increasing_sequences(
    store: RuntimeCoordinationStore,
) -> None:
    """Only a higher sequence appends to one generation-scoped series."""
    measured_at = _now()
    first = _metrics_sample(sequence=1, measured_at=measured_at)
    second = _metrics_sample(
        sequence=2,
        measured_at=measured_at + timedelta(minutes=1),
    )

    assert await store.append_runner_system_metrics(
        runtime_id="runtime-1",
        generation=7,
        sample=first,
    )
    assert not await store.append_runner_system_metrics(
        runtime_id="runtime-1",
        generation=7,
        sample=first,
    )
    assert await store.append_runner_system_metrics(
        runtime_id="runtime-1",
        generation=7,
        sample=second,
    )
    assert not await store.append_runner_system_metrics(
        runtime_id="runtime-1",
        generation=7,
        sample=first,
    )

    series = await store.read_runner_system_metrics(
        runtime_id="runtime-1",
        generation=7,
        current_time=second.measured_at,
    )

    assert [sample.sequence for sample in series] == [1, 2]


@pytest.mark.asyncio
async def test_system_metrics_series_is_bounded_and_generation_scoped(
    store: RuntimeCoordinationStore,
) -> None:
    """The store retains at most 60 samples without crossing generations."""
    start = _now()
    for sequence in range(1, 62):
        assert await store.append_runner_system_metrics(
            runtime_id="runtime-1",
            generation=7,
            sample=_metrics_sample(
                sequence=sequence,
                measured_at=start + timedelta(minutes=sequence - 1),
            ),
        )
    assert await store.append_runner_system_metrics(
        runtime_id="runtime-1",
        generation=8,
        sample=_metrics_sample(sequence=1, measured_at=start + timedelta(hours=1)),
    )

    current = await store.read_runner_system_metrics(
        runtime_id="runtime-1",
        generation=7,
        current_time=start + timedelta(hours=1),
    )
    replacement = await store.read_runner_system_metrics(
        runtime_id="runtime-1",
        generation=8,
        current_time=start + timedelta(hours=1),
    )

    assert len(current) == 60
    assert current[0].sequence == 2
    assert current[-1].sequence == 61
    assert [sample.sequence for sample in replacement] == [1]


@pytest.mark.asyncio
async def test_system_metrics_series_filters_and_expires_after_one_hour(
    store: RuntimeCoordinationStore,
) -> None:
    """A sample older than one hour is never returned."""
    measured_at = _now()
    assert await store.append_runner_system_metrics(
        runtime_id="runtime-1",
        generation=7,
        sample=_metrics_sample(sequence=1, measured_at=measured_at),
    )

    series = await store.read_runner_system_metrics(
        runtime_id="runtime-1",
        generation=7,
        current_time=measured_at + timedelta(hours=1, microseconds=1),
    )

    assert series == []


@pytest.mark.asyncio
async def test_concurrent_system_metrics_append_preserves_highest_sequence(
    store: RuntimeCoordinationStore,
) -> None:
    """Concurrent higher sequences cannot be replaced by a lower sequence."""
    measured_at = _now()
    results = await asyncio.gather(
        store.append_runner_system_metrics(
            runtime_id="runtime-1",
            generation=7,
            sample=_metrics_sample(sequence=2, measured_at=measured_at),
        ),
        store.append_runner_system_metrics(
            runtime_id="runtime-1",
            generation=7,
            sample=_metrics_sample(
                sequence=3,
                measured_at=measured_at + timedelta(microseconds=1),
            ),
        ),
    )
    series = await store.read_runner_system_metrics(
        runtime_id="runtime-1",
        generation=7,
        current_time=measured_at + timedelta(seconds=1),
    )

    assert any(results)
    assert series[-1].sequence == 3
    assert [sample.sequence for sample in series] == sorted(
        {sample.sequence for sample in series}
    )


@pytest.mark.asyncio
async def test_redis_system_metrics_append_refreshes_one_hour_ttl(
    redis_store: tuple[RedisRuntimeCoordinationStore, Redis],
) -> None:
    """Redis retains the bounded series for one hour from the last append."""
    store, client = redis_store
    assert await store.append_runner_system_metrics(
        runtime_id="runtime-1",
        generation=7,
        sample=_metrics_sample(sequence=1, measured_at=_now()),
    )

    keys = await client.keys("*system-metrics*")

    assert len(keys) == 1
    ttl = await client.ttl(keys[0])
    assert 0 < ttl <= 3600


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
async def test_redis_connection_generation_is_persistent(
    redis_store: tuple[RedisRuntimeCoordinationStore, Redis],
) -> None:
    """Connection generation counters remain after current connections expire."""
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
        == -1
    )


@pytest.mark.asyncio
async def test_redis_registration_removes_legacy_generation_counter_ttl(
    redis_store: tuple[RedisRuntimeCoordinationStore, Redis],
) -> None:
    """Registration increments a legacy counter and atomically removes its TTL."""
    store, redis = redis_store
    key = "azents:agent-runtime:coordination:connection-generation:provider:provider-1"
    await redis.set(key, "41", ex=60)
    assert await redis.ttl(key) > 0

    connected_at = _now()
    first = await store.register_connection(
        kind=RuntimeConnectionKind.PROVIDER,
        subject_id="provider-1",
        connection_id="provider-a",
        owner_replica_id="control-a",
        connected_at=connected_at,
        heartbeat_at=connected_at,
        ttl_seconds=60,
        metadata={},
    )

    assert first.generation == 42
    assert await redis.ttl(key) == -1

    second = await store.register_connection(
        kind=RuntimeConnectionKind.PROVIDER,
        subject_id="provider-1",
        connection_id="provider-b",
        owner_replica_id="control-b",
        connected_at=connected_at,
        heartbeat_at=connected_at,
        ttl_seconds=60,
        metadata={},
    )

    assert second.generation == 43
    assert await redis.ttl(key) == -1


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


def _metrics_sample(
    *,
    sequence: int,
    measured_at: datetime,
) -> RuntimeSystemMetricsSample:
    available = RunnerSystemMetricObservation(
        availability=RunnerSystemMetricAvailability.AVAILABLE,
        used=sequence * 100,
        total=1000,
    )
    unavailable = RunnerSystemMetricObservation(
        availability=RunnerSystemMetricAvailability.UNAVAILABLE,
        used=None,
        total=None,
    )
    return RuntimeSystemMetricsSample(
        sequence=sequence,
        measured_at=measured_at,
        scope=RunnerSystemMetricsScope.CONTAINER,
        cpu=unavailable if sequence == 1 else available,
        memory=available,
        disk=available,
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


async def _register_runner(
    store: RuntimeCoordinationStore,
    *,
    connected_at: datetime,
) -> RuntimeConnectionRecord:
    return await store.register_connection(
        kind=RuntimeConnectionKind.RUNNER,
        subject_id="runtime-1",
        connection_id=f"runner-{connected_at.timestamp()}",
        owner_replica_id="control-a",
        connected_at=connected_at,
        heartbeat_at=connected_at,
        ttl_seconds=60,
        metadata={},
    )


def _operation_envelope(
    request_id: str,
    *,
    generation: int,
) -> RuntimeRequestEnvelope:
    deadline_at = _now() + timedelta(seconds=30)
    return RuntimeRequestEnvelope(
        request_id=request_id,
        runtime_id="runtime-1",
        target=RuntimeCoordinationTarget.RUNNER,
        generation=generation,
        operation_type="bash",
        payload={"command": "echo ok"},
        reply_stream_id=f"runner:runtime-1:generation:{generation}:replies",
        deadline_at=deadline_at,
        body_stream_id=None,
    )


def _operation_metadata(
    envelope: RuntimeRequestEnvelope,
) -> RuntimeOperationMetadata:
    created_at = _now()
    return RuntimeOperationMetadata(
        operation_id=f"operation:{envelope.request_id}",
        request_id=envelope.request_id,
        runtime_id=envelope.runtime_id,
        target=envelope.target,
        target_subject_id=envelope.runtime_id,
        generation=envelope.generation,
        operation_type=envelope.operation_type,
        transfer_id=None,
        transfer_attempt_id=None,
        transfer_dispatch_id=None,
        transfer_direction=None,
        request_stream_id=(
            f"runner:runtime-1:generation:{envelope.generation}:requests"
        ),
        request_cursor=None,
        reply_stream_id=envelope.reply_stream_id,
        status=RuntimeOperationStatus.ACTIVE,
        created_at=created_at,
        updated_at=created_at,
        deadline_at=envelope.deadline_at,
        body_stream_id=envelope.body_stream_id,
        last_heartbeat_at=None,
        last_event_at=None,
        cancel_requested_at=None,
        final_event_cursor=None,
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
