"""Slack Socket Mode primitives for durable External Channel event admission."""

import asyncio
import datetime
import json
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Protocol

import httpx
from websockets.asyncio.client import connect as websocket_connect
from websockets.exceptions import ConnectionClosed

from azents.repos.external_channel.data import ExternalChannelEventCreate
from azents.services.external_channel.slack_endpoint import (
    slack_api_base_url,
    slack_insecure_websocket_allowed,
)
from azents.services.external_channel.slack_http import (
    SlackEventCallback,
    SlackHTTPInvalidPayload,
    parse_slack_callback,
)

MAX_SLACK_SOCKET_MESSAGE_BYTES = 256 * 1024
DEFAULT_SLACK_SOCKET_PING_INTERVAL_SECONDS = 20.0
DEFAULT_SLACK_SOCKET_PING_TIMEOUT_SECONDS = 20.0
DEFAULT_SLACK_SOCKET_RECONNECT_DELAY_SECONDS = 1.0


class SlackSocketError(ValueError):
    """Base class for controlled Slack Socket Mode failures."""


class SlackSocketUnavailable(SlackSocketError):
    """Slack could not provide a usable Socket Mode endpoint."""


class SlackSocketReconnectRequired(SlackSocketError):
    """Slack rejected credentials that require explicit operator reconnection."""


class SlackSocketInvalidEnvelope(SlackSocketError):
    """A Socket Mode message is malformed or cannot be admitted."""


@dataclass(frozen=True)
class SlackSocketConnectionOpen:
    """One short-lived Socket Mode endpoint minted by Slack."""

    url: str


@dataclass(frozen=True)
class SlackSocketEnvelope:
    """One validated Slack Socket Mode envelope."""

    envelope_id: str | None
    type: str
    payload: dict[str, object] | None


@dataclass(frozen=True)
class SlackSocketConnectionResult:
    """Reason one Socket Mode WebSocket connection ended."""

    reconnect: bool
    reason: str
    admitted_event_count: int


class SlackSocketConnection(Protocol):
    """Minimal WebSocket client surface used by the Socket Mode runner."""

    async def recv(self) -> str | bytes:
        """Receive one Slack Socket Mode message."""
        ...

    async def send(self, message: str) -> None:
        """Send one Slack Socket Mode acknowledgement."""
        ...

    async def close(self) -> None:
        """Close the Socket Mode WebSocket."""
        ...


type SlackSocketConnector = Callable[
    [str, float, float, int], Awaitable[SlackSocketConnection]
]
type SlackSocketEventAdmission = Callable[
    [ExternalChannelEventCreate], Awaitable[object]
]
type SlackSocketSleep = Callable[[float], Awaitable[object]]
type SlackSocketClock = Callable[[], datetime.datetime]


class SlackSocketEndpointOpener(Protocol):
    """Open a freshly minted Socket Mode endpoint."""

    async def open_connection(
        self,
        *,
        app_token: str,
    ) -> SlackSocketConnectionOpen:
        """Request one short-lived Socket Mode endpoint."""
        ...


async def _connect_socket(
    endpoint_url: str,
    ping_interval_seconds: float,
    ping_timeout_seconds: float,
    max_size: int,
) -> SlackSocketConnection:
    """Open one direct WebSocket connection using the runtime dependency."""
    return await websocket_connect(
        endpoint_url,
        ping_interval=ping_interval_seconds,
        ping_timeout=ping_timeout_seconds,
        max_size=max_size,
    )


def _utc_now() -> datetime.datetime:
    """Return the current timezone-aware timestamp for durable event admission."""
    return datetime.datetime.now(datetime.UTC)


