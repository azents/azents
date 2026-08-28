"""Tests for deterministic Discord test-environment collaborators."""

import asyncio
import json
from collections.abc import Callable
from unittest.mock import AsyncMock

import httpx
import pytest

from azents.repos.external_channel.data import DiscordGatewayTypingTarget
from azents.services.external_channel import discord_testenv
from azents.services.external_channel.discord_testenv import (
    DiscordGatewayError,
    DiscordTestenvGatewayRunner,
    DiscordTestenvSDKClientFactory,
)


class _GatewayIdleReached(Exception):
    """Stop the runner after it reaches the stable open state."""


def _typing_target(
    *,
    channel_id: str = "400",
    work_cycle_ids: tuple[str, ...] = ("private-work-cycle-id",),
) -> DiscordGatewayTypingTarget:
    """Return one target whose source Work IDs must be omitted from snapshots."""
    return DiscordGatewayTypingTarget(
        guild_id="300",
        channel_id=channel_id,
        work_cycle_ids=work_cycle_ids,
    )


def _fixture_client(
    responder: httpx.MockTransport,
) -> Callable[..., httpx.AsyncClient]:
    """Create a typed fixture Client factory backed by one local transport."""
    async_client = httpx.AsyncClient

    def create(*args: object, **kwargs: object) -> httpx.AsyncClient:
        del args, kwargs
        return async_client(transport=responder)

    return create


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
            load_typing_targets=AsyncMock(return_value=()),
        )

    assert resume_attempts == expected_resume_attempts
    assert [call.args[0] for call in lifecycle.await_args_list] == expected_lifecycle


