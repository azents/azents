"""Slack Socket Mode primitives for synchronous External Channel handoff."""

import asyncio
import dataclasses
import datetime
import json
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Protocol

import aiohttp
from slack_sdk.errors import SlackApiError
from slack_sdk.socket_mode.request import SocketModeRequest
from slack_sdk.socket_mode.response import SocketModeResponse
from slack_sdk.web.async_client import AsyncWebClient
from slack_sdk.web.async_slack_response import AsyncSlackResponse

from azents.core.enums import ExternalChannelInteractionType
from azents.repos.external_channel.data import ExternalChannelEventCreate
from azents.services.external_channel.interaction import (
    ExternalChannelInteractionHandoff,
)
from azents.services.external_channel.slack_endpoint import (
    slack_insecure_websocket_allowed,
)
from azents.services.external_channel.slack_http import (
    SlackEventCallback,
    SlackHTTPInvalidPayload,
    SlackInteractionCallback,
    parse_slack_callback,
    parse_slack_interaction_payload,
    project_slack_shortcut_source_event,
)
from azents.services.external_channel.slack_sdk_client import (
    create_slack_socket_mode_client,
)

MAX_SLACK_SOCKET_MESSAGE_BYTES = 256 * 1024
DEFAULT_SLACK_SOCKET_PING_INTERVAL_SECONDS = 20.0
DEFAULT_SLACK_SOCKET_PING_TIMEOUT_SECONDS = 20.0
DEFAULT_SLACK_SOCKET_CONNECT_TIMEOUT_SECONDS = 20.0


class SlackSocketError(ValueError):
    """Base class for controlled Slack Socket Mode failures."""


class SlackSocketUnavailable(SlackSocketError):
    """Slack could not provide a usable Socket Mode endpoint."""


class SlackSocketReconnectRequired(SlackSocketError):
    """Slack rejected credentials that require explicit operator reconnection."""


class SlackSocketInvalidEnvelope(SlackSocketError):
    """A Socket Mode message is malformed or cannot be admitted."""


class SlackSocketRetryableIngestion(SlackSocketError):
    """A message envelope must remain unacknowledged for provider redelivery."""


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


type SlackSocketEventAdmission = Callable[
    [ExternalChannelEventCreate], Awaitable[object]
]
type SlackSocketInteractionAdmission = Callable[
    [
        SlackInteractionCallback,
        ExternalChannelEventCreate | None,
    ],
    Awaitable[ExternalChannelInteractionHandoff | None],
]
type SlackSocketInteractionScheduler = Callable[
    [ExternalChannelInteractionHandoff],
    None,
]
type SlackSocketSleep = Callable[[float], Awaitable[object]]
type SlackSocketClock = Callable[[], datetime.datetime]


class SlackSocketSDKTransport(Protocol):
    """Public SDK Socket Mode transport surface used by the runner."""

    async def connect(self) -> None:
        """Connect the configured SDK transport."""
        ...

    async def close(self) -> None:
        """Close the configured SDK transport."""
        ...

    async def send_socket_mode_response(
        self,
        response: SocketModeResponse,
    ) -> None:
        """Send one SDK Socket Mode acknowledgement."""
        ...

    async def is_connected(self) -> bool:
        """Return whether the SDK transport is currently healthy."""
        ...


class SlackSocketSDKTransportFactory(Protocol):
    """Construct one SDK Socket Mode transport with explicit listeners."""

    def __call__(
        self,
        *,
        app_token: str,
        web_client: AsyncWebClient,
        endpoint_url: str,
        ping_interval: float,
        on_message: Callable[[aiohttp.WSMessage], Awaitable[None]],
        on_error: Callable[[aiohttp.WSMessage], Awaitable[None]],
        on_close: Callable[[aiohttp.WSMessage], Awaitable[None]],
    ) -> SlackSocketSDKTransport:
        """Create one non-reconnecting SDK transport."""
        ...


def _utc_now() -> datetime.datetime:
    """Return the current timezone-aware timestamp for durable event admission."""
    return datetime.datetime.now(datetime.UTC)


class SlackSocketWebAPIClient:
    """Open short-lived Slack Socket Mode endpoints with an app-level token."""

    def __init__(self, web_client: AsyncWebClient) -> None:
        self.web_client = web_client

    async def open_connection(
        self,
        *,
        app_token: str,
    ) -> SlackSocketConnectionOpen:
        """Request a Socket Mode endpoint without retaining the app token."""
        try:
            response = await self.web_client.apps_connections_open(
                app_token=app_token,
            )
        except SlackApiError as error:
            response = error.response
            payload = (
                response.data
                if isinstance(response, AsyncSlackResponse)
                and isinstance(response.data, dict)
                else {}
            )
            if isinstance(response, AsyncSlackResponse) and (
                response.status_code == 429 or response.status_code >= 500
            ):
                raise SlackSocketUnavailable(
                    "Slack Socket Mode endpoint is temporarily unavailable."
                ) from error
            if payload.get("error") in {
                "account_inactive",
                "invalid_auth",
                "not_authed",
                "token_revoked",
            }:
                raise SlackSocketReconnectRequired(
                    "Slack rejected the Socket Mode credentials."
                ) from error
            raise SlackSocketUnavailable(
                "Slack rejected the Socket Mode app token."
            ) from error
        except (aiohttp.ClientError, TimeoutError) as error:
            raise SlackSocketUnavailable(
                "Slack Socket Mode endpoint is temporarily unavailable."
            ) from error
        payload = response.data if isinstance(response.data, dict) else {}
        url = payload.get("url")
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


