"""Signed Discord selector component scope helpers."""

import base64
import hashlib
import hmac

_SELECTOR_PREFIX = "azents-selector"
_SELECTOR_ACTIONS = {"open", "select", "previous", "next"}
_SELECTOR_TOKEN_SIGNATURE_BYTES = 16


def build_discord_selector_custom_id(
    *,
    secret: str,
    selector_interaction_id: str,
    action: str,
    offset: int = 0,
) -> str:
    """Sign one compact selector scope that fits Discord's custom-ID bound."""
    if (
        action not in _SELECTOR_ACTIONS
        or not selector_interaction_id
        or len(selector_interaction_id) > 64
        or offset < 0
    ):
        raise ValueError("Discord selector scope is invalid.")
    payload = f"{action}:{selector_interaction_id}:{offset}".encode()
    signature = hmac.new(secret.encode(), payload, hashlib.sha256).digest()[
        :_SELECTOR_TOKEN_SIGNATURE_BYTES
    ]
    encoded_signature = base64.urlsafe_b64encode(signature).decode().rstrip("=")
    return (
        f"{_SELECTOR_PREFIX}:{action}:{selector_interaction_id}:"
        f"{offset}:{encoded_signature}"
    )