class SlackSocketWebAPIClient:
    """Open short-lived Slack Socket Mode endpoints with an app-level token."""

    def __init__(self, http_client: httpx.AsyncClient) -> None:
        self.http_client = http_client

    async def open_connection(
        self,
        *,
        app_token: str,
    ) -> SlackSocketConnectionOpen:
        """Request a Socket Mode endpoint without retaining the app token."""
        try:
            response = await self.http_client.post(
                f"{slack_api_base_url()}/apps.connections.open",
                headers={"Authorization": f"Bearer {app_token}"},
            )
        except httpx.RequestError as error:
            raise SlackSocketUnavailable(
                "Slack Socket Mode endpoint is temporarily unavailable."
            ) from error
        payload = self._json_object(response)
        if response.status_code >= 500 or response.status_code == 429:
            raise SlackSocketUnavailable(
                "Slack Socket Mode endpoint is temporarily unavailable."
            )
        url = payload.get("url")
        if response.status_code >= 400 or payload.get("ok") is not True:
            if payload.get("error") in {
                "account_inactive",
                "invalid_auth",
                "not_authed",
                "token_revoked",
            }:
                raise SlackSocketReconnectRequired(
                    "Slack rejected the Socket Mode credentials."
                )
            raise SlackSocketUnavailable("Slack rejected the Socket Mode app token.")
        secure_url = isinstance(url, str) and url.startswith("wss://")
        testenv_url = (
            isinstance(url, str)
            and url.startswith("ws://")
            and slack_insecure_websocket_allowed()
        )
        if not secure_url and not testenv_url:
            raise SlackSocketUnavailable(
                "Slack Socket Mode endpoint response is invalid."
            )
        assert isinstance(url, str)
        return SlackSocketConnectionOpen(url=url)

    @staticmethod
    def _json_object(response: httpx.Response) -> dict[str, object]:
        try:
            payload: object = response.json()
        except ValueError:
            return {}
        return payload if isinstance(payload, dict) else {}


class SlackSocketModeClient:
    """Admit Socket Mode events durably before acknowledging their envelopes."""

    def __init__(
        self,
        *,
        web_api_client: SlackSocketEndpointOpener,
        admit_event: SlackSocketEventAdmission,
        connector: SlackSocketConnector = _connect_socket,
        sleep: SlackSocketSleep = asyncio.sleep,
        clock: SlackSocketClock = _utc_now,
        ping_interval_seconds: float = DEFAULT_SLACK_SOCKET_PING_INTERVAL_SECONDS,
        ping_timeout_seconds: float = DEFAULT_SLACK_SOCKET_PING_TIMEOUT_SECONDS,
        reconnect_delay_seconds: float = DEFAULT_SLACK_SOCKET_RECONNECT_DELAY_SECONDS,
    ) -> None:
        """Initialize the connection loop with injected admission and transport."""
        if ping_interval_seconds <= 0:
            raise ValueError("Slack Socket Mode ping interval must be positive.")
        if ping_timeout_seconds <= 0:
            raise ValueError("Slack Socket Mode ping timeout must be positive.")
        if reconnect_delay_seconds < 0:
            raise ValueError("Slack Socket Mode reconnect delay must not be negative.")
        self.web_api_client = web_api_client
        self.admit_event = admit_event
        self.connector = connector
        self.sleep = sleep
        self.clock = clock
        self.ping_interval_seconds = ping_interval_seconds
        self.ping_timeout_seconds = ping_timeout_seconds
        self.reconnect_delay_seconds = reconnect_delay_seconds

    async def run(
        self,
        *,
        connection_id: str,
        app_token: str,
    ) -> SlackSocketConnectionResult:
        """Run reconnecting Socket Mode connections until Slack disables the link."""
        admitted_event_count = 0
        while True:
            opened = await self.web_api_client.open_connection(app_token=app_token)
            result = await self.run_connection(
                connection_id=connection_id,
                endpoint_url=opened.url,
            )
            admitted_event_count += result.admitted_event_count
            if not result.reconnect:
                return SlackSocketConnectionResult(
                    reconnect=False,
                    reason=result.reason,
                    admitted_event_count=admitted_event_count,
                )
            await self.sleep(self.reconnect_delay_seconds)

    async def run_connection(
        self,
        *,
        connection_id: str,
        endpoint_url: str,
    ) -> SlackSocketConnectionResult:
        """Process one WebSocket connection until it closes or requests refresh."""
        connection = await self.connector(
            endpoint_url,
            self.ping_interval_seconds,
            self.ping_timeout_seconds,
            MAX_SLACK_SOCKET_MESSAGE_BYTES,
        )
        admitted_event_count = 0
        try:
            while True:
                try:
                    message = await connection.recv()
                except ConnectionClosed:
                    return SlackSocketConnectionResult(
                        reconnect=True,
                        reason="connection_closed",
                        admitted_event_count=admitted_event_count,
                    )
                envelope = parse_slack_socket_envelope(message)
                if envelope.type == "hello":
                    continue
                if envelope.type == "disconnect":
                    reason = _disconnect_reason(envelope.payload)
                    return SlackSocketConnectionResult(
                        reconnect=reason != "link_disabled",
                        reason=reason,
                        admitted_event_count=admitted_event_count,
                    )
                if envelope.type != "events_api":
                    continue
                event = await self._admit_envelope(
                    connection_id=connection_id,
                    envelope=envelope,
                )
                await connection.send(
                    json.dumps(
                        {"envelope_id": envelope.envelope_id},
                        separators=(",", ":"),
                    )
                )
                if event is not None:
                    admitted_event_count += 1
        except asyncio.CancelledError:
            raise
        finally:
            await connection.close()

    async def _admit_envelope(
        self,
        *,
        connection_id: str,
        envelope: SlackSocketEnvelope,
    ) -> ExternalChannelEventCreate | None:
        """Durably admit one Events API envelope before its acknowledgement."""
        if envelope.envelope_id is None:
            raise SlackSocketInvalidEnvelope(
                "Slack Events API envelope is missing its envelope identifier."
            )
        if envelope.payload is None:
            raise SlackSocketInvalidEnvelope(
                "Slack Events API envelope is missing its payload."
            )
        raw_payload = json.dumps(envelope.payload, separators=(",", ":")).encode()
        try:
            callback = parse_slack_callback(
                connection_id=connection_id,
                raw_body=raw_payload,
                received_at=self.clock(),
            )
        except SlackHTTPInvalidPayload as error:
            raise SlackSocketInvalidEnvelope(
                "Slack Events API envelope payload is invalid."
            ) from error
        if not isinstance(callback, SlackEventCallback):
            raise SlackSocketInvalidEnvelope(
                "Slack Events API envelope does not contain an event callback."
            )
        event = callback.event.model_copy(
            update={"transport_envelope_id": envelope.envelope_id}
        )
        await self.admit_event(event)
        return event


