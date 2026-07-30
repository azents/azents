"""Provider-backed canonical history reader for synchronous ingestion."""

from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Annotated

import httpx
from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from azents.core.enums import ExternalChannelProvider
from azents.rdb.deps import get_session_manager
from azents.rdb.session import SessionManager
from azents.repos.external_channel.repository import ExternalChannelRepository
from azents.services.external_channel.connection import (
    get_external_channel_credentials_codec,
)
from azents.services.external_channel.conversation import (
    ExternalChannelHistoryCredentialsInvalid,
    ExternalChannelHistoryRange,
    ExternalChannelOperationDeadline,
)
from azents.services.external_channel.credentials import ExternalChannelCredentialsCodec
from azents.services.external_channel.data import (
    DiscordConnectionCredentials,
    SlackConnectionCredentials,
)
from azents.services.external_channel.discord_events import DiscordNormalizedMessage
from azents.services.external_channel.discord_history import (
    DiscordConversationHistoryClient,
    DiscordConversationHistoryTrigger,
)
from azents.services.external_channel.ingestion import (
    ExternalChannelCanonicalHistoryMessage,
    ExternalChannelTriggerLocator,
)
from azents.services.external_channel.slack_events import (
    SlackConversationClient,
    SlackConversationHistoryTrigger,
    SlackNormalizedMessage,
)
from azents.services.external_channel.slack_sdk_client import create_slack_web_client


async def get_ingestion_slack_http_client() -> AsyncIterator[httpx.AsyncClient]:
    """Provide bounded HTTP transport for synchronous Slack history."""
    async with httpx.AsyncClient(timeout=20.0) as client:
        yield client


def get_ingestion_slack_conversation_client(
    http_client: Annotated[
        httpx.AsyncClient,
        Depends(get_ingestion_slack_http_client),
    ],
) -> SlackConversationClient:
    """Provide the shared bounded Slack history client."""
    return SlackConversationClient(
        web_client=create_slack_web_client(),
        http_client=http_client,
    )


async def get_ingestion_discord_http_client() -> AsyncIterator[httpx.AsyncClient]:
    """Provide bounded HTTP transport for synchronous Discord history."""
    async with httpx.AsyncClient(timeout=20.0) as client:
        yield client


def get_ingestion_discord_conversation_client(
    http_client: Annotated[
        httpx.AsyncClient,
        Depends(get_ingestion_discord_http_client),
    ],
) -> DiscordConversationHistoryClient:
    """Provide the shared bounded Discord history client."""
    return DiscordConversationHistoryClient(http_client)


