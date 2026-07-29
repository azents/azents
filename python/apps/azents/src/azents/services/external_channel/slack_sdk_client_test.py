"""Configured Slack SDK client security-boundary tests."""

import logging

import aiohttp
import pytest
from slack_sdk.socket_mode.aiohttp import SocketModeClient

from azents.services.external_channel.slack_sdk_client import (
    create_slack_socket_mode_client,
    create_slack_web_client,
)


def test_slack_web_client_disables_retries_and_payload_logging() -> None:
    """Keep provider mutations one-attempt and provider content out of SDK logs."""
    client = create_slack_web_client()
    sdk_logger = client._logger  # pyright: ignore[reportPrivateUsage]

    assert client.retry_handlers == []
    assert isinstance(sdk_logger, logging.Logger)
    assert sdk_logger.level == logging.CRITICAL
    assert sdk_logger.propagate is False
    assert any(
        isinstance(handler, logging.NullHandler) for handler in sdk_logger.handlers
    )


@pytest.mark.asyncio
async def test_socket_mode_client_uses_sdk_transport_without_sdk_reconnect() -> None:
    """Use the public aiohttp SDK transport under Azents lifecycle ownership."""

    async def on_message(_: aiohttp.WSMessage) -> None:
        pass

    async def on_error(_: aiohttp.WSMessage) -> None:
        pass

    async def on_close(_: aiohttp.WSMessage) -> None:
        pass

    client = create_slack_socket_mode_client(
        app_token="xapp-secret",
        web_client=create_slack_web_client(),
        endpoint_url="wss://socket.example.test/connection",
        ping_interval=5.0,
        on_message=on_message,
        on_error=on_error,
        on_close=on_close,
    )
    try:
        assert isinstance(client, SocketModeClient)
        assert client.auto_reconnect_enabled is False
        assert client.default_auto_reconnect_enabled is False
        assert client.wss_uri == "wss://socket.example.test/connection"
        assert client.ping_interval == 5.0
        assert client.trace_enabled is False
        assert client.on_message_listeners == [on_message]
        assert client.on_error_listeners == [on_error]
        assert client.on_close_listeners == [on_close]
        assert client.logger.level == logging.CRITICAL
        assert client.logger.propagate is False

        await client.enqueue_message('{"type":"disconnect"}')
        assert client.message_queue.empty()
    finally:
        await client.close()
