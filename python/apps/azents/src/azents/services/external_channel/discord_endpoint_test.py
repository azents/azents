"""Discord endpoint test-boundary coverage."""

from pytest import MonkeyPatch

from azents.services.external_channel.discord_endpoint import (
    DISCORD_API_BASE_URL,
    DISCORD_GATEWAY_URL,
    discord_api_base_url,
    discord_gateway_url,
    discord_test_origin_matches,
)


def test_discord_endpoint_uses_production_defaults_without_test_overrides(
    monkeypatch: MonkeyPatch,
) -> None:
    """Keep the production REST origin selected without test overrides."""
    monkeypatch.delenv("AZ_TESTENV_DISCORD_API_BASE_URL", raising=False)
    monkeypatch.delenv("AZ_TESTENV_DISCORD_GATEWAY_URL", raising=False)

    assert discord_api_base_url() == DISCORD_API_BASE_URL
    assert discord_gateway_url() == DISCORD_GATEWAY_URL
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
    monkeypatch.setenv(
        "AZ_TESTENV_DISCORD_GATEWAY_URL",
        "ws://discord-fake:8086/",
    )

    assert discord_api_base_url() == "http://discord-fake:8085/api/v10"
    assert discord_gateway_url() == "ws://discord-fake:8086"
    assert discord_test_origin_matches("http://discord-fake:8085/attachments/1") is True
    assert discord_test_origin_matches("http://other-fake:8085/attachments/1") is False
