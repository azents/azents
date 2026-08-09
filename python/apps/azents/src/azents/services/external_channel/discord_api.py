"""Minimal Discord REST adapter for connection-authority metadata."""

from collections.abc import AsyncIterator
from dataclasses import dataclass
from enum import StrEnum
from typing import Annotated, Literal

import httpx
from fastapi import Depends
from pydantic import BaseModel, ConfigDict, ValidationError, model_validator

from azents.services.external_channel.discord_endpoint import discord_api_base_url

DISCORD_AZENTS_MESSAGE_COMMAND_NAME = "Ask an Azents Agent"


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


@dataclass(frozen=True)
class DiscordGuildCommand:
    """Sanitized provider-authoritative Guild application-command metadata."""

    command_id: str
    name: str
    command_type: int
    description: str | None


class DiscordGuildCommandRole(StrEnum):
    """One required Azents-owned Guild command responsibility."""

    MESSAGE_ACTION = "message_action"
    AZENTS_SETTINGS = "azents_settings"
    CONVERSATION_SETTINGS = "conversation_settings"


@dataclass(frozen=True)
class DiscordGuildCommandDefinition:
    """Provider-visible contract for one required Guild command role."""

    role: DiscordGuildCommandRole
    name: str
    command_type: int
    description: str | None

    def owns(self, command: DiscordGuildCommand) -> bool:
        """Return whether this definition recognizes a command as Azents-owned."""
        return command.name == self.name and command.command_type == self.command_type

    def matches(self, command: DiscordGuildCommand) -> bool:
        """Return whether the provider command is current for this definition."""
        return self.owns(command) and (
            self.command_type != 1 or command.description == self.description
        )

    def request_payload(self) -> dict[str, str | int]:
        """Return the minimal provider mutation payload for this command."""
        payload: dict[str, str | int] = {
            "name": self.name,
            "type": self.command_type,
        }
        if self.description is not None:
            payload["description"] = self.description
        return payload


DISCORD_REQUIRED_GUILD_COMMANDS = (
    DiscordGuildCommandDefinition(
        role=DiscordGuildCommandRole.MESSAGE_ACTION,
        name=DISCORD_AZENTS_MESSAGE_COMMAND_NAME,
        command_type=3,
        description=None,
    ),
    DiscordGuildCommandDefinition(
        role=DiscordGuildCommandRole.AZENTS_SETTINGS,
        name="Azents settings",
        command_type=1,
        description="Configure Azents settings.",
    ),
    DiscordGuildCommandDefinition(
        role=DiscordGuildCommandRole.CONVERSATION_SETTINGS,
        name="Conversation settings",
        command_type=3,
        description=None,
    ),
)

DISCORD_REQUIRED_GUILD_COMMAND_BY_ROLE = {
    command.role: command for command in DISCORD_REQUIRED_GUILD_COMMANDS
}


class DiscordGuildCommandSetCapability(BaseModel):
    """Versioned, complete command-role proof retained on a Discord connection."""

    model_config = ConfigDict(frozen=True)

    schema_version: Literal[1]
    command_ids: dict[DiscordGuildCommandRole, str]

    @model_validator(mode="after")
    def _validate_required_distinct_command_ids(
        self,
    ) -> "DiscordGuildCommandSetCapability":
        """Require every current role to resolve to one distinct Discord snowflake."""
        required_roles = set(DISCORD_REQUIRED_GUILD_COMMAND_BY_ROLE)
        if set(self.command_ids) != required_roles:
            raise ValueError("Discord command capability roles are incomplete.")
        if any(not command_id.isdigit() for command_id in self.command_ids.values()):
            raise ValueError("Discord command capability IDs are invalid.")
        if len(set(self.command_ids.values())) != len(self.command_ids):
            raise ValueError("Discord command capability IDs must be distinct.")
        return self

    def command_id_for(self, role: DiscordGuildCommandRole) -> str:
        """Return the persisted command ID for one required role."""
        return self.command_ids[role]


