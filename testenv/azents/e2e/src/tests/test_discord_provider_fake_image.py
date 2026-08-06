"""Discord provider fake built-image packaging coverage."""

import requests
from testcontainers.core.container import DockerContainer

_DISCORD_VERIFY_KEY = "233988c4fcf6ffd4dcf0590950d79671de856cfa36f65c16a2be13b1613875f0"


def test_discord_fake_container_uses_the_azents_server_image(
    discord_provider_fake_container: DockerContainer,
    discord_provider_fake_url: str,
) -> None:
    """Start the fake in the same Python image used by Azents E2E processes."""
    del discord_provider_fake_container
    response = requests.get(f"{discord_provider_fake_url}/health", timeout=5)
    application = requests.get(
        f"{discord_provider_fake_url}/api/v10/oauth2/applications/@me",
        timeout=5,
    )

    assert response.json() == {"status": "ok"}
    assert application.json()["verify_key"] == _DISCORD_VERIFY_KEY
    assert application.json()["owner"]["id"].isdigit()
