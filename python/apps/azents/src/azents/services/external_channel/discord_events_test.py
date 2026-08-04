"""Deterministic Discord Gateway message-projection tests."""

import datetime
import json
from typing import cast
from unittest.mock import MagicMock

import discord
import pytest

from azents.core.external_channel_file import MAX_EXTERNAL_CHANNEL_FILES
from azents.services.external_channel.discord_events import (
    DiscordEventExcluded,
    DiscordEventNormalizationError,
    DiscordMessageContentUnavailable,
    normalize_projected_discord_event,
    project_discord_gateway_event,
    project_discord_message,
)
from azents.services.external_channel.discord_gateway import DiscordGatewayMessageEvent
from azents.testing.types import is_string_object_dict


def _guild(*, guild_id: int = 300) -> MagicMock:
    guild = MagicMock(spec=discord.Guild)
    guild.id = guild_id
    return guild


def _channel(*, guild_id: int = 300) -> MagicMock:
    channel = MagicMock(spec=discord.TextChannel)
    channel.id = 200
    channel.guild = _guild(guild_id=guild_id)
    channel.name = "incidents"
    return channel


def _event(
    *,
    guild_id: int = 300,
) -> DiscordGatewayMessageEvent:
    """Build one representative typed discord.py event."""
    channel = _channel(guild_id=guild_id)
    author = MagicMock(spec=discord.User)
    author.id = 400
    author.name = "Example"
    author.global_name = None
    author.bot = False
    author.system = False
    attachment = MagicMock(spec=discord.Attachment)
    attachment.id = 500
    attachment.filename = "report.pdf"
    attachment.content_type = "application/pdf"
    attachment.size = 123
    message = MagicMock(spec=discord.Message)
    message.id = 100
    message.guild = channel.guild
    message.channel = channel
    message.content = "Please help with this."
    message.created_at = datetime.datetime(2026, 7, 26, tzinfo=datetime.UTC)
    message.edited_at = None
    message.author = author
    message.mentions = []
    message.role_mentions = []
    message.attachments = [attachment]
    return DiscordGatewayMessageEvent(
        event_type="message_create",
        channel=channel,
        message=message,
    )


def test_projects_message_event_without_attachment_urls_or_raw_payload() -> None:
    """Admission retains message data plus metadata-only attachment details."""
    event = project_discord_gateway_event(
        connection_id="connection-1",
        provider_app_id="app-1",
        target_guild_id="300",
        connected_bot_user_id="900",
        event=_event(),
        received_at=datetime.datetime(2026, 7, 26, tzinfo=datetime.UTC),
    )

    assert event is not None
    assert event.provider_event_id == "discord:discord_message_create:300:200:100"
    assert event.transport_envelope_id == event.provider_event_id
    assert event.event_type == "discord_message_create"
    assert event.resource_correlation_key == "300:200"
    assert event.envelope == {
        "message": {
            "id": "100",
            "channel_id": "200",
            "guild_id": "300",
            "timestamp": "2026-07-26T00:00:00+00:00",
            "channel_name": "incidents",
            "content": "Please help with this.",
            "author": {
                "id": "400",
                "username": "Example",
            },
            "mentions": [],
            "attachments": {
                "files": [
                    {
                        "provider": "discord",
                        "provider_file_id": "500",
                        "name": "report.pdf",
                        "title": None,
                        "media_type": "application/pdf",
                        "declared_size": 123,
                        "mode": None,
                        "external": False,
                        "file_access": None,
                        "supported": True,
                        "unsupported_reason": None,
                        "source_channel_id": "200",
                    }
                ]
            },
            "attachments_truncated": False,
        }
    }
    serialized = json.dumps(event.envelope)
    assert "proxy_url" not in serialized
    assert '"url"' not in serialized
    assert '"avatar"' not in serialized


def test_projects_invalid_attachment_size_as_advisory_metadata() -> None:
    """Discord attachment identity remains usable when event size is malformed."""
    gateway_event = _event()
    assert gateway_event.message is not None
    gateway_event.message.attachments[0].size = -1

    event = project_discord_gateway_event(
        connection_id="connection-1",
        provider_app_id="app-1",
        target_guild_id="300",
        connected_bot_user_id="900",
        event=gateway_event,
        received_at=datetime.datetime(2026, 7, 26, tzinfo=datetime.UTC),
    )

    assert event is not None
    files = event.envelope["message"]["attachments"]["files"]
    assert files[0]["declared_size"] is None
    assert files[0]["supported"] is True
    assert files[0]["unsupported_reason"] is None


