"""Discord public SDK application adapter tests."""

import contextlib
import json
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import cast

import httpx
import pytest

from azents.services.external_channel.discord_api import (
    DISCORD_AZENTS_MESSAGE_COMMAND_NAME,
    DISCORD_AZENTS_SETTINGS_COMMAND_NAME,
    DiscordAPIClient,
    DiscordAPIConfigurationInvalid,
    DiscordAPICredentialsInvalid,
    DiscordAPIUnavailable,
    DiscordGuildCommand,
    DiscordGuildCommandCreateTransport,
    DiscordGuildCommandDefinition,
    DiscordGuildCommandRole,
    DiscordInteractionEndpointHTTPTransport,
    DiscordInteractionEndpointTransport,
    discord_required_guild_command,
)
from azents.services.external_channel.discord_sdk import (
    DiscordSDKApplication,
    DiscordSDKCommand,
    DiscordSDKCredentialsInvalid,
    DiscordSDKSession,
)


@dataclass
class _SDKSession:
    application: DiscordSDKApplication = field(
        default_factory=lambda: DiscordSDKApplication(
            application_id="app-1",
            verify_key="ab" * 32,
        )
    )
    bot_user_id: str = "123456789012345678"
    commands: list[DiscordSDKCommand] = field(default_factory=list)
    updated: list[str] = field(default_factory=list)
    deleted: list[str] = field(default_factory=list)

    async def fetch_application(self) -> DiscordSDKApplication:
        return self.application

    def current_bot_user_id(self) -> str:
        return self.bot_user_id

    async def list_guild_commands(
        self,
        *,
        application_id: str,
        guild_id: str,
    ) -> tuple[DiscordSDKCommand, ...]:
        assert application_id == "app-1"
        assert guild_id == "guild-1"
        return tuple(self.commands)

    async def update_guild_command(
        self,
        *,
        command_id: str,
        name: str,
        command_type: int,
        description: str | None,
    ) -> DiscordSDKCommand:
        self.updated.append(command_id)
        updated = DiscordSDKCommand(
            command_id=command_id,
            name=name,
            command_type=command_type,
            description=description,
        )
        self.commands = [
            updated if command.command_id == command_id else command
            for command in self.commands
        ]
        return updated

    async def delete_guild_command(self, *, command_id: str) -> None:
        self.deleted.append(command_id)
        self.commands = [
            command for command in self.commands if command.command_id != command_id
        ]

    async def fetch_message_projection(self, **_: object) -> dict[str, object]:
        raise AssertionError("application adapter must not fetch messages")

    async def fetch_history_projections(
        self, **_: object
    ) -> tuple[dict[str, object], ...]:
        raise AssertionError("application adapter must not fetch history")


@dataclass
class _SDKFactory:
    session: _SDKSession
    error: Exception | None = None
    open_count: int = 0

    @contextlib.asynccontextmanager
    async def open(self, *, bot_token: str) -> AsyncIterator[DiscordSDKSession]:
        assert bot_token == "redacted-token"
        self.open_count += 1
        if self.error is not None:
            raise self.error
        yield cast(DiscordSDKSession, self.session)


@dataclass
class _CreateTransport(DiscordGuildCommandCreateTransport):
    created: list[DiscordGuildCommandDefinition] = field(default_factory=list)
    next_id: int = 300

    async def create(
        self,
        *,
        bot_token: str,
        application_id: str,
        guild_id: str,
        definition: DiscordGuildCommandDefinition,
    ) -> DiscordGuildCommand:
        assert bot_token == "redacted-token"
        assert application_id == "app-1"
        assert guild_id == "guild-1"
        self.created.append(definition)
        command = DiscordGuildCommand(
            command_id=str(self.next_id),
            name=definition.name,
            command_type=definition.command_type,
            description=definition.description,
        )
        self.next_id += 1
        return command


