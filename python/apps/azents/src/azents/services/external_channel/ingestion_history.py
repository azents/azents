"""Provider-backed canonical history reader for synchronous ingestion."""

import asyncio
import dataclasses
from collections.abc import AsyncIterator, Awaitable, Callable
from dataclasses import dataclass
from typing import Annotated

import httpx
from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from azents.core.enums import ExternalChannelProvider
from azents.core.external_channel_reference import provider_reference_mappings_size
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
from azents.services.external_channel.discord_sdk import (
    DiscordSDKClientFactory,
    get_discord_sdk_client_factory,
)
from azents.services.external_channel.ingestion import (
    ExternalChannelCanonicalHistoryMessage,
    ExternalChannelTriggerLocator,
)
from azents.services.external_channel.slack_events import (
    SlackConversationClient,
    SlackConversationHistoryTrigger,
    SlackNormalizedMessage,
    SlackProviderError,
    slack_message_reference_ids,
)
from azents.services.external_channel.slack_sdk_client import create_slack_web_client

_MAX_SLACK_REFERENCE_IDS = 20
_REQUIRED_ADMISSION_RESERVE_SECONDS = 1.0


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


def get_ingestion_discord_conversation_client(
    sdk_factory: Annotated[
        DiscordSDKClientFactory,
        Depends(get_discord_sdk_client_factory),
    ],
) -> DiscordConversationHistoryClient:
    """Provide the shared public discord.py history client."""
    return DiscordConversationHistoryClient(sdk_factory)


