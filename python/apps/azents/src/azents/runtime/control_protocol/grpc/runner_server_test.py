"""Agent Runtime Runner Control gRPC server tests."""

# protobuf generated modules expose dynamic message attributes.

import asyncio
import dataclasses
import inspect
from collections.abc import AsyncGenerator, AsyncIterator
from datetime import UTC, datetime, timedelta

import pytest
from azents_runtime_control.grpc_runner_client import (
    runner_system_metrics_to_message,
)
from azents_runtime_control.proto import (
    runtime_configuration_pb2,
    runtime_runner_control_pb2,
    runtime_runner_transfer_pb2,
)
from azents_runtime_control.runner import RunnerStateReport
from azents_runtime_control.runner import RuntimeRunnerState as SharedRunnerState
from azents_runtime_control.runner_transfer import RunnerTransferResult
from azents_runtime_control.runtime_configuration import (
    RuntimeConfigurationEvidence,
)
from azents_runtime_control.system_metrics import (
    RUNNER_SYSTEM_METRICS_CAPABILITY,
    RUNNER_SYSTEM_METRICS_MAX_MESSAGE_BYTES,
    RunnerSystemMetricAvailability,
    RunnerSystemMetricObservation,
    RunnerSystemMetricsReport,
    RunnerSystemMetricsScope,
)
from google.protobuf import timestamp_pb2

from azents.core.runtime_runner_credential import (
    RuntimeRunnerCredential,
    RuntimeRunnerCredentialInvalid,
)
from azents.runtime.control_protocol.data import (
    RuntimeDispatchResult,
    RuntimeProtocolRouteUnavailable,
    RuntimeRunnerOperation,
    RuntimeRunnerRegistration,
)
from azents.runtime.control_protocol.grpc.runner_server import (
    RuntimeRunnerControlGrpcServicer,
    _runner_transfer_cancel,
    _runner_transfer_intent,
    _RunnerOutboundItem,
)
from azents.runtime.control_protocol.service import (
    RuntimeControlProtocolService,
)
from azents.runtime.coordination.data import (
    RuntimeBodyChunk,
    RuntimeConnectionKind,
    RuntimeCoordinationTarget,
    RuntimeOperationMetadata,
    RuntimeOperationStatus,
    RuntimeOperationTransferDirection,
    RuntimeReplyEvent,
    RuntimeReplyEventType,
    RuntimeRequestEnvelope,
)
from azents.runtime.coordination.memory import (
    InMemoryRuntimeCoordinationStore,
)
from azents.runtime.transfer.data import RuntimeTransferFailure
from azents.runtime.transfer.result_coordinator import RuntimeRunnerTransferResultSink
from azents.testing.grpc import FakeGrpcContext as BaseFakeGrpcContext


async def _close_stream[MessageT](stream: AsyncIterator[MessageT]) -> None:
    """Close the concrete async generator returned by the test subject."""
    assert isinstance(stream, AsyncGenerator)
    await stream.aclose()


@dataclasses.dataclass
class FakeStateSink:
    """Collect Runner state reports delivered by the gRPC bridge."""

    reports: list[RunnerStateReport] = dataclasses.field(default_factory=list)
    registrations: list[RuntimeRunnerRegistration] = dataclasses.field(
        default_factory=list
    )
    registration_valid: bool = True
    heartbeat_configuration: RuntimeConfigurationEvidence | None = None

    async def record_runner_state(self, report: RunnerStateReport) -> None:
        """Record one Runner state report."""
        self.reports.append(report)

    async def validate_runner_registration(
        self,
        registration: RuntimeRunnerRegistration,
    ) -> bool:
        """Record and validate Runner configuration evidence."""
        self.registrations.append(registration)
        return self.registration_valid

    async def configuration_evidence_for_runner_heartbeat(
        self,
        *,
        runtime_id: str,
    ) -> RuntimeConfigurationEvidence | None:
        """Return configured heartbeat evidence for the registered Runtime."""
        del runtime_id
        return self.heartbeat_configuration


@dataclasses.dataclass
class RecordingTransferResultSink(RuntimeRunnerTransferResultSink):
    """Record structurally valid transfer results delegated by the bridge."""

    calls: list[tuple[RunnerTransferResult, str]] = dataclasses.field(
        default_factory=list
    )
    failure_calls: list[
        tuple[RuntimeOperationMetadata, str, str, RuntimeTransferFailure]
    ] = dataclasses.field(default_factory=list)

    async def handle(
        self,
        result: RunnerTransferResult,
        *,
        request_id: str,
    ) -> None:
        """Record one sink invocation."""
        self.calls.append((result, request_id))

    async def handle_failure(
        self,
        operation: RuntimeOperationMetadata,
        *,
        request_id: str,
        error_code: str,
        failure: RuntimeTransferFailure,
    ) -> None:
        """Record one unusable-result settlement invocation."""
        self.failure_calls.append((operation, request_id, error_code, failure))


def test_transfer_cancel_envelope_maps_to_typed_runner_message() -> None:
    """Bounded cancellation metadata maps without body or storage authority."""
    cancellation = _runner_transfer_cancel(
        RuntimeRequestEnvelope(
            request_id="cancel-1",
            runtime_id="runtime-1",
            target=RuntimeCoordinationTarget.RUNNER,
            generation=2,
            operation_type="file.transfer.cancel.v1",
            payload={
                "transfer_id": "transfer-1",
                "attempt_id": "attempt-1",
                "runtime_id": "runtime-1",
                "runner_generation": 2,
                "operation_id": "operation-1",
                "dispatch_id": "dispatch-1",
                "reason": "caller",
            },
            reply_stream_id="reply-1",
            deadline_at=datetime.now(UTC) + timedelta(minutes=1),
            body_stream_id=None,
        )
    )

    assert cancellation.identity.runner_generation == 2
    assert cancellation.operation_id == "operation-1"
    assert cancellation.dispatch_id == "dispatch-1"
    assert (
        cancellation.reason
        == runtime_runner_control_pb2.RUNNER_TRANSFER_CANCEL_REASON_CALLER
    )


@pytest.mark.asyncio
async def test_transfer_result_delegates_only_valid_structural_result() -> None:
    """Valid results use the sink; malformed results become protocol final errors."""
    store = InMemoryRuntimeCoordinationStore()
    now = datetime.now(UTC)
    await store.register_connection(
        kind=RuntimeConnectionKind.RUNNER,
        subject_id="runtime-1",
        connection_id="connection-1",
        owner_replica_id="control-a",
        connected_at=now,
        heartbeat_at=now,
        ttl_seconds=60,
        metadata={},
    )
    await store.put_operation(
        RuntimeOperationMetadata(
            operation_id="operation-1",
            runtime_id="runtime-1",
            target=RuntimeCoordinationTarget.RUNNER,
            generation=1,
            operation_type="file.transfer.v1",
            transfer_id="transfer-1",
            transfer_attempt_id="attempt-1",
            transfer_dispatch_id="dispatch-1",
            transfer_direction=RuntimeOperationTransferDirection.DOWNLOAD,
            request_stream_id="request-1",
            reply_stream_id="reply-1",
            status=RuntimeOperationStatus.ACTIVE,
            created_at=now,
            updated_at=now,
            deadline_at=now + timedelta(minutes=1),
            body_stream_id=None,
            last_heartbeat_at=None,
            last_event_at=None,
            cancel_requested_at=None,
            final_event_cursor=None,
        ),
        ttl_seconds=60,
    )
    control = RuntimeControlProtocolService(store)
    sink = RecordingTransferResultSink()
    servicer = RuntimeRunnerControlGrpcServicer(
        control_protocol=control,
        coordination_store=store,
        state_sink=FakeStateSink(),
        owner_replica_id="control-a",
        consumer_id="consumer-1",
        runner_authenticator=FakeRunnerAuthenticator(),
        transfer_result_sink=sink,
    )

    await servicer._append_transfer_result(  # Test the bounded bridge path directly.
        _transfer_result_message(committed=True)
    )

    assert len(sink.calls) == 1
    assert (
        await control.read_replies(
            reply_stream_id="reply-1",
            after_cursor=None,
            limit=10,
        )
        == []
    )

    await servicer._append_transfer_result(  # Test the bounded bridge path directly.
        _transfer_result_message(committed=False)
    )

    assert len(sink.calls) == 1
    assert len(sink.failure_calls) == 1
    operation, request_id, error_code, failure = sink.failure_calls[0]
    assert operation.operation_id == "operation-1"
    assert request_id == "result:False"
    assert error_code == "RUNNER_TRANSFER_PROTOCOL_VIOLATION"
    assert failure is RuntimeTransferFailure.FENCED


@pytest.mark.asyncio
async def test_transfer_result_rejects_unbounded_identity_before_store_lookup() -> None:
    """Untrusted identifiers are bounded before they can construct Redis keys."""

    class _NoLookupStore(InMemoryRuntimeCoordinationStore):
        async def get_operation(self, operation_id: str) -> RuntimeOperationMetadata:
            del operation_id
            raise AssertionError("store lookup must not run")

    sink = RecordingTransferResultSink()
    store = _NoLookupStore()
    servicer = RuntimeRunnerControlGrpcServicer(
        control_protocol=RuntimeControlProtocolService(store),
        coordination_store=store,
        state_sink=FakeStateSink(),
        owner_replica_id="control-a",
        consumer_id="consumer-1",
        runner_authenticator=FakeRunnerAuthenticator(),
        transfer_result_sink=sink,
    )
    message = _transfer_result_message(committed=True)
    message.transfer_result.operation_id = "o" * 129

    await servicer._append_transfer_result(message)

    assert sink.calls == []
    assert sink.failure_calls == []


