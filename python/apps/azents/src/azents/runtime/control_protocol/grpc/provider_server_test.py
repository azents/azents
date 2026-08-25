"""Agent Runtime Provider Control gRPC server tests."""

# protobuf generated modules expose dynamic message attributes.

import asyncio
import dataclasses
from collections.abc import AsyncGenerator, AsyncIterator
from datetime import UTC, datetime, timedelta

import grpc
import pytest
from azents_runtime_control.proto import (
    runtime_configuration_pb2,
    runtime_provider_control_pb2,
)
from azents_runtime_control.provider import (
    RuntimeLifecycleCommandType as RuntimeProviderCommandType,
)
from azents_runtime_control.provider import (
    RuntimeProviderOperationalDiagnostics,
    RuntimeProviderReconciliationEvidence,
    RuntimeProviderReconciliationObservation,
    RuntimeProviderReconciliationStatus,
    RuntimeProviderReport,
)
from azents_runtime_control.runtime_configuration import (
    JsonValue,
    RuntimeConfigurationEnvelope,
    RuntimeConfigurationEvidence,
    canonical_runtime_configuration_json,
)
from google.protobuf import struct_pb2, timestamp_pb2

from azents.core.enums import (
    RuntimeProviderAuthMethod,
    RuntimeProviderKind,
    RuntimeProviderScope,
)
from azents.core.runtime_runner_credential import RuntimeRunnerIssuedCredential
from azents.runtime.control_protocol.data import (
    RuntimeDispatchResult,
    RuntimeProviderCommand,
)
from azents.runtime.control_protocol.grpc.provider_server import (
    RuntimeProviderControlGrpcServicer,
)
from azents.runtime.control_protocol.service import (
    RuntimeControlProtocolService,
)
from azents.runtime.coordination.data import (
    RuntimeConnectionKind,
    RuntimeReplyEventType,
)
from azents.runtime.coordination.memory import (
    InMemoryRuntimeCoordinationStore,
)
from azents.services.runtime_provider_control.data import (
    RuntimeProviderCredentialAuthentication,
    RuntimeProviderCredentialUnavailable,
)
from azents.testing.grpc import FakeGrpcContext as BaseFakeGrpcContext


async def _close_stream[MessageT](stream: AsyncIterator[MessageT]) -> None:
    """Close the concrete async generator returned by the test subject."""
    assert isinstance(stream, AsyncGenerator)
    await stream.aclose()


@dataclasses.dataclass
class FakeReportSink:
    """Collect Provider reports delivered by the gRPC bridge."""

    reports: list[RuntimeProviderReport] = dataclasses.field(default_factory=list)
    configuration_acknowledgements: list[bool] = dataclasses.field(default_factory=list)
    restart_handoffs: list[RuntimeProviderReport] = dataclasses.field(
        default_factory=list
    )

    async def record_provider_report(
        self,
        report: RuntimeProviderReport,
        *,
        configuration_acknowledgement_allowed: bool,
    ) -> None:
        """Record one Provider report."""
        self.reports.append(report)
        self.configuration_acknowledgements.append(
            configuration_acknowledgement_allowed
        )

    async def complete_restart_handoff(
        self,
        report: RuntimeProviderReport,
    ) -> bool:
        """Record one successful correlated Restart handoff."""
        self.restart_handoffs.append(report)
        return True


@dataclasses.dataclass
class FakeObserveCompletionHandler:
    """Collect correlated successful OBSERVE completion reports."""

    reports: list[RuntimeProviderReport] = dataclasses.field(default_factory=list)

    async def reconcile_observe_completion(self, report: RuntimeProviderReport) -> bool:
        """Record one eligible report."""
        self.reports.append(report)
        return True


@dataclasses.dataclass
class FakeProviderCredentialBridge:
    """Authenticate fixed test credentials and capture stream lifecycle calls."""

    expected_secret: str = "provider-secret"
    authentication: RuntimeProviderCredentialAuthentication = dataclasses.field(
        default_factory=lambda: RuntimeProviderCredentialAuthentication(
            binding_id="binding-1",
            credential_id="credential-1",
            provider_id="provider-1",
            provider_resource_id="provider-row-1",
            provider_kind=RuntimeProviderKind.DOCKER,
            provider_scope=RuntimeProviderScope.SYSTEM,
            provider_workspace_id=None,
            auth_method=RuntimeProviderAuthMethod.AZENTS_ISSUED_TOKEN,
            auth_subject="admin:provider-1",
            evidence_expires_at=None,
        )
    )
    create_calls: list[dict[str, object]] = dataclasses.field(default_factory=list)
    heartbeat_calls: list[dict[str, object]] = dataclasses.field(default_factory=list)

    async def authenticate_credential(
        self,
        *,
        secret: str,
    ) -> RuntimeProviderCredentialAuthentication:
        """Resolve the test Provider credential."""
        if secret != self.expected_secret:
            raise RuntimeProviderCredentialUnavailable("credential_unavailable")
        return self.authentication

    async def authenticate_provider(
        self,
        *,
        method: RuntimeProviderAuthMethod,
        secret: str,
    ) -> RuntimeProviderCredentialAuthentication:
        """Resolve the explicitly selected test Provider auth method."""
        if method is not RuntimeProviderAuthMethod.AZENTS_ISSUED_TOKEN:
            raise RuntimeProviderCredentialUnavailable("auth_method_unavailable")
        return await self.authenticate_credential(secret=secret)

    async def create_connection(self, **kwargs: object) -> object:
        """Accept a test Provider stream."""
        self.create_calls.append(kwargs)
        return object()

    async def heartbeat_connection(self, **kwargs: object) -> bool:
        """Accept a test Provider stream heartbeat."""
        self.heartbeat_calls.append(kwargs)
        return True

    async def connection_active(self, **_: object) -> bool:
        """Keep test Provider command delivery authorized."""
        return True

    async def disconnect_connection(self, **_: object) -> bool:
        """Accept a test Provider stream closure."""
        return True


