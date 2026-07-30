"""Slack Socket Mode admission and connection-loop tests."""

import asyncio
import datetime
import json
from collections.abc import Awaitable, Callable
from typing import Any

import aiohttp
import httpx
import pytest
from slack_sdk.socket_mode.response import SocketModeResponse
from slack_sdk.web.async_client import AsyncWebClient
from slack_sdk.web.async_slack_response import AsyncSlackResponse

from azents.repos.external_channel.data import ExternalChannelTrigger
from azents.services.external_channel.interaction import (
    ExternalChannelInteractionHandoff,
)
from azents.services.external_channel.slack_endpoint import slack_api_base_url
from azents.services.external_channel.slack_http import SlackInteractionCallback
from azents.services.external_channel.slack_socket import (
    MAX_SLACK_SOCKET_MESSAGE_BYTES,
    SlackSocketInvalidEnvelope,
    SlackSocketModeRunner,
    SlackSocketReconnectRequired,
    SlackSocketUnavailable,
    SlackSocketWebAPIClient,
    parse_slack_socket_envelope,
)

_NOW = datetime.datetime(2026, 7, 22, 1, 0, tzinfo=datetime.UTC)


class FakeSocket:
    """In-memory SDK Socket Mode transport with explicit listener events."""

    def __init__(self, messages: list[str | bytes | BaseException]) -> None:
        self.messages = messages
        self.sent: list[str] = []
        self.closed = False
        self.connected = False
        self.on_message: Callable[[aiohttp.WSMessage], Awaitable[None]] | None = None
        self.on_error: Callable[[aiohttp.WSMessage], Awaitable[None]] | None = None
        self.on_close: Callable[[aiohttp.WSMessage], Awaitable[None]] | None = None

    def configure(
        self,
        *,
        on_message: Callable[[aiohttp.WSMessage], Awaitable[None]],
        on_error: Callable[[aiohttp.WSMessage], Awaitable[None]],
        on_close: Callable[[aiohttp.WSMessage], Awaitable[None]],
    ) -> None:
        """Bind the listeners supplied to the SDK transport factory."""
        self.on_message = on_message
        self.on_error = on_error
        self.on_close = on_close

    async def connect(self) -> None:
        """Emit configured SDK transport messages after connecting."""
        self.connected = True
        assert self.on_message is not None
        assert self.on_error is not None
        assert self.on_close is not None
        while self.messages:
            message = self.messages.pop(0)
            if isinstance(message, ConnectionError):
                self.connected = False
                await self.on_close(
                    aiohttp.WSMessage(aiohttp.WSMsgType.CLOSE, None, None)
                )
                return
            if isinstance(message, BaseException):
                self.connected = False
                await self.on_error(
                    aiohttp.WSMessage(aiohttp.WSMsgType.ERROR, message, None)
                )
                return
            await self.on_message(
                aiohttp.WSMessage(aiohttp.WSMsgType.TEXT, message, None)
            )

    async def close(self) -> None:
        self.closed = True
        self.connected = False

    async def send_socket_mode_response(
        self,
        response: SocketModeResponse,
    ) -> None:
        """Record one SDK acknowledgement."""
        self.sent.append(json.dumps(response.to_dict(), separators=(",", ":")))

    async def is_connected(self) -> bool:
        return self.connected and not self.closed


class _MockSlackSocketWebClient(AsyncWebClient):
    """Route the public endpoint-open SDK call through deterministic HTTPX."""

    def __init__(self, http_client: httpx.AsyncClient) -> None:
        super().__init__(retry_handlers=[])
        self.http_client = http_client

    async def api_call(
        self,
        api_method: str,
        *,
        http_verb: str = "POST",
        files: dict[str, Any] | None = None,
        data: dict[str, Any] | aiohttp.FormData | None = None,
        params: dict[str, Any] | None = None,
        json: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
        auth: dict[str, str] | None = None,
    ) -> AsyncSlackResponse:
        del files, auth
        request_headers = dict(headers or {})
        request_params = dict(params or {})
        request_data = dict(data) if isinstance(data, dict) else {}
        token = request_params.pop("token", None)
        if token is None:
            token = request_data.pop("token", None)
        if isinstance(token, str):
            request_headers["Authorization"] = f"Bearer {token}"
        response = await self.http_client.request(
            http_verb,
            f"{slack_api_base_url()}/{api_method}",
            params=request_params or None,
            json=json,
            data=request_data or None,
            headers=request_headers,
        )
        payload: object = response.json()
        return AsyncSlackResponse(
            client=self,
            http_verb=http_verb,
            api_url=str(response.request.url),
            req_args={},
            data=payload if isinstance(payload, dict) else {},
            headers=dict(response.headers),
            status_code=response.status_code,
        ).validate()


