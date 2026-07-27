"""Discord Gateway message projection and normalization."""

import datetime
import hashlib
import json
from dataclasses import dataclass

from azents.core.enums import (
    ExternalChannelEventEligibilityState,
    ExternalChannelEventStatus,
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
from azents.repos.external_channel.data import ExternalChannelEventCreate
from azents.services.external_channel.discord_gateway import DiscordGatewayDispatch

_MAX_DISCORD_MESSAGE_CONTENT_BYTES = 64 * 1024
_MESSAGE_EVENT_TYPES = {
    "MESSAGE_CREATE": "discord_message_create",
    "MESSAGE_UPDATE": "discord_message_update",
    "MESSAGE_DELETE": "discord_message_delete",
}


class DiscordEventNormalizationError(ValueError):
    """A projected Discord event cannot become a canonical message revision."""


class DiscordEventExcluded(DiscordEventNormalizationError):
    """A projected Discord event is intentionally outside the supported scope."""


class DiscordMessageContentUnavailable(DiscordEventNormalizationError):
    """Discord omitted message content required by the configured ingress contract."""


@dataclass(frozen=True)
class DiscordNormalizedMessage:
    """One Discord message lifecycle mutation independent from raw Gateway payloads."""

    tenant_id: str
    channel_id: str
    thread_id: str | None
    parent_channel_id: str | None
    message_id: str
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


def project_discord_gateway_dispatch(
    *,
    connection_id: str,
    provider_app_id: str | None,
    target_guild_id: str,
    dispatch: DiscordGatewayDispatch,
    received_at: datetime.datetime,
) -> ExternalChannelEventCreate | None:
    """Build a bounded canonical event without retaining raw Gateway payload data."""
    event_type = _MESSAGE_EVENT_TYPES.get(dispatch.event_name)
    if event_type is None:
        return None
    message = dispatch.data
    guild_id = _required_string(message, "guild_id")
    if guild_id != target_guild_id:
        return None
    message_id = _required_string(message, "id")
    channel_id = _required_string(message, "channel_id")
    if not dispatch.session_id:
        raise ValueError("Discord Gateway Dispatch is missing a session ID.")
    projection: dict[str, object] = {
        "id": message_id,
        "channel_id": channel_id,
        "guild_id": guild_id,
    }
    for key in ("type", "timestamp", "edited_timestamp"):
        value = message.get(key)
        if isinstance(value, str) and value:
            projection[key] = value
    content = message.get("content")
    if isinstance(content, str):
        if len(content.encode()) > _MAX_DISCORD_MESSAGE_CONTENT_BYTES:
            raise ValueError("Discord message content exceeds the size limit.")
        projection["content"] = content
    author = message.get("author")
    if isinstance(author, dict):
        projected_author = _project_author(author)
        if projected_author:
            projection["author"] = projected_author
    attachments = message.get("attachments")
    if isinstance(attachments, list):
        projection["attachments"] = _project_attachments(
            attachments,
            source_channel_id=channel_id,
        )
        projection["attachments_truncated"] = (
            len(attachments) > MAX_EXTERNAL_CHANNEL_FILES
        )
    thread = message.get("thread")
    if isinstance(thread, dict):
        projected_thread = _project_thread(thread)
        if projected_thread:
            projection["thread"] = projected_thread
    mentions = message.get("mentions")
    if isinstance(mentions, list):
        projection["mentions"] = _project_mentions(mentions)
    return ExternalChannelEventCreate(
        connection_id=connection_id,
        provider_event_id=(
            f"discord-gateway:{dispatch.session_id}:{dispatch.sequence}"
        ),
        transport_envelope_id=(
            f"discord-gateway:{dispatch.session_id}:{dispatch.sequence}"
        ),
        event_type=event_type,
        provider_app_id=provider_app_id,
        provider_tenant_id=guild_id,
        provider_enterprise_id=None,
        resource_correlation_key=f"{guild_id}:{channel_id}",
        eligibility_state=ExternalChannelEventEligibilityState.UNCLASSIFIED,
        envelope={"message": projection},
        status=ExternalChannelEventStatus.ACCEPTED,
        provider_occurred_at=_discord_timestamp(message.get("timestamp")),
        received_at=received_at,
    )


def normalize_projected_discord_event(
    *,
    event_type: str,
    tenant_id: str,
    envelope: dict[str, object],
    connected_bot_user_id: str | None,
) -> DiscordNormalizedMessage:
    """Normalize one bounded Discord message event into a canonical revision."""
    revision_kind, lifecycle = _message_lifecycle(event_type)
    raw_message = envelope.get("message")
    if not isinstance(raw_message, dict):
        raise DiscordEventNormalizationError("Discord projected message is missing.")
    guild_id = _required_string(raw_message, "guild_id")
    if guild_id != tenant_id:
        raise DiscordEventExcluded("Discord event Guild does not match the connection.")
    message_id = _required_string(raw_message, "id")
    channel_id = _required_string(raw_message, "channel_id")
    author_type, provider_user_id = _author(raw_message.get("author"))
    if connected_bot_user_id is not None and provider_user_id == connected_bot_user_id:
        author_type = ExternalChannelPrincipalAuthorType.BOT
    normalized_body = (
        None
        if revision_kind is ExternalChannelMessageRevisionKind.DELETE
        else _optional_content(raw_message)
    )
    attachment_metadata = _attachment_metadata(raw_message)
    created_at = _discord_timestamp(raw_message.get("timestamp"))
    updated_at = _discord_timestamp(raw_message.get("edited_timestamp"))
    thread_id, parent_channel_id = _thread_identity(raw_message)
    invocation = _mentions_connected_bot(
        raw_message.get("mentions"),
        connected_bot_user_id=connected_bot_user_id,
    )
    return DiscordNormalizedMessage(
        tenant_id=tenant_id,
        channel_id=channel_id,
        thread_id=thread_id,
        parent_channel_id=parent_channel_id,
        message_id=message_id,
        provider_message_key=f"discord:{tenant_id}:{message_id}",
        provider_position=_discord_position(message_id),
        revision_key=_revision_key(
            message_id=message_id,
            revision_kind=revision_kind,
            created_at=created_at,
            updated_at=updated_at,
            normalized_body=normalized_body,
        ),
        revision_kind=revision_kind,
        lifecycle=lifecycle,
        author_type=author_type,
        provider_user_id=provider_user_id,
        normalized_body=normalized_body,
        attachment_metadata=attachment_metadata,
        normalized_size=_normalized_size(normalized_body, attachment_metadata),
        provider_created_at=created_at,
        provider_updated_at=updated_at,
        invocation=invocation,
    )


def _required_string(payload: dict[str, object], key: str) -> str:
    value = payload.get(key)
    if not isinstance(value, str) or not value:
        raise ValueError(f"Discord message field '{key}' is missing.")
    if len(value) > MAX_EXTERNAL_CHANNEL_FILE_TEXT_LENGTH:
        raise ValueError(f"Discord message field '{key}' is too long.")
    return value


def _project_author(author: dict[str, object]) -> dict[str, object]:
    """Retain provenance fields only; exclude Discord profile URLs and raw objects."""
    projected: dict[str, object] = {}
    author_id = author.get("id")
    if isinstance(author_id, str) and author_id:
        projected["id"] = author_id[:MAX_EXTERNAL_CHANNEL_FILE_TEXT_LENGTH]
    for key in ("bot", "system"):
        value = author.get(key)
        if isinstance(value, bool):
            projected[key] = value
    for key in ("username", "global_name"):
        value = author.get(key)
        if isinstance(value, str) and value:
            projected[key] = value[:MAX_EXTERNAL_CHANNEL_FILE_TEXT_LENGTH]
    return projected


def _project_thread(thread: dict[str, object]) -> dict[str, object]:
    """Retain IDs needed to distinguish a Discord thread from its parent."""
    projected: dict[str, object] = {}
    for key in ("id", "parent_id"):
        value = _bounded_string(thread.get(key))
        if value is not None:
            projected[key] = value
    return projected


def _project_mentions(mentions: list[object]) -> list[dict[str, object]]:
    """Retain bounded mentioned-user identifiers without profile fields or URLs."""
    projected: list[dict[str, object]] = []
    for mention in mentions[:MAX_EXTERNAL_CHANNEL_FILES]:
        if not isinstance(mention, dict):
            continue
        mention_id = _bounded_string(mention.get("id"))
        if mention_id is not None:
            projected.append({"id": mention_id})
    return projected


def _project_attachments(
    attachments: list[object],
    *,
    source_channel_id: str,
) -> dict[str, object]:
    """Persist bounded provider-neutral metadata without Discord CDN or proxy URLs."""
    files: list[dict[str, object]] = []
    for attachment in attachments[:MAX_EXTERNAL_CHANNEL_FILES]:
        if not isinstance(attachment, dict):
            continue
        provider_file_id = _bounded_string(attachment.get("id"))
        declared_size = attachment.get("size")
        if not isinstance(declared_size, int) or isinstance(declared_size, bool):
            metadata = ExternalChannelFileMetadata(
                provider=ExternalChannelProvider.DISCORD,
                provider_file_id=provider_file_id,
                name=_bounded_string(attachment.get("filename")),
                title=None,
                media_type=_bounded_string(attachment.get("content_type")),
                declared_size=None,
                mode=None,
                external=False,
                file_access=None,
                supported=False,
                unsupported_reason=ExternalChannelFileUnsupportedReason.INVALID_SIZE,
            )
        elif provider_file_id is None:
            metadata = ExternalChannelFileMetadata(
                provider=ExternalChannelProvider.DISCORD,
                provider_file_id=None,
                name=_bounded_string(attachment.get("filename")),
                title=None,
                media_type=_bounded_string(attachment.get("content_type")),
                declared_size=declared_size if declared_size >= 0 else None,
                mode=None,
                external=False,
                file_access=None,
                supported=False,
                unsupported_reason=ExternalChannelFileUnsupportedReason.MISSING_FILE_ID,
            )
        elif declared_size < 0:
            metadata = ExternalChannelFileMetadata(
                provider=ExternalChannelProvider.DISCORD,
                provider_file_id=provider_file_id,
                name=_bounded_string(attachment.get("filename")),
                title=None,
                media_type=_bounded_string(attachment.get("content_type")),
                declared_size=None,
                mode=None,
                external=False,
                file_access=None,
                supported=False,
                unsupported_reason=ExternalChannelFileUnsupportedReason.INVALID_SIZE,
            )
        else:
            metadata = ExternalChannelFileMetadata(
                provider=ExternalChannelProvider.DISCORD,
                provider_file_id=provider_file_id,
                name=_bounded_string(attachment.get("filename")),
                title=None,
                media_type=_bounded_string(attachment.get("content_type")),
                declared_size=declared_size,
                mode=None,
                external=False,
                file_access=None,
                supported=True,
                unsupported_reason=None,
            )
        projected_metadata = metadata.model_dump(mode="json")
        projected_metadata["source_channel_id"] = source_channel_id
        files.append(projected_metadata)
    return {"files": files}


def _bounded_string(value: object) -> str | None:
    if not isinstance(value, str) or not value:
        return None
    return value[:MAX_EXTERNAL_CHANNEL_FILE_TEXT_LENGTH]


def _message_lifecycle(
    event_type: str,
) -> tuple[ExternalChannelMessageRevisionKind, ExternalChannelMessageLifecycle]:
    mapping = {
        "discord_message_create": (
            ExternalChannelMessageRevisionKind.ORIGINAL,
            ExternalChannelMessageLifecycle.CURRENT,
        ),
        "discord_message_update": (
            ExternalChannelMessageRevisionKind.EDIT,
            ExternalChannelMessageLifecycle.EDITED,
        ),
        "discord_message_delete": (
            ExternalChannelMessageRevisionKind.DELETE,
            ExternalChannelMessageLifecycle.DELETED,
        ),
    }
    lifecycle = mapping.get(event_type)
    if lifecycle is None:
        raise DiscordEventExcluded(
            "Discord event type is outside the configured scope."
        )
    return lifecycle


def _author(
    value: object,
) -> tuple[ExternalChannelPrincipalAuthorType, str | None]:
    if not isinstance(value, dict):
        return ExternalChannelPrincipalAuthorType.SYSTEM, None
    provider_user_id = _bounded_string(value.get("id"))
    if value.get("system") is True:
        return ExternalChannelPrincipalAuthorType.SYSTEM, provider_user_id
    if value.get("bot") is True:
        return ExternalChannelPrincipalAuthorType.BOT, provider_user_id
    return ExternalChannelPrincipalAuthorType.HUMAN, provider_user_id


def _optional_content(message: dict[str, object]) -> str | None:
    value = message.get("content")
    if value is None:
        raise DiscordMessageContentUnavailable(
            "Discord message content is unavailable for the configured connection."
        )
    if not isinstance(value, str):
        raise DiscordEventNormalizationError("Discord message content is invalid.")
    if len(value.encode()) > _MAX_DISCORD_MESSAGE_CONTENT_BYTES:
        raise DiscordEventNormalizationError("Discord message content is too large.")
    return value


def _attachment_metadata(message: dict[str, object]) -> dict[str, object] | None:
    value = message.get("attachments")
    if value is None:
        return None
    if not isinstance(value, dict):
        raise DiscordEventNormalizationError(
            "Discord attachment projection is invalid."
        )
    files = value.get("files")
    if not isinstance(files, list):
        raise DiscordEventNormalizationError("Discord attachment list is invalid.")
    return {
        "files": files,
        **({"truncated": True} if message.get("attachments_truncated") is True else {}),
    }


def _thread_identity(message: dict[str, object]) -> tuple[str | None, str | None]:
    raw_thread = message.get("thread")
    if not isinstance(raw_thread, dict):
        return None, None
    thread_id = _bounded_string(raw_thread.get("id"))
    parent_channel_id = _bounded_string(raw_thread.get("parent_id"))
    if thread_id is None:
        raise DiscordEventNormalizationError("Discord thread projection is invalid.")
    return thread_id, parent_channel_id


def _mentions_connected_bot(
    value: object,
    *,
    connected_bot_user_id: str | None,
) -> bool:
    if connected_bot_user_id is None or not isinstance(value, list):
        return False
    return any(
        isinstance(item, dict) and item.get("id") == connected_bot_user_id
        for item in value
    )


def _discord_position(message_id: str) -> str:
    if not message_id.isdigit():
        raise DiscordEventNormalizationError("Discord message ID is invalid.")
    return f"{int(message_id):020d}"


def _revision_key(
    *,
    message_id: str,
    revision_kind: ExternalChannelMessageRevisionKind,
    created_at: datetime.datetime | None,
    updated_at: datetime.datetime | None,
    normalized_body: str | None,
) -> str:
    if revision_kind is ExternalChannelMessageRevisionKind.ORIGINAL:
        return f"discord:{message_id}:original"
    if revision_kind is ExternalChannelMessageRevisionKind.DELETE:
        return f"discord:{message_id}:delete"
    timestamp = updated_at or created_at
    if timestamp is not None:
        return f"discord:{message_id}:edit:{timestamp.isoformat()}"
    body = "" if normalized_body is None else normalized_body
    return f"discord:{message_id}:edit:{hashlib.sha256(body.encode()).hexdigest()}"


def _normalized_size(
    body: str | None,
    attachment_metadata: dict[str, object] | None,
) -> int:
    body_size = 0 if body is None else len(body.encode())
    attachment_size = (
        0
        if attachment_metadata is None
        else len(json.dumps(attachment_metadata, separators=(",", ":")).encode())
    )
    return body_size + attachment_size


def _discord_timestamp(value: object) -> datetime.datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=datetime.UTC)
