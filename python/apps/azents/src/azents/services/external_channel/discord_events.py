"""Discord Gateway message projection and normalization."""

import datetime
import json
from dataclasses import dataclass

import discord

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
from azents.repos.external_channel.data import ExternalChannelTrigger
from azents.services.external_channel.discord_gateway import DiscordGatewayMessageEvent

_MAX_DISCORD_MESSAGE_CONTENT_BYTES = 64 * 1024
_MAX_DISCORD_EMBEDS = 10
_MAX_DISCORD_EMBED_FIELDS = 25
_MESSAGE_EVENT_TYPES = {
    "message_create": "discord_message_create",
}


class DiscordEventNormalizationError(ValueError):
    """A projected Discord event cannot become a canonical message revision."""


class DiscordEventExcluded(DiscordEventNormalizationError):
    """A projected Discord event is intentionally outside the supported scope."""


class DiscordMessageContentUnavailable(DiscordEventNormalizationError):
    """Discord omitted message content required by the configured ingress contract."""


@dataclass(frozen=True)
class DiscordNormalizedMessage:
    """One Discord message snapshot independent from raw Gateway payloads."""

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
    sender_display_name: str | None
    normalized_body: str | None
    attachment_metadata: dict[str, object] | None
    reference_mappings: dict[str, dict[str, str]]
    channel_display_name: str | None
    normalized_size: int
    provider_created_at: datetime.datetime | None
    provider_updated_at: datetime.datetime | None
    invocation: bool


def project_discord_gateway_event(
    *,
    connection_id: str,
    provider_app_id: str | None,
    target_guild_id: str,
    event: DiscordGatewayMessageEvent,
    received_at: datetime.datetime,
) -> ExternalChannelTrigger | None:
    """Build a canonical event exclusively from typed discord.py objects."""
    event_type = _MESSAGE_EVENT_TYPES[event.event_type]
    guild_id = str(event.channel.guild.id)
    if guild_id != target_guild_id:
        return None
    projection = _project_discord_sdk_event(event=event, guild_id=guild_id)
    channel_id = _required_string(projection, "channel_id")
    provider_event_id = _discord_gateway_event_id(
        event_type=event_type,
        projection=projection,
    )
    return ExternalChannelTrigger(
        connection_id=connection_id,
        provider_event_id=provider_event_id,
        transport_envelope_id=provider_event_id,
        event_type=event_type,
        provider_app_id=provider_app_id,
        provider_tenant_id=guild_id,
        provider_enterprise_id=None,
        resource_correlation_key=f"{guild_id}:{channel_id}",
        envelope={"message": projection},
        provider_occurred_at=_discord_timestamp(projection.get("timestamp")),
        received_at=received_at,
    )


def _project_discord_sdk_event(
    *,
    event: DiscordGatewayMessageEvent,
    guild_id: str,
) -> dict[str, object]:
    """Project public SDK attributes into the bounded provider-neutral envelope."""
    channel_id = str(event.channel.id)
    message = event.message
    if message is None:
        raise ValueError("Discord message event is missing its typed Message.")
    if message.guild is None or str(message.guild.id) != guild_id:
        raise ValueError("Discord Message Guild identity is invalid.")
    if message.channel.id != event.channel.id:
        raise ValueError("Discord Message channel identity is invalid.")
    source: dict[str, object] = {
        "id": str(message.id),
        "channel_id": channel_id,
        "guild_id": guild_id,
        "content": message.content,
        "timestamp": message.created_at.isoformat(),
        "author": _sdk_user(message.author),
        "mentions": [_sdk_user(mention) for mention in message.mentions],
        "attachments": [
            {
                "id": str(attachment.id),
                "filename": attachment.filename,
                "size": attachment.size,
                **(
                    {"content_type": attachment.content_type}
                    if attachment.content_type is not None
                    else {}
                ),
            }
            for attachment in message.attachments
        ],
    }
    embeds = [_sdk_embed(embed) for embed in message.embeds]
    if embeds:
        source["embeds"] = embeds
    channel_name = getattr(event.channel, "name", None)
    if isinstance(channel_name, str) and channel_name:
        source["channel_name"] = channel_name
    if isinstance(event.channel, discord.Thread):
        parent_id = event.channel.parent_id
        if parent_id == event.channel.id:
            raise ValueError("Discord Thread parent identity is invalid.")
        source["thread"] = {
            "id": channel_id,
            "parent_id": str(parent_id),
            **(
                {"name": channel_name}
                if isinstance(channel_name, str) and channel_name
                else {}
            ),
        }
        parent = event.channel.parent
        parent_name = getattr(parent, "name", None)
        if isinstance(parent_name, str) and parent_name:
            source["parent_channel_name"] = parent_name
    return project_discord_message(message=source, guild_id=guild_id)


