"""Slack Socket Mode admission and SDK lifecycle tests."""

import asyncio
import datetime
import json
from collections.abc import Awaitable, Callable

import aiohttp
import pytest
from slack_sdk.socket_mode.response import SocketModeResponse
from slack_sdk.web.async_client import AsyncWebClient

from azents.repos.external_channel.data import ExternalChannelTrigger
from azents.services.external_channel.interaction import (
    ExternalChannelInteractionHandoff,
)
from azents.services.external_channel.slack_http import SlackInteractionCallback
from azents.services.external_channel.slack_socket import (
    MAX_SLACK_SOCKET_MESSAGE_BYTES,
    SlackSocketInvalidEnvelope,
    SlackSocketModeRunner,
    parse_slack_socket_envelope,
)

_NOW = datetime.datetime(2026, 7, 22, 1, 0, tzinfo=datetime.UTC)


class FakeSocket:
    """In-memory SDK transport that owns recoverable reconnect simulation."""

    def __init__(self, messages: list[str | bytes | BaseException]) -> None:
        self.messages = messages
        self.sent: list[str] = []
        self.closed = False
        self.on_message: Callable[[aiohttp.WSMessage], Awaitable[None]] | None = None
        self.on_active: Callable[[], Awaitable[None]] | None = None
        self.on_gap: Callable[[str], Awaitable[None]] | None = None
        self.on_failure: Callable[[str, bool], Awaitable[None]] | None = None

    def configure(
        self,
        *,
        on_message: Callable[[aiohttp.WSMessage], Awaitable[None]],
        on_active: Callable[[], Awaitable[None]],
        on_gap: Callable[[str], Awaitable[None]],
        on_failure: Callable[[str, bool], Awaitable[None]],
    ) -> None:
        self.on_message = on_message
        self.on_active = on_active
        self.on_gap = on_gap
        self.on_failure = on_failure

    async def connect(self) -> None:
        """Establish one SDK session and keep recoverable transitions internal."""
        assert self.on_message is not None
        assert self.on_active is not None
        assert self.on_gap is not None
        await self.on_active()
        while self.messages:
            message = self.messages.pop(0)
            if isinstance(message, ConnectionError):
                await self.on_gap("socket_reconnecting")
                await self.on_active()
                continue
            if isinstance(message, BaseException):
                raise message
            await self.on_message(
                aiohttp.WSMessage(aiohttp.WSMsgType.TEXT, message, None)
            )
            payload = json.loads(message)
            if (
                isinstance(payload, dict)
                and payload.get("type") == "disconnect"
                and payload.get("payload") != {"reason": "link_disabled"}
            ):
                await self.on_gap("socket_reconnecting")
                await self.on_active()

    async def close(self) -> None:
        self.closed = True

    async def send_socket_mode_response(
        self,
        response: SocketModeResponse,
    ) -> None:
        """Record one SDK acknowledgement."""
        self.sent.append(json.dumps(response.to_dict(), separators=(",", ":")))


def _events_api_envelope(
    *,
    envelope_id: str = "envelope-1",
    event_id: str = "Ev-1",
) -> str:
    return json.dumps(
        {
            "envelope_id": envelope_id,
            "type": "events_api",
            "payload": {
                "type": "event_callback",
                "event_id": event_id,
                "event_time": int(_NOW.timestamp()),
                "api_app_id": "A-1",
                "team_id": "T-1",
                "event": {
                    "type": "app_mention",
                    "channel": "C-1",
                    "ts": "100.0001",
                    "text": "Investigate this",
                },
            },
        }
    )


def _interactive_envelope(*, envelope_id: str = "interactive-envelope-1") -> str:
    """Build one Socket Mode interaction envelope without persisted secrets."""
    return json.dumps(
        {
            "envelope_id": envelope_id,
            "type": "interactive",
            "payload": {
                "type": "message_action",
                "api_app_id": "A-1",
                "team": {"id": "T-1"},
                "user": {"id": "U-1"},
                "trigger_id": "trigger-secret-must-not-persist",
                "response_url": "https://hooks.slack.com/actions/private",
                "callback_id": "ask-agent",
                "channel": {"id": "C-1"},
                "message": {
                    "ts": "100.0001",
                    "thread_ts": "100.0001",
                    "text": "private text",
                },
            },
        }
    )


