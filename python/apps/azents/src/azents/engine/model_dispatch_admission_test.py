"""Every physical dispatch rechecks common admission before touching provider I/O."""

import asyncio

import pytest

from azents.engine.model_stream import (
    InternalModelCallIdentity,
    InternalModelStreamCallContext,
    ModelStreamCallContext,
    admit_model_dispatch,
)
from azents.engine.run.types import USER_STOP_CANCEL_MESSAGE


async def test_each_wire_attempt_observes_fresh_execution_authority() -> None:
    checks: list[str] = []

    async def check() -> bool:
        checks.append("check")
        if len(checks) == 2:
            raise PermissionError("Execution owner changed")
        return False

    context = ModelStreamCallContext(
        call_kind="historical_memory",
        provider="openai",
        provider_integration_id="integration",
        model="selected",
        session_id="private-session",
        run_id="actual-run",
        attempt_number=1,
        check_stop=check,
    )
    await admit_model_dispatch(context)
    with pytest.raises(PermissionError, match="Execution owner changed"):
        await admit_model_dispatch(context)
    assert checks == ["check", "check"]


async def test_stop_prevents_internal_dispatch_reservation_and_wire_attempt() -> None:
    admitted: list[str] = []

    async def check() -> bool:
        return True

    async def reserve() -> None:
        admitted.append("reserve")

    context = InternalModelStreamCallContext(
        call_kind="historical_memory",
        provider="anthropic",
        provider_integration_id="integration",
        model="selected",
        session_id=None,
        run_id=None,
        attempt_number=1,
        check_stop=check,
        identity=InternalModelCallIdentity("agent", "workspace", "unit", "attempt"),
        admit_dispatch=reserve,
    )
    with pytest.raises(asyncio.CancelledError) as stopped:
        await admit_model_dispatch(context)
    assert stopped.value.args == (USER_STOP_CANCEL_MESSAGE,)
    assert admitted == []


async def test_existing_internal_reservation_order_is_preserved() -> None:
    trace: list[str] = []

    async def check() -> bool:
        trace.append("check")
        return False

    async def reserve() -> None:
        trace.append("reserve")

    context = InternalModelStreamCallContext(
        call_kind="historical_memory",
        provider="openai",
        provider_integration_id=None,
        model="selected",
        session_id=None,
        run_id=None,
        attempt_number=None,
        check_stop=check,
        identity=InternalModelCallIdentity("agent", "workspace", "unit", "attempt"),
        admit_dispatch=reserve,
    )
    await admit_model_dispatch(context)
    assert trace == ["check", "reserve"]
