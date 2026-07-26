"""Independent Wait Toolkit tests."""

import json
from typing import cast

import pytest

from azents.core.tools import ToolkitStatus, TurnContext
from azents.engine.tools.wait import WaitToolkit
from azents.services.agent_wait import (
    AgentWaitService,
    WaitObservation,
)
from azents.worker.session.mailbox_activity import MailboxActivityObserver


class _WaitService:
    def __init__(self, observations: list[WaitObservation]) -> None:
        self.observations = iter(observations)

    async def observe(self, _session_id: str) -> WaitObservation:
        return next(self.observations)


def _context(observer: MailboxActivityObserver) -> TurnContext:
    return TurnContext(
        workspace_id="workspace-1",
        model="gpt-5.1",
        run_id="run-1",
        session_id="session-1",
        publish_event=lambda _event: _noop(),
        mailbox_activity_observer=observer,
    )


async def _noop() -> None:
    return None


@pytest.mark.asyncio
async def test_wait_tool_is_independent_and_describes_input_activity() -> None:
    observer = MailboxActivityObserver()
    toolkit = WaitToolkit(
        wait_service=cast(
            AgentWaitService,
            _WaitService([WaitObservation(True, 1, ("/root/child",))]),
        )
    )
    state = await toolkit.update_context(_context(observer))

    assert state.status is ToolkitStatus.ENABLED
    assert [tool.spec.name for tool in state.tools] == ["wait"]
    result = await state.tools[0].handler(json.dumps({}))
    assert json.loads(cast(str, result)) == {
        "outcome": "activity",
        "reason": (
            "new user input, agent or subagent message, scheduled continuation, "
            "external-channel request, or action"
        ),
    }


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("observation", "expected"),
    [
        (
            WaitObservation(False, 0, ()),
            {"outcome": "not_waitable", "reason": "no_descendants"},
        ),
        (
            WaitObservation(False, 1, ()),
            {"outcome": "not_waitable", "reason": "all_descendants_idle"},
        ),
    ],
)
async def test_wait_tool_reports_not_waitable_outcomes(
    observation: WaitObservation,
    expected: dict[str, str],
) -> None:
    observer = MailboxActivityObserver()
    toolkit = WaitToolkit(
        wait_service=cast(AgentWaitService, _WaitService([observation]))
    )
    state = await toolkit.update_context(_context(observer))

    result = await state.tools[0].handler(json.dumps({"timeout_seconds": 0}))
    assert json.loads(cast(str, result)) == expected


@pytest.mark.asyncio
async def test_wait_tool_reconciles_after_activity_signal_loss() -> None:
    observer = MailboxActivityObserver()
    service = _WaitService(
        [
            WaitObservation(False, 1, ("/root/child",)),
            WaitObservation(True, 1, ("/root/child",)),
        ]
    )
    toolkit = WaitToolkit(wait_service=cast(AgentWaitService, service))
    state = await toolkit.update_context(_context(observer))

    result = await state.tools[0].handler(json.dumps({"timeout_seconds": 1}))
    assert json.loads(cast(str, result)) == {
        "outcome": "activity",
        "reason": (
            "new user input, agent or subagent message, scheduled continuation, "
            "external-channel request, or action"
        ),
    }
