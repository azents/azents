"""Discord Gateway protocol primitives for the dedicated ingress worker."""

import asyncio
import dataclasses
import datetime
import json
from collections.abc import Awaitable, Callable
from typing import Protocol

from websockets.asyncio.client import connect as websocket_connect
from websockets.exceptions import ConnectionClosed

MAX_DISCORD_GATEWAY_MESSAGE_BYTES = 256 * 1024
DISCORD_GATEWAY_INTENTS = 1 | 512 | 32768
_DEFAULT_PROPERTIES = {
    "os": "linux",
    "browser": "azents",
    "device": "azents",
}


class DiscordGatewayError(ValueError):
    """Base class for controlled Discord Gateway protocol failures."""


class DiscordGatewayInvalidPayload(DiscordGatewayError):
    """Discord sent an invalid or unsupported Gateway payload."""


@dataclasses.dataclass(frozen=True)
class DiscordGatewayCheckpoint:
    """Resumable Discord Gateway state owned by the current lease."""

    session_id: str
    resume_gateway_url: str
    sequence: int


@dataclasses.dataclass(frozen=True)
class DiscordGatewayConnectionResult:
    """Reason one Discord Gateway connection stopped."""

    reconnect: bool
    can_resume: bool
    reason: str
    checkpoint: DiscordGatewayCheckpoint | None


class DiscordGatewayConnection(Protocol):
    """Minimal WebSocket surface required by the Gateway runner."""

    async def recv(self) -> str | bytes:
        """Receive one Gateway frame."""
        ...

    async def send(self, message: str) -> None:
        """Send one Gateway frame."""
        ...

    async def close(self) -> None:
        """Close the Gateway WebSocket."""
        ...


type DiscordGatewayConnector = Callable[
    [str, float, float, int],
    Awaitable[DiscordGatewayConnection],
]
type DiscordGatewayCheckpointSink = Callable[
    [DiscordGatewayCheckpoint],
    Awaitable[None],
]
type DiscordGatewayClock = Callable[[], datetime.datetime]


async def _connect_gateway(
    endpoint_url: str,
    ping_interval_seconds: float,
    ping_timeout_seconds: float,
    max_size: int,
) -> DiscordGatewayConnection:
    """Open one direct Discord Gateway WebSocket."""
    return await websocket_connect(
        endpoint_url,
        ping_interval=ping_interval_seconds,
        ping_timeout=ping_timeout_seconds,
        max_size=max_size,
    )


def _utc_now() -> datetime.datetime:
    """Return a timezone-aware timestamp for protocol bookkeeping."""
    return datetime.datetime.now(datetime.UTC)


class DiscordGatewayClient:
    """Run one fenced Discord Gateway connection without domain routing logic."""

    def __init__(
        self,
        *,
        connector: DiscordGatewayConnector = _connect_gateway,
        clock: DiscordGatewayClock = _utc_now,
        ping_interval_seconds: float = 20.0,
        ping_timeout_seconds: float = 20.0,
    ) -> None:
        """Initialize a Gateway client with transport dependencies."""
        if ping_interval_seconds <= 0:
            raise ValueError("Discord Gateway ping interval must be positive.")
        if ping_timeout_seconds <= 0:
            raise ValueError("Discord Gateway ping timeout must be positive.")
        self.connector = connector
        self.clock = clock
        self.ping_interval_seconds = ping_interval_seconds
        self.ping_timeout_seconds = ping_timeout_seconds

    async def run_connection(
        self,
        *,
        endpoint_url: str,
        bot_token: str,
        checkpoint: DiscordGatewayCheckpoint | None,
        persist_checkpoint: DiscordGatewayCheckpointSink,
    ) -> DiscordGatewayConnectionResult:
        """Run one Gateway session until Discord requests reconnection or closes it."""
        connection = await self.connector(
            endpoint_url,
            self.ping_interval_seconds,
            self.ping_timeout_seconds,
            MAX_DISCORD_GATEWAY_MESSAGE_BYTES,
        )
        active_checkpoint = checkpoint
        try:
            hello = _parse_payload(await connection.recv())
            heartbeat_interval_seconds = _heartbeat_interval_seconds(hello)
            await connection.send(
                json.dumps(
                    _initial_payload(bot_token=bot_token, checkpoint=checkpoint),
                    separators=(",", ":"),
                )
            )
            while True:
                try:
                    message = await asyncio.wait_for(
                        connection.recv(),
                        timeout=heartbeat_interval_seconds,
                    )
                except TimeoutError:
                    await connection.send(
                        json.dumps(
                            {
                                "op": 1,
                                "d": (
                                    active_checkpoint.sequence
                                    if active_checkpoint is not None
                                    else None
                                ),
                            },
                            separators=(",", ":"),
                        )
                    )
                    continue
                payload = _parse_payload(message)
                op = payload["op"]
                if op == 0:
                    active_checkpoint = _advance_checkpoint(
                        payload=payload,
                        checkpoint=active_checkpoint,
                    )
                    if active_checkpoint is not None:
                        await persist_checkpoint(active_checkpoint)
                    continue
                if op == 1:
                    await connection.send(
                        json.dumps(
                            {
                                "op": 1,
                                "d": (
                                    active_checkpoint.sequence
                                    if active_checkpoint is not None
                                    else None
                                ),
                            },
                            separators=(",", ":"),
                        )
                    )
                    continue
                if op == 7:
                    return DiscordGatewayConnectionResult(
                        reconnect=True,
                        can_resume=active_checkpoint is not None,
                        reason="reconnect_requested",
                        checkpoint=active_checkpoint,
                    )
                if op == 9:
                    can_resume = payload["d"] is True and active_checkpoint is not None
                    return DiscordGatewayConnectionResult(
                        reconnect=True,
                        can_resume=can_resume,
                        reason="invalid_session",
                        checkpoint=active_checkpoint if can_resume else None,
                    )
        except ConnectionClosed as error:
            close_code = getattr(error, "code", None)
            if close_code == 4014:
                return DiscordGatewayConnectionResult(
                    reconnect=False,
                    can_resume=False,
                    reason="intents_disallowed",
                    checkpoint=active_checkpoint,
                )
            return DiscordGatewayConnectionResult(
                reconnect=True,
                can_resume=active_checkpoint is not None,
                reason="connection_closed",
                checkpoint=active_checkpoint,
            )
        finally:
            await connection.close()


