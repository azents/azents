"""Slack event normalization and bounded conversation API operations."""

import asyncio
import datetime
import json
import logging
import re
import time
from collections.abc import AsyncIterator, Awaitable, Callable, Sequence
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from dataclasses import dataclass
from typing import Literal

import aiohttp
import httpx
from slack_sdk.errors import SlackApiError
from slack_sdk.web.async_client import AsyncWebClient
from slack_sdk.web.async_slack_response import AsyncSlackResponse

from azents.core.enums import (
    ExternalChannelMessageLifecycle,
    ExternalChannelMessageRevisionKind,
    ExternalChannelPrincipalAuthorType,
    ExternalChannelProvider,
)
from azents.core.external_channel_file import (
    MAX_EXTERNAL_CHANNEL_FILE_TEXT_LENGTH,
    MAX_EXTERNAL_CHANNEL_FILES,
    ExternalChannelFileMetadata,
    ExternalChannelFileUnsupportedReason,
)
from azents.runtime.transfer.provider_source import ProviderByteStreamResponse
from azents.services.external_channel.conversation import (
    ExternalChannelHistoryCredentialsInvalid,
    ExternalChannelHistoryDeadlineExceeded,
    ExternalChannelHistoryMalformed,
    ExternalChannelHistoryPermissionDenied,
    ExternalChannelHistoryPositionInvalid,
    ExternalChannelHistoryRange,
    ExternalChannelHistoryRangeIncomplete,
    ExternalChannelHistoryRateLimited,
    ExternalChannelHistoryResourceUnavailable,
    ExternalChannelHistoryTemporaryFailure,
    ExternalChannelHistoryTriggerMissing,
    ExternalChannelOperationDeadline,
)
from azents.services.external_channel.slack_blocks import (
    projected_slack_blocks_text,
    slack_blocks_text,
)
from azents.services.external_channel.slack_endpoint import slack_file_url_allowed

_MAX_NORMALIZED_TEXT_BYTES = 64 * 1024
_MAX_ATTACHMENT_TYPES = 32
SLACK_MARKDOWN_TEXT_MAX_LENGTH = 12_000
SLACK_INTERACTION_VIEW_TITLE_MAX_LENGTH = 24
SLACK_INTERACTION_VIEW_PRIVATE_METADATA_MAX_LENGTH = 3_000
SLACK_INTERACTION_VIEW_MAX_BLOCKS = 100
SLACK_INTERACTION_VIEW_MAX_BYTES = 100 * 1024
_MAX_REFERENCE_IDS = 20
_MAX_HISTORY_PAGES = 20
_MAX_HISTORY_SCANNED_MESSAGES = 2_000
_MAX_HISTORY_RETAINED_MESSAGES = 20
_MAX_HISTORY_RESPONSE_BYTES = 256 * 1024
_MAX_HISTORY_MESSAGE_BYTES = 64 * 1024
_SLACK_USER_REFERENCE = re.compile(r"<@([A-Z0-9]+)(?:\|[^>]+)?>|@([UW][A-Z0-9]+)")
_SLACK_CHANNEL_REFERENCE = re.compile(
    r"<#([CG][A-Z0-9]+)(?:\|[^>]+)?>|#([CG][A-Z0-9]+)"
)
_SLACK_DIAGNOSTIC_ARGUMENT_NAMES = (
    "alt_txt",
    "channel_id",
    "file_id",
    "files",
    "filename",
    "initial_comment",
    "length",
    "thread_ts",
    "title",
)

logger = logging.getLogger(__name__)


class SlackEventNormalizationError(ValueError):
    """An admitted Slack envelope is malformed for asynchronous processing."""


class SlackEventExcluded(SlackEventNormalizationError):
    """An admitted event is intentionally outside the External Channel scope."""


class SlackProviderError(RuntimeError):
    """Base class for controlled Slack Web API failures."""

    def __init__(
        self,
        message: str = "Slack provider operation failed.",
        *,
        diagnostics: dict[str, object] | None = None,
    ) -> None:
        super().__init__(message)
        self.diagnostics = dict(diagnostics or {})


class SlackProviderRateLimited(SlackProviderError):
    """Slack asked the inbound hydrator to retry after a bounded delay."""

    def __init__(
        self,
        retry_after_seconds: int,
        *,
        diagnostics: dict[str, object] | None = None,
    ) -> None:
        super().__init__(
            "Slack thread hydration is rate limited.",
            diagnostics=diagnostics,
        )
        self.retry_after_seconds = max(1, retry_after_seconds)


class SlackProviderTemporaryError(SlackProviderError):
    """Slack or the network is temporarily unavailable."""


class SlackProviderRequestRejected(SlackProviderTemporaryError):
    """Slack returned a confirmed provider-specific request rejection."""

    def __init__(
        self,
        error_code: str,
        *,
        diagnostics: dict[str, object] | None = None,
    ) -> None:
        super().__init__(
            "Slack rejected the provider request.",
            diagnostics=diagnostics,
        )
        self.error_code = error_code


class SlackProviderCredentialsInvalid(SlackProviderError):
    """Slack rejected the configured connection credential."""


class SlackProviderPermissionDenied(SlackProviderError):
    """Slack rejected an operation because required scopes are missing."""


class SlackProviderResourceUnavailable(SlackProviderError):
    """Slack cannot expose the requested channel or thread to the App."""


class SlackProviderMessageNotFound(SlackProviderError):
    """Slack no longer contains the requested message."""


class SlackProviderFileNotFound(SlackProviderError):
    """Slack no longer exposes the requested file."""


class SlackProviderFileTooLarge(SlackProviderError):
    """Slack returned more file bytes than the configured limit."""


class SlackOutboundFileContentError(SlackProviderError):
    """The run-scoped Runtime source changed or became unreadable."""


@dataclass(frozen=True)
class SlackConnectionRevocation:
    """Provider event that makes a Slack connection unavailable."""

    kind: Literal["app_uninstalled", "tokens_revoked"]


@dataclass(frozen=True)
class SlackNormalizedMessage:
    """One provider message lifecycle mutation normalized from Slack."""

    tenant_id: str
    channel_id: str
    root_thread_ts: str
    message_ts: str
    correlation_key: str
    provider_resource_key: str
    provider_message_key: str
    provider_position: str
    revision_key: str
    revision_kind: ExternalChannelMessageRevisionKind
    lifecycle: ExternalChannelMessageLifecycle
    author_type: ExternalChannelPrincipalAuthorType
    provider_user_id: str | None
    normalized_body: str | None
    attachment_metadata: dict[str, object] | None
    normalized_size: int
    provider_created_at: datetime.datetime | None
    provider_updated_at: datetime.datetime | None
    invocation: bool
    source_event_type: str


@dataclass(frozen=True)
class SlackThreadPage:
    """One bounded Slack thread-history page."""

    messages: tuple[SlackNormalizedMessage, ...]
    next_cursor: str | None


@dataclass(frozen=True)
class SlackConversationHistoryTrigger:
    """Credential-free provider locator for one bounded Slack history range."""

    tenant_id: str
    channel_id: str
    trigger_message_ts: str
    root_thread_ts: str | None
    connected_bot_user_id: str | None
    connected_app_id: str | None


@dataclass(frozen=True)
class SlackConversationAccess:
    """Slack conversation eligibility required for first-mention tracking."""

    app_member: bool
    external_shared: bool
    public_or_private_channel: bool
    display_name: str | None = None


@dataclass(frozen=True)
class SlackControlMessageResult:
    """Sanitized result of one Slack control-message provider attempt."""

    status: Literal["delivered", "failed", "unknown"]
    provider_message_key: str | None
    error_kind: str | None
    error_summary: str | None


@dataclass(frozen=True)
class SlackInteractionView:
    """Bounded selector modal content without provider authority or raw source data."""

    callback_id: str
    title: str
    private_metadata: str
    blocks: list[dict[str, object]]
    submit_title: str | None
    close_title: str | None


@dataclass(frozen=True)
class SlackInteractionViewResult:
    """Sanitized one-attempt Slack view mutation outcome."""

    status: Literal["opened", "updated", "expired", "conflict", "rejected", "unknown"]
    error_kind: str | None
    error_summary: str | None


@dataclass(frozen=True)
class SlackFileDownloadInfo:
    """Current provider metadata and private URL for one Slack-hosted file."""

    metadata: ExternalChannelFileMetadata
    private_url: str | None


@dataclass(frozen=True)
class SlackOutboundFile:
    """One known-length file source for Slack external upload."""

    filename: str
    length: int
    content: Callable[[], AsyncIterator[bytes]]


def normalize_slack_event(
    *,
    event_type: str,
    tenant_id: str,
    envelope: dict[str, object],
) -> SlackConnectionRevocation | SlackNormalizedMessage:
    """Normalize one raw Slack event or reject it as out of scope."""
    return _normalize_slack_event(
        event_type=event_type,
        tenant_id=tenant_id,
        envelope=envelope,
        trusted_block_projection=False,
        connected_bot_user_id=None,
    )


def normalize_projected_slack_event(
    *,
    event_type: str,
    tenant_id: str,
    envelope: dict[str, object],
    connected_bot_user_id: str | None,
) -> SlackConnectionRevocation | SlackNormalizedMessage:
    """Normalize one Azents-projected admitted Slack event."""
    return _normalize_slack_event(
        event_type=event_type,
        tenant_id=tenant_id,
        envelope=envelope,
        trusted_block_projection=True,
        connected_bot_user_id=connected_bot_user_id,
    )


