"""One typed boundary for retained External Channel label and reference semantics."""

from dataclasses import dataclass
from typing import Literal


@dataclass(frozen=True)
class ExternalChannelResourceLabels:
    """Validated decision fields and opaque, uninspected provider target coordinates.

    Legacy provider coordinates may contain values the downstream provider rejects.
    Values only relayed to provider egress remain opaque; decision fields are
    validated here without rejecting unrelated labels or extension metadata.
    """

    present: bool
    provider: Literal["slack", "discord"] | None
    conversation_scope: str | None
    thread_ts: str | None
    delivery_channel_id: str | None
    delivery_channel_absent: bool
    parent_channel_id: str | None
    root_message_id: str | None
    thread_id: str | None
    channel_label: str | None
    thread_label: str | None
    thread_label_invalid: bool
    tenant_coordinate: object
    channel_coordinate: object
    guild_coordinate: object
    parent_coordinate: object
    source_coordinate: object
    thread_coordinate: object


@dataclass(frozen=True)
class ExternalChannelReferenceMappings:
    """Typed dynamic user/channel identifier maps after ingress filtering."""

    users: dict[str, str]
    channels: dict[str, str]

    def to_payload(self) -> dict[str, dict[str, str]]:
        """Serialize the approved maps at presentation egress."""
        result: dict[str, dict[str, str]] = {}
        if self.users:
            result["users"] = self.users
        if self.channels:
            result["channels"] = self.channels
        return result


def _nonempty_string(value: object) -> str | None:
    return value if isinstance(value, str) and value else None


def decode_external_channel_resource_labels(
    value: dict[str, object] | None,
) -> ExternalChannelResourceLabels:
    """Validate decision fields once while preserving partial/legacy targets.

    Unknown fields are ignored under the retained-label compatibility contract.
    Nonempty delivery-channel strings, including whitespace, remain unchanged.
    Only mailbox label presentation requires valid display/channel/thread labels;
    invalid unrelated labels do not reject an operation-local presence target.
    """
    labels = value or {}
    provider = labels.get("provider")
    known_provider: Literal["slack", "discord"] | None = (
        "slack" if provider == "slack" else "discord" if provider == "discord" else None
    )
    channel = (
        labels.get("display_name")
        or labels.get("channel_name")
        or labels.get("channel_id")
        or labels.get("parent_channel_id")
        or labels.get("thread_id")
    )
    thread = labels.get("thread_ts")
    if thread is None and labels.get("parent_channel_id") == channel:
        thread = labels.get("thread_id")
    delivery = labels.get("delivery_channel_id")
    root_message = labels.get("root_message_id")
    thread_id = labels.get("thread_id")
    return ExternalChannelResourceLabels(
        present=bool(labels),
        provider=known_provider,
        conversation_scope=_nonempty_string(labels.get("conversation_scope")),
        thread_ts=_nonempty_string(labels.get("thread_ts")),
        delivery_channel_id=_nonempty_string(delivery),
        delivery_channel_absent=delivery is None,
        parent_channel_id=_nonempty_string(labels.get("parent_channel_id")),
        root_message_id=root_message if isinstance(root_message, str) else None,
        thread_id=thread_id if isinstance(thread_id, str) else None,
        channel_label=channel if isinstance(channel, str) else None,
        thread_label=thread if isinstance(thread, str) else None,
        thread_label_invalid=thread is not None and not isinstance(thread, str),
        tenant_coordinate=labels.get("tenant_id"),
        channel_coordinate=labels.get("channel_id"),
        guild_coordinate=labels.get("guild_id"),
        parent_coordinate=labels.get("parent_channel_id"),
        source_coordinate=labels.get("source_channel_id"),
        thread_coordinate=labels.get("thread_id"),
    )


def decode_external_channel_reference_mappings(
    value: dict[str, object] | None,
) -> ExternalChannelReferenceMappings:
    """Filter the two dynamic reference maps once at storage/presentation ingress."""
    mappings: dict[str, dict[str, str]] = {}
    for category in ("users", "channels"):
        raw = value.get(category) if isinstance(value, dict) else None
        if not isinstance(raw, dict):
            mappings[category] = {}
            continue
        mappings[category] = {
            identifier: display_name
            for identifier, display_name in raw.items()
            if isinstance(identifier, str)
            and identifier
            and isinstance(display_name, str)
            and display_name
        }
    return ExternalChannelReferenceMappings(
        users=mappings["users"], channels=mappings["channels"]
    )