@dataclasses.dataclass(frozen=True)
class FakeRuntimeRunnerCredentialIssuer:
    """Issue fixed Runner evidence for Provider relay tests."""

    def issue(
        self,
        *,
        runtime_id: str,
        desired_generation: int,
    ) -> RuntimeRunnerIssuedCredential:
        """Return deterministic test evidence for the expected Runtime."""
        assert runtime_id == "runtime-1"
        assert desired_generation == 5
        return RuntimeRunnerIssuedCredential(
            token="runner-token",
            credential_id="runner-credential-1",
        )


class FakeRuntimeProviderContractProposer:
    """Accept test Provider contract proposals."""

    async def propose_contract(self, **_: object) -> object:
        """Accept one test proposal."""
        return object()


class QueueIterator:
    """Async iterator backed by a queue."""

    def __init__(self) -> None:
        self._queue: asyncio.Queue[
            runtime_provider_control_pb2.ProviderMessage | None
        ] = asyncio.Queue()

    async def put(
        self,
        message: runtime_provider_control_pb2.ProviderMessage | None,
    ) -> None:
        """Append an inbound message."""
        await self._queue.put(message)

    def __aiter__(self) -> "QueueIterator":
        """Return self."""
        return self

    async def __anext__(self) -> runtime_provider_control_pb2.ProviderMessage:
        """Return the next queued message."""
        message = await self._queue.get()
        if message is None:
            raise StopAsyncIteration
        return message


class FakeGrpcContext(
    BaseFakeGrpcContext[
        runtime_provider_control_pb2.ProviderMessage,
        runtime_provider_control_pb2.ControlMessage,
    ]
):
    """Minimal gRPC context for tests."""

    def __init__(
        self,
        metadata: grpc.aio.Metadata | tuple[tuple[str, str], ...] | None = None,
    ) -> None:
        super().__init__(
            metadata=(
                metadata
                if metadata is not None
                else (
                    ("authorization", "Bearer provider-secret"),
                    (
                        "x-azents-runtime-provider-auth-method",
                        "azents_issued_token",
                    ),
                )
            )
        )


@pytest.mark.asyncio
async def test_provider_grpc_registers_and_acks_heartbeat() -> None:
    store = InMemoryRuntimeCoordinationStore()
    servicer = _servicer(RuntimeControlProtocolService(store), FakeReportSink())
    inbound = QueueIterator()
    await inbound.put(_register_message())
    await inbound.put(
        runtime_provider_control_pb2.ProviderMessage(
            connection_id="connection-1",
            request_id="heartbeat-1",
            generation=1,
            heartbeat=runtime_provider_control_pb2.ProviderHeartbeat(
                monotonic_sequence=7,
            ),
        )
    )
    await inbound.put(None)

    stream = servicer.ConnectProvider(inbound, FakeGrpcContext())
    accepted = await anext(stream)
    heartbeat_ack = await anext(stream)
    await _close_stream(stream)

    assert accepted.register_accepted.provider_id == "provider-1"
    assert accepted.register_accepted.generation == 1
    assert heartbeat_ack.heartbeat_ack.monotonic_sequence == 7


@pytest.mark.asyncio
async def test_provider_grpc_rejects_stream_generation_mismatch() -> None:
    store = InMemoryRuntimeCoordinationStore()
    sink = FakeReportSink()
    servicer = _servicer(RuntimeControlProtocolService(store), sink)
    inbound = QueueIterator()
    await inbound.put(_register_message())
    await inbound.put(
        runtime_provider_control_pb2.ProviderMessage(
            connection_id="connection-1",
            request_id="report-1",
            generation=2,
            report=_report_message(),
        )
    )

    stream = servicer.ConnectProvider(inbound, FakeGrpcContext())
    accepted = await anext(stream)
    error = await anext(stream)
    await _close_stream(stream)

    assert accepted.register_accepted.generation == 1
    assert error.error.code == "STALE_PROVIDER_GENERATION"
    assert sink.reports == []