def _parse_payload(message: str | bytes) -> dict[str, object]:
    """Parse one bounded Gateway frame into a minimal protocol object."""
    if isinstance(message, bytes):
        try:
            message = message.decode()
        except UnicodeDecodeError as error:
            raise DiscordGatewayInvalidPayload(
                "Discord Gateway frame is not valid UTF-8."
            ) from error
    if len(message.encode()) > MAX_DISCORD_GATEWAY_MESSAGE_BYTES:
        raise DiscordGatewayInvalidPayload("Discord Gateway frame is too large.")
    try:
        value: object = json.loads(message)
    except json.JSONDecodeError as error:
        raise DiscordGatewayInvalidPayload(
            "Discord Gateway frame is invalid JSON."
        ) from error
    if not isinstance(value, dict):
        raise DiscordGatewayInvalidPayload("Discord Gateway frame must be an object.")
    op = value.get("op")
    if not isinstance(op, int) or isinstance(op, bool):
        raise DiscordGatewayInvalidPayload(
            "Discord Gateway frame has an invalid opcode."
        )
    return value


def _heartbeat_interval_seconds(payload: dict[str, object]) -> float:
    """Return the Hello heartbeat interval or reject a malformed Hello frame."""
    if payload["op"] != 10:
        raise DiscordGatewayInvalidPayload("Discord Gateway must begin with Hello.")
    data = payload.get("d")
    if not isinstance(data, dict):
        raise DiscordGatewayInvalidPayload("Discord Gateway Hello is malformed.")
    interval = data.get("heartbeat_interval")
    if (
        not isinstance(interval, int | float)
        or isinstance(interval, bool)
        or interval <= 0
    ):
        raise DiscordGatewayInvalidPayload(
            "Discord Gateway Hello has an invalid heartbeat interval."
        )
    return float(interval) / 1000


def _initial_payload(
    *,
    bot_token: str,
    checkpoint: DiscordGatewayCheckpoint | None,
) -> dict[str, object]:
    """Build a Resume when durable state exists, otherwise an Identify."""
    if checkpoint is not None:
        return {
            "op": 6,
            "d": {
                "token": bot_token,
                "session_id": checkpoint.session_id,
                "seq": checkpoint.sequence,
            },
        }
    return {
        "op": 2,
        "d": {
            "token": bot_token,
            "intents": DISCORD_GATEWAY_INTENTS,
            "properties": _DEFAULT_PROPERTIES,
        },
    }


def _advance_checkpoint(
    *,
    payload: dict[str, object],
    checkpoint: DiscordGatewayCheckpoint | None,
) -> DiscordGatewayCheckpoint | None:
    """Advance durable resume state after one safely handled Dispatch."""
    sequence = payload.get("s")
    if not isinstance(sequence, int) or isinstance(sequence, bool) or sequence < 0:
        raise DiscordGatewayInvalidPayload(
            "Discord Gateway Dispatch has an invalid sequence."
        )
    event_name = payload.get("t")
    data = payload.get("d")
    if event_name == "READY":
        if not isinstance(data, dict):
            raise DiscordGatewayInvalidPayload("Discord READY payload is malformed.")
        session_id = data.get("session_id")
        resume_gateway_url = data.get("resume_gateway_url")
        if not isinstance(session_id, str) or not session_id:
            raise DiscordGatewayInvalidPayload("Discord READY is missing a session ID.")
        if not isinstance(resume_gateway_url, str) or not resume_gateway_url.startswith(
            "wss://"
        ):
            raise DiscordGatewayInvalidPayload(
                "Discord READY has an invalid resume Gateway URL."
            )
        return DiscordGatewayCheckpoint(
            session_id=session_id,
            resume_gateway_url=resume_gateway_url,
            sequence=sequence,
        )
    if checkpoint is None:
        return None
    return dataclasses.replace(checkpoint, sequence=sequence)
