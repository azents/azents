"""Bounded process-local Job Runtime backend."""

import asyncio
import datetime
import logging
import time
from collections.abc import Callable
from contextlib import AsyncExitStack
from dataclasses import dataclass

from azcommon import di

from azents.job_runtime.types import (
    JobExecutionContext,
    JobHandle,
    JobHandlerRegistry,
    JobOutcome,
    JobPayload,
    JobRequest,
    validate_job_payload,
)

logger = logging.getLogger(__name__)

_SCHEDULER_LEASE_MARGIN_SECONDS = 30.0


class JobRuntimeClosedError(RuntimeError):
    """Raised when new work is submitted during Runtime shutdown."""


@dataclass(frozen=True)
class LocalJobHandle(JobHandle):
    """Handle backed by one strongly owned local asyncio task."""

    task: asyncio.Task[JobOutcome]

    async def wait(self) -> JobOutcome:
        """Wait for the accepted local execution."""
        return await asyncio.shield(self.task)


class LocalJobRuntime:
    """Supervise bounded registered handlers inside one application process."""

    def __init__(
        self,
        *,
        handlers: JobHandlerRegistry,
        container_factory: Callable[[], di.Container],
        max_concurrency: int,
        cancellation_grace_seconds: float,
    ) -> None:
        """Create one bounded process-local Runtime."""
        if max_concurrency < 1:
            raise ValueError("Job Runtime concurrency must be at least one.")
        if (
            cancellation_grace_seconds <= 0
            or cancellation_grace_seconds >= _SCHEDULER_LEASE_MARGIN_SECONDS
        ):
            raise ValueError(
                "Job Runtime cancellation grace must be positive and shorter than "
                "the Scheduler lease margin."
            )
        self.handlers = handlers
        self.container_factory = container_factory
        self.cancellation_grace_seconds = cancellation_grace_seconds
        self._semaphore = asyncio.Semaphore(max_concurrency)
        self._lock = asyncio.Lock()
        self._tasks: dict[str, asyncio.Task[JobOutcome]] = {}
        self._rerun_requests: dict[str, JobRequest] = {}
        self._detached_cleanups: set[asyncio.Task[None]] = set()
        self._detached_execution_keys: set[str] = set()
        self._closed = False
        self._shutdown_drain_seconds: float | None = None

    @property
    def active_count(self) -> int:
        """Return the number of accepted executions not yet settled."""
        return len(self._tasks)

    @property
    def shutdown_drain_seconds(self) -> float | None:
        """Return the duration of the latest completed shutdown drain."""
        return self._shutdown_drain_seconds

    async def submit(self, request: JobRequest) -> JobHandle:
        """Accept one execution or coalesce an already active execution key."""
        async with self._lock:
            if self._closed:
                raise JobRuntimeClosedError("Job Runtime is closing.")
            if self.handlers.get(request.handler_key) is None:
                raise ValueError(
                    f"Unknown registered job handler: {request.handler_key}"
                )
            existing = self._tasks.get(request.execution_key)
            if existing is not None:
                if self.handlers.reruns_on_coalesce(request.handler_key):
                    self._rerun_requests[request.execution_key] = request
                return LocalJobHandle(existing)
            task = asyncio.create_task(
                self._run_tracked(request),
                name=f"job:{request.handler_key}:{request.execution_key}",
            )
            self._tasks[request.execution_key] = task
            return LocalJobHandle(task)

    async def close(self) -> None:
        """Close submission and wait for every accepted bounded execution."""
        started_at = time.perf_counter()
        async with self._lock:
            measure_drain = not self._closed
            if measure_drain:
                self._closed = True
        cancellation: asyncio.CancelledError | None = None
        while True:
            async with self._lock:
                execution_tasks = tuple(set(self._tasks.values()))
                cleanup_tasks = tuple(self._detached_cleanups)
                tasks = tuple({*execution_tasks, *cleanup_tasks})
            if not tasks:
                if measure_drain:
                    self._shutdown_drain_seconds = max(
                        0.0,
                        time.perf_counter() - started_at,
                    )
                if cancellation is not None:
                    raise cancellation
                return
            try:
                await asyncio.gather(*tasks, return_exceptions=True)
            except asyncio.CancelledError as error:
                if cancellation is None:
                    cancellation = error
                for task in execution_tasks:
                    if not task.done():
                        task.cancel()
                await self._wait_for_ownership(tasks)

    async def _run_tracked(self, request: JobRequest) -> JobOutcome:
        """Keep one accepted task registered until its terminal outcome exists."""
        current_request = request
        try:
            while True:
                try:
                    outcome = await self._execute(current_request)
                except asyncio.CancelledError:
                    raise
                except Exception as error:
                    logger.exception(
                        "Registered Job Runtime task escaped structured outcome",
                        extra={"job_execution_key": current_request.execution_key},
                    )
                    outcome = JobOutcome.failed(error)
                current = asyncio.current_task()
                async with self._lock:
                    if current_request.execution_key in self._detached_execution_keys:
                        return outcome
                    rerun = self._rerun_requests.pop(
                        current_request.execution_key,
                        None,
                    )
                    if rerun is None:
                        if self._tasks.get(current_request.execution_key) is current:
                            del self._tasks[current_request.execution_key]
                        return outcome
                    current_request = rerun
        finally:
            current = asyncio.current_task()
            async with self._lock:
                if (
                    request.execution_key not in self._detached_execution_keys
                    and self._tasks.get(request.execution_key) is current
                ):
                    del self._tasks[request.execution_key]
                self._rerun_requests.pop(request.execution_key, None)

    async def _execute(self, request: JobRequest) -> JobOutcome:
        """Run one registered handler inside a task-local DI container."""
        handler = self.handlers.get(request.handler_key)
        if handler is None:
            return JobOutcome.failed(
                ValueError(f"Unknown registered job handler: {request.handler_key}")
            )
        remaining = self._remaining_seconds(request)
        if remaining <= 0:
            return JobOutcome.timed_out()
        try:
            await asyncio.wait_for(self._semaphore.acquire(), timeout=remaining)
        except TimeoutError:
            return JobOutcome.timed_out()

        container_stack: AsyncExitStack | None = AsyncExitStack()
        release_semaphore = True
        try:
            remaining = self._remaining_seconds(request)
            if remaining <= 0:
                return JobOutcome.timed_out()
            container_context = self.container_factory()
            remaining = self._remaining_seconds(request)
            if remaining <= 0:
                return JobOutcome.timed_out()
            try:
                container = await asyncio.wait_for(
                    container_stack.enter_async_context(container_context),
                    timeout=remaining,
                )
            except TimeoutError:
                return JobOutcome.timed_out()
            remaining = self._remaining_seconds(request)
            if remaining <= 0:
                return JobOutcome.timed_out()
            handler_task = asyncio.ensure_future(
                handler(JobExecutionContext(request=request, container=container))
            )
            try:
                done, _ = await asyncio.wait({handler_task}, timeout=remaining)
            except asyncio.CancelledError:
                settled = await self._cancel_handler(handler_task, request=request)
                if not settled:
                    await self._adopt_detached_cleanup(
                        handler_task,
                        container_stack,
                        request=request,
                    )
                    container_stack = None
                    release_semaphore = False
                raise
            if handler_task not in done:
                settled = await self._cancel_handler(handler_task, request=request)
                if not settled:
                    await self._adopt_detached_cleanup(
                        handler_task,
                        container_stack,
                        request=request,
                    )
                    container_stack = None
                    release_semaphore = False
                return JobOutcome.timed_out()
            try:
                result = handler_task.result()
                return JobOutcome.succeeded(
                    None if result is None else validate_job_payload(result)
                )
            except asyncio.CancelledError:
                raise
            except Exception as error:
                return JobOutcome.failed(error)
        finally:
            if container_stack is not None:
                await container_stack.aclose()
            if release_semaphore:
                self._semaphore.release()

    async def _cancel_handler(
        self,
        task: asyncio.Future[JobPayload | None],
        *,
        request: JobRequest,
    ) -> bool:
        """Cancel one handler and report whether it settled within grace."""
        task.cancel()
        done, _ = await asyncio.wait(
            {task},
            timeout=self.cancellation_grace_seconds,
        )
        if task not in done:
            logger.warning(
                "Registered job handler exceeded cancellation grace",
                extra={
                    "job_handler_key": request.handler_key,
                    "job_execution_key": request.execution_key,
                    "job_cancellation_grace_seconds": (self.cancellation_grace_seconds),
                },
            )
            return False
        try:
            await task
        except asyncio.CancelledError:
            pass
        except Exception:
            pass
        return True

    async def _adopt_detached_cleanup(
        self,
        handler_task: asyncio.Future[JobPayload | None],
        container_stack: AsyncExitStack,
        *,
        request: JobRequest,
    ) -> None:
        """Quarantine a cancellation-violating handler with its owned capacity."""
        async with self._lock:
            self._detached_execution_keys.add(request.execution_key)
            cleanup_task = asyncio.create_task(
                self._finish_detached_handler(
                    handler_task,
                    container_stack,
                    request=request,
                ),
                name=f"job-cleanup:{request.handler_key}:{request.execution_key}",
            )
            self._detached_cleanups.add(cleanup_task)
        cleanup_task.add_done_callback(self._consume_detached_cleanup)

    async def _finish_detached_handler(
        self,
        handler_task: asyncio.Future[JobPayload | None],
        container_stack: AsyncExitStack,
        *,
        request: JobRequest,
    ) -> None:
        """Close task-local resources when a non-cooperative handler settles."""
        try:
            while not handler_task.done():
                try:
                    await asyncio.shield(handler_task)
                except asyncio.CancelledError:
                    continue
            try:
                handler_task.result()
            except asyncio.CancelledError:
                pass
            except Exception:
                logger.exception(
                    "Detached registered job handler failed after terminal outcome",
                    extra={
                        "job_handler_key": request.handler_key,
                        "job_execution_key": request.execution_key,
                    },
                )
        finally:
            await container_stack.aclose()
            self._semaphore.release()
            current = asyncio.current_task()
            async with self._lock:
                self._detached_execution_keys.discard(request.execution_key)
                self._tasks.pop(request.execution_key, None)
                self._rerun_requests.pop(request.execution_key, None)
                if current is not None:
                    self._detached_cleanups.discard(current)

    def _consume_detached_cleanup(self, task: asyncio.Task[None]) -> None:
        """Release detached cleanup ownership and consume cancellation."""
        self._detached_cleanups.discard(task)
        try:
            task.result()
        except asyncio.CancelledError:
            return
        except Exception:
            logger.exception("Detached registered job cleanup failed")

    @staticmethod
    async def _wait_for_ownership(
        tasks: tuple[asyncio.Task[JobOutcome] | asyncio.Task[None], ...],
    ) -> None:
        """Ignore repeated close cancellation until owned tasks settle."""
        group = asyncio.gather(*tasks, return_exceptions=True)
        while not group.done():
            try:
                await asyncio.shield(group)
            except asyncio.CancelledError:
                continue

    @staticmethod
    def _remaining_seconds(request: JobRequest) -> float:
        """Return seconds remaining before one request's absolute deadline."""
        return (request.deadline - datetime.datetime.now(datetime.UTC)).total_seconds()