@dataclass
class _EndpointTransport(DiscordInteractionEndpointTransport):
    configured_endpoint: str | None = None

    async def configure(
        self,
        *,
        bot_token: str,
        endpoint_url: str,
    ) -> None:
        assert bot_token == "redacted-token"
        self.configured_endpoint = endpoint_url


def _client(
    session: _SDKSession | None = None,
    *,
    error: Exception | None = None,
) -> tuple[
    DiscordAPIClient,
    _SDKFactory,
    _EndpointTransport,
    _CreateTransport,
]:
    factory = _SDKFactory(session or _SDKSession(), error=error)
    endpoint = _EndpointTransport()
    create = _CreateTransport()
    return DiscordAPIClient(factory, endpoint, create), factory, endpoint, create


@pytest.mark.asyncio
async def test_reads_current_application_verify_key_from_sdk() -> None:
    """Bot-token metadata exposes only validated SDK authority fields."""
    client, factory, _, _ = _client()

    metadata = await client.get_current_application(bot_token="redacted-token")

    assert metadata.application_id == "app-1"
    assert metadata.verify_key == "ab" * 32
    assert factory.open_count == 1


@pytest.mark.asyncio
async def test_maps_sdk_login_rejection_to_invalid_credentials() -> None:
    """Credential rejection remains distinct from provider unavailability."""
    client, _, _, _ = _client(error=DiscordSDKCredentialsInvalid())

    with pytest.raises(DiscordAPICredentialsInvalid):
        await client.get_current_application(bot_token="redacted-token")


@pytest.mark.asyncio
async def test_rejects_malformed_sdk_verify_key() -> None:
    """Malformed SDK metadata cannot become an interaction verifier."""
    session = _SDKSession(
        application=DiscordSDKApplication(
            application_id="app-1",
            verify_key="not-hex",
        )
    )
    client, _, _, _ = _client(session)

    with pytest.raises(DiscordAPIUnavailable):
        await client.get_current_application(bot_token="redacted-token")


@pytest.mark.asyncio
async def test_reads_current_bot_user_identity_from_sdk() -> None:
    """The SDK Bot identity remains distinct from the Application ID."""
    client, _, _, _ = _client()

    bot_user_id = await client.get_current_bot_user_id(bot_token="redacted-token")

    assert bot_user_id == "123456789012345678"


@pytest.mark.asyncio
async def test_configures_interaction_endpoint_through_direct_gap() -> None:
    """Endpoint configuration uses only the approved fixed-route transport."""
    client, _, endpoint, _ = _client()
    endpoint_url = "https://callbacks.example/discord/interactions/opaque-selector"

    await client.configure_interactions_endpoint(
        bot_token="redacted-token",
        endpoint_url=endpoint_url,
    )

    assert endpoint.configured_endpoint == endpoint_url


@pytest.mark.asyncio
async def test_callback_transport_issues_exact_current_application_patch() -> None:
    """The SDK gap transmits only the exact callback field and Bot authority."""
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, request=request)

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(handler),
    ) as http_client:
        transport = DiscordInteractionEndpointHTTPTransport(http_client)
        await transport.configure(
            bot_token="redacted-token",
            endpoint_url="https://callbacks.example/discord/interactions/selector",
        )

    assert len(requests) == 1
    request = requests[0]
    assert request.method == "PATCH"
    assert request.url.path == "/api/v10/applications/@me"
    assert request.headers["authorization"] == "Bot redacted-token"
    assert json.loads(request.content) == {
        "interactions_endpoint_url": (
            "https://callbacks.example/discord/interactions/selector"
        )
    }


def test_settings_command_uses_provider_valid_chat_input_name() -> None:
    """The settings slash-command payload satisfies Discord's name contract."""
    definition = discord_required_guild_command(DiscordGuildCommandRole.AZENTS_SETTINGS)

    assert definition.request_payload() == {
        "name": "azents",
        "type": 1,
        "description": "Configure Azents settings.",
    }