def _transfer_result_message(
    *,
    committed: bool,
) -> runtime_runner_control_pb2.RunnerMessage:
    """Build one bounded Runner transfer result message."""
    result = runtime_runner_control_pb2.RunnerTransferResult(
        identity=runtime_runner_transfer_pb2.TransferIdentity(
            transfer_id="transfer-1",
            attempt_id="attempt-1",
            runtime_id="runtime-1",
            runner_generation=1,
        ),
        operation_id="operation-1",
        dispatch_id="dispatch-1",
        outcome=runtime_runner_control_pb2.RUNNER_TRANSFER_OUTCOME_SUCCEEDED,
        actual_size=3,
        sha256="a" * 64,
        destination_committed=committed,
    )
    return runtime_runner_control_pb2.RunnerMessage(
        request_id=f"result:{committed}",
        generation=1,
        transfer_result=result,
    )


class QueueIterator:
    """Async iterator backed by a queue."""

    def __init__(self) -> None:
        self._queue: asyncio.Queue[runtime_runner_control_pb2.RunnerMessage | None] = (
            asyncio.Queue()
        )

    async def put(
        self,
        message: runtime_runner_control_pb2.RunnerMessage | None,
    ) -> None:
        """Append an inbound message."""
        await self._queue.put(message)

    def __aiter__(self) -> "QueueIterator":
        """Return self."""
        return self

    async def __anext__(self) -> runtime_runner_control_pb2.RunnerMessage:
        """Return the next queued message."""
        message = await self._queue.get()
        if message is None:
            raise StopAsyncIteration
        return message


class FakeGrpcContext(
    BaseFakeGrpcContext[
        runtime_runner_control_pb2.RunnerMessage,
        runtime_runner_control_pb2.RunnerControlMessage,
    ]
):
    """Minimal gRPC context for tests."""

    def __init__(
        self,
        metadata: tuple[tuple[str, str], ...] = (
            ("authorization", "Bearer runner-token"),
        ),
    ) -> None:
        super().__init__(metadata=metadata)


@dataclasses.dataclass
class FakeRunnerAuthenticator:
    """Authenticate one deterministic Runtime-bound test credential."""

    token: str = "runner-token"
    credential: RuntimeRunnerCredential = RuntimeRunnerCredential(
        credential_id="credential-1",
        runtime_id="runtime-1",
        desired_generation=1,
    )
    authorized: bool = True

    async def authenticate_runner(
        self,
        secret: str,
    ) -> RuntimeRunnerCredential:
        """Return authenticated claims for the configured test token."""
        if secret != self.token:
            raise RuntimeRunnerCredentialInvalid("invalid test credential")
        return self.credential

    async def authorize_runner(
        self,
        credential: RuntimeRunnerCredential,
    ) -> bool:
        """Return current durable authority for the configured claims."""
        return self.authorized and credential == self.credential


class CountingRelayControlProtocol(RuntimeControlProtocolService):
    """Return queued envelopes while recording durable claims."""

    def __init__(self, envelopes: list[RuntimeRequestEnvelope]) -> None:
        super().__init__(InMemoryRuntimeCoordinationStore())
        self.envelopes = envelopes
        self.claim_count = 0
        self.acked: list[RuntimeRequestEnvelope] = []

    async def claim_next_runner_request(
        self,
        *,
        runtime_id: str,
        generation: int,
        consumer_id: str,
        block_ms: int,
    ) -> RuntimeRequestEnvelope | None:
        """Return one envelope for each claim."""
        del runtime_id, generation, consumer_id, block_ms
        self.claim_count += 1
        if not self.envelopes:
            await asyncio.sleep(3600)
            return None
        return self.envelopes.pop(0)

    async def ack_claimed_request(self, envelope: RuntimeRequestEnvelope) -> None:
        """Record an identical duplicate acknowledgement."""
        self.acked.append(envelope)


@pytest.mark.asyncio
async def test_runner_grpc_registers_and_acks_heartbeat() -> None:
    store = InMemoryRuntimeCoordinationStore()
    sink = FakeStateSink(
        heartbeat_configuration=RuntimeConfigurationEvidence(
            configuration_sequence=2,
            digest="e" * 64,
            desired_generation=1,
        )
    )
    servicer = _servicer(RuntimeControlProtocolService(store), store, sink)
    inbound = QueueIterator()
    await inbound.put(_register_message())
    await inbound.put(
        runtime_runner_control_pb2.RunnerMessage(
            connection_id="connection-1",
            request_id="heartbeat-1",
            generation=1,
            heartbeat=runtime_runner_control_pb2.RunnerHeartbeat(
                monotonic_sequence=7,
            ),
        )
    )
    await inbound.put(None)

    stream = servicer.ConnectRunner(inbound, FakeGrpcContext())
    accepted = await anext(stream)
    heartbeat_ack = await anext(stream)
    await _close_stream(stream)

    assert accepted.register_accepted.runtime_id == "runtime-1"
    assert accepted.register_accepted.generation == 1
    assert heartbeat_ack.heartbeat_ack.monotonic_sequence == 7
    assert (
        heartbeat_ack.heartbeat_ack.runtime_configuration.configuration_sequence == "2"
    )
    assert heartbeat_ack.heartbeat_ack.runtime_configuration.digest == "e" * 64
    assert heartbeat_ack.heartbeat_ack.runtime_configuration.desired_generation == 1
    assert sink.reports[-1].runner_state is SharedRunnerState.UNKNOWN
    assert sink.reports[-1].diagnostic["reason"] == "runner_stream_closed"
    assert sink.registrations[0].runtime_configuration.configuration_sequence == 1


@pytest.mark.asyncio
async def test_runner_grpc_accepts_exact_limit_metrics_and_rejects_oversize() -> None:
    """The 4 KiB boundary is accepted while a larger report is dropped."""
    store = InMemoryRuntimeCoordinationStore()
    service = RuntimeControlProtocolService(store)
    servicer = _servicer(service, store, FakeStateSink())
    inbound = QueueIterator()
    await inbound.put(_metrics_register_message())
    await inbound.put(
        runtime_runner_control_pb2.RunnerMessage(
            connection_id="connection-1",
            request_id="metrics-limit",
            generation=1,
            system_metrics=_sized_system_metrics_message(
                RUNNER_SYSTEM_METRICS_MAX_MESSAGE_BYTES,
                sequence=1,
            ),
        )
    )
    await inbound.put(
        runtime_runner_control_pb2.RunnerMessage(
            connection_id="connection-1",
            request_id="metrics-oversize",
            generation=1,
            system_metrics=_sized_system_metrics_message(
                RUNNER_SYSTEM_METRICS_MAX_MESSAGE_BYTES + 1,
                sequence=2,
            ),
        )
    )
    await inbound.put(
        runtime_runner_control_pb2.RunnerMessage(
            connection_id="connection-1",
            request_id="heartbeat-after-metrics",
            generation=1,
            heartbeat=runtime_runner_control_pb2.RunnerHeartbeat(
                monotonic_sequence=1,
            ),
        )
    )

    stream = servicer.ConnectRunner(inbound, FakeGrpcContext())
    accepted = await anext(stream)
    heartbeat_ack = await anext(stream)
    series = await store.read_runner_system_metrics(
        runtime_id="runtime-1",
        generation=accepted.register_accepted.generation,
        current_time=datetime.now(UTC),
    )
    await _close_stream(stream)

    assert heartbeat_ack.request_id == "heartbeat-after-metrics"
    assert [sample.sequence for sample in series] == [1]


@pytest.mark.asyncio
async def test_runner_grpc_drops_invalid_and_incapable_metrics_without_closing() -> (
    None
):
    """Invalid and capability-mismatched reports do not affect heartbeats."""
    store = InMemoryRuntimeCoordinationStore()
    service = RuntimeControlProtocolService(store)
    servicer = _servicer(service, store, FakeStateSink())
    inbound = QueueIterator()
    await inbound.put(_register_message())
    await inbound.put(
        runtime_runner_control_pb2.RunnerMessage(
            connection_id="connection-1",
            request_id="metrics-invalid",
            generation=1,
            system_metrics=runtime_runner_control_pb2.RunnerSystemMetrics(
                runtime_id="runtime-1",
                sequence=0,
            ),
        )
    )
    await inbound.put(
        runtime_runner_control_pb2.RunnerMessage(
            connection_id="connection-1",
            request_id="metrics-incapable",
            generation=1,
            system_metrics=runner_system_metrics_to_message(
                _system_metrics_report(sequence=1)
            ),
        )
    )
    await inbound.put(
        runtime_runner_control_pb2.RunnerMessage(
            connection_id="connection-1",
            request_id="heartbeat-after-rejections",
            generation=1,
            heartbeat=runtime_runner_control_pb2.RunnerHeartbeat(
                monotonic_sequence=2,
            ),
        )
    )

    stream = servicer.ConnectRunner(inbound, FakeGrpcContext())
    accepted = await anext(stream)
    heartbeat_ack = await anext(stream)
    series = await store.read_runner_system_metrics(
        runtime_id="runtime-1",
        generation=accepted.register_accepted.generation,
        current_time=datetime.now(UTC),
    )
    await _close_stream(stream)

    assert heartbeat_ack.request_id == "heartbeat-after-rejections"
    assert series == []