def _sdk_user(user: discord.abc.User) -> dict[str, object]:
    """Project public Discord user attributes without profile URLs."""
    global_name = getattr(user, "global_name", None)
    return {
        "id": str(user.id),
        "username": user.name,
        **(
            {"global_name": global_name}
            if isinstance(global_name, str) and global_name
            else {}
        ),
        **({"bot": True} if user.bot else {}),
        **({"system": True} if user.system else {}),
    }


def _discord_gateway_event_id(
    *,
    event_type: str,
    projection: dict[str, object],
) -> str:
    """Return a stable provider identity without Gateway session internals."""
    guild_id = _required_string(projection, "guild_id")
    channel_id = _required_string(projection, "channel_id")
    message_id = _required_string(projection, "id")
    identity = f"discord:{event_type}:{guild_id}:{channel_id}:{message_id}"
    return identity


def project_discord_message_command_source_event(
    *,
    connection_id: str,
    provider_app_id: str,
    provider_interaction_id: str,
    guild_id: str,
    source_message: dict[str, object],
    received_at: datetime.datetime,
) -> ExternalChannelTrigger:
    """Project one selected Message Command source without raw interaction data."""
    projection = project_discord_message(message=source_message, guild_id=guild_id)
    message_id = _required_string(projection, "id")
    channel_id = _required_string(projection, "channel_id")
    return ExternalChannelTrigger(
        connection_id=connection_id,
        provider_event_id=(
            f"discord-interaction-source:{provider_interaction_id}:{message_id}"
        ),
        transport_envelope_id=None,
        event_type="discord_message_create",
        provider_app_id=provider_app_id,
        provider_tenant_id=guild_id,
        provider_enterprise_id=None,
        resource_correlation_key=f"{guild_id}:{channel_id}",
        envelope={"message": projection},
        provider_occurred_at=_discord_timestamp(source_message.get("timestamp")),
        received_at=received_at,
    )


def project_discord_message(
    *,
    message: dict[str, object],
    guild_id: str,
) -> dict[str, object]:
    """Retain bounded canonical message facts shared by Gateway and interactions."""
    message_id = _required_string(message, "id")
    channel_id = _required_string(message, "channel_id")
    projection: dict[str, object] = {
        "id": message_id,
        "channel_id": channel_id,
        "guild_id": guild_id,
    }
    for key in ("type", "timestamp", "edited_timestamp"):
        value = message.get(key)
        if isinstance(value, str) and value:
            projection[key] = value
    for key in ("channel_name", "parent_channel_name"):
        value = message.get(key)
        if isinstance(value, str) and value:
            projection[key] = value[:MAX_EXTERNAL_CHANNEL_FILE_TEXT_LENGTH]
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
    embeds = message.get("embeds")
    if isinstance(embeds, list):
        projection["embeds"] = _project_embeds(embeds)
        projection["embeds_truncated"] = len(embeds) > _MAX_DISCORD_EMBEDS
    thread = message.get("thread")
    if isinstance(thread, dict):
        projected_thread = _project_thread(thread)
        if projected_thread:
            projection["thread"] = projected_thread
    mentions = message.get("mentions")
    if isinstance(mentions, list):
        projection["mentions"] = _project_mentions(mentions)
    return projection


