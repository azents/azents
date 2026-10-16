"""Full toolkit invocation with semantic actions and provider-neutral schema."""

import json
from collections.abc import Sequence

import pytest

from azents.core.external_channel_navigation import (
    ChannelNavigationAction,
    ChannelNavigationLink,
)
from azents.engine.tooling.execution_context import client_tool_execution_context
from azents.engine.tools.external_channel_test import (
    _ActionService,
    _snapshot,
    _toolkit,
    _turn_context,
)


class _NavigationService(_ActionService):
    """Resolve a detached destination while retaining normal toolkit invocation."""

    async def prepare_navigation(
        self,
        *,
        actions: Sequence[ChannelNavigationAction],
        session_id: str,
        agent_id: str,
        binding_id: str,
    ) -> tuple[ChannelNavigationLink, ...]:
        assert list(actions) == [ChannelNavigationAction(type="browser")]
        assert (session_id, agent_id, binding_id) == (
            "session-1",
            "agent-1",
            "binding-1",
        )
        return (
            ChannelNavigationLink(
                label="Open browser",
                url="https://azents.example/browser",
            ),
        )


@pytest.mark.parametrize("mode", ["continue", "request_input", "finish"])
async def test_tool_invocation_carries_actions_through_scheduled_probe(
    mode: str,
) -> None:
    service = _NavigationService([_snapshot()])
    toolkit = _toolkit(service)
    state = await toolkit.update_context(_turn_context())
    tool = state.tools[0]
    assert tool.spec.input_schema["type"] == "object"
    assert "oneOf" not in json.dumps(tool.spec.input_schema)
    with client_tool_execution_context(call_id="navigation", name="channel_action"):
        await tool.handler(
            json.dumps(
                {
                    "mode": mode,
                    "binding": "binding-1",
                    "message": "Open browser",
                    "actions": [{"type": "browser"}],
                }
            )
        )
    assert service.calls[0]["links"] == (
        ChannelNavigationLink(
            label="Open browser",
            url="https://azents.example/browser",
        ),
    )
