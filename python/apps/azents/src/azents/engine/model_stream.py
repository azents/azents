"""Application-owned streaming model watchdog and cleanup ownership."""

import asyncio
import dataclasses
import logging
import math
from collections.abc import AsyncIterable, AsyncIterator, Awaitable, Callable
from typing import Annotated, Literal, Protocol, TypeVar

import httpx
from fastapi import Depends
from litellm.exceptions import Timeout as LiteLLMTimeout
from openai import APITimeoutError

from azents.core.config import Config
from azents.core.deps import get_appctx
from azents.engine.run.errors import (
    ModelStreamCallKind,
    ModelStreamTimeoutError,
)
from azents.engine.run.types import USER_STOP_CANCEL_MESSAGE
from azents.utils.appctx import AppContext

logger = logging.getLogger(__name__)

ModelStreamCleanupReason = Literal[
    "timeout",
    "caller_cancelled",
    "shutdown",
]

T = TypeVar("T")


@dataclasses.dataclass(frozen=True)
class ModelStreamTimeoutPolicy:
    """Effective deadlines for one streaming model call."""

    connect_timeout_seconds: float
    parsed_event_idle_timeout_seconds: float
    absolute_attempt_timeout_seconds: float

    def __post_init__(self) -> None:
        """Validate finite positive deadline values."""
        for field in dataclasses.fields(self):
            value = getattr(self, field.name)
            if not math.isfinite(value) or value <= 0:
                raise ValueError(f"{field.name} must be finite and greater than zero")


@dataclasses.dataclass(frozen=True)
class ModelStreamSpecificPolicyOverride:
    """One model or inference-profile override at the same specificity tier."""

    policy: ModelStreamTimeoutPolicy
    model: str | None
    inference_profile: str | None

    def __post_init__(self) -> None:
        """Require exactly one specific selector."""
        if (self.model is None) == (self.inference_profile is None):
            raise ValueError(
                "exactly one of model or inference_profile must be configured"
            )


@dataclasses.dataclass(frozen=True)
class ModelStreamProviderPolicyOverride:
    """One provider-specific timeout policy override."""

    provider: str
    policy: ModelStreamTimeoutPolicy


@dataclasses.dataclass(frozen=True)
class ModelStreamTimeoutPolicyResolver:
    """Resolve immutable model-stream policy from most specific to default."""

    default: ModelStreamTimeoutPolicy
    provider_overrides: tuple[ModelStreamProviderPolicyOverride, ...]
    specific_overrides: tuple[ModelStreamSpecificPolicyOverride, ...]

    def resolve(
        self,
        *,
        provider: str,
        model: str,
        inference_profile: str | None,
    ) -> ModelStreamTimeoutPolicy:
        """Resolve the unambiguous specific tier, provider, then default."""
        specific_matches = [
            override
            for override in self.specific_overrides
            if override.model == model
            or (
                inference_profile is not None
                and override.inference_profile == inference_profile
            )
        ]
        if len(specific_matches) > 1:
            raise ValueError("model stream timeout specific overrides are ambiguous")
        if specific_matches:
            return specific_matches[0].policy
        provider_matches = [
            override
            for override in self.provider_overrides
            if override.provider == provider
        ]
        if len(provider_matches) > 1:
            raise ValueError("model stream timeout provider overrides are ambiguous")
        if provider_matches:
            return provider_matches[0].policy
        return self.default


@dataclasses.dataclass(frozen=True)
class ModelStreamCallContext:
    """Safe operational identity for one streaming model call."""

    call_kind: ModelStreamCallKind
    provider: str
    model: str
    session_id: str | None
    run_id: str | None
    attempt_number: int | None
    check_stop: Callable[[], Awaitable[bool]] | None


class ModelStreamClock(Protocol):
    """Monotonic clock used by deterministic watchdog tests."""

    def time(self) -> float:
        """Return monotonic seconds."""
        ...

    async def sleep(self, delay: float) -> None:
        """Sleep for monotonic seconds."""
        ...


class AsyncioModelStreamClock:
    """Production clock backed by the active asyncio event loop."""

    def time(self) -> float:
        """Return event-loop monotonic seconds."""
        return asyncio.get_running_loop().time()

    async def sleep(self, delay: float) -> None:
        """Sleep with asyncio."""
        await asyncio.sleep(delay)