@pytest.mark.asyncio
async def test_provider_grpc_rejects_report_after_newer_registration() -> None:
    store = InMemoryRuntimeCoordinationStore()
    service = RuntimeControlProtocolService(store)
    sink = FakeReportSink()
    servicer = _servicer(service, sink)
    old_inbound = QueueIterator()
    await old_inbound.put(_register_message("connection-1"))
    old_stream = servicer.ConnectProvider(old_inbound, FakeGrpcContext())
    old_accepted = await anext(old_stream)
    new_inbound = QueueIterator()
    await new_inbound.put(_register_message("connection-2"))
    new_stream = servicer.ConnectProvider(new_inbound, FakeGrpcContext())
    new_accepted = await anext(new_stream)
    await old_inbound.put(
        runtime_provider_control_pb2.ProviderMessage(
            connection_id="connection-1",
            request_id="report-1",
            generation=old_accepted.register_accepted.generation,
            report=_report_message(),
        )
    )

    error = await anext(old_stream)
    await _close_stream(old_stream)
    await _close_stream(new_stream)

    assert old_accepted.register_accepted.generation == 1
    assert new_accepted.register_accepted.generation == 2
    assert error.error.code == "STALE_PROVIDER_GENERATION"
    assert sink.reports == []


@pytest.mark.asyncio
async def test_provider_grpc_rejects_report_generation_mismatch() -> None:
    store = InMemoryRuntimeCoordinationStore()
    sink = FakeReportSink()
    servicer = _servicer(RuntimeControlProtocolService(store), sink)
    inbound = QueueIterator()
    await inbound.put(_register_message())
    report = _report_message()
    report.provider_generation = 2
    await inbound.put(
        runtime_provider_control_pb2.ProviderMessage(
            connection_id="connection-1",
            request_id="report-1",
            generation=1,
            report=report,
        )
    )

    stream = servicer.ConnectProvider(inbound, FakeGrpcContext())
    accepted = await anext(stream)
    error = await anext(stream)
    await _close_stream(stream)

    assert accepted.register_accepted.generation == 1
    assert error.error.code == "STALE_PROVIDER_GENERATION"
    assert sink.reports == []


@pytest.mark.asyncio
async def test_provider_grpc_relays_commands_and_records_completion() -> None:
    store = InMemoryRuntimeCoordinationStore()
    service = RuntimeControlProtocolService(store, request_id_factory=lambda: "req-1")
    sink = FakeReportSink()
    servicer = _servicer(service, sink)
    inbound = QueueIterator()
    await inbound.put(_register_message())

    stream = servicer.ConnectProvider(inbound, FakeGrpcContext())
    accepted = await anext(stream)
    result = await service.dispatch_provider_command(
        RuntimeProviderCommand(
            provider_id="provider-1",
            provider_generation=accepted.register_accepted.generation,
            runtime_id="runtime-1",
            desired_generation=5,
            command_type=RuntimeProviderCommandType.RESTART,
            reset_final_desired_state=None,
            payload={
                "identity": {
                    "agent_id": "agent-1",
                    "workspace_id": "workspace-1",
                },
                "runner_image": "runner:latest",
                "auth": {
                    "control_endpoint": "runtime-control:8020",
                    "transfer_endpoint": "runtime-transfer:8030",
                    "runner_auth_credential_id": "runner-credential-1",
                },
            },
            deadline_at=datetime.now(UTC) + timedelta(seconds=30),
            runtime_configuration=_runtime_configuration(),
        ),
        created_at=_now(),
    )

    command = await anext(stream)
    assert isinstance(result, RuntimeDispatchResult)
    assert command.provider_command.runtime_id == "runtime-1"
    assert command.provider_command.command_type == "restart"
    assert command.provider_command.runner_image == "runner:latest"
    assert command.provider_command.transfer_endpoint == "runtime-transfer:8030"
    assert command.provider_command.runner_auth_token == "runner-token"
    auth_fields = command.provider_command.payload.fields["auth"].struct_value.fields
    assert "runner_auth_token" not in auth_fields
    assert auth_fields["runner_auth_credential_id"].string_value == (
        "runner-credential-1"
    )

    await inbound.put(
        runtime_provider_control_pb2.ProviderMessage(
            connection_id="connection-1",
            request_id="req-1",
            generation=accepted.register_accepted.generation,
            command_completion=runtime_provider_control_pb2.ProviderCommandCompletion(
                request_id="req-1",
                runtime_id="runtime-1",
                generation=accepted.register_accepted.generation,
                success=True,
                report=_report_message(),
                completed_at=_timestamp(_now()),
            ),
        )
    )
    await asyncio.sleep(0)
    replies = await service.read_replies(
        reply_stream_id=result.reply_stream_id,
        after_cursor=None,
        limit=10,
    )

    assert replies[0].event.event_type is RuntimeReplyEventType.FINAL_SUCCESS
    assert "workspace_path" not in replies[0].event.payload
    assert not hasattr(sink.reports[0], "workspace_path")
    assert sink.restart_handoffs == [sink.reports[0]]
    await _close_stream(stream)


