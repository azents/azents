"""Compact signed Discord conversation-settings component scopes."""

import base64
import datetime
import hashlib
import hmac
from dataclasses import dataclass
from typing import Literal

from azents.core.enums import (
    ExternalChannelConversationLocation,
    ExternalChannelResponseMode,
)

_DISCORD_SETTINGS_PREFIX = "a"
_DISCORD_SETTINGS_SIGNATURE_BYTES = 16

DiscordSettingsAction = Literal[
    "open",
    "open_binding",
    "setup_channel",
    "setup_threads",
    "parent_channel",
    "parent_threads",
    "parent_mention_only",
    "parent_all_messages",
    "thread_mention_only",
    "thread_all_messages",
]


@dataclass(frozen=True)
class DiscordSettingsScope:
    """One verified provider component scope with current-state fences."""

    action: DiscordSettingsAction
    origin_interaction_id: str
    setup_claim_id: str | None
    claim_generation: int | None
    source_revision: int | None
    setting_id: str | None
    settings_generation: int | None
    binding_id: str | None
    binding_version: str | None


def build_discord_binding_settings_open_custom_id(
    *,
    secret: str,
    binding_id: str,
) -> str:
    """Build a signed joined-presence settings locator for one Binding."""
    return build_discord_settings_custom_id(
        secret=secret,
        action="open_binding",
        origin_interaction_id=binding_id,
    )


def build_discord_settings_custom_id(
    *,
    secret: str,
    action: DiscordSettingsAction,
    origin_interaction_id: str,
    setup_claim_id: str | None = None,
    claim_generation: int | None = None,
    source_revision: int | None = None,
    setting_id: str | None = None,
    settings_generation: int | None = None,
    binding_id: str | None = None,
    binding_updated_at: datetime.datetime | None = None,
) -> str:
    """Build one signed component ID from opaque durable IDs and generations."""
    _require_identifier(origin_interaction_id)
    fields: list[str] = [
        _DISCORD_SETTINGS_PREFIX,
        _action_code(action),
        origin_interaction_id,
    ]
    if action in {"setup_channel", "setup_threads"}:
        setup_claim_id = _identifier(setup_claim_id)
        _require_positive_int(claim_generation)
        _require_positive_int(source_revision)
        fields.extend((setup_claim_id, str(claim_generation), str(source_revision)))
    elif action in {
        "parent_channel",
        "parent_threads",
        "parent_mention_only",
        "parent_all_messages",
    }:
        setting_id = _identifier(setting_id)
        _require_positive_int(settings_generation)
        fields.extend((setting_id, str(settings_generation)))
    elif action in {"thread_mention_only", "thread_all_messages"}:
        binding_id = _identifier(binding_id)
        if binding_updated_at is None or binding_updated_at.tzinfo is None:
            raise ValueError("Discord binding settings scope is invalid.")
        fields.extend((binding_id, _binding_version(binding_updated_at)))
    elif action not in {"open", "open_binding"}:
        raise AssertionError("Discord settings action is not exhaustive.")
    signature = _signature(secret=secret, fields=fields)
    custom_id = ":".join((*fields, signature))
    if len(custom_id) > 100:
        raise ValueError("Discord settings scope exceeds the component limit.")
    return custom_id


def parse_discord_settings_custom_id(
    *,
    custom_id: str,
    secret: str,
) -> DiscordSettingsScope:
    """Verify and parse one compact conversation-settings component scope."""
    fields = custom_id.split(":")
    if len(fields) < 4 or fields[0] != _DISCORD_SETTINGS_PREFIX:
        raise ValueError("Discord settings scope is invalid.")
    raw_action = fields[1]
    action = _action_from_code(raw_action)
    signature = fields[-1]
    unsigned_fields = fields[:-1]
    if not hmac.compare_digest(
        signature, _signature(secret=secret, fields=unsigned_fields)
    ):
        raise ValueError("Discord settings scope is invalid.")
    origin_interaction_id = unsigned_fields[2]
    _require_identifier(origin_interaction_id)
    extra = unsigned_fields[3:]
    if action in {"open", "open_binding"}:
        if extra:
            raise ValueError("Discord settings scope is invalid.")
        return DiscordSettingsScope(
            action=action,
            origin_interaction_id=origin_interaction_id,
            setup_claim_id=None,
            claim_generation=None,
            source_revision=None,
            setting_id=None,
            settings_generation=None,
            binding_id=None,
            binding_version=None,
        )
    if action in {"setup_channel", "setup_threads"}:
        if len(extra) != 3:
            raise ValueError("Discord settings scope is invalid.")
        return DiscordSettingsScope(
            action=action,
            origin_interaction_id=origin_interaction_id,
            setup_claim_id=_identifier(extra[0]),
            claim_generation=_positive_int(extra[1]),
            source_revision=_positive_int(extra[2]),
            setting_id=None,
            settings_generation=None,
            binding_id=None,
            binding_version=None,
        )
    if action in {
        "parent_channel",
        "parent_threads",
        "parent_mention_only",
        "parent_all_messages",
    }:
        if len(extra) != 2:
            raise ValueError("Discord settings scope is invalid.")
        return DiscordSettingsScope(
            action=action,
            origin_interaction_id=origin_interaction_id,
            setup_claim_id=None,
            claim_generation=None,
            source_revision=None,
            setting_id=_identifier(extra[0]),
            settings_generation=_positive_int(extra[1]),
            binding_id=None,
            binding_version=None,
        )
    if action in {"thread_mention_only", "thread_all_messages"}:
        if len(extra) != 2:
            raise ValueError("Discord settings scope is invalid.")
        binding_version = extra[1]
        if len(binding_version) != 16 or any(
            character not in "0123456789abcdef" for character in binding_version
        ):
            raise ValueError("Discord settings scope is invalid.")
        return DiscordSettingsScope(
            action=action,
            origin_interaction_id=origin_interaction_id,
            setup_claim_id=None,
            claim_generation=None,
            source_revision=None,
            setting_id=None,
            settings_generation=None,
            binding_id=_identifier(extra[0]),
            binding_version=binding_version,
        )
    raise AssertionError("Discord settings action is not exhaustive.")


