"""Tests for provider-backed canonical ingestion history."""

import dataclasses
import datetime
from collections.abc import Callable
from contextlib import AbstractAsyncContextManager
from unittest.mock import AsyncMock, call, create_autospec

import pytest
from cryptography.fernet import Fernet
from sqlalchemy.ext.asyncio import AsyncSession

from azents.core.crypto import CredentialCipher
from azents.core.enums import (
    ExternalChannelAppMode,
    ExternalChannelConnectionStatus,
    ExternalChannelIngressProfile,
    ExternalChannelMessageLifecycle,
    ExternalChannelMessageRevisionKind,
    ExternalChannelPrincipalAuthorType,
    ExternalChannelProvider,
    ExternalChannelTransport,
)
from azents.core.external_channel_conversation_data import (
    ExternalChannelHistoryRange,
    ExternalChannelHistoryTemporaryFailure,
    ExternalChannelOperationDeadline,
)
from azents.core.external_channel_ingestion import ExternalChannelTriggerLocator
from azents.core.external_channel_provider import (
    DiscordConnectionCredentials,
    ExternalChannelConnectionCredentials,
    SlackConnectionCredentials,
)
from azents.core.external_channel_reference import provider_reference_mappings_size
from azents.repos.external_channel.data import ExternalChannelConnectionConfiguration
from azents.repos.external_channel.repository import ExternalChannelRepository
from azents.services.external_channel.credentials import ExternalChannelCredentialsCodec
from azents.services.external_channel.discord_events import DiscordNormalizedMessage
from azents.services.external_channel.discord_history import (
    DiscordConversationHistoryClient,
    DiscordConversationHistoryTrigger,
)
from azents.services.external_channel.ingestion_history import (
    ExternalChannelProviderHistoryReader,
)
from azents.services.external_channel.slack_events import (
    SlackConversationClient,
    SlackConversationHistoryTrigger,
    SlackNormalizedMessage,
)


def _configuration(
    *,
    provider: ExternalChannelProvider,
    provider_tenant_id: str,
    provider_bot_user_id: str,
    provider_app_id: str,
    encrypted_credentials: str,
) -> ExternalChannelConnectionConfiguration:
    now = datetime.datetime.now(datetime.UTC)
    return ExternalChannelConnectionConfiguration(
        id="connection-1",
        workspace_id="workspace-1",
        provider=provider,
        transport=ExternalChannelTransport.HTTP,
        ingress_profile=ExternalChannelIngressProfile.SLACK_HTTP
        if provider is ExternalChannelProvider.SLACK
        else ExternalChannelIngressProfile.DISCORD_GATEWAY_HTTP,
        configuration_generation=1,
        status=ExternalChannelConnectionStatus.ACTIVE,
        app_mode=ExternalChannelAppMode.SINGLE,
        provider_tenant_id=provider_tenant_id,
        provider_bot_user_id=provider_bot_user_id,
        provider_app_id=provider_app_id,
        http_callback_selector_hash=None,
        encrypted_credentials=encrypted_credentials,
        capabilities=None,
        provider_config=None,
        last_verified_at=None,
        last_health_at=None,
        disconnected_at=None,
        socket_lease_owner=None,
        socket_lease_until=None,
        socket_heartbeat_at=None,
        socket_gap_detected_at=None,
        socket_gap_reason=None,
        created_at=now,
        updated_at=now,
    )


class _Repository(ExternalChannelRepository):
    def __init__(self, *, get_connection_configuration: AsyncMock) -> None:
        super().__init__()
        self.configuration_call = get_connection_configuration

    async def get_connection_configuration(
        self, session: AsyncSession, *, connection_id: str
    ) -> ExternalChannelConnectionConfiguration | None:
        result: object = await self.configuration_call(
            session, connection_id=connection_id
        )
        assert result is None or isinstance(
            result, ExternalChannelConnectionConfiguration
        )
        return result


