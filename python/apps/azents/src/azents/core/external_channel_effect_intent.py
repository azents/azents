"""Typed consumed fields of process-local External Channel effect payloads."""

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Literal

from azents.core.external_channel_session_presence import (
    ExternalChannelSessionPresenceState,
)


def _string(value: object) -> str | None:
    """Retain exactly the historical string predicate, including empty strings."""
    return value if isinstance(value, str) else None


def _integer(value: object) -> int | None:
    """Retain the existing integer predicate, which also admits bool values."""
    return value if isinstance(value, int) else None


@dataclass(frozen=True)
class ProviderEffectIntent:
    """Immutable application metadata decoded from one current effect payload.

    Provider-specific extensions remain opaque in the original payload. Only these
    fields choose application authority, settlement, or presentation behavior.
    """

    control_kind: str | None
    setup_claim_id: str | None
    access_request_id: str | None
    provider_message_key: str | None
    work_id: str | None
    desired_progress_revision: int | None
    part_ordinal: int | None
    tracker_host_kind: Literal["standalone", "reply"]
    scheduled_tracker: bool
    presence_state: ExternalChannelSessionPresenceState | None

    @classmethod
    def decode(cls, payload: Mapping[str, object]) -> "ProviderEffectIntent":
        """Restore exact consumed-field rules without interpreting extensions."""
        presence = payload.get("presence_state")
        state: ExternalChannelSessionPresenceState | None
        match presence:
            case "joined":
                state = "joined"
            case "left":
                state = "left"
            case _:
                state = None
        return cls(
            control_kind=_string(payload.get("control_kind")),
            setup_claim_id=_string(payload.get("setup_claim_id")),
            access_request_id=_string(payload.get("access_request_id")),
            provider_message_key=_string(payload.get("provider_message_key")),
            work_id=_string(payload.get("work_id")),
            desired_progress_revision=_integer(
                payload.get("desired_progress_revision")
            ),
            part_ordinal=_integer(payload.get("part_ordinal", 0)),
            tracker_host_kind=(
                "reply" if payload.get("tracker_host_kind") == "reply" else "standalone"
            ),
            scheduled_tracker=payload.get("tracker_kind") == "scheduled_task",
            presence_state=state,
        )


@dataclass(frozen=True)
class RetainedDiscordDeliveryIdentity:
    """Consumed provider marker and provisioned delivery identity from labels."""

    discord: bool
    delivery_channel_id: str | None

    @classmethod
    def decode(cls, labels: Mapping[str, object]) -> "RetainedDiscordDeliveryIdentity":
        """Preserve the historical Discord marker and nonempty string predicate."""
        value = _string(labels.get("delivery_channel_id"))
        return cls(
            discord=labels.get("provider") == "discord",
            delivery_channel_id=value if value else None,
        )


@dataclass(frozen=True)
class ProviderReplyPart:
    """One provider request part with its validated conversation scope."""

    payload: dict[str, object]
    conversation_scope: Literal["thread", "parent_channel"]

    @classmethod
    def decode(cls, payload: dict[str, object]) -> "ProviderReplyPart":
        """Validate the scope of an internally constructed outbound payload."""
        match payload.get("conversation_scope"):
            case "thread":
                scope: Literal["thread", "parent_channel"] = "thread"
            case "parent_channel":
                scope = "parent_channel"
            case _:
                raise ValueError("Provider reply conversation scope is invalid.")
        return cls(payload=payload, conversation_scope=scope)
