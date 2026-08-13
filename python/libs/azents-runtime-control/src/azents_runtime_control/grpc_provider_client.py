"""gRPC Provider Control client for external Runtime Providers."""

import asyncio
import contextlib
from collections.abc import AsyncIterable, AsyncIterator, Mapping, Sequence
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Protocol, cast

import grpc
from google.protobuf import json_format, struct_pb2, timestamp_pb2

from azents_runtime_control.grpc_tls import (
    GrpcClientTlsConfig,
    create_grpc_aio_channel,
)
from azents_runtime_control.proto import (
    runtime_configuration_pb2,
    runtime_provider_control_pb2,
)
from azents_runtime_control.provider import (
    JsonValue,
    ProviderCommandCompletion,
    ProviderCommandEnvelope,
    ProviderControlClient,
    ProviderRegistration,
    ProviderRegistrationAccepted,
    RuntimeContainerAuth,
    RuntimeDesiredState,
    RuntimeIdentity,
    RuntimeLifecycleCommand,
    RuntimeLifecycleCommandType,
    RuntimeProviderObservedState,
    RuntimeProviderOperationalDiagnostics,
    RuntimeProviderOperationalWarning,
    RuntimeProviderOperationalWarningSeverity,
    RuntimeProviderReconciliationEvidence,
    RuntimeProviderReconciliationObservation,
    RuntimeProviderReconciliationStatus,
    RuntimeProviderReport,
)
from azents_runtime_control.runtime_configuration import (
    RuntimeConfigurationEnvelope,
    RuntimeConfigurationEvidence,
    parse_configuration_sequence,
    serialize_configuration_sequence,
)

if TYPE_CHECKING:
    from azents_runtime_control.proto.runtime_provider_control_pb2_grpc import (
        RuntimeProviderControlAsyncStub as _RuntimeProviderControlStub,
    )
else:
    from azents_runtime_control.proto.runtime_provider_control_pb2_grpc import (
        RuntimeProviderControlStub as _RuntimeProviderControlStub,
    )


class ProviderControlStream(Protocol):
    """Callable gRPC stream constructor."""

    def __call__(
        self,
        request_iterator: AsyncIterator[runtime_provider_control_pb2.ProviderMessage],
        /,
        *,
        metadata: Sequence[tuple[str, str]] | None = None,
    ) -> AsyncIterable[runtime_provider_control_pb2.ControlMessage]:
        """Open a bidirectional Runtime Control stream."""
        ...


class RuntimeProviderControlStreamClosed(RuntimeError):
    """Provider Control gRPC stream closed before the requested operation finished."""


PROVIDER_AUTH_METHOD_AZENTS_ISSUED_TOKEN = "azents_issued_token"
PROVIDER_AUTH_METHOD_KUBERNETES_SERVICE_ACCOUNT = "kubernetes_service_account"
_PROVIDER_AUTH_METHOD_HEADER = "x-azents-runtime-provider-auth-method"


