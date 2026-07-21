"""Runtime control protocol service tests."""

from datetime import datetime, timedelta, timezone

import pytest
from azents_runtime_control.provider import (
    RuntimeLifecycleCommandType as RuntimeProviderCommandType,
)

from azents.runtime.control_protocol.data import (
    RuntimeDispatchResult,
    RuntimeProtocolCapabilities,
    RuntimeProtocolRouteUnavailable,
    RuntimeProtocolStaleGeneration,
    RuntimeProviderCommand,
    RuntimeProviderRegistration,
    RuntimeReplyAppendResult,
    RuntimeRunnerOperation,
    RuntimeRunnerRegistration,
)
from azents.runtime.control_protocol.service import (
    RuntimeControlProtocolService,
)
from azents.runtime.coordination.data import (
    RuntimeCoordinationTarget,
    RuntimeOperationMetadata,
    RuntimeOperationStatus,
    RuntimeReplyEvent,
    RuntimeReplyEventType,
)
from azents.runtime.coordination.memory import (
    InMemoryRuntimeCoordinationStore,
)


class RecordingTtlStore(InMemoryRuntimeCoordinationStore):
    """In-memory store that records operation metadata TTLs for assertions."""

    def __init__(self) -> None:
        super().__init__()
        self.last_operation_ttl_seconds: int | None = None

    async def put_operation(
        self,
        metadata: RuntimeOperationMetadata,
        *,
        ttl_seconds: int | None,
    ) -> None:
        self.last_operation_ttl_seconds = ttl_seconds
        await super().put_operation(metadata, ttl_seconds=ttl_seconds)


@pytest.mark.asyncio
async def test_register_provider_and_runner_issue_independent_generations() -> None:
    """Provider and Runner generations are independently scoped."""
    store = InMemoryRuntimeCoordinationStore()
    service = RuntimeControlProtocolService(store)
    now = _now()

    provider = await service.register_provider(
        _provider_registration(), registered_at=now
    )
    runner = await service.register_runner(_runner_registration(), registered_at=now)

    assert provider.generation == 1
    assert provider.provider_id == "provider-1"
    assert runner.generation == 1
    assert runner.runtime_id == "runtime-1"
    assert (
        await service.heartbeat_provider(
            provider_id="provider-1",
            generation=provider.generation,
            heartbeat_at=now + timedelta(seconds=1),
        )
        is True
    )
    assert (
        await service.heartbeat_runner(
            runtime_id="runtime-1",
            generation=runner.generation,
            heartbeat_at=now + timedelta(seconds=1),
        )
        is True
    )


@pytest.mark.asyncio
async def test_dispatch_provider_command_uses_provider_generation_fence() -> None:
    """Provider commands route through provider-scoped streams and generation groups."""
    store = InMemoryRuntimeCoordinationStore()
    service = RuntimeControlProtocolService(store, request_id_factory=lambda: "req-1")
    now = _now()
    accepted = await service.register_provider(
        _provider_registration(),
        registered_at=now,
    )

    result = await service.dispatch_provider_command(
        RuntimeProviderCommand(
            provider_id="provider-1",
            provider_generation=accepted.generation,
            runtime_id="runtime-1",
            desired_generation=3,
            command_type=RuntimeProviderCommandType.START,
            reset_final_desired_state=None,
            payload={"reason": "user"},
            deadline_at=now + timedelta(seconds=30),
        ),
        created_at=now,
    )
    claimed = await service.claim_next_provider_request(
        provider_id="provider-1",
        generation=accepted.generation,
        consumer_id="control-a",
        block_ms=0,
    )

    assert isinstance(result, RuntimeDispatchResult)
    assert result.request_stream_id == "provider:provider-1:generation:1:requests"
    assert result.reply_stream_id == "provider:provider-1:generation:1:replies"
    assert claimed is not None
    assert claimed.cursor is not None
    assert claimed.stream_id == "provider:provider-1:generation:1:requests"
    assert claimed.consumer_group == "provider-1:generation:1"
    assert claimed.runtime_id == "runtime-1"
    assert claimed.target == RuntimeCoordinationTarget.PROVIDER
    assert claimed.payload["desired_generation"] == 3

    await service.ack_claimed_request(claimed)
    assert (
        await service.claim_next_provider_request(
            provider_id="provider-1",
            generation=accepted.generation,
            consumer_id="control-b",
            block_ms=0,
        )
        is None
    )


