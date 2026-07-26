"""Deterministic protocol tests for the Discord Gateway client."""

import json
from collections.abc import Awaitable, Callable

import pytest
from pytest import MonkeyPatch

from azents.services.external_channel.discord_gateway import (
    DISCORD_GATEWAY_INTENTS,
    DiscordGatewayCheckpoint,
    DiscordGatewayClient,
    DiscordGatewayDispatch,
    DiscordGatewayInvalidPayload,
)


class _Socket:
    """Script one Gateway WebSocket exchange without a network dependency."""

    def __init__(self, messages: list[dict[str, object]]) -> None:
        self.messages = [json.dumps(message) for message in messages]
        self.sent: list[dict[str, object]] = []
        self.closed = False

    async def recv(self) -> str:
        return self.messages.pop(0)

    async def send(self, message: str) -> None:
        value = json.loads(message)
        assert isinstance(value, dict)
        self.sent.append(value)

    async def close(self) -> None:
        self.closed = True


async def _connector(
    socket: _Socket,
    _endpoint_url: str,
    _ping_interval_seconds: float,
    _ping_timeout_seconds: float,
    _max_size: int,
) -> _Socket:
    return socket


@pytest.mark.asyncio
async def test_identify_persists_ready_checkpoint_before_reconnect() -> None:
    """A fresh session identifies and saves READY sequence state before reconnecting."""
    socket = _Socket(
        [
            {"op": 10, "d": {"heartbeat_interval": 60_000}},
            {
                "op": 0,
                "s": 4,
                "t": "READY",
                "d": {
                    "session_id": "session-1",
                    "resume_gateway_url": "wss://gateway.discord.gg",
                },
            },
            {"op": 7, "d": None},
        ]
    )
    checkpoints: list[DiscordGatewayCheckpoint] = []
    client = DiscordGatewayClient(
        connector=lambda *args: _connector(socket, *args),
    )

    result = await client.run_connection(
        endpoint_url="wss://gateway.discord.gg",
        bot_token="redacted-token",
        checkpoint=None,
        persist_checkpoint=_checkpoint_sink(checkpoints),
        handle_dispatch=_dispatch_sink([]),
    )

    assert socket.sent[0] == {
        "op": 2,
        "d": {
            "token": "redacted-token",
            "intents": DISCORD_GATEWAY_INTENTS,
            "properties": {
                "os": "linux",
                "browser": "azents",
                "device": "azents",
            },
        },
    }
    assert checkpoints == [
        DiscordGatewayCheckpoint(
            session_id="session-1",
            resume_gateway_url="wss://gateway.discord.gg",
            sequence=4,
        )
    ]
    assert result.reconnect is True
    assert result.can_resume is True
    assert result.reason == "reconnect_requested"
    assert socket.closed is True


@pytest.mark.asyncio
async def test_test_gateway_ready_can_checkpoint_an_explicit_ws_fake(
    monkeypatch: MonkeyPatch,
) -> None:
    """Allow a test-only fake URL through the same READY checkpoint boundary."""
    monkeypatch.setenv(
        "AZ_TESTENV_DISCORD_API_BASE_URL",
        "http://discord-fake:8085/api/v10",
    )
    monkeypatch.setenv("AZ_TESTENV_DISCORD_ALLOW_INSECURE_GATEWAY", "true")
    socket = _Socket(
        [
            {"op": 10, "d": {"heartbeat_interval": 60_000}},
            {
                "op": 0,
                "s": 4,
                "t": "READY",
                "d": {
                    "session_id": "session-1",
                    "resume_gateway_url": "ws://discord-fake:8086",
                },
            },
            {"op": 7, "d": None},
        ]
    )
    checkpoints: list[DiscordGatewayCheckpoint] = []
    client = DiscordGatewayClient(
        connector=lambda *args: _connector(socket, *args),
    )

    result = await client.run_connection(
        endpoint_url="ws://discord-fake:8086",
        bot_token="redacted-token",
        checkpoint=None,
        persist_checkpoint=_checkpoint_sink(checkpoints),
        handle_dispatch=_dispatch_sink([]),
    )

    assert checkpoints == [
        DiscordGatewayCheckpoint(
            session_id="session-1",
            resume_gateway_url="ws://discord-fake:8086",
            sequence=4,
        )
    ]
    assert result.can_resume is True


