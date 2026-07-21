"""Agent Runtime Provider Control gRPC server bridge."""

# pyright: reportAttributeAccessIssue=false, reportUntypedBaseClass=false
# protobuf generated modules expose dynamic message/RPC attributes.

import asyncio
import contextlib
import dataclasses
import logging
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from typing import Protocol, cast

import grpc
from azents_runtime_control.grpc_provider_client import (
    json_value_from_struct,
    provider_report_from_message,
)
from azents_runtime_control.proto import (
    runtime_provider_control_pb2,
    runtime_provider_control_pb2_grpc,
)
from azents_runtime_control.provider import (
    RuntimeLifecycleCommandType as RuntimeProviderCommandType,
)
from azents_runtime_control.provider import (
    RuntimeProviderReport as SharedRuntimeProviderReport,
)
from google.protobuf import timestamp_pb2

from azents.runtime.control_protocol.data import (
    RuntimeProtocolCapabilities,
    RuntimeProviderRegistration,
)
from azents.runtime.control_protocol.grpc.auth import RuntimeControlGrpcAuth
from azents.runtime.control_protocol.service import (
    RuntimeControlProtocolService,
)
from azents.runtime.coordination.data import (
    JsonValue,
    RuntimeCoordinationTarget,
    RuntimeReplyEvent,
    RuntimeReplyEventType,
    RuntimeRequestEnvelope,
)

_DEFAULT_COMMAND_BLOCK_MS = 500
_LOGGER = logging.getLogger(__name__)


@dataclasses.dataclass(frozen=True)
class _ProviderOutboundItem:
    """Provider outbound message with optional request ack metadata."""

    message: runtime_provider_control_pb2.ControlMessage
    ack_envelope: RuntimeRequestEnvelope | None = None


type _ProviderOutbound = (
    runtime_provider_control_pb2.ControlMessage | _ProviderOutboundItem
)


class RuntimeProviderReportSink(Protocol):
    """Durable Provider state sink used by the gRPC bridge."""

    async def record_provider_report(
        self,
        report: SharedRuntimeProviderReport,
    ) -> None:
        """Persist one Provider observed-state report."""
        ...