def test_projects_connected_bot_managed_role_as_invocation() -> None:
    """A provider-owned Bot role is equivalent to directly mentioning that Bot."""
    role_tags = MagicMock(spec=discord.RoleTags)
    role_tags.bot_id = 900
    role = MagicMock(spec=discord.Role)
    role.id = 901
    role.tags = role_tags
    gateway_event = _event()
    assert gateway_event.message is not None
    gateway_event.message.role_mentions = [role]

    event = project_discord_gateway_event(
        connection_id="connection-1",
        provider_app_id="app-1",
        target_guild_id="300",
        connected_bot_user_id="900",
        event=gateway_event,
        received_at=datetime.datetime(2026, 7, 26, tzinfo=datetime.UTC),
    )

    assert event is not None
    raw_message = event.envelope["message"]
    assert isinstance(raw_message, dict)
    assert raw_message["managed_bot_role_mentions"] == [
        {
            "id": "901",
            "bot_user_id": "900",
        }
    ]
    normalized = normalize_projected_discord_event(
        event_type=event.event_type,
        tenant_id="300",
        connected_bot_user_id="900",
        envelope=event.envelope,
    )
    assert normalized.invocation is True


def test_projects_connected_bot_role_after_unrelated_managed_role_volume() -> None:
    """Other Bots' roles cannot displace the connected Bot's managed role."""
    unrelated_roles: list[MagicMock] = []
    for role_id in range(MAX_EXTERNAL_CHANNEL_FILES):
        role_tags = MagicMock(spec=discord.RoleTags)
        role_tags.bot_id = 1_000 + role_id
        role = MagicMock(spec=discord.Role)
        role.id = role_id
        role.tags = role_tags
        unrelated_roles.append(role)
    role_tags = MagicMock(spec=discord.RoleTags)
    role_tags.bot_id = 900
    managed_role = MagicMock(spec=discord.Role)
    managed_role.id = 901
    managed_role.tags = role_tags
    gateway_event = _event()
    assert gateway_event.message is not None
    gateway_event.message.role_mentions = [*unrelated_roles, managed_role]

    event = project_discord_gateway_event(
        connection_id="connection-1",
        provider_app_id="app-1",
        target_guild_id="300",
        connected_bot_user_id="900",
        event=gateway_event,
        received_at=datetime.datetime(2026, 7, 26, tzinfo=datetime.UTC),
    )

    assert event is not None
    raw_message = event.envelope["message"]
    assert isinstance(raw_message, dict)
    assert raw_message["managed_bot_role_mentions"] == [
        {
            "id": "901",
            "bot_user_id": "900",
        }
    ]


def test_rejects_unrelated_managed_bot_role_as_invocation() -> None:
    """Another Bot's managed role cannot invoke the connected Agent."""
    projection = project_discord_message(
        guild_id="guild-1",
        message={
            "id": "100",
            "channel_id": "200",
            "content": "<@&901> help",
            "managed_bot_role_mentions": [
                {
                    "id": "901",
                    "bot_user_id": "902",
                }
            ],
        },
    )

    normalized = normalize_projected_discord_event(
        event_type="discord_message_create",
        tenant_id="guild-1",
        connected_bot_user_id="900",
        envelope={"message": projection},
    )

    assert normalized.invocation is False


def test_omits_ordinary_role_from_invocation_projection() -> None:
    """A manually managed role has no Bot ownership invocation authority."""
    role = MagicMock(spec=discord.Role)
    role.id = 901
    role.tags = None
    gateway_event = _event()
    assert gateway_event.message is not None
    gateway_event.message.role_mentions = [role]

    event = project_discord_gateway_event(
        connection_id="connection-1",
        provider_app_id="app-1",
        target_guild_id="300",
        connected_bot_user_id="900",
        event=gateway_event,
        received_at=datetime.datetime(2026, 7, 26, tzinfo=datetime.UTC),
    )

    assert event is not None
    raw_message = event.envelope["message"]
    assert isinstance(raw_message, dict)
    assert "managed_bot_role_mentions" not in raw_message
    normalized = normalize_projected_discord_event(
        event_type=event.event_type,
        tenant_id="300",
        connected_bot_user_id="900",
        envelope=event.envelope,
    )
    assert normalized.invocation is False