@dataclass
class ExternalChannelProviderHistoryReader:
    """Read provider history and return one provider-neutral canonical range."""

    session_manager: Annotated[
        SessionManager[AsyncSession],
        Depends(get_session_manager),
    ]
    repository: Annotated[
        ExternalChannelRepository,
        Depends(ExternalChannelRepository),
    ]
    credentials_codec: Annotated[
        ExternalChannelCredentialsCodec,
        Depends(get_external_channel_credentials_codec),
    ]
    slack_client: Annotated[
        SlackConversationClient,
        Depends(get_ingestion_slack_conversation_client),
    ]
    discord_client: Annotated[
        DiscordConversationHistoryClient,
        Depends(get_ingestion_discord_conversation_client),
    ]

    async def read_range(
        self,
        *,
        locator: ExternalChannelTriggerLocator,
        exclusive_start_position: str | None,
        deadline: ExternalChannelOperationDeadline,
    ) -> ExternalChannelHistoryRange[ExternalChannelCanonicalHistoryMessage]:
        """Read one exact-trigger range without retaining credentials or raw pages."""
        async with self.session_manager() as session:
            configuration = await self.repository.get_connection_configuration(
                session,
                connection_id=locator.connection_id,
            )
        if (
            configuration is None
            or configuration.provider is not locator.provider
            or configuration.provider_tenant_id != locator.provider_tenant_id
            or configuration.encrypted_credentials is None
        ):
            raise ExternalChannelHistoryCredentialsInvalid(
                "External Channel history credentials are unavailable."
            )
        credentials = self.credentials_codec.decrypt(
            configuration.encrypted_credentials
        )
        if locator.provider is ExternalChannelProvider.SLACK:
            if not isinstance(credentials, SlackConnectionCredentials):
                raise ExternalChannelHistoryCredentialsInvalid(
                    "External Channel history credentials are invalid."
                )
            history = await self.slack_client.read_range(
                trigger=SlackConversationHistoryTrigger(
                    tenant_id=locator.provider_tenant_id,
                    channel_id=locator.provider_channel_id,
                    trigger_message_ts=locator.trigger_provider_message_id,
                    root_thread_ts=locator.provider_thread_key,
                    connected_bot_user_id=configuration.provider_bot_user_id,
                    connected_app_id=configuration.provider_app_id,
                ),
                bot_token=credentials.bot_token,
                exclusive_start_position=exclusive_start_position,
                deadline=deadline,
            )
            messages = tuple(_canonical_slack(message) for message in history.messages)
            trigger = _canonical_slack(history.trigger)
        else:
            if not isinstance(credentials, DiscordConnectionCredentials):
                raise ExternalChannelHistoryCredentialsInvalid(
                    "External Channel history credentials are invalid."
                )
            history = await self.discord_client.read_range(
                trigger=DiscordConversationHistoryTrigger(
                    guild_id=locator.provider_tenant_id,
                    source_channel_id=locator.provider_channel_id,
                    conversation_channel_id=(
                        locator.provider_thread_key or locator.provider_channel_id
                    ),
                    trigger_message_id=locator.trigger_provider_message_id,
                    connected_bot_user_id=configuration.provider_bot_user_id,
                ),
                bot_token=credentials.bot_token,
                exclusive_start_position=exclusive_start_position,
                deadline=deadline,
            )
            messages = tuple(
                _canonical_discord(message) for message in history.messages
            )
            trigger = _canonical_discord(history.trigger)
        return ExternalChannelHistoryRange(
            messages=messages,
            trigger=trigger,
            context_omitted=history.context_omitted,
            range_start_position=history.range_start_position,
            trigger_position=history.trigger_position,
            provider_request_count=history.provider_request_count,
            scanned_message_count=history.scanned_message_count,
            elapsed_seconds=history.elapsed_seconds,
        )


def _canonical_slack(
    message: SlackNormalizedMessage,
) -> ExternalChannelCanonicalHistoryMessage:
    """Convert one normalized Slack history item without a raw event dependency."""
    return ExternalChannelCanonicalHistoryMessage(
        provider_message_key=message.provider_message_key,
        provider_position=message.provider_position,
        revision_key=message.revision_key,
        revision_kind=message.revision_kind,
        lifecycle=message.lifecycle,
        author_type=message.author_type,
        provider_user_id=message.provider_user_id,
        sender_display_name=None,
        normalized_body=message.normalized_body,
        attachment_metadata=message.attachment_metadata,
        reference_mappings=None,
        normalized_size=message.normalized_size,
        provider_created_at=message.provider_created_at,
        provider_updated_at=message.provider_updated_at,
        original_url=None,
    )


def _canonical_discord(
    message: DiscordNormalizedMessage,
) -> ExternalChannelCanonicalHistoryMessage:
    """Convert one normalized Discord history item without a raw event dependency."""
    reference_mappings: dict[str, object] = {
        key: value for key, value in message.reference_mappings.items()
    }
    return ExternalChannelCanonicalHistoryMessage(
        provider_message_key=message.provider_message_key,
        provider_position=message.provider_position,
        revision_key=message.revision_key,
        revision_kind=message.revision_kind,
        lifecycle=message.lifecycle,
        author_type=message.author_type,
        provider_user_id=message.provider_user_id,
        sender_display_name=message.sender_display_name,
        normalized_body=message.normalized_body,
        attachment_metadata=message.attachment_metadata,
        reference_mappings=reference_mappings,
        normalized_size=message.normalized_size,
        provider_created_at=message.provider_created_at,
        provider_updated_at=message.provider_updated_at,
        original_url=None,
    )