class SlackSocketModeRunner:
    """Complete Socket Mode callbacks before acknowledging their envelopes."""

    def __init__(
        self,
        *,
        web_client: AsyncWebClient,
        admit_event: SlackSocketEventAdmission,
        admit_interaction: SlackSocketInteractionAdmission | None = None,
        schedule_interaction: SlackSocketInteractionScheduler | None = None,
        transport_factory: SlackSocketSDKTransportFactory = (
            create_slack_socket_mode_client
        ),
        sleep: SlackSocketSleep = asyncio.sleep,
        clock: SlackSocketClock = _utc_now,
        ping_interval_seconds: float = DEFAULT_SLACK_SOCKET_PING_INTERVAL_SECONDS,
        ping_timeout_seconds: float = DEFAULT_SLACK_SOCKET_PING_TIMEOUT_SECONDS,
        connect_timeout_seconds: float = DEFAULT_SLACK_SOCKET_CONNECT_TIMEOUT_SECONDS,
    ) -> None:
        """Initialize one SDK-backed connection runner."""
        if ping_interval_seconds <= 0:
            raise ValueError("Slack Socket Mode ping interval must be positive.")
        if ping_timeout_seconds <= 0:
            raise ValueError("Slack Socket Mode ping timeout must be positive.")
        if connect_timeout_seconds <= 0:
            raise ValueError("Slack Socket Mode connect timeout must be positive.")
        self.web_client = web_client
        self.admit_event = admit_event
        self.admit_interaction = admit_interaction
        self.schedule_interaction = schedule_interaction
        self.transport_factory = transport_factory
        self.sleep = sleep
        self.clock = clock
        self.ping_interval_seconds = ping_interval_seconds
        self.ping_timeout_seconds = ping_timeout_seconds
        self.connect_timeout_seconds = connect_timeout_seconds

    async def run_connection(
        self,
        *,
        connection_id: str,
        app_token: str,
        endpoint_url: str,
    ) -> SlackSocketConnectionResult:
        """Process one SDK Socket Mode connection until Azents chooses reconnect."""
        loop = asyncio.get_running_loop()
        outcome: asyncio.Future[SlackSocketConnectionResult] = loop.create_future()
        admitted_event_count = 0
        transport: SlackSocketSDKTransport | None = None

        def finish(*, reconnect: bool, reason: str) -> None:
            if not outcome.done():
                outcome.set_result(
                    SlackSocketConnectionResult(
                        reconnect=reconnect,
                        reason=reason,
                        admitted_event_count=admitted_event_count,
                    )
                )

        async def on_message(message: aiohttp.WSMessage) -> None:
            nonlocal admitted_event_count
            if outcome.done() or message.type is not aiohttp.WSMsgType.TEXT:
                return
            raw_message = message.data
            if not isinstance(raw_message, str | bytes):
                if not outcome.done():
                    outcome.set_exception(
                        SlackSocketInvalidEnvelope(
                            "Slack Socket Mode message has an invalid data type."
                        )
                    )
                return
            try:
                envelope = parse_slack_socket_envelope(raw_message)
                if envelope.type == "hello":
                    return
                if envelope.type == "disconnect":
                    reason = _disconnect_reason(envelope.payload)
                    finish(
                        reconnect=reason != "link_disabled",
                        reason=reason,
                    )
                    return
                if envelope.type not in {"events_api", "interactive"}:
                    return
                admitted, interaction_handoff = await self._admit_envelope(
                    connection_id=connection_id,
                    envelope=envelope,
                )
                assert envelope.envelope_id is not None
                assert transport is not None
                await transport.send_socket_mode_response(
                    SocketModeResponse(envelope_id=envelope.envelope_id)
                )
                if interaction_handoff is not None:
                    if self.schedule_interaction is None:
                        raise SlackSocketInvalidEnvelope(
                            "Slack Socket interaction scheduling is unavailable."
                        )
                    self.schedule_interaction(interaction_handoff)
                if admitted:
                    admitted_event_count += 1
            except asyncio.CancelledError:
                raise
            except Exception as error:
                if not outcome.done():
                    outcome.set_exception(error)

        async def on_error(_: aiohttp.WSMessage) -> None:
            finish(reconnect=True, reason="connection_error")

        async def on_close(_: aiohttp.WSMessage) -> None:
            finish(reconnect=True, reason="connection_closed")

        sdk_ping_interval = min(
            self.ping_interval_seconds,
            self.ping_timeout_seconds / 4,
        )
        transport = self.transport_factory(
            app_token=app_token,
            web_client=self.web_client,
            endpoint_url=endpoint_url,
            ping_interval=sdk_ping_interval,
            on_message=on_message,
            on_error=on_error,
            on_close=on_close,
        )
        watchdog_task: asyncio.Task[None] | None = None
        try:
            try:
                await asyncio.wait_for(
                    transport.connect(),
                    timeout=self.connect_timeout_seconds,
                )
            except TimeoutError as error:
                raise SlackSocketUnavailable(
                    "Slack Socket Mode transport connection timed out."
                ) from error
            watchdog_task = asyncio.create_task(
                self._watch_transport(
                    transport=transport,
                    outcome=outcome,
                    admitted_event_count=lambda: admitted_event_count,
                )
            )
            return await outcome
        except asyncio.CancelledError:
            raise
        finally:
            if watchdog_task is not None:
                watchdog_task.cancel()
                await asyncio.gather(watchdog_task, return_exceptions=True)
            await transport.close()

    async def _watch_transport(
        self,
        *,
        transport: SlackSocketSDKTransport,
        outcome: asyncio.Future[SlackSocketConnectionResult],
        admitted_event_count: Callable[[], int],
    ) -> None:
        """Surface closed or stale SDK sessions to the Azents lifecycle owner."""
        check_interval = min(
            self.ping_interval_seconds,
            self.ping_timeout_seconds,
        )
        while not outcome.done():
            await self.sleep(check_interval)
            if await transport.is_connected():
                continue
            if not outcome.done():
                outcome.set_result(
                    SlackSocketConnectionResult(
                        reconnect=True,
                        reason="connection_inactive",
                        admitted_event_count=admitted_event_count(),
                    )
                )
            return

    async def _admit_envelope(
        self,
        *,
        connection_id: str,
        envelope: SlackSocketEnvelope,
    ) -> tuple[bool, ExternalChannelInteractionHandoff | None]:
        """Durably admit one Slack envelope before acknowledgement."""
        if envelope.envelope_id is None:
            raise SlackSocketInvalidEnvelope(
                "Slack Socket envelope is missing its envelope identifier."
            )
        if envelope.payload is None:
            raise SlackSocketInvalidEnvelope(
                "Slack Socket envelope is missing its payload."
            )
        raw_payload = json.dumps(envelope.payload, separators=(",", ":")).encode()
        try:
            if envelope.type == "events_api":
                callback = parse_slack_callback(
                    connection_id=connection_id,
                    raw_body=raw_payload,
                    received_at=self.clock(),
                )
            else:
                callback = parse_slack_interaction_payload(
                    payload=envelope.payload,
                    provider_interaction_key=f"socket-{envelope.envelope_id}",
                    received_at=self.clock(),
                )
        except SlackHTTPInvalidPayload as error:
            raise SlackSocketInvalidEnvelope(
                "Slack Socket envelope payload is invalid."
            ) from error
        if isinstance(callback, SlackEventCallback):
            event = callback.event.model_copy(
                update={"transport_envelope_id": envelope.envelope_id}
            )
            await self.admit_event(event)
            return True, None
        if isinstance(callback, SlackInteractionCallback):
            if self.admit_interaction is None:
                raise SlackSocketInvalidEnvelope(
                    "Slack Socket interaction admission is unavailable."
                )
            shortcut_source_event = (
                project_slack_shortcut_source_event(
                    connection_id=connection_id,
                    payload=envelope.payload,
                    provider_interaction_key=callback.provider_interaction_key,
                    received_at=self.clock(),
                )
                if callback.interaction_type is ExternalChannelInteractionType.SHORTCUT
                else None
            )
            handoff = await self.admit_interaction(callback, shortcut_source_event)
            return True, handoff
        if dataclasses.is_dataclass(callback):
            raise SlackSocketInvalidEnvelope(
                "Slack Socket envelope callback type is unsupported."
            )
        raise AssertionError("Slack Socket callback parser is not exhaustive.")


