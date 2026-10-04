"""Tests of the common loop with a RAM-only, identity-free host."""

import asyncio
from dataclasses import dataclass
from typing import Literal

import pytest

from azents.engine.events.iteration import (
    AdmittedIteration,
    IterationEndReason,
    IterationFinished,
    IterationValue,
    ModelToolIterationCore,
)


@dataclass
class _Turn:
    """Transient turn state without a Session, Run or persistent event."""

    index: int
    ended: bool


@dataclass(frozen=True)
class _Output:
    """Purpose-owned output, independent of foreground normalization types."""

    tools: bool
    follow_up: bool


@dataclass
class _TransientHost:
    """RAM-only host exercising real core stage ordering and outcomes."""

    outputs: list[_Output]
    stages: list[str]
    early_stage: Literal["prepare", "model", "admit", "tools"] | None
    failure_stage: Literal["prepare", "model", "admit", "publish", "tools"] | None
    cancel_stage: Literal["model", "tools"] | None
    failure: Exception
    index: int

    async def prepare_turn(self) -> IterationValue[_Turn] | IterationFinished[str]:
        self.stages.append("prepare")
        if self.failure_stage == "prepare":
            raise self.failure
        if self.early_stage == "prepare":
            return IterationFinished("handoff", "completed")
        turn = _Turn(index=self.index, ended=False)
        self.index += 1
        return IterationValue(turn)

    async def invoke_model(
        self, prepared: _Turn
    ) -> IterationValue[_Output] | IterationFinished[str]:
        self.stages.append("model")
        if self.failure_stage == "model":
            raise self.failure
        if self.cancel_stage == "model":
            raise asyncio.CancelledError("shutdown")
        if self.early_stage == "model":
            return IterationFinished("stopped", "cancelled")
        return IterationValue(self.outputs[prepared.index])

    async def admit_output(
        self, prepared: _Turn, output: _Output
    ) -> AdmittedIteration[_Output] | IterationFinished[str]:
        self.stages.append("admit")
        if self.failure_stage == "admit":
            raise self.failure
        if self.early_stage == "admit":
            return IterationFinished("handoff", "cancelled")
        return AdmittedIteration(
            admission=output,
            has_tool_calls=output.tools,
            needs_follow_up=output.follow_up,
        )

    async def publish_output(self, admission: _Output) -> None:
        self.stages.append("publish")
        if self.failure_stage == "publish":
            raise self.failure

    async def execute_tools(
        self, prepared: _Turn, admission: _Output
    ) -> IterationFinished[str] | None:
        self.stages.append("tools")
        if self.failure_stage == "tools":
            raise self.failure
        if self.cancel_stage == "tools":
            raise asyncio.CancelledError("shutdown")
        if self.early_stage == "tools":
            return IterationFinished("tool-terminal", "completed")
        return None

    async def complete_turn(self, admission: _Output, *, include_output: bool) -> str:
        self.stages.append("complete-with-output" if include_output else "complete")
        return "completed"

    async def finish_turn(self, prepared: _Turn, reason: IterationEndReason) -> None:
        if prepared.ended:
            return
        prepared.ended = True
        self.stages.append(f"finish:{reason}")

    async def fail_turn(self, prepared: _Turn, error: Exception) -> None:
        assert error is self.failure
        await self.finish_turn(prepared, "error")

    async def close(self) -> None:
        self.stages.append("close")

    async def limit_reached(self) -> str:
        self.stages.append("limit")
        return "budget-exhausted"


def _host(outputs: list[_Output]) -> _TransientHost:
    return _TransientHost(
        outputs=outputs,
        stages=[],
        early_stage=None,
        failure_stage=None,
        cancel_stage=None,
        failure=ValueError("synthetic failure"),
        index=0,
    )


async def test_transient_host_runs_multiple_tool_turns_without_public_identity() -> (
    None
):
    host = _host([_Output(True, True), _Output(False, False)])
    result = await ModelToolIterationCore(host).run(max_turns=None)
    assert result == "completed"
    assert host.stages == [
        "prepare",
        "model",
        "admit",
        "publish",
        "tools",
        "finish:completed",
        "prepare",
        "model",
        "admit",
        "complete-with-output",
        "finish:completed",
        "close",
    ]


async def test_provider_follow_up_without_client_calls_uses_another_turn() -> None:
    host = _host([_Output(False, True), _Output(False, False)])
    assert await ModelToolIterationCore(host).run(max_turns=2) == "completed"
    assert host.stages.count("model") == 2
    assert "tools" not in host.stages
    assert host.stages.index("admit") < host.stages.index("publish")


async def test_final_tool_turn_completes_after_tools_without_duplicate_output() -> None:
    host = _host([_Output(True, False)])
    assert await ModelToolIterationCore(host).run(max_turns=1) == "completed"
    assert host.stages == [
        "prepare",
        "model",
        "admit",
        "publish",
        "tools",
        "complete",
        "finish:completed",
        "close",
    ]


@pytest.mark.parametrize("max_turns", [0, -1])
async def test_zero_budget_never_prepares_or_invokes_model(max_turns: int) -> None:
    host = _host([])
    assert (
        await ModelToolIterationCore(host).run(max_turns=max_turns)
        == "budget-exhausted"
    )
    assert host.stages == ["close", "limit"]


async def test_exhausted_turn_budget_is_not_successful_completion() -> None:
    host = _host([_Output(True, True)])
    assert await ModelToolIterationCore(host).run(max_turns=1) == "budget-exhausted"
    assert host.stages[-3:] == ["finish:completed", "close", "limit"]
    assert "complete" not in host.stages
    assert "complete-with-output" not in host.stages


@pytest.mark.parametrize("stage", ["prepare", "model", "admit", "tools"])
async def test_host_handoff_stops_dispatch_and_closes(
    stage: Literal["prepare", "model", "admit", "tools"],
) -> None:
    host = _host([_Output(True, True)])
    host.early_stage = stage
    result = await ModelToolIterationCore(host).run(max_turns=None)
    assert result in {"handoff", "stopped", "tool-terminal"}
    assert host.stages[-1] == "close"
    assert host.stages.count("prepare") == 1
    assert "limit" not in host.stages
    if stage in {"prepare", "model", "admit"}:
        assert "tools" not in host.stages
    if stage == "prepare":
        assert not any(s.startswith("finish:") for s in host.stages)


@pytest.mark.parametrize("stage", ["prepare", "model", "admit", "publish", "tools"])
async def test_failure_propagates_original_exception_and_closes(
    stage: Literal["prepare", "model", "admit", "publish", "tools"],
) -> None:
    host = _host([_Output(True, True)])
    host.failure_stage = stage
    with pytest.raises(ValueError, match="synthetic failure") as raised:
        await ModelToolIterationCore(host).run(max_turns=None)
    assert raised.value is host.failure
    assert host.stages[-1] == "close"
    assert "limit" not in host.stages
    assert host.stages.count("finish:error") == (0 if stage == "prepare" else 1)


@pytest.mark.parametrize("stage", ["model", "tools"])
async def test_shutdown_cancellation_does_not_invoke_failure_side_effects(
    stage: Literal["model", "tools"],
) -> None:
    host = _host([_Output(True, True)])
    host.cancel_stage = stage
    with pytest.raises(asyncio.CancelledError, match="shutdown"):
        await ModelToolIterationCore(host).run(max_turns=None)
    assert host.stages[-1] == "close"
    assert "finish:error" not in host.stages
    assert "limit" not in host.stages