def _terminal_disconnect() -> str:
    return json.dumps(
        {
            "type": "disconnect",
            "payload": {"reason": "link_disabled"},
        }
    )


def _client(
    *,
    socket: FakeSocket,
    admitted: list[ExternalChannelTrigger],
    admit: Callable[[ExternalChannelTrigger], Awaitable[object]] | None = None,
    admitted_interactions: list[SlackInteractionCallback] | None = None,
    admitted_shortcut_sources: list[ExternalChannelTrigger] | None = None,
    admit_interaction: Callable[
        [
            SlackInteractionCallback,
            ExternalChannelTrigger | None,
        ],
        Awaitable[ExternalChannelInteractionHandoff | None],
    ]
    | None = None,
    schedule_interaction: Callable[[ExternalChannelInteractionHandoff], None]
    | None = None,
    active_reports: list[str] | None = None,
    gap_reports: list[str] | None = None,
) -> SlackSocketModeRunner:
    async def default_admit(event: ExternalChannelTrigger) -> None:
        admitted.append(event)

    async def default_admit_interaction(
        callback: SlackInteractionCallback,
        shortcut_source_event: ExternalChannelTrigger | None,
    ) -> ExternalChannelInteractionHandoff | None:
        if admitted_interactions is not None:
            admitted_interactions.append(callback)
        if shortcut_source_event is not None and admitted_shortcut_sources is not None:
            admitted_shortcut_sources.append(shortcut_source_event)
        return None

    async def report_active() -> None:
        if active_reports is not None:
            active_reports.append("active")

    async def report_gap(reason: str) -> None:
        if gap_reports is not None:
            gap_reports.append(reason)

    def transport_factory(
        *,
        app_token: str,
        web_client: AsyncWebClient,
        ping_interval: float,
        on_message: Callable[[aiohttp.WSMessage], Awaitable[None]],
        on_active: Callable[[], Awaitable[None]],
        on_gap: Callable[[str], Awaitable[None]],
        on_failure: Callable[[str, bool], Awaitable[None]],
    ) -> FakeSocket:
        assert app_token == "xapp-secret"
        assert isinstance(web_client, AsyncWebClient)
        assert ping_interval == 11.0
        socket.configure(
            on_message=on_message,
            on_active=on_active,
            on_gap=on_gap,
            on_failure=on_failure,
        )
        return socket

    return SlackSocketModeRunner(
        web_client=AsyncWebClient(retry_handlers=[]),
        admit_event=admit if admit is not None else default_admit,
        admit_interaction=(
            admit_interaction
            if admit_interaction is not None
            else default_admit_interaction
            if admitted_interactions is not None
            else None
        ),
        schedule_interaction=schedule_interaction,
        report_active=report_active,
        report_gap=report_gap,
        transport_factory=transport_factory,
        clock=lambda: _NOW,
        ping_interval_seconds=11.0,
    )


def test_parse_socket_envelope_rejects_invalid_payload_shape() -> None:
    """Reject envelope payloads that cannot be normalized into Slack events."""
    with pytest.raises(SlackSocketInvalidEnvelope):
        parse_slack_socket_envelope(
            json.dumps({"envelope_id": "E-1", "type": "events_api", "payload": []})
        )


def test_parse_socket_envelope_bounds_message_size() -> None:
    """Bound Socket Mode messages before JSON parsing."""
    with pytest.raises(SlackSocketInvalidEnvelope):
        parse_slack_socket_envelope(b"x" * (MAX_SLACK_SOCKET_MESSAGE_BYTES + 1))


@pytest.mark.asyncio
async def test_events_api_acknowledges_only_after_durable_admission() -> None:
    """Use the transport envelope ID only after the durable callback succeeds."""
    socket = FakeSocket(
        [json.dumps({"type": "hello"}), _events_api_envelope(), _terminal_disconnect()]
    )
    admitted: list[ExternalChannelTrigger] = []
    active_reports: list[str] = []
    gap_reports: list[str] = []
    client = _client(
        socket=socket,
        admitted=admitted,
        active_reports=active_reports,
        gap_reports=gap_reports,
    )

    result = await client.run_connection(
        connection_id="connection-1",
        app_token="xapp-secret",
    )

    assert result.reconnect is False
    assert result.reason == "link_disabled"
    assert result.admitted_event_count == 1
    assert admitted[0].provider_event_id == "Ev-1"
    assert admitted[0].transport_envelope_id == "envelope-1"
    assert socket.sent == ['{"envelope_id":"envelope-1"}']
    assert socket.closed is True
    assert gap_reports == ["socket_connecting"]
    assert active_reports == ["active"]


