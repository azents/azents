"""Tests for shared External Channel model rendering."""

import datetime

from azents.core.enums import (
    ExternalChannelMessageLifecycle,
    ExternalChannelMessageRevisionKind,
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
    body: str | None = "hello",
    lifecycle: ExternalChannelMessageLifecycle = (
        ExternalChannelMessageLifecycle.CURRENT
    ),
    revision_kind: ExternalChannelMessageRevisionKind = (
        ExternalChannelMessageRevisionKind.ORIGINAL
    ),
    batch_id: str = "batch-1",
    external_message_id: str = "message-1",
    revision_id: str = "revision-1",
    reference_mappings: dict[str, dict[str, str]] | None = None,
) -> ExternalChannelMessagePayload:
    return ExternalChannelMessagePayload(
        provider=ExternalChannelProvider.SLACK,
        provider_tenant_id="tenant-1",
        resource_id="resource-1",
        resource_label="#incident / thread",
        resource_type=ExternalChannelResourceType.THREAD,
        binding_id="binding-1",
        invocation_batch_id=batch_id,
        external_message_id=external_message_id,
        revision_id=revision_id,
        revision_kind=revision_kind,
        projection_root_id=f"external-channel:binding-1:{external_message_id}",
        provider_message_key="slack:tenant-1:C1:1.000001",
        provider_position="00000000000000000001.000001",
        principal_id="principal-1",
        provider_user_id="U1",
        sender_display_name="Alice",
        author_type=ExternalChannelPrincipalAuthorType.HUMAN,
        authorization="authorized_invocation",
        lifecycle=lifecycle,
        body=body,
        attachment_metadata={},
        reference_mappings=reference_mappings or {},
        provider_created_at=datetime.datetime(2026, 7, 22, 12, 0, tzinfo=datetime.UTC),
        provider_updated_at=None,
        original_url="https://slack.example/permalink",
        truncated_context_message_count=2,
        truncated_context_size=128,
        correction_of_revision_id=(
            None
            if revision_kind is ExternalChannelMessageRevisionKind.ORIGINAL
            else "revision-original"
        ),
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


def test_shared_renderer_marks_deleted_revision_without_body() -> None:
    payload = _payload(
        body=None,
        lifecycle=ExternalChannelMessageLifecycle.DELETED,
        revision_kind=ExternalChannelMessageRevisionKind.DELETE,
    )

    rendered = render_external_channel_message(payload)

    assert "Revision: delete" in rendered
    assert "[Message deleted by provider.]" in rendered


def test_shared_renderer_preserves_attachment_only_message_state() -> None:
    rendered = render_external_channel_message(_payload(body=None))

    assert "[Message has no text content.]" in rendered
    assert "[Message deleted by provider.]" not in rendered


def test_turn_renderer_aggregates_payloads_without_losing_order() -> None:
    first = _payload(batch_id="batch-1")
    second = _payload(
        batch_id="batch-1",
        external_message_id="message-2",
        revision_id="revision-2",
        body="second",
    )

    rendered = render_external_channel_turn([first, second])

    assert rendered.startswith("Message Type: EXTERNAL_CHANNEL_TURN")
    assert rendered.index("Body: hello") < rendered.index("Body: second")


def test_turn_renderer_labels_corrections() -> None:
    edited = _payload(
        lifecycle=ExternalChannelMessageLifecycle.EDITED,
        revision_kind=ExternalChannelMessageRevisionKind.EDIT,
    )

    rendered = render_external_channel_turn([edited])

    assert "Revision: edit" in rendered
    assert "Correction of revision: revision-original" in rendered


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
    assert "U1" not in rendered
    assert "C1" not in rendered
    assert payload.body == "<@U1> asked <#C1> to investigate."
    assert payload.reference_mappings["users"]["U1"] == "Alice"


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