@pytest.mark.asyncio
async def test_claimed_runner_request_can_be_reclaimed_until_acked() -> None:
    """Unacked claimed requests can move to another consumer after idle timeout."""
    store = InMemoryRuntimeCoordinationStore()
    service = RuntimeControlProtocolService(
        store,
        request_id_factory=lambda: "req-2",
        request_reclaim_idle_seconds=0,
    )
    now = _now()
    runner = await service.register_runner(_runner_registration(), registered_at=now)
    result = await service.dispatch_runner_operation(
        RuntimeRunnerOperation(
            runtime_id="runtime-1",
            runner_generation=runner.generation,
            operation_type="bash",
            owner_session_id=None,
            payload={"command": "echo ok"},
            deadline_at=now + timedelta(seconds=30),
            body_stream_id=None,
        ),
        created_at=now,
    )

    first = await service.claim_next_runner_request(
        runtime_id="runtime-1",
        generation=runner.generation,
        consumer_id="runner-a",
        block_ms=0,
    )
    reclaimed = await service.claim_next_runner_request(
        runtime_id="runtime-1",
        generation=runner.generation,
        consumer_id="runner-b",
        block_ms=0,
    )

    assert isinstance(result, RuntimeDispatchResult)
    assert first is not None
    assert reclaimed is not None
    assert reclaimed.request_id == first.request_id
    assert reclaimed.cursor == first.cursor
    assert reclaimed.stream_id == first.stream_id
    assert reclaimed.consumer_group == first.consumer_group

    await service.ack_claimed_request(reclaimed)
    assert (
        await service.claim_next_runner_request(
            runtime_id="runtime-1",
            generation=runner.generation,
            consumer_id="runner-c",
            block_ms=0,
        )
        is None
    )


@pytest.mark.asyncio
async def test_provider_reconnect_skips_previous_generation_requests() -> None:
    """Provider request streams are generation-scoped to avoid replay after eviction."""
    store = InMemoryRuntimeCoordinationStore()
    service = RuntimeControlProtocolService(store, request_id_factory=lambda: "req-1")
    now = _now()
    first = await service.register_provider(_provider_registration(), registered_at=now)
    result = await service.dispatch_provider_command(
        RuntimeProviderCommand(
            provider_id="provider-1",
            provider_generation=first.generation,
            runtime_id="runtime-1",
            desired_generation=3,
            command_type=RuntimeProviderCommandType.START,
            reset_final_desired_state=None,
            payload={"reason": "user"},
            deadline_at=now + timedelta(seconds=30),
        ),
        created_at=now,
    )
    second = await service.register_provider(
        _provider_registration(),
        registered_at=now + timedelta(seconds=1),
    )

    claimed = await service.claim_next_provider_request(
        provider_id="provider-1",
        generation=second.generation,
        consumer_id="control-a",
        block_ms=0,
    )

    assert isinstance(result, RuntimeDispatchResult)
    assert first.generation == 1
    assert second.generation == 2
    assert claimed is None


