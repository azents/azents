"""Browser-only transitions, exact intent fencing and independent Runner lifetime."""

import asyncio
import logging
from collections.abc import Callable
from contextlib import asynccontextmanager
from typing import AsyncIterator

from azents_runtime_control.browser_configuration import (
    BrowserConfigurationRequest,
    BrowserConfigurationStatus,
    BrowserImplementation,
)
from azents_runtime_control.browser_contract import BrowserCommand, BrowserResult
from azents_runtime_control.runtime_stream_session import BrowserStreamAuthority

from azents_runtime_runner.browser import BrowserFailure, RunnerBrowserManager
from azents_runtime_runner.browser_input import BrowserInputKey
from azents_runtime_runner.browser_viewer import (
    RunnerBrowserViewer,
    ViewerReceive,
    ViewerSend,
)
from azents_runtime_runner.diagnostics import (
    RunnerDiagnosticReason,
    runner_exception_diagnostic,
)


class RunnerBrowserController:
    """Own only browser managers, captures and operations, never shell state."""

    def __init__(
        self,
        manager_factory: Callable[[BrowserImplementation], RunnerBrowserManager],
        viewer_factory: Callable[[RunnerBrowserManager], RunnerBrowserViewer],
        input_key: BrowserInputKey,
    ) -> None:
        self.manager_factory = manager_factory
        self.viewer_factory = viewer_factory
        self.input_key = input_key
        self.runtime_id: str | None = None
        self.generation: Callable[[], int | None] | None = None
        self.manager: RunnerBrowserManager | None = None
        self.viewer: RunnerBrowserViewer | None = None
        self.status = BrowserConfigurationStatus(None, None, "unconfigured", None)
        self.transition_lock = asyncio.Lock()
        self.transitions: set[asyncio.Task[None]] = set()
        self.active: set[asyncio.Task[object]] = set()
        self.retirement_failed = False
        self.closed = False

    def bind_runtime(
        self, runtime_id: str, generation: Callable[[], int | None]
    ) -> None:
        if self.runtime_id is not None:
            raise ValueError("Browser controller Runtime is already bound")
        self.runtime_id = runtime_id
        self.generation = generation

    def validate_operation(self, runtime_id: str, generation: int) -> None:
        if (
            self.runtime_id != runtime_id
            or self.generation is None
            or self.generation() != generation
        ):
            raise BrowserFailure(
                "browser_stale_generation",
                "Browser Runtime generation is no longer current",
            )

    async def configure(
        self, request: BrowserConfigurationRequest
    ) -> BrowserConfigurationStatus:
        if self.closed:
            raise BrowserFailure("browser_unavailable", "Browser controller is closed")
        if request.intent_id == self.status.intent_id:
            if request.implementation != self.status.implementation:
                raise BrowserFailure(
                    "browser_invalid_configuration",
                    "Browser intent cannot change implementation",
                )
            # Status reconciliation never restarts a correct or failed browser.
            return self.status
        if request.expected_intent_id != self.status.intent_id:
            raise BrowserFailure(
                "browser_stale_configuration", "Browser configuration intent is stale"
            )
        self.status = BrowserConfigurationStatus(
            request.intent_id, request.implementation, "applying", None
        )
        # Fence every old native input/effect before the first suspension point.
        if self.manager is not None:
            self.manager.closed = True
        for active in tuple(self.active):
            active.cancel()
        transition = asyncio.create_task(
            self._apply(request), name="browser-transition"
        )
        self.transitions.add(transition)
        try:
            # A lost control response must not cancel a partially applied switch.
            await asyncio.shield(transition)
        finally:
            if transition.done():
                self.transitions.discard(transition)
        return self.status

    async def _apply(self, request: BrowserConfigurationRequest) -> None:
        async with self.transition_lock:
            if self.status.intent_id != request.intent_id or self.closed:
                return
            try:
                await self._retire()
                if self.status.intent_id != request.intent_id or self.closed:
                    return
                if self.retirement_failed:
                    raise BrowserFailure(
                        "browser_cleanup_failed",
                        "Prior browser retirement is unconfirmed",
                    )
                manager = self.manager_factory(request.implementation)
                self.manager = manager
                await manager.initialize()
                if self.status.intent_id != request.intent_id or self.closed:
                    manager.closed = True
                    return
                self.viewer = self.viewer_factory(manager)
                self.status = BrowserConfigurationStatus(
                    request.intent_id, request.implementation, "ready", None
                )
            except asyncio.CancelledError:
                raise
            except BrowserFailure as error:
                if self.manager is not None:
                    self.manager.closed = True
                if self.status.intent_id == request.intent_id:
                    self.status = BrowserConfigurationStatus(
                        request.intent_id, request.implementation, "failed", error.code
                    )
            except Exception as error:
                # This independently owned application task must publish failed
                # evidence even if its caller lost the control connection.
                diagnostic = runner_exception_diagnostic(
                    error, RunnerDiagnosticReason.BROWSER_APPLICATION_FAILED
                )
                logging.getLogger(__name__).error(
                    "Browser application failed",
                    exc_info=diagnostic.exc_info,
                    extra={
                        **diagnostic.log_fields(),
                        "intent_id": request.intent_id,
                        "implementation": request.implementation.value,
                    },
                )
                if self.manager is not None:
                    self.manager.closed = True
                if self.status.intent_id == request.intent_id:
                    self.status = BrowserConfigurationStatus(
                        request.intent_id,
                        request.implementation,
                        "failed",
                        "browser_application_failed",
                    )

    async def _retire(self) -> None:
        active = tuple(self.active)
        for task in active:
            task.cancel()
        await asyncio.gather(*active, return_exceptions=True)
        try:
            if self.viewer is not None:
                await self.viewer.close()
        except asyncio.CancelledError:
            raise
        except Exception:
            self.retirement_failed = True
            raise
        finally:
            self.viewer = None
            if self.manager is not None:
                try:
                    await self.manager.close()
                except asyncio.CancelledError:
                    raise
                except Exception:
                    self.retirement_failed = True
                    raise
                else:
                    self.manager = None

    @asynccontextmanager
    async def _track(self) -> AsyncIterator[None]:
        task = asyncio.current_task()
        if task is None:
            raise RuntimeError("Browser work has no owning task")
        self.active.add(task)
        try:
            yield
        finally:
            self.active.discard(task)

    def _ready(self) -> RunnerBrowserManager:
        if self.closed or self.status.state != "ready" or self.manager is None:
            raise BrowserFailure(
                "browser_unavailable", "Browser configuration is not ready"
            )
        return self.manager

    async def execute(self, intent_id: str, command: BrowserCommand) -> BrowserResult:
        if intent_id != self.status.intent_id:
            raise BrowserFailure(
                "browser_stale_configuration", "Browser intent is stale"
            )
        manager = self._ready()
        async with self._track():
            return await manager.execute(command)

    def validate(self, authority: BrowserStreamAuthority) -> None:
        self._ready().viewer_authority(authority)

    async def run(
        self,
        authority: BrowserStreamAuthority,
        receive: ViewerReceive,
        send: ViewerSend,
    ) -> None:
        self.validate(authority)
        viewer = self.viewer
        if viewer is None:
            raise BrowserFailure("browser_unavailable", "Browser viewer is unavailable")
        async with self._track():
            await viewer.run(authority, receive, send)

    async def close(self) -> None:
        self.closed = True
        if self.manager is not None:
            self.manager.closed = True
        await asyncio.gather(*self.transitions)
        self.transitions.clear()
        await self._retire()
