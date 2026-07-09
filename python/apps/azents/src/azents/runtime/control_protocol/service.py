"""Agent Runtime control protocol foundation service."""

import dataclasses
import secrets
from datetime import datetime

from azents.runtime.control_protocol.data import (
    RuntimeDispatchResult,
    RuntimeProtocolRouteUnavailable,
    RuntimeProtocolStaleGeneration,
    RuntimeProviderCommand,
    RuntimeProviderRegistration,
    RuntimeProviderRegistrationAccepted,
    RuntimeReplyAppendResult,
    RuntimeRequestIdFactory,
    RuntimeRunnerOperation,
    RuntimeRunnerRegistration,
    RuntimeRunnerRegistrationAccepted,
)
from azents.runtime.coordination.data import (
    JsonValue,
    RuntimeBackgroundOperationContext,
    RuntimeConnectionKind,
    RuntimeCoordinationTarget,
    RuntimeOperationMetadata,
    RuntimeOperationStatus,
    RuntimeReplyEvent,
    RuntimeReplyRecord,
    RuntimeRequestEnvelope,
)
from azents.runtime.coordination.store import RuntimeCoordinationStore

_DEFAULT_HEARTBEAT_INTERVAL_SECONDS = 20
_DEFAULT_CONNECTION_TTL_SECONDS = 60
_DEFAULT_OPERATION_TTL_SECONDS = 900
_DEFAULT_REQUEST_RECLAIM_IDLE_SECONDS = 30.0
_OPERATION_TTL_DEADLINE_BUFFER_SECONDS = 300