@pytest.mark.asyncio
async def test_dispatch_runner_operation_supports_resume_after_reply_cursor() -> None:
    """Runner operation dispatch writes metadata and reply streams support resume."""
    store = InMemoryRuntimeCoordinationStore()
    service = RuntimeControlProtocolService(store, request_id_factory=lambda: "req-2")
    now = _now()
    runner = await service.register_runner(_runner_registration(), registered_at=now)

    result = await service.dispatch_runner_operation(
        RuntimeRunnerOperation(
            runtime_id="runtime-1",
            runner_generation=runner.generation,
            operation_type="bash",
            owner_session_id=None,
            payload={"command": "echo ok"},
            deadline_at=now + timedelta(seconds=30),
            body_stream_id=None,
        ),
        created_at=now,
    )
    assert isinstance(result, RuntimeDispatchResult)
    claimed = await service.claim_next_runner_request(
        runtime_id="runtime-1",
        generation=runner.generation,
        consumer_id="runner-a",
        block_ms=0,
    )
    assert claimed is not None
    assert claimed.operation_type == "bash"

    first = await service.append_reply_event(
        _reply("req-2", runner.generation, RuntimeReplyEventType.ACCEPTED),
        reply_stream_id=result.reply_stream_id,
        operation_id=result.operation_id,
        expected_target=RuntimeCoordinationTarget.RUNNER,
        expected_subject_id="runtime-1",
    )
    final = await service.append_reply_event(
        _reply(
            "req-2",
            runner.generation,
            RuntimeReplyEventType.FINAL_SUCCESS,
            final=True,
        ),
        reply_stream_id=result.reply_stream_id,
        operation_id=result.operation_id,
        expected_target=RuntimeCoordinationTarget.RUNNER,
        expected_subject_id="runtime-1",
    )
    resumed = await service.read_replies(
        reply_stream_id=result.reply_stream_id,
        after_cursor=first.cursor
        if isinstance(first, RuntimeReplyAppendResult)
        else None,
        limit=10,
    )

    assert isinstance(final, RuntimeReplyAppendResult)
    assert final.final is True
    assert [record.event.event_type for record in resumed] == [
        RuntimeReplyEventType.FINAL_SUCCESS
    ]
    metadata = await store.get_operation(result.operation_id)
    assert metadata is not None
    assert metadata.final_event_cursor == final.cursor


@pytest.mark.asyncio
async def test_runner_operations_share_generation_reply_stream() -> None:
    """Runner operation replies share a generation-scoped stream."""
    store = InMemoryRuntimeCoordinationStore()
    request_ids = iter(("req-1", "req-2"))
    service = RuntimeControlProtocolService(
        store,
        request_id_factory=lambda: next(request_ids),
    )
    now = _now()
    runner = await service.register_runner(_runner_registration(), registered_at=now)

    first = await service.dispatch_runner_operation(
        _runner_operation(generation=runner.generation, now=now),
        created_at=now,
    )
    second = await service.dispatch_runner_operation(
        _runner_operation(generation=runner.generation, now=now),
        created_at=now,
    )

    assert isinstance(first, RuntimeDispatchResult)
    assert isinstance(second, RuntimeDispatchResult)
    assert first.reply_stream_id == "runner:runtime-1:generation:1:replies"
    assert second.reply_stream_id == first.reply_stream_id


@pytest.mark.asyncio
async def test_runner_cancel_marks_metadata_and_appends_ordered_command() -> None:
    """Runner cancellation blocks new starts and follows the original request."""
    store = InMemoryRuntimeCoordinationStore()
    request_ids = iter(("req-operation", "req-cancel"))
    service = RuntimeControlProtocolService(
        store,
        request_id_factory=lambda: next(request_ids),
    )
    now = _now()
    cancel_requested_at = now + timedelta(seconds=1)
    runner = await service.register_runner(_runner_registration(), registered_at=now)
    operation = await service.dispatch_runner_operation(
        _runner_operation(generation=runner.generation, now=now),
        created_at=now,
    )
    assert isinstance(operation, RuntimeDispatchResult)

    cancellation = await service.request_runner_operation_cancel(
        runtime_id="runtime-1",
        runner_generation=runner.generation,
        operation_id=operation.operation_id,
        created_at=cancel_requested_at,
    )

    assert isinstance(cancellation, RuntimeDispatchResult)
    metadata = await store.get_operation(operation.operation_id)
    assert metadata is not None
    assert metadata.status is RuntimeOperationStatus.CANCEL_REQUESTED
    assert metadata.cancel_requested_at == cancel_requested_at
    assert (
        await store.try_start_operation(
            operation.operation_id,
            updated_at=cancel_requested_at + timedelta(seconds=1),
        )
        is None
    )
    first = await service.claim_next_runner_request(
        runtime_id="runtime-1",
        generation=runner.generation,
        consumer_id="runner-a",
        block_ms=0,
    )
    second = await service.claim_next_runner_request(
        runtime_id="runtime-1",
        generation=runner.generation,
        consumer_id="runner-a",
        block_ms=0,
    )
    assert first is not None
    assert first.request_id == "req-operation"
    assert second is not None
    assert second.request_id == "req-cancel"
    assert second.operation_type == "operation.cancel"
    assert second.payload == {"operation_id": operation.operation_id}