@pytest.mark.asyncio
async def test_provider_grpc_rejects_restart_report_for_another_runtime() -> None:
    """A correlated Restart completion cannot hand off a different Runtime."""
    store = InMemoryRuntimeCoordinationStore()
    service = RuntimeControlProtocolService(store, request_id_factory=lambda: "req-1")
    sink = FakeReportSink()
    servicer = _servicer(service, sink)
    inbound = QueueIterator()
    await inbound.put(_register_message())

    stream = servicer.ConnectProvider(inbound, FakeGrpcContext())
    accepted = await anext(stream)
    result = await service.dispatch_provider_command(
        _provider_command(
            generation=accepted.register_accepted.generation,
            command_type=RuntimeProviderCommandType.RESTART,
        ),
        created_at=_now(),
    )
    assert isinstance(result, RuntimeDispatchResult)
    await anext(stream)
    report = _report_message()
    report.runtime_id = "runtime-2"
    await inbound.put(
        runtime_provider_control_pb2.ProviderMessage(
            connection_id="connection-1",
            request_id="req-1",
            generation=accepted.register_accepted.generation,
            command_completion=runtime_provider_control_pb2.ProviderCommandCompletion(
                request_id="req-1",
                runtime_id="runtime-1",
                generation=accepted.register_accepted.generation,
                success=True,
                report=report,
                completed_at=_timestamp(_now()),
            ),
        )
    )

    error = await anext(stream)
    replies = await service.read_replies(
        reply_stream_id=result.reply_stream_id,
        after_cursor=None,
        limit=10,
    )
    await _close_stream(stream)

    assert error.error.code == "INVALID_PROVIDER_COMMAND_COMPLETION"
    assert replies == []
    assert sink.reports == []
    assert sink.restart_handoffs == []


@pytest.mark.asyncio
async def test_provider_grpc_hands_only_observe_completion_to_reconciler() -> None:
    """A duplicate OBSERVE completion cannot enqueue duplicate drift repair."""
    store = InMemoryRuntimeCoordinationStore()
    service = RuntimeControlProtocolService(
        store,
        request_id_factory=lambda: "observe-request",
    )
    sink = FakeReportSink()
    handler = FakeObserveCompletionHandler()
    bridge = FakeProviderCredentialBridge(
        authentication=dataclasses.replace(
            FakeProviderCredentialBridge().authentication,
            provider_kind=RuntimeProviderKind.KUBERNETES,
        )
    )
    servicer = _servicer(
        service,
        sink,
        bridge=bridge,
        observe_completion_handler=handler,
    )
    inbound = QueueIterator()
    await inbound.put(
        _register_message(
            provider_type="kubernetes",
            protocol_version="agent-runtime-provider-kubernetes-v2",
        )
    )

    stream = servicer.ConnectProvider(inbound, FakeGrpcContext())
    accepted = await anext(stream)
    result = await service.dispatch_provider_command(
        _provider_command(
            generation=accepted.register_accepted.generation,
            command_type=RuntimeProviderCommandType.OBSERVE,
        ),
        created_at=_now(),
    )
    command = await anext(stream)

    assert isinstance(result, RuntimeDispatchResult)
    assert command.provider_command.command_type == "observe"
    report = _report_message()
    report.reconciliation.CopyFrom(
        runtime_provider_control_pb2.RuntimeProviderReconciliationEvidence(
            observations=(
                runtime_provider_control_pb2.RuntimeProviderReconciliationObservation(
                    kind="network_policy",
                    status="drifted",
                    reason="network_policy_mismatch",
                ),
            )
        )
    )
    completion = runtime_provider_control_pb2.ProviderMessage(
        connection_id="connection-1",
        request_id="observe-request",
        generation=accepted.register_accepted.generation,
        command_completion=runtime_provider_control_pb2.ProviderCommandCompletion(
            request_id="observe-request",
            runtime_id="runtime-1",
            generation=accepted.register_accepted.generation,
            success=True,
            report=report,
            completed_at=_timestamp(_now()),
        ),
    )
    await inbound.put(completion)
    await inbound.put(completion)
    await asyncio.sleep(0)

    assert len(handler.reports) == 1
    assert handler.reports[0].reconciliation == RuntimeProviderReconciliationEvidence(
        observations=(
            RuntimeProviderReconciliationObservation(
                kind="network_policy",
                status=RuntimeProviderReconciliationStatus.DRIFTED,
                reason="network_policy_mismatch",
                diagnostic={},
            ),
        )
    )
    await _close_stream(stream)