@pytest.mark.asyncio
async def test_resume_advances_existing_checkpoint() -> None:
    """A resumed session keeps its identity and advances dispatch sequence."""
    checkpoint = DiscordGatewayCheckpoint(
        session_id="session-1",
        resume_gateway_url="wss://gateway.discord.gg",
        sequence=4,
    )
    socket = _Socket(
        [
            {"op": 10, "d": {"heartbeat_interval": 60_000}},
            {"op": 0, "s": 5, "t": "RESUMED", "d": {}},
            {"op": 9, "d": False},
        ]
    )
    checkpoints: list[DiscordGatewayCheckpoint] = []
    client = DiscordGatewayClient(
        connector=lambda *args: _connector(socket, *args),
    )

    result = await client.run_connection(
        endpoint_url=checkpoint.resume_gateway_url,
        bot_token="redacted-token",
        checkpoint=checkpoint,
        persist_checkpoint=_checkpoint_sink(checkpoints),
        handle_dispatch=_dispatch_sink([]),
    )

    assert socket.sent[0] == {
        "op": 6,
        "d": {
            "token": "redacted-token",
            "session_id": "session-1",
            "seq": 4,
        },
    }
    assert checkpoints == [
        DiscordGatewayCheckpoint(
            session_id="session-1",
            resume_gateway_url="wss://gateway.discord.gg",
            sequence=5,
        )
    ]
    assert result.reconnect is True
    assert result.can_resume is False
    assert result.checkpoint is None


@pytest.mark.asyncio
async def test_dispatch_handler_finishes_before_checkpoint_persistence() -> None:
    """A dispatched event is admitted by its callback before resume state advances."""
    socket = _Socket(
        [
            {"op": 10, "d": {"heartbeat_interval": 60_000}},
            {
                "op": 0,
                "s": 4,
                "t": "READY",
                "d": {
                    "session_id": "session-1",
                    "resume_gateway_url": "wss://gateway.discord.gg",
                },
            },
            {
                "op": 0,
                "s": 5,
                "t": "MESSAGE_CREATE",
                "d": {"id": "message-1"},
            },
            {"op": 7, "d": None},
        ]
    )
    events: list[str] = []
    client = DiscordGatewayClient(
        connector=lambda *args: _connector(socket, *args),
    )

    async def handle_dispatch(dispatch: DiscordGatewayDispatch) -> bool:
        assert dispatch.session_id == "session-1"
        assert dispatch.resume_gateway_url == "wss://gateway.discord.gg"
        assert dispatch.sequence == 5
        assert dispatch.event_name == "MESSAGE_CREATE"
        events.append("dispatch")
        return False

    async def persist_checkpoint(checkpoint: DiscordGatewayCheckpoint) -> None:
        events.append(f"checkpoint:{checkpoint.sequence}")

    await client.run_connection(
        endpoint_url="wss://gateway.discord.gg",
        bot_token="redacted-token",
        checkpoint=None,
        persist_checkpoint=persist_checkpoint,
        handle_dispatch=handle_dispatch,
    )

    assert events == ["checkpoint:4", "dispatch", "checkpoint:5"]


@pytest.mark.asyncio
async def test_rejects_dispatch_without_a_sequence() -> None:
    """Malformed Dispatches do not advance resumable state."""
    socket = _Socket(
        [
            {"op": 10, "d": {"heartbeat_interval": 60_000}},
            {"op": 0, "s": None, "t": "READY", "d": {}},
        ]
    )
    client = DiscordGatewayClient(
        connector=lambda *args: _connector(socket, *args),
    )

    with pytest.raises(DiscordGatewayInvalidPayload, match="invalid sequence"):
        await client.run_connection(
            endpoint_url="wss://gateway.discord.gg",
            bot_token="redacted-token",
            checkpoint=None,
            persist_checkpoint=lambda _checkpoint: _unexpected_persist(),
            handle_dispatch=_dispatch_sink([]),
        )
    assert socket.closed is True


async def _unexpected_persist() -> None:
    raise AssertionError("Malformed Dispatch must not persist a checkpoint.")


def _checkpoint_sink(
    checkpoints: list[DiscordGatewayCheckpoint],
) -> Callable[[DiscordGatewayCheckpoint], Awaitable[None]]:
    """Build an async sink that records one durable checkpoint write."""

    async def persist(checkpoint: DiscordGatewayCheckpoint) -> None:
        checkpoints.append(checkpoint)

    return persist


def _dispatch_sink(
    dispatches: list[DiscordGatewayDispatch],
) -> Callable[[DiscordGatewayDispatch], Awaitable[bool]]:
    """Build an async sink that records dispatched payloads."""

    async def handle(dispatch: DiscordGatewayDispatch) -> bool:
        dispatches.append(dispatch)
        return False

    return handle
