"""Tests for deterministic Discord test-environment collaborators."""

import json
from unittest.mock import AsyncMock

import httpx
import pytest

from azents.services.external_channel import discord_testenv
from azents.services.external_channel.discord_testenv import (
    DiscordTestenvGatewayRunner,
    DiscordTestenvSDKClientFactory,
)


class _GatewayIdleReached(Exception):
    """Stop the runner after it reaches the stable open state."""


@pytest.mark.asyncio
async def test_sdk_factory_login_populates_current_bot_user(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Opening the fixture session models the public SDK's authenticated user."""
    operations: list[str] = []
    async_client = httpx.AsyncClient

    def respond(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content)
        operation = payload["operation"]
        operations.append(operation)
        if operation == "login":
            return httpx.Response(200, json={"bot_user_id": "900"})
        return httpx.Response(
            200,
            json={"application_id": "800", "verify_key": "0" * 64},
        )

    def fixture_client(*args: object, **kwargs: object) -> httpx.AsyncClient:
        del args, kwargs
        return async_client(transport=httpx.MockTransport(respond))

    monkeypatch.setattr(discord_testenv.httpx, "AsyncClient", fixture_client)

    async with DiscordTestenvSDKClientFactory("http://discord.test").open(
        bot_token="redacted-token"
    ) as session:
        assert session.current_bot_user_id() == "900"
        application = await session.fetch_application()

    assert application.application_id == "800"
    assert operations == ["login", "fetch_application"]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("scenarios", "expected_resume_attempts", "expected_lifecycle"),
    [
        (
            ["invalid_session_resumable", "open"],
            [False, True],
            ["disconnected", "resumed"],
        ),
        (
            ["reconnect", "invalid_session_fresh", "open"],
            [False, True, False],
            [
                "disconnected",
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
            interactions_callback_base_url="https://callbacks.example/",
            interactions_callback_selector_hash="selector-hash",
            handle_event=AsyncMock(),
            handle_lifecycle=lifecycle,
        )

    assert resume_attempts == expected_resume_attempts
    assert [call.args[0] for call in lifecycle.await_args_list] == expected_lifecycle
