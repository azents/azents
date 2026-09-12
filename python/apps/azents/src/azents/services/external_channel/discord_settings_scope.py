"""Compact signed Discord conversation-settings component scopes."""

import base64
import binascii
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
_DISCORD_ACCOUNT_LINK_PREFIX = "al1"
_DISCORD_MODEL_SETTINGS_PREFIX = "ms1"
_DISCORD_SETTINGS_SIGNATURE_BYTES = 16

DiscordSettingsAction = Literal[
    "open",
    "open_binding",
    "setup_channel",
    "setup_threads",
    "parent_location",
    "parent_response_mode",
    "thread_response_mode",
]

DiscordAccountLinkAction = Literal["start", "enter_code"]

DiscordModelSettingsAction = Literal[
    "open",
    "select_model",
    "select_reasoning",
    "select_execution",
    "previous_page",
    "next_page",
    "apply",
    "cancel",
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


@dataclass(frozen=True)
class DiscordAccountLinkScope:
    """One signed private account-link control locator."""

    action: DiscordAccountLinkAction
    origin_interaction_id: str | None
    origin_id: str | None


@dataclass(frozen=True)
class DiscordModelSettingsScope:
    """One signed actor-owned model draft control locator."""

    action: DiscordModelSettingsAction
    draft_id: str
    offset: int
    selection_fingerprint: str | None


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
    thread_action = action == "thread_response_mode"
    fields: list[str] = [
        _DISCORD_SETTINGS_PREFIX,
        _action_code(action),
        (
            _compact_identifier(origin_interaction_id)
            if thread_action
            else _identifier(origin_interaction_id)
        ),
    ]
    if action in {"setup_channel", "setup_threads"}:
        setup_claim_id = _identifier(setup_claim_id)
        _require_positive_int(claim_generation)
        _require_positive_int(source_revision)
        fields.extend((setup_claim_id, str(claim_generation), str(source_revision)))
    elif action in {"parent_location", "parent_response_mode"}:
        setting_id = _identifier(setting_id)
        _require_positive_int(settings_generation)
        fields.extend((setting_id, str(settings_generation)))
    elif thread_action:
        binding_id = _compact_identifier(binding_id)
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
    thread_action = action == "thread_response_mode"
    origin_interaction_id = (
        _expanded_identifier(unsigned_fields[2])
        if thread_action
        else _identifier(unsigned_fields[2])
    )
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
    if action in {"parent_location", "parent_response_mode"}:
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
    if thread_action:
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
            binding_id=_expanded_identifier(extra[0]),
            binding_version=binding_version,
        )
    raise AssertionError("Discord settings action is not exhaustive.")


def build_discord_account_link_custom_id(
    *,
    secret: str,
    action: DiscordAccountLinkAction,
    origin_interaction_id: str | None,
    origin_id: str | None,
) -> str:
    """Build one signed actor-bound account-link component or modal ID."""
    if action == "start":
        value = _identifier(origin_interaction_id)
        if origin_id is not None:
            raise ValueError("Discord account-link scope is invalid.")
        action_code = "s"
    elif action == "enter_code":
        value = _identifier(origin_id)
        if origin_interaction_id is not None:
            raise ValueError("Discord account-link scope is invalid.")
        action_code = "e"
    else:
        raise AssertionError("Discord account-link action is not exhaustive.")
    fields = [_DISCORD_ACCOUNT_LINK_PREFIX, action_code, value]
    custom_id = ":".join((*fields, _signature(secret=secret, fields=fields)))
    if len(custom_id) > 100:
        raise ValueError("Discord account-link scope exceeds the component limit.")
    return custom_id


def parse_discord_account_link_custom_id(
    *,
    custom_id: str,
    secret: str,
) -> DiscordAccountLinkScope:
    """Verify and parse one private account-link component or modal ID."""
    fields = custom_id.split(":")
    if len(fields) != 4 or fields[0] != _DISCORD_ACCOUNT_LINK_PREFIX:
        raise ValueError("Discord account-link scope is invalid.")
    unsigned_fields = fields[:-1]
    if not hmac.compare_digest(
        fields[-1], _signature(secret=secret, fields=unsigned_fields)
    ):
        raise ValueError("Discord account-link scope is invalid.")
    value = _identifier(fields[2])
    if fields[1] == "s":
        return DiscordAccountLinkScope(
            action="start",
            origin_interaction_id=value,
            origin_id=None,
        )
    if fields[1] == "e":
        return DiscordAccountLinkScope(
            action="enter_code",
            origin_interaction_id=None,
            origin_id=value,
        )
    raise ValueError("Discord account-link scope is invalid.")


def build_discord_model_settings_custom_id(
    *,
    secret: str,
    action: DiscordModelSettingsAction,
    draft_id: str,
    offset: int,
    selection_fingerprint: str | None,
) -> str:
    """Build one signed model-draft action without embedding model authority."""
    fields = [
        _DISCORD_MODEL_SETTINGS_PREFIX,
        _model_action_code(action),
        _compact_identifier(draft_id),
        str(_nonnegative_int(offset)),
        _model_selection_fingerprint(
            selection_fingerprint,
            required=action == "apply",
        ),
    ]
    custom_id = ":".join((*fields, _signature(secret=secret, fields=fields)))
    if len(custom_id) > 100:
        raise ValueError("Discord model settings scope exceeds the component limit.")
    return custom_id