def _history_range[MessageT](
    value: object, message_type: type[MessageT]
) -> ExternalChannelHistoryRange[MessageT]:
    assert isinstance(value, ExternalChannelHistoryRange)
    messages: list[MessageT] = []
    for message in value.messages:
        assert isinstance(message, message_type)
        messages.append(message)
    assert isinstance(value.trigger, message_type)
    return ExternalChannelHistoryRange(
        messages=tuple(messages),
        trigger=value.trigger,
        context_omitted=value.context_omitted,
        range_start_position=value.range_start_position,
        trigger_position=value.trigger_position,
        provider_request_count=value.provider_request_count,
        scanned_message_count=value.scanned_message_count,
        elapsed_seconds=value.elapsed_seconds,
    )


class _SlackClient(SlackConversationClient):
    def __init__(
        self,
        *,
        read_range: AsyncMock,
        get_permalink: AsyncMock,
        fetch_user_display_name: AsyncMock,
        fetch_channel_display_name: AsyncMock,
    ) -> None:
        self.range_call = read_range
        self.permalink_call = get_permalink
        self.user_call = fetch_user_display_name
        self.channel_call = fetch_channel_display_name

    async def read_range(
        self,
        *,
        trigger: SlackConversationHistoryTrigger,
        bot_token: str,
        exclusive_start_position: str | None,
        deadline: ExternalChannelOperationDeadline,
    ) -> ExternalChannelHistoryRange[SlackNormalizedMessage]:
        result: object = await self.range_call(
            trigger=trigger,
            bot_token=bot_token,
            exclusive_start_position=exclusive_start_position,
            deadline=deadline,
        )
        return _history_range(result, SlackNormalizedMessage)

    async def get_permalink(
        self, *, bot_token: str, channel_id: str, message_ts: str
    ) -> str | None:
        result: object = await self.permalink_call(
            bot_token=bot_token, channel_id=channel_id, message_ts=message_ts
        )
        assert result is None or isinstance(result, str)
        return result

    async def fetch_user_display_name(
        self, *, bot_token: str, provider_user_id: str
    ) -> str | None:
        result: object = await self.user_call(
            bot_token=bot_token, provider_user_id=provider_user_id
        )
        assert result is None or isinstance(result, str)
        return result

    async def fetch_channel_display_name(
        self, *, bot_token: str, channel_id: str
    ) -> str | None:
        result: object = await self.channel_call(
            bot_token=bot_token, channel_id=channel_id
        )
        assert result is None or isinstance(result, str)
        return result


class _DiscordClient(DiscordConversationHistoryClient):
    def __init__(self, *, read_range: AsyncMock) -> None:
        self.range_call = read_range

    async def read_range(
        self,
        *,
        trigger: DiscordConversationHistoryTrigger,
        bot_token: str,
        exclusive_start_position: str | None,
        deadline: ExternalChannelOperationDeadline,
    ) -> ExternalChannelHistoryRange[DiscordNormalizedMessage]:
        result: object = await self.range_call(
            trigger=trigger,
            bot_token=bot_token,
            exclusive_start_position=exclusive_start_position,
            deadline=deadline,
        )
        return _history_range(result, DiscordNormalizedMessage)


class _Cipher(CredentialCipher):
    def __init__(
        self, decrypt: Callable[[str], ExternalChannelConnectionCredentials]
    ) -> None:
        super().__init__(Fernet.generate_key().decode())
        self.decode_credentials = decrypt

    def decrypt(self, ciphertext: str) -> str:
        return self.decode_credentials(ciphertext).model_dump_json()


def _codec(
    *, decrypt: Callable[[str], ExternalChannelConnectionCredentials]
) -> ExternalChannelCredentialsCodec:
    return ExternalChannelCredentialsCodec(cipher=_Cipher(decrypt))


class _SessionContext(AbstractAsyncContextManager[AsyncSession]):
    def __init__(self) -> None:
        self.session = AsyncSession()

    async def __aenter__(self) -> AsyncSession:
        return self.session

    async def __aexit__(self, *args: object) -> None:
        await self.session.close()
        return None


