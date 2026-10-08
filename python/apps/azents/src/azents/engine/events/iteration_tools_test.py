"""Shared parallel call matching and cancellation tests with transient results."""

import asyncio
from collections.abc import Sequence
from dataclasses import dataclass

import pytest

from azents.engine.events.iteration_tools import ParallelIterationTools


@dataclass(frozen=True)
class _Call:
    call_id: str


@dataclass(frozen=True)
class _Result:
    text: str
    terminal: bool


@dataclass(frozen=True)
class _Settled:
    call: _Call
    result: _Result


@dataclass
class _Host:
    """Synthetic RAM-only host with deterministic tool settlement barriers."""

    gates: dict[str, asyncio.Event]
    started: dict[str, asyncio.Event]
    finalized: dict[str, asyncio.Event]
    cancel_defiant: set[str]
    terminal_ids: set[str]
    results: list[_Settled]
    cancel_requests: list[str]
    cancelled: list[str]
    cancellation_messages: list[tuple[object, ...]]

    async def execute(self, call: _Call) -> _Result:
        self.started[call.call_id].set()
        try:
            await self.gates[call.call_id].wait()
        except asyncio.CancelledError:
            if call.call_id not in self.cancel_defiant:
                raise
        return _Result(
            text=f"result:{call.call_id}", terminal=call.call_id in self.terminal_ids
        )

    async def finalize(self, call: _Call, result: _Result) -> bool:
        self.results.append(_Settled(call=call, result=result))
        self.finalized[call.call_id].set()
        return result.terminal

    def request_cancel(self, call: _Call) -> None:
        self.cancel_requests.append(call.call_id)

    async def finalize_cancelled(self, calls: Sequence[_Call]) -> None:
        self.cancelled.extend(call.call_id for call in calls)

    async def handle_cancellation(self, error: asyncio.CancelledError) -> None:
        self.cancellation_messages.append(error.args)


def _host(ids: list[str]) -> _Host:
    return _Host(
        gates={i: asyncio.Event() for i in ids},
        started={i: asyncio.Event() for i in ids},
        finalized={i: asyncio.Event() for i in ids},
        cancel_defiant=set(),
        terminal_ids=set(),
        results=[],
        cancel_requests=[],
        cancelled=[],
        cancellation_messages=[],
    )


async def test_parallel_results_preserve_call_identity_not_submission_order() -> None:
    host = _host(["first", "second"])
    batch = asyncio.create_task(
        ParallelIterationTools(host).run([_Call("first"), _Call("second")])
    )
    await host.started["first"].wait()
    await host.started["second"].wait()
    host.gates["second"].set()
    await host.finalized["second"].wait()
    assert [r.call.call_id for r in host.results] == ["second"]
    host.gates["first"].set()
    assert not await batch
    assert [r.call.call_id for r in host.results] == ["second", "first"]
    assert [r.result.text for r in host.results] == ["result:second", "result:first"]


async def test_terminal_result_does_not_skip_other_admitted_calls() -> None:
    host = _host(["terminal", "other"])
    host.terminal_ids.add("terminal")
    host.gates["terminal"].set()
    host.gates["other"].set()
    assert await ParallelIterationTools(host).run([_Call("terminal"), _Call("other")])
    assert {r.call.call_id for r in host.results} == {"terminal", "other"}


@pytest.mark.parametrize("message", ["user-stop", "worker-shutdown"])
async def test_stop_only_cancels_unsettled_calls_and_preserves_settled_results(
    message: str,
) -> None:
    host = _host(["done", "waiting"])
    batch = asyncio.create_task(
        ParallelIterationTools(host).run([_Call("done"), _Call("waiting")])
    )
    await host.started["waiting"].wait()
    host.gates["done"].set()
    await host.finalized["done"].wait()
    batch.cancel(message)
    with pytest.raises(asyncio.CancelledError, match=message):
        await batch
    assert host.cancel_requests == ["waiting"]
    assert host.cancelled == ["waiting"]
    assert [r.call.call_id for r in host.results] == ["done"]
    assert host.cancellation_messages == [(message,)]


async def test_cancellation_preserves_a_result_that_settles_during_stop() -> None:
    host = _host(["settles", "cancelled"])
    host.cancel_defiant.add("settles")
    batch = asyncio.create_task(
        ParallelIterationTools(host).run([_Call("settles"), _Call("cancelled")])
    )
    await host.started["settles"].wait()
    await host.started["cancelled"].wait()
    batch.cancel("worker-shutdown")
    with pytest.raises(asyncio.CancelledError):
        await batch
    assert host.cancel_requests == ["settles", "cancelled"]
    assert host.cancelled == ["cancelled"]
    assert [r.call.call_id for r in host.results] == ["settles"]


async def test_empty_batch_does_not_claim_a_terminal_result() -> None:
    host = _host([])
    assert not await ParallelIterationTools(host).run([])
    assert host.results == []
    assert host.cancel_requests == []


class _FaultHost(_Host):
    async def execute(self, call: _Call) -> _Result:
        result = await super().execute(call)
        if call.call_id == "fault":
            raise PermissionError("Synthetic authority failure")
        return result


async def test_unexpected_failure_quiesces_siblings_before_host_failure() -> None:
    base = _host(["fault", "waiting"])
    host = _FaultHost(**vars(base))
    batch = asyncio.create_task(
        ParallelIterationTools(host).run([_Call("fault"), _Call("waiting")])
    )
    await host.started["fault"].wait()
    await host.started["waiting"].wait()
    host.gates["fault"].set()
    with pytest.raises(PermissionError, match="Synthetic authority"):
        await batch
    assert set(host.cancel_requests) == {"fault", "waiting"}
    assert host.results == []
    assert host.cancellation_messages == []


async def test_duplicate_ids_fail_before_any_tool_dispatch() -> None:
    host = _host(["same"])
    with pytest.raises(ValueError, match="repeats a call identity"):
        await ParallelIterationTools(host).run([_Call("same"), _Call("same")])
    assert not host.started["same"].is_set()


class _LostFinalizeHost(_Host):
    async def finalize(self, call: _Call, result: _Result) -> bool:
        raise PermissionError("Synthetic settlement authority loss")


async def test_late_settlement_denial_cannot_replace_shutdown_cancellation() -> None:
    base = _host(["late"])
    host = _LostFinalizeHost(**vars(base))
    host.cancel_defiant.add("late")
    batch = asyncio.create_task(ParallelIterationTools(host).run([_Call("late")]))
    await host.started["late"].wait()
    batch.cancel("worker-shutdown")
    with pytest.raises(asyncio.CancelledError, match="worker-shutdown") as error:
        await batch
    assert isinstance(error.value.__cause__, PermissionError)
    assert host.results == [] and host.cancel_requests == ["late"]