class RuntimeProviderControlGrpcServicer(
    runtime_provider_control_pb2_grpc.RuntimeProviderControlServicer
):
    """Bidirectional gRPC stream bridge for external Runtime Providers."""

    def __init__(
        self,
        *,
        control_protocol: RuntimeControlProtocolService,
        report_sink: RuntimeProviderReportSink,
        owner_replica_id: str,
        consumer_id: str,
        control_auth_token: str | None,
        command_block_ms: int = _DEFAULT_COMMAND_BLOCK_MS,
    ) -> None:
        """Initialize the Provider Control gRPC servicer."""
        self._control_protocol = control_protocol
        self._report_sink = report_sink
        self._owner_replica_id = owner_replica_id
        self._consumer_id = consumer_id
        self._auth = RuntimeControlGrpcAuth(control_auth_token)
        self._command_block_ms = command_block_ms

    async def ConnectProvider(
        self,
        request_iterator: AsyncIterator[runtime_provider_control_pb2.ProviderMessage],
        context: grpc.aio.ServicerContext[
            runtime_provider_control_pb2.ProviderMessage,
            runtime_provider_control_pb2.ControlMessage,
        ],
    ) -> AsyncIterator[runtime_provider_control_pb2.ControlMessage]:
        """Register a Provider, then bridge heartbeat/report/command messages."""
        await self._auth.authorize(context, subject="Provider")
        first_message = await _first_register_message(request_iterator, context)
        now = datetime.now(UTC)
        accepted = await self._control_protocol.register_provider(
            _registration(
                first_message,
                owner_replica_id=self._owner_replica_id,
            ),
            registered_at=now,
        )
        _LOGGER.info(
            "Runtime Provider connected",
            extra={
                "provider_id": accepted.provider_id,
                "connection_id": accepted.connection_id,
                "provider_generation": accepted.generation,
                "owner_replica_id": self._owner_replica_id,
            },
        )
        outbound: asyncio.Queue[_ProviderOutbound] = asyncio.Queue()
        inbound_task = asyncio.create_task(
            self._consume_provider_messages(
                request_iterator,
                outbound,
                provider_id=accepted.provider_id,
                generation=accepted.generation,
            )
        )
        command_task = asyncio.create_task(
            self._relay_provider_commands(
                outbound,
                provider_id=accepted.provider_id,
                generation=accepted.generation,
            )
        )
        yield runtime_provider_control_pb2.ControlMessage(
            request_id=first_message.request_id,
            register_accepted=runtime_provider_control_pb2.ProviderRegisterAccepted(
                provider_id=accepted.provider_id,
                connection_id=accepted.connection_id,
                generation=accepted.generation,
                heartbeat_interval_seconds=accepted.heartbeat_interval_seconds,
            ),
        )
        try:
            async for message in _outbound_messages(
                outbound,
                inbound_task,
                command_task,
                control_protocol=self._control_protocol,
            ):
                yield message
        finally:
            for task in (inbound_task, command_task):
                task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await task
            _LOGGER.info(
                "Runtime Provider stream closed",
                extra={
                    "provider_id": accepted.provider_id,
                    "connection_id": accepted.connection_id,
                    "provider_generation": accepted.generation,
                    "owner_replica_id": self._owner_replica_id,
                },
            )

    async def _consume_provider_messages(
        self,
        request_iterator: AsyncIterator[runtime_provider_control_pb2.ProviderMessage],
        outbound: asyncio.Queue[_ProviderOutbound],
        *,
        provider_id: str,
        generation: int,
    ) -> None:
        async for message in request_iterator:
            payload = message.WhichOneof("payload")
            if message.generation != generation:
                await outbound.put(
                    _error(message.request_id, "STALE_PROVIDER_GENERATION")
                )
                return
            if payload == "heartbeat":
                ok = await self._control_protocol.heartbeat_provider(
                    provider_id=provider_id,
                    generation=generation,
                    heartbeat_at=datetime.now(UTC),
                )
                if not ok:
                    await outbound.put(
                        _error(message.request_id, "STALE_PROVIDER_GENERATION")
                    )
                    return
                await outbound.put(
                    runtime_provider_control_pb2.ControlMessage(
                        request_id=message.request_id,
                        heartbeat_ack=runtime_provider_control_pb2.ProviderHeartbeatAck(
                            monotonic_sequence=message.heartbeat.monotonic_sequence,
                        ),
                    )
                )
                continue
            if payload == "report":
                if message.report.provider_generation != generation:
                    await outbound.put(
                        _error(message.request_id, "STALE_PROVIDER_GENERATION")
                    )
                    return
                if not await self._provider_generation_current(
                    provider_id=provider_id,
                    generation=generation,
                    request_id=message.request_id,
                    outbound=outbound,
                ):
                    return
                await self._report_sink.record_provider_report(
                    _shared_report(message.report)
                )
                continue
            if payload == "command_completion":
                if message.command_completion.generation != generation:
                    await outbound.put(
                        _error(message.request_id, "STALE_PROVIDER_GENERATION")
                    )
                    return
                if (
                    message.command_completion.report.runtime_id
                    and message.command_completion.report.provider_generation
                    != generation
                ):
                    await outbound.put(
                        _error(message.request_id, "STALE_PROVIDER_GENERATION")
                    )
                    return
                if not await self._provider_generation_current(
                    provider_id=provider_id,
                    generation=generation,
                    request_id=message.request_id,
                    outbound=outbound,
                ):
                    return
                await self._complete_provider_command(
                    message.command_completion,
                    provider_id=provider_id,
                )
                if message.command_completion.report.runtime_id:
                    await self._report_sink.record_provider_report(
                        _shared_report(message.command_completion.report)
                    )

    async def _provider_generation_current(
        self,
        *,
        provider_id: str,
        generation: int,
        request_id: str,
        outbound: asyncio.Queue[_ProviderOutbound],
    ) -> bool:
        ok = await self._control_protocol.heartbeat_provider(
            provider_id=provider_id,
            generation=generation,
            heartbeat_at=datetime.now(UTC),
        )
        if ok:
            return True
        await outbound.put(_error(request_id, "STALE_PROVIDER_GENERATION"))
        return False

    async def _relay_provider_commands(
        self,
        outbound: asyncio.Queue[_ProviderOutbound],
        *,
        provider_id: str,
        generation: int,
    ) -> None:
        while True:
            envelope = await self._control_protocol.claim_next_provider_request(
                provider_id=provider_id,
                generation=generation,
                consumer_id=self._consumer_id,
                block_ms=self._command_block_ms,
            )
            if envelope is None:
                await asyncio.sleep(max(self._command_block_ms, 1) / 1000)
                continue
            if _deadline_expired(envelope, datetime.now(UTC)):
                await self._expire_provider_command(
                    envelope,
                    provider_id=provider_id,
                )
                await self._control_protocol.ack_claimed_request(envelope)
                continue
            try:
                command = _provider_command(envelope)
            except InvalidRuntimeProviderCommandPayload as exc:
                _LOGGER.warning(
                    "Runtime Provider command payload invalid",
                    extra={
                        "provider_id": provider_id,
                        "provider_generation": generation,
                        "request_id": envelope.request_id,
                        "runtime_id": envelope.runtime_id,
                        "error_code": exc.code,
                    },
                )
                await outbound.put(_error(envelope.request_id, exc.code, str(exc)))
                await self._control_protocol.ack_claimed_request(envelope)
                continue
            _LOGGER.info(
                "Runtime Provider command relayed",
                extra={
                    "provider_id": provider_id,
                    "provider_generation": generation,
                    "request_id": envelope.request_id,
                    "runtime_id": envelope.runtime_id,
                    "operation_type": envelope.operation_type,
                },
            )
            await outbound.put(
                _ProviderOutboundItem(
                    message=runtime_provider_control_pb2.ControlMessage(
                        request_id=envelope.request_id,
                        provider_command=command,
                    ),
                    ack_envelope=envelope,
                )
            )

    async def _expire_provider_command(
        self,
        envelope: RuntimeRequestEnvelope,
        *,
        provider_id: str,
    ) -> None:
        _LOGGER.warning(
            "Runtime Provider command expired before relay",
            extra={
                "provider_id": provider_id,
                "provider_generation": envelope.generation,
                "request_id": envelope.request_id,
                "runtime_id": envelope.runtime_id,
                "operation_type": envelope.operation_type,
            },
        )
        await self._control_protocol.append_reply_event(
            RuntimeReplyEvent(
                request_id=envelope.request_id,
                runtime_id=envelope.runtime_id,
                generation=envelope.generation,
                event_type=RuntimeReplyEventType.FINAL_ERROR,
                payload={
                    "success": False,
                    "error_code": "PROVIDER_COMMAND_EXPIRED",
                    "error_message": "Provider command expired before relay",
                },
                created_at=datetime.now(UTC),
                final=True,
            ),
            reply_stream_id=envelope.reply_stream_id,
            operation_id=f"operation:{envelope.request_id}",
            expected_target=RuntimeCoordinationTarget.PROVIDER,
            expected_subject_id=provider_id,
        )

    async def _complete_provider_command(
        self,
        completion: runtime_provider_control_pb2.ProviderCommandCompletion,
        *,
        provider_id: str,
    ) -> None:
        event_type = (
            RuntimeReplyEventType.FINAL_SUCCESS
            if completion.success
            else RuntimeReplyEventType.FINAL_ERROR
        )
        payload: dict[str, JsonValue] = {
            "success": completion.success,
            "error_code": completion.error_code or None,
            "error_message": completion.error_message or None,
        }
        if completion.report.runtime_id:
            payload["provider_observed_state"] = completion.report.observed_state
            payload["workspace_path"] = completion.report.workspace_path
        await self._control_protocol.append_operation_reply_event(
            RuntimeReplyEvent(
                request_id=completion.request_id,
                runtime_id=completion.runtime_id,
                generation=completion.generation,
                event_type=event_type,
                payload=payload,
                created_at=completion.completed_at.ToDatetime(tzinfo=UTC),
                final=True,
            ),
            operation_id=f"operation:{completion.request_id}",
            expected_target=RuntimeCoordinationTarget.PROVIDER,
            expected_subject_id=provider_id,
        )
        _LOGGER.info(
            "Runtime Provider command completed",
            extra={
                "provider_id": provider_id,
                "request_id": completion.request_id,
                "runtime_id": completion.runtime_id,
                "success": completion.success,
                "error_code": completion.error_code or None,
            },
        )