def normalize_projected_discord_event(
    *,
    event_type: str,
    tenant_id: str,
    envelope: dict[str, object],
    connected_bot_user_id: str | None,
) -> DiscordNormalizedMessage:
    """Normalize one bounded Discord create event into a canonical snapshot."""
    if event_type != "discord_message_create":
        raise DiscordEventExcluded(
            "Discord event type is outside the configured scope."
        )
    raw_message = envelope.get("message")
    if not isinstance(raw_message, dict):
        raise DiscordEventNormalizationError("Discord projected message is missing.")
    guild_id = _required_string(raw_message, "guild_id")
    if guild_id != tenant_id:
        raise DiscordEventExcluded("Discord event Guild does not match the connection.")
    message_id = _required_string(raw_message, "id")
    channel_id = _required_string(raw_message, "channel_id")
    author_type, provider_user_id, sender_display_name = _author(
        raw_message.get("author")
    )
    if connected_bot_user_id is not None and provider_user_id == connected_bot_user_id:
        author_type = ExternalChannelPrincipalAuthorType.BOT
    normalized_body = _optional_content(raw_message)
    attachment_metadata = _attachment_metadata(raw_message)
    created_at = _discord_timestamp(raw_message.get("timestamp"))
    updated_at = _discord_timestamp(raw_message.get("edited_timestamp"))
    thread_id, parent_channel_id = _thread_identity(raw_message)
    invocation = _mentions_connected_bot(
        raw_message.get("mentions"),
        connected_bot_user_id=connected_bot_user_id,
    )
    reference_mappings = _reference_mappings(raw_message)
    return DiscordNormalizedMessage(
        tenant_id=tenant_id,
        channel_id=channel_id,
        thread_id=thread_id,
        parent_channel_id=parent_channel_id,
        message_id=message_id,
        provider_message_key=f"discord:{tenant_id}:{message_id}",
        provider_position=_discord_position(message_id),
        revision_key=_revision_key(message_id=message_id),
        revision_kind=ExternalChannelMessageRevisionKind.ORIGINAL,
        lifecycle=ExternalChannelMessageLifecycle.CURRENT,
        author_type=author_type,
        provider_user_id=provider_user_id,
        sender_display_name=sender_display_name,
        normalized_body=normalized_body,
        attachment_metadata=attachment_metadata,
        reference_mappings=reference_mappings,
        channel_display_name=_bounded_string(raw_message.get("channel_name")),
        normalized_size=_normalized_size(
            normalized_body,
            attachment_metadata,
            reference_mappings,
        ),
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
    for key in ("id", "parent_id", "name"):
        value = _bounded_string(thread.get(key))
        if value is not None:
            projected[key] = value
    return projected


def _project_mentions(mentions: list[object]) -> list[dict[str, object]]:
    """Retain bounded mentioned-user identities without profile URLs."""
    projected: list[dict[str, object]] = []
    for mention in mentions[:MAX_EXTERNAL_CHANNEL_FILES]:
        if not isinstance(mention, dict):
            continue
        mention_id = _bounded_string(mention.get("id"))
        if mention_id is not None:
            projected_mention: dict[str, object] = {"id": mention_id}
            for key in ("username", "global_name"):
                value = _bounded_string(mention.get(key))
                if value is not None:
                    projected_mention[key] = value
            projected.append(projected_mention)
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


def _sdk_embed(embed: discord.Embed) -> dict[str, object]:
    """Project typed embed attributes without URLs, CDN locators, or raw objects."""
    return {
        "type": embed.type,
        "title": embed.title,
        "description": embed.description,
        "author": {"name": embed.author.name} if embed.author.name else {},
        "footer": {"text": embed.footer.text} if embed.footer.text else {},
        "fields": [
            {
                "name": field.name,
                "value": field.value,
                "inline": field.inline,
            }
            for field in embed.fields
        ],
        "image": {"present": bool(embed.image.url)},
        "thumbnail": {"present": bool(embed.thumbnail.url)},
    }


def _project_embeds(embeds: list[object]) -> list[dict[str, object]]:
    """Retain bounded visible Discord embed semantics without any URLs."""
    projected: list[dict[str, object]] = []
    for embed in embeds[:_MAX_DISCORD_EMBEDS]:
        if not isinstance(embed, dict):
            continue
        item: dict[str, object] = {}
        for key in ("type", "title", "description"):
            value = _bounded_string(embed.get(key))
            if value is not None:
                item[key] = value
        for source_key, destination_key, text_key in (
            ("author", "author_name", "name"),
            ("footer", "footer_text", "text"),
        ):
            source = embed.get(source_key)
            if not isinstance(source, dict):
                continue
            value = _bounded_string(source.get(text_key))
            if value is not None:
                item[destination_key] = value
        fields = embed.get("fields")
        if isinstance(fields, list):
            projected_fields: list[dict[str, object]] = []
            for field in fields[:_MAX_DISCORD_EMBED_FIELDS]:
                if not isinstance(field, dict):
                    continue
                name = _bounded_string(field.get("name"))
                value = _bounded_string(field.get("value"))
                if name is None and value is None:
                    continue
                projected_fields.append(
                    {
                        **({"name": name} if name is not None else {}),
                        **({"value": value} if value is not None else {}),
                        **({"inline": True} if field.get("inline") is True else {}),
                    }
                )
            if projected_fields:
                item["fields"] = projected_fields
                if len(fields) > _MAX_DISCORD_EMBED_FIELDS:
                    item["fields_truncated"] = True
        for key in ("image", "thumbnail"):
            source = embed.get(key)
            if isinstance(source, dict) and (
                source.get("present") is True
                or isinstance(source.get("url"), str)
                or isinstance(source.get("proxy_url"), str)
            ):
                item[f"has_{key}"] = True
        if item:
            projected.append(item)
    return projected


def _bounded_string(value: object) -> str | None:
    if not isinstance(value, str) or not value:
        return None
    return value[:MAX_EXTERNAL_CHANNEL_FILE_TEXT_LENGTH]


def _author(
    value: object,
) -> tuple[ExternalChannelPrincipalAuthorType, str | None, str | None]:
    if not isinstance(value, dict):
        return ExternalChannelPrincipalAuthorType.SYSTEM, None, None
    provider_user_id = _bounded_string(value.get("id"))
    display_name = _discord_display_name(value)
    if value.get("system") is True:
        return (
            ExternalChannelPrincipalAuthorType.SYSTEM,
            provider_user_id,
            display_name,
        )
    if value.get("bot") is True:
        return ExternalChannelPrincipalAuthorType.BOT, provider_user_id, display_name
    return ExternalChannelPrincipalAuthorType.HUMAN, provider_user_id, display_name


def _reference_mappings(
    message: dict[str, object],
) -> dict[str, dict[str, str]]:
    """Return bounded Discord user and channel display-name mappings."""
    users: dict[str, str] = {}
    channels: dict[str, str] = {}
    author = message.get("author")
    if isinstance(author, dict):
        author_id = _bounded_string(author.get("id"))
        display_name = _discord_display_name(author)
        if author_id is not None and display_name is not None:
            users[author_id] = display_name
    mentions = message.get("mentions")
    if isinstance(mentions, list):
        for mention in mentions:
            if not isinstance(mention, dict):
                continue
            mention_id = _bounded_string(mention.get("id"))
            display_name = _discord_display_name(mention)
            if mention_id is not None and display_name is not None:
                users[mention_id] = display_name
    channel_id = _bounded_string(message.get("channel_id"))
    channel_name = _bounded_string(message.get("channel_name"))
    if channel_id is not None and channel_name is not None:
        channels[channel_id] = channel_name
    thread = message.get("thread")
    if isinstance(thread, dict):
        thread_id = _bounded_string(thread.get("id"))
        thread_name = _bounded_string(thread.get("name"))
        if thread_id is not None and thread_name is not None:
            channels[thread_id] = thread_name
        parent_id = _bounded_string(thread.get("parent_id"))
        parent_name = _bounded_string(message.get("parent_channel_name"))
        if parent_id is not None and parent_name is not None:
            channels[parent_id] = parent_name
    return {
        category: mappings
        for category, mappings in (
            ("users", users),
            ("channels", channels),
        )
        if mappings
    }


def _discord_display_name(value: dict[str, object]) -> str | None:
    """Prefer a Discord global display name and fall back to username."""
    return _bounded_string(value.get("global_name")) or _bounded_string(
        value.get("username")
    )


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
    attachments = message.get("attachments")
    embeds = message.get("embeds")
    if attachments is None and embeds is None:
        return None
    metadata: dict[str, object] = {}
    if attachments is not None and not isinstance(attachments, dict):
        raise DiscordEventNormalizationError(
            "Discord attachment projection is invalid."
        )
    if isinstance(attachments, dict):
        files = attachments.get("files")
        if not isinstance(files, list):
            raise DiscordEventNormalizationError("Discord attachment list is invalid.")
        metadata["files"] = files
        if message.get("attachments_truncated") is True:
            metadata["files_truncated"] = True
    if embeds is not None:
        if not isinstance(embeds, list):
            raise DiscordEventNormalizationError("Discord embed projection is invalid.")
        metadata["embeds"] = embeds
        if message.get("embeds_truncated") is True:
            metadata["embeds_truncated"] = True
    return metadata


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
) -> str:
    """Return one immutable original snapshot identity."""
    return f"discord:{message_id}:original"


def _normalized_size(
    body: str | None,
    attachment_metadata: dict[str, object] | None,
    reference_mappings: dict[str, dict[str, str]],
) -> int:
    """Return a conservative byte budget for stored and model-visible content."""
    body_size = 0 if body is None else len(body.encode())
    attachment_size = (
        0
        if attachment_metadata is None
        else len(json.dumps(attachment_metadata, separators=(",", ":")).encode())
    )
    mapping_lines = ["Identity Mappings:"]
    mapping_lines.extend(
        f"- User {identifier}: {display_name}"
        for identifier, display_name in sorted(
            reference_mappings.get("users", {}).items()
        )
    )
    mapping_lines.extend(
        f"- Channel {identifier}: {display_name}"
        for identifier, display_name in sorted(
            reference_mappings.get("channels", {}).items()
        )
    )
    mapping_size = (
        0 if len(mapping_lines) == 1 else len("\n".join(mapping_lines).encode())
    )
    return body_size + attachment_size + mapping_size


def _discord_timestamp(value: object) -> datetime.datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=datetime.UTC)
