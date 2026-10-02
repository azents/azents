"""Shared parallel tool-call matching, settlement and cancellation algorithm."""

import asyncio
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Protocol


class IterationToolCall(Protocol):
    """Stable model-call identity used for result matching, not a Session."""

    @property
    def call_id(self) -> str:
        """Return the admitted call identity."""
        ...


@dataclass(frozen=True)
class IterationToolResult[TCall, TResult]:
    """One settled call/result pair, preserving identity across completion order."""

    call: TCall
    result: TResult


class IterationToolHost[TCall: IterationToolCall, TResult](Protocol):
    """Tool behavior and result admission for one execution purpose."""

    async def execute(self, call: TCall) -> TResult:
        """Execute one call and normalize purpose-specific tool failures."""
        ...

    async def finalize(self, call: TCall, result: TResult) -> bool:
        """Admit one result and report whether it completed a terminal tool."""
        ...

    def request_cancel(self, call: TCall) -> None:
        """Request cancellation of a still-unsettled tool operation."""
        ...

    async def finalize_cancelled(self, calls: Sequence[TCall]) -> None:
        """Admit cancellation results for calls that produced no settled result."""
        ...

    async def handle_cancellation(self, error: asyncio.CancelledError) -> None:
        """Apply host stop behavior; shutdown cancellation is otherwise re-raised."""
        ...


@dataclass(frozen=True)
class ParallelIterationTools[TCall: IterationToolCall, TResult]:
    """One parallel batch algorithm shared by durable and RAM-only hosts."""

    host: IterationToolHost[TCall, TResult]

    async def _execute(self, call: TCall) -> IterationToolResult[TCall, TResult]:
        result = await self.host.execute(call)
        return IterationToolResult(call=call, result=result)

    async def run(self, calls: Sequence[TCall]) -> bool:
        """Finalize each settled result independently and preserve stop ordering."""
        completed_ids: set[str] = set()
        terminal_completed = False
        tasks_by_id = {
            call.call_id: asyncio.create_task(self._execute(call)) for call in calls
        }
        try:
            for completed in asyncio.as_completed(list(tasks_by_id.values())):
                outcome = await completed
                terminal = await self.host.finalize(outcome.call, outcome.result)
                terminal_completed = terminal_completed or terminal
                completed_ids.add(outcome.call.call_id)
        except asyncio.CancelledError as error:
            unresolved = [call for call in calls if call.call_id not in completed_ids]
            for call in unresolved:
                self.host.request_cancel(call)
            for call in unresolved:
                task = tasks_by_id[call.call_id]
                if not task.done():
                    task.cancel()
            settled = await asyncio.gather(
                *(tasks_by_id[call.call_id] for call in unresolved),
                return_exceptions=True,
            )
            cancelled: list[TCall] = []
            for call, outcome in zip(unresolved, settled, strict=True):
                if isinstance(outcome, IterationToolResult):
                    await self.host.finalize(outcome.call, outcome.result)
                    completed_ids.add(outcome.call.call_id)
                else:
                    cancelled.append(call)
            await self.host.finalize_cancelled(cancelled)
            await self.host.handle_cancellation(error)
            raise
        return terminal_completed