@pytest.mark.asyncio
async def test_runner_grpc_drops_stale_and_wrong_runtime_metrics_without_closing() -> (
    None
):
    """Generation and Runtime identity fencing are metrics-local failures."""
    store = InMemoryRuntimeCoordinationStore()
    service = RuntimeControlProtocolService(store)
    servicer = _servicer(service, store, FakeStateSink())
    inbound = QueueIterator()
    await inbound.put(_metrics_register_message())
    await inbound.put(
        runtime_runner_control_pb2.RunnerMessage(
            connection_id="connection-1",
            request_id="metrics-stale",
            generation=2,
            system_metrics=runner_system_metrics_to_message(
                _system_metrics_report(sequence=1)
            ),
        )
    )
    wrong_runtime = runner_system_metrics_to_message(_system_metrics_report(sequence=2))
    wrong_runtime.runtime_id = "runtime-2"
    await inbound.put(
        runtime_runner_control_pb2.RunnerMessage(
            connection_id="connection-1",
            request_id="metrics-wrong-runtime",
            generation=1,
            system_metrics=wrong_runtime,
        )
    )
    await inbound.put(
        runtime_runner_control_pb2.RunnerMessage(
            connection_id="connection-1",
            request_id="heartbeat-after-fencing",
            generation=1,
            heartbeat=runtime_runner_control_pb2.RunnerHeartbeat(
                monotonic_sequence=3,
            ),
        )
    )

    stream = servicer.ConnectRunner(inbound, FakeGrpcContext())
    accepted = await anext(stream)
    heartbeat_ack = await anext(stream)
    series = await store.read_runner_system_metrics(
        runtime_id="runtime-1",
        generation=accepted.register_accepted.generation,
        current_time=datetime.now(UTC),
    )
    await _close_stream(stream)

    assert heartbeat_ack.request_id == "heartbeat-after-fencing"
    assert series == []


@pytest.mark.asyncio
async def test_runner_grpc_isolates_metrics_store_failure_from_heartbeat() -> None:
    """A metrics append exception drops only that sample."""

    class _FailingMetricsStore(InMemoryRuntimeCoordinationStore):
        async def append_runner_system_metrics(self, **kwargs: object) -> bool:
            del kwargs
            raise RuntimeError("metrics store unavailable")

    store = _FailingMetricsStore()
    service = RuntimeControlProtocolService(store)
    servicer = RuntimeRunnerControlGrpcServicer(
        control_protocol=service,
        coordination_store=store,
        state_sink=FakeStateSink(),
        owner_replica_id="control-a",
        consumer_id="runner-consumer-a",
        runner_authenticator=FakeRunnerAuthenticator(),
        transfer_result_sink=RecordingTransferResultSink(),
        operation_block_ms=1,
    )
    inbound = QueueIterator()
    await inbound.put(_metrics_register_message())
    await inbound.put(
        runtime_runner_control_pb2.RunnerMessage(
            connection_id="connection-1",
            request_id="metrics-store-failure",
            generation=1,
            system_metrics=runner_system_metrics_to_message(
                _system_metrics_report(sequence=1)
            ),
        )
    )
    await inbound.put(
        runtime_runner_control_pb2.RunnerMessage(
            connection_id="connection-1",
            request_id="heartbeat-after-store-failure",
            generation=1,
            heartbeat=runtime_runner_control_pb2.RunnerHeartbeat(
                monotonic_sequence=4,
            ),
        )
    )

    stream = servicer.ConnectRunner(inbound, FakeGrpcContext())
    await anext(stream)
    heartbeat_ack = await anext(stream)
    await _close_stream(stream)

    assert heartbeat_ack.request_id == "heartbeat-after-store-failure"


@pytest.mark.asyncio
async def test_runner_grpc_rejects_registration_policy_mismatch() -> None:
    """A Runner stream is rejected before registration when evidence is stale."""
    store = InMemoryRuntimeCoordinationStore()
    sink = FakeStateSink(registration_valid=False)
    servicer = _servicer(RuntimeControlProtocolService(store), store, sink)
    inbound = QueueIterator()
    await inbound.put(_register_message())

    stream = servicer.ConnectRunner(inbound, FakeGrpcContext())

    with pytest.raises(RuntimeError, match="FAILED_PRECONDITION"):
        await anext(stream)
    assert sink.registrations[0].runtime_configuration.configuration_sequence == 1
    assert sink.reports == []


@pytest.mark.asyncio
async def test_runner_grpc_revoke_current_connection_on_close() -> None:
    """Closing the current Runner stream removes it from operation routing."""
    store = InMemoryRuntimeCoordinationStore()
    service = RuntimeControlProtocolService(store)
    sink = FakeStateSink()
    servicer = _servicer(service, store, sink)
    inbound = QueueIterator()
    await inbound.put(_register_message())

    stream = servicer.ConnectRunner(inbound, FakeGrpcContext())
    accepted = await anext(stream)
    await _close_stream(stream)

    result = await service.dispatch_runner_operation(
        RuntimeRunnerOperation(
            runtime_id="runtime-1",
            runner_generation=accepted.register_accepted.generation,
            operation_type="process.start",
            owner_session_id="session-1",
            payload={"command": "echo ok"},
            deadline_at=datetime.now(UTC) + timedelta(seconds=30),
            body_stream_id=None,
        ),
        created_at=datetime.now(UTC),
    )

    assert isinstance(result, RuntimeProtocolRouteUnavailable)
    assert sink.reports[-1].diagnostic["reason"] == "runner_stream_closed"


@pytest.mark.asyncio
async def test_runner_grpc_ignores_stale_stream_close_after_reconnect() -> None:
    """Old Runner stream closure must not overwrite newer generation state."""
    store = InMemoryRuntimeCoordinationStore()
    service = RuntimeControlProtocolService(store)
    sink = FakeStateSink()
    servicer = _servicer(service, store, sink)
    old_inbound = QueueIterator()
    await old_inbound.put(_register_message("connection-1"))
    old_stream = servicer.ConnectRunner(old_inbound, FakeGrpcContext())
    old_accepted = await anext(old_stream)
    new_inbound = QueueIterator()
    await new_inbound.put(_register_message("connection-2"))
    new_stream = servicer.ConnectRunner(new_inbound, FakeGrpcContext())
    new_accepted = await anext(new_stream)

    await _close_stream(old_stream)

    assert old_accepted.register_accepted.generation == 1
    assert new_accepted.register_accepted.generation == 2
    assert sink.reports == []

    await _close_stream(new_stream)
    assert sink.reports[-1].runner_generation == 2
    assert sink.reports[-1].diagnostic["connection_id"] == "connection-2"


@pytest.mark.asyncio
async def test_runner_grpc_rejects_stream_generation_mismatch() -> None:
    store = InMemoryRuntimeCoordinationStore()
    sink = FakeStateSink()
    servicer = _servicer(RuntimeControlProtocolService(store), store, sink)
    inbound = QueueIterator()
    await inbound.put(_register_message())
    await inbound.put(
        runtime_runner_control_pb2.RunnerMessage(
            connection_id="connection-1",
            request_id="state-1",
            generation=2,
            state_report=_state_report_message(),
        )
    )

    stream = servicer.ConnectRunner(inbound, FakeGrpcContext())
    accepted = await anext(stream)
    error = await anext(stream)
    await _close_stream(stream)

    assert accepted.register_accepted.generation == 1
    assert error.error.code == "STALE_RUNNER_GENERATION"
    assert all(
        report.runner_state is not SharedRunnerState.READY for report in sink.reports
    )


@pytest.mark.asyncio
async def test_runner_grpc_rejects_state_report_after_newer_registration() -> None:
    store = InMemoryRuntimeCoordinationStore()
    service = RuntimeControlProtocolService(store)
    sink = FakeStateSink()
    servicer = _servicer(service, store, sink)
    old_inbound = QueueIterator()
    await old_inbound.put(_register_message("connection-1"))
    old_stream = servicer.ConnectRunner(old_inbound, FakeGrpcContext())
    old_accepted = await anext(old_stream)
    new_inbound = QueueIterator()
    await new_inbound.put(_register_message("connection-2"))
    new_stream = servicer.ConnectRunner(new_inbound, FakeGrpcContext())
    new_accepted = await anext(new_stream)
    await old_inbound.put(
        runtime_runner_control_pb2.RunnerMessage(
            connection_id="connection-1",
            request_id="state-1",
            generation=old_accepted.register_accepted.generation,
            state_report=_state_report_message(),
        )
    )

    error = await anext(old_stream)
    await _close_stream(old_stream)
    await _close_stream(new_stream)

    assert old_accepted.register_accepted.generation == 1
    assert new_accepted.register_accepted.generation == 2
    assert error.error.code == "STALE_RUNNER_GENERATION"
    assert all(
        report.runner_state is not SharedRunnerState.READY for report in sink.reports
    )