def _socket_web_api_client(
    http_client: httpx.AsyncClient,
) -> SlackSocketWebAPIClient:
    return SlackSocketWebAPIClient(_MockSlackSocketWebClient(http_client))


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

    def transport_factory(
        *,
        app_token: str,
        web_client: AsyncWebClient,
        endpoint_url: str,
        ping_interval: float,
        on_message: Callable[[aiohttp.WSMessage], Awaitable[None]],
        on_error: Callable[[aiohttp.WSMessage], Awaitable[None]],
        on_close: Callable[[aiohttp.WSMessage], Awaitable[None]],
    ) -> FakeSocket:
        assert app_token == "xapp-secret"
        assert isinstance(web_client, AsyncWebClient)
        assert endpoint_url == "wss://socket.example.test/connection"
        assert ping_interval == 3.0
        socket.configure(
            on_message=on_message,
            on_error=on_error,
            on_close=on_close,
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
        transport_factory=transport_factory,
        clock=lambda: _NOW,
        ping_interval_seconds=11.0,
        ping_timeout_seconds=12.0,
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
async def test_open_connection_uses_app_token_without_returning_it() -> None:
    """Open one endpoint with the app token and expose only the endpoint."""

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/apps.connections.open"
        assert request.headers["Authorization"] == "Bearer xapp-secret"
        return httpx.Response(
            200,
            json={"ok": True, "url": "wss://socket.example.test/connection"},
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http_client:
        opened = await _socket_web_api_client(http_client).open_connection(
            app_token="xapp-secret"
        )

    assert opened.url == "wss://socket.example.test/connection"
    assert "xapp-secret" not in repr(opened)


@pytest.mark.asyncio
async def test_open_connection_maps_rejected_token_to_sanitized_failure() -> None:
    """Do not return Slack's token-specific response details to the caller."""

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(
            lambda request: httpx.Response(
                200,
                json={"ok": False, "error": "invalid_auth"},
            )
        )
    ) as http_client:
        with pytest.raises(SlackSocketReconnectRequired) as error:
            await _socket_web_api_client(http_client).open_connection(
                app_token="xapp-secret"
            )

    assert "xapp-secret" not in str(error.value)


@pytest.mark.asyncio
async def test_open_connection_allows_insecure_testenv_socket_only_when_enabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Keep insecure WebSockets restricted to the explicit deterministic boundary."""

    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={"ok": True, "url": "ws://slack-fake:8084/socket"},
        )

    monkeypatch.delenv("AZ_TESTENV_SLACK_API_BASE_URL", raising=False)
    monkeypatch.delenv(
        "AZ_TESTENV_SLACK_ALLOW_INSECURE_WEBSOCKET",
        raising=False,
    )
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http_client:
        with pytest.raises(
            SlackSocketUnavailable,
            match="endpoint response is invalid",
        ):
            await _socket_web_api_client(http_client).open_connection(
                app_token="xapp-secret"
            )

    monkeypatch.setenv(
        "AZ_TESTENV_SLACK_ALLOW_INSECURE_WEBSOCKET",
        "true",
    )
    monkeypatch.setenv(
        "AZ_TESTENV_SLACK_API_BASE_URL",
        "http://slack-fake:8083/api",
    )
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http_client:
        opened = await _socket_web_api_client(http_client).open_connection(
            app_token="xapp-secret"
        )

    assert opened.url == "ws://slack-fake:8084/socket"


@pytest.mark.asyncio
async def test_events_api_acknowledges_only_after_durable_admission() -> None:
    """Use the transport envelope ID only after the durable callback succeeds."""
    socket = FakeSocket(
        [
            json.dumps({"type": "hello"}),
            _events_api_envelope(),
            json.dumps(
                {
                    "type": "disconnect",
                    "payload": {"reason": "link_disabled"},
                }
            ),
        ]
    )
    admitted: list[ExternalChannelTrigger] = []
    client = _client(socket=socket, admitted=admitted)

    result = await client.run_connection(
        connection_id="connection-1",
        app_token="xapp-secret",
        endpoint_url="wss://socket.example.test/connection",
    )

    assert result.reconnect is False
    assert result.reason == "link_disabled"
    assert result.admitted_event_count == 1
    assert admitted[0].provider_event_id == "Ev-1"
    assert admitted[0].transport_envelope_id == "envelope-1"
    assert socket.sent == ['{"envelope_id":"envelope-1"}']
    assert socket.closed is True


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
    socket = FakeSocket(
        [
            json.dumps(envelope),
            json.dumps(
                {
                    "type": "disconnect",
                    "payload": {"reason": "link_disabled"},
                }
            ),
        ]
    )
    admitted: list[ExternalChannelTrigger] = []
    client = _client(socket=socket, admitted=admitted)

    result = await client.run_connection(
        connection_id="connection-1",
        app_token="xapp-secret",
        endpoint_url="wss://socket.example.test/connection",
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
    admitted: list[ExternalChannelTrigger] = []

    async def rejected_admission(event: ExternalChannelTrigger) -> None:
        del event
        raise RuntimeError("transaction failed")

    client = _client(socket=socket, admitted=admitted, admit=rejected_admission)

    with pytest.raises(RuntimeError, match="transaction failed"):
        await client.run_connection(
            connection_id="connection-1",
            app_token="xapp-secret",
            endpoint_url="wss://socket.example.test/connection",
        )

    assert socket.sent == []
    assert socket.closed is True


@pytest.mark.asyncio
async def test_interactive_envelope_acknowledges_only_after_durable_admission() -> None:
    """A Socket interaction uses its envelope ID as the durable retry key."""
    socket = FakeSocket(
        [
            _interactive_envelope(),
            json.dumps(
                {
                    "type": "disconnect",
                    "payload": {"reason": "link_disabled"},
                }
            ),
        ]
    )
    admitted: list[ExternalChannelTrigger] = []
    interactions: list[SlackInteractionCallback] = []
    shortcut_sources: list[ExternalChannelTrigger] = []
    client = _client(
        socket=socket,
        admitted=admitted,
        admitted_interactions=interactions,
        admitted_shortcut_sources=shortcut_sources,
    )

    result = await client.run_connection(
        connection_id="connection-1",
        app_token="xapp-secret",
        endpoint_url="wss://socket.example.test/connection",
    )

    assert result.admitted_event_count == 1
    assert admitted == []
    assert len(interactions) == 1
    interaction = interactions[0]
    assert interaction.provider_interaction_key == "socket-interactive-envelope-1"
    assert interaction.resource_correlation_key == "C-1:100.0001"
    assert "trigger-secret" not in repr(interaction)
    assert "hooks.slack.com" not in repr(interaction)
    assert len(shortcut_sources) == 1
    assert (
        shortcut_sources[0].provider_event_id
        == "shortcut-socket-interactive-envelope-1"
    )
    assert shortcut_sources[0].resource_correlation_key == "C-1:100.0001"
    assert socket.sent == ['{"envelope_id":"interactive-envelope-1"}']


@pytest.mark.asyncio
async def test_interactive_envelope_does_not_acknowledge_failed_admission() -> None:
    """Leave an interaction envelope unacknowledged when its transaction fails."""
    socket = FakeSocket([_interactive_envelope()])
    admitted: list[ExternalChannelTrigger] = []

    async def rejected_interaction(
        _: SlackInteractionCallback,
        __: ExternalChannelTrigger | None,
    ) -> None:
        raise RuntimeError("transaction failed")

    client = _client(
        socket=socket,
        admitted=admitted,
        admit_interaction=rejected_interaction,
    )

    with pytest.raises(RuntimeError, match="transaction failed"):
        await client.run_connection(
            connection_id="connection-1",
            app_token="xapp-secret",
            endpoint_url="wss://socket.example.test/connection",
        )

    assert socket.sent == []
    assert socket.closed is True


@pytest.mark.asyncio
async def test_interactive_handoff_is_scheduled_only_after_socket_ack() -> None:
    """Socket provider work starts only after the durable claim and exact ACK."""
    socket = FakeSocket(
        [
            _interactive_envelope(),
            json.dumps(
                {
                    "type": "disconnect",
                    "payload": {"reason": "link_disabled"},
                }
            ),
        ]
    )
    admitted: list[ExternalChannelTrigger] = []
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
        admitted=admitted,
        admit_interaction=admit_interaction,
        schedule_interaction=schedule,
    )

    result = await client.run_connection(
        connection_id="connection-1",
        app_token="xapp-secret",
        endpoint_url="wss://socket.example.test/connection",
    )

    assert result.admitted_event_count == 1
    assert scheduled == [
        ExternalChannelInteractionHandoff(
            interaction_id="interaction-1",
            trigger_id="trigger-secret-must-not-persist",
        )
    ]
    assert "trigger-secret" not in repr(scheduled[0])
    assert socket.sent == ['{"envelope_id":"interactive-envelope-1"}']


@pytest.mark.asyncio
async def test_refresh_disconnect_returns_reconnect_decision_to_owner() -> None:
    """Return refresh control to the Azents-owned reconnect loop."""
    socket = FakeSocket(
        [json.dumps({"type": "disconnect", "payload": {"reason": "refresh_requested"}})]
    )
    client = _client(socket=socket, admitted=[])
    result = await client.run_connection(
        connection_id="connection-1",
        app_token="xapp-secret",
        endpoint_url="wss://socket.example.test/connection",
    )

    assert result.reconnect is True
    assert result.reason == "refresh_requested"
    assert socket.closed is True


@pytest.mark.asyncio
async def test_connection_close_reconnects_and_cancellation_closes_socket() -> None:
    """Reconnect closed connections and close active sockets during cancellation."""
    socket = FakeSocket([ConnectionError("closed")])
    admitted: list[ExternalChannelTrigger] = []
    client = _client(socket=socket, admitted=admitted)

    result = await client.run_connection(
        connection_id="connection-1",
        app_token="xapp-secret",
        endpoint_url="wss://socket.example.test/connection",
    )

    assert result.reconnect is True
    assert result.reason == "connection_closed"
    assert socket.closed is True

    blocking = FakeSocket([])
    cancel_client = _client(socket=blocking, admitted=[])
    task = asyncio.create_task(
        cancel_client.run_connection(
            connection_id="connection-1",
            app_token="xapp-secret",
            endpoint_url="wss://socket.example.test/connection",
        )
    )
    await asyncio.sleep(0)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert blocking.closed is True
