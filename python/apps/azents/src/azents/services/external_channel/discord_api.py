"""Minimal Discord REST adapter for connection-authority metadata."""

from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Annotated

import httpx
from fastapi import Depends

from azents.services.external_channel.discord_endpoint import discord_api_base_url


class DiscordAPIError(RuntimeError):
    """Base class for controlled Discord REST adapter errors."""


class DiscordAPICredentialsInvalid(DiscordAPIError):
    """Discord rejected the configured Bot Token."""


class DiscordAPIConfigurationInvalid(DiscordAPIError):
    """Discord rejected the configured Application or interaction endpoint."""


class DiscordAPIUnavailable(DiscordAPIError):
    """Discord cannot currently provide required authority metadata."""


@dataclass(frozen=True)
class DiscordApplicationMetadata:
    """Sanitized provider-authoritative Application metadata."""

    application_id: str
    verify_key: str


class DiscordAPIClient:
    """Fetch the current Application metadata using a Bot Token."""

    def __init__(self, http_client: httpx.AsyncClient) -> None:
        self.http_client = http_client

    async def get_current_application(
        self,
        *,
        bot_token: str,
    ) -> DiscordApplicationMetadata:
        """Return App identity and interaction verification key."""
        try:
            response = await self.http_client.get(
                f"{discord_api_base_url()}/oauth2/applications/@me",
                headers={"Authorization": f"Bot {bot_token}"},
            )
        except httpx.RequestError as error:
            raise DiscordAPIUnavailable from error
        if response.status_code in {401, 403}:
            raise DiscordAPICredentialsInvalid
        if response.status_code == 429 or response.status_code >= 500:
            raise DiscordAPIUnavailable
        try:
            payload: object = response.json()
        except ValueError as error:
            raise DiscordAPIUnavailable from error
        if not isinstance(payload, dict):
            raise DiscordAPIUnavailable
        application_id = payload.get("id")
        verify_key = payload.get("verify_key")
        if (
            not isinstance(application_id, str)
            or not application_id
            or not isinstance(verify_key, str)
            or len(verify_key) != 64
        ):
            raise DiscordAPIUnavailable
        try:
            bytes.fromhex(verify_key)
        except ValueError as error:
            raise DiscordAPIUnavailable from error
        return DiscordApplicationMetadata(
            application_id=application_id,
            verify_key=verify_key,
        )

    async def get_current_bot_user_id(self, *, bot_token: str) -> str:
        """Return the current Bot user identity required for mention classification."""
        try:
            response = await self.http_client.get(
                f"{discord_api_base_url()}/users/@me",
                headers={"Authorization": f"Bot {bot_token}"},
            )
        except httpx.RequestError as error:
            raise DiscordAPIUnavailable from error
        if response.status_code in {401, 403}:
            raise DiscordAPICredentialsInvalid
        if response.status_code == 429 or response.status_code >= 500:
            raise DiscordAPIUnavailable
        try:
            payload: object = response.json()
        except ValueError as error:
            raise DiscordAPIUnavailable from error
        bot_user_id = payload.get("id") if isinstance(payload, dict) else None
        if not isinstance(bot_user_id, str) or not bot_user_id.isdigit():
            raise DiscordAPIUnavailable
        return bot_user_id

    async def configure_interactions_endpoint(
        self,
        *,
        bot_token: str,
        application_id: str,
        endpoint_url: str,
    ) -> None:
        """Configure one Application's outgoing interaction endpoint."""
        try:
            response = await self.http_client.patch(
                f"{discord_api_base_url()}/applications/{application_id}",
                headers={"Authorization": f"Bot {bot_token}"},
                json={"interactions_endpoint_url": endpoint_url},
            )
        except httpx.RequestError as error:
            raise DiscordAPIUnavailable from error
        if response.status_code in {401, 403}:
            raise DiscordAPICredentialsInvalid
        if response.status_code == 429 or response.status_code >= 500:
            raise DiscordAPIUnavailable
        if response.status_code >= 400:
            raise DiscordAPIConfigurationInvalid


async def get_discord_api_http_client() -> AsyncIterator[httpx.AsyncClient]:
    """Provide a bounded HTTP client for Discord Application API calls."""
    async with httpx.AsyncClient(timeout=20.0) as client:
        yield client


def get_discord_api_client(
    http_client: Annotated[
        httpx.AsyncClient,
        Depends(get_discord_api_http_client),
    ],
) -> DiscordAPIClient:
    """Provide the Discord Application API adapter."""
    return DiscordAPIClient(http_client)
