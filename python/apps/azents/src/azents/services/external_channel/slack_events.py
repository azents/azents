"""Slack event normalization and bounded conversation API operations."""

import datetime
import hashlib
import json
import re
from dataclasses import dataclass
from typing import Literal
from urllib.parse import urlsplit

import httpx

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
from azents.services.external_channel.slack_blocks import (
    projected_slack_blocks_text,
    slack_blocks_text,
)
from azents.services.external_channel.slack_endpoint import slack_api_base_url

_MAX_NORMALIZED_TEXT_BYTES = 64 * 1024
_MAX_ATTACHMENT_TYPES = 32
SLACK_MARKDOWN_TEXT_MAX_LENGTH = 12_000
_MAX_REFERENCE_IDS = 20
_SLACK_USER_REFERENCE = re.compile(r"<@([A-Z0-9]+)(?:\|[^>]+)?>|@([UW][A-Z0-9]+)")
_SLACK_CHANNEL_REFERENCE = re.compile(
    r"<#([CG][A-Z0-9]+)(?:\|[^>]+)?>|#([CG][A-Z0-9]+)"
)


class SlackEventNormalizationError(ValueError):
    """An admitted Slack envelope is malformed for asynchronous processing."""


class SlackEventExcluded(SlackEventNormalizationError):
    """An admitted event is intentionally outside the External Channel scope."""


class SlackProviderError(RuntimeError):
    """Base class for controlled Slack Web API failures."""


class SlackProviderRateLimited(SlackProviderError):
    """Slack asked the inbound hydrator to retry after a bounded delay."""

    def __init__(self, retry_after_seconds: int) -> None:
        super().__init__("Slack thread hydration is rate limited.")
        self.retry_after_seconds = max(1, retry_after_seconds)


class SlackProviderTemporaryError(SlackProviderError):
    """Slack or the network is temporarily unavailable."""


class SlackProviderRequestRejected(SlackProviderTemporaryError):
    """Slack returned a confirmed provider-specific request rejection."""

    def __init__(self, error_code: str) -> None:
        super().__init__("Slack rejected the provider request.")
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
class SlackFileDownloadInfo:
    """Current provider metadata and private URL for one Slack-hosted file."""

    metadata: ExternalChannelFileMetadata
    private_url: str | None


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
    )


def normalize_projected_slack_event(
    *,
    event_type: str,
    tenant_id: str,
    envelope: dict[str, object],
) -> SlackConnectionRevocation | SlackNormalizedMessage:
    """Normalize one Azents-projected admitted Slack event."""
    return _normalize_slack_event(
        event_type=event_type,
        tenant_id=tenant_id,
        envelope=envelope,
        trusted_block_projection=True,
    )