class _SessionManager:
    def __call__(self) -> AbstractAsyncContextManager[AsyncSession]:
        return _SessionContext()


def _deadline(seconds: float = 30) -> ExternalChannelOperationDeadline:
    return ExternalChannelOperationDeadline(
        datetime.datetime.now(datetime.UTC) + datetime.timedelta(seconds=seconds)
    )


def _slack_message() -> SlackNormalizedMessage:
    return SlackNormalizedMessage(
        tenant_id="tenant-1",
        channel_id="channel-1",
        root_thread_ts="1.000000",
        message_ts="2.000000",
        correlation_key="tenant-1:channel-1:1.000000",
        provider_resource_key="slack:tenant-1:channel-1:1.000000",
        provider_message_key="slack:tenant-1:channel-1:2.000000",
        provider_position="00000000000000000002",
        revision_key="2.000000:original",
        revision_kind=ExternalChannelMessageRevisionKind.ORIGINAL,
        lifecycle=ExternalChannelMessageLifecycle.CURRENT,
        author_type=ExternalChannelPrincipalAuthorType.HUMAN,
        provider_user_id="participant-1",
        normalized_body="Slack history body",
        attachment_metadata=None,
        normalized_size=18,
        provider_created_at=datetime.datetime(2026, 7, 29, tzinfo=datetime.UTC),
        provider_updated_at=None,
        invocation=True,
        source_event_type="app_mention",
    )


def _discord_message() -> DiscordNormalizedMessage:
    return DiscordNormalizedMessage(
        tenant_id="100",
        channel_id="300",
        thread_id="300",
        parent_channel_id="200",
        message_id="2",
        provider_message_key="discord:100:2",
        provider_position="00000000000000000002",
        revision_key="2:original",
        revision_kind=ExternalChannelMessageRevisionKind.ORIGINAL,
        lifecycle=ExternalChannelMessageLifecycle.CURRENT,
        author_type=ExternalChannelPrincipalAuthorType.HUMAN,
        provider_user_id="participant-1",
        sender_display_name="Participant",
        normalized_body="Discord history body",
        attachment_metadata=None,
        reference_mappings={"users": {"participant-1": "Participant"}},
        channel_display_name="thread",
        normalized_size=20,
        provider_created_at=datetime.datetime(2026, 7, 29, tzinfo=datetime.UTC),
        provider_updated_at=None,
        invocation=False,
    )


def _file_metadata(provider: ExternalChannelProvider) -> dict[str, object]:
    """Build the minimal file projection needed for count validation."""
    return {"files": [{"provider": provider.value}]}