@pytest.mark.asyncio
async def test_runner_grpc_rejects_state_report_generation_mismatch() -> None:
    store = InMemoryRuntimeCoordinationStore()
    sink = FakeStateSink()
    servicer = _servicer(RuntimeControlProtocolService(store), store, sink)
    inbound = QueueIterator()
    await inbound.put(_register_message())
    state_report = _state_report_message()
    state_report.runner_generation = 2
    await inbound.put(
        runtime_runner_control_pb2.RunnerMessage(
            connection_id="connection-1",
            request_id="state-1",
            generation=1,
            state_report=state_report,
        )
    )

    stream = servicer.ConnectRunner(inbound, FakeGrpcContext())
    accepted = await anext(stream)
    error = await anext(stream)
    await _close_stream(stream)

    assert accepted.register_accepted.generation == 1
    assert error.error.code == "STALE_RUNNER_GENERATION"
    assert all(
        report.runner_state is not SharedRunnerState.READY for report in sink.reports
    )


@pytest.mark.asyncio
async def test_runner_grpc_relays_operations_and_appends_events() -> None:
    store = InMemoryRuntimeCoordinationStore()
    service = RuntimeControlProtocolService(store, request_id_factory=lambda: "req-1")
    sink = FakeStateSink()
    servicer = _servicer(service, store, sink)
    inbound = QueueIterator()
    await inbound.put(_register_message())

    stream = servicer.ConnectRunner(inbound, FakeGrpcContext())
    accepted = await anext(stream)
    result = await service.dispatch_runner_operation(
        RuntimeRunnerOperation(
            runtime_id="runtime-1",
            runner_generation=accepted.register_accepted.generation,
            operation_type="process.start",
            owner_session_id="session-1",
            payload={
                "command": "python -m http.server",
                "workdir": "/workspace/agent",
                "yield_time_ms": 1000,
                "max_output_bytes": 4096,
                "env": {"PYTHONUNBUFFERED": "1"},
            },
            deadline_at=datetime.now(UTC) + timedelta(seconds=30),
            body_stream_id=None,
        ),
        created_at=_now(),
    )

    command = await anext(stream)
    assert isinstance(result, RuntimeDispatchResult)
    assert command.operation_request.runtime_id == "runtime-1"
    assert command.operation_request.operation_type == "process.start"
    assert command.operation_request.owner_session_id == "session-1"
    assert command.operation_request.HasField("owner_session_id")
    assert command.operation_request.WhichOneof("payload") == "process_start"
    assert command.operation_request.process_start.command == "python -m http.server"
    assert command.operation_request.process_start.workdir == "/workspace/agent"
    assert command.operation_request.process_start.yield_time_ms == 1000
    assert command.operation_request.process_start.max_output_bytes == 4096
    assert command.operation_request.process_start.env == {"PYTHONUNBUFFERED": "1"}

    await inbound.put(
        runtime_runner_control_pb2.RunnerMessage(
            connection_id="connection-1",
            request_id="start:req-1",
            generation=accepted.register_accepted.generation,
            operation_start=runtime_runner_control_pb2.RunnerOperationStart(
                runtime_id="runtime-1",
                operation_id="operation:req-1",
            ),
        )
    )
    start_ack = await anext(stream)
    assert start_ack.operation_start_ack.allowed

    await inbound.put(
        runtime_runner_control_pb2.RunnerMessage(
            connection_id="connection-1",
            request_id="req-1",
            generation=accepted.register_accepted.generation,
            operation_event=runtime_runner_control_pb2.RunnerOperationEvent(
                runtime_id="runtime-1",
                operation_id="operation:req-1",
                generation=accepted.register_accepted.generation,
                event_type="process_output",
                created_at=_timestamp(_now()),
                final=False,
                process_output=runtime_runner_control_pb2.RunnerProcessOutputPayload(
                    process_id="proc_123",
                    stream="stdout",
                    chunk_id=1,
                    text="Serving HTTP",
                    truncated=False,
                    omitted_bytes=0,
                ),
            ),
        )
    )
    await asyncio.sleep(0)
    replies = await service.read_replies(
        reply_stream_id=result.reply_stream_id,
        after_cursor=None,
        limit=10,
    )

    assert replies[0].event.event_type is RuntimeReplyEventType.PROCESS_OUTPUT
    assert replies[0].event.payload["process_id"] == "proc_123"
    assert replies[0].event.payload["text"] == "Serving HTTP"
    await _close_stream(stream)


@pytest.mark.asyncio
async def test_runner_grpc_expires_operation_before_relay() -> None:
    """Expired Runner operations are finalized and acked without relaying."""
    store = InMemoryRuntimeCoordinationStore()
    service = RuntimeControlProtocolService(store, request_id_factory=lambda: "req-1")
    sink = FakeStateSink()
    servicer = _servicer(service, store, sink)
    inbound = QueueIterator()
    await inbound.put(_register_message())

    stream = servicer.ConnectRunner(inbound, FakeGrpcContext())
    accepted = await anext(stream)
    result = await service.dispatch_runner_operation(
        RuntimeRunnerOperation(
            runtime_id="runtime-1",
            runner_generation=accepted.register_accepted.generation,
            operation_type="process.start",
            owner_session_id="session-1",
            payload={
                "command": "python -m http.server",
                "workdir": "/workspace/agent",
                "yield_time_ms": 1000,
                "max_output_bytes": 4096,
            },
            deadline_at=_now() - timedelta(seconds=1),
            body_stream_id=None,
        ),
        created_at=_now() - timedelta(seconds=2),
    )

    assert isinstance(result, RuntimeDispatchResult)
    replies = []
    for _ in range(10):
        replies = await service.read_replies(
            reply_stream_id=result.reply_stream_id,
            after_cursor=None,
            limit=10,
        )
        if replies:
            break
        await asyncio.sleep(0.01)

    assert len(replies) == 1
    assert replies[0].event.event_type is RuntimeReplyEventType.FINAL_ERROR
    assert replies[0].event.payload["error_code"] == "RUNNER_OPERATION_EXPIRED"
    assert (
        await service.claim_next_runner_request(
            runtime_id="runtime-1",
            generation=accepted.register_accepted.generation,
            consumer_id="runner-b",
            block_ms=0,
        )
        is None
    )
    await _close_stream(stream)


@pytest.mark.asyncio
async def test_runner_grpc_rejects_start_for_canceled_operation() -> None:
    store = InMemoryRuntimeCoordinationStore()
    service = RuntimeControlProtocolService(store, request_id_factory=lambda: "req-1")
    servicer = _servicer(service, store, FakeStateSink())
    inbound = QueueIterator()
    await inbound.put(_register_message())

    stream = servicer.ConnectRunner(inbound, FakeGrpcContext())
    accepted = await anext(stream)
    result = await service.dispatch_runner_operation(
        RuntimeRunnerOperation(
            runtime_id="runtime-1",
            runner_generation=accepted.register_accepted.generation,
            operation_type="file.stat",
            owner_session_id="session-1",
            payload={"path": "/workspace/agent"},
            deadline_at=datetime.now(UTC) + timedelta(seconds=30),
            body_stream_id=None,
        ),
        created_at=_now(),
    )
    assert isinstance(result, RuntimeDispatchResult)
    await anext(stream)
    await store.update_operation_status(
        result.operation_id,
        status=RuntimeOperationStatus.FINAL,
        updated_at=_now(),
        final_event_cursor="1-0",
    )

    await inbound.put(
        runtime_runner_control_pb2.RunnerMessage(
            connection_id="connection-1",
            request_id="start:req-1",
            generation=accepted.register_accepted.generation,
            operation_start=runtime_runner_control_pb2.RunnerOperationStart(
                runtime_id="runtime-1",
                operation_id=result.operation_id,
            ),
        )
    )

    start_ack = await anext(stream)
    assert not start_ack.operation_start_ack.allowed
    await _close_stream(stream)


@pytest.mark.asyncio
async def test_runner_operation_relay_backpressures_durable_claims() -> None:
    envelopes = [
        RuntimeRequestEnvelope(
            request_id=f"req-{index}",
            runtime_id="runtime-1",
            target=RuntimeCoordinationTarget.RUNNER,
            generation=1,
            operation_type="file.stat",
            payload={"payload": {"path": "/workspace/agent"}},
            reply_stream_id="reply-1",
            deadline_at=datetime.now(UTC) + timedelta(seconds=30),
            body_stream_id=None,
        )
        for index in range(3)
    ]
    control = CountingRelayControlProtocol(envelopes)
    store = InMemoryRuntimeCoordinationStore()
    servicer = RuntimeRunnerControlGrpcServicer(
        control_protocol=control,
        coordination_store=store,
        state_sink=FakeStateSink(),
        owner_replica_id="control-a",
        consumer_id="runner-consumer-a",
        operation_block_ms=1,
        runner_authenticator=FakeRunnerAuthenticator(),
        transfer_result_sink=RecordingTransferResultSink(),
    )
    outbound: asyncio.Queue[
        runtime_runner_control_pb2.RunnerControlMessage | _RunnerOutboundItem
    ] = asyncio.Queue(maxsize=1)

    task = asyncio.create_task(
        servicer._relay_runner_operations(  # Exercise relay backpressure directly.
            outbound,
            authentication=RuntimeRunnerCredential(
                credential_id="credential-1",
                runtime_id="runtime-1",
                desired_generation=1,
            ),
            runtime_id="runtime-1",
            generation=1,
            active_transfer_dispatches={},
        )
    )
    for _ in range(100):
        if control.claim_count >= 2:
            break
        await asyncio.sleep(0.01)

    assert outbound.qsize() == 1
    assert control.claim_count == 2
    assert len(control.envelopes) == 1
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task