def _normalize_slack_event(
    *,
    event_type: str,
    tenant_id: str,
    envelope: dict[str, object],
    trusted_block_projection: bool,
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
    if event_type == "app_mention":
        if subtype not in {None, "bot_message"}:
            raise SlackEventExcluded("Slack mention subtype is not supported.")
        message = event
        revision_kind = ExternalChannelMessageRevisionKind.ORIGINAL
        lifecycle = ExternalChannelMessageLifecycle.CURRENT
        message_ts = _required_string(message, "ts")
        provider_updated_at = None
    elif subtype in {None, "bot_message"}:
        message = event
        revision_kind = ExternalChannelMessageRevisionKind.ORIGINAL
        lifecycle = ExternalChannelMessageLifecycle.CURRENT
        message_ts = _required_string(message, "ts")
        provider_updated_at = None
    elif subtype == "message_changed":
        raw_message = event.get("message")
        if not isinstance(raw_message, dict):
            raise SlackEventNormalizationError("Slack edited message is missing.")
        message = raw_message
        message_ts = _required_string(message, "ts")
        revision_kind = ExternalChannelMessageRevisionKind.EDIT
        lifecycle = ExternalChannelMessageLifecycle.EDITED
        provider_updated_at = _slack_timestamp(
            _edited_timestamp(message) or _optional_string(event, "event_ts")
        )
    elif subtype == "message_deleted":
        raw_previous = event.get("previous_message")
        previous = raw_previous if isinstance(raw_previous, dict) else {}
        message_ts = _required_string(event, "deleted_ts")
        message = previous
        revision_kind = ExternalChannelMessageRevisionKind.DELETE
        lifecycle = ExternalChannelMessageLifecycle.DELETED
        provider_updated_at = _slack_timestamp(
            _optional_string(event, "event_ts") or message_ts
        )
    else:
        raise SlackEventExcluded(
            "Slack message subtype is outside the configured scope."
        )

    root_thread_ts = _optional_string(message, "thread_ts") or message_ts
    author_type, provider_user_id = _author(message)
    normalized_body = (
        None
        if revision_kind is ExternalChannelMessageRevisionKind.DELETE
        else _normalized_message_body(
            message,
            trusted_block_projection=trusted_block_projection,
        )
    )
    attachment_metadata = _attachment_metadata(
        blocks=message.get("blocks"),
        files=message.get("files"),
        files_truncated=message.get("files_truncated"),
    )
    normalized_size = _normalized_size(normalized_body, attachment_metadata)
    provider_created_at = _slack_timestamp(message_ts)
    provider_position = slack_provider_position(message_ts)
    revision_key = _revision_key(
        revision_kind=revision_kind,
        message_ts=message_ts,
        event=event,
        message=message,
        normalized_body=normalized_body,
    )
    invocation = (
        event_type == "app_mention"
        and author_type is ExternalChannelPrincipalAuthorType.HUMAN
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


class SlackConversationClient:
    """Bounded Slack Web API adapter for inbound hydration and access control."""

    def __init__(self, http_client: httpx.AsyncClient) -> None:
        self.http_client = http_client

    async def fetch_conversation_access(
        self,
        *,
        bot_token: str,
        channel_id: str,
    ) -> SlackConversationAccess:
        """Validate App membership and unsupported Slack Connect state."""
        response = await self._request(
            "GET",
            "/conversations.info",
            bot_token=bot_token,
            params={"channel": channel_id, "include_num_members": "false"},
        )
        payload = self._success_payload(response)
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
        response = await self._request(
            "GET",
            "/conversations.info",
            bot_token=bot_token,
            params={"channel": channel_id, "include_num_members": "false"},
        )
        payload = self._success_payload(response)
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
            response = await self._request(
                "GET",
                "/bots.info",
                bot_token=bot_token,
                params={"bot": provider_user_id.removeprefix("bot:")},
            )
            payload = self._success_payload(response)
            bot = payload.get("bot")
            if not isinstance(bot, dict):
                raise SlackProviderTemporaryError("Slack bot response is malformed.")
            name = bot.get("name")
            return name if isinstance(name, str) and name else None
        if provider_user_id.startswith("app:"):
            return None
        response = await self._request(
            "GET",
            "/users.info",
            bot_token=bot_token,
            params={"user": provider_user_id},
        )
        payload = self._success_payload(response)
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
        params: dict[str, str | int] = {
            "channel": channel_id,
            "ts": root_thread_ts,
            "limit": limit,
            "inclusive": "true",
        }
        if cursor is not None:
            params["cursor"] = cursor
        response = await self._request(
            "GET",
            "/conversations.replies",
            bot_token=bot_token,
            params=params,
        )
        payload = self._success_payload(response)
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

    async def get_permalink(
        self,
        *,
        bot_token: str,
        channel_id: str,
        message_ts: str,
    ) -> str | None:
        """Resolve a provider-validated permalink for one Slack message."""
        response = await self._request(
            "GET",
            "/chat.getPermalink",
            bot_token=bot_token,
            params={"channel": channel_id, "message_ts": message_ts},
        )
        payload = self._success_payload(response)
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
        response = await self._request(
            "GET",
            "/files.info",
            bot_token=bot_token,
            params={"file": provider_file_id},
        )
        payload = self._success_payload(response)
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
        if private_url is not None:
            parsed = urlsplit(private_url)
            if parsed.scheme != "https" or not parsed.netloc:
                raise SlackProviderTemporaryError(
                    "Slack returned an invalid private file URL."
                )
        return SlackFileDownloadInfo(
            metadata=metadata,
            private_url=private_url,
        )

    async def download_private_file(
        self,
        *,
        bot_token: str,
        private_url: str,
        max_bytes: int,
    ) -> bytes:
        """Read one authenticated private file while enforcing an actual-byte cap."""
        parsed = urlsplit(private_url)
        if parsed.scheme != "https" or not parsed.netloc:
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
                content_length = response.headers.get("Content-Length")
                if content_length is not None:
                    try:
                        declared_response_size = int(content_length)
                    except ValueError:
                        declared_response_size = None
                    if (
                        declared_response_size is not None
                        and declared_response_size > max_bytes
                    ):
                        raise SlackProviderFileTooLarge(
                            "Slack file exceeds the configured limit."
                        )
                body = bytearray()
                async for chunk in response.aiter_bytes():
                    if len(body) + len(chunk) > max_bytes:
                        raise SlackProviderFileTooLarge(
                            "Slack file exceeds the configured limit."
                        )
                    body.extend(chunk)
                return bytes(body)
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
    ) -> SlackControlMessageResult:
        """Attempt one ordinary thread reply containing an approval link."""
        try:
            response = await self._request(
                "POST",
                "/chat.postMessage",
                bot_token=bot_token,
                json_body={
                    "channel": channel_id,
                    "thread_ts": thread_ts,
                    **_approval_message_payload(
                        approval_url,
                        participant_label=participant_label,
                        participant_provider_user_id=participant_provider_user_id,
                    ),
                    "unfurl_links": False,
                    "unfurl_media": False,
                },
            )
            payload = self._success_payload(response)
        except SlackProviderPermissionDenied:
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
                error_summary="Slack cannot post to the linked conversation.",
            )
        except SlackProviderRateLimited:
            return SlackControlMessageResult(
                status="failed",
                provider_message_key=None,
                error_kind="rate_limited",
                error_summary="Slack rate limited the control message attempt.",
            )
        except SlackProviderRequestRejected as error:
            return SlackControlMessageResult(
                status="failed",
                provider_message_key=None,
                error_kind="provider_rejected",
                error_summary=(
                    f"Slack rejected the control message ({error.error_code})."
                ),
            )
        except SlackProviderTemporaryError:
            return SlackControlMessageResult(
                status="unknown",
                provider_message_key=None,
                error_kind="provider_ambiguous",
                error_summary="Slack delivery outcome is unknown.",
            )
        ts = payload.get("ts")
        if not isinstance(ts, str) or not ts:
            return SlackControlMessageResult(
                status="unknown",
                provider_message_key=None,
                error_kind="provider_response_invalid",
                error_summary="Slack did not return a message identity.",
            )
        return SlackControlMessageResult(
            status="delivered",
            provider_message_key=f"slack:{tenant_id}:{channel_id}:{ts}",
            error_kind=None,
            error_summary=None,
        )

    async def post_message(
        self,
        *,
        bot_token: str,
        tenant_id: str,
        channel_id: str,
        thread_ts: str,
        markdown_text: str,
    ) -> SlackControlMessageResult:
        """Attempt one ordinary thread message without retry."""
        if len(markdown_text) > SLACK_MARKDOWN_TEXT_MAX_LENGTH:
            return SlackControlMessageResult(
                status="failed",
                provider_message_key=None,
                error_kind="provider_payload_invalid",
                error_summary="Slack Markdown text exceeds the supported limit.",
            )
        return await self._attempt_message_operation(
            bot_token=bot_token,
            tenant_id=tenant_id,
            channel_id=channel_id,
            path="/chat.postMessage",
            json_body={
                "channel": channel_id,
                "thread_ts": thread_ts,
                "markdown_text": markdown_text,
                "unfurl_links": False,
                "unfurl_media": False,
            },
            expected_message_ts=None,
        )

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
        return await self._attempt_message_operation(
            bot_token=bot_token,
            tenant_id=tenant_id,
            channel_id=channel_id,
            path="/chat.update",
            json_body={
                "channel": channel_id,
                "ts": message_ts,
                "text": text,
                **({"blocks": blocks} if blocks is not None else {}),
                "parse": "none",
                "link_names": False,
            },
            expected_message_ts=message_ts,
        )

    async def post_blocks(
        self,
        *,
        bot_token: str,
        tenant_id: str,
        channel_id: str,
        thread_ts: str,
        text: str,
        blocks: list[dict[str, object]],
    ) -> SlackControlMessageResult:
        """Post one operational Block Kit message without retry."""
        return await self._attempt_message_operation(
            bot_token=bot_token,
            tenant_id=tenant_id,
            channel_id=channel_id,
            path="/chat.postMessage",
            json_body={
                "channel": channel_id,
                "thread_ts": thread_ts,
                "text": text,
                "blocks": blocks,
                "mrkdwn": False,
                "parse": "none",
                "link_names": False,
                "unfurl_links": False,
                "unfurl_media": False,
            },
            expected_message_ts=None,
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
        return await self._attempt_message_operation(
            bot_token=bot_token,
            tenant_id=tenant_id,
            channel_id=channel_id,
            path="/chat.delete",
            json_body={"channel": channel_id, "ts": message_ts},
            expected_message_ts=message_ts,
        )

    async def _attempt_message_operation(
        self,
        *,
        bot_token: str,
        tenant_id: str,
        channel_id: str,
        path: str,
        json_body: dict[str, object],
        expected_message_ts: str | None,
    ) -> SlackControlMessageResult:
        """Map one Slack mutation into a sanitized at-most-once outcome."""
        try:
            response = await self._request(
                "POST",
                path,
                bot_token=bot_token,
                json_body=json_body,
            )
            payload = self._success_payload(response)
        except SlackProviderPermissionDenied:
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

    async def _request(
        self,
        method: str,
        path: str,
        *,
        bot_token: str,
        params: dict[str, str | int] | None = None,
        json_body: dict[str, object] | None = None,
    ) -> httpx.Response:
        try:
            response = await self.http_client.request(
                method,
                f"{slack_api_base_url()}{path}",
                headers={"Authorization": f"Bearer {bot_token}"},
                params=params,
                json=json_body,
            )
        except httpx.RequestError as error:
            raise SlackProviderTemporaryError(
                "Slack request did not produce a response."
            ) from error
        if response.status_code == 429:
            retry_after = response.headers.get("Retry-After", "1")
            try:
                retry_after_seconds = int(retry_after)
            except ValueError:
                retry_after_seconds = 1
            raise SlackProviderRateLimited(retry_after_seconds)
        if response.status_code >= 500:
            raise SlackProviderTemporaryError("Slack is temporarily unavailable.")
        return response

    @staticmethod
    def _success_payload(response: httpx.Response) -> dict[str, object]:
        try:
            payload: object = response.json()
        except ValueError as error:
            raise SlackProviderTemporaryError(
                "Slack response body is not valid JSON."
            ) from error
        if not isinstance(payload, dict):
            raise SlackProviderTemporaryError("Slack response body is malformed.")
        if response.status_code < 400 and payload.get("ok") is True:
            return payload
        error_code = payload.get("error")
        if error_code == "missing_scope":
            raise SlackProviderPermissionDenied("Slack App permissions are incomplete.")
        if error_code in {
            "account_inactive",
            "invalid_auth",
            "not_authed",
            "not_allowed_token_type",
            "token_revoked",
        }:
            raise SlackProviderCredentialsInvalid(
                "Slack rejected the configured credential."
            )
        if error_code in {
            "channel_not_found",
            "is_archived",
            "not_in_channel",
            "thread_not_found",
        }:
            raise SlackProviderResourceUnavailable(
                "Slack conversation is unavailable to the App."
            )
        if error_code == "message_not_found":
            raise SlackProviderMessageNotFound(
                "Slack no longer contains the requested message."
            )
        if error_code in {"file_deleted", "file_not_found"}:
            raise SlackProviderFileNotFound(
                "Slack no longer exposes the requested file."
            )
        normalized_error_code = (
            error_code
            if isinstance(error_code, str)
            and re.fullmatch(r"[a-z0-9_]{1,80}", error_code)
            else "unknown_error"
        )
        raise SlackProviderRequestRejected(normalized_error_code)


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


def _edited_timestamp(message: dict[str, object]) -> str | None:
    edited = message.get("edited")
    if not isinstance(edited, dict):
        return None
    return _optional_string(edited, "ts")


def _revision_key(
    *,
    revision_kind: ExternalChannelMessageRevisionKind,
    message_ts: str,
    event: dict[str, object],
    message: dict[str, object],
    normalized_body: str | None,
) -> str:
    if revision_kind is ExternalChannelMessageRevisionKind.ORIGINAL:
        return f"original:{message_ts}"
    if revision_kind is ExternalChannelMessageRevisionKind.DELETE:
        return f"delete:{message_ts}"
    lifecycle_ts = (
        _edited_timestamp(message) or _optional_string(event, "event_ts") or message_ts
    )
    body_digest = hashlib.sha256((normalized_body or "").encode()).hexdigest()[:16]
    return f"edit:{lifecycle_ts}:{body_digest}"
