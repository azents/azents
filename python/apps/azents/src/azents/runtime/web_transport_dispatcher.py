"""Metadata-only Runtime Web intent dispatcher over Runner Control."""

from datetime import datetime

from azents_runtime_control.runner_web import (
    RUNNER_WEB_CAPABILITY,
    RunnerWebCancelReason,
    RunnerWebIdentity,
)

from azents.runtime.control_protocol.data import (
    RuntimeDispatchResult,
    RuntimeProtocolRouteUnavailable,
    RuntimeProtocolStaleGeneration,
    RuntimeRunnerOperation,
)
from azents.runtime.control_protocol.service import RuntimeControlProtocolService
from azents.runtime.coordination.data import JsonValue, RuntimeConnectionKind
from azents.runtime.coordination.store import RuntimeCoordinationStore

_WEB_OPEN_OPERATION_TYPE = "runtime.web.open.v1"
_WEB_CANCEL_OPERATION_TYPE = "runtime.web.cancel.v1"


class RuntimeWebDispatchUnavailable(RuntimeError):
    """The exact capable Runner generation cannot accept a Web intent."""


class RuntimeWebTransportDispatcher:
    """Dispatch bounded open/cancel metadata without application bytes."""

    def __init__(
        self,
        *,
        control_protocol: RuntimeControlProtocolService,
        coordination_store: RuntimeCoordinationStore,
    ) -> None:
        self.control_protocol = control_protocol
        self.coordination_store = coordination_store

    async def open(
        self,
        identity: RunnerWebIdentity,
        *,
        requested_at: datetime,
    ) -> RuntimeDispatchResult:
        """Dispatch one exact current-generation open intent."""
        if not await self._capability_current(identity):
            raise RuntimeWebDispatchUnavailable(
                "Runtime Web Runner capability is unavailable"
            )
        result = await self.control_protocol.dispatch_runner_operation(
            RuntimeRunnerOperation(
                runtime_id=identity.runtime_id,
                runner_generation=identity.runner_generation,
                operation_type=_WEB_OPEN_OPERATION_TYPE,
                owner_session_id=None,
                payload=_identity_payload(identity),
                deadline_at=identity.registration_deadline_at,
                body_stream_id=None,
            ),
            created_at=requested_at,
        )
        if isinstance(result, RuntimeProtocolRouteUnavailable):
            raise RuntimeWebDispatchUnavailable("Runtime Web Runner is unavailable")
        if isinstance(result, RuntimeProtocolStaleGeneration):
            raise RuntimeWebDispatchUnavailable(
                "Runtime Web Runner generation is stale"
            )
        return result

    async def cancel(
        self,
        identity: RunnerWebIdentity,
        *,
        reason: RunnerWebCancelReason,
        requested_at: datetime,
    ) -> bool:
        """Dispatch a best-effort exact tunnel cancellation."""
        if not await self._capability_current(identity):
            return False
        result = await self.control_protocol.dispatch_runner_operation(
            RuntimeRunnerOperation(
                runtime_id=identity.runtime_id,
                runner_generation=identity.runner_generation,
                operation_type=_WEB_CANCEL_OPERATION_TYPE,
                owner_session_id=None,
                payload={
                    **_identity_payload(identity),
                    "reason": reason.value,
                },
                deadline_at=identity.transport_deadline_at,
                body_stream_id=None,
            ),
            created_at=requested_at,
        )
        return isinstance(result, RuntimeDispatchResult)

    async def _capability_current(self, identity: RunnerWebIdentity) -> bool:
        connection = await self.coordination_store.get_connection(
            kind=RuntimeConnectionKind.RUNNER,
            subject_id=identity.runtime_id,
        )
        if connection is None or connection.generation != identity.runner_generation:
            return False
        capabilities = connection.metadata.get("capabilities")
        return isinstance(capabilities, list) and RUNNER_WEB_CAPABILITY in capabilities


def _identity_payload(identity: RunnerWebIdentity) -> dict[str, JsonValue]:
    return {
        "tunnel_id": identity.tunnel_id,
        "endpoint_id": identity.endpoint_id,
        "cycle_id": identity.cycle_id,
        "endpoint_authority_revision": identity.endpoint_authority_revision,
        "close_barrier": identity.close_barrier,
        "runtime_id": identity.runtime_id,
        "desired_generation": identity.desired_generation,
        "runner_generation": identity.runner_generation,
        "port": identity.port,
        "join_nonce": identity.join_nonce,
        "registration_deadline_at": identity.registration_deadline_at.isoformat(),
        "approval_deadline_at": identity.approval_deadline_at.isoformat(),
        "transport_deadline_at": identity.transport_deadline_at.isoformat(),
    }