class GrpcProviderControlClient(ProviderControlClient):
    """ProviderControlClient implementation backed by a bidirectional gRPC stream."""

    def __init__(
        self,
        stream: ProviderControlStream,
        *,
        channel: grpc.aio.Channel | None = None,
        heartbeat_ack_timeout_seconds: float = 10.0,
        provider_credential: str,
        provider_auth_method: str,
    ) -> None:
        """Initialize the gRPC client with a stream callable."""
        self._stream = stream
        self._channel = channel
        self._heartbeat_ack_timeout_seconds = heartbeat_ack_timeout_seconds
        self._metadata = _provider_credential_metadata(
            provider_credential,
            provider_auth_method,
        )
        self._outbound: asyncio.Queue[runtime_provider_control_pb2.ProviderMessage] = (
            asyncio.Queue()
        )
        self._commands: asyncio.Queue[ProviderCommandEnvelope] = asyncio.Queue()
        self._pending_heartbeat_acks: dict[str, asyncio.Future[bool]] = {}
        self._runtime_by_request_id: dict[str, str] = {}
        self._accepted: asyncio.Future[ProviderRegistrationAccepted] | None = None
        self._receiver_task: asyncio.Task[None] | None = None
        self._connection_id: str | None = None
        self._heartbeat_sequence = 0

    @classmethod
    def from_endpoint(
        cls,
        endpoint: str,
        *,
        heartbeat_ack_timeout_seconds: float = 10.0,
        provider_credential: str,
        provider_auth_method: str,
        tls: GrpcClientTlsConfig | None,
        allow_insecure: bool,
    ) -> "GrpcProviderControlClient":
        """Create a client using authenticated TLS or explicit insecure mode."""
        channel = create_grpc_aio_channel(
            endpoint,
            tls=tls,
            allow_insecure=allow_insecure,
        )
        stub = _RuntimeProviderControlStub(channel)
        return cls(
            stub.ConnectProvider,
            channel=channel,
            heartbeat_ack_timeout_seconds=heartbeat_ack_timeout_seconds,
            provider_credential=provider_credential,
            provider_auth_method=provider_auth_method,
        )

    async def register_provider(
        self,
        registration: ProviderRegistration,
        *,
        connection_id: str,
        registered_at: datetime,
    ) -> ProviderRegistrationAccepted:
        """Open the stream, send Provider registration, and wait for acceptance."""
        if self._accepted is not None:
            raise RuntimeError("Provider Control stream is already registered")
        self._connection_id = connection_id
        self._accepted = asyncio.get_running_loop().create_future()
        outbound = self._outbound_messages(
            _register_message(
                registration,
                connection_id=connection_id,
                request_id="register",
            )
        )
        responses = self._stream(outbound, metadata=self._metadata)
        self._receiver_task = asyncio.create_task(self._receive(responses))
        return await self._accepted

    async def heartbeat_provider(
        self,
        *,
        provider_id: str,
        generation: int,
        heartbeat_at: datetime,
        operational_diagnostics: RuntimeProviderOperationalDiagnostics | None,
    ) -> bool:
        """Send a heartbeat and wait for the matching ack."""
        self._heartbeat_sequence += 1
        request_id = f"heartbeat:{self._heartbeat_sequence}"
        future = asyncio.get_running_loop().create_future()
        self._pending_heartbeat_acks[request_id] = future
        heartbeat = runtime_provider_control_pb2.ProviderHeartbeat(
            monotonic_sequence=self._heartbeat_sequence,
        )
        if operational_diagnostics is not None:
            heartbeat.operational_diagnostics.CopyFrom(
                _operational_diagnostics_message(operational_diagnostics)
            )
        await self._send(
            runtime_provider_control_pb2.ProviderMessage(
                connection_id=self._require_connection_id(),
                request_id=request_id,
                generation=generation,
                heartbeat=heartbeat,
            )
        )
        try:
            return await asyncio.wait_for(
                future,
                timeout=self._heartbeat_ack_timeout_seconds,
            )
        finally:
            self._pending_heartbeat_acks.pop(request_id, None)

    async def report_provider_state(self, report: RuntimeProviderReport) -> None:
        """Publish one Provider observed-state report."""
        await self._send(
            runtime_provider_control_pb2.ProviderMessage(
                connection_id=self._require_connection_id(),
                request_id=f"report:{report.runtime_id}:{report.provider_generation}",
                generation=report.provider_generation,
                report=_report_message(report),
            )
        )

    async def claim_next_provider_command(
        self,
        *,
        provider_id: str,
        generation: int,
        consumer_id: str,
        block_ms: int,
    ) -> ProviderCommandEnvelope | None:
        """Wait for the next Provider command from the stream."""
        del provider_id, generation, consumer_id
        if block_ms <= 0:
            try:
                return self._commands.get_nowait()
            except asyncio.QueueEmpty:
                return None
        try:
            return await asyncio.wait_for(
                self._commands.get(),
                timeout=block_ms / 1000,
            )
        except TimeoutError:
            return None

    async def complete_provider_command(
        self,
        completion: ProviderCommandCompletion,
    ) -> None:
        """Complete a claimed Provider command."""
        runtime_id = self._runtime_by_request_id.pop(completion.request_id, None)
        if runtime_id is None and completion.report is not None:
            runtime_id = completion.report.runtime_id
        await self._send(
            runtime_provider_control_pb2.ProviderMessage(
                connection_id=self._require_connection_id(),
                request_id=completion.request_id,
                generation=completion.generation,
                command_completion=_completion_message(
                    completion,
                    runtime_id=runtime_id or "",
                ),
            )
        )

    async def close(self) -> None:
        """Close receiver task resources."""
        if self._receiver_task is not None:
            self._receiver_task.cancel()
            with contextlib.suppress(
                asyncio.CancelledError,
                RuntimeProviderControlStreamClosed,
                grpc.aio.AioRpcError,
            ):
                await self._receiver_task
            self._receiver_task = None
        if self._channel is not None:
            await self._channel.close()
            self._channel = None

    async def _send(
        self,
        message: runtime_provider_control_pb2.ProviderMessage,
    ) -> None:
        if self._receiver_task is not None and self._receiver_task.done():
            raise RuntimeProviderControlStreamClosed(
                "Provider Control stream is closed"
            )
        await self._outbound.put(message)

    async def _outbound_messages(
        self,
        register: runtime_provider_control_pb2.ProviderMessage,
    ) -> AsyncIterator[runtime_provider_control_pb2.ProviderMessage]:
        yield register
        while True:
            yield await self._outbound.get()

    async def _receive(
        self,
        responses: AsyncIterable[runtime_provider_control_pb2.ControlMessage],
    ) -> None:
        try:
            async for message in responses:
                await self._handle_control_message(message)
            self._fail_pending(RuntimeProviderControlStreamClosed("stream closed"))
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            self._fail_pending(exc)
            raise

    async def _handle_control_message(
        self,
        message: runtime_provider_control_pb2.ControlMessage,
    ) -> None:
        payload = message.WhichOneof("payload")
        if payload == "register_accepted":
            accepted = _accepted(message.register_accepted)
            if self._accepted is not None and not self._accepted.done():
                self._accepted.set_result(accepted)
            return
        if payload == "heartbeat_ack":
            future = self._pending_heartbeat_acks.get(message.request_id)
            if future is not None and not future.done():
                future.set_result(True)
            return
        if payload == "provider_command":
            command = _command(message.provider_command)
            self._runtime_by_request_id[message.request_id] = (
                command.identity.runtime_id
            )
            await self._commands.put(
                ProviderCommandEnvelope(
                    request_id=message.request_id,
                    command=command,
                    deadline_at=_optional_datetime(message.provider_command),
                )
            )
            return
        if payload == "error":
            raise RuntimeProviderControlStreamClosed(message.error.message)

    def _fail_pending(self, exc: Exception) -> None:
        if self._accepted is not None and not self._accepted.done():
            self._accepted.set_exception(exc)
        for future in self._pending_heartbeat_acks.values():
            if not future.done():
                future.set_exception(exc)

    def _require_connection_id(self) -> str:
        if self._connection_id is None:
            raise RuntimeError("Provider Control stream is not registered")
        return self._connection_id