@dataclasses.dataclass(frozen=True)
class ModelStreamCleanupMetadata:
    """Metadata retained while detached model cleanup is process-owned."""

    context: ModelStreamCallContext
    reason: ModelStreamCleanupReason
    adopted_at: float


class ModelStreamCleanupRegistry:
    """Own non-cooperative model stream cleanup until completion or exit."""

    def __init__(self, *, clock: ModelStreamClock) -> None:
        """Inject the monotonic clock."""
        self.clock = clock
        self._tasks: dict[asyncio.Task[None], ModelStreamCleanupMetadata] = {}

    @property
    def active_count(self) -> int:
        """Return the number of process-owned cleanup tasks."""
        return len(self._tasks)

    def adopt(
        self,
        task: asyncio.Task[None],
        *,
        context: ModelStreamCallContext,
        reason: ModelStreamCleanupReason,
    ) -> None:
        """Take strong ownership and consume the eventual task outcome."""
        metadata = ModelStreamCleanupMetadata(
            context=context,
            reason=reason,
            adopted_at=self.clock.time(),
        )
        self._tasks[task] = metadata
        logger.warning(
            "Model stream cleanup adopted",
            extra={
                **_context_log_fields(context),
                "cleanup_reason": reason,
                "cleanup_active_count": self.active_count,
            },
        )
        task.add_done_callback(self._consume_done)

    def _consume_done(self, task: asyncio.Task[None]) -> None:
        metadata = self._tasks.pop(task, None)
        if metadata is None:
            return
        try:
            task.result()
        except asyncio.CancelledError:
            outcome = "cancelled"
        except Exception:
            outcome = "failed"
            logger.warning(
                "Model stream cleanup failed",
                extra={
                    **_context_log_fields(metadata.context),
                    "cleanup_reason": metadata.reason,
                    "cleanup_age_seconds": round(
                        self.clock.time() - metadata.adopted_at,
                        3,
                    ),
                    "cleanup_active_count": self.active_count,
                },
                exc_info=True,
            )
        else:
            outcome = "completed"
        if outcome != "failed":
            logger.info(
                "Model stream cleanup settled",
                extra={
                    **_context_log_fields(metadata.context),
                    "cleanup_reason": metadata.reason,
                    "cleanup_outcome": outcome,
                    "cleanup_age_seconds": round(
                        self.clock.time() - metadata.adopted_at,
                        3,
                    ),
                    "cleanup_active_count": self.active_count,
                },
            )

    async def drain(self, *, grace_seconds: float) -> int:
        """Cancel registered cleanup and wait only through the shutdown grace."""
        if not math.isfinite(grace_seconds) or grace_seconds <= 0:
            raise ValueError("grace_seconds must be finite and greater than zero")
        tasks = list(self._tasks)
        if not tasks:
            return 0
        for task in tasks:
            task.cancel()
        grace_task = asyncio.create_task(self.clock.sleep(grace_seconds))
        drain_task = asyncio.create_task(_wait_for_tasks(tasks))
        done, _ = await asyncio.wait(
            {drain_task, grace_task},
            return_when=asyncio.FIRST_COMPLETED,
        )
        if drain_task in done:
            grace_task.cancel()
            await _consume_task(grace_task)
            await _consume_task(drain_task)
        else:
            drain_task.cancel()
            await _consume_task(drain_task)
        pending_count = sum(not task.done() for task in tasks)
        if pending_count:
            logger.warning(
                "Model stream cleanup remains pending at shutdown",
                extra={
                    "cleanup_pending_count": pending_count,
                    "cleanup_active_count": self.active_count,
                    "cleanup_shutdown_grace_seconds": grace_seconds,
                },
            )
        return pending_count


@dataclasses.dataclass
class _ModelStreamCallState:
    """Mutable timing state shared across response open and iteration."""

    context: ModelStreamCallContext
    policy: ModelStreamTimeoutPolicy
    started_at: float
    idle_deadline: float
    absolute_deadline: float
    response_handle_at: float | None = None
    first_event_at: float | None = None
    previous_event_at: float | None = None
    maximum_event_gap_seconds: float = 0
    event_count: int = 0
    terminal_logged: bool = False


