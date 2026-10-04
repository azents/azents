"""Execution-neutral orchestration for the shared model/tool iteration loop."""

from __future__ import annotations

import asyncio
import itertools
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Literal, Protocol

IterationEndReason = Literal["completed", "error", "cancelled", "unknown"]


@dataclass(frozen=True)
class IterationValue[TValue]:
    """A host-owned prepared turn or model output ready for the next stage."""

    value: TValue


@dataclass(frozen=True)
class IterationFinished[TResult]:
    """A host-owned terminal or handoff outcome, not a persisted Run status."""

    result: TResult
    reason: IterationEndReason


@dataclass(frozen=True)
class AdmittedIteration[TAdmission]:
    """Committed host output and its execution-neutral continuation policy."""

    admission: TAdmission
    has_tool_calls: bool
    needs_follow_up: bool


class ModelToolIterationHost[TPrepared, TOutput, TAdmission, TResult](Protocol):
    """Purpose-specific identity, state, admission and terminal operations.

    Every operation finishes its own persistence boundary before returning.
    The core never supplies a Session, Run, repository or event envelope.
    """

    async def prepare_turn(
        self,
    ) -> IterationValue[TPrepared] | IterationFinished[TResult]:
        """Check authority/inputs and prepare one model request."""
        ...

    async def invoke_model(
        self, prepared: TPrepared
    ) -> IterationValue[TOutput] | IterationFinished[TResult]:
        """Stream and normalize the prepared provider request."""
        ...

    async def admit_output(
        self, prepared: TPrepared, output: TOutput
    ) -> AdmittedIteration[TAdmission] | IterationFinished[TResult]:
        """Admit normalized output before tools or completed output delivery."""
        ...

    async def publish_output(self, admission: TAdmission) -> None:
        """Deliver admitted nonterminal output, if this host exposes it."""
        ...

    async def execute_tools(
        self, prepared: TPrepared, admission: TAdmission
    ) -> IterationFinished[TResult] | None:
        """Execute and match admitted calls, then check purpose-specific handoff."""
        ...

    async def complete_turn(
        self, admission: TAdmission, *, include_output: bool
    ) -> TResult:
        """Complete normally with host-owned persistence and delivery."""
        ...

    async def finish_turn(
        self, prepared: TPrepared, reason: IterationEndReason
    ) -> None:
        """Finish the prepared turn at most once."""
        ...

    async def fail_turn(self, prepared: TPrepared, error: Exception) -> None:
        """Record purpose-specific turn failure without swallowing the error."""
        ...

    async def close(self) -> None:
        """Close transport resources after any terminal, error or handoff."""
        ...

    async def limit_reached(self) -> TResult:
        """Handle exhaustion without turning it into normal completion."""
        ...


@dataclass(frozen=True)
class ModelToolIterationCore[TPrepared, TOutput, TAdmission, TResult]:
    """One shared stage-ordering algorithm for durable and transient hosts."""

    host: ModelToolIterationHost[TPrepared, TOutput, TAdmission, TResult]

    async def run(self, *, max_turns: int | None) -> TResult:
        """Run model/tool turns without assuming an execution identity or store."""
        try:
            turns: Iterable[int] = (
                itertools.count() if max_turns is None else range(max_turns)
            )
            for _ in turns:
                preparation = await self.host.prepare_turn()
                if isinstance(preparation, IterationFinished):
                    return preparation.result
                prepared = preparation.value
                try:
                    output = await self.host.invoke_model(prepared)
                    if isinstance(output, IterationFinished):
                        await self.host.finish_turn(prepared, output.reason)
                        return output.result
                    admitted = await self.host.admit_output(prepared, output.value)
                    if isinstance(admitted, IterationFinished):
                        await self.host.finish_turn(prepared, admitted.reason)
                        return admitted.result
                    admission = admitted.admission
                    if not admitted.has_tool_calls and not admitted.needs_follow_up:
                        result = await self.host.complete_turn(
                            admission, include_output=True
                        )
                        await self.host.finish_turn(prepared, "completed")
                        return result
                    await self.host.publish_output(admission)
                    if admitted.has_tool_calls:
                        tool_outcome = await self.host.execute_tools(
                            prepared, admission
                        )
                        if tool_outcome is not None:
                            await self.host.finish_turn(prepared, tool_outcome.reason)
                            return tool_outcome.result
                        if not admitted.needs_follow_up:
                            result = await self.host.complete_turn(
                                admission, include_output=False
                            )
                            await self.host.finish_turn(prepared, "completed")
                            return result
                    await self.host.finish_turn(prepared, "completed")
                except asyncio.CancelledError:
                    raise
                except Exception as error:
                    await self.host.fail_turn(prepared, error)
                    raise
        finally:
            await self.host.close()
        return await self.host.limit_reached()
