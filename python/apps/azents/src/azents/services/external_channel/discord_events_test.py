"""Deterministic Discord Gateway message-projection tests."""

import datetime
import json
from typing import cast

import pytest

from azents.services.external_channel.discord_events import (
    DiscordEventExcluded,
    DiscordEventNormalizationError,
    DiscordMessageContentUnavailable,
    normalize_projected_discord_event,
    project_discord_gateway_dispatch,
)
from azents.services.external_channel.discord_gateway import DiscordGatewayDispatch


def _dispatch(
    *,
    event_name: str = "MESSAGE_CREATE",
    guild_id: str = "guild-1",
) -> DiscordGatewayDispatch:
    """Build one representative Discord message Dispatch."""
    return DiscordGatewayDispatch(
        session_id="gateway-session-1",
        resume_gateway_url="wss://gateway.discord.gg",
        sequence=42,
        event_name=event_name,
        data={
            "id": "message-1",
            "channel_id": "channel-1",
            "guild_id": guild_id,
            "content": "Please help with this.",
            "timestamp": "2026-07-26T00:00:00.000000+00:00",
            "author": {
                "id": "user-1",
                "username": "Example",
                "avatar": "https://cdn.discordapp.com/avatars/private",
            },
            "attachments": [
                {
                    "id": "attachment-1",
                    "filename": "report.pdf",
                    "content_type": "application/pdf",
                    "size": 123,
                    "url": "https://cdn.discordapp.com/attachments/private",
                    "proxy_url": "https://media.discordapp.net/attachments/private",
                }
            ],
        },
    )


def test_projects_message_event_without_attachment_urls_or_raw_payload() -> None:
    """Admission retains message data plus metadata-only attachment details."""
    event = project_discord_gateway_dispatch(
        connection_id="connection-1",
        provider_app_id="app-1",
        target_guild_id="guild-1",
        dispatch=_dispatch(),
        received_at=datetime.datetime(2026, 7, 26, tzinfo=datetime.UTC),
    )

    assert event is not None
    assert event.provider_event_id == "discord-gateway:gateway-session-1:42"
    assert event.transport_envelope_id == "discord-gateway:gateway-session-1:42"
    assert event.event_type == "discord_message_create"
    assert event.resource_correlation_key == "guild-1:channel-1"
    assert event.envelope == {
        "message": {
            "id": "message-1",
            "channel_id": "channel-1",
            "guild_id": "guild-1",
            "timestamp": "2026-07-26T00:00:00.000000+00:00",
            "content": "Please help with this.",
            "author": {
                "id": "user-1",
                "username": "Example",
            },
            "attachments": {
                "files": [
                    {
                        "provider": "discord",
                        "provider_file_id": "attachment-1",
                        "name": "report.pdf",
                        "title": None,
                        "media_type": "application/pdf",
                        "declared_size": 123,
                        "mode": None,
                        "external": False,
                        "file_access": None,
                        "supported": True,
                        "unsupported_reason": None,
                        "source_channel_id": "channel-1",
                    }
                ]
            },
            "attachments_truncated": False,
        }
    }
    serialized = json.dumps(event.envelope)
    assert "cdn.discordapp.com" not in serialized
    assert "proxy_url" not in serialized
    assert '"url"' not in serialized
    assert '"avatar"' not in serialized


@pytest.mark.parametrize(
    "event_name",
    ("MESSAGE_CREATE", "MESSAGE_UPDATE", "MESSAGE_DELETE"),
)
def test_projects_all_supported_message_lifecycle_events(event_name: str) -> None:
    """Every supported Discord message lifecycle dispatch has its own event type."""
    event = project_discord_gateway_dispatch(
        connection_id="connection-1",
        provider_app_id="app-1",
        target_guild_id="guild-1",
        dispatch=_dispatch(event_name=event_name),
        received_at=datetime.datetime(2026, 7, 26, tzinfo=datetime.UTC),
    )

    assert event is not None
    expected_event_type = (
        f"discord_message_{event_name.removeprefix('MESSAGE_').lower()}"
    )
    assert event.event_type == expected_event_type


def test_ignores_cross_guild_and_unsupported_dispatches() -> None:
    """A connection never admits another Guild's events or unrelated Dispatches."""
    received_at = datetime.datetime(2026, 7, 26, tzinfo=datetime.UTC)

    cross_guild = project_discord_gateway_dispatch(
        connection_id="connection-1",
        provider_app_id="app-1",
        target_guild_id="guild-1",
        dispatch=_dispatch(guild_id="guild-2"),
        received_at=received_at,
    )
    unsupported = project_discord_gateway_dispatch(
        connection_id="connection-1",
        provider_app_id="app-1",
        target_guild_id="guild-1",
        dispatch=_dispatch(event_name="GUILD_CREATE"),
        received_at=received_at,
    )

    assert cross_guild is None
    assert unsupported is None


def test_rejects_malformed_message_dispatch_before_admission() -> None:
    """Reject a lifecycle event without its canonical message identity."""
    dispatch = DiscordGatewayDispatch(
        session_id="gateway-session-1",
        resume_gateway_url="wss://gateway.discord.gg",
        sequence=42,
        event_name="MESSAGE_CREATE",
        data={"guild_id": "guild-1", "channel_id": "channel-1"},
    )

    with pytest.raises(ValueError, match="'id' is missing"):
        project_discord_gateway_dispatch(
            connection_id="connection-1",
            provider_app_id="app-1",
            target_guild_id="guild-1",
            dispatch=dispatch,
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
    assert normalized.normalized_body == "Ask the connected App."
    assert normalized.thread_id == "400"
    assert normalized.parent_channel_id == "200"
    assert normalized.invocation is True
    assert normalized.attachment_metadata is not None
    files = normalized.attachment_metadata["files"]
    assert isinstance(files, list)
    assert isinstance(files[0], dict)
    assert files[0]["provider_file_id"] == "500"


@pytest.mark.parametrize(
    ("event_type", "expected_revision", "expected_lifecycle"),
    (
        ("discord_message_create", "original", "current"),
        ("discord_message_update", "edit", "edited"),
        ("discord_message_delete", "delete", "deleted"),
    ),
)
def test_normalizes_message_lifecycle_events(
    event_type: str,
    expected_revision: str,
    expected_lifecycle: str,
) -> None:
    """Create, update, and delete have deterministic revision semantics."""
    normalized = normalize_projected_discord_event(
        event_type=event_type,
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

    assert normalized.revision_kind.value == expected_revision
    assert normalized.lifecycle.value == expected_lifecycle
    assert normalized.normalized_body == (
        None if expected_revision == "delete" else "current content"
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
