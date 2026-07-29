"""Tests for provider-backed canonical ingestion history."""

import datetime
from contextlib import AbstractAsyncContextManager
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import AsyncMock

from sqlalchemy.ext.asyncio import AsyncSession

from azents.core.enums import (
    ExternalChannelMessageLifecycle,
    ExternalChannelMessageRevisionKind,
    ExternalChannelPrincipalAuthorType,
    ExternalChannelProvider,
)
from azents.services.external_channel.conversation import (
    ExternalChannelHistoryRange,
    ExternalChannelOperationDeadline,
)
from azents.services.external_channel.data import (
    DiscordConnectionCredentials,
    SlackConnectionCredentials,
)
from azents.services.external_channel.discord_events import DiscordNormalizedMessage
from azents.services.external_channel.ingestion import ExternalChannelTriggerLocator
from azents.services.external_channel.ingestion_history import (
    ExternalChannelProviderHistoryReader,
)
from azents.services.external_channel.slack_events import SlackNormalizedMessage


class _SessionContext(AbstractAsyncContextManager[AsyncSession]):
    async def __aenter__(self) -> AsyncSession:
        return cast(AsyncSession, SimpleNamespace())

    async def __aexit__(self, *args: object) -> None:
        return None


class _SessionManager:
    def __call__(self) -> AbstractAsyncContextManager[AsyncSession]:
        return _SessionContext()


def _deadline() -> ExternalChannelOperationDeadline:
    return ExternalChannelOperationDeadline(
        datetime.datetime.now(datetime.UTC) + datetime.timedelta(seconds=30)
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


async def test_slack_history_uses_native_trigger_and_returns_canonical_messages() -> (
    None
):
    message = _slack_message()
    slack_client = SimpleNamespace(
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
    )
    repository = SimpleNamespace(
        get_connection_configuration=AsyncMock(
            return_value=SimpleNamespace(
                provider=ExternalChannelProvider.SLACK,
                provider_tenant_id="tenant-1",
                provider_bot_user_id="connected-bot",
                provider_app_id="connected-app",
                encrypted_credentials="ciphertext",
            )
        )
    )
    codec = SimpleNamespace(
        decrypt=lambda ciphertext: SlackConnectionCredentials(
            bot_token="secret-bot-token",
            signing_secret="secret-signing-key",
            app_token=None,
        )
    )
    reader = ExternalChannelProviderHistoryReader(
        session_manager=cast(Any, _SessionManager()),
        repository=cast(Any, repository),
        credentials_codec=cast(Any, codec),
        slack_client=cast(Any, slack_client),
        discord_client=cast(Any, SimpleNamespace()),
    )
    locator = ExternalChannelTriggerLocator(
        connection_id="connection-1",
        provider=ExternalChannelProvider.SLACK,
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
    )

    history = await reader.read_range(
        locator=locator,
        exclusive_start_position="00000000000000000001",
        deadline=_deadline(),
    )

    call = slack_client.read_range.await_args.kwargs
    assert call["trigger"].trigger_message_ts == "2.000000"
    assert call["trigger"].root_thread_ts == "1.000000"
    assert call["bot_token"] == "secret-bot-token"
    assert history.trigger.normalized_body == "Slack history body"
    assert history.trigger.provider_message_key == message.provider_message_key
    assert (
        history.trigger.original_url
        == "https://example.slack.com/archives/channel-1/p2000000"
    )
    assert history.messages[0].original_url == history.trigger.original_url
    slack_client.get_permalink.assert_awaited_once_with(
        bot_token="secret-bot-token",
        channel_id="channel-1",
        message_ts="2.000000",
    )


async def test_discord_history_preserves_reference_mappings() -> None:
    message = _discord_message()
    discord_client = SimpleNamespace(
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
    repository = SimpleNamespace(
        get_connection_configuration=AsyncMock(
            return_value=SimpleNamespace(
                provider=ExternalChannelProvider.DISCORD,
                provider_tenant_id="100",
                provider_bot_user_id="connected-bot",
                provider_app_id="connected-app",
                encrypted_credentials="ciphertext",
            )
        )
    )
    reader = ExternalChannelProviderHistoryReader(
        session_manager=cast(Any, _SessionManager()),
        repository=cast(Any, repository),
        credentials_codec=cast(
            Any,
            SimpleNamespace(
                decrypt=lambda ciphertext: DiscordConnectionCredentials(
                    bot_token="secret-bot-token"
                )
            ),
        ),
        slack_client=cast(Any, SimpleNamespace()),
        discord_client=cast(Any, discord_client),
    )
    locator = ExternalChannelTriggerLocator(
        connection_id="connection-1",
        provider=ExternalChannelProvider.DISCORD,
        provider_tenant_id="100",
        provider_channel_id="200",
        provider_parent_channel_id="200",
        provider_thread_key="300",
        delivery_thread_key="300",
        provider_resource_key="discord:100:300",
        trigger_provider_message_key=message.provider_message_key,
        trigger_provider_message_id="2",
        trigger_position=message.provider_position,
        provider_user_id="participant-1",
        invocation=False,
    )

    history = await reader.read_range(
        locator=locator,
        exclusive_start_position=None,
        deadline=_deadline(),
    )

    call = discord_client.read_range.await_args.kwargs
    assert call["trigger"].conversation_channel_id == "300"
    assert call["trigger"].trigger_message_id == "2"
    assert history.context_omitted is True
    assert history.trigger.reference_mappings == {
        "users": {"participant-1": "Participant"}
    }
    assert history.trigger.original_url == "https://discord.com/channels/100/300/2"
