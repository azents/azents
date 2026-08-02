"""Discord Application metadata client tests."""

import httpx
import pytest

from azents.services.external_channel.discord_api import (
    DISCORD_AZENTS_MESSAGE_COMMAND_NAME,
    DiscordAPIClient,
    DiscordAPIConfigurationInvalid,
    DiscordAPICredentialsInvalid,
    DiscordAPIUnavailable,
    DiscordGuildCommandRole,
)


def _client(handler: httpx.MockTransport) -> DiscordAPIClient:
    return DiscordAPIClient(httpx.AsyncClient(transport=handler))


@pytest.mark.asyncio
async def test_reads_current_application_verify_key() -> None:
    """Bot-token metadata exposes only validated authority fields."""
    transport = httpx.MockTransport(
        lambda request: httpx.Response(
            200,
            json={"id": "app-1", "verify_key": "ab" * 32},
            request=request,
        )
    )
    client = _client(transport)

    metadata = await client.get_current_application(bot_token="redacted-token")

    assert metadata.application_id == "app-1"
    assert metadata.verify_key == "ab" * 32
    await client.http_client.aclose()


@pytest.mark.asyncio
async def test_rejects_invalid_bot_token() -> None:
    """Credential rejection remains distinct from provider unavailability."""
    transport = httpx.MockTransport(
        lambda request: httpx.Response(401, request=request)
    )
    client = _client(transport)

    with pytest.raises(DiscordAPICredentialsInvalid):
        await client.get_current_application(bot_token="redacted-token")
    await client.http_client.aclose()


@pytest.mark.asyncio
async def test_rejects_malformed_verify_key() -> None:
    """Malformed provider metadata cannot become an interaction verifier."""
    transport = httpx.MockTransport(
        lambda request: httpx.Response(
            200,
            json={"id": "app-1", "verify_key": "not-hex"},
            request=request,
        )
    )
    client = _client(transport)

    with pytest.raises(DiscordAPIUnavailable):
        await client.get_current_application(bot_token="redacted-token")
    await client.http_client.aclose()


@pytest.mark.asyncio
async def test_reads_current_bot_user_identity() -> None:
    """The Bot identity is stored separately from the Discord Application ID."""
    transport = httpx.MockTransport(
        lambda request: httpx.Response(
            200,
            json={"id": "123456789012345678"},
            request=request,
        )
    )
    client = _client(transport)

    bot_user_id = await client.get_current_bot_user_id(bot_token="redacted-token")

    assert bot_user_id == "123456789012345678"
    await client.http_client.aclose()


@pytest.mark.asyncio
async def test_configures_interaction_endpoint_without_persisting_selector() -> None:
    """The provider call receives the opaque selector only in its endpoint URL."""
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, request=request)

    client = _client(httpx.MockTransport(handler))
    endpoint_url = "https://callbacks.example/discord/interactions/opaque-selector"

    await client.configure_interactions_endpoint(
        bot_token="redacted-token",
        application_id="app-1",
        endpoint_url=endpoint_url,
    )

    assert len(requests) == 1
    request = requests[0]
    assert request.method == "PATCH"
    assert request.url.path == "/api/v10/applications/app-1"
    assert request.headers["authorization"] == "Bot redacted-token"
    assert (
        request.json()
        if False
        else request.content
        == (
            b'{"interactions_endpoint_url":"'
            b"https://callbacks.example/discord/interactions/opaque-selector"
            b'"}'
        )
    )
    await client.http_client.aclose()


