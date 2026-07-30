"""Tests for shared External Channel model rendering."""

import datetime

from azents.core.enums import (
    ExternalChannelPrincipalAuthorType,
    ExternalChannelProvider,
    ExternalChannelResourceType,
)
from azents.engine.events.external_channel_rendering import (
    external_channel_message_visible_value,
    render_external_channel_message,
    render_external_channel_turn,
)
from azents.engine.events.types import ExternalChannelMessagePayload


def _payload(
    *,
    provider: ExternalChannelProvider = ExternalChannelProvider.SLACK,
    body: str | None = "hello",
    batch_id: str = "batch-1",
    external_message_id: str = "message-1",
    reference_mappings: dict[str, dict[str, str]] | None = None,
    attachment_metadata: dict[str, object] | None = None,
) -> ExternalChannelMessagePayload:
    return ExternalChannelMessagePayload(
        provider=provider,
        provider_tenant_id="tenant-1",
        resource_id="resource-1",
        resource_label="#incident / thread",
        resource_type=ExternalChannelResourceType.THREAD,
        binding_id="binding-1",
        invocation_batch_id=batch_id,
        external_message_id=external_message_id,
        projection_root_id=f"external-channel:binding-1:{external_message_id}",
        provider_message_key="slack:tenant-1:C1:1.000001",
        provider_position="00000000000000000001.000001",
        principal_id="principal-1",
        provider_user_id="U1",
        sender_display_name="Alice",
        author_type=ExternalChannelPrincipalAuthorType.HUMAN,
        authorization="authorized_invocation",
        body=body,
        attachment_metadata=attachment_metadata or {},
        reference_mappings=reference_mappings or {},
        provider_created_at=datetime.datetime(2026, 7, 22, 12, 0, tzinfo=datetime.UTC),
        provider_updated_at=None,
        original_url="https://slack.example/permalink",
        truncated_context_message_count=2,
        truncated_context_size=128,
    )


def test_shared_renderer_preserves_source_and_truncation_metadata() -> None:
    payload = _payload()
    value = external_channel_message_visible_value(payload)
    rendered = render_external_channel_message(payload)

    assert value["provider"] == "slack"
    assert value["resource"] == {
        "id": "resource-1",
        "label": "#incident / thread",
        "type": "thread",
    }
    assert value["truncated_context"] == {"message_count": 2, "size": 128}
    assert "Authorization: authorized_invocation" in rendered
    assert "Truncated context: 2 messages, 128 bytes" in rendered


def test_shared_renderer_preserves_attachment_only_message_state() -> None:
    payload = _payload(body=None)

    rendered = render_external_channel_message(payload)

    assert "[Message has no text content.]" in rendered


def test_turn_renderer_aggregates_payloads_without_losing_order() -> None:
    first = _payload(batch_id="batch-1")
    second = _payload(
        batch_id="batch-1",
        external_message_id="message-2",
        body="second",
    )

    rendered = render_external_channel_turn([first, second])

    assert rendered.startswith("Message Type: EXTERNAL_CHANNEL_TURN")
    assert rendered.index("Body: hello") < rendered.index("Body: second")


def test_turn_renderer_resolves_visible_references_but_retains_raw_payload() -> None:
    """Visible text uses names while canonical payload identity stays unchanged."""
    payload = _payload(
        body="<@U1> asked <#C1> to investigate.",
        reference_mappings={
            "users": {"U1": "Alice"},
            "channels": {"C1": "#incidents"},
        },
    )
    rendered = render_external_channel_turn([payload])

    assert "Body: @Alice asked #incidents to investigate." in rendered
    assert "- User U1: Alice" in rendered
    assert "- Channel C1: #incidents" in rendered
    assert payload.body == "<@U1> asked <#C1> to investigate."
    assert payload.reference_mappings["users"]["U1"] == "Alice"


def test_discord_nickname_mention_uses_visible_identity_mapping() -> None:
    """Discord nickname mention syntax resolves without changing stored text."""
    payload = _payload(
        provider=ExternalChannelProvider.DISCORD,
        body="<@!123456789> asked for help.",
        reference_mappings={
            "users": {"123456789": "Alice"},
        },
    )

    rendered = render_external_channel_message(payload)

    assert "@Alice asked for help." in rendered
    assert payload.body == "<@!123456789> asked for help."


def test_visible_reference_resolution_does_not_reprocess_display_names() -> None:
    payload = _payload(
        body="<@U1> and <@U2> discussed <#C1> with <#C2>.",
        reference_mappings={
            "users": {"U1": "U2", "U2": "Alice"},
            "channels": {"C1": "C2", "C2": "incidents"},
        },
    )

    rendered = render_external_channel_turn([payload])

    assert "Body: @U2 and @Alice discussed #C2 with #incidents." in rendered