def parse_slack_socket_envelope(message: str | bytes) -> SlackSocketEnvelope:
    """Parse one bounded SDK Socket Mode request or control message."""
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
    try:
        request = SocketModeRequest.from_dict(payload)
    except (TypeError, ValueError) as error:
        raise SlackSocketInvalidEnvelope(
            "Slack Socket Mode request is invalid."
        ) from error
    if request is not None:
        if (
            not isinstance(request.type, str)
            or not request.type
            or not isinstance(request.envelope_id, str)
            or not request.envelope_id
            or not isinstance(request.payload, dict)
        ):
            raise SlackSocketInvalidEnvelope("Slack Socket Mode request is invalid.")
        return SlackSocketEnvelope(
            envelope_id=request.envelope_id,
            type=request.type,
            payload=request.payload,
        )
    envelope_type = payload.get("type")
    if envelope_type not in {"hello", "disconnect"}:
        raise SlackSocketInvalidEnvelope(
            "Slack Socket Mode envelope type is unsupported."
        )
    envelope_payload = payload.get("payload")
    if envelope_payload is not None and not isinstance(envelope_payload, dict):
        raise SlackSocketInvalidEnvelope(
            "Slack Socket Mode envelope payload must be an object."
        )
    return SlackSocketEnvelope(
        envelope_id=None,
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
