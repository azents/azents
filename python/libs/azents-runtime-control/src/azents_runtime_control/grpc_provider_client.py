"""gRPC Provider Control client for external Runtime Providers."""

# pyright: reportAttributeAccessIssue=false, reportArgumentType=false
# protobuf generated modules expose dynamic message attributes.

import asyncio
import contextlib
from collections.abc import AsyncIterator, Sequence
from datetime import UTC, datetime
from typing import Protocol, cast

import grpc
from google.protobuf import json_format, struct_pb2, timestamp_pb2

from azents_runtime_control.proto import (
    runtime_provider_control_pb2,
    runtime_provider_control_pb2_grpc,
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
    RuntimeProviderReport,
)


class ProviderControlStream(Protocol):
    """Callable gRPC stream constructor."""

    def __call__(
        self,
        request_iterator: AsyncIterator[runtime_provider_control_pb2.ProviderMessage],
        /,
        *,
        metadata: Sequence[tuple[str, str]] | None = None,
    ) -> AsyncIterator[runtime_provider_control_pb2.ControlMessage]:
        """Open a bidirectional Runtime Control stream."""
        ...


class RuntimeProviderControlStreamClosed(RuntimeError):
    """Provider Control gRPC stream closed before the requested operation finished."""


class GrpcProviderControlClient(ProviderControlClient):
    """ProviderControlClient implementation backed by a bidirectional gRPC stream."""

    def __init__(
        self,
        stream: ProviderControlStream,
        *,
        channel: grpc.aio.Channel | None = None,
        heartbeat_ack_timeout_seconds: float = 10.0,
        control_auth_token: str | None = None,
    ) -> None:
        """Initialize the gRPC client with a stream callable."""
        self._stream = stream
        self._channel = channel
        self._heartbeat_ack_timeout_seconds = heartbeat_ack_timeout_seconds
        self._metadata = _auth_metadata(control_auth_token)
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
        control_auth_token: str | None = None,
    ) -> "GrpcProviderControlClient":
        """Create a client using an insecure gRPC channel."""
        channel = grpc.aio.insecure_channel(endpoint)
        stub = runtime_provider_control_pb2_grpc.RuntimeProviderControlStub(channel)
        return cls(
            stub.ConnectProvider,
            channel=channel,
            heartbeat_ack_timeout_seconds=heartbeat_ack_timeout_seconds,
            control_auth_token=control_auth_token,
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
        if self._metadata is None:
            responses = self._stream(outbound)
        else:
            responses = self._stream(outbound, metadata=self._metadata)
        self._receiver_task = asyncio.create_task(self._receive(responses))
        return await self._accepted

    async def heartbeat_provider(
        self,
        *,
        provider_id: str,
        generation: int,
        heartbeat_at: datetime,
    ) -> bool:
        """Send a heartbeat and wait for the matching ack."""
        self._heartbeat_sequence += 1
        request_id = f"heartbeat:{self._heartbeat_sequence}"
        future = asyncio.get_running_loop().create_future()
        self._pending_heartbeat_acks[request_id] = future
        await self._send(
            runtime_provider_control_pb2.ProviderMessage(
                connection_id=self._require_connection_id(),
                request_id=request_id,
                generation=generation,
                heartbeat=runtime_provider_control_pb2.ProviderHeartbeat(
                    monotonic_sequence=self._heartbeat_sequence,
                ),
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
        responses: AsyncIterator[runtime_provider_control_pb2.ControlMessage],
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
                    deadline_at=_optional_datetime(
                        message.provider_command,
                        "deadline_at",
                    ),
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


def _auth_metadata(token: str | None) -> tuple[tuple[str, str], ...] | None:
    if token is None or not token:
        return None
    return (("authorization", f"Bearer {token}"),)


def _register_message(
    registration: ProviderRegistration,
    *,
    connection_id: str,
    request_id: str,
) -> runtime_provider_control_pb2.ProviderMessage:
    return runtime_provider_control_pb2.ProviderMessage(
        connection_id=connection_id,
        request_id=request_id,
        register=runtime_provider_control_pb2.ProviderRegister(
            provider_id=registration.provider_id,
            provider_type=registration.provider_type,
            scope=registration.scope,
            workspace_id=registration.workspace_id or "",
            protocol_version=registration.protocol_version,
            capabilities=list(registration.capabilities),
            config_schema_version=registration.config_schema_version,
            metadata=_struct(registration.metadata),
            auth_credential_id=registration.auth_credential_id,
        ),
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
            runner_auth_token=message.runner_auth_token,
            control_token=_optional_control_token(payload),
        ),
        reset_final_desired_state=_optional_desired_state(
            message.reset_final_desired_state
        ),
    )


def _optional_desired_state(value: str) -> RuntimeDesiredState | None:
    if not value:
        return None
    return RuntimeDesiredState(value)


def _optional_control_token(payload: dict[str, JsonValue]) -> str | None:
    auth = payload.get("auth")
    if not isinstance(auth, dict):
        return None
    token = auth.get("control_token")
    if not isinstance(token, str):
        return None
    normalized = token.strip()
    return normalized or None


def _report_message(
    report: RuntimeProviderReport,
) -> runtime_provider_control_pb2.RuntimeProviderReport:
    return runtime_provider_control_pb2.RuntimeProviderReport(
        runtime_id=report.runtime_id,
        provider_id=report.provider_id,
        provider_generation=report.provider_generation,
        observed_state=report.observed_state.value,
        observed_desired_generation=report.observed_desired_generation,
        provider_runtime_id=report.provider_runtime_id or "",
        workspace_path=report.workspace_path,
        reason=report.reason,
        diagnostic=dict(report.diagnostic),
        reported_at=_timestamp(report.reported_at),
    )


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
    return RuntimeProviderReport(
        runtime_id=message.runtime_id,
        provider_id=message.provider_id,
        provider_generation=message.provider_generation,
        observed_state=RuntimeProviderObservedState(message.observed_state),
        observed_desired_generation=message.observed_desired_generation,
        provider_runtime_id=message.provider_runtime_id or None,
        workspace_path=message.workspace_path,
        reason=message.reason,
        diagnostic=dict(message.diagnostic),
        reported_at=_datetime(message.reported_at),
    )


def _struct(metadata: object) -> struct_pb2.Struct:
    struct = struct_pb2.Struct()
    struct.update(cast(dict[str, object], metadata))
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
    field_name: str,
) -> datetime | None:
    if not message.HasField(field_name):
        return None
    return _datetime(message.deadline_at)


__all__ = [
    "GrpcProviderControlClient",
    "ProviderControlStream",
    "RuntimeProviderControlStreamClosed",
    "json_value_from_struct",
    "provider_report_from_message",
]