class InvalidRuntimeProviderCommandPayload(ValueError):
    """Provider command payload cannot be converted to the gRPC contract."""

    def __init__(self, code: str, message: str) -> None:
        """Initialize the payload error."""
        super().__init__(message)
        self.code = code


def add_runtime_provider_control_servicer(
    server: grpc.aio.Server,
    *,
    control_protocol: RuntimeControlProtocolService,
    report_sink: RuntimeProviderReportSink,
    owner_replica_id: str,
    consumer_id: str,
    control_auth_token: str | None,
    command_block_ms: int = _DEFAULT_COMMAND_BLOCK_MS,
) -> None:
    """Add the Agent Runtime Provider Control servicer to a gRPC server."""
    runtime_provider_control_pb2_grpc.add_RuntimeProviderControlServicer_to_server(
        RuntimeProviderControlGrpcServicer(
            control_protocol=control_protocol,
            report_sink=report_sink,
            owner_replica_id=owner_replica_id,
            consumer_id=consumer_id,
            control_auth_token=control_auth_token,
            command_block_ms=command_block_ms,
        ),
        server,
    )


async def _first_register_message(
    request_iterator: AsyncIterator[runtime_provider_control_pb2.ProviderMessage],
    context: grpc.aio.ServicerContext[
        runtime_provider_control_pb2.ProviderMessage,
        runtime_provider_control_pb2.ControlMessage,
    ],
) -> runtime_provider_control_pb2.ProviderMessage:
    try:
        first_message = await anext(request_iterator)
    except StopAsyncIteration:
        await context.abort(
            grpc.StatusCode.INVALID_ARGUMENT,
            "Provider register message required",
        )
        raise AssertionError("unreachable") from None
    if first_message.WhichOneof("payload") != "register":
        await context.abort(
            grpc.StatusCode.INVALID_ARGUMENT,
            "Provider register message required",
        )
        raise AssertionError("unreachable") from None
    return first_message