@pytest.mark.asyncio
async def test_runner_operation_relay_checks_authority_before_claim() -> None:
    control = CountingRelayControlProtocol([])
    authenticator = FakeRunnerAuthenticator(authorized=False)
    servicer = RuntimeRunnerControlGrpcServicer(
        control_protocol=control,
        coordination_store=InMemoryRuntimeCoordinationStore(),
        state_sink=FakeStateSink(),
        owner_replica_id="control-a",
        consumer_id="runner-consumer-a",
        operation_block_ms=1,
        runner_authenticator=authenticator,
        transfer_result_sink=RecordingTransferResultSink(),
    )

    await servicer._relay_runner_operations(  # Verify auth precedes durable claim.
        asyncio.Queue(maxsize=1),
        authentication=authenticator.credential,
        runtime_id="runtime-1",
        generation=1,
        active_transfer_dispatches={},
    )

    assert control.claim_count == 0


@pytest.mark.asyncio
async def test_runner_transfer_relay_deduplicates_only_identical_intent() -> None:
    """Identical transport retries are acknowledged without a second task."""
    envelope = _transfer_envelope()
    intent = _runner_transfer_intent(envelope)
    dispatch_key = ("transfer-1", "attempt-1", "dispatch-1", 1)
    fingerprint = (
        envelope.request_id,
        envelope.operation_type,
        envelope.reply_stream_id,
        intent.SerializeToString(deterministic=True),
    )
    control = CountingRelayControlProtocol([envelope])
    authenticator = FakeRunnerAuthenticator()
    servicer = RuntimeRunnerControlGrpcServicer(
        control_protocol=control,
        coordination_store=InMemoryRuntimeCoordinationStore(),
        state_sink=FakeStateSink(),
        owner_replica_id="control-a",
        consumer_id="runner-consumer-a",
        operation_block_ms=1,
        runner_authenticator=authenticator,
        transfer_result_sink=RecordingTransferResultSink(),
    )
    task = asyncio.create_task(
        servicer._relay_runner_operations(
            asyncio.Queue(maxsize=1),
            authentication=authenticator.credential,
            runtime_id="runtime-1",
            generation=1,
            active_transfer_dispatches={dispatch_key: fingerprint},
        )
    )
    for _ in range(100):
        if control.acked:
            break
        await asyncio.sleep(0)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    assert control.acked == [envelope]


@pytest.mark.asyncio
async def test_runner_transfer_relay_fails_closed_on_conflicting_duplicate() -> None:
    """A reused dispatch identity with different correlation closes the relay."""
    envelope = _transfer_envelope()
    dispatch_key = ("transfer-1", "attempt-1", "dispatch-1", 1)
    control = CountingRelayControlProtocol([envelope])
    authenticator = FakeRunnerAuthenticator()
    servicer = RuntimeRunnerControlGrpcServicer(
        control_protocol=control,
        coordination_store=InMemoryRuntimeCoordinationStore(),
        state_sink=FakeStateSink(),
        owner_replica_id="control-a",
        consumer_id="runner-consumer-a",
        operation_block_ms=1,
        runner_authenticator=authenticator,
        transfer_result_sink=RecordingTransferResultSink(),
    )

    with pytest.raises(RuntimeError, match="Conflicting duplicate"):
        await servicer._relay_runner_operations(
            asyncio.Queue(maxsize=1),
            authentication=authenticator.credential,
            runtime_id="runtime-1",
            generation=1,
            active_transfer_dispatches={
                dispatch_key: ("other-request", "file.transfer.v1", "reply-1", b"")
            },
        )

    assert control.acked == []


@pytest.mark.asyncio
async def test_transfer_results_do_not_evict_dispatch_tombstone() -> None:
    """Rejected and accepted results retain dedup authority for delayed intents."""
    store = InMemoryRuntimeCoordinationStore()
    now = datetime.now(UTC)
    await store.register_connection(
        kind=RuntimeConnectionKind.RUNNER,
        subject_id="runtime-1",
        connection_id="connection-1",
        owner_replica_id="control-a",
        connected_at=now,
        heartbeat_at=now,
        ttl_seconds=60,
        metadata={},
    )
    await store.put_operation(
        RuntimeOperationMetadata(
            operation_id="operation-1",
            runtime_id="runtime-1",
            target=RuntimeCoordinationTarget.RUNNER,
            generation=1,
            operation_type="file.transfer.v1",
            transfer_id="transfer-1",
            transfer_attempt_id="attempt-1",
            transfer_dispatch_id="dispatch-1",
            transfer_direction=RuntimeOperationTransferDirection.DOWNLOAD,
            request_stream_id="request-1",
            reply_stream_id="reply-1",
            status=RuntimeOperationStatus.ACTIVE,
            created_at=now,
            updated_at=now,
            deadline_at=now + timedelta(minutes=1),
            body_stream_id=None,
            last_heartbeat_at=None,
            last_event_at=None,
            cancel_requested_at=None,
            final_event_cursor=None,
        ),
        ttl_seconds=60,
    )
    sink = RecordingTransferResultSink()
    authenticator = FakeRunnerAuthenticator()
    servicer = RuntimeRunnerControlGrpcServicer(
        control_protocol=RuntimeControlProtocolService(store),
        coordination_store=store,
        state_sink=FakeStateSink(),
        owner_replica_id="control-a",
        consumer_id="runner-consumer-a",
        operation_block_ms=1,
        runner_authenticator=authenticator,
        transfer_result_sink=sink,
    )
    envelope = _transfer_envelope()
    intent = _runner_transfer_intent(envelope)
    dispatch_key = ("transfer-1", "attempt-1", "dispatch-1", 1)
    fingerprint = (
        envelope.request_id,
        envelope.operation_type,
        envelope.reply_stream_id,
        intent.SerializeToString(deterministic=True),
    )
    tombstones = {dispatch_key: fingerprint}
    inbound = QueueIterator()
    malformed = _transfer_result_message(committed=True)
    malformed.transfer_result.operation_id = "o" * 129
    await inbound.put(malformed)
    await inbound.put(_transfer_result_message(committed=True))
    await inbound.put(None)

    await servicer._consume_runner_messages(
        inbound,
        asyncio.Queue(maxsize=1),
        authentication=authenticator.credential,
        runtime_id="runtime-1",
        generation=1,
        active_transfer_dispatches=tombstones,
    )

    assert tombstones == {dispatch_key: fingerprint}
    assert len(sink.calls) == 1


@pytest.mark.asyncio
async def test_runner_grpc_relays_git_operation_payload() -> None:
    """The gRPC bridge maps Git operation payloads to protobuf oneofs."""
    store = InMemoryRuntimeCoordinationStore()
    service = RuntimeControlProtocolService(store, request_id_factory=lambda: "req-git")
    sink = FakeStateSink()
    servicer = _servicer(service, store, sink)
    inbound = QueueIterator()
    await inbound.put(_register_message())

    stream = servicer.ConnectRunner(inbound, FakeGrpcContext())
    accepted = await anext(stream)
    await service.dispatch_runner_operation(
        RuntimeRunnerOperation(
            runtime_id="runtime-1",
            runner_generation=accepted.register_accepted.generation,
            operation_type="create_git_worktree",
            owner_session_id=None,
            payload={
                "source_project_path": "/workspace/agent/repo",
                "worktree_path": "/workspace/agent/.azents/worktrees/session/repo",
                "branch_name": "azents/session",
                "starting_ref": "main",
            },
            deadline_at=datetime.now(UTC) + timedelta(seconds=30),
            body_stream_id=None,
        ),
        created_at=_now(),
    )

    command = await anext(stream)
    assert command.operation_request.operation_type == "create_git_worktree"
    assert not command.operation_request.HasField("owner_session_id")
    assert command.operation_request.WhichOneof("payload") == "git_create_worktree"
    assert command.operation_request.git_create_worktree.source_project_path == (
        "/workspace/agent/repo"
    )
    assert command.operation_request.git_create_worktree.branch_name == "azents/session"

    await service.dispatch_runner_operation(
        RuntimeRunnerOperation(
            runtime_id="runtime-1",
            runner_generation=accepted.register_accepted.generation,
            operation_type="inspect_git_worktree",
            owner_session_id="session-1",
            payload={
                "source_project_path": "/workspace/agent/repo",
                "worktree_path": "/workspace/agent/.azents/worktrees/session/repo",
                "branch_name": "azents/session",
            },
            deadline_at=datetime.now(UTC) + timedelta(seconds=30),
            body_stream_id=None,
        ),
        created_at=_now(),
    )
    command = await anext(stream)
    assert command.operation_request.WhichOneof("payload") == "git_inspect_worktree"
    assert command.operation_request.owner_session_id == "session-1"
    assert command.operation_request.git_inspect_worktree.worktree_path == (
        "/workspace/agent/.azents/worktrees/session/repo"
    )
    assert command.operation_request.git_inspect_worktree.branch_name == (
        "azents/session"
    )

    await service.dispatch_runner_operation(
        RuntimeRunnerOperation(
            runtime_id="runtime-1",
            runner_generation=accepted.register_accepted.generation,
            operation_type="discover_managed_git_worktrees",
            owner_session_id="session-1",
            payload={},
            deadline_at=datetime.now(UTC) + timedelta(seconds=30),
            body_stream_id=None,
        ),
        created_at=_now(),
    )
    command = await anext(stream)
    assert command.operation_request.WhichOneof("payload") == (
        "git_discover_managed_worktrees"
    )
    assert command.operation_request.owner_session_id == "session-1"

    await service.dispatch_runner_operation(
        RuntimeRunnerOperation(
            runtime_id="runtime-1",
            runner_generation=accepted.register_accepted.generation,
            operation_type="remove_git_worktree",
            owner_session_id="session-1",
            payload={
                "source_project_path": "/workspace/agent/repo",
                "worktree_path": "/workspace/agent/.azents/worktrees/session/repo",
                "branch_name": "azents/session",
                "force": True,
            },
            deadline_at=datetime.now(UTC) + timedelta(seconds=30),
            body_stream_id=None,
        ),
        created_at=_now(),
    )
    command = await anext(stream)
    assert command.operation_request.WhichOneof("payload") == "git_remove_worktree"
    assert command.operation_request.git_remove_worktree.force is True
    assert command.operation_request.git_remove_worktree.branch_name == (
        "azents/session"
    )
    await _close_stream(stream)


