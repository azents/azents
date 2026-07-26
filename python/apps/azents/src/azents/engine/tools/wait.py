"""Independent model-visible wait Toolkit."""

import json
import time
from typing import cast

from pydantic import BaseModel, Field

from azents.core.tools import (
    FunctionTool,
    Toolkit,
    ToolkitState,
    ToolkitStatus,
    TurnContext,
)
from azents.engine.run.types import FunctionToolError
from azents.engine.tooling.make_tool import make_tool
from azents.services.agent_wait import (
    AgentWaitService,
    MailboxActivityObserverProtocol,
    WaitObservation,
)


class WaitToolkitConfig(BaseModel):
    """Stateless Wait Toolkit configuration."""


class WaitToolkit(Toolkit[WaitToolkitConfig]):
    """Wait for descendant work or newly available input activity."""

    def __init__(self, *, wait_service: AgentWaitService) -> None:
        self.wait_service = wait_service
        self.session_id = ""
        self.observer: MailboxActivityObserverProtocol | None = None

    async def update_context(self, context: TurnContext) -> ToolkitState:
        """Bind the current Session and Run-scoped observer."""
        self.session_id = context.session_id
        self.observer = cast(
            MailboxActivityObserverProtocol | None,
            context.mailbox_activity_observer,
        )
        return ToolkitState(
            status=ToolkitStatus.ENABLED,
            tools=[self._wait_tool()],
        )

    async def get_static_prompt(self, context: TurnContext) -> str:
        """Return concise wait guidance."""
        del context
        return (
            "Use wait only while descendant work is active. New user input, an "
            "agent or subagent message, a scheduled continuation, an "
            "external-channel request, or an action may end the wait; wait does "
            "not consume the input."
        )

    def _wait_tool(self) -> FunctionTool:
        async def wait(input: _WaitInput) -> str:
            """Wait for descendant activity or newly available input."""
            if self.observer is None:
                raise FunctionToolError("Mailbox activity observer is unavailable")
            return await self._wait(input.timeout_seconds)

        return make_tool(
            wait,
            name="wait",
            description=(
                "Wait while descendant work is active. Returns when new user "
                "input, an agent or subagent message, a scheduled continuation, "
                "an external-channel request, or an action arrives; also returns "
                "for no descendants, all descendants idle, or timeout."
            ),
        )

    async def _wait(self, timeout_seconds: int) -> str:
        deadline = time.monotonic() + timeout_seconds
        assert self.observer is not None
        revision = self.observer.current_revision()
        while True:
            observation = await self.wait_service.observe(self.session_id)
            immediate = _outcome(observation)
            if immediate is not None:
                return immediate
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                final = await self.wait_service.observe(self.session_id)
                return _outcome(final) or json.dumps({"outcome": "timed_out"})
            await self.observer.wait_after(
                revision,
                min(1.0, remaining),
            )
            revision = self.observer.current_revision()


class _WaitInput(BaseModel):
    """Validated wait input."""

    timeout_seconds: int = Field(default=30, ge=0, le=900)


def _outcome(observation: WaitObservation) -> str | None:
    if observation.mailbox_updated:
        return json.dumps(
            {
                "outcome": "activity",
                "reason": (
                    "new user input, agent or subagent message, scheduled "
                    "continuation, external-channel request, or action"
                ),
            }
        )
    if observation.descendant_count == 0:
        return json.dumps({"outcome": "not_waitable", "reason": "no_descendants"})
    if not observation.active_paths:
        return json.dumps({"outcome": "not_waitable", "reason": "all_descendants_idle"})
    return None
