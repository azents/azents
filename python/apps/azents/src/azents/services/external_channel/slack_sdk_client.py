"""Configured public Slack SDK clients for External Channel operations."""

import logging
from collections.abc import Awaitable, Callable

from aiohttp import WSMessage
from slack_sdk.socket_mode.aiohttp import SocketModeClient
from slack_sdk.web.async_client import AsyncWebClient

from azents.services.external_channel.slack_endpoint import slack_api_base_url


class AzentsSlackSocketModeClient(SocketModeClient):
    """Use SDK transport without its message-level reconnect dispatcher."""

    async def enqueue_message(self, message: str) -> None:
        """Dispatch Socket messages only through the explicit Azents listener."""
        del message


def create_slack_web_client() -> AsyncWebClient:
    """Create a non-retrying Slack client that cannot log provider content."""
    return AsyncWebClient(
        base_url=f"{slack_api_base_url().rstrip('/')}/",
        timeout=20,
        retry_handlers=[],
        logger=_slack_sdk_logger(),
    )


def create_slack_socket_mode_client(
    *,
    app_token: str,
    web_client: AsyncWebClient,
    endpoint_url: str,
    ping_interval: float,
    on_message: Callable[[WSMessage], Awaitable[None]],
    on_error: Callable[[WSMessage], Awaitable[None]],
    on_close: Callable[[WSMessage], Awaitable[None]],
) -> SocketModeClient:
    """Create one non-reconnecting SDK Socket Mode transport."""
    client = AzentsSlackSocketModeClient(
        app_token=app_token,
        logger=_slack_sdk_logger(),
        web_client=web_client,
        auto_reconnect_enabled=False,
        ping_interval=ping_interval,
        trace_enabled=False,
        on_message_listeners=[on_message],
        on_error_listeners=[on_error],
        on_close_listeners=[on_close],
    )
    client.wss_uri = endpoint_url
    return client


def _slack_sdk_logger() -> logging.Logger:
    """Create a silent SDK logger for payload-bearing Web API operations."""
    sdk_logger = logging.Logger(
        "azents.services.external_channel.slack_sdk",
        level=logging.CRITICAL,
    )
    sdk_logger.addHandler(logging.NullHandler())
    sdk_logger.propagate = False
    return sdk_logger