def _normalize_slack_event(
    *,
    event_type: str,
    tenant_id: str,
    envelope: dict[str, object],
    trusted_block_projection: bool,
    connected_bot_user_id: str | None,
) -> SlackConnectionRevocation | SlackNormalizedMessage:
    """Normalize one Slack event with an explicit block trust boundary."""
    if event_type == "app_uninstalled":
        return SlackConnectionRevocation(kind="app_uninstalled")
    if event_type == "tokens_revoked":
        return SlackConnectionRevocation(kind="tokens_revoked")
    if event_type not in {"app_mention", "message"}:
        raise SlackEventExcluded("Slack event type is outside the configured scope.")

    event = envelope.get("event")
    if not isinstance(event, dict):
        raise SlackEventNormalizationError("Slack event object is missing.")
    if event.get("is_ext_shared_channel") is True:
        raise SlackEventExcluded("Slack Connect conversations are not supported.")
    channel_id = _required_string(event, "channel")
    channel_type = event.get("channel_type")
    if not _eligible_channel(channel_id, channel_type):
        raise SlackEventExcluded("Slack direct and group messages are not supported.")

    subtype = _optional_string(event, "subtype")
    if event_type == "message" and subtype in {"message_changed", "message_deleted"}:
        raise SlackEventExcluded(
            "Slack message updates and deletions are outside the configured scope."
        )
    if event_type == "app_mention":
        message = event
        revision_kind = ExternalChannelMessageRevisionKind.ORIGINAL
        lifecycle = ExternalChannelMessageLifecycle.CURRENT
        message_ts = _required_string(message, "ts")
        provider_updated_at = None
    else:
        raw_message = event.get("message")
        message = (
            raw_message
            if _optional_string(event, "ts") is None and isinstance(raw_message, dict)
            else event
        )
        revision_kind = ExternalChannelMessageRevisionKind.ORIGINAL
        lifecycle = ExternalChannelMessageLifecycle.CURRENT
        message_ts = _required_string(message, "ts")
        provider_updated_at = None

    root_thread_ts = _optional_string(message, "thread_ts") or message_ts
    author_type, provider_user_id = _author(message)
    normalized_body = _normalized_message_body(
        message,
        trusted_block_projection=trusted_block_projection,
    )
    attachment_metadata = _attachment_metadata(
        blocks=message.get("blocks"),
        files=message.get("files"),
        files_truncated=message.get("files_truncated"),
    )
    normalized_size = _normalized_size(normalized_body, attachment_metadata)
    provider_created_at = _slack_timestamp(message_ts)
    provider_position = slack_provider_position(message_ts)
    revision_key = _revision_key(message_ts=message_ts)
    invocation = _slack_message_invocation(
        event_type=event_type,
        subtype=subtype,
        author_type=author_type,
        provider_user_id=provider_user_id,
        normalized_body=normalized_body,
        tenant_id=tenant_id,
        envelope=envelope,
        connected_bot_user_id=connected_bot_user_id,
    )
    return SlackNormalizedMessage(
        tenant_id=tenant_id,
        channel_id=channel_id,
        root_thread_ts=root_thread_ts,
        message_ts=message_ts,
        correlation_key=f"{channel_id}:{root_thread_ts}",
        provider_resource_key=(f"slack:{tenant_id}:{channel_id}:{root_thread_ts}"),
        provider_message_key=f"slack:{tenant_id}:{channel_id}:{message_ts}",
        provider_position=provider_position,
        revision_key=revision_key,
        revision_kind=revision_kind,
        lifecycle=lifecycle,
        author_type=author_type,
        provider_user_id=provider_user_id,
        normalized_body=normalized_body,
        attachment_metadata=attachment_metadata,
        normalized_size=normalized_size,
        provider_created_at=provider_created_at,
        provider_updated_at=provider_updated_at,
        invocation=invocation,
        source_event_type=event_type,
    )


def normalize_slack_history_message(
    *,
    tenant_id: str,
    channel_id: str,
    root_thread_ts: str,
    message: dict[str, object],
) -> SlackNormalizedMessage:
    """Normalize one message returned by ``conversations.replies``."""
    envelope: dict[str, object] = {
        "event": {
            **message,
            "type": "message",
            "channel": channel_id,
            "channel_type": "channel" if channel_id.startswith("C") else "group",
            "thread_ts": message.get("thread_ts") or root_thread_ts,
        }
    }
    normalized = normalize_slack_event(
        event_type="message",
        tenant_id=tenant_id,
        envelope=envelope,
    )
    if isinstance(normalized, SlackConnectionRevocation):
        raise AssertionError("History message cannot normalize as revocation.")
    return normalized


def slack_provider_position(timestamp: str) -> str:
    """Return a lexically sortable canonical Slack timestamp position."""
    seconds, separator, fraction = timestamp.partition(".")
    if not seconds.isdigit() or (separator and not fraction.isdigit()):
        raise SlackEventNormalizationError("Slack message timestamp is invalid.")
    fraction = (fraction + "000000")[:6]
    return f"{int(seconds):020d}.{fraction}"


def _valid_slack_position(position: str) -> bool:
    seconds, separator, fraction = position.partition(".")
    return (
        len(seconds) == 20
        and seconds.isdigit()
        and separator == "."
        and len(fraction) == 6
        and fraction.isdigit()
    )


def _slack_position_to_timestamp(position: str | None) -> str | None:
    if position is None:
        return None
    if not _valid_slack_position(position):
        raise ExternalChannelHistoryMalformed(
            "Slack history range start position is invalid."
        )
    seconds, _, fraction = position.partition(".")
    return f"{int(seconds)}.{fraction}"


def _slack_connected_identity(
    message: SlackNormalizedMessage,
    *,
    connected_bot_user_id: str | None,
    connected_app_id: str | None,
) -> bool:
    identities = {
        identity
        for identity in (
            None if connected_bot_user_id is None else f"bot:{connected_bot_user_id}",
            None if connected_app_id is None else f"app:{connected_app_id}",
        )
        if identity is not None
    }
    return message.provider_user_id in identities


def _validate_slack_history_item(
    message: dict[str, object],
    *,
    trigger: SlackConversationHistoryTrigger,
) -> None:
    """Validate one raw message remains inside the requested Slack scope."""
    raw_channel = message.get("channel")
    if raw_channel is not None and raw_channel != trigger.channel_id:
        raise ExternalChannelHistoryMalformed(
            "Slack history item crossed the requested channel."
        )
    if trigger.root_thread_ts is None:
        return
    raw_timestamp = message.get("ts")
    raw_thread_timestamp = message.get("thread_ts")
    if raw_timestamp == trigger.root_thread_ts:
        if (
            raw_thread_timestamp is not None
            and raw_thread_timestamp != trigger.root_thread_ts
        ):
            raise ExternalChannelHistoryMalformed(
                "Slack history root had an invalid thread boundary."
            )
        return
    if raw_thread_timestamp != trigger.root_thread_ts:
        raise ExternalChannelHistoryMalformed(
            "Slack history reply crossed the requested thread."
        )


