"""Deterministic protocol tests for the Discord Gateway client."""

import json
from collections.abc import Awaitable, Callable

import pytest

from azents.services.external_channel.discord_gateway import (
    DISCORD_GATEWAY_INTENTS,
    DiscordGatewayCheckpoint,
    DiscordGatewayClient,
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
