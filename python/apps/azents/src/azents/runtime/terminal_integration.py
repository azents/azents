"""Runtime Terminal invalidation adapters across durable and volatile owners."""

import asyncio
import logging
from collections.abc import Callable, Sequence
from datetime import datetime

from azents_runtime_control.runner_terminal import RunnerTerminalTerminationReason

from azents.runtime.control_protocol.service import RuntimeRunnerGenerationObserver
from azents.runtime.terminal_coordination.data import (
    TERMINAL_FINAL_TTL_SECONDS,
    RuntimeTerminalInvalidationSource,
    RuntimeTerminalLifecycle,
    RuntimeTerminalMutationStatus,
)
from azents.runtime.terminal_coordination.store import (
    RuntimeTerminalCoordinationStore,
)
from azents.services.runtime_terminal.invalidation import (
    RuntimeTerminalInvalidationPublisher,
)
from azents.services.runtime_terminal.service import RuntimeTerminalControlDispatcher
from azents.services.terminal_policy.invalidation import (
    TerminalPolicyInvalidationPublisher,
    TerminalPolicySourceInvalidation,
    TerminalPolicySourceScope,
)

_LOGGER = logging.getLogger(__name__)


class CompositeRuntimeRunnerGenerationObserver:
    """Notify independent Runner-generation observers without cross-blocking."""

    def __init__(self, *observers: RuntimeRunnerGenerationObserver) -> None:
        """Initialize the exact process-owned observer set."""
        if not observers:
            raise ValueError("At least one Runner generation observer is required")
        self._observers = observers

    async def on_runner_replaced(
        self,
        *,
        runtime_id: str,
        previous_generation: int,
        generation: int,
    ) -> None:
        """Notify every observer of a newly accepted Runner generation."""
        results = await asyncio.gather(
            *(
                observer.on_runner_replaced(
                    runtime_id=runtime_id,
                    previous_generation=previous_generation,
                    generation=generation,
                )
                for observer in self._observers
            ),
            return_exceptions=True,
        )
        _log_observer_failures(results, runtime_id=runtime_id, action="replaced")

    async def on_runner_revoked(
        self,
        *,
        runtime_id: str,
        generation: int,
    ) -> None:
        """Notify every observer of a revoked current Runner generation."""
        results = await asyncio.gather(
            *(
                observer.on_runner_revoked(
                    runtime_id=runtime_id,
                    generation=generation,
                )
                for observer in self._observers
            ),
            return_exceptions=True,
        )
        _log_observer_failures(results, runtime_id=runtime_id, action="revoked")


class RuntimeTerminalRunnerGenerationObserver:
    """Invalidate Runtime Terminals when Runner generation authority changes."""

    def __init__(
        self,
        *,
        store: RuntimeTerminalCoordinationStore,
        clock: Callable[[], datetime],
    ) -> None:
        """Initialize volatile coordination invalidation."""
        self._store = store
        self._clock = clock

    async def on_runner_replaced(
        self,
        *,
        runtime_id: str,
        previous_generation: int,
        generation: int,
    ) -> None:
        """Terminate every Terminal owned by the replaced Runner generation."""
        del previous_generation, generation
        await self._invalidate(
            runtime_id,
            reason=RunnerTerminalTerminationReason.RUNNER_REPLACED,
        )

    async def on_runner_revoked(
        self,
        *,
        runtime_id: str,
        generation: int,
    ) -> None:
        """Terminate every Terminal after current Runner authority is revoked."""
        del generation
        await self._invalidate(
            runtime_id,
            reason=RunnerTerminalTerminationReason.RUNTIME_INVALIDATED,
        )

    async def _invalidate(
        self,
        runtime_id: str,
        *,
        reason: RunnerTerminalTerminationReason,
    ) -> None:
        now = _aware_now(self._clock)
        invalidated = await self._store.invalidate(
            source=RuntimeTerminalInvalidationSource.RUNTIME,
            source_id=runtime_id,
            reason=reason,
            invalidated_at=now,
        )
        await _finalize_runner_authority_invalidated(
            self._store,
            invalidated.terminal_ids,
            reason=reason,
            finalized_at=now,
        )


