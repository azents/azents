"""Slack Socket Mode admission and connection-loop tests."""

import asyncio
import datetime
import json
from collections.abc import Awaitable, Callable

import httpx
import pytest
from websockets.exceptions import ConnectionClosedError

from azents.repos.external_channel.data import ExternalChannelEventCreate
from azents.services.external_channel.slack_socket import (
    MAX_SLACK_SOCKET_MESSAGE_BYTES,
    SlackSocketConnectionOpen,
    SlackSocketInvalidEnvelope,
    SlackSocketModeClient,
    SlackSocketReconnectRequired,
    SlackSocketUnavailable,
    SlackSocketWebAPIClient,
    parse_slack_socket_envelope,
)

_NOW = datetime.datetime(2026, 7, 22, 1, 0, tzinfo=datetime.UTC)


class FakeSocket:
    """In-memory WebSocket with explicit receive messages and sent acknowledgements."""

    def __init__(self, messages: list[str | bytes | BaseException]) -> None:
        self.messages = messages
        self.sent: list[str] = []
        self.closed = False

    async def recv(self) -> str | bytes:
        next_message = self.messages.pop(0)
        if isinstance(next_message, BaseException):
            raise next_message
        return next_message

    async def send(self, message: str) -> None:
        self.sent.append(message)

    async def close(self) -> None:
        self.closed = True


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


def _client(
    *,
    socket: FakeSocket,
    admitted: list[ExternalChannelEventCreate],
    admit: Callable[[ExternalChannelEventCreate], Awaitable[object]] | None = None,
) -> SlackSocketModeClient:
    async def default_admit(event: ExternalChannelEventCreate) -> None:
        admitted.append(event)

    async def connector(
        endpoint_url: str,
        ping_interval_seconds: float,
        ping_timeout_seconds: float,
        max_size: int,
    ) -> FakeSocket:
        assert endpoint_url == "wss://socket.example.test/connection"
        assert ping_interval_seconds == 11.0
        assert ping_timeout_seconds == 12.0
        assert max_size == MAX_SLACK_SOCKET_MESSAGE_BYTES
        return socket

    return SlackSocketModeClient(
        web_api_client=SlackSocketWebAPIClient(httpx.AsyncClient()),
        admit_event=admit if admit is not None else default_admit,
        connector=connector,
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
        opened = await SlackSocketWebAPIClient(http_client).open_connection(
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
            await SlackSocketWebAPIClient(http_client).open_connection(
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
            await SlackSocketWebAPIClient(http_client).open_connection(
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
        opened = await SlackSocketWebAPIClient(http_client).open_connection(
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
    admitted: list[ExternalChannelEventCreate] = []
    client = _client(socket=socket, admitted=admitted)

    result = await client.run_connection(
        connection_id="connection-1",
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
    admitted: list[ExternalChannelEventCreate] = []
    client = _client(socket=socket, admitted=admitted)

    result = await client.run_connection(
        connection_id="connection-1",
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
    admitted: list[ExternalChannelEventCreate] = []

    async def rejected_admission(event: ExternalChannelEventCreate) -> None:
        del event
        raise RuntimeError("transaction failed")

    client = _client(socket=socket, admitted=admitted, admit=rejected_admission)

    with pytest.raises(RuntimeError, match="transaction failed"):
        await client.run_connection(
            connection_id="connection-1",
            endpoint_url="wss://socket.example.test/connection",
        )

    assert socket.sent == []
    assert socket.closed is True


@pytest.mark.asyncio
async def test_run_reopens_after_refresh_requested() -> None:
    """Refresh control messages reconnect with a newly minted Slack endpoint."""
    first_socket = FakeSocket(
        [json.dumps({"type": "disconnect", "payload": {"reason": "refresh_requested"}})]
    )
    second_socket = FakeSocket(
        [json.dumps({"type": "disconnect", "payload": {"reason": "link_disabled"}})]
    )
    sockets = [first_socket, second_socket]
    opened_count = 0
    sleeps: list[float] = []

    class FakeWebAPI:
        async def open_connection(
            self,
            *,
            app_token: str,
        ) -> SlackSocketConnectionOpen:
            nonlocal opened_count
            assert app_token == "xapp-secret"
            opened_count += 1
            return SlackSocketConnectionOpen(
                url="wss://socket.example.test/connection",
            )

    async def connector(
        endpoint_url: str,
        ping_interval_seconds: float,
        ping_timeout_seconds: float,
        max_size: int,
    ) -> FakeSocket:
        del endpoint_url, ping_interval_seconds, ping_timeout_seconds, max_size
        return sockets.pop(0)

    async def admit(event: ExternalChannelEventCreate) -> None:
        del event

    async def sleep(delay: float) -> None:
        sleeps.append(delay)

    client = SlackSocketModeClient(
        web_api_client=FakeWebAPI(),
        admit_event=admit,
        connector=connector,
        sleep=sleep,
        reconnect_delay_seconds=0.5,
    )

    result = await client.run(connection_id="connection-1", app_token="xapp-secret")

    assert opened_count == 2
    assert sleeps == [0.5]
    assert result.reason == "link_disabled"
    assert first_socket.closed is True
    assert second_socket.closed is True


@pytest.mark.asyncio
async def test_connection_close_reconnects_and_cancellation_closes_socket() -> None:
    """Reconnect closed connections and close active sockets during cancellation."""
    socket = FakeSocket([ConnectionClosedError(None, None)])
    admitted: list[ExternalChannelEventCreate] = []
    client = _client(socket=socket, admitted=admitted)

    result = await client.run_connection(
        connection_id="connection-1",
        endpoint_url="wss://socket.example.test/connection",
    )

    assert result.reconnect is True
    assert result.reason == "connection_closed"
    assert socket.closed is True

    blocking_socket = FakeSocket([])

    class BlockingSocket(FakeSocket):
        async def recv(self) -> str | bytes:
            await asyncio.Event().wait()
            raise AssertionError("unreachable")

    blocking = BlockingSocket([])
    cancel_client = _client(socket=blocking, admitted=[])
    task = asyncio.create_task(
        cancel_client.run_connection(
            connection_id="connection-1",
            endpoint_url="wss://socket.example.test/connection",
        )
    )
    await asyncio.sleep(0)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert blocking.closed is True
    del blocking_socket