@dataclasses.dataclass(frozen=True)
class _DeadlineReached(Exception):
    """Internal deadline signal before typed model timeout conversion."""

    kind: Literal["parsed_event_idle", "absolute_attempt"]


class ModelStreamWatchdog:
    """Bound streaming response acquisition, parsed-event idle, and duration."""

    def __init__(
        self,
        *,
        resolver: ModelStreamTimeoutPolicyResolver,
        cleanup_registry: ModelStreamCleanupRegistry,
        close_grace_seconds: float,
        clock: ModelStreamClock,
    ) -> None:
        """Inject immutable policy, cleanup ownership, and time source."""
        if not math.isfinite(close_grace_seconds) or close_grace_seconds <= 0:
            raise ValueError("close_grace_seconds must be finite and greater than zero")
        self.resolver = resolver
        self.cleanup_registry = cleanup_registry
        self.close_grace_seconds = close_grace_seconds
        self.clock = clock

    def resolve_policy(
        self,
        *,
        provider: str,
        model: str,
        inference_profile: str | None,
    ) -> ModelStreamTimeoutPolicy:
        """Resolve the effective policy once for a streaming call."""
        return self.resolver.resolve(
            provider=provider,
            model=model,
            inference_profile=inference_profile,
        )

    async def open_response(
        self,
        factory: Callable[[], Awaitable[object]],
        *,
        policy: ModelStreamTimeoutPolicy,
        context: ModelStreamCallContext,
    ) -> object:
        """Watch response-handle acquisition and return a watched iterable."""
        state = self._start_state(policy=policy, context=context)
        operation = asyncio.create_task(_await_factory(factory))
        try:
            response = await self._wait_for_operation(operation, state=state)
        except asyncio.CancelledError:
            await self._cleanup_after_caller_cancel(
                operation,
                resource=None,
                context=context,
            )
            self._log_terminal(state, outcome="cancelled", failure_code=None)
            raise
        except _DeadlineReached as reached:
            await self._cleanup_after_timeout(
                operation,
                resource=None,
                context=context,
            )
            error = self._deadline_error(reached.kind, state=state)
            self._log_terminal(
                state, outcome="timeout", failure_code=error.failure_code
            )
            raise error from None
        except (LiteLLMTimeout, APITimeoutError) as exc:
            error = self._connect_error(state=state)
            self._log_terminal(
                state, outcome="timeout", failure_code=error.failure_code
            )
            raise error from exc
        except Exception:
            self._log_terminal(state, outcome="failed", failure_code=None)
            raise
        state.response_handle_at = self.clock.time()
        if not isinstance(response, AsyncIterable):
            self._log_terminal(state, outcome="completed", failure_code=None)
            return response
        return self.watch_iterable(
            response, policy=policy, context=context, state=state
        )

    async def watch_iterable(
        self,
        source: AsyncIterable[T],
        *,
        policy: ModelStreamTimeoutPolicy,
        context: ModelStreamCallContext,
        state: _ModelStreamCallState | None = None,
    ) -> AsyncIterator[T]:
        """Yield parsed provider events within idle and absolute deadlines."""
        call_state = state or self._start_state(policy=policy, context=context)
        iterator = source.__aiter__()
        cleanup_started = False
        completed = False
        try:
            while True:
                operation = asyncio.create_task(_next_item(iterator))
                try:
                    event = await self._wait_for_operation(operation, state=call_state)
                except StopAsyncIteration:
                    completed = True
                    self._log_terminal(
                        call_state,
                        outcome="completed",
                        failure_code=None,
                    )
                    return
                except asyncio.CancelledError:
                    cleanup_started = True
                    await self._cleanup_after_caller_cancel(
                        operation,
                        resource=iterator,
                        context=context,
                    )
                    self._log_terminal(
                        call_state,
                        outcome="cancelled",
                        failure_code=None,
                    )
                    raise
                except _DeadlineReached as reached:
                    cleanup_started = True
                    await self._cleanup_after_timeout(
                        operation,
                        resource=iterator,
                        context=context,
                    )
                    error = self._deadline_error(reached.kind, state=call_state)
                    self._log_terminal(
                        call_state,
                        outcome="timeout",
                        failure_code=error.failure_code,
                    )
                    raise error from None
                except (LiteLLMTimeout, APITimeoutError) as exc:
                    cleanup_started = True
                    await self._cleanup_after_timeout(
                        operation,
                        resource=iterator,
                        context=context,
                    )
                    error = self._connect_error(state=call_state)
                    self._log_terminal(
                        call_state,
                        outcome="timeout",
                        failure_code=error.failure_code,
                    )
                    raise error from exc
                except Exception:
                    self._log_terminal(
                        call_state,
                        outcome="failed",
                        failure_code=None,
                    )
                    raise
                now = self.clock.time()
                if call_state.first_event_at is None:
                    call_state.first_event_at = now
                    logger.info(
                        "Model stream first parsed event received",
                        extra={
                            **_context_log_fields(context),
                            "model_stream_first_event_seconds": round(
                                now - call_state.started_at,
                                3,
                            ),
                        },
                    )
                previous = call_state.previous_event_at or call_state.started_at
                call_state.maximum_event_gap_seconds = max(
                    call_state.maximum_event_gap_seconds,
                    now - previous,
                )
                call_state.previous_event_at = now
                call_state.event_count += 1
                call_state.idle_deadline = (
                    now + policy.parsed_event_idle_timeout_seconds
                )
                yield event
        finally:
            if not completed and not cleanup_started:
                self._log_terminal(
                    call_state,
                    outcome="cancelled",
                    failure_code=None,
                )
                await self._cleanup_after_caller_cancel(
                    None,
                    resource=iterator,
                    context=context,
                )

    def _start_state(
        self,
        *,
        policy: ModelStreamTimeoutPolicy,
        context: ModelStreamCallContext,
    ) -> _ModelStreamCallState:
        started_at = self.clock.time()
        logger.info(
            "Model stream started",
            extra={
                **_context_log_fields(context),
                "model_stream_connect_timeout_seconds": (
                    policy.connect_timeout_seconds
                ),
                "model_stream_idle_timeout_seconds": (
                    policy.parsed_event_idle_timeout_seconds
                ),
                "model_stream_absolute_timeout_seconds": (
                    policy.absolute_attempt_timeout_seconds
                ),
            },
        )
        return _ModelStreamCallState(
            context=context,
            policy=policy,
            started_at=started_at,
            idle_deadline=started_at + policy.parsed_event_idle_timeout_seconds,
            absolute_deadline=started_at + policy.absolute_attempt_timeout_seconds,
        )

    async def _wait_for_operation(
        self,
        operation: asyncio.Task[T],
        *,
        state: _ModelStreamCallState,
    ) -> T:
        now = self.clock.time()
        idle_remaining = state.idle_deadline - now
        absolute_remaining = state.absolute_deadline - now
        if idle_remaining <= 0 or absolute_remaining <= 0:
            await self._prefer_user_stop(state.context)
            if absolute_remaining <= idle_remaining:
                raise _DeadlineReached("absolute_attempt")
            raise _DeadlineReached("parsed_event_idle")

        idle_task = asyncio.create_task(self.clock.sleep(idle_remaining))
        absolute_task = asyncio.create_task(self.clock.sleep(absolute_remaining))
        try:
            done, _ = await asyncio.wait(
                {operation, idle_task, absolute_task},
                return_when=asyncio.FIRST_COMPLETED,
            )
        finally:
            for timer in (idle_task, absolute_task):
                if not timer.done():
                    timer.cancel()
            await asyncio.gather(idle_task, absolute_task, return_exceptions=True)

        if operation in done:
            return operation.result()
        await asyncio.sleep(0)
        await self._prefer_user_stop(state.context)
        if absolute_task in done:
            raise _DeadlineReached("absolute_attempt")
        raise _DeadlineReached("parsed_event_idle")

    async def _prefer_user_stop(self, context: ModelStreamCallContext) -> None:
        if context.check_stop is not None and await context.check_stop():
            raise asyncio.CancelledError(USER_STOP_CANCEL_MESSAGE)

    async def _cleanup_after_timeout(
        self,
        operation: asyncio.Task[object],
        *,
        resource: object | None,
        context: ModelStreamCallContext,
    ) -> None:
        cleanup = asyncio.create_task(_cleanup_stream_operation(operation, resource))
        grace = asyncio.create_task(self.clock.sleep(self.close_grace_seconds))
        try:
            done, _ = await asyncio.wait(
                {cleanup, grace},
                return_when=asyncio.FIRST_COMPLETED,
            )
        except asyncio.CancelledError as exc:
            grace.cancel()
            await _consume_task(grace)
            if not cleanup.done():
                self.cleanup_registry.adopt(
                    cleanup,
                    context=context,
                    reason="timeout",
                )
            if _is_user_stop_cancellation(exc):
                current = asyncio.current_task()
                if current is not None:
                    current.uncancel()
                return
            raise
        if cleanup in done:
            grace.cancel()
            await _consume_task(grace)
            await self._consume_cleanup_task(
                cleanup,
                context=context,
                reason="timeout",
            )
            return
        self.cleanup_registry.adopt(
            cleanup,
            context=context,
            reason="timeout",
        )

    async def _cleanup_after_caller_cancel(
        self,
        operation: asyncio.Task[object] | None,
        *,
        resource: object | None,
        context: ModelStreamCallContext,
    ) -> None:
        cleanup = asyncio.create_task(_cleanup_stream_operation(operation, resource))
        await asyncio.sleep(0)
        if cleanup.done():
            await self._consume_cleanup_task(
                cleanup,
                context=context,
                reason="caller_cancelled",
            )
            return
        self.cleanup_registry.adopt(
            cleanup,
            context=context,
            reason="caller_cancelled",
        )

    async def _consume_cleanup_task(
        self,
        task: asyncio.Task[None],
        *,
        context: ModelStreamCallContext,
        reason: ModelStreamCleanupReason,
    ) -> None:
        """Consume cooperative cleanup and report a close failure once."""
        try:
            await task
        except asyncio.CancelledError:
            return
        except Exception:
            logger.warning(
                "Model stream cleanup failed",
                extra={
                    **_context_log_fields(context),
                    "cleanup_reason": reason,
                    "cleanup_active_count": self.cleanup_registry.active_count,
                },
                exc_info=True,
            )

    def _connect_error(
        self, *, state: _ModelStreamCallState
    ) -> ModelStreamTimeoutError:
        return ModelStreamTimeoutError(
            timeout_kind="connect",
            deadline_seconds=state.policy.connect_timeout_seconds,
            elapsed_seconds=self.clock.time() - state.started_at,
            call_kind=state.context.call_kind,
            provider=state.context.provider,
            model=state.context.model,
        )

    def _deadline_error(
        self,
        kind: Literal["parsed_event_idle", "absolute_attempt"],
        *,
        state: _ModelStreamCallState,
    ) -> ModelStreamTimeoutError:
        deadline = (
            state.policy.parsed_event_idle_timeout_seconds
            if kind == "parsed_event_idle"
            else state.policy.absolute_attempt_timeout_seconds
        )
        return ModelStreamTimeoutError(
            timeout_kind=kind,
            deadline_seconds=deadline,
            elapsed_seconds=self.clock.time() - state.started_at,
            call_kind=state.context.call_kind,
            provider=state.context.provider,
            model=state.context.model,
        )

    def _log_terminal(
        self,
        state: _ModelStreamCallState,
        *,
        outcome: str,
        failure_code: str | None,
    ) -> None:
        if state.terminal_logged:
            return
        state.terminal_logged = True
        now = self.clock.time()
        log = logger.warning if outcome in {"timeout", "failed"} else logger.info
        messages = {
            "completed": "Model stream completed",
            "cancelled": "Model stream cancelled",
            "failed": "Model stream failed",
            "timeout": "Model stream timed out",
        }
        log(
            messages.get(outcome, "Model stream terminated"),
            extra={
                **_context_log_fields(state.context),
                "model_stream_outcome": outcome,
                "model_stream_failure_code": failure_code,
                "model_stream_total_seconds": round(now - state.started_at, 3),
                "model_stream_response_handle_seconds": (
                    round(state.response_handle_at - state.started_at, 3)
                    if state.response_handle_at is not None
                    else None
                ),
                "model_stream_first_event_seconds": (
                    round(state.first_event_at - state.started_at, 3)
                    if state.first_event_at is not None
                    else None
                ),
                "model_stream_maximum_event_gap_seconds": round(
                    state.maximum_event_gap_seconds,
                    3,
                ),
                "model_stream_event_count": state.event_count,
            },
        )