@pytest.mark.asyncio
async def test_runner_reconnect_does_not_replay_previous_generation_requests() -> None:
    """Runner request streams are generation-scoped to avoid replay after eviction."""
    store = InMemoryRuntimeCoordinationStore()
    service = RuntimeControlProtocolService(store, request_id_factory=lambda: "req-2")
    now = _now()
    first = await service.register_runner(_runner_registration(), registered_at=now)
    result = await service.dispatch_runner_operation(
        RuntimeRunnerOperation(
            runtime_id="runtime-1",
            runner_generation=first.generation,
            operation_type="bash",
            owner_session_id=None,
            payload={"command": "echo ok"},
            deadline_at=now + timedelta(seconds=30),
            body_stream_id=None,
        ),
        created_at=now,
    )
    second = await service.register_runner(
        _runner_registration(),
        registered_at=now + timedelta(seconds=1),
    )

    claimed = await service.claim_next_runner_request(
        runtime_id="runtime-1",
        generation=second.generation,
        consumer_id="runner-a",
        block_ms=0,
    )

    assert isinstance(result, RuntimeDispatchResult)
    assert first.generation == 1
    assert second.generation == 2
    assert claimed is None


@pytest.mark.asyncio
async def test_dispatch_rejects_missing_and_stale_runner_generation() -> None:
    """Control rejects missing or stale Runner generations."""
    store = InMemoryRuntimeCoordinationStore()
    service = RuntimeControlProtocolService(store)
    now = _now()

    missing = await service.dispatch_runner_operation(
        _runner_operation(generation=1, now=now),
        created_at=now,
    )
    runner = await service.register_runner(_runner_registration(), registered_at=now)
    stale = await service.dispatch_runner_operation(
        _runner_operation(generation=runner.generation - 1, now=now),
        created_at=now,
    )

    assert isinstance(missing, RuntimeProtocolRouteUnavailable)
    assert missing.subject_id == "runtime-1"
    assert isinstance(stale, RuntimeProtocolStaleGeneration)
    assert stale.generation == 0


@pytest.mark.asyncio
async def test_stale_reply_event_is_not_appended() -> None:
    """Reply events are fenced by current Runner generation."""
    store = InMemoryRuntimeCoordinationStore()
    service = RuntimeControlProtocolService(store)
    now = _now()
    runner = await service.register_runner(_runner_registration(), registered_at=now)

    result = await service.append_reply_event(
        _reply("req-1", runner.generation - 1, RuntimeReplyEventType.ACCEPTED),
        reply_stream_id="runner:runtime-1:generation:1:replies",
        operation_id=None,
        expected_target=RuntimeCoordinationTarget.RUNNER,
        expected_subject_id="runtime-1",
    )

    assert isinstance(result, RuntimeProtocolStaleGeneration)
    assert (
        await service.read_replies(
            reply_stream_id="runner:runtime-1:generation:1:replies",
            after_cursor=None,
            limit=10,
        )
        == []
    )


@pytest.mark.asyncio
async def test_operation_ttl_keeps_deadline_buffer() -> None:
    """Operation metadata remains available past short client deadlines."""
    store = RecordingTtlStore()
    request_ids = iter(("req-1", "req-2"))
    service = RuntimeControlProtocolService(
        store,
        request_id_factory=lambda: next(request_ids),
        operation_ttl_seconds=900,
    )
    created_at = _now()
    runner = await service.register_runner(
        _runner_registration(),
        registered_at=created_at,
    )

    await service.dispatch_runner_operation(
        RuntimeRunnerOperation(
            runtime_id="runtime-1",
            runner_generation=runner.generation,
            operation_type="bash",
            owner_session_id=None,
            payload={"command": "echo short"},
            deadline_at=created_at + timedelta(seconds=30),
            body_stream_id=None,
        ),
        created_at=created_at,
    )
    assert store.last_operation_ttl_seconds == 900

    await service.dispatch_runner_operation(
        RuntimeRunnerOperation(
            runtime_id="runtime-1",
            runner_generation=runner.generation,
            operation_type="bash",
            owner_session_id=None,
            payload={"command": "echo long"},
            deadline_at=created_at + timedelta(seconds=1200),
            body_stream_id=None,
        ),
        created_at=created_at,
    )
    assert store.last_operation_ttl_seconds == 1500