def test_projects_only_message_create_events() -> None:
    """The Gateway projects only message-create callbacks into ingestion."""
    event = project_discord_gateway_event(
        connection_id="connection-1",
        provider_app_id="app-1",
        target_guild_id="300",
        connected_bot_user_id="900",
        event=_event(),
        received_at=datetime.datetime(2026, 7, 26, tzinfo=datetime.UTC),
    )

    assert event is not None
    assert event.event_type == "discord_message_create"


def test_ignores_cross_guild_typed_events() -> None:
    """A connection never admits another Guild's typed event."""
    cross_guild = project_discord_gateway_event(
        connection_id="connection-1",
        provider_app_id="app-1",
        target_guild_id="300",
        connected_bot_user_id="900",
        event=_event(guild_id=301),
        received_at=datetime.datetime(2026, 7, 26, tzinfo=datetime.UTC),
    )

    assert cross_guild is None


def test_rejects_typed_create_without_message() -> None:
    malformed = DiscordGatewayMessageEvent(
        event_type="message_create",
        channel=_channel(),
    )

    with pytest.raises(ValueError, match="typed Message"):
        project_discord_gateway_event(
            connection_id="connection-1",
            provider_app_id="app-1",
            target_guild_id="300",
            connected_bot_user_id="900",
            event=malformed,
            received_at=datetime.datetime(2026, 7, 26, tzinfo=datetime.UTC),
        )


def test_normalizes_create_with_principal_and_attachment_metadata() -> None:
    """Normalize a Discord principal without inferring an Azents user."""
    normalized = normalize_projected_discord_event(
        event_type="discord_message_create",
        tenant_id="guild-1",
        connected_bot_user_id="900",
        envelope={
            "message": {
                "id": "100",
                "channel_id": "200",
                "guild_id": "guild-1",
                "content": "Ask the connected App.",
                "timestamp": "2026-07-26T00:00:00+00:00",
                "author": {"id": "300", "username": "participant"},
                "mentions": [{"id": "900"}],
                "thread": {"id": "400", "parent_id": "200"},
                "attachments": {
                    "files": [
                        {
                            "provider": "discord",
                            "provider_file_id": "500",
                            "name": "report.pdf",
                            "title": None,
                            "media_type": "application/pdf",
                            "declared_size": 123,
                            "mode": None,
                            "external": False,
                            "file_access": None,
                            "supported": True,
                            "unsupported_reason": None,
                        }
                    ]
                },
            }
        },
    )

    assert normalized.tenant_id == "guild-1"
    assert normalized.provider_message_key == "discord:guild-1:100"
    assert normalized.provider_position == "00000000000000000100"
    assert normalized.provider_user_id == "300"
    assert normalized.sender_display_name == "participant"
    assert normalized.normalized_body == "Ask the connected App."
    assert normalized.thread_id == "400"
    assert normalized.parent_channel_id == "200"
    assert normalized.invocation is True
    assert normalized.attachment_metadata is not None
    files = normalized.attachment_metadata["files"]
    assert isinstance(files, list)
    assert is_string_object_dict(files[0])
    assert files[0]["provider_file_id"] == "500"
    assert normalized.reference_mappings == {
        "users": {"300": "participant"},
    }
    assert normalized.normalized_size > len(normalized.normalized_body.encode())


def test_projects_safe_bounded_embeds_without_urls() -> None:
    """Gateway and REST inputs share visible embed text but never persist locators."""
    projection = project_discord_message(
        guild_id="guild-1",
        message={
            "id": "100",
            "channel_id": "200",
            "content": "",
            "embeds": [
                {
                    "type": "rich",
                    "title": "Incident summary",
                    "description": "Database latency is elevated.",
                    "url": "https://untrusted.example/incident",
                    "author": {
                        "name": "Status Bot",
                        "url": "https://untrusted.example/author",
                        "icon_url": "https://cdn.discordapp.com/avatar.png",
                    },
                    "footer": {
                        "text": "Updated now",
                        "icon_url": "https://cdn.discordapp.com/footer.png",
                    },
                    "fields": [
                        {
                            "name": "Severity",
                            "value": "High",
                            "inline": True,
                        }
                    ],
                    "image": {"url": "https://cdn.discordapp.com/image.png"},
                    "thumbnail": {
                        "proxy_url": "https://media.discordapp.net/thumb.png"
                    },
                }
            ],
        },
    )

    normalized = normalize_projected_discord_event(
        event_type="discord_message_create",
        tenant_id="guild-1",
        connected_bot_user_id=None,
        envelope={"message": projection},
    )

    assert normalized.attachment_metadata == {
        "embeds": [
            {
                "type": "rich",
                "title": "Incident summary",
                "description": "Database latency is elevated.",
                "author_name": "Status Bot",
                "footer_text": "Updated now",
                "fields": [{"name": "Severity", "value": "High", "inline": True}],
                "has_image": True,
                "has_thumbnail": True,
            }
        ]
    }
    serialized = json.dumps(projection)
    assert "untrusted.example" not in serialized
    assert "discordapp" not in serialized
    assert "media.discord" not in serialized


