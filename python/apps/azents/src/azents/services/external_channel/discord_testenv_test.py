"""Tests for deterministic Discord test-environment collaborators."""

from unittest.mock import AsyncMock

import pytest

from azents.services.external_channel import discord_testenv
from azents.services.external_channel.discord_testenv import (
    DiscordTestenvGatewayRunner,
)


class _GatewayIdleReached(Exception):
    """Stop the runner after it reaches the stable open state."""


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("scenarios", "expected_resume_attempts", "expected_lifecycle"),
    [
        (
            ["invalid_session_resumable", "open"],
            [False, True],
            ["ready", "disconnected", "resumed"],
        ),
        (
            ["reconnect", "invalid_session_fresh", "open"],
            [False, True, False],
            [
                "ready",
                "disconnected",
                "resumed",
                "disconnected",
                "ready",
            ],
        ),
    ],
)
async def test_gateway_invalid_session_selects_resume_or_fresh_identify(
    monkeypatch: pytest.MonkeyPatch,
    scenarios: list[str],
    expected_resume_attempts: list[bool],
    expected_lifecycle: list[str],
) -> None:
    """Invalid sessions reconnect with Resume only when the fixture permits it."""
    resume_attempts: list[bool] = []

    async def gateway_attempt(
        client: object,
        url: str,
        *,
        target_guild_id: str,
        resumed: bool,
    ) -> dict[str, object]:
        del client, url, target_guild_id
        resume_attempts.append(resumed)
        return {"scenario": scenarios.pop(0), "dispatches": []}

    async def stop_after_open(delay: float) -> None:
        del delay
        raise _GatewayIdleReached

    monkeypatch.setattr(discord_testenv, "_gateway_attempt", gateway_attempt)
    monkeypatch.setattr(discord_testenv.asyncio, "sleep", stop_after_open)
    lifecycle = AsyncMock()

    with pytest.raises(_GatewayIdleReached):
        await DiscordTestenvGatewayRunner("http://discord.test").run_connection(
            bot_token="redacted-token",
            target_guild_id="300",
            handle_event=AsyncMock(),
            handle_lifecycle=lifecycle,
        )

    assert resume_attempts == expected_resume_attempts
    assert [call.args[0] for call in lifecycle.await_args_list] == expected_lifecycle