@pytest.mark.asyncio
async def test_provider_grpc_rejects_missing_provider_credential() -> None:
    store = InMemoryRuntimeCoordinationStore()
    servicer = _servicer(RuntimeControlProtocolService(store), FakeReportSink())
    inbound = QueueIterator()
    await inbound.put(_register_message())

    stream = servicer.ConnectProvider(inbound, FakeGrpcContext(()))

    with pytest.raises(RuntimeError, match="UNAUTHENTICATED"):
        await anext(stream)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "metadata",
    (
        (("authorization", "Bearer provider-secret"),),
        (
            ("authorization", "Bearer provider-secret"),
            ("authorization", "Bearer provider-secret"),
            ("x-azents-runtime-provider-auth-method", "azents_issued_token"),
        ),
        (
            ("authorization", "Bearer provider-secret"),
            ("x-azents-runtime-provider-auth-method", "azents_issued_token"),
            ("x-azents-runtime-provider-auth-method", "azents_issued_token"),
        ),
        (
            ("authorization", "Bearer provider-secret"),
            ("x-azents-runtime-provider-auth-method", "unknown"),
        ),
    ),
)
async def test_provider_grpc_rejects_ambiguous_or_unknown_auth_metadata(
    metadata: tuple[tuple[str, str], ...],
) -> None:
    store = InMemoryRuntimeCoordinationStore()
    servicer = _servicer(RuntimeControlProtocolService(store), FakeReportSink())
    inbound = QueueIterator()
    await inbound.put(_register_message())

    stream = servicer.ConnectProvider(inbound, FakeGrpcContext(metadata))

    with pytest.raises(RuntimeError, match="UNAUTHENTICATED"):
        await anext(stream)


@pytest.mark.asyncio
async def test_provider_grpc_rejects_shared_control_token_fallback() -> None:
    store = InMemoryRuntimeCoordinationStore()
    servicer = _servicer(RuntimeControlProtocolService(store), FakeReportSink())
    inbound = QueueIterator()
    await inbound.put(_register_message())

    stream = servicer.ConnectProvider(
        inbound,
        FakeGrpcContext((("x-azents-runtime-control-token", "provider-secret"),)),
    )

    with pytest.raises(RuntimeError, match="UNAUTHENTICATED"):
        await anext(stream)


@pytest.mark.asyncio
async def test_provider_grpc_rejects_registration_provider_id_spoofing() -> None:
    store = InMemoryRuntimeCoordinationStore()
    servicer = _servicer(RuntimeControlProtocolService(store), FakeReportSink())
    inbound = QueueIterator()
    message = _register_message()
    message.register.provider_id = "provider-2"
    await inbound.put(message)

    stream = servicer.ConnectProvider(inbound, FakeGrpcContext())

    with pytest.raises(RuntimeError, match="PERMISSION_DENIED"):
        await anext(stream)


@pytest.mark.asyncio
async def test_provider_grpc_rejects_report_provider_id_spoofing() -> None:
    store = InMemoryRuntimeCoordinationStore()
    sink = FakeReportSink()
    servicer = _servicer(RuntimeControlProtocolService(store), sink)
    inbound = QueueIterator()
    await inbound.put(_register_message())
    report = _report_message()
    report.provider_id = "provider-2"
    await inbound.put(
        runtime_provider_control_pb2.ProviderMessage(
            connection_id="connection-1",
            request_id="report-1",
            generation=1,
            report=report,
        )
    )

    stream = servicer.ConnectProvider(inbound, FakeGrpcContext())
    await anext(stream)
    error = await anext(stream)
    await _close_stream(stream)

    assert error.error.code == "PROVIDER_IDENTITY_MISMATCH"
    assert sink.reports == []


@pytest.mark.asyncio
async def test_provider_grpc_accepts_provider_credential_metadata() -> None:
    store = InMemoryRuntimeCoordinationStore()
    servicer = _servicer(RuntimeControlProtocolService(store), FakeReportSink())
    inbound = QueueIterator()
    await inbound.put(_register_message())

    stream = servicer.ConnectProvider(
        inbound,
        FakeGrpcContext(
            grpc.aio.Metadata(
                ("authorization", "Bearer provider-secret"),
                ("x-azents-runtime-provider-auth-method", "azents_issued_token"),
            )
        ),
    )
    accepted = await anext(stream)
    await _close_stream(stream)

    assert accepted.register_accepted.provider_id == "provider-1"


@pytest.mark.asyncio
async def test_provider_grpc_rejects_kubernetes_v1_before_registration() -> None:
    """Kubernetes v1 does not receive a connection or command authority."""
    store = InMemoryRuntimeCoordinationStore()
    bridge = FakeProviderCredentialBridge(
        authentication=dataclasses.replace(
            FakeProviderCredentialBridge().authentication,
            provider_kind=RuntimeProviderKind.KUBERNETES,
        )
    )
    servicer = _servicer(
        RuntimeControlProtocolService(store),
        FakeReportSink(),
        bridge=bridge,
    )
    inbound = QueueIterator()
    await inbound.put(
        _register_message(
            provider_type="kubernetes",
            protocol_version="agent-runtime-provider-kubernetes-v1",
        )
    )

    stream = servicer.ConnectProvider(inbound, FakeGrpcContext())

    with pytest.raises(RuntimeError, match="FAILED_PRECONDITION"):
        await anext(stream)
    connection = await store.get_connection(
        kind=RuntimeConnectionKind.PROVIDER,
        subject_id="provider-1",
    )

    assert connection is None