@dataclass
class ExternalChannelProviderHistoryReader:
    """Read provider history and return one provider-neutral canonical range."""

    session_manager: Annotated[
        SessionManager[AsyncSession],
        Depends(get_session_manager),
    ]
    repository: Annotated[
        ExternalChannelRepository,
        Depends(ExternalChannelRepository.create),
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
            reference_cache = await _optional_slack_reference_cache(
                client=self.slack_client,
                bot_token=credentials.bot_token,
                messages=history.messages,
                trigger=history.trigger,
                deadline=deadline,
            )
            messages = tuple(
                _canonical_slack(
                    message,
                    reference_cache=reference_cache,
                )
                for message in history.messages
            )
            trigger = _canonical_slack(
                history.trigger,
                reference_cache=reference_cache,
            )
            original_url = await _optional_slack_permalink(
                client=self.slack_client,
                bot_token=credentials.bot_token,
                channel_id=locator.provider_channel_id,
                message_ts=locator.trigger_provider_message_id,
                deadline=deadline,
            )
            if original_url is not None:
                trigger = dataclasses.replace(trigger, original_url=original_url)
                messages = tuple(
                    (
                        trigger
                        if message.provider_message_key == trigger.provider_message_key
                        else message
                    )
                    for message in messages
                )
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


async def _optional_slack_permalink(
    *,
    client: SlackConversationClient,
    bot_token: str,
    channel_id: str,
    message_ts: str,
    deadline: ExternalChannelOperationDeadline,
) -> str | None:
    """Resolve optional source navigation without consuming required admission time."""
    budget = _optional_enrichment_budget(deadline)
    if budget <= 0:
        return None
    try:
        async with asyncio.timeout(budget):
            return await client.get_permalink(
                bot_token=bot_token,
                channel_id=channel_id,
                message_ts=message_ts,
            )
    except asyncio.CancelledError:
        raise
    except TimeoutError, SlackProviderError:
        return None


async def _optional_slack_reference_cache(
    *,
    client: SlackConversationClient,
    bot_token: str,
    messages: tuple[SlackNormalizedMessage, ...],
    trigger: SlackNormalizedMessage,
    deadline: ExternalChannelOperationDeadline,
) -> dict[str, dict[str, str]]:
    """Resolve bounded provider-history identities without blocking admission."""
    author_ids: list[str] = []
    seen_author_ids: set[str] = set()
    for message in (trigger, *messages):
        if (
            message.provider_user_id is not None
            and message.provider_user_id not in seen_author_ids
        ):
            author_ids.append(message.provider_user_id)
            seen_author_ids.add(message.provider_user_id)

    reference_user_ids: set[str] = set()
    channel_ids: set[str] = set()
    for message in messages:
        message_user_ids, message_channel_ids = slack_message_reference_ids(
            message.normalized_body
        )
        reference_user_ids.update(message_user_ids)
        channel_ids.update(message_channel_ids)

    user_ids = [
        *author_ids,
        *sorted(reference_user_ids.difference(seen_author_ids)),
    ][:_MAX_SLACK_REFERENCE_IDS]
    cache: dict[str, dict[str, str]] = {"users": {}, "channels": {}}
    for user_id in user_ids:
        display_name = await _optional_slack_display_name(
            lambda user_id=user_id: client.fetch_user_display_name(
                bot_token=bot_token, provider_user_id=user_id
            ),
            deadline=deadline,
        )
        if display_name is not None:
            cache["users"][user_id] = display_name
    for channel_id in sorted(channel_ids)[:_MAX_SLACK_REFERENCE_IDS]:
        display_name = await _optional_slack_display_name(
            lambda channel_id=channel_id: client.fetch_channel_display_name(
                bot_token=bot_token, channel_id=channel_id
            ),
            deadline=deadline,
        )
        if display_name is not None:
            cache["channels"][channel_id] = display_name
    return cache


async def _optional_slack_display_name(
    request: Callable[[], Awaitable[str | None]],
    *,
    deadline: ExternalChannelOperationDeadline,
) -> str | None:
    """Create one optional Slack lookup only when enrichment budget remains."""
    budget = _optional_enrichment_budget(deadline)
    if budget <= 0:
        return None
    try:
        async with asyncio.timeout(budget):
            return await request()
    except asyncio.CancelledError:
        raise
    except TimeoutError, SlackProviderError:
        return None


def _optional_enrichment_budget(
    deadline: ExternalChannelOperationDeadline,
) -> float:
    """Return time available after preserving required stage and delivery reserve."""
    return max(
        0.0,
        deadline.remaining_seconds() - _REQUIRED_ADMISSION_RESERVE_SECONDS,
    )


def _canonical_slack(
    message: SlackNormalizedMessage,
    *,
    reference_cache: dict[str, dict[str, str]],
) -> ExternalChannelCanonicalHistoryMessage:
    """Convert one normalized Slack history item without a raw event dependency."""
    user_ids, channel_ids = slack_message_reference_ids(message.normalized_body)
    if message.provider_user_id is not None:
        user_ids.add(message.provider_user_id)
    reference_mappings: dict[str, object] = {}
    users = {
        user_id: reference_cache["users"][user_id]
        for user_id in sorted(user_ids)
        if user_id in reference_cache["users"]
    }
    channels = {
        channel_id: reference_cache["channels"][channel_id]
        for channel_id in sorted(channel_ids)
        if channel_id in reference_cache["channels"]
    }
    if users:
        reference_mappings["users"] = users
    if channels:
        reference_mappings["channels"] = channels
    return ExternalChannelCanonicalHistoryMessage(
        provider_message_key=message.provider_message_key,
        provider_position=message.provider_position,
        revision_key=message.revision_key,
        revision_kind=message.revision_kind,
        lifecycle=message.lifecycle,
        author_type=message.author_type,
        provider_user_id=message.provider_user_id,
        sender_display_name=(
            None
            if message.provider_user_id is None
            else reference_cache["users"].get(message.provider_user_id)
        ),
        normalized_body=message.normalized_body,
        attachment_metadata=message.attachment_metadata,
        reference_mappings=reference_mappings or None,
        normalized_size=message.normalized_size
        + provider_reference_mappings_size(users=users, channels=channels),
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
        original_url=_discord_original_url(message),
    )


def _discord_original_url(message: DiscordNormalizedMessage) -> str | None:
    """Return one canonical Discord message URL from validated snowflakes."""
    identifiers = (
        message.tenant_id,
        message.channel_id,
        message.message_id,
    )
    if not all(identifier.isdigit() for identifier in identifiers):
        return None
    return f"https://discord.com/channels/{'/'.join(identifiers)}"
