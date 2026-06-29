"""runtime hook dispatcher test fixtures."""

import asyncio
import dataclasses
from typing import cast

from pydantic import BaseModel

from azents.core.tools import Toolkit, ToolkitState, ToolkitStatus, TurnContext
from azents.engine.hooks.types import (
    AfterToolCallHookContext,
    BeforeToolCallHookContext,
    RunEndHookContext,
    RunStartHookContext,
    RuntimeHibernateHookContext,
    RuntimeHookName,
    RuntimeHooks,
    RuntimeRestoreHookContext,
    SessionClearHookContext,
    SessionCompactHookContext,
    SessionStartHookContext,
    ToolCallDecision,
    ToolOutputDecision,
    TurnEndHookContext,
    TurnStartHookContext,
    TurnStartResult,
)


@dataclasses.dataclass(frozen=True)
class DeterministicHookAction:
    """Actions performed by test hook in order."""

    result: object | None = None
    exception: BaseException | None = None
    cancelled: bool = False


@dataclasses.dataclass(frozen=True)
class DeterministicHookCall:
    """Hook call summary recorded without raw payload."""

    provider_slug: str
    lifecycle: RuntimeHookName
    context_summary: dict[str, str | int | None]


class DeterministicRuntimeHookProvider(Toolkit[BaseModel]):
    """Test provider with deterministic lifecycle results and exceptions."""

    def __init__(
        self,
        *,
        slug: str,
        actions: dict[RuntimeHookName, list[DeterministicHookAction]] | None = None,
    ) -> None:
        self.slug = slug
        self._actions = actions if actions is not None else {}
        self.calls: list[DeterministicHookCall] = []

    async def update_context(self, context: TurnContext) -> ToolkitState:
        """Always return active empty state."""
        return ToolkitState(status=ToolkitStatus.ENABLED, tools=[])

    def hooks(self) -> RuntimeHooks:
        """Return only lifecycle callbacks registered in actions."""
        hooks: RuntimeHooks = {}
        if "on_session_start" in self._actions:
            hooks["on_session_start"] = self._on_session_start
        if "on_session_clear" in self._actions:
            hooks["on_session_clear"] = self._on_session_clear
        if "on_session_compact" in self._actions:
            hooks["on_session_compact"] = self._on_session_compact
        if "on_run_start" in self._actions:
            hooks["on_run_start"] = self._on_run_start
        if "on_run_end" in self._actions:
            hooks["on_run_end"] = self._on_run_end
        if "on_turn_start" in self._actions:
            hooks["on_turn_start"] = self._on_turn_start
        if "on_turn_end" in self._actions:
            hooks["on_turn_end"] = self._on_turn_end
        if "on_before_tool_call" in self._actions:
            hooks["on_before_tool_call"] = self._on_before_tool_call
        if "on_after_tool_call" in self._actions:
            hooks["on_after_tool_call"] = self._on_after_tool_call
        if "on_runtime_hibernate" in self._actions:
            hooks["on_runtime_hibernate"] = self._on_runtime_hibernate
        if "on_runtime_restore" in self._actions:
            hooks["on_runtime_restore"] = self._on_runtime_restore
        return hooks

    async def _on_session_start(self, context: SessionStartHookContext) -> None:
        await self._run("on_session_start", context)

    async def _on_session_clear(self, context: SessionClearHookContext) -> None:
        await self._run("on_session_clear", context)

    async def _on_session_compact(self, context: SessionCompactHookContext) -> None:
        await self._run("on_session_compact", context)

    async def _on_run_start(self, context: RunStartHookContext) -> None:
        await self._run("on_run_start", context)

    async def _on_run_end(self, context: RunEndHookContext) -> None:
        await self._run("on_run_end", context)

    async def _on_turn_start(
        self, context: TurnStartHookContext
    ) -> TurnStartResult | None:
        result = await self._run("on_turn_start", context)
        return cast(TurnStartResult | None, result)

    async def _on_turn_end(self, context: TurnEndHookContext) -> None:
        await self._run("on_turn_end", context)

    async def _on_before_tool_call(
        self, context: BeforeToolCallHookContext
    ) -> ToolCallDecision | None:
        result = await self._run("on_before_tool_call", context)
        return cast(ToolCallDecision | None, result)

    async def _on_after_tool_call(
        self, context: AfterToolCallHookContext
    ) -> ToolOutputDecision | None:
        result = await self._run("on_after_tool_call", context)
        return cast(ToolOutputDecision | None, result)

    async def _on_runtime_hibernate(self, context: RuntimeHibernateHookContext) -> None:
        await self._run("on_runtime_hibernate", context)

    async def _on_runtime_restore(self, context: RuntimeRestoreHookContext) -> None:
        await self._run("on_runtime_restore", context)

    async def _run(self, lifecycle: RuntimeHookName, context: object) -> object | None:
        """Record call and execute next action."""
        self.calls.append(
            DeterministicHookCall(
                provider_slug=self.slug,
                lifecycle=lifecycle,
                context_summary=_summarize_context(context),
            )
        )
        action = self._next_action(lifecycle)
        if action.cancelled:
            raise asyncio.CancelledError
        if action.exception is not None:
            raise action.exception
        return action.result

    def _next_action(self, lifecycle: RuntimeHookName) -> DeterministicHookAction:
        """Return next action for lifecycle."""
        actions = self._actions[lifecycle]
        if not actions:
            return DeterministicHookAction()
        return actions.pop(0)


def _summarize_context(context: object) -> dict[str, str | int | None]:
    """Summarize only context identifiers without sensitive payload."""
    summary: dict[str, str | int | None] = {}
    for field_name in (
        "workspace_id",
        "agent_id",
        "session_id",
        "run_id",
        "tool_name",
        "toolkit_slug",
        "turn_index",
        "reason",
        "agent_runtime_id",
    ):
        value = getattr(context, field_name, None)
        if isinstance(value, str | int) or value is None:
            summary[field_name] = value
    return summary