class SlackConversationClient:
    """Bounded Slack Web API adapter for inbound hydration and access control."""

    def __init__(
        self,
        *,
        web_client: AsyncWebClient,
        http_client: httpx.AsyncClient,
    ) -> None:
        self.web_client = web_client
        self.http_client = http_client

    async def fetch_conversation_access(
        self,
        *,
        bot_token: str,
        channel_id: str,
    ) -> SlackConversationAccess:
        """Validate App membership and unsupported Slack Connect state."""
        payload = await self._call_api(
            api_method="conversations.info",
            argument_names=("channel", "include_num_members"),
            request=self.web_client.conversations_info(
                channel=channel_id,
                include_num_members=False,
                token=bot_token,
            ),
        )
        channel = payload.get("channel")
        if not isinstance(channel, dict):
            raise SlackProviderTemporaryError(
                "Slack conversation response is malformed."
            )
        return SlackConversationAccess(
            app_member=channel.get("is_member") is True,
            external_shared=(
                channel.get("is_ext_shared") is True
                or channel.get("is_org_shared") is True
            ),
            public_or_private_channel=(
                channel.get("is_channel") is True or channel.get("is_group") is True
            )
            and channel.get("is_im") is not True
            and channel.get("is_mpim") is not True,
            display_name=_channel_display_name(channel),
        )

    async def fetch_channel_display_name(
        self,
        *,
        bot_token: str,
        channel_id: str,
    ) -> str | None:
        """Resolve one Slack channel ID to a display label."""
        payload = await self._call_api(
            api_method="conversations.info",
            argument_names=("channel", "include_num_members"),
            request=self.web_client.conversations_info(
                channel=channel_id,
                include_num_members=False,
                token=bot_token,
            ),
        )
        channel = payload.get("channel")
        if not isinstance(channel, dict):
            raise SlackProviderTemporaryError(
                "Slack conversation response is malformed."
            )
        return _channel_display_name(channel)

    async def fetch_user_display_name(
        self,
        *,
        bot_token: str,
        provider_user_id: str,
    ) -> str | None:
        """Resolve one Slack user or bot identity to a human-readable name."""
        if provider_user_id.startswith("bot:"):
            payload = await self._call_api(
                api_method="bots.info",
                argument_names=("bot",),
                request=self.web_client.bots_info(
                    bot=provider_user_id.removeprefix("bot:"),
                    token=bot_token,
                ),
            )
            bot = payload.get("bot")
            if not isinstance(bot, dict):
                raise SlackProviderTemporaryError("Slack bot response is malformed.")
            name = bot.get("name")
            return name if isinstance(name, str) and name else None
        if provider_user_id.startswith("app:"):
            return None
        payload = await self._call_api(
            api_method="users.info",
            argument_names=("user",),
            request=self.web_client.users_info(
                user=provider_user_id,
                token=bot_token,
            ),
        )
        user = payload.get("user")
        if not isinstance(user, dict):
            raise SlackProviderTemporaryError("Slack user response is malformed.")
        profile = user.get("profile")
        profile_values = profile if isinstance(profile, dict) else {}
        for value in (
            profile_values.get("display_name"),
            user.get("real_name"),
            profile_values.get("real_name"),
            user.get("name"),
        ):
            if isinstance(value, str) and value.strip():
                return value.strip()
        return None

    async def fetch_thread_page(
        self,
        *,
        bot_token: str,
        tenant_id: str,
        channel_id: str,
        root_thread_ts: str,
        cursor: str | None,
        limit: int,
    ) -> SlackThreadPage:
        """Fetch one cursor page of accessible thread history."""
        payload = await self._call_api(
            api_method="conversations.replies",
            argument_names=("channel", "cursor", "inclusive", "limit", "ts"),
            request=self.web_client.conversations_replies(
                channel=channel_id,
                ts=root_thread_ts,
                cursor=cursor,
                inclusive=True,
                limit=limit,
                token=bot_token,
            ),
        )
        raw_messages = payload.get("messages")
        if not isinstance(raw_messages, list):
            raise SlackProviderTemporaryError(
                "Slack thread history response is malformed."
            )
        messages: list[SlackNormalizedMessage] = []
        for item in raw_messages:
            if isinstance(item, dict):
                try:
                    normalized = normalize_slack_history_message(
                        tenant_id=tenant_id,
                        channel_id=channel_id,
                        root_thread_ts=root_thread_ts,
                        message=item,
                    )
                except SlackEventExcluded:
                    continue
                messages.append(normalized)
        metadata = payload.get("response_metadata")
        next_cursor = None
        if isinstance(metadata, dict):
            raw_cursor = metadata.get("next_cursor")
            if isinstance(raw_cursor, str) and raw_cursor:
                next_cursor = raw_cursor
        return SlackThreadPage(messages=tuple(messages), next_cursor=next_cursor)

    async def read_range(
        self,
        *,
        trigger: SlackConversationHistoryTrigger,
        bot_token: str,
        exclusive_start_position: str | None,
        deadline: ExternalChannelOperationDeadline,
    ) -> ExternalChannelHistoryRange[SlackNormalizedMessage]:
        """Read a bounded exclusive-start, inclusive-trigger Slack range."""
        started = time.monotonic()
        try:
            trigger_position = slack_provider_position(trigger.trigger_message_ts)
        except SlackEventNormalizationError as error:
            raise ExternalChannelHistoryPositionInvalid(
                "Slack history trigger position is invalid."
            ) from error
        if exclusive_start_position is not None and not _valid_slack_position(
            exclusive_start_position
        ):
            raise ExternalChannelHistoryPositionInvalid(
                "Slack history range start position is invalid."
            )
        cursor: str | None = None
        pages = 0
        scanned = 0
        normalized_messages: list[SlackNormalizedMessage] = []
        while True:
            if deadline.remaining_seconds() <= 0:
                raise ExternalChannelHistoryDeadlineExceeded(
                    "Slack history retrieval exceeded its deadline."
                )
            pages += 1
            if pages > _MAX_HISTORY_PAGES:
                raise ExternalChannelHistoryRangeIncomplete(
                    "Slack history range exceeded the bounded page limit."
                )
            try:
                if trigger.root_thread_ts is None:
                    request = self.web_client.conversations_history(
                        channel=trigger.channel_id,
                        cursor=cursor,
                        inclusive=True,
                        latest=trigger.trigger_message_ts,
                        limit=100,
                        oldest=(
                            _slack_position_to_timestamp(exclusive_start_position)
                            if exclusive_start_position is not None
                            else None
                        ),
                        token=bot_token,
                    )
                    payload = await self._call_api(
                        api_method="conversations.history",
                        argument_names=(
                            "channel",
                            "cursor",
                            "inclusive",
                            "latest",
                            "limit",
                            "oldest",
                        ),
                        request=request,
                        deadline=deadline,
                    )
                else:
                    request = self.web_client.conversations_replies(
                        channel=trigger.channel_id,
                        ts=trigger.root_thread_ts,
                        cursor=cursor,
                        inclusive=True,
                        limit=100,
                        latest=trigger.trigger_message_ts,
                        oldest=_slack_position_to_timestamp(exclusive_start_position),
                        token=bot_token,
                    )
                    payload = await self._call_api(
                        api_method="conversations.replies",
                        argument_names=(
                            "channel",
                            "cursor",
                            "inclusive",
                            "latest",
                            "limit",
                            "oldest",
                            "ts",
                        ),
                        request=request,
                        deadline=deadline,
                    )
            except SlackProviderRateLimited as error:
                raise ExternalChannelHistoryRateLimited(
                    error.retry_after_seconds
                ) from error
            except SlackProviderCredentialsInvalid as error:
                raise ExternalChannelHistoryCredentialsInvalid(str(error)) from error
            except SlackProviderPermissionDenied as error:
                raise ExternalChannelHistoryPermissionDenied(str(error)) from error
            except SlackProviderResourceUnavailable as error:
                raise ExternalChannelHistoryResourceUnavailable(str(error)) from error
            except SlackProviderTemporaryError as error:
                raise ExternalChannelHistoryTemporaryFailure(str(error)) from error
            except TimeoutError as error:
                raise ExternalChannelHistoryDeadlineExceeded(
                    "Slack history retrieval exceeded its deadline."
                ) from error
            except SlackEventNormalizationError as error:
                raise ExternalChannelHistoryMalformed(str(error)) from error
            raw_messages = payload.get("messages")
            if not isinstance(raw_messages, list):
                raise ExternalChannelHistoryMalformed(
                    "Slack history response is malformed."
                )
            try:
                response_size = len(
                    json.dumps(
                        payload,
                        ensure_ascii=False,
                        separators=(",", ":"),
                    ).encode()
                )
            except (TypeError, ValueError) as error:
                raise ExternalChannelHistoryMalformed(
                    "Slack history response could not be bounded."
                ) from error
            if response_size > _MAX_HISTORY_RESPONSE_BYTES:
                raise ExternalChannelHistoryMalformed(
                    "Slack history response exceeded the size limit."
                )
            page_messages: list[SlackNormalizedMessage] = []
            for raw_message in raw_messages:
                if not isinstance(raw_message, dict):
                    continue
                try:
                    message_size = len(
                        json.dumps(
                            raw_message,
                            ensure_ascii=False,
                            separators=(",", ":"),
                        ).encode()
                    )
                except (TypeError, ValueError) as error:
                    raise ExternalChannelHistoryMalformed(
                        "Slack history message could not be bounded."
                    ) from error
                if message_size > _MAX_HISTORY_MESSAGE_BYTES:
                    raise ExternalChannelHistoryMalformed(
                        "Slack history message exceeded the size limit."
                    )
                _validate_slack_history_item(raw_message, trigger=trigger)
                if (
                    trigger.connected_app_id is not None
                    and raw_message.get("app_id") == trigger.connected_app_id
                ) or (
                    trigger.connected_bot_user_id is not None
                    and raw_message.get("user") == trigger.connected_bot_user_id
                ):
                    continue
                try:
                    message = normalize_slack_history_message(
                        tenant_id=trigger.tenant_id,
                        channel_id=trigger.channel_id,
                        root_thread_ts=(
                            trigger.root_thread_ts
                            or _optional_string(raw_message, "thread_ts")
                            or _required_string(raw_message, "ts")
                        ),
                        message=raw_message,
                    )
                except SlackEventExcluded:
                    continue
                if _slack_connected_identity(
                    message,
                    connected_bot_user_id=trigger.connected_bot_user_id,
                    connected_app_id=trigger.connected_app_id,
                ):
                    continue
                scanned += 1
                if scanned > _MAX_HISTORY_SCANNED_MESSAGES:
                    raise ExternalChannelHistoryRangeIncomplete(
                        "Slack history range exceeded the bounded message limit."
                    )
                page_messages.append(message)
                eligible_count = sum(
                    1
                    for candidate in (*normalized_messages, *page_messages)
                    if (
                        (
                            exclusive_start_position is None
                            or candidate.provider_position > exclusive_start_position
                        )
                        and candidate.provider_position <= trigger_position
                    )
                )
                if eligible_count >= _MAX_HISTORY_RETAINED_MESSAGES + 1:
                    break
            normalized_messages.extend(page_messages)
            eligible_count = sum(
                1
                for message in normalized_messages
                if (
                    (
                        exclusive_start_position is None
                        or message.provider_position > exclusive_start_position
                    )
                    and message.provider_position <= trigger_position
                )
            )
            if eligible_count >= _MAX_HISTORY_RETAINED_MESSAGES + 1:
                break
            metadata = payload.get("response_metadata")
            next_cursor = None
            if isinstance(metadata, dict):
                value = metadata.get("next_cursor")
                if isinstance(value, str) and value:
                    next_cursor = value
            reached_start = exclusive_start_position is not None and any(
                message.provider_position <= exclusive_start_position
                for message in page_messages
            )
            if next_cursor is None or reached_start:
                break
            cursor = next_cursor

        in_range = [
            message
            for message in normalized_messages
            if (
                (
                    exclusive_start_position is None
                    or message.provider_position > exclusive_start_position
                )
                and message.provider_position <= trigger_position
            )
        ]
        in_range.sort(key=lambda message: message.provider_position)
        trigger_messages = [
            message
            for message in in_range
            if message.message_ts == trigger.trigger_message_ts
        ]
        if not trigger_messages:
            raise ExternalChannelHistoryTriggerMissing(
                "Slack history did not contain the exact trigger."
            )
        context_omitted = len(in_range) > _MAX_HISTORY_RETAINED_MESSAGES
        retained = tuple(in_range[-_MAX_HISTORY_RETAINED_MESSAGES:])
        trigger_message = trigger_messages[0]
        if trigger_message not in retained:
            retained = tuple(
                sorted(
                    (*retained[:-1], trigger_message),
                    key=lambda message: message.provider_position,
                )
            )
        return ExternalChannelHistoryRange(
            messages=retained,
            trigger=trigger_message,
            context_omitted=context_omitted,
            range_start_position=exclusive_start_position,
            trigger_position=trigger_message.provider_position,
            provider_request_count=pages,
            scanned_message_count=scanned,
            elapsed_seconds=max(0.0, time.monotonic() - started),
            discord_root_thread_observation=None,
        )

    async def get_permalink(
        self,
        *,
        bot_token: str,
        channel_id: str,
        message_ts: str,
    ) -> str | None:
        """Resolve a provider-validated permalink for one Slack message."""
        payload = await self._call_api(
            api_method="chat.getPermalink",
            argument_names=("channel", "message_ts"),
            request=self.web_client.chat_getPermalink(
                channel=channel_id,
                message_ts=message_ts,
                token=bot_token,
            ),
        )
        permalink = payload.get("permalink")
        if not isinstance(permalink, str) or not permalink.startswith("https://"):
            return None
        return permalink

    async def fetch_file_download_info(
        self,
        *,
        bot_token: str,
        provider_file_id: str,
    ) -> SlackFileDownloadInfo:
        """Fetch current metadata and a server-only private download URL."""
        payload = await self._call_api(
            api_method="files.info",
            argument_names=("file",),
            request=self.web_client.files_info(
                file=provider_file_id,
                token=bot_token,
            ),
        )
        raw_file = payload.get("file")
        if not isinstance(raw_file, dict):
            raise SlackProviderTemporaryError("Slack file response is malformed.")
        if raw_file.get("deleted") is True:
            raise SlackProviderFileNotFound(
                "Slack no longer exposes the requested file."
            )
        metadata = normalize_slack_file_metadata(raw_file)
        if metadata.provider_file_id != provider_file_id:
            raise SlackProviderTemporaryError(
                "Slack file response identity does not match the request."
            )
        private_url = _optional_string(raw_file, "url_private_download")
        if private_url is None:
            private_url = _optional_string(raw_file, "url_private")
        if private_url is not None and not slack_file_url_allowed(private_url):
            raise SlackProviderTemporaryError(
                "Slack returned an invalid private file URL."
            )
        return SlackFileDownloadInfo(
            metadata=metadata,
            private_url=private_url,
        )

    def open_private_file_stream(
        self,
        *,
        bot_token: str,
        private_url: str,
        max_bytes: int,
        maximum_chunk_size: int,
    ) -> AbstractAsyncContextManager[ProviderByteStreamResponse]:
        """Return one owned bounded private-file stream."""
        return self._open_private_file_stream(
            bot_token=bot_token,
            private_url=private_url,
            max_bytes=max_bytes,
            maximum_chunk_size=maximum_chunk_size,
        )

    @asynccontextmanager
    async def _open_private_file_stream(
        self,
        *,
        bot_token: str,
        private_url: str,
        max_bytes: int,
        maximum_chunk_size: int,
    ) -> AsyncIterator[ProviderByteStreamResponse]:
        """Open one authenticated private file and close it after stream consumption."""
        if maximum_chunk_size <= 0:
            raise ValueError("Slack stream chunk size must be positive")
        if not slack_file_url_allowed(private_url):
            raise SlackProviderTemporaryError(
                "Slack returned an invalid private file URL."
            )
        try:
            async with self.http_client.stream(
                "GET",
                private_url,
                headers={"Authorization": f"Bearer {bot_token}"},
            ) as response:
                if response.status_code == 429:
                    retry_after = response.headers.get("Retry-After", "1")
                    try:
                        retry_after_seconds = int(retry_after)
                    except ValueError:
                        retry_after_seconds = 1
                    raise SlackProviderRateLimited(retry_after_seconds)
                if response.status_code == 401:
                    raise SlackProviderCredentialsInvalid(
                        "Slack rejected the configured credential."
                    )
                if response.status_code == 403:
                    raise SlackProviderPermissionDenied(
                        "Slack denied access to the requested file."
                    )
                if response.status_code == 404:
                    raise SlackProviderFileNotFound(
                        "Slack no longer exposes the requested file."
                    )
                if response.status_code >= 500:
                    raise SlackProviderTemporaryError(
                        "Slack is temporarily unavailable."
                    )
                if response.status_code >= 400:
                    raise SlackProviderRequestRejected("file_download_failed")
                if response.status_code != 200:
                    raise SlackProviderTemporaryError(
                        "Slack private file response is incomplete."
                    )
                content_lengths = response.headers.get_list("Content-Length")
                if (
                    len(content_lengths) != 1
                    or not content_lengths[0].isascii()
                    or not content_lengths[0].isdecimal()
                ):
                    raise SlackProviderRequestRejected("file_download_invalid_size")
                declared_response_size = int(content_lengths[0])
                if declared_response_size > max_bytes:
                    raise SlackProviderFileTooLarge(
                        "Slack file exceeds the configured limit."
                    )

                async def chunks() -> AsyncIterator[bytes]:
                    """Yield bounded response chunks without retaining all bytes."""
                    actual_size = 0
                    async for chunk in response.aiter_bytes(
                        chunk_size=maximum_chunk_size
                    ):
                        actual_size += len(chunk)
                        if actual_size > max_bytes:
                            raise SlackProviderFileTooLarge(
                                "Slack file exceeds the configured limit."
                            )
                        yield chunk

                yield ProviderByteStreamResponse(
                    content_length=declared_response_size,
                    chunks=chunks(),
                )
        except httpx.RequestError as error:
            raise SlackProviderTemporaryError(
                "Slack file download did not produce a complete response."
            ) from error

    async def post_approval_control_message(
        self,
        *,
        bot_token: str,
        tenant_id: str,
        channel_id: str,
        thread_ts: str,
        approval_url: str,
        participant_label: str,
        participant_provider_user_id: str,
        agent_name: str | None,
        agent_markdown_line: str | None,
        icon_url: str | None,
    ) -> SlackControlMessageResult:
        """Attempt one ordinary thread reply containing an approval link."""
        message = _approval_message_payload(
            approval_url,
            participant_label=participant_label,
            participant_provider_user_id=participant_provider_user_id,
        )
        if agent_name is not None and agent_markdown_line is not None:
            text = message.get("text")
            blocks = message.get("blocks")
            if isinstance(text, str) and isinstance(blocks, list):
                message["text"] = f"{agent_name}\n{text}"
                message["blocks"] = [
                    {
                        "type": "section",
                        "text": {"type": "mrkdwn", "text": agent_markdown_line},
                    },
                    *blocks,
                ]
        text = message.get("text")
        blocks = message.get("blocks")
        if not isinstance(text, str) or not isinstance(blocks, list):
            raise ValueError("Slack approval message projection is invalid.")

        async def request(include_icon: bool) -> AsyncSlackResponse:
            return await self.web_client.chat_postMessage(
                channel=channel_id,
                thread_ts=thread_ts,
                text=text,
                blocks=blocks,
                icon_url=icon_url if include_icon else None,
                unfurl_links=False,
                unfurl_media=False,
                token=bot_token,
            )

        return await self._attempt_message_operation(
            tenant_id=tenant_id,
            channel_id=channel_id,
            api_method="chat.postMessage",
            argument_names=(
                "blocks",
                "channel",
                "icon_url",
                "text",
                "thread_ts",
                "unfurl_links",
                "unfurl_media",
            ),
            request=request,
            expected_message_ts=None,
            allow_icon_fallback=icon_url is not None,
        )

    async def post_message(
        self,
        *,
        bot_token: str,
        tenant_id: str,
        channel_id: str,
        thread_ts: str | None,
        markdown_text: str,
        icon_url: str | None,
    ) -> SlackControlMessageResult:
        """Attempt one ordinary thread message without retry."""
        if len(markdown_text) > SLACK_MARKDOWN_TEXT_MAX_LENGTH:
            return SlackControlMessageResult(
                status="failed",
                provider_message_key=None,
                error_kind="provider_payload_invalid",
                error_summary="Slack Markdown text exceeds the supported limit.",
            )

        async def request(include_icon: bool) -> AsyncSlackResponse:
            return await self.web_client.chat_postMessage(
                channel=channel_id,
                thread_ts=thread_ts,
                markdown_text=markdown_text,
                icon_url=icon_url if include_icon else None,
                unfurl_links=False,
                unfurl_media=False,
                token=bot_token,
            )

        return await self._attempt_message_operation(
            tenant_id=tenant_id,
            channel_id=channel_id,
            api_method="chat.postMessage",
            argument_names=(
                "channel",
                "icon_url",
                "markdown_text",
                "thread_ts",
                "unfurl_links",
                "unfurl_media",
            ),
            request=request,
            expected_message_ts=None,
            allow_icon_fallback=icon_url is not None,
        )

    async def open_interaction_view(
        self,
        *,
        bot_token: str,
        trigger_id: str,
        view: SlackInteractionView,
    ) -> SlackInteractionViewResult:
        """Open one bounded modal with an ephemeral trigger that is never retained."""
        self._validate_interaction_view(view)
        if not trigger_id or len(trigger_id) > 512:
            return SlackInteractionViewResult(
                status="expired",
                error_kind="trigger_expired",
                error_summary="Slack interaction trigger is unavailable.",
            )
        return await self._attempt_interaction_view_mutation(
            api_method="views.open",
            argument_names=("trigger_id", "view"),
            request=self.web_client.views_open(
                trigger_id=trigger_id,
                view=self._interaction_view_payload(view),
                token=bot_token,
            ),
            success_status="opened",
        )

    async def update_interaction_view(
        self,
        *,
        bot_token: str,
        view_id: str,
        view_hash: str | None,
        view: SlackInteractionView,
    ) -> SlackInteractionViewResult:
        """Update one current modal without retrying a conflicting view revision."""
        self._validate_interaction_view(view)
        if not view_id or len(view_id) > 255:
            return SlackInteractionViewResult(
                status="rejected",
                error_kind="provider_payload_invalid",
                error_summary="Slack interaction view identifier is invalid.",
            )
        if view_hash is not None and (not view_hash or len(view_hash) > 255):
            return SlackInteractionViewResult(
                status="conflict",
                error_kind="view_hash_conflict",
                error_summary="Slack interaction view revision is unavailable.",
            )
        return await self._attempt_interaction_view_mutation(
            api_method="views.update",
            argument_names=("hash", "view", "view_id"),
            request=self.web_client.views_update(
                view_id=view_id,
                hash=view_hash,
                view=self._interaction_view_payload(view),
                token=bot_token,
            ),
            success_status="updated",
        )

    async def post_file_message(
        self,
        *,
        bot_token: str,
        tenant_id: str,
        channel_id: str,
        thread_ts: str | None,
        markdown_text: str,
        files: Sequence[SlackOutboundFile],
        before_provider_request: Callable[[], Awaitable[None]] | None = None,
        deadline_at: datetime.datetime | None = None,
    ) -> SlackControlMessageResult:
        """Upload ordered files under one absolute provider-operation deadline."""
        try:
            async with asyncio.timeout(self._delivery_timeout(deadline_at)):
                return await self._post_file_message(
                    bot_token=bot_token,
                    tenant_id=tenant_id,
                    channel_id=channel_id,
                    thread_ts=thread_ts,
                    markdown_text=markdown_text,
                    files=files,
                    before_provider_request=before_provider_request,
                    deadline_at=deadline_at,
                )
        except TimeoutError, SlackProviderTemporaryError:
            return SlackControlMessageResult(
                status="unknown",
                provider_message_key=None,
                error_kind="provider_ambiguous",
                error_summary="Slack file reply outcome is unknown.",
            )

    async def _post_file_message(
        self,
        *,
        bot_token: str,
        tenant_id: str,
        channel_id: str,
        thread_ts: str | None,
        markdown_text: str,
        files: Sequence[SlackOutboundFile],
        before_provider_request: Callable[[], Awaitable[None]] | None,
        deadline_at: datetime.datetime | None,
    ) -> SlackControlMessageResult:
        """Upload ordered files and publish them through one Slack completion."""
        if (
            not files
            or len(files) > MAX_EXTERNAL_CHANNEL_FILES
            or len(markdown_text) > SLACK_MARKDOWN_TEXT_MAX_LENGTH
        ):
            return SlackControlMessageResult(
                status="failed",
                provider_message_key=None,
                error_kind="provider_payload_invalid",
                error_summary="Slack file reply payload is invalid.",
            )
        uploaded_files: list[dict[str, str | None]] = []
        try:
            for file in files:
                if before_provider_request is not None:
                    await before_provider_request()
                upload_target = await self._call_api(
                    api_method="files.getUploadURLExternal",
                    argument_names=("filename", "length"),
                    request=self.web_client.files_getUploadURLExternal(
                        filename=file.filename,
                        length=file.length,
                        token=bot_token,
                    ),
                )
                upload_url = upload_target.get("upload_url")
                file_id = upload_target.get("file_id")
                if (
                    not isinstance(upload_url, str)
                    or not isinstance(file_id, str)
                    or not file_id
                ):
                    return SlackControlMessageResult(
                        status="unknown",
                        provider_message_key=None,
                        error_kind="provider_response_invalid",
                        error_summary=(
                            "Slack did not return a valid file upload target."
                        ),
                    )
                if not slack_file_url_allowed(upload_url):
                    return SlackControlMessageResult(
                        status="unknown",
                        provider_message_key=None,
                        error_kind="provider_response_invalid",
                        error_summary="Slack returned an invalid file upload URL.",
                    )
                try:
                    if before_provider_request is not None:
                        await before_provider_request()
                    upload_response = await self.http_client.request(
                        "POST",
                        upload_url,
                        headers={
                            "Content-Type": "application/octet-stream",
                            "Content-Length": str(file.length),
                        },
                        content=file.content(),
                        timeout=self._delivery_timeout(deadline_at),
                    )
                except SlackOutboundFileContentError:
                    return SlackControlMessageResult(
                        status="failed",
                        provider_message_key=None,
                        error_kind="runtime_file_unavailable",
                        error_summary=(
                            "The Runtime file changed or became unreadable "
                            "during upload."
                        ),
                    )
                except httpx.RequestError:
                    return SlackControlMessageResult(
                        status="unknown",
                        provider_message_key=None,
                        error_kind="provider_ambiguous",
                        error_summary="Slack file upload outcome is unknown.",
                    )
                try:
                    if upload_response.status_code >= 500:
                        return SlackControlMessageResult(
                            status="unknown",
                            provider_message_key=None,
                            error_kind="provider_ambiguous",
                            error_summary="Slack file upload outcome is unknown.",
                        )
                    if upload_response.status_code == 429:
                        return SlackControlMessageResult(
                            status="failed",
                            provider_message_key=None,
                            error_kind="rate_limited",
                            error_summary="Slack rate limited the file upload.",
                        )
                    if upload_response.status_code != 200:
                        return SlackControlMessageResult(
                            status="failed",
                            provider_message_key=None,
                            error_kind="provider_rejected",
                            error_summary="Slack rejected the external file upload.",
                        )
                    uploaded_files.append({"id": file_id, "title": file.filename})
                finally:
                    await upload_response.aclose()
            if before_provider_request is not None:
                await before_provider_request()
            await self._call_api(
                api_method="files.completeUploadExternal",
                argument_names=(
                    "channel_id",
                    "files",
                    "initial_comment",
                    "thread_ts",
                ),
                request=self.web_client.files_completeUploadExternal(
                    files=uploaded_files,
                    channel_id=channel_id,
                    thread_ts=thread_ts,
                    initial_comment=markdown_text,
                    token=bot_token,
                ),
            )
        except SlackProviderPermissionDenied as error:
            _log_slack_provider_failure(error, operation="file_reply")
            return SlackControlMessageResult(
                status="failed",
                provider_message_key=None,
                error_kind="missing_scope",
                error_summary="Slack App permissions are incomplete.",
            )
        except SlackProviderCredentialsInvalid as error:
            _log_slack_provider_failure(error, operation="file_reply")
            return SlackControlMessageResult(
                status="failed",
                provider_message_key=None,
                error_kind="credentials_invalid",
                error_summary="Slack rejected the configured credential.",
            )
        except SlackProviderResourceUnavailable as error:
            _log_slack_provider_failure(error, operation="file_reply")
            return SlackControlMessageResult(
                status="failed",
                provider_message_key=None,
                error_kind="resource_unavailable",
                error_summary="Slack cannot post to the linked conversation.",
            )
        except SlackProviderFileNotFound as error:
            _log_slack_provider_failure(error, operation="file_reply")
            return SlackControlMessageResult(
                status="failed",
                provider_message_key=None,
                error_kind="provider_rejected",
                error_summary="Slack no longer accepts one uploaded file.",
            )
        except SlackProviderRateLimited as error:
            _log_slack_provider_failure(error, operation="file_reply")
            return SlackControlMessageResult(
                status="failed",
                provider_message_key=None,
                error_kind="rate_limited",
                error_summary="Slack rate limited the file reply attempt.",
            )
        except SlackProviderRequestRejected as error:
            _log_slack_provider_failure(error, operation="file_reply")
            return SlackControlMessageResult(
                status="failed",
                provider_message_key=None,
                error_kind="provider_rejected",
                error_summary=f"Slack rejected the file reply ({error.error_code}).",
            )
        except SlackProviderTemporaryError as error:
            _log_slack_provider_failure(error, operation="file_reply")
            return SlackControlMessageResult(
                status="unknown",
                provider_message_key=None,
                error_kind="provider_ambiguous",
                error_summary="Slack file reply outcome is unknown.",
            )
        return SlackControlMessageResult(
            status="delivered",
            provider_message_key=None,
            error_kind=None,
            error_summary=None,
        )

    @staticmethod
    def _delivery_timeout(deadline_at: datetime.datetime | None) -> float | None:
        """Return the remaining logical delivery time for one provider request."""
        if deadline_at is None:
            return None
        remaining = (deadline_at - datetime.datetime.now(datetime.UTC)).total_seconds()
        if remaining <= 0:
            raise SlackProviderTemporaryError(
                "Slack file delivery deadline expired before the provider request."
            )
        return remaining

    async def update_message(
        self,
        *,
        bot_token: str,
        tenant_id: str,
        channel_id: str,
        message_ts: str,
        text: str,
        blocks: list[dict[str, object]] | None = None,
    ) -> SlackControlMessageResult:
        """Attempt one message update without retry."""

        async def request(_: bool) -> AsyncSlackResponse:
            return await self.web_client.chat_update(
                channel=channel_id,
                ts=message_ts,
                text=text,
                blocks=blocks,
                parse="none",
                link_names=False,
                token=bot_token,
            )

        return await self._attempt_message_operation(
            tenant_id=tenant_id,
            channel_id=channel_id,
            api_method="chat.update",
            argument_names=("blocks", "channel", "link_names", "parse", "text", "ts"),
            request=request,
            expected_message_ts=message_ts,
            allow_icon_fallback=False,
        )

    async def post_blocks(
        self,
        *,
        bot_token: str,
        tenant_id: str,
        channel_id: str,
        thread_ts: str | None,
        text: str,
        blocks: list[dict[str, object]],
        icon_url: str | None,
    ) -> SlackControlMessageResult:
        """Post one operational Block Kit message without retry."""

        async def request(include_icon: bool) -> AsyncSlackResponse:
            return await self.web_client.chat_postMessage(
                channel=channel_id,
                thread_ts=thread_ts,
                text=text,
                blocks=blocks,
                icon_url=icon_url if include_icon else None,
                mrkdwn=False,
                parse="none",
                link_names=False,
                unfurl_links=False,
                unfurl_media=False,
                token=bot_token,
            )

        return await self._attempt_message_operation(
            tenant_id=tenant_id,
            channel_id=channel_id,
            api_method="chat.postMessage",
            argument_names=(
                "blocks",
                "channel",
                "icon_url",
                "link_names",
                "mrkdwn",
                "parse",
                "text",
                "thread_ts",
                "unfurl_links",
                "unfurl_media",
            ),
            request=request,
            expected_message_ts=None,
            allow_icon_fallback=icon_url is not None,
        )

    async def delete_message(
        self,
        *,
        bot_token: str,
        tenant_id: str,
        channel_id: str,
        message_ts: str,
    ) -> SlackControlMessageResult:
        """Attempt one message delete without retry."""

        async def request(_: bool) -> AsyncSlackResponse:
            return await self.web_client.chat_delete(
                channel=channel_id,
                ts=message_ts,
                token=bot_token,
            )

        return await self._attempt_message_operation(
            tenant_id=tenant_id,
            channel_id=channel_id,
            api_method="chat.delete",
            argument_names=("channel", "ts"),
            request=request,
            expected_message_ts=message_ts,
            allow_icon_fallback=False,
        )

    @staticmethod
    def _validate_interaction_view(view: SlackInteractionView) -> None:
        """Reject oversized or incomplete modal content before Slack mutation."""
        for name, value in (
            ("callback ID", view.callback_id),
            ("title", view.title),
            ("private metadata", view.private_metadata),
        ):
            if not value:
                raise ValueError(f"Slack interaction view {name} must not be blank.")
        if len(view.callback_id) > 255:
            raise ValueError("Slack interaction view callback ID is too long.")
        if len(view.title) > SLACK_INTERACTION_VIEW_TITLE_MAX_LENGTH:
            raise ValueError("Slack interaction view title is too long.")
        if (
            len(view.private_metadata)
            > SLACK_INTERACTION_VIEW_PRIVATE_METADATA_MAX_LENGTH
        ):
            raise ValueError("Slack interaction view private metadata is too long.")
        if len(view.blocks) > SLACK_INTERACTION_VIEW_MAX_BLOCKS:
            raise ValueError("Slack interaction view contains too many blocks.")
        try:
            encoded = json.dumps(
                SlackConversationClient._interaction_view_payload(view),
                ensure_ascii=False,
                separators=(",", ":"),
            ).encode()
        except (TypeError, ValueError) as error:
            raise ValueError(
                "Slack interaction view is not JSON serializable."
            ) from error
        if len(encoded) > SLACK_INTERACTION_VIEW_MAX_BYTES:
            raise ValueError("Slack interaction view exceeds Slack's size limit.")

    @staticmethod
    def _interaction_view_payload(view: SlackInteractionView) -> dict[str, object]:
        """Build a Slack modal payload from already bounded selector state."""
        return {
            "type": "modal",
            "callback_id": view.callback_id,
            "private_metadata": view.private_metadata,
            "title": {"type": "plain_text", "text": view.title},
            "blocks": view.blocks,
            **(
                {"submit": {"type": "plain_text", "text": view.submit_title}}
                if view.submit_title is not None
                else {}
            ),
            **(
                {"close": {"type": "plain_text", "text": view.close_title}}
                if view.close_title is not None
                else {}
            ),
        }

    async def _attempt_interaction_view_mutation(
        self,
        *,
        api_method: str,
        argument_names: tuple[str, ...],
        request: Awaitable[AsyncSlackResponse],
        success_status: Literal["opened", "updated"],
    ) -> SlackInteractionViewResult:
        """Map one view mutation to a sanitized one-attempt provider outcome."""
        try:
            await self._call_api(
                api_method=api_method,
                argument_names=argument_names,
                request=request,
            )
        except SlackProviderRequestRejected as error:
            if error.error_code == "trigger_expired":
                return SlackInteractionViewResult(
                    status="expired",
                    error_kind="trigger_expired",
                    error_summary="Slack interaction trigger expired.",
                )
            if error.error_code in {"invalid_hash", "view_not_found"}:
                return SlackInteractionViewResult(
                    status="conflict",
                    error_kind="view_hash_conflict",
                    error_summary="Slack interaction view changed before update.",
                )
            return SlackInteractionViewResult(
                status="rejected",
                error_kind="provider_rejected",
                error_summary="Slack rejected the interaction view mutation.",
            )
        except (
            SlackProviderCredentialsInvalid,
            SlackProviderPermissionDenied,
            SlackProviderResourceUnavailable,
        ) as error:
            _log_slack_provider_failure(error, operation="interaction_view")
            return SlackInteractionViewResult(
                status="rejected",
                error_kind="provider_unavailable",
                error_summary="Slack interaction view mutation is unavailable.",
            )
        except (SlackProviderRateLimited, SlackProviderTemporaryError) as error:
            _log_slack_provider_failure(error, operation="interaction_view")
            return SlackInteractionViewResult(
                status="unknown",
                error_kind="provider_ambiguous",
                error_summary="Slack interaction view outcome is unknown.",
            )
        return SlackInteractionViewResult(
            status=success_status,
            error_kind=None,
            error_summary=None,
        )

    async def _attempt_message_operation(
        self,
        *,
        tenant_id: str,
        channel_id: str,
        api_method: str,
        argument_names: tuple[str, ...],
        request: Callable[[bool], Awaitable[AsyncSlackResponse]],
        expected_message_ts: str | None,
        allow_icon_fallback: bool,
    ) -> SlackControlMessageResult:
        """Map one Slack mutation into a sanitized at-most-once outcome."""
        try:
            payload = await self._call_api(
                api_method=api_method,
                argument_names=argument_names,
                request=request(allow_icon_fallback),
            )
        except SlackProviderPermissionDenied:
            if allow_icon_fallback:
                return await self._attempt_message_operation(
                    tenant_id=tenant_id,
                    channel_id=channel_id,
                    api_method=api_method,
                    argument_names=argument_names,
                    request=request,
                    expected_message_ts=expected_message_ts,
                    allow_icon_fallback=False,
                )
            return SlackControlMessageResult(
                status="failed",
                provider_message_key=None,
                error_kind="missing_scope",
                error_summary="Slack App permissions are incomplete.",
            )
        except SlackProviderCredentialsInvalid:
            return SlackControlMessageResult(
                status="failed",
                provider_message_key=None,
                error_kind="credentials_invalid",
                error_summary="Slack rejected the configured credential.",
            )
        except SlackProviderResourceUnavailable:
            return SlackControlMessageResult(
                status="failed",
                provider_message_key=None,
                error_kind="resource_unavailable",
                error_summary="Slack cannot mutate the linked conversation.",
            )
        except SlackProviderMessageNotFound:
            return SlackControlMessageResult(
                status="failed",
                provider_message_key=None,
                error_kind="message_not_found",
                error_summary="Slack no longer contains the Activity Tracker message.",
            )
        except SlackProviderRateLimited:
            return SlackControlMessageResult(
                status="failed",
                provider_message_key=None,
                error_kind="rate_limited",
                error_summary="Slack rate limited the provider operation.",
            )
        except SlackProviderRequestRejected as error:
            if allow_icon_fallback:
                return await self._attempt_message_operation(
                    tenant_id=tenant_id,
                    channel_id=channel_id,
                    api_method=api_method,
                    argument_names=argument_names,
                    request=request,
                    expected_message_ts=expected_message_ts,
                    allow_icon_fallback=False,
                )
            return SlackControlMessageResult(
                status="failed",
                provider_message_key=None,
                error_kind="provider_rejected",
                error_summary=(
                    f"Slack rejected the provider operation ({error.error_code})."
                ),
            )
        except SlackProviderTemporaryError:
            return SlackControlMessageResult(
                status="unknown",
                provider_message_key=None,
                error_kind="provider_ambiguous",
                error_summary="Slack delivery outcome is unknown.",
            )
        message_ts = payload.get("ts")
        if not isinstance(message_ts, str) or not message_ts:
            message_ts = expected_message_ts
        if message_ts is None:
            return SlackControlMessageResult(
                status="unknown",
                provider_message_key=None,
                error_kind="provider_response_invalid",
                error_summary="Slack did not return a message identity.",
            )
        return SlackControlMessageResult(
            status="delivered",
            provider_message_key=(f"slack:{tenant_id}:{channel_id}:{message_ts}"),
            error_kind=None,
            error_summary=None,
        )

    async def _call_api(
        self,
        *,
        api_method: str,
        argument_names: tuple[str, ...],
        request: Awaitable[AsyncSlackResponse],
        deadline: ExternalChannelOperationDeadline | None = None,
    ) -> dict[str, object]:
        """Await one public Slack SDK operation and map controlled failures."""
        try:
            if deadline is None:
                response = await request
            else:
                remaining = deadline.remaining_seconds()
                if remaining <= 0:
                    raise TimeoutError
                async with asyncio.timeout(remaining):
                    response = await request
        except SlackApiError as error:
            raise _slack_provider_error(
                error,
                api_method=api_method,
                argument_names=argument_names,
            ) from None
        except TimeoutError:
            raise
        except aiohttp.ClientError as error:
            raise SlackProviderTemporaryError(
                "Slack request did not produce a response.",
                diagnostics={
                    "slack_api_method": api_method,
                    "slack_request_field_names": list(argument_names),
                },
            ) from error
        payload = response.data
        if not isinstance(payload, dict):
            raise SlackProviderTemporaryError(
                "Slack response body is malformed.",
                diagnostics=_slack_sdk_response_diagnostics(
                    response,
                    api_method=api_method,
                    argument_names=argument_names,
                ),
            )
        return payload