class RuntimeControlProtocolService:
    """Provider/Runner registration and request stream foundation."""

    def __init__(
        self,
        store: RuntimeCoordinationStore,
        *,
        request_id_factory: RuntimeRequestIdFactory | None = None,
        heartbeat_interval_seconds: int = _DEFAULT_HEARTBEAT_INTERVAL_SECONDS,
        connection_ttl_seconds: int = _DEFAULT_CONNECTION_TTL_SECONDS,
        operation_ttl_seconds: int = _DEFAULT_OPERATION_TTL_SECONDS,
        request_reclaim_idle_seconds: float = _DEFAULT_REQUEST_RECLAIM_IDLE_SECONDS,
    ) -> None:
        """Initialize the control protocol service."""
        self._store = store
        self._request_id_factory = request_id_factory or _new_request_id
        self._heartbeat_interval_seconds = heartbeat_interval_seconds
        self._connection_ttl_seconds = connection_ttl_seconds
        self._operation_ttl_seconds = operation_ttl_seconds
        self._request_reclaim_idle_seconds = request_reclaim_idle_seconds

    async def register_provider(
        self,
        registration: RuntimeProviderRegistration,
        *,
        registered_at: datetime,
    ) -> RuntimeProviderRegistrationAccepted:
        """Register a Provider connection and issue a provider generation."""
        record = await self._store.register_connection(
            kind=RuntimeConnectionKind.PROVIDER,
            subject_id=registration.provider_id,
            connection_id=registration.connection_id,
            owner_replica_id=registration.owner_replica_id,
            connected_at=registered_at,
            heartbeat_at=registered_at,
            ttl_seconds=self._connection_ttl_seconds,
            metadata={
                "provider_type": registration.provider_type,
                "scope": registration.scope,
                "workspace_id": registration.workspace_id,
                "protocol_version": registration.protocol_version,
                "capabilities": list(registration.capabilities.values),
                "config_schema_version": registration.config_schema_version,
                "auth_credential_id": registration.auth_credential_id,
                "metadata": registration.metadata,
            },
        )
        return RuntimeProviderRegistrationAccepted(
            provider_id=registration.provider_id,
            connection_id=registration.connection_id,
            generation=record.generation,
            heartbeat_interval_seconds=self._heartbeat_interval_seconds,
        )

    async def register_runner(
        self,
        registration: RuntimeRunnerRegistration,
        *,
        registered_at: datetime,
    ) -> RuntimeRunnerRegistrationAccepted:
        """Register a Runner connection and issue a runner generation."""
        record = await self._store.register_connection(
            kind=RuntimeConnectionKind.RUNNER,
            subject_id=registration.runtime_id,
            connection_id=registration.connection_id,
            owner_replica_id=registration.owner_replica_id,
            connected_at=registered_at,
            heartbeat_at=registered_at,
            ttl_seconds=self._connection_ttl_seconds,
            metadata={
                "runner_id": registration.runner_id,
                "protocol_version": registration.protocol_version,
                "capabilities": list(registration.capabilities.values),
                "health": registration.health,
                "workspace_path": registration.workspace_path,
                "auth_credential_id": registration.auth_credential_id,
                "metadata": registration.metadata,
            },
        )
        return RuntimeRunnerRegistrationAccepted(
            runtime_id=registration.runtime_id,
            runner_id=registration.runner_id,
            connection_id=registration.connection_id,
            generation=record.generation,
            heartbeat_interval_seconds=self._heartbeat_interval_seconds,
        )

    async def heartbeat_provider(
        self,
        *,
        provider_id: str,
        generation: int,
        heartbeat_at: datetime,
    ) -> bool:
        """Refresh provider connection TTL if generation fencing matches."""
        return await self._store.heartbeat_connection(
            kind=RuntimeConnectionKind.PROVIDER,
            subject_id=provider_id,
            generation=generation,
            heartbeat_at=heartbeat_at,
            ttl_seconds=self._connection_ttl_seconds,
        )

    async def heartbeat_runner(
        self,
        *,
        runtime_id: str,
        generation: int,
        heartbeat_at: datetime,
    ) -> bool:
        """Refresh runner connection TTL if generation fencing matches."""
        return await self._store.heartbeat_connection(
            kind=RuntimeConnectionKind.RUNNER,
            subject_id=runtime_id,
            generation=generation,
            heartbeat_at=heartbeat_at,
            ttl_seconds=self._connection_ttl_seconds,
        )

    async def dispatch_provider_command(
        self,
        command: RuntimeProviderCommand,
        *,
        created_at: datetime,
    ) -> (
        RuntimeDispatchResult
        | RuntimeProtocolRouteUnavailable
        | RuntimeProtocolStaleGeneration
    ):
        """Append a Provider command to the Provider request stream."""
        connection = await self._store.get_connection(
            kind=RuntimeConnectionKind.PROVIDER,
            subject_id=command.provider_id,
        )
        if connection is None:
            return RuntimeProtocolRouteUnavailable(
                target=RuntimeCoordinationTarget.PROVIDER,
                subject_id=command.provider_id,
            )
        if connection.generation != command.provider_generation:
            return RuntimeProtocolStaleGeneration(
                target=RuntimeCoordinationTarget.PROVIDER,
                subject_id=command.provider_id,
                generation=command.provider_generation,
            )
        request_id = self._request_id_factory()
        request_stream_id = _provider_request_stream_id(
            command.provider_id,
            command.provider_generation,
        )
        reply_stream_id = _provider_reply_stream_id(
            command.provider_id,
            command.provider_generation,
        )
        payload: dict[str, JsonValue] = {
            "provider_id": command.provider_id,
            "desired_generation": command.desired_generation,
            "command_type": command.command_type.value,
            "reset_final_desired_state": command.reset_final_desired_state,
            "payload": command.payload,
        }
        return await self._append_request(
            request_id=request_id,
            runtime_id=command.runtime_id,
            target=RuntimeCoordinationTarget.PROVIDER,
            generation=command.provider_generation,
            operation_type=f"provider.{command.command_type.value}",
            payload=payload,
            request_stream_id=request_stream_id,
            reply_stream_id=reply_stream_id,
            body_stream_id=None,
            deadline_at=command.deadline_at,
            created_at=created_at,
            background=False,
            background_context=None,
        )

    async def dispatch_runner_operation(
        self,
        operation: RuntimeRunnerOperation,
        *,
        created_at: datetime,
    ) -> (
        RuntimeDispatchResult
        | RuntimeProtocolRouteUnavailable
        | RuntimeProtocolStaleGeneration
    ):
        """Append a Runner operation to the Runtime request stream."""
        connection = await self._store.get_connection(
            kind=RuntimeConnectionKind.RUNNER,
            subject_id=operation.runtime_id,
        )
        if connection is None:
            return RuntimeProtocolRouteUnavailable(
                target=RuntimeCoordinationTarget.RUNNER,
                subject_id=operation.runtime_id,
            )
        if connection.generation != operation.runner_generation:
            return RuntimeProtocolStaleGeneration(
                target=RuntimeCoordinationTarget.RUNNER,
                subject_id=operation.runtime_id,
                generation=operation.runner_generation,
            )
        request_id = self._request_id_factory()
        request_stream_id = _runner_request_stream_id(
            operation.runtime_id,
            operation.runner_generation,
        )
        reply_stream_id = _runner_reply_stream_id(
            operation.runtime_id,
            operation.runner_generation,
        )
        payload: dict[str, JsonValue] = {
            "operation_type": operation.operation_type,
            "payload": operation.payload,
            "background": operation.background,
        }
        return await self._append_request(
            request_id=request_id,
            runtime_id=operation.runtime_id,
            target=RuntimeCoordinationTarget.RUNNER,
            generation=operation.runner_generation,
            operation_type=operation.operation_type,
            payload=payload,
            request_stream_id=request_stream_id,
            reply_stream_id=reply_stream_id,
            body_stream_id=operation.body_stream_id,
            deadline_at=operation.deadline_at,
            created_at=created_at,
            background=operation.background,
            background_context=operation.background_context,
        )

    async def claim_next_provider_request(
        self,
        *,
        provider_id: str,
        generation: int,
        consumer_id: str,
        block_ms: int,
    ) -> RuntimeRequestEnvelope | None:
        """Claim the next Provider request for the current provider generation."""
        if not await self._generation_current(
            kind=RuntimeConnectionKind.PROVIDER,
            subject_id=provider_id,
            generation=generation,
        ):
            return None
        stream_id = _provider_request_stream_id(provider_id, generation)
        consumer_group = _generation_group(provider_id, generation)
        record = await self._store.claim_next_request(
            stream_id,
            consumer_group=consumer_group,
            consumer_id=consumer_id,
            block_ms=block_ms,
            reclaim_idle_seconds=self._request_reclaim_idle_seconds,
        )
        if record is None:
            return None
        return dataclasses.replace(
            record.envelope,
            cursor=record.cursor,
            stream_id=stream_id,
            consumer_group=consumer_group,
        )

    async def claim_next_runner_request(
        self,
        *,
        runtime_id: str,
        generation: int,
        consumer_id: str,
        block_ms: int,
    ) -> RuntimeRequestEnvelope | None:
        """Claim the next Runner request for the current runner generation."""
        if not await self._generation_current(
            kind=RuntimeConnectionKind.RUNNER,
            subject_id=runtime_id,
            generation=generation,
        ):
            return None
        stream_id = _runner_request_stream_id(runtime_id, generation)
        consumer_group = _generation_group(runtime_id, generation)
        record = await self._store.claim_next_request(
            stream_id,
            consumer_group=consumer_group,
            consumer_id=consumer_id,
            block_ms=block_ms,
            reclaim_idle_seconds=self._request_reclaim_idle_seconds,
        )
        if record is None:
            return None
        return dataclasses.replace(
            record.envelope,
            cursor=record.cursor,
            stream_id=stream_id,
            consumer_group=consumer_group,
        )

    async def ack_claimed_request(
        self,
        envelope: RuntimeRequestEnvelope,
    ) -> None:
        """Acknowledge a claimed Provider or Runner request envelope."""
        if envelope.cursor is None:
            raise ValueError("Claimed request cursor is required")
        if envelope.stream_id is None or envelope.consumer_group is None:
            raise ValueError("Claimed request stream metadata is required")
        await self._store.ack_request(
            envelope.stream_id,
            consumer_group=envelope.consumer_group,
            cursor=envelope.cursor,
        )

    async def append_reply_event(
        self,
        event: RuntimeReplyEvent,
        *,
        reply_stream_id: str,
        operation_id: str | None,
        expected_target: RuntimeCoordinationTarget,
        expected_subject_id: str,
    ) -> (
        RuntimeReplyAppendResult
        | RuntimeProtocolRouteUnavailable
        | RuntimeProtocolStaleGeneration
    ):
        """Append a fenced Provider or Runner reply event."""
        kind = _connection_kind(expected_target)
        connection = await self._store.get_connection(
            kind=kind,
            subject_id=expected_subject_id,
        )
        if connection is None:
            return RuntimeProtocolRouteUnavailable(
                target=expected_target,
                subject_id=expected_subject_id,
            )
        if connection.generation != event.generation:
            return RuntimeProtocolStaleGeneration(
                target=expected_target,
                subject_id=expected_subject_id,
                generation=event.generation,
            )
        cursor = await self._store.append_reply(reply_stream_id, event)
        if operation_id is not None:
            if event.final:
                await self._store.update_operation_status(
                    operation_id,
                    status=RuntimeOperationStatus.FINAL,
                    updated_at=event.created_at,
                    final_event_cursor=cursor,
                )
            else:
                await self._store.heartbeat_operation(
                    operation_id,
                    heartbeat_at=event.created_at,
                )
        return RuntimeReplyAppendResult(
            cursor=cursor,
            final=event.final,
            operation_id=operation_id,
        )

    async def append_operation_reply_event(
        self,
        event: RuntimeReplyEvent,
        *,
        operation_id: str,
        expected_target: RuntimeCoordinationTarget,
        expected_subject_id: str,
    ) -> (
        RuntimeReplyAppendResult
        | RuntimeProtocolRouteUnavailable
        | RuntimeProtocolStaleGeneration
        | None
    ):
        """Append an event to the reply stream stored in operation metadata."""
        operation = await self._store.get_operation(operation_id)
        if operation is None:
            return None
        return await self.append_reply_event(
            event,
            reply_stream_id=operation.reply_stream_id,
            operation_id=operation_id,
            expected_target=expected_target,
            expected_subject_id=expected_subject_id,
        )

    async def read_replies(
        self,
        *,
        reply_stream_id: str,
        after_cursor: str | None,
        limit: int,
    ) -> list[RuntimeReplyRecord]:
        """Read reply events for foreground operation resume."""
        return await self._store.read_replies(
            reply_stream_id,
            after_cursor=after_cursor,
            limit=limit,
        )

    async def _append_request(
        self,
        *,
        request_id: str,
        runtime_id: str,
        target: RuntimeCoordinationTarget,
        generation: int,
        operation_type: str,
        payload: dict[str, JsonValue],
        request_stream_id: str,
        reply_stream_id: str,
        body_stream_id: str | None,
        deadline_at: datetime | None,
        created_at: datetime,
        background: bool,
        background_context: RuntimeBackgroundOperationContext | None,
    ) -> RuntimeDispatchResult:
        envelope = RuntimeRequestEnvelope(
            request_id=request_id,
            runtime_id=runtime_id,
            target=target,
            generation=generation,
            operation_type=operation_type,
            payload=payload,
            reply_stream_id=reply_stream_id,
            deadline_at=deadline_at,
            body_stream_id=body_stream_id,
        )
        operation_id = _operation_id(request_id)
        await self._store.put_operation(
            RuntimeOperationMetadata(
                operation_id=operation_id,
                runtime_id=runtime_id,
                target=target,
                request_stream_id=request_stream_id,
                reply_stream_id=reply_stream_id,
                status=RuntimeOperationStatus.ACTIVE,
                created_at=created_at,
                updated_at=created_at,
                deadline_at=deadline_at,
                body_stream_id=body_stream_id,
                last_heartbeat_at=None,
                last_event_at=None,
                cancel_requested_at=None,
                final_event_cursor=None,
                background=background,
                background_context=background_context,
            ),
            ttl_seconds=_operation_ttl_seconds(
                created_at=created_at,
                deadline_at=deadline_at,
                default_ttl_seconds=self._operation_ttl_seconds,
            ),
        )
        await self._store.append_request(request_stream_id, envelope)
        return RuntimeDispatchResult(
            operation_id=operation_id,
            request_id=request_id,
            request_stream_id=request_stream_id,
            reply_stream_id=reply_stream_id,
            target=target,
        )

    async def _generation_current(
        self,
        *,
        kind: RuntimeConnectionKind,
        subject_id: str,
        generation: int,
    ) -> bool:
        connection = await self._store.get_connection(kind=kind, subject_id=subject_id)
        return connection is not None and connection.generation == generation


