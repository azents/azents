"""Exercise the real channel case's registered HTTP-bounded cleanup callback."""

from collections.abc import Callable
from unittest.mock import Mock, call

import pytest

from support import utils
from support.utils import AgentSessionSetup
from tests.required.public import test_routine_channels as channels


@pytest.mark.parametrize("failure", ["none", "timeout", "truncated"])
def test_registered_case_drain_bounds_lists_and_rejects_incomplete_observation(
    monkeypatch: pytest.MonkeyPatch, failure: str
) -> None:
    # Keep the real poll/error chaining without waiting through its wall deadline.
    monkeypatch.setattr(
        utils, "time", Mock(time=Mock(side_effect=[0, 0, 121]), sleep=Mock())
    )
    drains: list[Callable[[], object]] = []
    setup = Mock(spec=AgentSessionSetup)
    setup.access_token = "test-token"
    setup.workspace_handle = "owned-workspace"
    setup.agent_id = "owned-agent"
    setup.session_id = "primary"
    headers = {"Authorization": "Bearer test-token"}
    chat = Mock()

    def listing(**kwargs: object) -> Mock:
        assert kwargs["_request_timeout"] == 10
        assert kwargs["limit"] == 100
        if failure == "timeout":
            raise TimeoutError("bounded Session list failed")
        identities = (
            ["primary", "bound"] if kwargs["status"] == "active" else ["archived"]
        )
        return Mock(
            items=[Mock(id=value) for value in identities],
            total_count=len(identities) + int(failure == "truncated"),
        )

    chat.chat_v1_list_agent_sessions.side_effect = listing
    monkeypatch.setattr(channels, "ChatV1Api", lambda *args: chat)
    api = Mock()
    api.external_channel_v1_setup_slack_connection.side_effect = ValueError(
        "connection setup failed after drain registration"
    )
    monkeypatch.setattr(channels, "ExternalChannelV1Api", lambda *args: api)
    monkeypatch.setattr(channels.requests, "post", lambda *args, **kwargs: Mock())
    idle = Mock(return_value=True)
    monkeypatch.setattr(channels, "_live_idle", idle)

    def journey(*args: object) -> None:
        selected = args[-1]
        assert isinstance(selected, channels.RoutineChannelJourney)
        with pytest.raises(ValueError, match="connection setup failed"):
            selected.prepare_session(setup)

    monkeypatch.setattr(channels, "run_routine_journey", journey)
    gateway = Mock()
    gateway.__enter__ = Mock()
    gateway.__exit__ = Mock()
    case = channels.TestRoutinePrimaryDelivery()
    case.test_routine_current_primary_uses_one_provider_attempt_without_fallback(
        request=Mock(),
        public_api_client=Mock(),
        admin_api_client=Mock(),
        azents_public_server_url="https://public.invalid",
        azents_admin_server_url="https://admin.invalid",
        ordinary_model_stream_case=drains.append,
        azents_external_channel_gateway_factory=lambda: gateway,
        slack_provider_fake_url="https://slack.invalid",
        openai_proxy_url="https://provider.invalid",
        delivery="delivered",
    )
    assert len(drains) == 1
    drain = drains[0]
    assert callable(drain)
    if failure == "none":
        drain()
        chat.chat_v1_list_agent_sessions.assert_has_calls(
            [
                call(
                    agent_id="owned-agent",
                    status=status,
                    limit=100,
                    _headers=headers,
                    _request_timeout=10,
                )
                for status in ("active", "archived")
            ]
        )
        assert {entry.kwargs["session_id"] for entry in idle.call_args_list} == {
            "primary",
            "bound",
            "archived",
        }
    else:
        with pytest.raises(TimeoutError) as raised:
            drain()
        if failure == "truncated":
            assert isinstance(raised.value.__cause__, AssertionError)
        idle.assert_not_called()
