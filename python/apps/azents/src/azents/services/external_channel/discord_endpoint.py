"""Discord endpoint selection with explicit deterministic test boundaries."""

import os
from urllib.parse import urlsplit

DISCORD_API_BASE_URL = "https://discord.com/api/v10"
_TESTENV_DISCORD_API_BASE_URL_ENV = "AZ_TESTENV_DISCORD_API_BASE_URL"


def discord_api_base_url() -> str:
    """Return Discord's REST base URL or an explicit deterministic test URL."""
    return os.environ.get(
        _TESTENV_DISCORD_API_BASE_URL_ENV,
        DISCORD_API_BASE_URL,
    ).rstrip("/")


def discord_test_origin_matches(url: str) -> bool:
    """Return whether a URL belongs to the explicit deterministic test origin."""
    api_base_url = discord_api_base_url()
    if api_base_url == DISCORD_API_BASE_URL:
        return False
    candidate = urlsplit(url)
    configured = urlsplit(api_base_url)
    return (
        candidate.scheme == "http"
        and bool(candidate.netloc)
        and candidate.scheme == configured.scheme
        and candidate.netloc == configured.netloc
    )