@pytest.mark.asyncio
async def test_provider_grpc_accepts_kubernetes_v2_registration() -> None:
    """Kubernetes v2 receives Provider connection authority."""
    store = InMemoryRuntimeCoordinationStore()
    bridge = FakeProviderCredentialBridge(
        authentication=dataclasses.replace(
            FakeProviderCredentialBridge().authentication,
            provider_kind=RuntimeProviderKind.KUBERNETES,
        )
    )
    servicer = _servicer(
        RuntimeControlProtocolService(store),
        FakeReportSink(),
        bridge=bridge,
    )
    inbound = QueueIterator()
    await inbound.put(
        _register_message(
            provider_type="kubernetes",
            protocol_version="agent-runtime-provider-kubernetes-v2",
        )
    )

    stream = servicer.ConnectProvider(inbound, FakeGrpcContext())
    accepted = await anext(stream)
    await _close_stream(stream)

    assert accepted.register_accepted.provider_id == "provider-1"


@pytest.mark.asyncio
async def test_provider_grpc_persists_v3_registration_and_heartbeat_diagnostics() -> (
    None
):
    """V3 diagnostics are generation-fenced snapshots outside capability authority."""
    store = InMemoryRuntimeCoordinationStore()
    bridge = FakeProviderCredentialBridge(
        authentication=dataclasses.replace(
            FakeProviderCredentialBridge().authentication,
            provider_kind=RuntimeProviderKind.KUBERNETES,
        )
    )
    servicer = _servicer(
        RuntimeControlProtocolService(store),
        FakeReportSink(),
        bridge=bridge,
    )
    inbound = QueueIterator()
    register = _register_message(
        provider_type="kubernetes",
        protocol_version="agent-runtime-provider-kubernetes-v3",
    )
    register.register.operational_diagnostics.CopyFrom(
        _diagnostics_message(
            checked_at=_now(),
            code="cni_support_unconfirmed",
        )
    )
    await inbound.put(register)

    stream = servicer.ConnectProvider(inbound, FakeGrpcContext())
    accepted = await anext(stream)
    heartbeat = runtime_provider_control_pb2.ProviderHeartbeat(monotonic_sequence=1)
    heartbeat.operational_diagnostics.CopyFrom(
        _diagnostics_message(
            checked_at=_now() + timedelta(minutes=5),
            code="unexpected_network_policy",
        )
    )
    await inbound.put(
        runtime_provider_control_pb2.ProviderMessage(
            connection_id="connection-1",
            request_id="heartbeat-1",
            generation=accepted.register_accepted.generation,
            heartbeat=heartbeat,
        )
    )
    ack = await anext(stream)
    await _close_stream(stream)

    created = bridge.create_calls[0]["operational_diagnostics"]
    replaced = bridge.heartbeat_calls[0]["operational_diagnostics"]
    assert isinstance(created, RuntimeProviderOperationalDiagnostics)
    assert created.warnings[0].code == "cni_support_unconfirmed"
    assert isinstance(replaced, RuntimeProviderOperationalDiagnostics)
    assert replaced.warnings[0].code == "unexpected_network_policy"
    assert ack.heartbeat_ack.monotonic_sequence == 1


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("status", "acknowledgement_allowed"),
    [
        (None, False),
        ("drifted", False),
        ("in_sync", True),
    ],
)
async def test_provider_grpc_v3_enforcement_controls_configuration_acknowledgement(
    status: str | None,
    acknowledgement_allowed: bool,
) -> None:
    """Only aggregate in-sync v3 evidence can acknowledge configuration."""
    bridge = FakeProviderCredentialBridge(
        authentication=dataclasses.replace(
            FakeProviderCredentialBridge().authentication,
            provider_kind=RuntimeProviderKind.KUBERNETES,
        )
    )
    sink = FakeReportSink()
    inbound = QueueIterator()
    register = _register_message(
        provider_type="kubernetes",
        protocol_version="agent-runtime-provider-kubernetes-v3",
    )
    register.register.operational_diagnostics.CopyFrom(
        _diagnostics_message(
            checked_at=_now(),
            code="cni_support_unconfirmed",
        )
    )
    await inbound.put(register)
    stream = _servicer(
        RuntimeControlProtocolService(InMemoryRuntimeCoordinationStore()),
        sink,
        bridge=bridge,
    ).ConnectProvider(inbound, FakeGrpcContext())
    accepted = await anext(stream)
    report = _report_message()
    if status is not None:
        report.reconciliation.CopyFrom(
            runtime_provider_control_pb2.RuntimeProviderReconciliationEvidence(
                observations=[
                    runtime_provider_control_pb2.RuntimeProviderReconciliationObservation(
                        kind="network_enforcement",
                        status=status,
                        reason=f"network_enforcement_{status}",
                    )
                ]
            )
        )
    await inbound.put(
        runtime_provider_control_pb2.ProviderMessage(
            connection_id="connection-1",
            request_id="report-1",
            generation=accepted.register_accepted.generation,
            report=report,
        )
    )
    await asyncio.sleep(0)
    await _close_stream(stream)

    assert len(sink.reports) == 1
    assert sink.configuration_acknowledgements == [acknowledgement_allowed]


