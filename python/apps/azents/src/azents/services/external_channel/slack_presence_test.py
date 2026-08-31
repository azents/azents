"""Slack Work presence SDK adapter tests."""

from unittest.mock import AsyncMock

import pytest
from slack_sdk.errors import SlackApiError
from slack_sdk.web.async_slack_response import AsyncSlackResponse

from azents.repos.external_channel.data import SlackWorkPresenceTarget
from azents.services.external_channel.slack_presence import SlackWorkPresenceClient


def _target(
    *,
    kind: str = "channel_loading",
    desired_state: str = "processing",
) -> SlackWorkPresenceTarget:
    return SlackWorkPresenceTarget(
        binding_id="binding-1",
        work_cycle_id="work-1",
        kind=kind,  # ty: ignore[invalid-argument-type] — parameters intentionally exercise the closed provider variants.
        desired_state=desired_state,  # ty: ignore[invalid-argument-type] — parameters intentionally exercise the closed provider variants.
        channel_id="C1",
        thread_ts="1721600000.000100",
        initiator_user_id="U1",
        status_text="Investigating…",
        agent_name="Research Agent",
        customize_messages=True,
    )


@pytest.mark.asyncio
async def test_channel_loading_uses_public_assistant_status_method() -> None:
    """Parent-channel Work uses the bounded assistant loading projection."""
    web_client = AsyncMock()
    web_client.assistant_threads_setStatus.return_value = AsyncMock()
    client = SlackWorkPresenceClient(web_client)

    outcome = await client.set_presence(
        bot_token="xoxb-secret",
        target=_target(),
    )

    assert outcome.status == "delivered"
    web_client.assistant_threads_setStatus.assert_called_once_with(
        channel_id="C1",
        thread_ts="1721600000.000100",
        status="Investigating…",
        username="Research Agent",
        token="xoxb-secret",
    )
    web_client.agents_sessions_setStatus.assert_not_called()


@pytest.mark.asyncio
async def test_thread_idle_uses_public_agent_session_status_method() -> None:
    """Finished exact-thread Work restores the native Agent Session to active."""
    web_client = AsyncMock()
    web_client.agents_sessions_setStatus.return_value = AsyncMock()
    client = SlackWorkPresenceClient(web_client)

    outcome = await client.set_presence(
        bot_token="xoxb-secret",
        target=_target(kind="thread_agent", desired_state="idle"),
    )

    assert outcome.status == "delivered"
    web_client.agents_sessions_setStatus.assert_called_once_with(
        channel_id="C1",
        thread_ts="1721600000.000100",
        status="active",
        initiator_user_id=None,
        username="Research Agent",
        token="xoxb-secret",
    )
    web_client.assistant_threads_setStatus.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("status_code", "error_code", "expected_status", "expected_kind"),
    [
        (429, "ratelimited", "failed", "rate_limited"),
        (200, "missing_scope", "failed", "missing_scope"),
        (200, "feature_disabled", "failed", "feature_disabled"),
        (200, "invalid_auth", "failed", "credentials_invalid"),
        (200, "thread_not_found", "failed", "resource_unavailable"),
        (503, "fatal_error", "unknown", "provider_ambiguous"),
    ],
)
async def test_provider_rejections_are_sanitized(
    status_code: int,
    error_code: str,
    expected_status: str,
    expected_kind: str,
) -> None:
    """Provider bodies collapse into closed presence outcome classes."""
    response = AsyncSlackResponse(
        client=AsyncMock(),
        http_verb="POST",
        api_url="https://slack.example/api/assistant.threads.setStatus",
        req_args={},
        data={"ok": False, "error": error_code},
        headers={},
        status_code=status_code,
    )
    web_client = AsyncMock()
    web_client.assistant_threads_setStatus.side_effect = SlackApiError(
        "rejected",
        response,
    )
    client = SlackWorkPresenceClient(web_client)

    outcome = await client.set_presence(
        bot_token="xoxb-secret",
        target=_target(),
    )

    assert outcome.status == expected_status
    assert outcome.error_kind == expected_kind
    assert "xoxb-secret" not in repr(outcome)
