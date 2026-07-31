"""Configured public Slack SDK clients for External Channel operations."""

import asyncio
import logging
from collections.abc import Awaitable, Callable

from aiohttp import WSMessage
from slack_sdk.errors import SlackApiError
from slack_sdk.socket_mode.aiohttp import SocketModeClient
from slack_sdk.web.async_client import AsyncWebClient
from slack_sdk.web.async_slack_response import AsyncSlackResponse

from azents.services.external_channel.slack_endpoint import (
    slack_api_base_url,
    slack_insecure_websocket_allowed,
)

type SlackSocketActiveCallback = Callable[[], Awaitable[None]]
type SlackSocketGapCallback = Callable[[str], Awaitable[None]]
type SlackSocketFailureCallback = Callable[[str, bool], Awaitable[None]]


class AzentsSlackSocketModeClient(SocketModeClient):
    """Observe SDK lifecycle while retaining SDK-owned reconnect mechanics."""

    def __init__(
        self,
        *,
        app_token: str,
        logger: logging.Logger,
        web_client: AsyncWebClient,
        ping_interval: float,
        on_message: Callable[[WSMessage], Awaitable[None]],
        on_active: SlackSocketActiveCallback,
        on_gap: SlackSocketGapCallback,
        on_failure: SlackSocketFailureCallback,
    ) -> None:
        self.on_active = on_active
        self.on_gap = on_gap
        self.on_failure = on_failure
        super().__init__(
            app_token=app_token,
            logger=logger,
            web_client=web_client,
            auto_reconnect_enabled=True,
            ping_interval=ping_interval,
            trace_enabled=False,
            on_message_listeners=[on_message],
        )

    async def connect(self) -> None:
        """Delegate connection establishment and report the resulting active state."""
        await super().connect()
        await self.on_active()

    async def connect_to_new_endpoint(self, force: bool = False) -> None:
        """Report a gap before delegating endpoint replacement to the SDK."""
        await self.on_gap("socket_reconnecting")
        await super().connect_to_new_endpoint(force=force)

    async def issue_new_wss_url(self) -> str:
        """Delegate endpoint minting while surfacing bounded terminal outcomes."""
        try:
            url = await super().issue_new_wss_url()
        except asyncio.CancelledError:
            raise
        except SlackApiError as error:
            error_code = _slack_api_error_code(error)
            reconnect_required = error_code in {
                "account_inactive",
                "invalid_auth",
                "not_authed",
                "token_revoked",
            }
            await self.on_failure(
                "socket_credentials_rejected"
                if reconnect_required
                else "socket_endpoint_unavailable",
                reconnect_required,
            )
            raise
        secure_url = url.startswith("wss://")
        testenv_url = url.startswith("ws://") and slack_insecure_websocket_allowed()
        if not secure_url and not testenv_url:
            await self.on_failure("socket_endpoint_invalid", False)
            raise ValueError("Slack Socket Mode endpoint is invalid.")
        return url


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
    ping_interval: float,
    on_message: Callable[[WSMessage], Awaitable[None]],
    on_active: SlackSocketActiveCallback,
    on_gap: SlackSocketGapCallback,
    on_failure: SlackSocketFailureCallback,
) -> SocketModeClient:
    """Create one automatically reconnecting observed SDK Socket client."""
    return AzentsSlackSocketModeClient(
        app_token=app_token,
        logger=_slack_sdk_logger(),
        web_client=web_client,
        ping_interval=ping_interval,
        on_message=on_message,
        on_active=on_active,
        on_gap=on_gap,
        on_failure=on_failure,
    )


def _slack_api_error_code(error: SlackApiError) -> str | None:
    response = error.response
    if not isinstance(response, AsyncSlackResponse) or not isinstance(
        response.data, dict
    ):
        return None
    value = response.data.get("error")
    return value if isinstance(value, str) else None


def _slack_sdk_logger() -> logging.Logger:
    """Create a silent SDK logger for payload-bearing Web API operations."""
    sdk_logger = logging.Logger(
        "azents.services.external_channel.slack_sdk",
        level=logging.CRITICAL,
    )
    sdk_logger.addHandler(logging.NullHandler())
    sdk_logger.propagate = False
    return sdk_logger
