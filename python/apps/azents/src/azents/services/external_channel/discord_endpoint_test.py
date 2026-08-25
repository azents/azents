"""Discord endpoint test-boundary coverage."""

import hashlib

import pytest
from pytest import MonkeyPatch

from azents.services.external_channel.discord_endpoint import (
    DISCORD_API_BASE_URL,
    discord_api_base_url,
    discord_interactions_endpoint_matches,
    discord_interactions_endpoint_url,
    discord_test_origin_matches,
)


def test_discord_endpoint_uses_production_defaults_without_test_overrides(
    monkeypatch: MonkeyPatch,
) -> None:
    """Keep the production REST origin selected without test overrides."""
    monkeypatch.delenv("AZ_TESTENV_DISCORD_API_BASE_URL", raising=False)

    assert discord_api_base_url() == DISCORD_API_BASE_URL
    assert (
        discord_test_origin_matches("http://discord-fake:8085/attachments/1") is False
    )


def test_discord_endpoint_allows_explicit_rest_test_origin(
    monkeypatch: MonkeyPatch,
) -> None:
    """Allow deterministic REST traffic only for the configured test origin."""
    monkeypatch.setenv(
        "AZ_TESTENV_DISCORD_API_BASE_URL",
        "http://discord-fake:8085/api/v10/",
    )
    assert discord_api_base_url() == "http://discord-fake:8085/api/v10"
    assert discord_test_origin_matches("http://discord-fake:8085/attachments/1") is True
    assert discord_test_origin_matches("http://other-fake:8085/attachments/1") is False


def test_discord_interactions_endpoint_matches_exact_selector_authority() -> None:
    """The provider URL matches through its selector hash without retention."""
    selector = "opaque-selector"
    endpoint_url = discord_interactions_endpoint_url(
        callback_base_url="https://callbacks.example/base/",
        selector=selector,
    )

    assert discord_interactions_endpoint_matches(
        endpoint_url=endpoint_url,
        callback_base_url="https://callbacks.example/base/",
        selector_hash=hashlib.sha256(selector.encode()).hexdigest(),
    )


@pytest.mark.parametrize(
    "endpoint_url",
    [
        None,
        "https://other.example/base/external-channel/v1/discord/interactions/selector",
        "https://callbacks.example/base/external-channel/v1/discord/interactions/wrong",
        (
            "https://callbacks.example/base/external-channel/v1/discord/interactions/"
            "selector/extra"
        ),
    ],
)
def test_discord_interactions_endpoint_rejects_drift(
    endpoint_url: str | None,
) -> None:
    """Absent, origin, selector, and path drift all fail closed."""
    assert not discord_interactions_endpoint_matches(
        endpoint_url=endpoint_url,
        callback_base_url="https://callbacks.example/base/",
        selector_hash=hashlib.sha256(b"selector").hexdigest(),
    )
