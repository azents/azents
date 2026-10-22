"""Independent model-visible interruptible wait Toolkit."""

import asyncio
import dataclasses
import json
import logging
import time

from azents_runtime_control.process_observation import ProcessObservation
from pydantic import BaseModel, ConfigDict, Field

from azents.core.mailbox_activity import MailboxActivityObserverProtocol
from azents.core.tools import (
    FunctionTool,
    Toolkit,
    ToolkitState,
    ToolkitStatus,
    TurnContext,
)
from azents.engine.run.types import FunctionToolError, FunctionToolResult
from azents.engine.tooling.make_tool import make_tool
from azents.engine.tools.process_wait import ProcessWaitSource, ProcessWaitTarget
from azents.engine.tools.runtime_io import (
    RuntimeRunnerOperationFailedError,
    RuntimeRunnerOperationGenerationError,
    RuntimeRunnerOperationUnavailable,
)
from azents.services.agent_wait import WaitObservation, WaitStateReader

logger = logging.getLogger(__name__)
_OBSERVATION_CLEANUP_GRACE_SECONDS = 1.0


class WaitToolkitConfig(BaseModel):
    """Stateless Wait Toolkit configuration."""


@dataclasses.dataclass(frozen=True)
class _ShellObservation:
    target: ProcessWaitTarget
    state: ProcessObservation