def _provider_credential_metadata(
    provider_credential: str,
    provider_auth_method: str,
) -> tuple[tuple[str, str], ...]:
    """Create required Provider credential metadata for Control."""
    credential = provider_credential.strip()
    if not credential:
        raise ValueError("provider_credential must not be empty")
    method = provider_auth_method.strip()
    if not method:
        raise ValueError("provider_auth_method must not be empty")
    return (
        ("authorization", f"Bearer {credential}"),
        (_PROVIDER_AUTH_METHOD_HEADER, method),
    )


def _register_message(
    registration: ProviderRegistration,
    *,
    connection_id: str,
    request_id: str,
) -> runtime_provider_control_pb2.ProviderMessage:
    register = runtime_provider_control_pb2.ProviderRegister(
        provider_id=registration.provider_id,
        provider_type=registration.provider_type,
        scope=registration.scope,
        workspace_id=registration.workspace_id or "",
        protocol_version=registration.protocol_version,
        capabilities=list(registration.capabilities),
        config_schema_version=registration.config_schema_version,
        metadata=_struct(registration.metadata),
        capability_contract=_struct(registration.capability_contract),
    )
    if registration.operational_diagnostics is not None:
        register.operational_diagnostics.CopyFrom(
            _operational_diagnostics_message(registration.operational_diagnostics)
        )
    return runtime_provider_control_pb2.ProviderMessage(
        connection_id=connection_id,
        request_id=request_id,
        register=register,
    )


def _accepted(
    message: runtime_provider_control_pb2.ProviderRegisterAccepted,
) -> ProviderRegistrationAccepted:
    return ProviderRegistrationAccepted(
        provider_id=message.provider_id,
        connection_id=message.connection_id,
        generation=message.generation,
        heartbeat_interval_seconds=message.heartbeat_interval_seconds,
    )


def _command(
    message: runtime_provider_control_pb2.ProviderCommand,
) -> RuntimeLifecycleCommand:
    if not message.HasField("runtime_configuration"):
        raise ValueError("Runtime configuration envelope is required.")
    payload = json_value_from_struct(message.payload)
    return RuntimeLifecycleCommand(
        command_type=RuntimeLifecycleCommandType(message.command_type),
        identity=RuntimeIdentity(
            runtime_id=message.runtime_id,
            agent_id=message.agent_id,
            workspace_id=message.workspace_id,
        ),
        desired_generation=message.desired_generation,
        provider_generation=message.provider_generation,
        runner_image=message.runner_image,
        auth=RuntimeContainerAuth(
            control_endpoint=message.control_endpoint,
            transfer_endpoint=_required_transfer_endpoint(message.transfer_endpoint),
            runner_auth_token=message.runner_auth_token,
            runner_auth_credential_id=_required_runner_auth_credential_id(payload),
            control_tls_ca_pem=_optional_control_tls_ca_pem(payload),
            allow_insecure_control=_allow_insecure_control(payload),
        ),
        reset_final_desired_state=_optional_desired_state(
            message.reset_final_desired_state
        ),
        runtime_configuration=_runtime_configuration_envelope(
            message.runtime_configuration
        ),
    )