async def _outbound_messages(
    outbound: asyncio.Queue[_ProviderOutbound],
    inbound_task: asyncio.Task[None],
    command_task: asyncio.Task[None],
    *,
    control_protocol: RuntimeControlProtocolService,
) -> AsyncIterator[runtime_provider_control_pb2.ControlMessage]:
    get_task = asyncio.create_task(outbound.get())
    try:
        while True:
            done, _pending = await asyncio.wait(
                {inbound_task, command_task, get_task},
                return_when=asyncio.FIRST_COMPLETED,
            )
            if get_task in done:
                item = get_task.result()
                if isinstance(item, _ProviderOutboundItem):
                    try:
                        yield item.message
                    finally:
                        await _ack_outbound_item(control_protocol, item)
                else:
                    yield item
                get_task = asyncio.create_task(outbound.get())
                continue
            for task in (inbound_task, command_task):
                if task in done:
                    task_name = (
                        "provider-inbound"
                        if task is inbound_task
                        else "provider-command-relay"
                    )
                    try:
                        await task
                    except asyncio.CancelledError:
                        raise
                    except Exception:
                        _LOGGER.exception(
                            "Runtime Provider stream task failed",
                            extra={"task_name": task_name},
                        )
                        raise
                    _LOGGER.info(
                        "Runtime Provider stream task ended",
                        extra={"task_name": task_name},
                    )
                    return
    finally:
        get_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await get_task


async def _ack_outbound_item(
    control_protocol: RuntimeControlProtocolService,
    item: _ProviderOutboundItem,
) -> None:
    if item.ack_envelope is None:
        return
    await control_protocol.ack_claimed_request(item.ack_envelope)