def discord_binding_version(updated_at: datetime.datetime) -> str:
    """Return a compact equality fence for one connected Binding revision."""
    if updated_at.tzinfo is None:
        raise ValueError("Discord binding settings scope is invalid.")
    return _binding_version(updated_at)


def settings_action_location(
    action: DiscordSettingsAction,
) -> ExternalChannelConversationLocation | None:
    """Return the parent location selected by one component action."""
    if action in {"setup_channel", "parent_channel"}:
        return ExternalChannelConversationLocation.CHANNEL
    if action in {"setup_threads", "parent_threads"}:
        return ExternalChannelConversationLocation.THREADS
    return None


def settings_action_response_mode(
    action: DiscordSettingsAction,
) -> ExternalChannelResponseMode | None:
    """Return the concrete response mode selected by one component action."""
    if action in {"parent_mention_only", "thread_mention_only"}:
        return ExternalChannelResponseMode.MENTION_ONLY
    if action in {"parent_all_messages", "thread_all_messages"}:
        return ExternalChannelResponseMode.ALL_MESSAGES
    return None


def _action_code(action: DiscordSettingsAction) -> str:
    return {
        "open": "o",
        "open_binding": "ob",
        "setup_channel": "sc",
        "setup_threads": "st",
        "parent_channel": "pc",
        "parent_threads": "pt",
        "parent_mention_only": "pm",
        "parent_all_messages": "pa",
        "thread_mention_only": "tm",
        "thread_all_messages": "ta",
    }[action]


def _action_from_code(code: str) -> DiscordSettingsAction:
    actions: dict[str, DiscordSettingsAction] = {
        "o": "open",
        "ob": "open_binding",
        "sc": "setup_channel",
        "st": "setup_threads",
        "pc": "parent_channel",
        "pt": "parent_threads",
        "pm": "parent_mention_only",
        "pa": "parent_all_messages",
        "tm": "thread_mention_only",
        "ta": "thread_all_messages",
    }
    try:
        return actions[code]
    except KeyError as error:
        raise ValueError("Discord settings scope is invalid.") from error


def _signature(*, secret: str, fields: list[str]) -> str:
    digest = hmac.new(
        secret.encode(), ":".join(fields).encode(), hashlib.sha256
    ).digest()
    return (
        base64.urlsafe_b64encode(digest[:_DISCORD_SETTINGS_SIGNATURE_BYTES])
        .decode()
        .rstrip("=")
    )


def _binding_version(updated_at: datetime.datetime) -> str:
    return hashlib.sha256(updated_at.isoformat().encode()).hexdigest()[:16]


def _require_identifier(value: str | None) -> None:
    _identifier(value)


def _identifier(value: str | None) -> str:
    if not isinstance(value, str) or not value or len(value) > 64 or ":" in value:
        raise ValueError("Discord settings scope is invalid.")
    return value


def _require_positive_int(value: int | None) -> None:
    _positive_int(value)


def _positive_int(value: object) -> int:
    if isinstance(value, bool):
        raise ValueError("Discord settings scope is invalid.")
    if isinstance(value, int):
        parsed = value
    elif isinstance(value, str) and value.isascii() and value.isdigit():
        parsed = int(value)
    else:
        raise ValueError("Discord settings scope is invalid.")
    if parsed <= 0:
        raise ValueError("Discord settings scope is invalid.")
    return parsed