async def test_slack_history_uses_native_trigger_and_returns_canonical_messages() -> (
    None
):
    message = dataclasses.replace(
        _slack_message(),
        normalized_body="Slack history body for <@UREVIEWER> in <#CRELATED>",
        attachment_metadata=_file_metadata(ExternalChannelProvider.SLACK),
        normalized_size=49,
    )
    slack_client = _SlackClient(
        read_range=AsyncMock(
            return_value=ExternalChannelHistoryRange(
                messages=(message,),
                trigger=message,
                context_omitted=False,
                range_start_position="00000000000000000001",
                trigger_position=message.provider_position,
                provider_request_count=1,
                scanned_message_count=1,
                elapsed_seconds=0,
            )
        ),
        get_permalink=AsyncMock(
            return_value="https://example.slack.com/archives/channel-1/p2000000"
        ),
        fetch_user_display_name=AsyncMock(
            side_effect=lambda *, bot_token, provider_user_id: {
                "participant-1": "Participant",
                "UREVIEWER": "Reviewer",
            }[provider_user_id]
        ),
        fetch_channel_display_name=AsyncMock(return_value="#related"),
    )
    repository = _Repository(
        get_connection_configuration=AsyncMock(
            return_value=_configuration(
                provider=ExternalChannelProvider.SLACK,
                provider_tenant_id="tenant-1",
                provider_bot_user_id="connected-bot",
                provider_app_id="connected-app",
                encrypted_credentials="ciphertext",
            )
        )
    )
    codec = _codec(
        decrypt=lambda ciphertext: SlackConnectionCredentials(
            bot_token="secret-bot-token",
            signing_secret="secret-signing-key",
            app_token=None,
        )
    )
    reader = ExternalChannelProviderHistoryReader(
        session_manager=_SessionManager(),
        repository=repository,
        credentials_codec=codec,
        slack_client=slack_client,
        discord_client=create_autospec(
            DiscordConversationHistoryClient, instance=True, spec_set=True
        ),
    )
    locator = ExternalChannelTriggerLocator(
        connection_id="connection-1",
        provider=ExternalChannelProvider.SLACK,
        provider_event_type="app_mention",
        provider_tenant_id="tenant-1",
        provider_channel_id="channel-1",
        provider_parent_channel_id=None,
        provider_thread_key="1.000000",
        delivery_thread_key="1.000000",
        provider_resource_key=message.provider_resource_key,
        trigger_provider_message_key=message.provider_message_key,
        trigger_provider_message_id="2.000000",
        trigger_position=message.provider_position,
        provider_user_id="participant-1",
        invocation=True,
        expected_file_count=1,
    )

    history = await reader.read_range(
        locator=locator,
        exclusive_start_position="00000000000000000001",
        deadline=_deadline(),
    )

    assert slack_client.range_call.await_args is not None
    read_range_call = slack_client.range_call.await_args.kwargs
    assert read_range_call["trigger"].trigger_message_ts == "2.000000"
    assert read_range_call["trigger"].root_thread_ts == "1.000000"
    assert read_range_call["bot_token"] == "secret-bot-token"
    assert history.trigger.normalized_body == (
        "Slack history body for <@UREVIEWER> in <#CRELATED>"
    )
    assert history.trigger.provider_message_key == message.provider_message_key
    assert history.trigger.reference_mappings == {
        "users": {
            "UREVIEWER": "Reviewer",
            "participant-1": "Participant",
        },
        "channels": {"CRELATED": "#related"},
    }
    assert history.trigger.sender_display_name == "Participant"
    assert history.trigger.normalized_size == message.normalized_size + (
        provider_reference_mappings_size(
            users={
                "UREVIEWER": "Reviewer",
                "participant-1": "Participant",
            },
            channels={"CRELATED": "#related"},
        )
    )
    assert history.messages[0].reference_mappings == history.trigger.reference_mappings
    assert history.messages[0].sender_display_name == "Participant"
    assert (
        history.trigger.original_url
        == "https://example.slack.com/archives/channel-1/p2000000"
    )
    assert history.messages[0].original_url == history.trigger.original_url
    slack_client.permalink_call.assert_awaited_once_with(
        bot_token="secret-bot-token",
        channel_id="channel-1",
        message_ts="2.000000",
    )
    slack_client.user_call.assert_has_awaits(
        [
            call(
                bot_token="secret-bot-token",
                provider_user_id="UREVIEWER",
            ),
            call(
                bot_token="secret-bot-token",
                provider_user_id="participant-1",
            ),
        ],
        any_order=True,
    )
    slack_client.channel_call.assert_awaited_once_with(
        bot_token="secret-bot-token",
        channel_id="CRELATED",
    )