async def _await_factory(factory: Callable[[], Awaitable[T]]) -> T:
    """Await one response factory in a concrete coroutine task."""
    return await factory()


async def _next_item(iterator: AsyncIterator[T]) -> T:
    """Await one parsed event in a concrete coroutine task."""
    return await anext(iterator)


async def _cleanup_stream_operation(
    operation: asyncio.Task[object] | None,
    resource: object | None,
) -> None:
    """Cancel an active wait, discard its late result, then close its resource."""
    late_result: object | None = None
    if operation is not None:
        operation.cancel()
        try:
            late_result = await operation
        except asyncio.CancelledError:
            pass
        except Exception:
            pass
    resource_to_close = resource if resource is not None else late_result
    await close_stream_response(resource_to_close)


async def _wait_for_tasks(tasks: list[asyncio.Task[None]]) -> None:
    """Wait for a registry snapshot without propagating cancellation to it."""
    await asyncio.wait(tasks)


async def _consume_task(task: asyncio.Task[object]) -> None:
    """Consume success, cancellation, or failure from an owned task."""
    try:
        await task
    except asyncio.CancelledError:
        return
    except Exception:
        return


async def close_stream_response(response: object | None) -> None:
    """Close a watched response wrapper after its consumer exits."""
    if response is None:
        return
    close = getattr(response, "aclose", None) or getattr(response, "close", None)
    if not callable(close):
        return
    result = close()
    if isinstance(result, Awaitable):
        await result