def parse_discord_model_settings_custom_id(
    *,
    custom_id: str,
    secret: str,
) -> DiscordModelSettingsScope:
    """Verify and parse one actor-owned model-draft action."""
    fields = custom_id.split(":")
    if len(fields) != 6 or fields[0] != _DISCORD_MODEL_SETTINGS_PREFIX:
        raise ValueError("Discord model settings scope is invalid.")
    unsigned_fields = fields[:-1]
    if not hmac.compare_digest(
        fields[-1], _signature(secret=secret, fields=unsigned_fields)
    ):
        raise ValueError("Discord model settings scope is invalid.")
    action = _model_action_from_code(fields[1])
    selection_fingerprint = (
        None
        if fields[4] == "-"
        else _model_selection_fingerprint(fields[4], required=True)
    )
    if (action == "apply") != (selection_fingerprint is not None):
        raise ValueError("Discord model settings scope is invalid.")
    return DiscordModelSettingsScope(
        action=action,
        draft_id=_expanded_identifier(fields[2]),
        offset=_nonnegative_int(fields[3]),
        selection_fingerprint=selection_fingerprint,
    )


def discord_binding_version(updated_at: datetime.datetime) -> str:
    """Return a compact equality fence for one connected Binding revision."""
    if updated_at.tzinfo is None:
        raise ValueError("Discord binding settings scope is invalid.")
    return _binding_version(updated_at)


def settings_setup_location(
    action: DiscordSettingsAction,
) -> ExternalChannelConversationLocation | None:
    """Return the setup location selected by one button action."""
    if action == "setup_channel":
        return ExternalChannelConversationLocation.CHANNEL
    if action == "setup_threads":
        return ExternalChannelConversationLocation.THREADS
    return None


def settings_selected_location(
    value: str | None,
) -> ExternalChannelConversationLocation | None:
    """Return one validated parent location Select value."""
    if value == "channel":
        return ExternalChannelConversationLocation.CHANNEL
    if value == "threads":
        return ExternalChannelConversationLocation.THREADS
    return None


def settings_selected_response_mode(
    value: str | None,
) -> ExternalChannelResponseMode | None:
    """Return one validated response-mode Select value."""
    if value == "mention_only":
        return ExternalChannelResponseMode.MENTION_ONLY
    if value == "all_messages":
        return ExternalChannelResponseMode.ALL_MESSAGES
    return None


def _action_code(action: DiscordSettingsAction) -> str:
    return {
        "open": "o",
        "open_binding": "ob",
        "setup_channel": "sc",
        "setup_threads": "st",
        "parent_location": "pl",
        "parent_response_mode": "pr",
        "thread_response_mode": "tr",
    }[action]


def _action_from_code(code: str) -> DiscordSettingsAction:
    actions: dict[str, DiscordSettingsAction] = {
        "o": "open",
        "ob": "open_binding",
        "sc": "setup_channel",
        "st": "setup_threads",
        "pl": "parent_location",
        "pr": "parent_response_mode",
        "tr": "thread_response_mode",
    }
    try:
        return actions[code]
    except KeyError as error:
        raise ValueError("Discord settings scope is invalid.") from error


def _model_action_code(action: DiscordModelSettingsAction) -> str:
    return {
        "open": "o",
        "select_model": "m",
        "select_reasoning": "r",
        "select_execution": "x",
        "previous_page": "p",
        "next_page": "n",
        "apply": "a",
        "cancel": "c",
    }[action]


def _model_action_from_code(code: str) -> DiscordModelSettingsAction:
    actions: dict[str, DiscordModelSettingsAction] = {
        "o": "open",
        "m": "select_model",
        "r": "select_reasoning",
        "x": "select_execution",
        "p": "previous_page",
        "n": "next_page",
        "a": "apply",
        "c": "cancel",
    }
    try:
        return actions[code]
    except KeyError as error:
        raise ValueError("Discord model settings scope is invalid.") from error


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


def _compact_identifier(value: str | None) -> str:
    identifier = _identifier(value)
    if len(identifier) != 32 or any(
        character not in "0123456789abcdef" for character in identifier
    ):
        raise ValueError("Discord settings scope is invalid.")
    return base64.urlsafe_b64encode(bytes.fromhex(identifier)).decode().rstrip("=")


def _expanded_identifier(value: str) -> str:
    if len(value) != 22:
        raise ValueError("Discord settings scope is invalid.")
    try:
        decoded = base64.b64decode(f"{value}==", altchars=b"-_", validate=True)
    except binascii.Error as error:
        raise ValueError("Discord settings scope is invalid.") from error
    if len(decoded) != 16:
        raise ValueError("Discord settings scope is invalid.")
    identifier = decoded.hex()
    if _compact_identifier(identifier) != value:
        raise ValueError("Discord settings scope is invalid.")
    return identifier


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


def _nonnegative_int(value: object) -> int:
    if isinstance(value, bool):
        raise ValueError("Discord settings scope is invalid.")
    if isinstance(value, int):
        parsed = value
    elif isinstance(value, str) and value.isascii() and value.isdigit():
        parsed = int(value)
    else:
        raise ValueError("Discord settings scope is invalid.")
    if parsed < 0:
        raise ValueError("Discord settings scope is invalid.")
    return parsed


def _model_selection_fingerprint(value: str | None, *, required: bool) -> str:
    if value is None:
        if required:
            raise ValueError("Discord model settings scope is invalid.")
        return "-"
    if len(value) != 16 or any(
        character not in "0123456789abcdef" for character in value
    ):
        raise ValueError("Discord model settings scope is invalid.")
    return value