def _optional_desired_state(value: str) -> RuntimeDesiredState | None:
    if not value:
        return None
    return RuntimeDesiredState(value)


def _required_runner_auth_credential_id(payload: dict[str, JsonValue]) -> str:
    auth = payload.get("auth")
    if not isinstance(auth, dict):
        raise ValueError("runner_auth_credential_id is required")
    credential_id = auth.get("runner_auth_credential_id")
    if not isinstance(credential_id, str):
        raise ValueError("runner_auth_credential_id is required")
    normalized = credential_id.strip()
    if not normalized:
        raise ValueError("runner_auth_credential_id is required")
    return normalized


def _required_transfer_endpoint(value: str) -> str:
    normalized = value.strip()
    if not normalized:
        raise ValueError("transfer_endpoint is required")
    return normalized


def _optional_control_tls_ca_pem(payload: dict[str, JsonValue]) -> str | None:
    auth = payload.get("auth")
    if not isinstance(auth, dict):
        return None
    value = auth.get("control_tls_ca_pem")
    if not isinstance(value, str):
        return None
    normalized = value.strip()
    return normalized or None


def _allow_insecure_control(payload: dict[str, JsonValue]) -> bool:
    auth = payload.get("auth")
    if not isinstance(auth, dict):
        return False
    value = auth.get("allow_insecure_control")
    return value if isinstance(value, bool) else False


def _report_message(
    report: RuntimeProviderReport,
) -> runtime_provider_control_pb2.RuntimeProviderReport:
    message = runtime_provider_control_pb2.RuntimeProviderReport(
        runtime_id=report.runtime_id,
        provider_id=report.provider_id,
        provider_generation=report.provider_generation,
        observed_state=report.observed_state.value,
        observed_desired_generation=report.observed_desired_generation,
        provider_runtime_id=report.provider_runtime_id or "",
        reason=report.reason,
        diagnostic=dict(report.diagnostic),
        reported_at=_timestamp(report.reported_at),
        terminal_delete_acknowledged=report.terminal_delete_acknowledged,
    )
    message.runtime_configuration.CopyFrom(
        _runtime_configuration_evidence_message(report.runtime_configuration)
    )
    if report.reconciliation is not None:
        message.reconciliation.CopyFrom(
            _reconciliation_evidence_message(report.reconciliation)
        )
    return message


def _completion_message(
    completion: ProviderCommandCompletion,
    *,
    runtime_id: str,
) -> runtime_provider_control_pb2.ProviderCommandCompletion:
    message = runtime_provider_control_pb2.ProviderCommandCompletion(
        request_id=completion.request_id,
        runtime_id=runtime_id,
        generation=completion.generation,
        success=completion.success,
        error_code=completion.error_code or "",
        error_message=completion.error_message or "",
        completed_at=_timestamp(completion.completed_at),
    )
    if completion.report is not None:
        message.report.CopyFrom(_report_message(completion.report))
    return message


def provider_report_from_message(
    message: runtime_provider_control_pb2.RuntimeProviderReport,
) -> RuntimeProviderReport:
    if not message.HasField("runtime_configuration"):
        raise ValueError("Runtime Provider configuration evidence is required.")
    return RuntimeProviderReport(
        runtime_id=message.runtime_id,
        provider_id=message.provider_id,
        provider_generation=message.provider_generation,
        observed_state=RuntimeProviderObservedState(message.observed_state),
        observed_desired_generation=message.observed_desired_generation,
        provider_runtime_id=message.provider_runtime_id or None,
        reason=message.reason,
        diagnostic=dict(message.diagnostic),
        reported_at=_datetime(message.reported_at),
        terminal_delete_acknowledged=message.terminal_delete_acknowledged,
        runtime_configuration=_runtime_configuration_evidence(
            message.runtime_configuration
        ),
        reconciliation=(
            _reconciliation_evidence(message.reconciliation)
            if message.HasField("reconciliation")
            else None
        ),
    )