@pytest.mark.asyncio
async def test_gateway_publishes_active_then_empty_typing_snapshots(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Target reconciliation publishes only redacted full snapshots."""
    snapshots: list[dict[str, object]] = []
    empty_snapshot = asyncio.Event()
    load_count = 0

    async def gateway_attempt(
        client: object,
        url: str,
        *,
        target_guild_id: str,
        resumed: bool,
    ) -> dict[str, object]:
        del client, url, target_guild_id, resumed
        return {"scenario": "open", "dispatches": []}

    async def load_typing_targets() -> tuple[DiscordGatewayTypingTarget, ...]:
        nonlocal load_count
        load_count += 1
        return (_typing_target(),) if load_count == 1 else ()

    def respond(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/__testenv/typing"
        payload = json.loads(request.content)
        snapshots.append(payload)
        if payload == {"targets": []}:
            empty_snapshot.set()
        return httpx.Response(204)

    monkeypatch.setattr(discord_testenv, "_gateway_attempt", gateway_attempt)
    monkeypatch.setattr(
        discord_testenv.httpx,
        "AsyncClient",
        _fixture_client(httpx.MockTransport(respond)),
    )
    monkeypatch.setattr(discord_testenv, "_TYPING_SNAPSHOT_INTERVAL_SECONDS", 0.001)
    task = asyncio.create_task(
        DiscordTestenvGatewayRunner("http://discord.test").run_connection(
            bot_token="redacted-token",
            target_guild_id="300",
            interactions_callback_base_url="https://callbacks.example/",
            interactions_callback_selector_hash="selector-hash",
            handle_event=AsyncMock(),
            handle_lifecycle=AsyncMock(),
            load_typing_targets=load_typing_targets,
        )
    )

    await empty_snapshot.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    assert snapshots == [
        {
            "targets": [
                {
                    "guild_id": "300",
                    "channel_id": "400",
                    "work_cycle_count": 1,
                }
            ]
        },
        {"targets": []},
    ]
    assert "private-work-cycle-id" not in str(snapshots)


@pytest.mark.asyncio
async def test_gateway_repeats_typing_pulses_for_the_same_active_target(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An unchanged active target is renewed without exposing its Work identity."""
    snapshots: list[dict[str, object]] = []
    renewed = asyncio.Event()

    async def gateway_attempt(
        client: object,
        url: str,
        *,
        target_guild_id: str,
        resumed: bool,
    ) -> dict[str, object]:
        del client, url, target_guild_id, resumed
        return {"scenario": "open", "dispatches": []}

    def respond(request: httpx.Request) -> httpx.Response:
        snapshots.append(json.loads(request.content))
        if len(snapshots) == 2:
            renewed.set()
        return httpx.Response(204)

    monkeypatch.setattr(discord_testenv, "_gateway_attempt", gateway_attempt)
    monkeypatch.setattr(
        discord_testenv.httpx,
        "AsyncClient",
        _fixture_client(httpx.MockTransport(respond)),
    )
    monkeypatch.setattr(discord_testenv, "_TYPING_SNAPSHOT_INTERVAL_SECONDS", 0.001)
    task = asyncio.create_task(
        DiscordTestenvGatewayRunner("http://discord.test").run_connection(
            bot_token="redacted-token",
            target_guild_id="300",
            interactions_callback_base_url="https://callbacks.example/",
            interactions_callback_selector_hash="selector-hash",
            handle_event=AsyncMock(),
            handle_lifecycle=AsyncMock(),
            load_typing_targets=AsyncMock(return_value=(_typing_target(),)),
        )
    )

    await renewed.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    assert (
        snapshots
        == [
            {
                "targets": [
                    {
                        "guild_id": "300",
                        "channel_id": "400",
                        "work_cycle_count": 1,
                    }
                ]
            }
        ]
        * 2
    )


@pytest.mark.asyncio
async def test_gateway_retries_typing_provider_failure_without_stopping(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """One controlled fixture failure is isolated from the open Gateway lifecycle."""
    attempts = 0
    recovered = asyncio.Event()

    async def gateway_attempt(
        client: object,
        url: str,
        *,
        target_guild_id: str,
        resumed: bool,
    ) -> dict[str, object]:
        del client, url, target_guild_id, resumed
        return {"scenario": "open", "dispatches": []}

    def respond(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        assert request.url.path == "/__testenv/typing"
        attempts += 1
        if attempts == 1:
            return httpx.Response(503)
        recovered.set()
        return httpx.Response(204)

    monkeypatch.setattr(discord_testenv, "_gateway_attempt", gateway_attempt)
    monkeypatch.setattr(
        discord_testenv.httpx,
        "AsyncClient",
        _fixture_client(httpx.MockTransport(respond)),
    )
    monkeypatch.setattr(
        discord_testenv,
        "_TYPING_SNAPSHOT_RETRY_INTERVAL_SECONDS",
        0.001,
    )
    task = asyncio.create_task(
        DiscordTestenvGatewayRunner("http://discord.test").run_connection(
            bot_token="redacted-token",
            target_guild_id="300",
            interactions_callback_base_url="https://callbacks.example/",
            interactions_callback_selector_hash="selector-hash",
            handle_event=AsyncMock(),
            handle_lifecycle=AsyncMock(),
            load_typing_targets=AsyncMock(return_value=(_typing_target(),)),
        )
    )

    await recovered.wait()
    assert not task.done()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert attempts == 2


@pytest.mark.asyncio
async def test_gateway_rejects_stale_typing_target_authority(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A stale loader remains an authority failure before provider typing begins."""
    calls: list[httpx.Request] = []

    async def gateway_attempt(
        client: object,
        url: str,
        *,
        target_guild_id: str,
        resumed: bool,
    ) -> dict[str, object]:
        del client, url, target_guild_id, resumed
        return {"scenario": "open", "dispatches": []}

    def respond(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(204)

    monkeypatch.setattr(discord_testenv, "_gateway_attempt", gateway_attempt)
    monkeypatch.setattr(
        discord_testenv.httpx,
        "AsyncClient",
        _fixture_client(httpx.MockTransport(respond)),
    )

    with pytest.raises(DiscordGatewayError, match="authority is unavailable"):
        await DiscordTestenvGatewayRunner("http://discord.test").run_connection(
            bot_token="redacted-token",
            target_guild_id="300",
            interactions_callback_base_url="https://callbacks.example/",
            interactions_callback_selector_hash="selector-hash",
            handle_event=AsyncMock(),
            handle_lifecycle=AsyncMock(),
            load_typing_targets=AsyncMock(return_value=None),
        )

    assert calls == []