def test_identity_mapping_render_budget_is_included_in_pending_size() -> None:
    """Discord display names consume the same bounded pending-context budget."""
    without_mappings = normalize_projected_discord_event(
        event_type="discord_message_create",
        tenant_id="guild-1",
        connected_bot_user_id=None,
        envelope={
            "message": {
                "id": "100",
                "channel_id": "200",
                "guild_id": "guild-1",
                "content": "hello",
            }
        },
    )
    with_mappings = normalize_projected_discord_event(
        event_type="discord_message_create",
        tenant_id="guild-1",
        connected_bot_user_id=None,
        envelope={
            "message": {
                "id": "100",
                "channel_id": "200",
                "channel_name": "incidents",
                "guild_id": "guild-1",
                "content": "hello",
                "author": {"id": "300", "global_name": "Participant"},
            }
        },
    )

    assert without_mappings.normalized_size == len(b"hello")
    assert with_mappings.normalized_size > without_mappings.normalized_size


def test_normalizes_only_message_create_events() -> None:
    """Create events retain one immutable original snapshot."""
    normalized = normalize_projected_discord_event(
        event_type="discord_message_create",
        tenant_id="guild-1",
        connected_bot_user_id="900",
        envelope={
            "message": {
                "id": "100",
                "channel_id": "200",
                "guild_id": "guild-1",
                "content": "current content",
                "timestamp": "2026-07-26T00:00:00+00:00",
                "edited_timestamp": "2026-07-26T00:01:00+00:00",
                "author": {"id": "300"},
            }
        },
    )

    assert normalized.revision_kind.value == "original"
    assert normalized.lifecycle.value == "current"
    assert normalized.normalized_body == "current content"

    with pytest.raises(DiscordEventExcluded):
        normalize_projected_discord_event(
            event_type="discord_message_update",
            tenant_id="guild-1",
            connected_bot_user_id="900",
            envelope={
                "message": {
                    "id": "100",
                    "channel_id": "200",
                    "guild_id": "guild-1",
                    "content": "current content",
                    "author": {"id": "300"},
                }
            },
        )


def test_rejects_wrong_guild_and_non_snowflake_message_identity() -> None:
    """A projection cannot cross connection authority or use unordered message IDs."""
    wrong_guild = {
        "message": {
            "id": "100",
            "channel_id": "200",
            "guild_id": "guild-2",
        }
    }
    malformed_id = {
        "message": {
            "id": "not-a-snowflake",
            "channel_id": "200",
            "guild_id": "guild-1",
            "content": "present",
        }
    }

    with pytest.raises(DiscordEventExcluded, match="does not match"):
        normalize_projected_discord_event(
            event_type="discord_message_create",
            tenant_id="guild-1",
            connected_bot_user_id=None,
            envelope=cast(dict[str, object], wrong_guild),
        )
    with pytest.raises(DiscordEventNormalizationError, match="message ID"):
        normalize_projected_discord_event(
            event_type="discord_message_create",
            tenant_id="guild-1",
            connected_bot_user_id=None,
            envelope=cast(dict[str, object], malformed_id),
        )


def test_detects_missing_message_content_as_connection_health_failure() -> None:
    """Missing content is distinct from a legitimate empty message body."""
    with pytest.raises(DiscordMessageContentUnavailable, match="unavailable"):
        normalize_projected_discord_event(
            event_type="discord_message_create",
            tenant_id="guild-1",
            connected_bot_user_id=None,
            envelope={
                "message": {
                    "id": "100",
                    "channel_id": "200",
                    "guild_id": "guild-1",
                    "author": {"id": "300"},
                }
            },
        )