def _log_slack_provider_failure(
    error: SlackProviderError,
    *,
    operation: str,
) -> None:
    """Log one outbound Slack failure after it has reached its result boundary."""
    logger.exception(
        "Slack outbound operation failed",
        extra={
            "slack_operation": operation,
            **error.diagnostics,
        },
    )


def _slack_provider_error(
    error: SlackApiError,
    *,
    api_method: str,
    argument_names: tuple[str, ...],
) -> SlackProviderError:
    """Map one SDK API rejection without retaining provider payload data."""
    response = error.response
    if not isinstance(response, AsyncSlackResponse):
        return SlackProviderTemporaryError(
            "Slack response body is unavailable.",
            diagnostics={
                "slack_api_method": api_method,
                "slack_request_field_names": list(argument_names),
            },
        )
    payload = response.data if isinstance(response.data, dict) else {}
    diagnostics = _slack_sdk_response_diagnostics(
        response,
        api_method=api_method,
        argument_names=argument_names,
    )
    if response.status_code == 429:
        retry_after = _slack_sdk_response_header(response, "retry-after") or "1"
        try:
            retry_after_seconds = int(retry_after)
        except ValueError:
            retry_after_seconds = 1
        return SlackProviderRateLimited(
            retry_after_seconds,
            diagnostics=diagnostics,
        )
    if response.status_code >= 500:
        return SlackProviderTemporaryError(
            "Slack is temporarily unavailable.",
            diagnostics=diagnostics,
        )
    error_code = payload.get("error")
    if error_code == "missing_scope":
        return SlackProviderPermissionDenied(
            "Slack App permissions are incomplete.",
            diagnostics=diagnostics,
        )
    if error_code in {
        "account_inactive",
        "invalid_auth",
        "not_authed",
        "not_allowed_token_type",
        "token_revoked",
    }:
        return SlackProviderCredentialsInvalid(
            "Slack rejected the configured credential.",
            diagnostics=diagnostics,
        )
    if error_code in {
        "channel_not_found",
        "is_archived",
        "not_in_channel",
        "thread_not_found",
    }:
        return SlackProviderResourceUnavailable(
            "Slack conversation is unavailable to the App.",
            diagnostics=diagnostics,
        )
    if error_code == "message_not_found":
        return SlackProviderMessageNotFound(
            "Slack no longer contains the requested message.",
            diagnostics=diagnostics,
        )
    if error_code in {"file_deleted", "file_not_found"}:
        return SlackProviderFileNotFound(
            "Slack no longer exposes the requested file.",
            diagnostics=diagnostics,
        )
    normalized_error_code = (
        error_code
        if isinstance(error_code, str) and re.fullmatch(r"[a-z0-9_]{1,80}", error_code)
        else "unknown_error"
    )
    return SlackProviderRequestRejected(
        normalized_error_code,
        diagnostics=diagnostics,
    )