def connect_only_http_timeout(connect_timeout_seconds: float) -> httpx.Timeout:
    """Build an HTTP timeout that limits only connection establishment."""
    if not math.isfinite(connect_timeout_seconds) or connect_timeout_seconds <= 0:
        raise ValueError("connect_timeout_seconds must be finite and greater than zero")
    return httpx.Timeout(None, connect=connect_timeout_seconds)


def _context_log_fields(context: ModelStreamCallContext) -> dict[str, object]:
    return {
        "session_id": context.session_id,
        "run_id": context.run_id,
        "model_stream_call_kind": context.call_kind,
        "provider": context.provider,
        "model": context.model,
        "model_stream_attempt_number": context.attempt_number,
    }


def _is_user_stop_cancellation(exc: asyncio.CancelledError) -> bool:
    return any(arg == USER_STOP_CANCEL_MESSAGE for arg in exc.args)


async def get_model_stream_watchdog(
    appctx: Annotated[AppContext[Config], Depends(get_appctx)],
) -> ModelStreamWatchdog:
    """Return the process-owned watchdog and drain cleanup during shutdown."""

    async def create() -> AsyncIterator[ModelStreamWatchdog]:
        clock = AsyncioModelStreamClock()
        timeout_config = appctx.config.model_stream_timeout
        policy = ModelStreamTimeoutPolicy(
            connect_timeout_seconds=timeout_config.connect_timeout_seconds,
            parsed_event_idle_timeout_seconds=(
                timeout_config.parsed_event_idle_timeout_seconds
            ),
            absolute_attempt_timeout_seconds=(
                timeout_config.absolute_attempt_timeout_seconds
            ),
        )
        close_grace_seconds = timeout_config.close_grace_seconds
        registry = ModelStreamCleanupRegistry(clock=clock)
        watchdog = ModelStreamWatchdog(
            resolver=ModelStreamTimeoutPolicyResolver(
                default=policy,
                provider_overrides=(),
                specific_overrides=(),
            ),
            cleanup_registry=registry,
            close_grace_seconds=close_grace_seconds,
            clock=clock,
        )
        try:
            yield watchdog
        finally:
            await registry.drain(grace_seconds=close_grace_seconds)

    return await appctx.get_variable(f"{__name__}.get_model_stream_watchdog", create)
