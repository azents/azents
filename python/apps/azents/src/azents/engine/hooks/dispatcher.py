"""runtime hook dispatcher skeleton."""

import asyncio
import dataclasses
import logging
import time
from collections.abc import Awaitable, Callable, Sequence
from typing import Any, Literal, overload

from azents.core.tools import Toolkit
from azents.engine.hooks.trace import (
    NoopRuntimeHookTraceSink,
    RuntimeHookTraceEvent,
    RuntimeHookTraceSink,
)
from azents.engine.hooks.types import (
    AfterToolCallHookContext,
    BeforeToolCallHookContext,
    CompactionSummaryDecision,
    CompactionSummaryHookContext,
    CompactionSummaryReplace,
    CompactionSummaryUnchanged,
    ObservationRuntimeHookName,
    RuntimeHookName,
    RuntimeHooks,
    SessionIdleHookContext,
    SessionIdleResult,
    ToolCallAllow,
    ToolCallDecision,
    ToolCallDeny,
    ToolOutputDecision,
    ToolOutputReplace,
    ToolOutputUnchanged,
    TurnStartHookContext,
    TurnStartResult,
    normalize_after_tool_call_result,
    normalize_before_tool_call_result,
    normalize_compaction_summary_result,
    normalize_session_idle_result,
    normalize_turn_start_result,
)

logger = logging.getLogger(__name__)

ObservationHook = Callable[[Any], Awaitable[None]]  # noqa: ANN401 — For lifecycle-specific context union casts
TurnStartHook = Callable[[TurnStartHookContext], Awaitable[TurnStartResult | None]]
SessionIdleHook = Callable[
    [SessionIdleHookContext], Awaitable[SessionIdleResult | None]
]
BeforeToolCallHook = Callable[
    [BeforeToolCallHookContext], Awaitable[ToolCallDecision | None]
]
AfterToolCallHook = Callable[
    [AfterToolCallHookContext], Awaitable[ToolOutputDecision | None]
]
CompactionSummaryHook = Callable[
    [CompactionSummaryHookContext], Awaitable[CompactionSummaryDecision | None]
]
RuntimeHook = (
    ObservationHook
    | TurnStartHook
    | SessionIdleHook
    | BeforeToolCallHook
    | AfterToolCallHook
    | CompactionSummaryHook
)


@dataclasses.dataclass(frozen=True)
class RuntimeHookProviderRef:
    """Provider reference called by dispatcher."""

    slug: str
    toolkit: Toolkit[Any]