def _slack_sdk_response_diagnostics(
    response: AsyncSlackResponse,
    *,
    api_method: str,
    argument_names: tuple[str, ...],
) -> dict[str, object]:
    """Return safe SDK response diagnostics without provider content."""
    payload = response.data if isinstance(response.data, dict) else {}
    response_metadata = payload.get("response_metadata")
    return {
        "slack_api_method": api_method,
        "slack_http_status_code": response.status_code,
        "slack_request_id": _slack_sdk_response_header(
            response,
            "x-slack-req-id",
        ),
        "slack_request_field_names": list(argument_names),
        "slack_response_error_code": _normalized_slack_log_value(payload.get("error")),
        "slack_response_warning_code": _normalized_slack_log_value(
            payload.get("warning")
        ),
        "slack_response_diagnostic_argument_names": _diagnostic_argument_names(
            response_metadata
        ),
    }


def _slack_sdk_response_header(
    response: AsyncSlackResponse,
    name: str,
) -> str | None:
    """Read one SDK response header without relying on provider casing."""
    normalized_name = name.lower()
    for header_name, value in response.headers.items():
        if header_name.lower() == normalized_name and isinstance(value, str):
            return value
    return None


def _diagnostic_argument_names(response_metadata: object) -> list[str]:
    """Extract known parameter names from Slack diagnostics without their values."""
    if not isinstance(response_metadata, dict):
        return []
    messages = response_metadata.get("messages")
    if not isinstance(messages, list):
        return []
    diagnostic_text = " ".join(
        message for message in messages if isinstance(message, str)
    )
    return [
        argument_name
        for argument_name in _SLACK_DIAGNOSTIC_ARGUMENT_NAMES
        if re.search(rf"\b{re.escape(argument_name)}\b", diagnostic_text)
    ]