@pytest.mark.asyncio
async def test_reconciles_required_commands_without_touching_customer_command() -> None:
    """SDK listing preserves unrelated Guild commands and returns every role ID."""
    session = _SDKSession(
        commands=[
            DiscordSDKCommand(
                command_id="101",
                name=DISCORD_AZENTS_MESSAGE_COMMAND_NAME,
                command_type=3,
                description=None,
            ),
            DiscordSDKCommand(
                command_id="102",
                name=DISCORD_AZENTS_SETTINGS_COMMAND_NAME,
                command_type=1,
                description="Configure Azents settings.",
            ),
            DiscordSDKCommand(
                command_id="103",
                name="Conversation settings",
                command_type=3,
                description=None,
            ),
            DiscordSDKCommand(
                command_id="900",
                name="Customer command",
                command_type=1,
                description="Customer-owned command.",
            ),
        ]
    )
    client, factory, _, create = _client(session)

    command_set = await client.reconcile_required_guild_commands(
        bot_token="redacted-token",
        application_id="app-1",
        guild_id="guild-1",
    )

    assert command_set.command_ids == {
        DiscordGuildCommandRole.MESSAGE_ACTION: "101",
        DiscordGuildCommandRole.AZENTS_SETTINGS: "102",
        DiscordGuildCommandRole.CONVERSATION_SETTINGS: "103",
    }
    assert factory.open_count == 1
    assert create.created == []
    assert session.updated == []
    assert session.deleted == []
    assert any(command.command_id == "900" for command in session.commands)


@pytest.mark.asyncio
async def test_reconciliation_uses_g1_only_for_missing_command() -> None:
    """SDK update/delete and the sole G1 create gap reconcile known commands."""
    session = _SDKSession(
        commands=[
            DiscordSDKCommand(
                command_id="100",
                name=DISCORD_AZENTS_MESSAGE_COMMAND_NAME,
                command_type=3,
                description=None,
            ),
            DiscordSDKCommand(
                command_id="101",
                name=DISCORD_AZENTS_MESSAGE_COMMAND_NAME,
                command_type=3,
                description=None,
            ),
            DiscordSDKCommand(
                command_id="200",
                name=DISCORD_AZENTS_SETTINGS_COMMAND_NAME,
                command_type=1,
                description="Old settings copy.",
            ),
            DiscordSDKCommand(
                command_id="900",
                name="Customer command",
                command_type=1,
                description="Customer-owned command.",
            ),
        ]
    )
    client, _, _, create = _client(session)

    command_set = await client.reconcile_required_guild_commands(
        bot_token="redacted-token",
        application_id="app-1",
        guild_id="guild-1",
    )

    assert command_set.command_ids == {
        DiscordGuildCommandRole.MESSAGE_ACTION: "100",
        DiscordGuildCommandRole.AZENTS_SETTINGS: "200",
        DiscordGuildCommandRole.CONVERSATION_SETTINGS: "300",
    }
    assert session.updated == ["200"]
    assert session.deleted == ["101"]
    assert [definition.role for definition in create.created] == [
        DiscordGuildCommandRole.CONVERSATION_SETTINGS
    ]
    assert any(command.command_id == "900" for command in session.commands)


@pytest.mark.asyncio
async def test_reconciliation_rejects_non_distinct_required_command_ids() -> None:
    """One provider identity cannot activate two required command roles."""
    session = _SDKSession(
        commands=[
            DiscordSDKCommand(
                command_id="100",
                name=DISCORD_AZENTS_MESSAGE_COMMAND_NAME,
                command_type=3,
                description=None,
            ),
            DiscordSDKCommand(
                command_id="100",
                name=DISCORD_AZENTS_SETTINGS_COMMAND_NAME,
                command_type=1,
                description="Configure Azents settings.",
            ),
            DiscordSDKCommand(
                command_id="100",
                name="Conversation settings",
                command_type=3,
                description=None,
            ),
        ]
    )
    client, _, _, _ = _client(session)

    with pytest.raises(DiscordAPIConfigurationInvalid):
        await client.reconcile_required_guild_commands(
            bot_token="redacted-token",
            application_id="app-1",
            guild_id="guild-1",
        )