class CoordinatedRuntimeTerminalInvalidationPublisher(
    RuntimeTerminalInvalidationPublisher
):
    """Publish committed durable authority changes to Terminal coordination."""

    def __init__(
        self,
        *,
        store: RuntimeTerminalCoordinationStore,
        dispatcher: RuntimeTerminalControlDispatcher,
        clock: Callable[[], datetime],
    ) -> None:
        """Initialize Runtime-scoped volatile invalidation."""
        self._store = store
        self._dispatcher = dispatcher
        self._clock = clock

    async def publish_runtime_terminal_invalidation(self, runtime_id: str) -> None:
        """Invalidate active Terminals without blocking durable lifecycle work."""
        await self._publish(
            source=RuntimeTerminalInvalidationSource.RUNTIME,
            source_id=runtime_id,
            reason=RunnerTerminalTerminationReason.RUNTIME_INVALIDATED,
            failure_message="Runtime Terminal lifecycle invalidation failed",
            log_extra={"runtime_id": runtime_id},
        )

    async def publish_user_terminal_invalidation(self, user_id: str) -> None:
        """Invalidate active Terminals after one User loses durable access."""
        await self._publish(
            source=RuntimeTerminalInvalidationSource.USER,
            source_id=user_id,
            reason=RunnerTerminalTerminationReason.ACCESS_REVOKED,
            failure_message="Runtime Terminal User invalidation failed",
            log_extra={"user_id": user_id},
        )

    async def publish_authentication_session_terminal_invalidation(
        self,
        authentication_session_id: str,
    ) -> None:
        """Invalidate active Terminals after one authentication Session is revoked."""
        await self._publish(
            source=RuntimeTerminalInvalidationSource.ACCESS,
            source_id=authentication_session_id,
            reason=RunnerTerminalTerminationReason.ACCESS_REVOKED,
            failure_message=(
                "Runtime Terminal authentication Session invalidation failed"
            ),
            log_extra={"authentication_session_id": authentication_session_id},
        )

    async def publish_agent_session_terminal_invalidation(
        self,
        agent_session_id: str,
    ) -> None:
        """Invalidate active Terminals after one Agent Session loses access."""
        await self._publish(
            source=RuntimeTerminalInvalidationSource.SESSION,
            source_id=agent_session_id,
            reason=RunnerTerminalTerminationReason.ACCESS_REVOKED,
            failure_message="Runtime Terminal Agent Session invalidation failed",
            log_extra={"agent_session_id": agent_session_id},
        )

    async def _publish(
        self,
        *,
        source: RuntimeTerminalInvalidationSource,
        source_id: str,
        reason: RunnerTerminalTerminationReason,
        failure_message: str,
        log_extra: dict[str, str],
    ) -> None:
        """Invalidate and dispatch one exact durable authority source."""
        try:
            now = _aware_now(self._clock)
            invalidated = await self._store.invalidate(
                source=source,
                source_id=source_id,
                reason=reason,
                invalidated_at=now,
            )
            await _dispatch_invalidated(
                self._store,
                self._dispatcher,
                invalidated.terminal_ids,
                reason=reason,
                requested_at=now,
            )
        except asyncio.CancelledError:
            raise
        except Exception:
            _LOGGER.exception(failure_message, extra=log_extra)