@pytest.mark.asyncio
async def test_late_final_reply_does_not_replace_canceled_cursor() -> None:
    """Canceled finals remain authoritative when a late Runner final arrives."""
    store = InMemoryRuntimeCoordinationStore()
    service = RuntimeControlProtocolService(
        store,
        request_id_factory=lambda: "req-late",
    )
    now = _now()
    runner = await service.register_runner(_runner_registration(), registered_at=now)
    result = await service.dispatch_runner_operation(
        RuntimeRunnerOperation(
            runtime_id="runtime-1",
            runner_generation=runner.generation,
            operation_type="bash",
            owner_session_id=None,
            payload={"command": "echo late"},
            deadline_at=now + timedelta(seconds=30),
            body_stream_id=None,
        ),
        created_at=now,
    )
    assert isinstance(result, RuntimeDispatchResult)

    canceled = await service.append_reply_event(
        _reply(
            "req-late",
            runner.generation,
            RuntimeReplyEventType.FINAL_ERROR,
            final=True,
        ),
        reply_stream_id=result.reply_stream_id,
        operation_id=result.operation_id,
        expected_target=RuntimeCoordinationTarget.RUNNER,
        expected_subject_id="runtime-1",
    )
    late = await service.append_reply_event(
        _reply(
            "req-late",
            runner.generation,
            RuntimeReplyEventType.FINAL_SUCCESS,
            final=True,
        ),
        reply_stream_id=result.reply_stream_id,
        operation_id=result.operation_id,
        expected_target=RuntimeCoordinationTarget.RUNNER,
        expected_subject_id="runtime-1",
    )

    assert isinstance(canceled, RuntimeReplyAppendResult)
    assert late is None
    metadata = await store.get_operation(result.operation_id)
    assert metadata is not None
    assert metadata.status is RuntimeOperationStatus.FINAL
    assert metadata.final_event_cursor == canceled.cursor
    replies = await service.read_replies(
        reply_stream_id=result.reply_stream_id,
        after_cursor=None,
        limit=10,
    )
    assert [record.event.event_type for record in replies] == [
        RuntimeReplyEventType.FINAL_ERROR
    ]


def _provider_registration() -> RuntimeProviderRegistration:
    return RuntimeProviderRegistration(
        provider_id="provider-1",
        provider_type="docker",
        scope="workspace",
        workspace_id="workspace-1",
        protocol_version="2026-05-25",
        capabilities=RuntimeProtocolCapabilities(("lifecycle",)),
        config_schema_version="v1",
        metadata={"region": "local"},
        auth_credential_id="credential-1",
        connection_id="provider-connection-1",
        owner_replica_id="control-a",
    )


def _runner_registration() -> RuntimeRunnerRegistration:
    return RuntimeRunnerRegistration(
        runtime_id="runtime-1",
        runner_id="runner-1",
        protocol_version="2026-05-25",
        capabilities=RuntimeProtocolCapabilities(("bash", "files")),
        health="ok",
        workspace_path="/workspace/agent",
        metadata={"image": "runner:v1"},
        auth_credential_id="credential-1",
        connection_id="runner-connection-1",
        owner_replica_id="control-a",
    )


def _runner_operation(*, generation: int, now: datetime) -> RuntimeRunnerOperation:
    return RuntimeRunnerOperation(
        runtime_id="runtime-1",
        runner_generation=generation,
        operation_type="bash",
        owner_session_id=None,
        payload={"command": "pwd"},
        deadline_at=now + timedelta(seconds=30),
        body_stream_id=None,
    )


def _reply(
    request_id: str,
    generation: int,
    event_type: RuntimeReplyEventType,
    *,
    final: bool = False,
) -> RuntimeReplyEvent:
    return RuntimeReplyEvent(
        request_id=request_id,
        runtime_id="runtime-1",
        generation=generation,
        event_type=event_type,
        payload={"ok": True},
        created_at=_now(),
        final=final,
    )


def _now() -> datetime:
    return datetime.now(timezone.utc)