@pytest.mark.asyncio
async def test_runner_grpc_round_trips_file_glob_payload_and_result() -> None:
    """The gRPC bridge preserves file.glob request and result entries."""
    store = InMemoryRuntimeCoordinationStore()
    service = RuntimeControlProtocolService(
        store,
        request_id_factory=lambda: "req-glob",
    )
    servicer = _servicer(service, store, FakeStateSink())
    inbound = QueueIterator()
    await inbound.put(_register_message())

    stream = servicer.ConnectRunner(inbound, FakeGrpcContext())
    accepted = await anext(stream)
    result = await service.dispatch_runner_operation(
        RuntimeRunnerOperation(
            runtime_id="runtime-1",
            runner_generation=accepted.register_accepted.generation,
            operation_type="file.glob",
            owner_session_id="session-1",
            payload={
                "pattern": "/workspace/agent/**/*.py",
                "exclude_patterns": [".git", "node_modules"],
            },
            deadline_at=datetime.now(UTC) + timedelta(seconds=30),
            body_stream_id=None,
        ),
        created_at=_now(),
    )

    command = await anext(stream)
    assert isinstance(result, RuntimeDispatchResult)
    assert command.operation_request.WhichOneof("payload") == "file_glob"
    assert command.operation_request.file_glob.pattern == ("/workspace/agent/**/*.py")
    assert list(command.operation_request.file_glob.exclude_patterns) == [
        ".git",
        "node_modules",
    ]

    await inbound.put(
        runtime_runner_control_pb2.RunnerMessage(
            connection_id="connection-1",
            request_id="req-glob",
            generation=accepted.register_accepted.generation,
            operation_event=runtime_runner_control_pb2.RunnerOperationEvent(
                runtime_id="runtime-1",
                operation_id=result.operation_id,
                generation=accepted.register_accepted.generation,
                event_type="final_success",
                created_at=_timestamp(_now()),
                final=True,
                final_success=(
                    runtime_runner_control_pb2.RunnerOperationFinalSuccessPayload(
                        file_glob=runtime_runner_control_pb2.FileGlobFinalSuccess(
                            entries=[
                                runtime_runner_control_pb2.RuntimeFileListEntry(
                                    path="/workspace/agent/src/app.py",
                                    type="file",
                                    size_bytes=12,
                                )
                            ]
                        )
                    )
                ),
            ),
        )
    )
    await asyncio.sleep(0)
    replies = await service.read_replies(
        reply_stream_id=result.reply_stream_id,
        after_cursor=None,
        limit=10,
    )

    assert replies[-1].event.event_type is RuntimeReplyEventType.FINAL_SUCCESS
    assert replies[-1].event.payload == {
        "entries": [
            {
                "path": "/workspace/agent/src/app.py",
                "type": "file",
                "size_bytes": 12,
                "modified_at": None,
            }
        ]
    }
    await _close_stream(stream)


@pytest.mark.asyncio
async def test_runner_grpc_relays_file_apply_patch_and_preserves_failure() -> None:
    """The bridge relays patch bodies and stores typed partial-failure detail."""
    store = InMemoryRuntimeCoordinationStore()
    service = RuntimeControlProtocolService(
        store, request_id_factory=lambda: "req-patch"
    )
    sink = FakeStateSink()
    servicer = _servicer(service, store, sink)
    inbound = QueueIterator()
    await inbound.put(_register_message())

    stream = servicer.ConnectRunner(inbound, FakeGrpcContext())
    accepted = await anext(stream)
    body_stream_id = "body:req-patch"
    patch = b"*** Begin Patch\n*** End Patch\n"
    await store.append_body_chunk(
        body_stream_id,
        RuntimeBodyChunk(
            request_id=body_stream_id,
            chunk_id=1,
            data=patch,
            created_at=_now(),
            final=True,
        ),
    )
    result = await service.dispatch_runner_operation(
        RuntimeRunnerOperation(
            runtime_id="runtime-1",
            runner_generation=accepted.register_accepted.generation,
            operation_type="file.apply_patch",
            owner_session_id="session-1",
            payload={
                "base_path": "/workspace/agent/project",
                "total_bytes": len(patch),
                "schema_version": 1,
            },
            deadline_at=datetime.now(UTC) + timedelta(seconds=30),
            body_stream_id=body_stream_id,
        ),
        created_at=_now(),
    )

    command = await anext(stream)
    assert isinstance(result, RuntimeDispatchResult)
    assert command.operation_request.WhichOneof("payload") == "file_apply_patch"
    assert (
        command.operation_request.file_apply_patch.base_path
        == "/workspace/agent/project"
    )
    assert command.operation_request.file_apply_patch.total_bytes == len(patch)
    assert command.operation_request.file_apply_patch.schema_version == 1
    assert command.operation_request.body_chunks[0].data == patch

    await inbound.put(
        runtime_runner_control_pb2.RunnerMessage(
            connection_id="connection-1",
            request_id="req-patch",
            generation=accepted.register_accepted.generation,
            operation_event=runtime_runner_control_pb2.RunnerOperationEvent(
                runtime_id="runtime-1",
                operation_id="operation:req-patch",
                generation=accepted.register_accepted.generation,
                event_type="final_error",
                created_at=_timestamp(_now()),
                final=True,
                final_error=(
                    runtime_runner_control_pb2.RunnerOperationFinalErrorPayload(
                        error_code="PATCH_COMMIT_FAILED",
                        error_message="Source changed before delete",
                        file_apply_patch=(
                            runtime_runner_control_pb2.FileApplyPatchFailure(
                                phase="commit",
                                reason="source_changed",
                                applied=[
                                    runtime_runner_control_pb2.RuntimeFilePatchChange(
                                        path="src/app.py",
                                        action="update",
                                        added_lines=2,
                                        removed_lines=1,
                                        content_sha256="abc123",
                                    )
                                ],
                                failed=(
                                    runtime_runner_control_pb2.RuntimeFilePatchOperation(
                                        path="src/legacy.py",
                                        action="delete",
                                    )
                                ),
                                not_attempted=[
                                    runtime_runner_control_pb2.RuntimeFilePatchOperation(
                                        path="src/after.py",
                                        action="add",
                                    )
                                ],
                                exact=True,
                            )
                        ),
                    )
                ),
            ),
        )
    )
    replies = []
    for _ in range(10):
        replies = await service.read_replies(
            reply_stream_id=result.reply_stream_id,
            after_cursor=None,
            limit=10,
        )
        if replies:
            break
        await asyncio.sleep(0)

    detail = replies[0].event.payload["file_apply_patch"]
    assert isinstance(detail, dict)
    assert detail["phase"] == "commit"
    assert detail["applied"] == [
        {
            "path": "src/app.py",
            "action": "update",
            "added_lines": 2,
            "removed_lines": 1,
            "content_sha256": "abc123",
        }
    ]
    assert detail["failed"] == {"path": "src/legacy.py", "action": "delete"}
    assert detail["not_attempted"] == [{"path": "src/after.py", "action": "add"}]
    assert detail["exact"] is True
    await _close_stream(stream)


