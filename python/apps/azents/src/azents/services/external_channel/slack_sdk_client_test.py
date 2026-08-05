"""Configured Slack SDK client security-boundary tests."""

import logging
from unittest.mock import AsyncMock

import aiohttp
import pytest
from slack_sdk.socket_mode.aiohttp import SocketModeClient

from azents.services.external_channel.slack_sdk_client import (
    AzentsSlackSocketModeClient,
    create_slack_socket_mode_client,
    create_slack_web_client,
)


def test_slack_web_client_disables_retries_and_payload_logging() -> None:
    """Keep provider mutations one-attempt and provider content out of SDK logs."""
    client = create_slack_web_client()
    sdk_logger = client._logger

    assert client.retry_handlers == []
    assert isinstance(sdk_logger, logging.Logger)
    assert sdk_logger.level == logging.CRITICAL
    assert sdk_logger.propagate is False
    assert any(
        isinstance(handler, logging.NullHandler) for handler in sdk_logger.handlers
    )


@pytest.mark.asyncio
async def test_socket_mode_client_retains_sdk_dispatch_and_reconnect() -> None:
    """The SDK owns its queue, endpoint acquisition, and automatic reconnect."""

    async def on_message(_: aiohttp.WSMessage) -> None:
        pass

    client = create_slack_socket_mode_client(
        app_token="xapp-secret",
        web_client=create_slack_web_client(),
        ping_interval=5.0,
        on_message=on_message,
        on_active=AsyncMock(),
        on_gap=AsyncMock(),
        on_failure=AsyncMock(),
    )
    try:
        assert isinstance(client, AzentsSlackSocketModeClient)
        assert client.auto_reconnect_enabled is True
        assert client.default_auto_reconnect_enabled is True
        assert client.wss_uri is None
        assert client.ping_interval == 5.0
        assert client.trace_enabled is False
        assert client.on_message_listeners == [on_message]
        assert client.on_error_listeners == []
        assert client.on_close_listeners == []
        assert client.logger.level == logging.CRITICAL
        assert client.logger.propagate is False
        assert (
            AzentsSlackSocketModeClient.enqueue_message
            is SocketModeClient.enqueue_message
        )
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_socket_mode_client_observes_sdk_connect_and_reconnect(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Lifecycle callbacks wrap the SDK methods without replacing their mechanics."""
    sdk_calls: list[tuple[str, bool | None]] = []
    active = AsyncMock()
    gap = AsyncMock()

    async def sdk_connect(self: SocketModeClient) -> None:
        del self
        sdk_calls.append(("connect", None))

    async def sdk_reconnect(
        self: SocketModeClient,
        force: bool = False,
    ) -> None:
        del self
        sdk_calls.append(("reconnect", force))

    monkeypatch.setattr(SocketModeClient, "connect", sdk_connect)
    monkeypatch.setattr(SocketModeClient, "connect_to_new_endpoint", sdk_reconnect)
    client = create_slack_socket_mode_client(
        app_token="xapp-secret",
        web_client=create_slack_web_client(),
        ping_interval=5.0,
        on_message=AsyncMock(),
        on_active=active,
        on_gap=gap,
        on_failure=AsyncMock(),
    )
    try:
        await client.connect()
        await client.connect_to_new_endpoint(force=True)
    finally:
        await client.close()

    assert sdk_calls == [("connect", None), ("reconnect", True)]
    active.assert_awaited_once()
    gap.assert_awaited_once_with("socket_reconnecting")