def _registration(
    message: runtime_provider_control_pb2.ProviderMessage,
    *,
    owner_replica_id: str,
) -> RuntimeProviderRegistration:
    register = message.register
    return RuntimeProviderRegistration(
        provider_id=register.provider_id,
        provider_type=register.provider_type,
        scope=register.scope,
        workspace_id=register.workspace_id or None,
        protocol_version=register.protocol_version,
        capabilities=RuntimeProtocolCapabilities(tuple(register.capabilities)),
        config_schema_version=register.config_schema_version,
        metadata=json_value_from_struct(register.metadata),
        auth_credential_id=register.auth_credential_id,
        connection_id=message.connection_id,
        owner_replica_id=owner_replica_id,
    )


def _provider_command(
    envelope: RuntimeRequestEnvelope,
) -> runtime_provider_control_pb2.ProviderCommand:
    payload = envelope.payload.get("payload")
    if not isinstance(payload, dict):
        raise InvalidRuntimeProviderCommandPayload(
            "INVALID_PROVIDER_COMMAND_PAYLOAD",
            "Provider command payload is missing",
        )
    identity = _required_mapping(payload, "identity")
    auth = _required_mapping(payload, "auth")
    deadline = timestamp_pb2.Timestamp()
    if envelope.deadline_at is not None:
        deadline.FromDatetime(envelope.deadline_at.astimezone(UTC))
    command = runtime_provider_control_pb2.ProviderCommand(
        runtime_id=envelope.runtime_id,
        agent_id=_required_string(identity, "agent_id"),
        workspace_id=_required_string(identity, "workspace_id"),
        desired_generation=_required_int(envelope.payload, "desired_generation"),
        provider_generation=envelope.generation,
        command_type=_required_command_type(envelope.payload),
        reset_final_desired_state=_optional_string(
            envelope.payload,
            "reset_final_desired_state",
        ),
        runner_image=_required_string(payload, "runner_image"),
        control_endpoint=_required_string(auth, "control_endpoint"),
        runner_auth_token=_required_string(auth, "runner_auth_token"),
    )
    command.payload.update(cast(dict[str, object], payload))
    if envelope.deadline_at is not None:
        command.deadline_at.CopyFrom(deadline)
    return command


def _deadline_expired(envelope: RuntimeRequestEnvelope, now: datetime) -> bool:
    return envelope.deadline_at is not None and envelope.deadline_at <= now


def _shared_report(
    message: runtime_provider_control_pb2.RuntimeProviderReport,
) -> SharedRuntimeProviderReport:
    return provider_report_from_message(message)


def _required_mapping(payload: dict[str, JsonValue], key: str) -> dict[str, JsonValue]:
    value = payload.get(key)
    if not isinstance(value, dict):
        raise InvalidRuntimeProviderCommandPayload(
            "INVALID_PROVIDER_COMMAND_PAYLOAD",
            f"Provider command payload requires object field: {key}",
        )
    return value


def _required_string(payload: dict[str, JsonValue], key: str) -> str:
    value = payload.get(key)
    if not isinstance(value, str) or not value:
        raise InvalidRuntimeProviderCommandPayload(
            "INVALID_PROVIDER_COMMAND_PAYLOAD",
            f"Provider command payload requires string field: {key}",
        )
    return value


def _optional_string(payload: dict[str, JsonValue], key: str) -> str:
    value = payload.get(key)
    if value is None:
        return ""
    if not isinstance(value, str):
        raise InvalidRuntimeProviderCommandPayload(
            "INVALID_PROVIDER_COMMAND_PAYLOAD",
            f"Provider command payload has non-string field: {key}",
        )
    return value


def _required_int(payload: dict[str, JsonValue], key: str) -> int:
    value = payload.get(key)
    if not isinstance(value, int):
        raise InvalidRuntimeProviderCommandPayload(
            "INVALID_PROVIDER_COMMAND_PAYLOAD",
            f"Provider command payload requires integer field: {key}",
        )
    return value


def _required_command_type(payload: dict[str, JsonValue]) -> str:
    value = _required_string(payload, "command_type")
    RuntimeProviderCommandType(value)
    return value


def _error(
    request_id: str,
    code: str,
    message: str | None = None,
) -> runtime_provider_control_pb2.ControlMessage:
    return runtime_provider_control_pb2.ControlMessage(
        request_id=request_id,
        error=runtime_provider_control_pb2.ProviderError(
            code=code,
            message=message or code,
        ),
    )