@pytest.mark.asyncio
async def test_runner_grpc_relays_file_edit_and_replacement_count() -> None:
    """The bridge serializes native edit parameters and final count."""
    store = InMemoryRuntimeCoordinationStore()
    service = RuntimeControlProtocolService(
        store, request_id_factory=lambda: "req-edit"
    )
    servicer = _servicer(service, store, FakeStateSink())
    inbound = QueueIterator()
    await inbound.put(_register_message())

    stream = servicer.ConnectRunner(inbound, FakeGrpcContext())
    accepted = await anext(stream)
    result = await service.dispatch_runner_operation(
        RuntimeRunnerOperation(
            runtime_id="runtime-1",
            runner_generation=accepted.register_accepted.generation,
            operation_type="file.edit",
            owner_session_id="session-1",
            payload={
                "path": "/workspace/agent/note.txt",
                "old_string": "before",
                "new_string": "after",
                "replace_all": True,
            },
            deadline_at=datetime.now(UTC) + timedelta(seconds=30),
            body_stream_id=None,
        ),
        created_at=_now(),
    )

    command = await anext(stream)
    assert isinstance(result, RuntimeDispatchResult)
    assert command.operation_request.WhichOneof("payload") == "file_edit"
    assert command.operation_request.file_edit.path == "/workspace/agent/note.txt"
    assert command.operation_request.file_edit.old_string == "before"
    assert command.operation_request.file_edit.new_string == "after"
    assert command.operation_request.file_edit.replace_all is True

    await inbound.put(
        runtime_runner_control_pb2.RunnerMessage(
            connection_id="connection-1",
            request_id="req-edit",
            generation=accepted.register_accepted.generation,
            operation_event=runtime_runner_control_pb2.RunnerOperationEvent(
                runtime_id="runtime-1",
                operation_id="operation:req-edit",
                generation=accepted.register_accepted.generation,
                event_type="final_success",
                created_at=_timestamp(_now()),
                final=True,
                final_success=(
                    runtime_runner_control_pb2.RunnerOperationFinalSuccessPayload(
                        file_edit=runtime_runner_control_pb2.FileEditFinalSuccess(
                            replacements=3
                        )
                    )
                ),
            ),
        )
    )
    replies = []
    for _ in range(10):
        replies = await service.read_replies(
            reply_stream_id=result.reply_stream_id,
            after_cursor=None,
            limit=10,
        )
        if replies:
            break
        await asyncio.sleep(0)

    assert replies[0].event.payload == {"replacements": 3}
    await _close_stream(stream)


@pytest.mark.asyncio
async def test_runner_grpc_rejects_missing_runner_credential() -> None:
    store = InMemoryRuntimeCoordinationStore()
    servicer = _servicer(RuntimeControlProtocolService(store), store, FakeStateSink())
    inbound = QueueIterator()
    await inbound.put(_register_message())

    stream = servicer.ConnectRunner(inbound, FakeGrpcContext(()))

    with pytest.raises(RuntimeError, match="UNAUTHENTICATED"):
        await anext(stream)


@pytest.mark.asyncio
async def test_runner_grpc_rejects_wrong_runner_credential() -> None:
    store = InMemoryRuntimeCoordinationStore()
    servicer = _servicer(RuntimeControlProtocolService(store), store, FakeStateSink())
    inbound = QueueIterator()
    await inbound.put(_register_message())

    stream = servicer.ConnectRunner(
        inbound,
        FakeGrpcContext((("authorization", "Bearer wrong"),)),
    )

    with pytest.raises(RuntimeError, match="UNAUTHENTICATED"):
        await anext(stream)


@pytest.mark.asyncio
async def test_runner_grpc_accepts_runtime_bound_bearer_credential() -> None:
    store = InMemoryRuntimeCoordinationStore()
    servicer = _servicer(RuntimeControlProtocolService(store), store, FakeStateSink())
    inbound = QueueIterator()
    await inbound.put(_register_message())

    stream = servicer.ConnectRunner(
        inbound,
        FakeGrpcContext((("authorization", "Bearer runner-token"),)),
    )
    accepted = await anext(stream)
    connection = await store.get_connection(
        kind=RuntimeConnectionKind.RUNNER,
        subject_id="runtime-1",
    )
    await _close_stream(stream)

    assert accepted.register_accepted.runtime_id == "runtime-1"
    assert connection is not None
    assert connection.metadata["auth_credential_id"] == "credential-1"
    assert "runner-token" not in repr(connection.metadata)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "register",
    [
        runtime_runner_control_pb2.RunnerRegister(
            runtime_id="runtime-2",
            runner_id="runner-1",
            protocol_version="agent-runtime-runner.v1",
            capabilities=("bash",),
            health="ok",
            workspace_path="/workspace/agent",
            auth_credential_id="credential-1",
        ),
        runtime_runner_control_pb2.RunnerRegister(
            runtime_id="runtime-1",
            runner_id="runner-1",
            protocol_version="agent-runtime-runner.v1",
            capabilities=("bash",),
            health="ok",
            workspace_path="/workspace/agent",
            auth_credential_id="credential-2",
        ),
    ],
)
async def test_runner_grpc_rejects_registration_identity_mismatch(
    register: runtime_runner_control_pb2.RunnerRegister,
) -> None:
    store = InMemoryRuntimeCoordinationStore()
    servicer = _servicer(RuntimeControlProtocolService(store), store, FakeStateSink())
    inbound = QueueIterator()
    await inbound.put(
        runtime_runner_control_pb2.RunnerMessage(
            connection_id="connection-1",
            request_id="register",
            register=register,
        )
    )

    stream = servicer.ConnectRunner(inbound, FakeGrpcContext())

    with pytest.raises(RuntimeError, match="PERMISSION_DENIED"):
        await anext(stream)


@pytest.mark.asyncio
async def test_runner_grpc_revokes_retained_authority_after_generation_change() -> None:
    store = InMemoryRuntimeCoordinationStore()
    service = RuntimeControlProtocolService(store)
    authenticator = FakeRunnerAuthenticator()
    servicer = _servicer(
        service,
        store,
        FakeStateSink(),
        runner_authenticator=authenticator,
    )
    inbound = QueueIterator()
    await inbound.put(_register_message())
    stream = servicer.ConnectRunner(inbound, FakeGrpcContext())
    accepted = await anext(stream)
    authenticator.authorized = False
    await inbound.put(
        runtime_runner_control_pb2.RunnerMessage(
            connection_id="connection-1",
            request_id="heartbeat-1",
            generation=accepted.register_accepted.generation,
            heartbeat=runtime_runner_control_pb2.RunnerHeartbeat(
                monotonic_sequence=1,
            ),
        )
    )

    with pytest.raises(StopAsyncIteration):
        await anext(stream)

    result = await service.dispatch_runner_operation(
        RuntimeRunnerOperation(
            runtime_id="runtime-1",
            runner_generation=accepted.register_accepted.generation,
            operation_type="file.stat",
            owner_session_id="session-1",
            payload={"path": "/workspace/agent"},
            deadline_at=datetime.now(UTC) + timedelta(seconds=30),
            body_stream_id=None,
        ),
        created_at=_now(),
    )
    assert isinstance(result, RuntimeProtocolRouteUnavailable)


@pytest.mark.asyncio
async def test_runner_grpc_start_claim_is_atomic() -> None:
    """Start authorization claims ACTIVE operations so cancel can win before start."""
    store = InMemoryRuntimeCoordinationStore()
    service = RuntimeControlProtocolService(store, request_id_factory=lambda: "req-1")
    servicer = _servicer(service, store, FakeStateSink())
    inbound = QueueIterator()
    await inbound.put(_register_message())

    stream = servicer.ConnectRunner(inbound, FakeGrpcContext())
    accepted = await anext(stream)
    result = await service.dispatch_runner_operation(
        RuntimeRunnerOperation(
            runtime_id="runtime-1",
            runner_generation=accepted.register_accepted.generation,
            operation_type="file.stat",
            owner_session_id="session-1",
            payload={"path": "/workspace/agent"},
            deadline_at=datetime.now(UTC) + timedelta(seconds=30),
            body_stream_id=None,
        ),
        created_at=_now(),
    )
    assert isinstance(result, RuntimeDispatchResult)
    await anext(stream)

    await inbound.put(
        runtime_runner_control_pb2.RunnerMessage(
            connection_id="connection-1",
            request_id="start:req-1",
            generation=accepted.register_accepted.generation,
            operation_start=runtime_runner_control_pb2.RunnerOperationStart(
                runtime_id="runtime-1",
                operation_id=result.operation_id,
            ),
        )
    )
    start_ack = await anext(stream)
    assert start_ack.operation_start_ack.allowed
    metadata = await store.get_operation(result.operation_id)
    assert metadata is not None
    assert metadata.status is RuntimeOperationStatus.RUNNING

    await inbound.put(
        runtime_runner_control_pb2.RunnerMessage(
            connection_id="connection-1",
            request_id="start:req-1-retry",
            generation=accepted.register_accepted.generation,
            operation_start=runtime_runner_control_pb2.RunnerOperationStart(
                runtime_id="runtime-1",
                operation_id=result.operation_id,
            ),
        )
    )
    retry_ack = await anext(stream)
    assert not retry_ack.operation_start_ack.allowed
    await _close_stream(stream)