def _normalized_slack_log_value(value: object) -> str | None:
    if isinstance(value, str) and re.fullmatch(r"[a-z0-9_]{1,80}", value):
        return value
    return None


def _required_string(payload: dict[str, object], key: str) -> str:
    value = payload.get(key)
    if not isinstance(value, str) or not value:
        raise SlackEventNormalizationError(f"Slack field '{key}' is missing.")
    return value


def _optional_string(payload: dict[str, object], key: str) -> str | None:
    value = payload.get(key)
    return value if isinstance(value, str) and value else None


def _eligible_channel(channel_id: str, channel_type: object) -> bool:
    if channel_type in {"im", "mpim"} or channel_id.startswith("D"):
        return False
    if channel_type in {"channel", "group"}:
        return True
    return channel_id.startswith(("C", "G"))


def _author(
    message: dict[str, object],
) -> tuple[ExternalChannelPrincipalAuthorType, str | None]:
    user_id = _optional_string(message, "user")
    bot_id = _optional_string(message, "bot_id")
    app_id = _optional_string(message, "app_id")
    if bot_id is not None:
        return ExternalChannelPrincipalAuthorType.BOT, f"bot:{bot_id}"
    if app_id is not None and user_id is None:
        return ExternalChannelPrincipalAuthorType.APP, f"app:{app_id}"
    if user_id is not None:
        return ExternalChannelPrincipalAuthorType.HUMAN, user_id
    return ExternalChannelPrincipalAuthorType.SYSTEM, None


