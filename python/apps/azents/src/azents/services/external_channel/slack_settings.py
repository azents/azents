"""Signed Slack conversation-settings control locators."""

import base64
import hashlib
import hmac
import json
from dataclasses import dataclass

_SLACK_SETTINGS_LOCATOR_VERSION = 1
_MAX_LOCATOR_IDENTIFIER_LENGTH = 255


@dataclass(frozen=True)
class SlackSettingsLocator:
    """Verified provider-message locator without actor authority."""

    connection_id: str
    provider_parent_channel_id: str
    resource_id: str
    binding_id: str


def build_slack_settings_locator(
    *,
    secret: str,
    connection_id: str,
    provider_parent_channel_id: str,
    resource_id: str,
    binding_id: str,
) -> str:
    """Build one compact signed locator for a connected binding control."""
    payload: dict[str, object] = {
        "v": _SLACK_SETTINGS_LOCATOR_VERSION,
        "c": connection_id,
        "h": provider_parent_channel_id,
        "r": resource_id,
        "b": binding_id,
    }
    encoded = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode()
    signature = hmac.new(secret.encode(), encoded, hashlib.sha256).digest()
    return (
        base64.urlsafe_b64encode(encoded).decode().rstrip("=")
        + "."
        + base64.urlsafe_b64encode(signature).decode().rstrip("=")
    )


def parse_slack_settings_locator(
    *,
    metadata: str,
    secret: str,
) -> SlackSettingsLocator:
    """Verify one provider-message locator before reading its scope."""
    encoded_part, separator, signature_part = metadata.partition(".")
    if not separator or not encoded_part or not signature_part:
        raise ValueError("Slack settings locator is invalid.")
    try:
        encoded = _base64url_decode(encoded_part)
        signature = _base64url_decode(signature_part)
        payload = json.loads(encoded)
    except (UnicodeDecodeError, ValueError, json.JSONDecodeError) as error:
        raise ValueError("Slack settings locator is invalid.") from error
    if not isinstance(payload, dict):
        raise ValueError("Slack settings locator is invalid.")
    expected_signature = hmac.new(secret.encode(), encoded, hashlib.sha256).digest()
    if not hmac.compare_digest(signature, expected_signature):
        raise ValueError("Slack settings locator is invalid.")
    if payload.get("v") != _SLACK_SETTINGS_LOCATOR_VERSION:
        raise ValueError("Slack settings locator is invalid.")
    values: dict[str, str] = {}
    for key, attribute in {
        "c": "connection_id",
        "h": "provider_parent_channel_id",
        "r": "resource_id",
        "b": "binding_id",
    }.items():
        value = payload.get(key)
        if (
            not isinstance(value, str)
            or not value
            or len(value) > _MAX_LOCATOR_IDENTIFIER_LENGTH
        ):
            raise ValueError("Slack settings locator is invalid.")
        values[attribute] = value
    return SlackSettingsLocator(**values)


def _base64url_decode(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))