@pytest.mark.asyncio
async def test_runner_grpc_relays_ordered_cancel_command() -> None:
    """Control relays cancellation after the operation on the Runner stream."""
    store = InMemoryRuntimeCoordinationStore()
    request_ids = iter(("req-operation", "req-cancel"))
    service = RuntimeControlProtocolService(
        store,
        request_id_factory=lambda: next(request_ids),
    )
    servicer = _servicer(service, store, FakeStateSink())
    inbound = QueueIterator()
    await inbound.put(_register_message())

    stream = servicer.ConnectRunner(inbound, FakeGrpcContext())
    accepted = await anext(stream)
    operation = await service.dispatch_runner_operation(
        RuntimeRunnerOperation(
            runtime_id="runtime-1",
            runner_generation=accepted.register_accepted.generation,
            operation_type="file.apply_patch",
            owner_session_id="session-1",
            payload={
                "base_path": "/workspace/agent/project",
                "total_bytes": 0,
                "schema_version": 1,
            },
            deadline_at=datetime.now(UTC) + timedelta(seconds=30),
            body_stream_id=None,
        ),
        created_at=_now(),
    )
    assert isinstance(operation, RuntimeDispatchResult)
    operation_message = await anext(stream)

    cancellation = await service.request_runner_operation_cancel(
        runtime_id="runtime-1",
        runner_generation=accepted.register_accepted.generation,
        operation_id=operation.operation_id,
        created_at=_now() + timedelta(seconds=1),
    )
    cancel_message = await anext(stream)

    assert isinstance(cancellation, RuntimeDispatchResult)
    assert operation_message.WhichOneof("payload") == "operation_request"
    assert cancel_message.WhichOneof("payload") == "operation_cancel"
    assert cancel_message.request_id == "req-cancel"
    assert cancel_message.operation_cancel.runtime_id == "runtime-1"
    assert cancel_message.operation_cancel.operation_id == operation.operation_id
    await _close_stream(stream)


@pytest.mark.asyncio
async def test_runner_grpc_rejects_late_final_after_cancel() -> None:
    """Late Runner finals must not overwrite a canceled final cursor."""
    store = InMemoryRuntimeCoordinationStore()
    service = RuntimeControlProtocolService(store, request_id_factory=lambda: "req-1")
    servicer = _servicer(service, store, FakeStateSink())
    inbound = QueueIterator()
    await inbound.put(_register_message())

    stream = servicer.ConnectRunner(inbound, FakeGrpcContext())
    accepted = await anext(stream)
    result = await service.dispatch_runner_operation(
        RuntimeRunnerOperation(
            runtime_id="runtime-1",
            runner_generation=accepted.register_accepted.generation,
            operation_type="file.stat",
            owner_session_id="session-1",
            payload={"path": "/workspace/agent"},
            deadline_at=datetime.now(UTC) + timedelta(seconds=30),
            body_stream_id=None,
        ),
        created_at=_now(),
    )
    assert isinstance(result, RuntimeDispatchResult)
    await anext(stream)
    canceled = await store.append_reply_for_operation(
        result.reply_stream_id,
        RuntimeReplyEvent(
            request_id="req-1",
            runtime_id="runtime-1",
            generation=accepted.register_accepted.generation,
            event_type=RuntimeReplyEventType.FINAL_ERROR,
            payload={"error_code": "canceled", "error_message": "cancelled"},
            created_at=_now(),
            final=True,
        ),
        operation_id=result.operation_id,
    )
    assert canceled is not None
    cancel_cursor, _ = canceled

    await inbound.put(
        runtime_runner_control_pb2.RunnerMessage(
            connection_id="connection-1",
            request_id="req-1",
            generation=accepted.register_accepted.generation,
            operation_event=runtime_runner_control_pb2.RunnerOperationEvent(
                runtime_id="runtime-1",
                operation_id=result.operation_id,
                generation=accepted.register_accepted.generation,
                event_type="final_success",
                created_at=_timestamp(_now()),
                final=True,
                final_success=(
                    runtime_runner_control_pb2.RunnerOperationFinalSuccessPayload(
                        bash=runtime_runner_control_pb2.BashFinalSuccess(
                            exit_code=0,
                        )
                    )
                ),
            ),
        )
    )
    await asyncio.sleep(0)
    metadata = await store.get_operation(result.operation_id)
    assert metadata is not None
    assert metadata.status is RuntimeOperationStatus.FINAL
    assert metadata.final_event_cursor == cancel_cursor
    replies = await service.read_replies(
        reply_stream_id=result.reply_stream_id,
        after_cursor=None,
        limit=10,
    )
    assert len(replies) == 1
    assert replies[0].event.event_type is RuntimeReplyEventType.FINAL_ERROR
    await _close_stream(stream)


def test_connect_runner_outbound_queue_is_bounded() -> None:
    """ConnectRunner constructs a maxsize=1 outbound queue for backpressure."""
    source = inspect.getsource(RuntimeRunnerControlGrpcServicer.ConnectRunner)
    assert "asyncio.Queue(maxsize=1)" in source


def _servicer(
    service: RuntimeControlProtocolService,
    store: InMemoryRuntimeCoordinationStore,
    sink: FakeStateSink,
    *,
    runner_authenticator: FakeRunnerAuthenticator | None = None,
) -> RuntimeRunnerControlGrpcServicer:
    return RuntimeRunnerControlGrpcServicer(
        control_protocol=service,
        coordination_store=store,
        state_sink=sink,
        owner_replica_id="control-a",
        consumer_id="runner-consumer-a",
        runner_authenticator=runner_authenticator or FakeRunnerAuthenticator(),
        transfer_result_sink=RecordingTransferResultSink(),
        operation_block_ms=1,
    )


def _register_message(
    connection_id: str = "connection-1",
) -> runtime_runner_control_pb2.RunnerMessage:
    return runtime_runner_control_pb2.RunnerMessage(
        connection_id=connection_id,
        request_id="register",
        register=runtime_runner_control_pb2.RunnerRegister(
            runtime_id="runtime-1",
            runner_id="runner-1",
            protocol_version="2026-07-25",
            capabilities=("bash", "file.read", "file.transfer.v1"),
            health="ok",
            workspace_path="/workspace/agent",
            auth_credential_id="credential-1",
            runtime_configuration=_runtime_configuration_evidence_message(),
        ),
    )


def _metrics_register_message() -> runtime_runner_control_pb2.RunnerMessage:
    message = _register_message()
    message.register.capabilities.append(RUNNER_SYSTEM_METRICS_CAPABILITY)
    return message


def _system_metrics_report(*, sequence: int) -> RunnerSystemMetricsReport:
    return RunnerSystemMetricsReport(
        runtime_id="runtime-1",
        sequence=sequence,
        scope=RunnerSystemMetricsScope.CONTAINER,
        cpu=RunnerSystemMetricObservation(
            availability=RunnerSystemMetricAvailability.AVAILABLE,
            used=250,
            total=1000,
        ),
        memory=RunnerSystemMetricObservation(
            availability=RunnerSystemMetricAvailability.AVAILABLE,
            used=1024,
            total=4096,
        ),
        disk=RunnerSystemMetricObservation(
            availability=RunnerSystemMetricAvailability.UNAVAILABLE,
            used=None,
            total=None,
        ),
    )


def _sized_system_metrics_message(
    target_size: int,
    *,
    sequence: int,
) -> runtime_runner_control_pb2.RunnerSystemMetrics:
    message = runner_system_metrics_to_message(
        _system_metrics_report(sequence=sequence)
    )
    serialized = message.SerializeToString(deterministic=True)
    unknown_tag = _encode_varint((99 << 3) | 2)
    payload_size = target_size - len(serialized) - len(unknown_tag)
    while True:
        length_prefix = _encode_varint(payload_size)
        adjusted = target_size - len(serialized) - len(unknown_tag) - len(length_prefix)
        if adjusted == payload_size:
            break
        payload_size = adjusted
    assert payload_size >= 0
    message.ParseFromString(
        serialized + unknown_tag + _encode_varint(payload_size) + (b"x" * payload_size)
    )
    assert message.ByteSize() == target_size
    return message


def _encode_varint(value: int) -> bytes:
    encoded = bytearray()
    while value > 0x7F:
        encoded.append((value & 0x7F) | 0x80)
        value >>= 7
    encoded.append(value)
    return bytes(encoded)


def _transfer_envelope() -> RuntimeRequestEnvelope:
    return RuntimeRequestEnvelope(
        request_id="transfer-request-1",
        runtime_id="runtime-1",
        target=RuntimeCoordinationTarget.RUNNER,
        generation=1,
        operation_type="file.transfer.v1",
        payload={
            "transfer_id": "transfer-1",
            "attempt_id": "attempt-1",
            "runtime_id": "runtime-1",
            "desired_generation": 1,
            "direction": "upload",
            "operation_id": "operation-1",
            "owner_session_id": "session-1",
            "runtime_path": "/workspace/file",
            "overwrite": False,
            "expected_size": 3,
            "expected_sha256": "a" * 64,
            "dispatch_id": "dispatch-1",
        },
        reply_stream_id="reply-1",
        deadline_at=_now() + timedelta(minutes=1),
        body_stream_id=None,
    )


def _state_report_message() -> runtime_runner_control_pb2.RunnerStateReport:
    return runtime_runner_control_pb2.RunnerStateReport(
        runtime_id="runtime-1",
        runner_id="runner-1",
        runner_generation=1,
        runner_state="ready",
        capabilities=("bash", "file.read"),
        health="ok",
        workspace_path="/workspace/agent",
        reported_at=_timestamp(_now()),
        runtime_configuration=_runtime_configuration_evidence_message(),
    )


def _runtime_configuration_evidence_message() -> (
    runtime_configuration_pb2.RuntimeConfigurationEvidence
):
    return runtime_configuration_pb2.RuntimeConfigurationEvidence(
        configuration_sequence="1",
        digest="d" * 64,
        desired_generation=1,
    )


def _timestamp(value: datetime) -> timestamp_pb2.Timestamp:
    timestamp = timestamp_pb2.Timestamp()
    timestamp.FromDatetime(value)
    return timestamp


def _now() -> datetime:
    return datetime(2026, 5, 25, tzinfo=UTC)