@pytest.mark.asyncio
async def test_events_api_uses_safe_bounded_file_projection() -> None:
    """Socket Mode stores the same URL-free file projection as HTTP admission."""
    envelope = json.loads(_events_api_envelope())
    event = envelope["payload"]["event"]
    event["files"] = [
        {
            "id": "F1",
            "name": "report.csv",
            "mimetype": "text/csv",
            "size": 42,
            "mode": "hosted",
            "url_private": "https://files.slack.test/private/F1",
            "body": "must not survive",
        }
    ]
    socket = FakeSocket([json.dumps(envelope), _terminal_disconnect()])
    admitted: list[ExternalChannelTrigger] = []
    client = _client(socket=socket, admitted=admitted)

    result = await client.run_connection(
        connection_id="connection-1",
        app_token="xapp-secret",
    )

    assert result.admitted_event_count == 1
    projected_event = admitted[0].envelope["event"]
    assert isinstance(projected_event, dict)
    assert projected_event["files"] == [
        {
            "id": "F1",
            "name": "report.csv",
            "mimetype": "text/csv",
            "mode": "hosted",
            "size": 42,
        }
    ]
    assert "url_private" not in repr(projected_event)
    assert "must not survive" not in repr(projected_event)


@pytest.mark.asyncio
async def test_events_api_does_not_acknowledge_failed_admission() -> None:
    """Leave an envelope unacknowledged when its durable transaction fails."""
    socket = FakeSocket([_events_api_envelope()])

    async def rejected_admission(event: ExternalChannelTrigger) -> None:
        del event
        raise RuntimeError("transaction failed")

    client = _client(socket=socket, admitted=[], admit=rejected_admission)

    with pytest.raises(RuntimeError, match="transaction failed"):
        await client.run_connection(
            connection_id="connection-1",
            app_token="xapp-secret",
        )

    assert socket.sent == []
    assert socket.closed is True


@pytest.mark.asyncio
async def test_interactive_envelope_acknowledges_only_after_durable_admission() -> None:
    """A Socket interaction uses its envelope ID as the durable retry key."""
    socket = FakeSocket([_interactive_envelope(), _terminal_disconnect()])
    interactions: list[SlackInteractionCallback] = []
    shortcut_sources: list[ExternalChannelTrigger] = []
    client = _client(
        socket=socket,
        admitted=[],
        admitted_interactions=interactions,
        admitted_shortcut_sources=shortcut_sources,
    )

    result = await client.run_connection(
        connection_id="connection-1",
        app_token="xapp-secret",
    )

    assert result.admitted_event_count == 1
    assert len(interactions) == 1
    interaction = interactions[0]
    assert interaction.provider_interaction_key == "socket-interactive-envelope-1"
    assert interaction.resource_correlation_key == "C-1:100.0001"
    assert "trigger-secret" not in repr(interaction)
    assert "hooks.slack.com" not in repr(interaction)
    assert len(shortcut_sources) == 1
    assert socket.sent == ['{"envelope_id":"interactive-envelope-1"}']


@pytest.mark.asyncio
async def test_interactive_envelope_does_not_acknowledge_failed_admission() -> None:
    """Leave an interaction envelope unacknowledged when its transaction fails."""
    socket = FakeSocket([_interactive_envelope()])

    async def rejected_interaction(
        _: SlackInteractionCallback,
        __: ExternalChannelTrigger | None,
    ) -> None:
        raise RuntimeError("transaction failed")

    client = _client(
        socket=socket,
        admitted=[],
        admit_interaction=rejected_interaction,
    )

    with pytest.raises(RuntimeError, match="transaction failed"):
        await client.run_connection(
            connection_id="connection-1",
            app_token="xapp-secret",
        )

    assert socket.sent == []


