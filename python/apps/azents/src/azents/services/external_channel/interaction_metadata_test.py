"""Closed signed modal metadata protocol tests."""

import base64
import hashlib
import hmac
import json

import pytest

from azents.core.enums import ExternalChannelResponseMode
from azents.services.external_channel.interaction import (
    _parse_selector_metadata,
    _parse_settings_metadata,
)

_SECRET = "metadata-test-secret"


def _signed(payload: dict[str, object]) -> str:
    """Sign test wire bytes through the same published compact envelope shape."""
    encoded = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode()
    signature = hmac.new(_SECRET.encode(), encoded, hashlib.sha256).digest()
    return ".".join(
        base64.urlsafe_b64encode(part).decode().rstrip("=")
        for part in (encoded, signature)
    )


def _settings_payload(target: str) -> dict[str, object]:
    common: dict[str, object] = {
        "v": 1,
        "k": target,
        "c": "connection",
        "h": "channel",
        "p": "principal",
        "i": "interaction",
    }
    if target == "setup":
        return {**common, "a": "claim", "g": 2, "s": 3}
    if target == "parent":
        return {**common, "e": "setting", "n": 4}
    return {
        **common,
        "r": "resource",
        "b": "binding",
        "m": ExternalChannelResponseMode.MENTION_ONLY.value,
        "u": "2026-10-04T00:00:00+00:00",
    }


@pytest.mark.parametrize("target", ["setup", "parent", "thread"])
def test_settings_metadata_preserves_valid_target_scope(target: str) -> None:
    parsed = _parse_settings_metadata(
        metadata=_signed(_settings_payload(target)), secret=_SECRET
    )
    assert parsed.target == target
    assert parsed.connection_id == "connection"
    assert parsed.principal_id == "principal"
    if target == "setup":
        assert parsed.setup_claim_id == "claim"
        assert parsed.claim_generation == 2
        assert parsed.source_revision == 3
    elif target == "parent":
        assert parsed.setting_id == "setting"
        assert parsed.settings_generation == 4
    else:
        assert parsed.binding_id == "binding"
        assert parsed.binding_response_mode is ExternalChannelResponseMode.MENTION_ONLY
        assert parsed.binding_updated_at is not None
        assert parsed.binding_updated_at.utcoffset() is not None


@pytest.mark.parametrize("target", ["setup", "parent", "thread"])
@pytest.mark.parametrize("extra", [{"unexpected": "ignored"}, {"o": 0}])
def test_settings_metadata_rejects_unknown_fields(
    target: str, extra: dict[str, object]
) -> None:
    with pytest.raises(ValueError, match="Slack settings metadata is invalid"):
        _parse_settings_metadata(
            metadata=_signed({**_settings_payload(target), **extra}), secret=_SECRET
        )


@pytest.mark.parametrize(
    "patch",
    [
        {"v": True},
        {"v": "1"},
        {"c": None},
        {"g": True},
        {"g": "2"},
        {"g": 0},
        {"s": 1.5},
        {"k": "unknown"},
    ],
)
def test_settings_metadata_rejects_coercion_and_invalid_scope(
    patch: dict[str, object],
) -> None:
    with pytest.raises(ValueError, match="Slack settings metadata is invalid"):
        _parse_settings_metadata(
            metadata=_signed({**_settings_payload("setup"), **patch}), secret=_SECRET
        )


def test_settings_metadata_requires_aware_thread_binding_time() -> None:
    payload = {**_settings_payload("thread"), "u": "2026-10-04T00:00:00"}
    with pytest.raises(ValueError, match="Slack settings metadata is invalid"):
        _parse_settings_metadata(metadata=_signed(payload), secret=_SECRET)


@pytest.mark.parametrize(
    "patch",
    [
        {"unexpected": "ignored"},
        {"v": True},
        {"v": "1"},
        {"o": True},
        {"o": "0"},
        {"o": -1},
    ],
)
def test_selector_metadata_rejects_unknown_fields_and_coercion(
    patch: dict[str, object],
) -> None:
    payload = {
        "v": 1,
        "c": "connection",
        "r": "resource",
        "a": "selector",
        "i": "interaction",
        "p": "principal",
        "o": 0,
    }
    with pytest.raises(ValueError, match="Slack selector metadata is invalid"):
        _parse_selector_metadata(metadata=_signed({**payload, **patch}), secret=_SECRET)
