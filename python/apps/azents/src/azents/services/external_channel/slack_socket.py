"""Slack Socket Mode primitives for synchronous External Channel handoff."""

import asyncio
import dataclasses
import datetime
import json
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Literal, Protocol

import aiohttp
from slack_sdk.socket_mode.request import SocketModeRequest
from slack_sdk.socket_mode.response import SocketModeResponse
from slack_sdk.web.async_client import AsyncWebClient

from azents.core.external_channel_projection import is_external_channel_projection
from azents.repos.external_channel.data import ExternalChannelTrigger
from azents.services.external_channel.interaction import (
    ExternalChannelInteractionHandoff,
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


type SlackSocketEventAdmission = Callable[[ExternalChannelTrigger], Awaitable[object]]
type SlackSocketInteractionAdmission = Callable[
    [
        SlackInteractionCallback,
        ExternalChannelTrigger | None,
    ],
    Awaitable[ExternalChannelInteractionHandoff | None],
]
type SlackSocketInteractionScheduler = Callable[
    [ExternalChannelInteractionHandoff],
    None,
]
type SlackSocketActiveReporter = Callable[[], Awaitable[object]]
type SlackSocketGapReporter = Callable[[str], Awaitable[object]]
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


class SlackSocketSDKTransportFactory(Protocol):
    """Construct one SDK Socket Mode transport with explicit listeners."""

    def __call__(
        self,
        *,
        app_token: str,
        web_client: AsyncWebClient,
        ping_interval: float,
        on_message: Callable[[aiohttp.WSMessage], Awaitable[None]],
        on_active: Callable[[], Awaitable[None]],
        on_gap: Callable[[str], Awaitable[None]],
        on_failure: Callable[[str, bool], Awaitable[None]],
    ) -> SlackSocketSDKTransport:
        """Create one automatically reconnecting observed SDK transport."""
        ...


def _utc_now() -> datetime.datetime:
    """Return the current timezone-aware timestamp for durable event admission."""
    return datetime.datetime.now(datetime.UTC)


class SlackSocketModeRunner:
    """Complete Socket Mode callbacks before acknowledging their envelopes."""

    def __init__(
        self,
        *,
        web_client: AsyncWebClient,
        admit_event: SlackSocketEventAdmission,
        admit_interaction: SlackSocketInteractionAdmission | None = None,
        schedule_interaction: SlackSocketInteractionScheduler | None = None,
        report_active: SlackSocketActiveReporter,
        report_gap: SlackSocketGapReporter,
        transport_factory: SlackSocketSDKTransportFactory = (
            create_slack_socket_mode_client
        ),
        clock: SlackSocketClock = _utc_now,
        ping_interval_seconds: float = DEFAULT_SLACK_SOCKET_PING_INTERVAL_SECONDS,
    ) -> None:
        """Initialize one SDK-backed connection runner."""
        if ping_interval_seconds <= 0:
            raise ValueError("Slack Socket Mode ping interval must be positive.")
        self.web_client = web_client
        self.admit_event = admit_event
        self.admit_interaction = admit_interaction
        self.schedule_interaction = schedule_interaction
        self.report_active = report_active
        self.report_gap = report_gap
        self.transport_factory = transport_factory
        self.clock = clock
        self.ping_interval_seconds = ping_interval_seconds

    async def run_connection(
        self,
        *,
        connection_id: str,
        app_token: str,
    ) -> SlackSocketConnectionResult:
        """Process Socket callbacks while the SDK owns recoverable reconnect."""
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
                    if reason == "link_disabled":
                        finish(reconnect=False, reason=reason)
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

        async def on_active() -> None:
            try:
                await self.report_active()
            except asyncio.CancelledError:
                raise
            except Exception as error:
                if not outcome.done():
                    outcome.set_exception(error)

        async def on_gap(reason: str) -> None:
            try:
                await self.report_gap(reason)
            except asyncio.CancelledError:
                raise
            except Exception as error:
                if not outcome.done():
                    outcome.set_exception(error)

        async def on_failure(reason: str, reconnect_required: bool) -> None:
            if reconnect_required:
                finish(reconnect=False, reason=reason)
                return
            try:
                await self.report_gap(reason)
            except asyncio.CancelledError:
                raise
            except Exception as error:
                if not outcome.done():
                    outcome.set_exception(error)

        transport = self.transport_factory(
            app_token=app_token,
            web_client=self.web_client,
            ping_interval=self.ping_interval_seconds,
            on_message=on_message,
            on_active=on_active,
            on_gap=on_gap,
            on_failure=on_failure,
        )
        connect_task: asyncio.Task[None] | None = None
        try:
            await self.report_gap("socket_connecting")
            connect_task = asyncio.create_task(transport.connect())
            await asyncio.wait(
                (connect_task, outcome),
                return_when=asyncio.FIRST_COMPLETED,
            )
            if outcome.done():
                return outcome.result()
            connect_task.result()
            return await outcome
        except asyncio.CancelledError:
            raise
        finally:
            if connect_task is not None and not connect_task.done():
                connect_task.cancel()
                await asyncio.gather(connect_task, return_exceptions=True)
            await transport.close()

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
                if callback.handler == "selector_open"
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
    if not is_external_channel_projection(payload):
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
            or not is_external_channel_projection(request.payload)
        ):
            raise SlackSocketInvalidEnvelope("Slack Socket Mode request is invalid.")
        return SlackSocketEnvelope(
            envelope_id=request.envelope_id,
            type=request.type,
            payload=request.payload,
        )
    envelope_type = payload.get("type")
    validated_type: Literal["hello", "disconnect"]
    if envelope_type == "hello":
        validated_type = "hello"
    elif envelope_type == "disconnect":
        validated_type = "disconnect"
    else:
        raise SlackSocketInvalidEnvelope(
            "Slack Socket Mode envelope type is unsupported."
        )
    envelope_payload = payload.get("payload")
    validated_payload = (
        envelope_payload if is_external_channel_projection(envelope_payload) else None
    )
    if envelope_payload is not None and validated_payload is None:
        raise SlackSocketInvalidEnvelope(
            "Slack Socket Mode envelope payload must be an object."
        )
    return SlackSocketEnvelope(
        envelope_id=None,
        type=validated_type,
        payload=validated_payload,
    )


def _disconnect_reason(payload: dict[str, object] | None) -> str:
    """Normalize Slack's reconnect control-message reason."""
    if payload is None:
        return "disconnect_requested"
    reason = payload.get("reason")
    if not isinstance(reason, str) or not reason:
        return "disconnect_requested"
    return reason