def _new_request_id() -> str:
    return secrets.token_hex(16)


def _operation_id(request_id: str) -> str:
    return f"operation:{request_id}"


def _operation_ttl_seconds(
    *,
    created_at: datetime,
    deadline_at: datetime | None,
    default_ttl_seconds: int,
) -> int:
    if deadline_at is None:
        return default_ttl_seconds
    deadline_ttl = int((deadline_at - created_at).total_seconds())
    deadline_ttl_with_buffer = deadline_ttl + _OPERATION_TTL_DEADLINE_BUFFER_SECONDS
    return max(default_ttl_seconds, deadline_ttl_with_buffer, 1)


def _provider_request_stream_id(provider_id: str, generation: int) -> str:
    return f"provider:{provider_id}:generation:{generation}:requests"


def _runner_request_stream_id(runtime_id: str, generation: int) -> str:
    return f"runner:{runtime_id}:generation:{generation}:requests"


def _provider_reply_stream_id(provider_id: str, generation: int) -> str:
    return f"provider:{provider_id}:generation:{generation}:replies"


def _runner_reply_stream_id(runtime_id: str, generation: int) -> str:
    return f"runner:{runtime_id}:generation:{generation}:replies"


def _generation_group(subject_id: str, generation: int) -> str:
    return f"{subject_id}:generation:{generation}"


def _connection_kind(target: RuntimeCoordinationTarget) -> RuntimeConnectionKind:
    if target == RuntimeCoordinationTarget.PROVIDER:
        return RuntimeConnectionKind.PROVIDER
    return RuntimeConnectionKind.RUNNER