@pytest.mark.asyncio
@pytest.mark.parametrize("payload", ["registration", "heartbeat", "report"])
async def test_provider_grpc_rejects_kubernetes_payloads_from_docker(
    payload: str,
) -> None:
    """Docker cannot submit Kubernetes diagnostics or reconciliation evidence."""
    sink = FakeReportSink()
    inbound = QueueIterator()
    register = _register_message()
    if payload == "registration":
        register.register.operational_diagnostics.CopyFrom(
            _diagnostics_message(
                checked_at=_now(),
                code="cni_support_unconfirmed",
            )
        )
    await inbound.put(register)
    stream = _servicer(
        RuntimeControlProtocolService(InMemoryRuntimeCoordinationStore()),
        sink,
    ).ConnectProvider(inbound, FakeGrpcContext())
    if payload == "registration":
        with pytest.raises(RuntimeError, match="FAILED_PRECONDITION"):
            await anext(stream)
        return
    accepted = await anext(stream)
    if payload == "heartbeat":
        heartbeat = runtime_provider_control_pb2.ProviderHeartbeat(monotonic_sequence=1)
        heartbeat.operational_diagnostics.CopyFrom(
            _diagnostics_message(
                checked_at=_now(),
                code="cni_support_unconfirmed",
            )
        )
        message = runtime_provider_control_pb2.ProviderMessage(
            connection_id="connection-1",
            request_id="heartbeat-1",
            generation=accepted.register_accepted.generation,
            heartbeat=heartbeat,
        )
        expected_code = "INVALID_PROVIDER_DIAGNOSTICS"
    else:
        report = _report_message()
        report.reconciliation.CopyFrom(
            runtime_provider_control_pb2.RuntimeProviderReconciliationEvidence(
                observations=[
                    runtime_provider_control_pb2.RuntimeProviderReconciliationObservation(
                        kind="network_policy",
                        status="in_sync",
                        reason="network_policy_in_sync",
                    )
                ]
            )
        )
        message = runtime_provider_control_pb2.ProviderMessage(
            connection_id="connection-1",
            request_id="report-1",
            generation=accepted.register_accepted.generation,
            report=report,
        )
        expected_code = "INVALID_PROVIDER_REPORT"
    await inbound.put(message)
    error = await anext(stream)
    await _close_stream(stream)

    assert error.error.code == expected_code
    assert sink.reports == []


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("protocol_version", "kind"),
    [
        ("agent-runtime-provider-kubernetes-v2", "network_enforcement"),
        ("agent-runtime-provider-kubernetes-v3", "network_policy"),
    ],
)
async def test_provider_grpc_rejects_protocol_mismatched_reconciliation(
    protocol_version: str,
    kind: str,
) -> None:
    """V2 and v3 evidence cannot cross-authorize one another."""
    store = InMemoryRuntimeCoordinationStore()
    bridge = FakeProviderCredentialBridge(
        authentication=dataclasses.replace(
            FakeProviderCredentialBridge().authentication,
            provider_kind=RuntimeProviderKind.KUBERNETES,
        )
    )
    sink = FakeReportSink()
    servicer = _servicer(
        RuntimeControlProtocolService(store),
        sink,
        bridge=bridge,
    )
    inbound = QueueIterator()
    register = _register_message(
        provider_type="kubernetes",
        protocol_version=protocol_version,
    )
    if protocol_version.endswith("-v3"):
        register.register.operational_diagnostics.CopyFrom(
            _diagnostics_message(
                checked_at=_now(),
                code="cni_support_unconfirmed",
            )
        )
    await inbound.put(register)

    stream = servicer.ConnectProvider(inbound, FakeGrpcContext())
    accepted = await anext(stream)
    report = _report_message()
    report.reconciliation.CopyFrom(
        runtime_provider_control_pb2.RuntimeProviderReconciliationEvidence(
            observations=[
                runtime_provider_control_pb2.RuntimeProviderReconciliationObservation(
                    kind=kind,
                    status="drifted",
                    reason="network_enforcement_mismatch",
                )
            ]
        )
    )
    await inbound.put(
        runtime_provider_control_pb2.ProviderMessage(
            connection_id="connection-1",
            request_id="report-1",
            generation=accepted.register_accepted.generation,
            report=report,
        )
    )
    error = await anext(stream)
    await _close_stream(stream)

    assert error.error.code == "INVALID_PROVIDER_REPORT"
    assert sink.reports == []


def _servicer(
    service: RuntimeControlProtocolService,
    sink: FakeReportSink,
    *,
    bridge: FakeProviderCredentialBridge | None = None,
    observe_completion_handler: FakeObserveCompletionHandler | None = None,
) -> RuntimeProviderControlGrpcServicer:
    bridge = bridge or FakeProviderCredentialBridge()
    return RuntimeProviderControlGrpcServicer(
        control_protocol=service,
        report_sink=sink,
        observe_completion_handler=(
            observe_completion_handler or FakeObserveCompletionHandler()
        ),
        owner_replica_id="control-a",
        consumer_id="provider-consumer-a",
        credential_authenticator=bridge,
        connection_tracker=bridge,
        contract_proposer=FakeRuntimeProviderContractProposer(),
        runner_credential_issuer=FakeRuntimeRunnerCredentialIssuer(),
        command_block_ms=1,
    )


