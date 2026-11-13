"""Explicit Scheduled selection never mutates ordinary Channel Work."""

import json
from unittest.mock import AsyncMock, MagicMock

import pytest

from azents.core.enums import ExternalChannelWorkStatus
from azents.engine.run.types import FunctionToolError
from azents.engine.tooling.execution_context import client_tool_execution_context
from azents.engine.tools.external_channel_test import (
    _ActionService,
    _snapshot,
    _toolkit,
    _turn_context,
)
from azents.repos.external_channel.work_data import ChannelActionResult
from azents.services.scheduled_task.channel import ScheduledTaskProgressExecution


@pytest.mark.parametrize("admitted", [False, True])
async def test_explicit_scheduled_selector_has_no_channel_work_fallback(
    admitted: bool,
) -> None:
    service = _ActionService([_snapshot()])
    toolkit = _toolkit(service)
    scheduled = AsyncMock()
    scheduled.for_execution = MagicMock(return_value=scheduled)
    scheduled.execute_progress.return_value = ScheduledTaskProgressExecution(
        result=(
            ChannelActionResult(
                binding_id="binding-1",
                work_id="s" * 32,
                work_status=ExternalChannelWorkStatus.ACTIVE,
                state_revision=1,
                awaiting_input=False,
                outcomes=(),
            )
            if admitted
            else None
        )
    )
    toolkit.scheduled_channel_service = scheduled
    state = await toolkit.update_context(_turn_context())

    async def invoke() -> object:
        with client_tool_execution_context(call_id="selected", name="channel_action"):
            return await state.tools[0].handler(
                json.dumps(
                    {
                        "binding": "binding-1",
                        "mode": "continue",
                        "message": "Working.",
                        "work_cycle_id": None,
                        "scheduled_cycle_id": "s" * 32,
                    }
                )
            )

    if admitted:
        output = await invoke()
        assert isinstance(output, str)
        payload = json.loads(output)
        assert payload["scheduled_cycle_id"] == "s" * 32
        assert payload["work_cycle_id"] is None
    else:
        with pytest.raises(FunctionToolError, match="not admitted"):
            await invoke()
    scheduled.execute_progress.assert_awaited_once()
    assert scheduled.execute_progress.await_args.kwargs["cycle_id"] == "s" * 32
    assert service.calls == []