class RuntimeTerminalPolicyInvalidationPublisher(TerminalPolicyInvalidationPublisher):
    """Publish committed policy-source changes to Terminal coordination."""

    def __init__(
        self,
        *,
        store: RuntimeTerminalCoordinationStore,
        dispatcher: RuntimeTerminalControlDispatcher,
        clock: Callable[[], datetime],
    ) -> None:
        """Initialize policy invalidation publication."""
        self._store = store
        self._dispatcher = dispatcher
        self._clock = clock

    async def publish_terminal_policy_invalidation(
        self,
        invalidation: TerminalPolicySourceInvalidation,
    ) -> None:
        """Invalidate active Terminals indexed by the changed durable source."""
        try:
            now = _aware_now(self._clock)
            invalidated = await self._store.invalidate(
                source={
                    TerminalPolicySourceScope.INFRASTRUCTURE_PROFILE: (
                        RuntimeTerminalInvalidationSource.PROVIDER_PROFILE
                    ),
                    TerminalPolicySourceScope.WORKSPACE_PROFILE: (
                        RuntimeTerminalInvalidationSource.WORKSPACE_PROFILE
                    ),
                    TerminalPolicySourceScope.AGENT: (
                        RuntimeTerminalInvalidationSource.AGENT
                    ),
                }[invalidation.scope],
                source_id=invalidation.source_id,
                reason=RunnerTerminalTerminationReason.POLICY_REVOKED,
                invalidated_at=now,
            )
            await _dispatch_invalidated(
                self._store,
                self._dispatcher,
                invalidated.terminal_ids,
                reason=RunnerTerminalTerminationReason.POLICY_REVOKED,
                requested_at=now,
            )
        except asyncio.CancelledError:
            raise
        except Exception:
            _LOGGER.exception(
                "Runtime Terminal policy invalidation failed",
                extra={
                    "source_scope": invalidation.scope.value,
                    "source_id": invalidation.source_id,
                    "source_version": invalidation.source_version,
                },
            )


async def _dispatch_invalidated(
    store: RuntimeTerminalCoordinationStore,
    dispatcher: RuntimeTerminalControlDispatcher,
    terminal_ids: Sequence[str],
    *,
    reason: RunnerTerminalTerminationReason,
    requested_at: datetime,
) -> None:
    for terminal_id in terminal_ids:
        record = await store.get_terminal(terminal_id, current_time=requested_at)
        if record is None:
            continue
        await dispatcher.terminate_terminal(
            record,
            reason=reason,
            requested_at=requested_at,
        )
        current = await store.get_terminal(terminal_id, current_time=requested_at)
        if (
            current is not None
            and current.lifecycle is RuntimeTerminalLifecycle.TERMINATING
            and current.runner_stream is None
        ):
            await _finalize_without_runner_stream(
                store,
                terminal_id,
                reason=reason,
                finalized_at=requested_at,
            )


async def _finalize_runner_authority_invalidated(
    store: RuntimeTerminalCoordinationStore,
    terminal_ids: Sequence[str],
    *,
    reason: RunnerTerminalTerminationReason,
    finalized_at: datetime,
) -> None:
    for terminal_id in terminal_ids:
        record = await store.get_terminal(terminal_id, current_time=finalized_at)
        if (
            record is None
            or record.lifecycle is not RuntimeTerminalLifecycle.TERMINATING
        ):
            continue
        finalized = await store.finalize_terminal(
            terminal_id,
            runner_stream_generation=(
                None
                if record.runner_stream is None
                else record.runner_stream.generation
            ),
            reason=reason,
            exit_code=None,
            finalized_at=finalized_at,
            final_ttl_seconds=TERMINAL_FINAL_TTL_SECONDS,
        )
        if finalized.status is not RuntimeTerminalMutationStatus.APPLIED:
            raise RuntimeError(
                "Runtime Terminal Runner-authority finalization was rejected"
            )


async def _finalize_without_runner_stream(
    store: RuntimeTerminalCoordinationStore,
    terminal_id: str,
    *,
    reason: RunnerTerminalTerminationReason,
    finalized_at: datetime,
) -> None:
    finalized = await store.finalize_terminal(
        terminal_id,
        runner_stream_generation=None,
        reason=reason,
        exit_code=None,
        finalized_at=finalized_at,
        final_ttl_seconds=TERMINAL_FINAL_TTL_SECONDS,
    )
    if finalized.status is not RuntimeTerminalMutationStatus.APPLIED:
        raise RuntimeError("Runtime Terminal invalidation finalization was rejected")


def _log_observer_failures(
    results: Sequence[object],
    *,
    runtime_id: str,
    action: str,
) -> None:
    for result in results:
        if isinstance(result, asyncio.CancelledError):
            continue
        if isinstance(result, BaseException):
            _LOGGER.warning(
                "Runtime Runner generation observer failed",
                exc_info=(type(result), result, result.__traceback__),
                extra={"runtime_id": runtime_id, "action": action},
            )


def _aware_now(clock: Callable[[], datetime]) -> datetime:
    now = clock()
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("Runtime Terminal invalidation clock must be timezone-aware")
    return now