def parse_slack_socket_envelope(message: str | bytes) -> SlackSocketEnvelope:
    """Parse a bounded JSON Socket Mode message without admitting it."""
    raw_message = message.encode() if isinstance(message, str) else message
    if len(raw_message) > MAX_SLACK_SOCKET_MESSAGE_BYTES:
        raise SlackSocketInvalidEnvelope(
            "Slack Socket Mode message exceeds the size limit."
        )
    try:
        payload: object = json.loads(raw_message)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise SlackSocketInvalidEnvelope(
            "Slack Socket Mode message is not valid JSON."
        ) from error
    if not isinstance(payload, dict):
        raise SlackSocketInvalidEnvelope(
            "Slack Socket Mode message must be a JSON object."
        )
    envelope_type = payload.get("type")
    if not isinstance(envelope_type, str) or not envelope_type:
        raise SlackSocketInvalidEnvelope("Slack Socket Mode envelope type is missing.")
    envelope_id = payload.get("envelope_id")
    if envelope_id is not None and (
        not isinstance(envelope_id, str) or not envelope_id
    ):
        raise SlackSocketInvalidEnvelope(
            "Slack Socket Mode envelope identifier is invalid."
        )
    envelope_payload = payload.get("payload")
    if envelope_payload is not None and not isinstance(envelope_payload, dict):
        raise SlackSocketInvalidEnvelope(
            "Slack Socket Mode envelope payload must be an object."
        )
    return SlackSocketEnvelope(
        envelope_id=envelope_id,
        type=envelope_type,
        payload=envelope_payload,
    )


def _disconnect_reason(payload: dict[str, object] | None) -> str:
    """Normalize Slack's reconnect control-message reason."""
    if payload is None:
        return "disconnect_requested"
    reason = payload.get("reason")
    if not isinstance(reason, str) or not reason:
        return "disconnect_requested"
    return reason