def slack_message_reference_ids(body: str | None) -> tuple[set[str], set[str]]:
    """Extract bounded Slack user and channel IDs from message text."""
    if body is None:
        return set(), set()
    user_ids = {
        match.group(1) or match.group(2)
        for match in _SLACK_USER_REFERENCE.finditer(body)
        if match.group(1) or match.group(2)
    }
    channel_ids = {
        match.group(1) or match.group(2)
        for match in _SLACK_CHANNEL_REFERENCE.finditer(body)
        if match.group(1) or match.group(2)
    }
    return (
        set(sorted(user_ids)[:_MAX_REFERENCE_IDS]),
        set(sorted(channel_ids)[:_MAX_REFERENCE_IDS]),
    )


def _slack_message_invocation(
    *,
    event_type: str,
    subtype: str | None,
    author_type: ExternalChannelPrincipalAuthorType,
    provider_user_id: str | None,
    normalized_body: str,
    tenant_id: str,
    envelope: dict[str, object],
    connected_bot_user_id: str | None,
) -> bool:
    """Classify only explicit human references to the authenticated Slack bot."""
    if event_type == "app_mention":
        return True
    if (
        subtype is not None
        or author_type is not ExternalChannelPrincipalAuthorType.HUMAN
    ):
        return False
    target_user_ids = _connected_slack_bot_user_ids(
        tenant_id=tenant_id,
        envelope=envelope,
        connected_bot_user_id=connected_bot_user_id,
    )
    if not target_user_ids or provider_user_id in target_user_ids:
        return False
    return any(
        (match.group(1) or match.group(2)) in target_user_ids
        for match in _SLACK_USER_REFERENCE.finditer(normalized_body)
    )