def test_file_metadata_is_identical_and_safe_across_visible_renderers() -> None:
    """Structured and text projections expose only bounded file decision fields."""
    payload = _payload(
        attachment_metadata={
            "blocks": {
                "block_count": 2,
                "block_types": ["section", "context"],
                "truncated": False,
            },
            "files": [
                {
                    "provider": "slack",
                    "provider_file_id": "F123",
                    "name": "report.csv",
                    "title": "Quarterly\nReport",
                    "media_type": "text/csv",
                    "declared_size": 1024,
                    "mode": "hosted",
                    "external": False,
                    "file_access": None,
                    "supported": True,
                    "unsupported_reason": None,
                    "file": "external-file:v1:slack:binding-1:F123",
                    "url_private": "https://secret-download.example/F123",
                    "body": "private file bytes",
                },
                {
                    "provider": "slack",
                    "provider_file_id": "F456",
                    "name": None,
                    "title": "Remote",
                    "media_type": None,
                    "declared_size": None,
                    "mode": "external",
                    "external": True,
                    "file_access": None,
                    "supported": False,
                    "unsupported_reason": "external_file",
                    "file": "external-file:v1:slack:binding-1:F456",
                },
            ],
            "files_truncated": True,
        }
    )

    value = external_channel_message_visible_value(payload)
    rendered_message = render_external_channel_message(payload)
    rendered_turn = render_external_channel_turn([payload])

    assert value["attachments"] == {
        "blocks": {
            "block_count": 2,
            "block_types": ["section", "context"],
            "truncated": False,
        },
        "files": [
            {
                "name": "report.csv",
                "title": "Quarterly Report",
                "media_type": "text/csv",
                "declared_size": 1024,
                "supported": True,
                "unsupported_reason": None,
                "file": "external-file:v1:slack:binding-1:F123",
            },
            {
                "name": None,
                "title": "Remote",
                "media_type": None,
                "declared_size": None,
                "supported": False,
                "unsupported_reason": "external_file",
                "file": "external-file:v1:slack:binding-1:F456",
            },
        ],
        "files_truncated": True,
    }
    for rendered in (rendered_message, rendered_turn):
        assert "Files:" in rendered
        assert "Name: report.csv" in rendered
        assert "Title: Quarterly Report" in rendered
        assert "Declared size: 1024 bytes" in rendered
        assert "Status: supported" in rendered
        assert "Status: unsupported (external_file)" in rendered
        assert "external-file:v1:slack:binding-1:F123" in rendered
        assert "Additional files omitted" in rendered
        assert "secret-download" not in rendered
        assert "private file bytes" not in rendered
        assert "provider_file_id" not in rendered
    assert "secret-download" not in str(value)
    assert "private file bytes" not in str(value)
    assert "provider_file_id" not in str(value)


def test_file_renderer_omits_untrusted_locator_values() -> None:
    """Only a valid versioned locator reaches structured or text visibility."""
    payload = _payload(
        attachment_metadata={
            "files": [
                {
                    "name": "report.csv",
                    "title": None,
                    "media_type": "text/csv",
                    "declared_size": 1024,
                    "supported": True,
                    "unsupported_reason": None,
                    "file": "https://secret-download.example/F123",
                }
            ]
        }
    )

    value = external_channel_message_visible_value(payload)
    rendered = render_external_channel_message(payload)

    assert "file" not in value["attachments"]["files"][0]  # type: ignore[index]
    assert "secret-download" not in rendered


def test_embed_metadata_is_visible_without_urls_or_provider_payload() -> None:
    """Embed text and media presence reach models without locators or raw fields."""
    payload = _payload(
        provider=ExternalChannelProvider.DISCORD,
        attachment_metadata={
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
                    "url": "https://untrusted.example/incident",
                    "image": {"url": "https://cdn.discordapp.com/image.png"},
                }
            ]
        },
    )

    value = external_channel_message_visible_value(payload)
    rendered_message = render_external_channel_message(payload)
    rendered_turn = render_external_channel_turn([payload])

    assert value["attachments"]["embeds"] == [  # type: ignore[index]
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
    for rendered in (rendered_message, rendered_turn):
        assert "Embeds:" in rendered
        assert "Title: Incident summary" in rendered
        assert "Severity: High (inline)" in rendered
        assert "Image: present" in rendered
        assert "Thumbnail: present" in rendered
        assert "untrusted.example" not in rendered
        assert "discordapp" not in rendered
    assert "untrusted.example" not in str(value)
    assert "discordapp" not in str(value)