def discord_required_guild_command(
    role: DiscordGuildCommandRole,
) -> DiscordGuildCommandDefinition:
    """Return the current provider contract for one required command role."""
    return DISCORD_REQUIRED_GUILD_COMMAND_BY_ROLE[role]


def discord_command_role_from_name_and_type(
    *,
    name: str,
    command_type: int,
) -> DiscordGuildCommandRole | None:
    """Resolve one exact current provider name/type pair to its required role."""
    for definition in DISCORD_REQUIRED_GUILD_COMMANDS:
        if definition.name == name and definition.command_type == command_type:
            return definition.role
    return None


def discord_command_matches_capability(
    *,
    command_set: DiscordGuildCommandSetCapability,
    role: DiscordGuildCommandRole,
    command_id: str,
    name: str,
    command_type: int,
) -> bool:
    """Return whether an interaction command exactly matches current authority."""
    definition = discord_required_guild_command(role)
    return (
        command_set.command_id_for(role) == command_id
        and definition.name == name
        and definition.command_type == command_type
    )


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
        endpoint_url: str,
    ) -> None:
        """Configure the requesting Bot's outgoing interaction endpoint."""
        try:
            response = await self.http_client.patch(
                f"{discord_api_base_url()}/applications/@me",
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

    async def list_guild_commands(
        self,
        *,
        bot_token: str,
        application_id: str,
        guild_id: str,
    ) -> tuple[DiscordGuildCommand, ...]:
        """List sanitized current application commands for one target Guild."""
        try:
            response = await self.http_client.get(
                f"{discord_api_base_url()}/applications/{application_id}/guilds/"
                f"{guild_id}/commands",
                headers={"Authorization": f"Bot {bot_token}"},
            )
        except httpx.RequestError as error:
            raise DiscordAPIUnavailable from error
        self._raise_for_command_response(response)
        try:
            payload: object = response.json()
        except ValueError as error:
            raise DiscordAPIUnavailable from error
        if not isinstance(payload, list):
            raise DiscordAPIUnavailable
        commands: list[DiscordGuildCommand] = []
        for item in payload:
            command = _discord_guild_command_from_payload(item)
            if command is None:
                raise DiscordAPIUnavailable
            commands.append(command)
        return tuple(commands)

    async def create_guild_command(
        self,
        *,
        bot_token: str,
        application_id: str,
        guild_id: str,
        definition: DiscordGuildCommandDefinition,
    ) -> DiscordGuildCommand:
        """Create one required Azents-owned Guild command."""
        try:
            response = await self.http_client.post(
                f"{discord_api_base_url()}/applications/{application_id}/guilds/"
                f"{guild_id}/commands",
                headers={"Authorization": f"Bot {bot_token}"},
                json=definition.request_payload(),
            )
        except httpx.RequestError as error:
            raise DiscordAPIUnavailable from error
        self._raise_for_command_response(response)
        return _discord_guild_command_from_response(response)

    async def update_guild_command(
        self,
        *,
        bot_token: str,
        application_id: str,
        guild_id: str,
        command_id: str,
        definition: DiscordGuildCommandDefinition,
    ) -> DiscordGuildCommand:
        """Update one recognized Azents-owned Guild command to its current contract."""
        try:
            response = await self.http_client.patch(
                f"{discord_api_base_url()}/applications/{application_id}/guilds/"
                f"{guild_id}/commands/{command_id}",
                headers={"Authorization": f"Bot {bot_token}"},
                json=definition.request_payload(),
            )
        except httpx.RequestError as error:
            raise DiscordAPIUnavailable from error
        self._raise_for_command_response(response)
        return _discord_guild_command_from_response(response)

    async def delete_guild_command(
        self,
        *,
        bot_token: str,
        application_id: str,
        guild_id: str,
        command_id: str,
    ) -> None:
        """Delete one recognized obsolete Azents-owned Guild command."""
        try:
            response = await self.http_client.delete(
                f"{discord_api_base_url()}/applications/{application_id}/guilds/"
                f"{guild_id}/commands/{command_id}",
                headers={"Authorization": f"Bot {bot_token}"},
            )
        except httpx.RequestError as error:
            raise DiscordAPIUnavailable from error
        self._raise_for_command_response(response)

    async def reconcile_required_guild_commands(
        self,
        *,
        bot_token: str,
        application_id: str,
        guild_id: str,
    ) -> DiscordGuildCommandSetCapability:
        """Reconcile only known Azents commands without replacing customer commands."""
        current = await self.list_guild_commands(
            bot_token=bot_token,
            application_id=application_id,
            guild_id=guild_id,
        )
        selected: dict[DiscordGuildCommandRole, DiscordGuildCommand] = {}
        obsolete: list[DiscordGuildCommand] = []
        for definition in DISCORD_REQUIRED_GUILD_COMMANDS:
            matching = sorted(
                (command for command in current if definition.owns(command)),
                key=lambda command: (
                    not definition.matches(command),
                    command.command_id,
                ),
            )
            if not matching:
                created = await self.create_guild_command(
                    bot_token=bot_token,
                    application_id=application_id,
                    guild_id=guild_id,
                    definition=definition,
                )
                _require_definition_match(created, definition)
                selected[definition.role] = created
                continue
            selected_command = matching[0]
            if not definition.matches(selected_command):
                selected_command = await self.update_guild_command(
                    bot_token=bot_token,
                    application_id=application_id,
                    guild_id=guild_id,
                    command_id=selected_command.command_id,
                    definition=definition,
                )
                _require_definition_match(selected_command, definition)
            selected[definition.role] = selected_command
            obsolete.extend(matching[1:])
        for command in obsolete:
            await self.delete_guild_command(
                bot_token=bot_token,
                application_id=application_id,
                guild_id=guild_id,
                command_id=command.command_id,
            )
        try:
            return DiscordGuildCommandSetCapability(
                schema_version=1,
                command_ids={
                    role: command.command_id for role, command in selected.items()
                },
            )
        except ValidationError as error:
            raise DiscordAPIConfigurationInvalid from error

    @staticmethod
    def _raise_for_command_response(response: httpx.Response) -> None:
        """Map one command endpoint response to established safe error types."""
        if response.status_code in {401, 403}:
            raise DiscordAPICredentialsInvalid
        if response.status_code == 429 or response.status_code >= 500:
            raise DiscordAPIUnavailable
        if response.status_code >= 400:
            raise DiscordAPIConfigurationInvalid


def _discord_guild_command_from_response(
    response: httpx.Response,
) -> DiscordGuildCommand:
    """Parse one successful command mutation response."""
    try:
        payload: object = response.json()
    except ValueError as error:
        raise DiscordAPIUnavailable from error
    command = _discord_guild_command_from_payload(payload)
    if command is None:
        raise DiscordAPIUnavailable
    return command


def _discord_guild_command_from_payload(payload: object) -> DiscordGuildCommand | None:
    """Return sanitized command metadata only when all routing fields are valid."""
    if not isinstance(payload, dict):
        return None
    command_id = payload.get("id")
    name = payload.get("name")
    command_type = payload.get("type")
    description = payload.get("description")
    if (
        not isinstance(command_id, str)
        or not command_id.isdigit()
        or not isinstance(name, str)
        or not name
        or not isinstance(command_type, int)
        or isinstance(command_type, bool)
        or description is not None
        and not isinstance(description, str)
    ):
        return None
    return DiscordGuildCommand(
        command_id=command_id,
        name=name,
        command_type=command_type,
        description=description,
    )


def _require_definition_match(
    command: DiscordGuildCommand,
    definition: DiscordGuildCommandDefinition,
) -> None:
    """Reject provider mutation output that cannot prove the requested authority."""
    if not definition.matches(command):
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