def _runtime_configuration_envelope(
    message: runtime_configuration_pb2.RuntimeConfigurationEnvelope,
) -> RuntimeConfigurationEnvelope:
    return RuntimeConfigurationEnvelope(
        evidence=_runtime_configuration_evidence(message.evidence),
        resolved_configuration_json=message.resolved_configuration_json,
    )


def _runtime_configuration_evidence(
    message: runtime_configuration_pb2.RuntimeConfigurationEvidence,
) -> RuntimeConfigurationEvidence:
    return RuntimeConfigurationEvidence(
        configuration_sequence=parse_configuration_sequence(
            message.configuration_sequence
        ),
        digest=message.digest,
        desired_generation=message.desired_generation,
    )


def _runtime_configuration_evidence_message(
    evidence: RuntimeConfigurationEvidence,
) -> runtime_configuration_pb2.RuntimeConfigurationEvidence:
    return runtime_configuration_pb2.RuntimeConfigurationEvidence(
        configuration_sequence=serialize_configuration_sequence(
            evidence.configuration_sequence
        ),
        digest=evidence.digest,
        desired_generation=evidence.desired_generation,
    )


def _reconciliation_evidence(
    message: runtime_provider_control_pb2.RuntimeProviderReconciliationEvidence,
) -> RuntimeProviderReconciliationEvidence:
    return RuntimeProviderReconciliationEvidence(
        observations=tuple(
            RuntimeProviderReconciliationObservation(
                kind=observation.kind,
                status=RuntimeProviderReconciliationStatus(observation.status),
                reason=observation.reason,
                diagnostic=dict(observation.diagnostic),
            )
            for observation in message.observations
        )
    )


def _reconciliation_evidence_message(
    evidence: RuntimeProviderReconciliationEvidence,
) -> runtime_provider_control_pb2.RuntimeProviderReconciliationEvidence:
    return runtime_provider_control_pb2.RuntimeProviderReconciliationEvidence(
        observations=[
            runtime_provider_control_pb2.RuntimeProviderReconciliationObservation(
                kind=observation.kind,
                status=observation.status.value,
                reason=observation.reason,
                diagnostic=dict(observation.diagnostic),
            )
            for observation in evidence.observations
        ]
    )


def operational_diagnostics_from_message(
    message: runtime_provider_control_pb2.ProviderOperationalDiagnostics,
) -> RuntimeProviderOperationalDiagnostics:
    """Decode one bounded warning-only Provider diagnostics snapshot."""
    if not message.HasField("checked_at"):
        raise ValueError("operational diagnostics checked_at is required")
    return RuntimeProviderOperationalDiagnostics(
        checked_at=_datetime(message.checked_at),
        warnings=tuple(
            RuntimeProviderOperationalWarning(
                code=warning.code,
                severity=RuntimeProviderOperationalWarningSeverity(warning.severity),
                metadata=dict(warning.metadata),
            )
            for warning in message.warnings
        ),
    )


def _operational_diagnostics_message(
    diagnostics: RuntimeProviderOperationalDiagnostics,
) -> runtime_provider_control_pb2.ProviderOperationalDiagnostics:
    return runtime_provider_control_pb2.ProviderOperationalDiagnostics(
        checked_at=_timestamp(diagnostics.checked_at),
        warnings=[
            runtime_provider_control_pb2.ProviderOperationalWarning(
                code=warning.code,
                severity=warning.severity.value,
                metadata=dict(warning.metadata),
            )
            for warning in diagnostics.warnings
        ],
    )


def _struct(metadata: Mapping[str, JsonValue]) -> struct_pb2.Struct:
    struct = struct_pb2.Struct()
    struct.update(metadata)
    return struct


def json_value_from_struct(struct: struct_pb2.Struct) -> dict[str, JsonValue]:
    return cast(dict[str, JsonValue], json_format.MessageToDict(struct))


def _timestamp(value: datetime) -> timestamp_pb2.Timestamp:
    timestamp = timestamp_pb2.Timestamp()
    timestamp.FromDatetime(value.astimezone(UTC))
    return timestamp


def _datetime(value: timestamp_pb2.Timestamp) -> datetime:
    return value.ToDatetime(tzinfo=UTC)


def _optional_datetime(
    message: runtime_provider_control_pb2.ProviderCommand,
) -> datetime | None:
    if not message.HasField("deadline_at"):
        return None
    return _datetime(message.deadline_at)


__all__ = [
    "GrpcProviderControlClient",
    "ProviderControlStream",
    "RuntimeProviderControlStreamClosed",
    "json_value_from_struct",
    "operational_diagnostics_from_message",
    "provider_report_from_message",
]