async def test_slack_history_resolves_visible_bot_author_display_name() -> None:
    """A provider-visible non-connected bot is context with a readable sender name."""
    message = dataclasses.replace(
        _slack_message(),
        author_type=ExternalChannelPrincipalAuthorType.BOT,
        provider_user_id="bot:BVISIBLE",
        normalized_body="Deployment completed.",
    )
    slack_client = _SlackClient(
        read_range=AsyncMock(
            return_value=ExternalChannelHistoryRange(
                messages=(message,),
                trigger=message,
                context_omitted=False,
                range_start_position=None,
                trigger_position=message.provider_position,
                provider_request_count=1,
                scanned_message_count=1,
                elapsed_seconds=0,
            )
        ),
        get_permalink=AsyncMock(return_value=None),
        fetch_user_display_name=AsyncMock(return_value="Deploy Bot"),
        fetch_channel_display_name=AsyncMock(),
    )
    repository = _Repository(
        get_connection_configuration=AsyncMock(
            return_value=_configuration(
                provider=ExternalChannelProvider.SLACK,
                provider_tenant_id="tenant-1",
                provider_bot_user_id="connected-bot",
                provider_app_id="connected-app",
                encrypted_credentials="ciphertext",
            )
        )
    )
    reader = ExternalChannelProviderHistoryReader(
        session_manager=_SessionManager(),
        repository=repository,
        credentials_codec=_codec(
            decrypt=lambda ciphertext: SlackConnectionCredentials(
                bot_token="secret-bot-token",
                signing_secret="secret-signing-key",
                app_token=None,
            )
        ),
        slack_client=slack_client,
        discord_client=create_autospec(
            DiscordConversationHistoryClient, instance=True, spec_set=True
        ),
    )
    locator = ExternalChannelTriggerLocator(
        connection_id="connection-1",
        provider=ExternalChannelProvider.SLACK,
        provider_event_type="app_mention",
        provider_tenant_id="tenant-1",
        provider_channel_id="channel-1",
        provider_parent_channel_id=None,
        provider_thread_key="1.000000",
        delivery_thread_key="1.000000",
        provider_resource_key=message.provider_resource_key,
        trigger_provider_message_key=message.provider_message_key,
        trigger_provider_message_id="2.000000",
        trigger_position=message.provider_position,
        provider_user_id="participant-1",
        invocation=False,
        expected_file_count=None,
    )

    history = await reader.read_range(
        locator=locator,
        exclusive_start_position=None,
        deadline=_deadline(),
    )

    assert history.trigger.author_type is ExternalChannelPrincipalAuthorType.BOT
    assert history.trigger.sender_display_name == "Deploy Bot"
    assert history.trigger.reference_mappings == {
        "users": {"bot:BVISIBLE": "Deploy Bot"}
    }
    slack_client.user_call.assert_awaited_once_with(
        bot_token="secret-bot-token",
        provider_user_id="bot:BVISIBLE",
    )
    slack_client.channel_call.assert_not_awaited()


async def test_slack_history_skips_optional_enrichment_inside_required_reserve() -> (
    None
):
    """Optional Slack lookups do not consume the required admission reserve."""
    message = _slack_message()
    slack_client = _SlackClient(
        read_range=AsyncMock(
            return_value=ExternalChannelHistoryRange(
                messages=(message,),
                trigger=message,
                context_omitted=False,
                range_start_position=None,
                trigger_position=message.provider_position,
                provider_request_count=1,
                scanned_message_count=1,
                elapsed_seconds=0,
            )
        ),
        get_permalink=AsyncMock(return_value="https://example.invalid/source"),
        fetch_user_display_name=AsyncMock(return_value="Participant"),
        fetch_channel_display_name=AsyncMock(return_value="#related"),
    )
    repository = _Repository(
        get_connection_configuration=AsyncMock(
            return_value=_configuration(
                provider=ExternalChannelProvider.SLACK,
                provider_tenant_id="tenant-1",
                provider_bot_user_id="connected-bot",
                provider_app_id="connected-app",
                encrypted_credentials="ciphertext",
            )
        )
    )
    reader = ExternalChannelProviderHistoryReader(
        session_manager=_SessionManager(),
        repository=repository,
        credentials_codec=_codec(
            decrypt=lambda ciphertext: SlackConnectionCredentials(
                bot_token="secret-bot-token",
                signing_secret="secret-signing-key",
                app_token=None,
            )
        ),
        slack_client=slack_client,
        discord_client=create_autospec(
            DiscordConversationHistoryClient, instance=True, spec_set=True
        ),
    )
    locator = ExternalChannelTriggerLocator(
        connection_id="connection-1",
        provider=ExternalChannelProvider.SLACK,
        provider_event_type="app_mention",
        provider_tenant_id="tenant-1",
        provider_channel_id="channel-1",
        provider_parent_channel_id=None,
        provider_thread_key="1.000000",
        delivery_thread_key="1.000000",
        provider_resource_key=message.provider_resource_key,
        trigger_provider_message_key=message.provider_message_key,
        trigger_provider_message_id="2.000000",
        trigger_position=message.provider_position,
        provider_user_id="participant-1",
        invocation=True,
        expected_file_count=None,
    )

    history = await reader.read_range(
        locator=locator,
        exclusive_start_position=None,
        deadline=_deadline(0.5),
    )

    assert history.trigger.sender_display_name is None
    assert history.trigger.original_url is None
    slack_client.user_call.assert_not_awaited()
    slack_client.channel_call.assert_not_awaited()
    slack_client.permalink_call.assert_not_awaited()