def _connected_slack_bot_user_ids(
    *,
    tenant_id: str,
    envelope: dict[str, object],
    connected_bot_user_id: str | None,
) -> set[str]:
    """Return configured or authenticated callback Bot User identities."""
    user_ids: set[str] = set()
    if isinstance(connected_bot_user_id, str) and _valid_slack_user_id(
        connected_bot_user_id
    ):
        user_ids.add(connected_bot_user_id)
    authorizations = envelope.get("authorizations")
    if not isinstance(authorizations, list):
        return user_ids
    for authorization in authorizations:
        if (
            isinstance(authorization, dict)
            and authorization.get("is_bot") is True
            and authorization.get("team_id") == tenant_id
        ):
            user_id = authorization.get("user_id")
            if isinstance(user_id, str) and _valid_slack_user_id(user_id):
                user_ids.add(user_id)
    return user_ids


def _valid_slack_user_id(value: str) -> bool:
    return len(value) > 1 and value[0] in {"U", "W"} and value.isalnum()


def _channel_display_name(channel: dict[str, object]) -> str | None:
    """Return one display-ready Slack channel label."""
    name = channel.get("name")
    if isinstance(name, str) and name.strip():
        return f"#{name.strip()}"
    return None


def _approval_message_payload(
    approval_url: str,
    *,
    participant_label: str,
    participant_provider_user_id: str,
) -> dict[str, object]:
    """Render one accessible Block Kit access-approval message."""
    participant = f"{participant_label} ({participant_provider_user_id})"
    return {
        "text": (f"Approval is required before {participant} can invoke the Agent."),
        "blocks": [
            {
                "type": "header",
                "text": {"type": "plain_text", "text": "Approval required"},
            },
            {
                "type": "section",
                "text": {
                    "type": "plain_text",
                    "text": (
                        f"Participant: {participant_label} "
                        f"({participant_provider_user_id})\n"
                        "Approve this participant before the Agent can respond."
                    ),
                },
            },
            {
                "type": "actions",
                "elements": [
                    {
                        "type": "button",
                        "text": {"type": "plain_text", "text": "Review access"},
                        "url": approval_url,
                        "action_id": "azents_external_channel_access_review",
                    }
                ],
            },
        ],
    }


def _bounded_text(value: object) -> str:
    if not isinstance(value, str):
        return ""
    encoded = value.encode()
    if len(encoded) <= _MAX_NORMALIZED_TEXT_BYTES:
        return value
    clipped = encoded[:_MAX_NORMALIZED_TEXT_BYTES].decode(errors="ignore")
    return f"{clipped}\n[Slack message truncated by Azents]"


def _normalized_message_body(
    message: dict[str, object],
    *,
    trusted_block_projection: bool,
) -> str:
    """Prefer Slack fallback text and derive readable block-only content."""
    fallback = message.get("text")
    if isinstance(fallback, str) and fallback.strip():
        return _bounded_text(fallback)
    block_text = (
        projected_slack_blocks_text(message.get("blocks"))
        if trusted_block_projection
        else slack_blocks_text(message.get("blocks"))
    )
    return _bounded_text(block_text)


def _attachment_metadata(
    *,
    blocks: object,
    files: object,
    files_truncated: object,
) -> dict[str, object] | None:
    metadata: dict[str, object] = {}
    block_metadata = _block_attachment_metadata(blocks)
    if block_metadata is not None:
        metadata["blocks"] = block_metadata
    file_metadata = _file_attachment_metadata(files)
    if file_metadata:
        metadata["files"] = file_metadata
        metadata["files_truncated"] = (
            files_truncated is True
            or isinstance(files, list)
            and len(files) > MAX_EXTERNAL_CHANNEL_FILES
        )
    return metadata or None


def _block_attachment_metadata(value: object) -> dict[str, object] | None:
    if not isinstance(value, list) or not value:
        return None
    block_types = [
        block.get("type")
        for block in value[:_MAX_ATTACHMENT_TYPES]
        if isinstance(block, dict) and isinstance(block.get("type"), str)
    ]
    return {
        "block_count": len(value),
        "block_types": block_types,
        "truncated": len(value) > _MAX_ATTACHMENT_TYPES,
    }


def _file_attachment_metadata(value: object) -> list[dict[str, object]]:
    if not isinstance(value, list):
        return []
    metadata: list[dict[str, object]] = []
    for raw_file in value[:MAX_EXTERNAL_CHANNEL_FILES]:
        if not isinstance(raw_file, dict):
            continue
        metadata.append(normalize_slack_file_metadata(raw_file).model_dump(mode="json"))
    return metadata


def normalize_slack_file_metadata(
    raw_file: dict[str, object],
) -> ExternalChannelFileMetadata:
    """Normalize current or event-carried Slack file metadata identically."""
    provider_file_id = _bounded_file_string(raw_file.get("id"))
    name = _bounded_file_string(raw_file.get("name"))
    title = _bounded_file_string(raw_file.get("title"))
    media_type = _bounded_file_string(raw_file.get("mimetype"))
    mode = _bounded_file_string(raw_file.get("mode"))
    external_type = _bounded_file_string(raw_file.get("external_type"))
    file_access = _bounded_file_string(raw_file.get("file_access"))
    declared_size, invalid_size = _file_declared_size(raw_file.get("size"))
    external = (
        raw_file.get("is_external") is True
        or external_type is not None
        or mode in {"external", "remote"}
    )
    unsupported_reason: ExternalChannelFileUnsupportedReason | None = None
    if file_access == "check_file_info":
        unsupported_reason = ExternalChannelFileUnsupportedReason.SLACK_CONNECT_FILE
    elif external:
        unsupported_reason = ExternalChannelFileUnsupportedReason.EXTERNAL_FILE
    elif provider_file_id is None:
        unsupported_reason = ExternalChannelFileUnsupportedReason.MISSING_FILE_ID
    elif invalid_size:
        unsupported_reason = ExternalChannelFileUnsupportedReason.INVALID_SIZE
    elif mode is None or declared_size is None or (name is None and title is None):
        unsupported_reason = ExternalChannelFileUnsupportedReason.SPARSE_FILE
    elif mode != "hosted":
        unsupported_reason = ExternalChannelFileUnsupportedReason.UNSUPPORTED_MODE
    return ExternalChannelFileMetadata(
        provider=ExternalChannelProvider.SLACK,
        provider_file_id=provider_file_id,
        name=name,
        title=title,
        media_type=media_type,
        declared_size=declared_size,
        mode=mode,
        external=external,
        file_access=file_access,
        supported=unsupported_reason is None,
        unsupported_reason=unsupported_reason,
    )


def _bounded_file_string(value: object) -> str | None:
    if not isinstance(value, str) or not value:
        return None
    return value[:MAX_EXTERNAL_CHANNEL_FILE_TEXT_LENGTH]


def _file_declared_size(value: object) -> tuple[int | None, bool]:
    if value is None:
        return None, False
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        return None, True
    return value, False


def _normalized_size(
    body: str | None,
    attachment_metadata: dict[str, object] | None,
) -> int:
    return len((body or "").encode()) + len(
        json.dumps(
            attachment_metadata,
            separators=(",", ":"),
            sort_keys=True,
        ).encode()
        if attachment_metadata is not None
        else b""
    )


def _slack_timestamp(value: str | None) -> datetime.datetime | None:
    if value is None:
        return None
    seconds, separator, fraction = value.partition(".")
    if not seconds.isdigit() or (separator and not fraction.isdigit()):
        return None
    microseconds = int((fraction + "000000")[:6]) if separator else 0
    try:
        return datetime.datetime.fromtimestamp(
            int(seconds),
            datetime.UTC,
        ).replace(microsecond=microseconds)
    except OverflowError, OSError, ValueError:
        return None


def _revision_key(*, message_ts: str) -> str:
    """Return one immutable original snapshot identity."""
    return f"original:{message_ts}"
