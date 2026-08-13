"""Tests for provider-backed canonical ingestion history."""

import dataclasses
import datetime
from contextlib import AbstractAsyncContextManager
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import AsyncMock, call

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from azents.core.enums import (
    ExternalChannelMessageLifecycle,
    ExternalChannelMessageRevisionKind,
    ExternalChannelPrincipalAuthorType,
    ExternalChannelProvider,
)
from azents.core.external_channel_reference import provider_reference_mappings_size
from azents.services.external_channel.conversation import (
    ExternalChannelHistoryRange,
    ExternalChannelHistoryTemporaryFailure,
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
        fetch_user_display_name=AsyncMock(
            side_effect=lambda *, bot_token, provider_user_id: {
                "participant-1": "Participant",
                "UREVIEWER": "Reviewer",
            }[provider_user_id]
        ),
        fetch_channel_display_name=AsyncMock(return_value="#related"),
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

    read_range_call = slack_client.read_range.await_args.kwargs
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
    slack_client.get_permalink.assert_awaited_once_with(
        bot_token="secret-bot-token",
        channel_id="channel-1",
        message_ts="2.000000",
    )
    slack_client.fetch_user_display_name.assert_has_awaits(
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
    slack_client.fetch_channel_display_name.assert_awaited_once_with(
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
    slack_client = SimpleNamespace(
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
    reader = ExternalChannelProviderHistoryReader(
        session_manager=cast(Any, _SessionManager()),
        repository=cast(Any, repository),
        credentials_codec=cast(
            Any,
            SimpleNamespace(
                decrypt=lambda ciphertext: SlackConnectionCredentials(
                    bot_token="secret-bot-token",
                    signing_secret="secret-signing-key",
                    app_token=None,
                )
            ),
        ),
        slack_client=cast(Any, slack_client),
        discord_client=cast(Any, SimpleNamespace()),
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
    slack_client.fetch_user_display_name.assert_awaited_once_with(
        bot_token="secret-bot-token",
        provider_user_id="bot:BVISIBLE",
    )
    slack_client.fetch_channel_display_name.assert_not_awaited()


async def test_slack_history_skips_optional_enrichment_inside_required_reserve() -> (
    None
):
    """Optional Slack lookups do not consume the required admission reserve."""
    message = _slack_message()
    slack_client = SimpleNamespace(
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
    reader = ExternalChannelProviderHistoryReader(
        session_manager=cast(Any, _SessionManager()),
        repository=cast(Any, repository),
        credentials_codec=cast(
            Any,
            SimpleNamespace(
                decrypt=lambda ciphertext: SlackConnectionCredentials(
                    bot_token="secret-bot-token",
                    signing_secret="secret-signing-key",
                    app_token=None,
                )
            ),
        ),
        slack_client=cast(Any, slack_client),
        discord_client=cast(Any, SimpleNamespace()),
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
    slack_client.fetch_user_display_name.assert_not_awaited()
    slack_client.fetch_channel_display_name.assert_not_awaited()
    slack_client.get_permalink.assert_not_awaited()


async def test_discord_history_preserves_reference_mappings() -> None:
    message = dataclasses.replace(
        _discord_message(),
        attachment_metadata=_file_metadata(ExternalChannelProvider.DISCORD),
    )
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

    read_range_call = discord_client.read_range.await_args.kwargs
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
    slack_client = SimpleNamespace(
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
        session_manager=cast(Any, _SessionManager()),
        repository=cast(
            Any,
            SimpleNamespace(
                get_connection_configuration=AsyncMock(
                    return_value=SimpleNamespace(
                        provider=ExternalChannelProvider.SLACK,
                        provider_tenant_id="tenant-1",
                        provider_bot_user_id="connected-bot",
                        provider_app_id="connected-app",
                        encrypted_credentials="ciphertext",
                    )
                )
            ),
        ),
        credentials_codec=cast(
            Any,
            SimpleNamespace(
                decrypt=lambda ciphertext: SlackConnectionCredentials(
                    bot_token="secret-bot-token",
                    signing_secret="secret-signing-key",
                    app_token=None,
                )
            ),
        ),
        slack_client=cast(Any, slack_client),
        discord_client=cast(Any, SimpleNamespace()),
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
    discord_client = SimpleNamespace(
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
        session_manager=cast(Any, _SessionManager()),
        repository=cast(
            Any,
            SimpleNamespace(
                get_connection_configuration=AsyncMock(
                    return_value=SimpleNamespace(
                        provider=ExternalChannelProvider.DISCORD,
                        provider_tenant_id="100",
                        provider_bot_user_id="connected-bot",
                        provider_app_id="connected-app",
                        encrypted_credentials="ciphertext",
                    )
                )
            ),
        ),
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