async def test_discord_history_preserves_reference_mappings() -> None:
    message = dataclasses.replace(
        _discord_message(),
        attachment_metadata=_file_metadata(ExternalChannelProvider.DISCORD),
    )
    discord_client = _DiscordClient(
        read_range=AsyncMock(
            return_value=ExternalChannelHistoryRange(
                messages=(message,),
                trigger=message,
                context_omitted=True,
                range_start_position=None,
                trigger_position=message.provider_position,
                provider_request_count=2,
                scanned_message_count=21,
                elapsed_seconds=0,
            )
        )
    )
    repository = _Repository(
        get_connection_configuration=AsyncMock(
            return_value=_configuration(
                provider=ExternalChannelProvider.DISCORD,
                provider_tenant_id="100",
                provider_bot_user_id="connected-bot",
                provider_app_id="connected-app",
                encrypted_credentials="ciphertext",
            )
        )
    )
    reader = ExternalChannelProviderHistoryReader(
        session_manager=_SessionManager(),
        repository=repository,
        credentials_codec=_codec(
            decrypt=lambda ciphertext: DiscordConnectionCredentials(
                bot_token="secret-bot-token"
            )
        ),
        slack_client=create_autospec(
            SlackConversationClient, instance=True, spec_set=True
        ),
        discord_client=discord_client,
    )
    locator = ExternalChannelTriggerLocator(
        connection_id="connection-1",
        provider=ExternalChannelProvider.DISCORD,
        provider_event_type="discord_message_create",
        provider_tenant_id="100",
        provider_channel_id="300",
        provider_parent_channel_id="200",
        provider_thread_key="300",
        delivery_thread_key="300",
        provider_resource_key="discord:100:300",
        trigger_provider_message_key=message.provider_message_key,
        trigger_provider_message_id="2",
        trigger_position=message.provider_position,
        provider_user_id="participant-1",
        invocation=False,
        expected_file_count=1,
    )

    history = await reader.read_range(
        locator=locator,
        exclusive_start_position=None,
        deadline=_deadline(),
    )

    assert discord_client.range_call.await_args is not None
    read_range_call = discord_client.range_call.await_args.kwargs
    assert read_range_call["trigger"].source_channel_id == "200"
    assert read_range_call["trigger"].conversation_channel_id == "300"
    assert read_range_call["trigger"].trigger_message_id == "2"
    assert history.context_omitted is True
    assert history.trigger.reference_mappings == {
        "users": {"participant-1": "Participant"}
    }
    assert history.trigger.original_url == "https://discord.com/channels/100/300/2"