@pytest.mark.asyncio
async def test_reconciles_required_commands_without_overwriting_customer_commands() -> (
    None
):
    """The reconciler preserves unrelated Guild commands and returns every role ID."""
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(
            200,
            json=[
                {
                    "id": "101",
                    "name": DISCORD_AZENTS_MESSAGE_COMMAND_NAME,
                    "type": 3,
                },
                {
                    "id": "102",
                    "name": "Azents settings",
                    "type": 1,
                    "description": "Configure Azents settings.",
                },
                {
                    "id": "103",
                    "name": "Conversation settings",
                    "type": 3,
                },
                {
                    "id": "900",
                    "name": "Customer command",
                    "type": 1,
                    "description": "Customer-owned command.",
                },
            ],
            request=request,
        )

    client = _client(httpx.MockTransport(handler))

    command_set = await client.reconcile_required_guild_commands(
        bot_token="redacted-token",
        application_id="app-1",
        guild_id="guild-1",
    )

    assert command_set.schema_version == 1
    assert command_set.command_ids == {
        DiscordGuildCommandRole.MESSAGE_ACTION: "101",
        DiscordGuildCommandRole.AZENTS_SETTINGS: "102",
        DiscordGuildCommandRole.CONVERSATION_SETTINGS: "103",
    }
    assert len(requests) == 1
    request = requests[0]
    assert request.method == "GET"
    assert request.url.path == "/api/v10/applications/app-1/guilds/guild-1/commands"
    assert request.headers["authorization"] == "Bot redacted-token"
    await client.http_client.aclose()


@pytest.mark.asyncio
async def test_reconciles_missing_stale_and_duplicate_azents_commands_only() -> None:
    """The reconciler creates, updates, and deletes only recognized Azents commands."""
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.method == "GET":
            return httpx.Response(
                200,
                json=[
                    {
                        "id": "100",
                        "name": DISCORD_AZENTS_MESSAGE_COMMAND_NAME,
                        "type": 3,
                    },
                    {
                        "id": "101",
                        "name": DISCORD_AZENTS_MESSAGE_COMMAND_NAME,
                        "type": 3,
                    },
                    {
                        "id": "200",
                        "name": "Azents settings",
                        "type": 1,
                        "description": "Old settings copy.",
                    },
                    {
                        "id": "900",
                        "name": "Customer command",
                        "type": 1,
                        "description": "Customer-owned command.",
                    },
                ],
                request=request,
            )
        if request.method == "PATCH":
            assert request.url.path.endswith("/commands/200")
            return httpx.Response(
                200,
                json={
                    "id": "200",
                    "name": "Azents settings",
                    "type": 1,
                    "description": "Configure Azents settings.",
                },
                request=request,
            )
        if request.method == "POST":
            return httpx.Response(
                201,
                json={
                    "id": "300",
                    "name": "Conversation settings",
                    "type": 3,
                },
                request=request,
            )
        assert request.method == "DELETE"
        assert request.url.path.endswith("/commands/101")
        return httpx.Response(204, request=request)

    client = _client(httpx.MockTransport(handler))

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
    assert [(request.method, request.url.path) for request in requests] == [
        ("GET", "/api/v10/applications/app-1/guilds/guild-1/commands"),
        ("PATCH", "/api/v10/applications/app-1/guilds/guild-1/commands/200"),
        ("POST", "/api/v10/applications/app-1/guilds/guild-1/commands"),
        ("DELETE", "/api/v10/applications/app-1/guilds/guild-1/commands/101"),
    ]
    assert requests[1].content == (
        b'{"name":"Azents settings","type":1,'
        b'"description":"Configure Azents settings."}'
    )
    assert requests[2].content == b'{"name":"Conversation settings","type":3}'
    await client.http_client.aclose()


@pytest.mark.asyncio
async def test_reconciliation_rejects_non_distinct_required_command_ids() -> None:
    """A provider result cannot activate two required roles with one command ID."""
    transport = httpx.MockTransport(
        lambda request: httpx.Response(
            200,
            json=[
                {
                    "id": "100",
                    "name": DISCORD_AZENTS_MESSAGE_COMMAND_NAME,
                    "type": 3,
                },
                {
                    "id": "100",
                    "name": "Azents settings",
                    "type": 1,
                    "description": "Configure Azents settings.",
                },
                {
                    "id": "100",
                    "name": "Conversation settings",
                    "type": 3,
                },
            ],
            request=request,
        )
    )
    client = _client(transport)

    with pytest.raises(DiscordAPIConfigurationInvalid):
        await client.reconcile_required_guild_commands(
            bot_token="redacted-token",
            application_id="app-1",
            guild_id="guild-1",
        )
    await client.http_client.aclose()