def _provider_command(
    *,
    generation: int,
    command_type: RuntimeProviderCommandType,
) -> RuntimeProviderCommand:
    return RuntimeProviderCommand(
        provider_id="provider-1",
        provider_generation=generation,
        runtime_id="runtime-1",
        desired_generation=5,
        command_type=command_type,
        reset_final_desired_state=None,
        payload={
            "identity": {
                "agent_id": "agent-1",
                "workspace_id": "workspace-1",
            },
            "runner_image": "runner:latest",
            "auth": {
                "control_endpoint": "runtime-control:8020",
                "transfer_endpoint": "runtime-transfer:8030",
                "runner_auth_credential_id": "runner-credential-1",
            },
        },
        deadline_at=datetime.now(UTC) + timedelta(seconds=30),
        runtime_configuration=_runtime_configuration(),
    )


def _register_message(
    connection_id: str = "connection-1",
    *,
    provider_type: str = "docker",
    protocol_version: str = "agent-runtime-provider.v1",
) -> runtime_provider_control_pb2.ProviderMessage:
    return runtime_provider_control_pb2.ProviderMessage(
        connection_id=connection_id,
        request_id="register",
        register=runtime_provider_control_pb2.ProviderRegister(
            provider_id="provider-1",
            provider_type=provider_type,
            scope="system",
            protocol_version=protocol_version,
            capabilities=("lifecycle", "observe"),
            config_schema_version="v1",
            auth_credential_id="credential-1",
            capability_contract=struct_pb2.Struct(
                fields={
                    "schema_version": struct_pb2.Value(number_value=1),
                }
            ),
        ),
    )


def _report_message() -> runtime_provider_control_pb2.RuntimeProviderReport:
    return runtime_provider_control_pb2.RuntimeProviderReport(
        runtime_id="runtime-1",
        provider_id="provider-1",
        provider_generation=1,
        observed_state="running",
        observed_desired_generation=5,
        provider_runtime_id="provider-runtime-1",
        reason="container_running",
        reported_at=_timestamp(_now()),
        runtime_configuration=_runtime_configuration_evidence_message(),
    )


def _runtime_configuration() -> RuntimeConfigurationEnvelope:
    return RuntimeConfigurationEnvelope(
        evidence=RuntimeConfigurationEvidence(
            configuration_sequence=1,
            digest="d" * 64,
            desired_generation=5,
        ),
        resolved_configuration_json=canonical_runtime_configuration_json(
            _runtime_configuration_document()
        ),
    )


def _runtime_configuration_evidence_message() -> (
    runtime_configuration_pb2.RuntimeConfigurationEvidence
):
    evidence = _runtime_configuration().evidence
    return runtime_configuration_pb2.RuntimeConfigurationEvidence(
        configuration_sequence=str(evidence.configuration_sequence),
        digest=evidence.digest,
        desired_generation=evidence.desired_generation,
    )


def _runtime_configuration_document() -> dict[str, JsonValue]:
    return {
        "schema_version": 1,
        "provider": {
            "id": "provider-resource-1",
            "logical_id": "provider-1",
            "kind": "docker",
            "capability_revision_id": "capability-1",
            "capability_digest": "a" * 64,
        },
        "infrastructure_profile": {
            "id": "infrastructure-1",
            "version": 1,
            "digest": "b" * 64,
        },
        "workspace_runtime_profile": {
            "id": "workspace-profile-1",
            "version": 1,
            "digest": "c" * 64,
        },
        "effective_profile": {
            "profile_kind": "docker_container",
            "contract_family": "docker.container-profile",
            "schema_version": 1,
            "runner_resources": {
                "cpu_reservation_millicores": None,
                "cpu_limit_millicores": None,
                "memory_reservation_bytes": None,
                "memory_limit_bytes": None,
            },
            "network_name": None,
        },
    }


def _timestamp(value: datetime) -> timestamp_pb2.Timestamp:
    timestamp = timestamp_pb2.Timestamp()
    timestamp.FromDatetime(value)
    return timestamp


def _diagnostics_message(
    *,
    checked_at: datetime,
    code: str,
) -> runtime_provider_control_pb2.ProviderOperationalDiagnostics:
    return runtime_provider_control_pb2.ProviderOperationalDiagnostics(
        checked_at=_timestamp(checked_at),
        warnings=[
            runtime_provider_control_pb2.ProviderOperationalWarning(
                code=code,
                severity="warning",
                metadata=_diagnostics_metadata(code),
            )
        ],
    )


def _diagnostics_metadata(code: str) -> dict[str, str]:
    if code == "unexpected_network_policy":
        return {"policy_count": "1"}
    return {"reason": "api_discovery_unavailable"}


def _now() -> datetime:
    return datetime(2026, 5, 25, tzinfo=UTC)
