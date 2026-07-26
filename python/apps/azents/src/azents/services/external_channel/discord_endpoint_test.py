"""Discord endpoint test-boundary coverage."""

from pytest import MonkeyPatch

from azents.services.external_channel.discord_endpoint import (
    DISCORD_API_BASE_URL,
    discord_api_base_url,
    discord_gateway_url_allowed,
    discord_insecure_gateway_allowed,
    discord_test_origin_matches,
)


def test_discord_endpoint_uses_production_defaults_without_test_overrides(
    monkeypatch: MonkeyPatch,
) -> None:
    """Keep production REST and Gateway transport defaults secure."""
    monkeypatch.delenv("AZ_TESTENV_DISCORD_API_BASE_URL", raising=False)
    monkeypatch.delenv("AZ_TESTENV_DISCORD_ALLOW_INSECURE_GATEWAY", raising=False)

    assert discord_api_base_url() == DISCORD_API_BASE_URL
    assert discord_insecure_gateway_allowed() is False
    assert discord_gateway_url_allowed("wss://gateway.discord.gg") is True
    assert discord_gateway_url_allowed("ws://discord-fake:8086") is False
    assert (
        discord_test_origin_matches("http://discord-fake:8085/attachments/1") is False
    )


def test_discord_endpoint_allows_insecure_gateway_only_for_test_origin(
    monkeypatch: MonkeyPatch,
) -> None:
    """Require both explicit deterministic test endpoint and opt-in flag."""
    monkeypatch.setenv(
        "AZ_TESTENV_DISCORD_API_BASE_URL",
        "http://discord-fake:8085/api/v10/",
    )
    monkeypatch.delenv("AZ_TESTENV_DISCORD_ALLOW_INSECURE_GATEWAY", raising=False)

    assert discord_api_base_url() == "http://discord-fake:8085/api/v10"
    assert discord_insecure_gateway_allowed() is False
    assert discord_test_origin_matches("http://discord-fake:8085/attachments/1") is True
    assert discord_test_origin_matches("http://other-fake:8085/attachments/1") is False

    monkeypatch.setenv("AZ_TESTENV_DISCORD_ALLOW_INSECURE_GATEWAY", "true")

    assert discord_insecure_gateway_allowed() is True
    assert discord_gateway_url_allowed("ws://discord-fake:8086") is True