class WaitToolkit(Toolkit[WaitToolkitConfig]):
    """Wait for input, descendant activity, or non-detached shell completion."""

    def __init__(
        self, *, wait_service: WaitStateReader, process_source: ProcessWaitSource | None
    ) -> None:
        self.wait_service = wait_service
        self.process_source = process_source
        self.session_id: str | None = None
        self.observer: MailboxActivityObserverProtocol | None = None
        self.cleanup_tasks: set[asyncio.Task[object]] = set()

    async def update_context(self, context: TurnContext) -> ToolkitState:
        """Bind current Session and Run-scoped mailbox observer."""
        self.session_id = context.session_id
        self.observer = context.mailbox_activity_observer
        return ToolkitState(status=ToolkitStatus.ENABLED, tools=[self._wait_tool()])

    async def get_static_prompt(self, context: TurnContext) -> str:
        """Return pre-discovery guidance for shared waiting."""
        del context
        return (
            "Use wait while descendant work or ordinary shell commands are active. "
            "New input or shell completion can end waiting; wait does not consume "
            "input or shell output. Fire-and-forget commands do not affect wait."
        )

    def _wait_tool(self) -> FunctionTool:
        async def wait(input: _WaitInput) -> str | FunctionToolResult:
            """Wait without selecting targets or consuming results."""
            if self.observer is None:
                raise FunctionToolError("Mailbox activity observer is unavailable")
            return await self._wait(input.timeout_seconds)

        return make_tool(
            wait,
            name="wait",
            description=(
                "Wait for new input, descendant work, or ordinary shell completion. "
                "Returns early on user/agent messages, scheduled or external-channel "
                "activity, actions, or a new shell completion; also returns for no "
                "eligible work or timeout. Fire-and-forget commands are excluded. "
                "Does not consume input or shell output; collect output with "
                "write_stdin. Only the timeout is required; targets are automatic."
            ),
        )

    async def _observe_shell(self, timeout_seconds: int) -> _ShellObservation | None:
        if self.process_source is None or self.session_id is None:
            return None
        target = await self.process_source.process_wait_target()
        if target is None:
            return None
        after_revision = await self.wait_service.process_revision(
            self.session_id, target.runtime_id, target.runner_generation
        )
        state = await self.process_source.wait_processes(
            target, after_revision=after_revision, timeout_ms=timeout_seconds * 1000
        )
        return _ShellObservation(target=target, state=state)

    def _cancel_in_background(self, task: asyncio.Task[object]) -> None:
        """Do not hold mailbox delivery behind remote observation cancellation."""
        if task.done():
            # Retrieving an unselected failure prevents an unobserved-task error.
            self._cleanup_done(task)
            return
        self.cleanup_tasks.add(task)
        task.add_done_callback(self._cleanup_done)
        task.cancel()
        # A second cancellation interrupts the transport's cancellation-handler
        # awaits if Control is unavailable. It never targets managed processes.
        watchdog = asyncio.get_running_loop().call_later(
            _OBSERVATION_CLEANUP_GRACE_SECONDS, task.cancel
        )
        task.add_done_callback(lambda _task: watchdog.cancel())

    def _cleanup_done(self, task: asyncio.Task[object]) -> None:
        self.cleanup_tasks.discard(task)
        if task.cancelled():
            return
        error = task.exception()
        if error is not None:
            logger.error(
                "Wait observation cleanup failed",
                exc_info=(type(error), error, error.__traceback__),
            )

    async def _wait(self, timeout_seconds: int) -> str | FunctionToolResult:
        if self.session_id is None:
            raise FunctionToolError("AgentSession is unavailable")
        assert self.observer is not None
        deadline = time.monotonic() + timeout_seconds
        revision = self.observer.current_revision()
        shell = asyncio.create_task(self._observe_shell(timeout_seconds))
        shell_result_taken = False
        try:
            while True:
                observation = await self.wait_service.observe(self.session_id)
                if observation.mailbox_updated:
                    return _activity()
                shell_active = self.process_source is not None and not shell.done()
                if shell.done():
                    shell_result_taken = True
                    result = shell.result()
                    if result is not None:
                        if result.state.completed:
                            return FunctionToolResult(
                                output=json.dumps(
                                    {
                                        "outcome": "activity",
                                        "reason": "shell_completion",
                                        "completed": [
                                            item.to_payload()
                                            for item in result.state.completed
                                        ],
                                    }
                                ),
                                metadata={
                                    "shell_wait_runtime_id": result.target.runtime_id,
                                    "shell_wait_generation": (
                                        result.target.runner_generation
                                    ),
                                    "shell_wait_revision": result.state.revision,
                                },
                            )
                        shell_active = result.state.running_count > 0
                if not shell_active:
                    immediate = _outcome(observation)
                    if immediate is not None:
                        return immediate
                remaining = deadline - time.monotonic()
                if remaining <= 0 and (
                    timeout_seconds > 0 or shell.done() or self.process_source is None
                ):
                    final = await self.wait_service.observe(self.session_id)
                    if final.mailbox_updated:
                        return _activity()
                    return json.dumps({"outcome": "timed_out"})
                signal = asyncio.create_task(
                    self.observer.wait_after(
                        revision, min(1.0, remaining) if remaining > 0 else 1.0
                    )
                )
                try:
                    pending: set[asyncio.Task[object]] = {signal}
                    if not shell.done():
                        pending.add(shell)
                    await asyncio.wait(pending, return_when=asyncio.FIRST_COMPLETED)
                finally:
                    signal.cancel()
                    await asyncio.gather(signal, return_exceptions=True)
                revision = self.observer.current_revision()
        except (
            RuntimeRunnerOperationUnavailable,
            RuntimeRunnerOperationGenerationError,
            RuntimeRunnerOperationFailedError,
        ) as exc:
            raise FunctionToolError(str(exc)) from None
        finally:
            if not shell_result_taken:
                self._cancel_in_background(shell)


class _WaitInput(BaseModel):
    """Validated time-only wait input."""

    model_config = ConfigDict(extra="forbid")
    timeout_seconds: int = Field(default=30, ge=0, le=900)


def _activity() -> str:
    return json.dumps(
        {
            "outcome": "activity",
            "reason": (
                "new user input, agent or subagent message, scheduled "
                "continuation, external-channel request, or action"
            ),
        }
    )


def _outcome(observation: WaitObservation) -> str | None:
    if observation.mailbox_updated:
        return _activity()
    if observation.descendant_count == 0:
        return json.dumps({"outcome": "not_waitable", "reason": "no_descendants"})
    if not observation.active_paths:
        return json.dumps({"outcome": "not_waitable", "reason": "all_descendants_idle"})
    return None
