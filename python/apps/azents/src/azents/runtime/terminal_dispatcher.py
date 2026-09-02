"""Runtime Control dispatcher for metadata-only Terminal intents."""

import logging
from datetime import datetime, timedelta

from azents_runtime_control.runner_terminal import (
    RUNNER_TERMINAL_CAPABILITY,
    RunnerTerminalTerminationReason,
)

from azents.runtime.control_protocol.data import (
    RuntimeDispatchResult,
    RuntimeProtocolRouteUnavailable,
    RuntimeProtocolStaleGeneration,
    RuntimeRunnerOperation,
)
from azents.runtime.control_protocol.service import RuntimeControlProtocolService
from azents.runtime.coordination.data import RuntimeConnectionKind
from azents.runtime.coordination.store import RuntimeCoordinationStore
from azents.runtime.terminal_coordination.data import RuntimeTerminalRecord
from azents.runtime.terminal_coordination.store import (
    RuntimeTerminalCoordinationStore,
)
from azents.services.runtime_terminal.service import RuntimeTerminalControlDispatcher

_TERMINAL_OPEN_OPERATION_TYPE = "terminal.open.v1"
_TERMINAL_TERMINATE_OPERATION_TYPE = "terminal.terminate.v1"
_TERMINAL_TERMINATE_DEADLINE = timedelta(seconds=30)
_LOGGER = logging.getLogger(__name__)


class RuntimeTerminalControlDispatcherAdapter(RuntimeTerminalControlDispatcher):
    """Dispatch typed Terminal intents through the current Runner Control stream."""

    def __init__(
        self,
        *,
        control_protocol: RuntimeControlProtocolService,
        terminal_coordination: RuntimeTerminalCoordinationStore,
        runtime_coordination: RuntimeCoordinationStore,
    ) -> None:
        """Initialize Control and volatile settlement dependencies."""
        self._control_protocol = control_protocol
        self._terminal_coordination = terminal_coordination
        self._runtime_coordination = runtime_coordination

    async def open_terminal(
        self,
        record: RuntimeTerminalRecord,
        *,
        columns: int,
        rows: int,
        requested_at: datetime,
    ) -> None:
        """Dispatch one idempotent open intent for an opening Terminal."""
        admission = record.admission
        if not await self._terminal_capability_current(record):
            await self._terminate_unroutable(record, requested_at=requested_at)
            return
        result = await self._control_protocol.dispatch_runner_operation(
            RuntimeRunnerOperation(
                runtime_id=admission.runtime_id,
                runner_generation=admission.runner_generation,
                operation_type=_TERMINAL_OPEN_OPERATION_TYPE,
                owner_session_id=admission.session_id,
                payload={
                    "terminal_id": admission.terminal_id,
                    "working_directory": admission.working_directory,
                    "columns": columns,
                    "rows": rows,
                    "idle_deadline_at": admission.idle_deadline_at.isoformat(),
                    "maximum_deadline_at": admission.maximum_deadline_at.isoformat(),
                    "data_stream_grace_deadline_at": (
                        admission.data_stream_grace_deadline_at.isoformat()
                    ),
                    "stream_nonce": admission.stream_nonce,
                    "initial_stream_generation": 1,
                },
                deadline_at=admission.data_stream_grace_deadline_at,
                body_stream_id=None,
            ),
            created_at=requested_at,
        )
        await self._settle_dispatch(record, result, requested_at=requested_at)

    async def terminate_terminal(
        self,
        record: RuntimeTerminalRecord,
        *,
        reason: RunnerTerminalTerminationReason,
        requested_at: datetime,
    ) -> None:
        """Dispatch one best-effort terminate intent."""
        admission = record.admission
        if not await self._terminal_capability_current(record):
            await self._terminate_unroutable(record, requested_at=requested_at)
            return
        result = await self._control_protocol.dispatch_runner_operation(
            RuntimeRunnerOperation(
                runtime_id=admission.runtime_id,
                runner_generation=admission.runner_generation,
                operation_type=_TERMINAL_TERMINATE_OPERATION_TYPE,
                owner_session_id=admission.session_id,
                payload={
                    "terminal_id": admission.terminal_id,
                    "reason": reason.value,
                },
                deadline_at=requested_at + _TERMINAL_TERMINATE_DEADLINE,
                body_stream_id=None,
            ),
            created_at=requested_at,
        )
        await self._settle_dispatch(record, result, requested_at=requested_at)

    async def _settle_dispatch(
        self,
        record: RuntimeTerminalRecord,
        result: (
            RuntimeDispatchResult
            | RuntimeProtocolRouteUnavailable
            | RuntimeProtocolStaleGeneration
        ),
        *,
        requested_at: datetime,
    ) -> None:
        if isinstance(result, RuntimeDispatchResult):
            return
        reason = (
            RunnerTerminalTerminationReason.RUNNER_REPLACED
            if isinstance(result, RuntimeProtocolStaleGeneration)
            else RunnerTerminalTerminationReason.RUNTIME_INVALIDATED
        )
        await self._terminal_coordination.request_termination(
            record.admission.terminal_id,
            reason=reason,
            requested_at=requested_at,
        )
        _LOGGER.warning(
            "Runtime Terminal intent dispatch unavailable",
            extra={
                "terminal_id": record.admission.terminal_id,
                "runtime_id": record.admission.runtime_id,
                "runner_generation": record.admission.runner_generation,
                "reason": reason.value,
            },
        )

    async def _terminal_capability_current(
        self,
        record: RuntimeTerminalRecord,
    ) -> bool:
        admission = record.admission
        runner = await self._runtime_coordination.get_connection(
            kind=RuntimeConnectionKind.RUNNER,
            subject_id=admission.runtime_id,
        )
        if runner is None or runner.generation != admission.runner_generation:
            return False
        capabilities = runner.metadata.get("capabilities")
        return (
            isinstance(capabilities, list)
            and RUNNER_TERMINAL_CAPABILITY in capabilities
        )

    async def _terminate_unroutable(
        self,
        record: RuntimeTerminalRecord,
        *,
        requested_at: datetime,
    ) -> None:
        await self._terminal_coordination.request_termination(
            record.admission.terminal_id,
            reason=RunnerTerminalTerminationReason.RUNTIME_INVALIDATED,
            requested_at=requested_at,
        )
        _LOGGER.warning(
            "Runtime Terminal intent capability unavailable",
            extra={
                "terminal_id": record.admission.terminal_id,
                "runtime_id": record.admission.runtime_id,
                "runner_generation": record.admission.runner_generation,
            },
        )