@pytest.mark.asyncio
async def test_interactive_handoff_is_scheduled_only_after_socket_ack() -> None:
    """Provider work starts only after the durable claim and exact ACK."""
    socket = FakeSocket([_interactive_envelope(), _terminal_disconnect()])
    scheduled: list[ExternalChannelInteractionHandoff] = []

    async def admit_interaction(
        callback: SlackInteractionCallback,
        shortcut_source_event: ExternalChannelTrigger | None,
    ) -> ExternalChannelInteractionHandoff:
        assert callback.trigger_id == "trigger-secret-must-not-persist"
        assert shortcut_source_event is not None
        return ExternalChannelInteractionHandoff(
            interaction_id="interaction-1",
            trigger_id=callback.trigger_id,
        )

    def schedule(handoff: ExternalChannelInteractionHandoff) -> None:
        assert socket.sent == ['{"envelope_id":"interactive-envelope-1"}']
        scheduled.append(handoff)

    client = _client(
        socket=socket,
        admitted=[],
        admit_interaction=admit_interaction,
        schedule_interaction=schedule,
    )

    await client.run_connection(
        connection_id="connection-1",
        app_token="xapp-secret",
    )

    assert len(scheduled) == 1
    assert "trigger-secret" not in repr(scheduled[0])


@pytest.mark.asyncio
async def test_recoverable_disconnect_stays_inside_sdk_lifecycle() -> None:
    """Refresh and network close recover without completing the Azents runner."""
    socket = FakeSocket(
        [
            json.dumps(
                {"type": "disconnect", "payload": {"reason": "refresh_requested"}}
            ),
            ConnectionError("closed"),
            _events_api_envelope(),
            _terminal_disconnect(),
        ]
    )
    admitted: list[ExternalChannelTrigger] = []
    active_reports: list[str] = []
    gap_reports: list[str] = []
    client = _client(
        socket=socket,
        admitted=admitted,
        active_reports=active_reports,
        gap_reports=gap_reports,
    )

    result = await client.run_connection(
        connection_id="connection-1",
        app_token="xapp-secret",
    )

    assert result.reconnect is False
    assert result.admitted_event_count == 1
    assert gap_reports == [
        "socket_connecting",
        "socket_reconnecting",
        "socket_reconnecting",
    ]
    assert active_reports == ["active", "active", "active"]


@pytest.mark.asyncio
async def test_recoverable_endpoint_failure_stays_inside_sdk_lifecycle() -> None:
    """A transient endpoint failure degrades health without completing the runner."""
    socket = FakeSocket([_events_api_envelope(), _terminal_disconnect()])
    admitted: list[ExternalChannelTrigger] = []
    gap_reports: list[str] = []
    client = _client(
        socket=socket,
        admitted=admitted,
        gap_reports=gap_reports,
    )

    task = asyncio.create_task(
        client.run_connection(
            connection_id="connection-1",
            app_token="xapp-secret",
        )
    )
    await asyncio.sleep(0)
    assert socket.on_failure is not None
    await socket.on_failure("socket_endpoint_unavailable", False)

    result = await task

    assert result.reconnect is False
    assert result.reason == "link_disabled"
    assert result.admitted_event_count == 1
    assert gap_reports == [
        "socket_connecting",
        "socket_endpoint_unavailable",
    ]


@pytest.mark.asyncio
async def test_terminal_endpoint_failure_completes_sdk_lifecycle() -> None:
    """A terminal credential failure stops SDK retries for durable health handling."""
    socket = FakeSocket([])
    client = _client(socket=socket, admitted=[])

    task = asyncio.create_task(
        client.run_connection(
            connection_id="connection-1",
            app_token="xapp-secret",
        )
    )
    await asyncio.sleep(0)
    assert socket.on_failure is not None
    await socket.on_failure("socket_credentials_rejected", True)

    result = await task

    assert result.reconnect is False
    assert result.reason == "socket_credentials_rejected"
    assert result.admitted_event_count == 0
    assert socket.closed is True


@pytest.mark.asyncio
async def test_cancellation_closes_sdk_transport() -> None:
    blocking = FakeSocket([])
    client = _client(socket=blocking, admitted=[])
    task = asyncio.create_task(
        client.run_connection(
            connection_id="connection-1",
            app_token="xapp-secret",
        )
    )
    await asyncio.sleep(0)
    task.cancel()

    with pytest.raises(asyncio.CancelledError):
        await task

    assert blocking.closed is True