class RuntimeHookDispatcher:
    """Explicitly dispatch RuntimeHooks mapping."""

    def __init__(
        self,
        *,
        trace_sink: RuntimeHookTraceSink | None = None,
        logger_: logging.Logger | None = None,
    ) -> None:
        self.trace_sink = (
            trace_sink if trace_sink is not None else NoopRuntimeHookTraceSink()
        )
        self.logger = logger_ if logger_ is not None else logger

    async def dispatch_observation(
        self,
        providers: Sequence[RuntimeHookProviderRef],
        lifecycle: ObservationRuntimeHookName,
        context: object,
    ) -> None:
        """Call observation-only lifecycle hooks in provider order."""
        for provider in providers:
            hook = await self._resolve_hook(provider, lifecycle)
            if hook is None:
                continue
            started_at = await self._record_started(provider.slug, lifecycle)
            try:
                await hook(context)
            except asyncio.CancelledError:
                await self._record_cancelled(provider.slug, lifecycle, started_at)
                raise
            except Exception as exc:
                await self._record_failed(provider.slug, lifecycle, started_at, exc)
                self.logger.warning(
                    "Runtime hook failed",
                    exc_info=True,
                    extra={
                        "provider_slug": provider.slug,
                        "lifecycle": lifecycle,
                        "exception_class": type(exc).__name__,
                    },
                )
                continue
            await self._record_completed(
                provider.slug,
                lifecycle,
                started_at,
                result_kind="none",
                short_circuit=False,
            )

    async def dispatch_turn_start(
        self,
        providers: Sequence[RuntimeHookProviderRef],
        context: TurnStartHookContext,
    ) -> TurnStartResult:
        """Merge turn start hook results in provider order."""
        merged = TurnStartResult()
        lifecycle: RuntimeHookName = "on_turn_start"
        for provider in providers:
            hook = await self._resolve_hook(provider, lifecycle)
            if hook is None:
                continue
            started_at = await self._record_started(provider.slug, lifecycle)
            try:
                result = normalize_turn_start_result(await hook(context))
            except asyncio.CancelledError:
                await self._record_cancelled(provider.slug, lifecycle, started_at)
                raise
            except Exception as exc:
                await self._record_failed(provider.slug, lifecycle, started_at, exc)
                self.logger.warning(
                    "Runtime hook failed",
                    exc_info=True,
                    extra={
                        "provider_slug": provider.slug,
                        "lifecycle": lifecycle,
                        "exception_class": type(exc).__name__,
                    },
                )
                continue
            for prompt_index, prompt in enumerate(result.injected_prompts):
                merged.injected_prompts.append(
                    prompt.model_copy(
                        update={
                            "hook_provider_slug": provider.slug,
                            "hook_prompt_index": prompt_index,
                        }
                    )
                )
            await self._record_completed(
                provider.slug,
                lifecycle,
                started_at,
                result_kind="turn_start",
                short_circuit=False,
            )
        return merged

    async def dispatch_session_idle(
        self,
        providers: Sequence[RuntimeHookProviderRef],
        context: SessionIdleHookContext,
    ) -> SessionIdleResult:
        """Merge session idle hook results in provider order."""
        merged = SessionIdleResult()
        lifecycle: RuntimeHookName = "on_session_idle"
        for provider in providers:
            hook = await self._resolve_hook(provider, lifecycle)
            if hook is None:
                continue
            started_at = await self._record_started(provider.slug, lifecycle)
            try:
                result = normalize_session_idle_result(await hook(context))
            except asyncio.CancelledError:
                await self._record_cancelled(provider.slug, lifecycle, started_at)
                raise
            except Exception as exc:
                await self._record_failed(provider.slug, lifecycle, started_at, exc)
                self.logger.warning(
                    "Runtime hook failed",
                    exc_info=True,
                    extra={
                        "provider_slug": provider.slug,
                        "lifecycle": lifecycle,
                        "exception_class": type(exc).__name__,
                    },
                )
                continue
            for continuation_index, continuation in enumerate(result.continuations):
                merged.continuations.append(
                    continuation.model_copy(
                        update={
                            "hook_provider_slug": provider.slug,
                            "hook_continuation_index": continuation_index,
                        }
                    )
                )
            await self._record_completed(
                provider.slug,
                lifecycle,
                started_at,
                result_kind="session_idle",
                short_circuit=False,
            )
        return merged

    async def dispatch_compaction_summary(
        self,
        providers: Sequence[RuntimeHookProviderRef],
        context: CompactionSummaryHookContext,
    ) -> str:
        """Run compaction summary replacement pipeline in provider order."""
        lifecycle: RuntimeHookName = "on_compaction_summary"
        current_summary = context.summary
        for provider in providers:
            hook = await self._resolve_hook(provider, lifecycle)
            if hook is None:
                continue
            provider_context = dataclasses.replace(context, summary=current_summary)
            started_at = await self._record_started(provider.slug, lifecycle)
            try:
                decision = normalize_compaction_summary_result(
                    await hook(provider_context)
                )
            except asyncio.CancelledError:
                await self._record_cancelled(provider.slug, lifecycle, started_at)
                raise
            except Exception as exc:
                decision = CompactionSummaryUnchanged()
                await self._record_failed(provider.slug, lifecycle, started_at, exc)
                self.logger.warning(
                    "Runtime hook failed",
                    exc_info=True,
                    extra={
                        "provider_slug": provider.slug,
                        "lifecycle": lifecycle,
                        "exception_class": type(exc).__name__,
                    },
                )
                continue
            if isinstance(decision, CompactionSummaryReplace):
                current_summary = decision.summary
            await self._record_completed(
                provider.slug,
                lifecycle,
                started_at,
                result_kind=decision.kind,
                short_circuit=False,
            )
        return current_summary

    async def dispatch_before_tool_call(
        self,
        providers: Sequence[RuntimeHookProviderRef],
        context: BeforeToolCallHookContext,
    ) -> ToolCallDecision:
        """Call before tool hook and stop on first deny."""
        lifecycle: RuntimeHookName = "on_before_tool_call"
        for provider in providers:
            hook = await self._resolve_hook(provider, lifecycle)
            if hook is None:
                continue
            started_at = await self._record_started(provider.slug, lifecycle)
            try:
                decision = normalize_before_tool_call_result(await hook(context))
            except asyncio.CancelledError:
                await self._record_cancelled(provider.slug, lifecycle, started_at)
                raise
            except Exception as exc:
                decision = ToolCallAllow()
                await self._record_failed(provider.slug, lifecycle, started_at, exc)
                self.logger.warning(
                    "Runtime hook failed",
                    exc_info=True,
                    extra={
                        "provider_slug": provider.slug,
                        "lifecycle": lifecycle,
                        "exception_class": type(exc).__name__,
                    },
                )
                continue
            short_circuit = isinstance(decision, ToolCallDeny)
            await self._record_completed(
                provider.slug,
                lifecycle,
                started_at,
                result_kind=decision.kind,
                short_circuit=short_circuit,
            )
            if short_circuit:
                return decision
        return ToolCallAllow()

    async def dispatch_after_tool_call(
        self,
        providers: Sequence[RuntimeHookProviderRef],
        context: AfterToolCallHookContext,
    ) -> ToolOutputDecision:
        """Calculate after tool hook pipeline result."""
        lifecycle: RuntimeHookName = "on_after_tool_call"
        current_output = context.output_text
        final_decision: ToolOutputDecision = ToolOutputUnchanged()
        for provider in providers:
            hook = await self._resolve_hook(provider, lifecycle)
            if hook is None:
                continue
            provider_context = dataclasses.replace(context, output_text=current_output)
            started_at = await self._record_started(provider.slug, lifecycle)
            try:
                decision = normalize_after_tool_call_result(
                    await hook(provider_context)
                )
            except asyncio.CancelledError:
                await self._record_cancelled(provider.slug, lifecycle, started_at)
                raise
            except Exception as exc:
                decision = ToolOutputUnchanged()
                await self._record_failed(provider.slug, lifecycle, started_at, exc)
                self.logger.warning(
                    "Runtime hook failed",
                    exc_info=True,
                    extra={
                        "provider_slug": provider.slug,
                        "lifecycle": lifecycle,
                        "exception_class": type(exc).__name__,
                    },
                )
                continue
            if isinstance(decision, ToolOutputReplace):
                current_output = decision.output_text
                final_decision = decision
            await self._record_completed(
                provider.slug,
                lifecycle,
                started_at,
                result_kind=decision.kind,
                short_circuit=False,
            )
        return final_decision

    @overload
    async def _resolve_hook(
        self,
        provider: RuntimeHookProviderRef,
        lifecycle: ObservationRuntimeHookName,
    ) -> ObservationHook | None: ...

    @overload
    async def _resolve_hook(
        self,
        provider: RuntimeHookProviderRef,
        lifecycle: Literal["on_turn_start"],
    ) -> TurnStartHook | None: ...

    @overload
    async def _resolve_hook(
        self,
        provider: RuntimeHookProviderRef,
        lifecycle: Literal["on_session_idle"],
    ) -> SessionIdleHook | None: ...

    @overload
    async def _resolve_hook(
        self,
        provider: RuntimeHookProviderRef,
        lifecycle: Literal["on_before_tool_call"],
    ) -> BeforeToolCallHook | None: ...

    @overload
    async def _resolve_hook(
        self,
        provider: RuntimeHookProviderRef,
        lifecycle: Literal["on_after_tool_call"],
    ) -> AfterToolCallHook | None: ...

    @overload
    async def _resolve_hook(
        self,
        provider: RuntimeHookProviderRef,
        lifecycle: Literal["on_compaction_summary"],
    ) -> CompactionSummaryHook | None: ...

    async def _resolve_hook(
        self,
        provider: RuntimeHookProviderRef,
        lifecycle: RuntimeHookName,
    ) -> RuntimeHook | None:
        """Get lifecycle callback from provider hooks mapping."""
        try:
            hooks: RuntimeHooks = provider.toolkit.hooks()
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            await self._record_event(
                RuntimeHookTraceEvent(
                    provider_slug=provider.slug,
                    lifecycle=lifecycle,
                    status="failed",
                    result_kind=None,
                    exception_class=type(exc).__name__,
                    duration_ms=None,
                    short_circuit=False,
                    cancelled=False,
                    reason="hooks_resolution_failed",
                )
            )
            self.logger.warning(
                "Runtime hooks mapping resolution failed",
                exc_info=True,
                extra={
                    "provider_slug": provider.slug,
                    "lifecycle": lifecycle,
                    "exception_class": type(exc).__name__,
                },
            )
            return None

        hook = hooks.get(lifecycle)
        if hook is None:
            await self._record_event(
                RuntimeHookTraceEvent(
                    provider_slug=provider.slug,
                    lifecycle=lifecycle,
                    status="skipped",
                    result_kind=None,
                    exception_class=None,
                    duration_ms=None,
                    short_circuit=False,
                    cancelled=False,
                    reason="hook_not_registered",
                )
            )
        return hook

    async def _record_started(
        self,
        provider_slug: str,
        lifecycle: RuntimeHookName,
    ) -> float:
        """Record started trace and return start time."""
        started_at = time.perf_counter()
        await self._record_event(
            RuntimeHookTraceEvent(
                provider_slug=provider_slug,
                lifecycle=lifecycle,
                status="started",
                result_kind=None,
                exception_class=None,
                duration_ms=None,
                short_circuit=False,
                cancelled=False,
                reason=None,
            )
        )
        return started_at

    async def _record_completed(
        self,
        provider_slug: str,
        lifecycle: RuntimeHookName,
        started_at: float,
        *,
        result_kind: str,
        short_circuit: bool,
    ) -> None:
        """Record completed trace."""
        await self._record_event(
            RuntimeHookTraceEvent(
                provider_slug=provider_slug,
                lifecycle=lifecycle,
                status="completed",
                result_kind=result_kind,
                exception_class=None,
                duration_ms=self._elapsed_ms(started_at),
                short_circuit=short_circuit,
                cancelled=False,
                reason=None,
            )
        )

    async def _record_failed(
        self,
        provider_slug: str,
        lifecycle: RuntimeHookName,
        started_at: float,
        exc: Exception,
    ) -> None:
        """Record failed trace."""
        await self._record_event(
            RuntimeHookTraceEvent(
                provider_slug=provider_slug,
                lifecycle=lifecycle,
                status="failed",
                result_kind=None,
                exception_class=type(exc).__name__,
                duration_ms=self._elapsed_ms(started_at),
                short_circuit=False,
                cancelled=False,
                reason="hook_failed",
            )
        )

    async def _record_cancelled(
        self,
        provider_slug: str,
        lifecycle: RuntimeHookName,
        started_at: float,
    ) -> None:
        """Record cancelled trace."""
        await self._record_event(
            RuntimeHookTraceEvent(
                provider_slug=provider_slug,
                lifecycle=lifecycle,
                status="cancelled",
                result_kind=None,
                exception_class="CancelledError",
                duration_ms=self._elapsed_ms(started_at),
                short_circuit=False,
                cancelled=True,
                reason="cancelled",
            )
        )

    async def _record_event(self, event: RuntimeHookTraceEvent) -> None:
        """Isolate trace sink failure from hook dispatch."""
        try:
            await self.trace_sink.record(event)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            self.logger.warning(
                "Runtime hook trace sink failed",
                exc_info=True,
                extra={
                    "provider_slug": event.provider_slug,
                    "lifecycle": event.lifecycle,
                    "trace_status": event.status,
                    "exception_class": type(exc).__name__,
                },
            )

    @staticmethod
    def _elapsed_ms(started_at: float) -> float:
        """Calculate elapsed milliseconds based on perf_counter."""
        return (time.perf_counter() - started_at) * 1000