async def test_slack_history_retries_when_callback_file_is_not_visible() -> None:
    """A Slack history snapshot missing a callback-observed file is temporary."""
    message = _slack_message()
    slack_client = _SlackClient(
        read_range=AsyncMock(
            return_value=ExternalChannelHistoryRange(
                messages=(message,),
                trigger=message,
                context_omitted=False,
                range_start_position=None,
                trigger_position=message.provider_position,
                provider_request_count=1,
                scanned_message_count=1,
                elapsed_seconds=0,
            )
        ),
        get_permalink=AsyncMock(return_value=None),
        fetch_user_display_name=AsyncMock(return_value=None),
        fetch_channel_display_name=AsyncMock(return_value=None),
    )
    reader = ExternalChannelProviderHistoryReader(
        session_manager=_SessionManager(),
        repository=_Repository(
            get_connection_configuration=AsyncMock(
                return_value=_configuration(
                    provider=ExternalChannelProvider.SLACK,
                    provider_tenant_id="tenant-1",
                    provider_bot_user_id="connected-bot",
                    provider_app_id="connected-app",
                    encrypted_credentials="ciphertext",
                )
            ),
        ),
        credentials_codec=_codec(
            decrypt=lambda ciphertext: SlackConnectionCredentials(
                bot_token="secret-bot-token",
                signing_secret="secret-signing-key",
                app_token=None,
            )
        ),
        slack_client=slack_client,
        discord_client=create_autospec(
            DiscordConversationHistoryClient, instance=True, spec_set=True
        ),
    )
    locator = ExternalChannelTriggerLocator(
        connection_id="connection-1",
        provider=ExternalChannelProvider.SLACK,
        provider_event_type="app_mention",
        provider_tenant_id="tenant-1",
        provider_channel_id="channel-1",
        provider_parent_channel_id=None,
        provider_thread_key="1.000000",
        delivery_thread_key="1.000000",
        provider_resource_key=message.provider_resource_key,
        trigger_provider_message_key=message.provider_message_key,
        trigger_provider_message_id="2.000000",
        trigger_position=message.provider_position,
        provider_user_id="participant-1",
        invocation=True,
        expected_file_count=1,
    )

    with pytest.raises(
        ExternalChannelHistoryTemporaryFailure,
        match="has not exposed all trigger files yet",
    ):
        await reader.read_range(
            locator=locator,
            exclusive_start_position=None,
            deadline=_deadline(),
        )


async def test_discord_history_retries_when_callback_file_is_not_visible() -> None:
    """A Discord history snapshot missing a callback-observed file is temporary."""
    message = _discord_message()
    discord_client = _DiscordClient(
        read_range=AsyncMock(
            return_value=ExternalChannelHistoryRange(
                messages=(message,),
                trigger=message,
                context_omitted=False,
                range_start_position=None,
                trigger_position=message.provider_position,
                provider_request_count=1,
                scanned_message_count=1,
                elapsed_seconds=0,
            )
        )
    )
    reader = ExternalChannelProviderHistoryReader(
        session_manager=_SessionManager(),
        repository=_Repository(
            get_connection_configuration=AsyncMock(
                return_value=_configuration(
                    provider=ExternalChannelProvider.DISCORD,
                    provider_tenant_id="100",
                    provider_bot_user_id="connected-bot",
                    provider_app_id="connected-app",
                    encrypted_credentials="ciphertext",
                )
            ),
        ),
        credentials_codec=_codec(
            decrypt=lambda ciphertext: DiscordConnectionCredentials(
                bot_token="secret-bot-token"
            )
        ),
        slack_client=create_autospec(
            SlackConversationClient, instance=True, spec_set=True
        ),
        discord_client=discord_client,
    )
    locator = ExternalChannelTriggerLocator(
        connection_id="connection-1",
        provider=ExternalChannelProvider.DISCORD,
        provider_event_type="discord_message_create",
        provider_tenant_id="100",
        provider_channel_id="300",
        provider_parent_channel_id="200",
        provider_thread_key="300",
        delivery_thread_key="300",
        provider_resource_key="discord:100:300",
        trigger_provider_message_key=message.provider_message_key,
        trigger_provider_message_id="2",
        trigger_position=message.provider_position,
        provider_user_id="participant-1",
        invocation=False,
        expected_file_count=1,
    )

    with pytest.raises(
        ExternalChannelHistoryTemporaryFailure,
        match="has not exposed all trigger files yet",
    ):
        await reader.read_range(
            locator=locator,
            exclusive_start_position=None,
            deadline=_deadline(),
        )
