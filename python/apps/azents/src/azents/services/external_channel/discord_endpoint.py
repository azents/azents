"""Discord endpoint selection with explicit deterministic test boundaries."""

import os
from urllib.parse import urlsplit

DISCORD_API_BASE_URL = "https://discord.com/api/v10"
DISCORD_GATEWAY_URL = "wss://gateway.discord.gg"
_TESTENV_DISCORD_API_BASE_URL_ENV = "AZ_TESTENV_DISCORD_API_BASE_URL"
_TESTENV_DISCORD_GATEWAY_URL_ENV = "AZ_TESTENV_DISCORD_GATEWAY_URL"


def discord_api_base_url() -> str:
    """Return Discord's REST base URL or an explicit deterministic test URL."""
    return os.environ.get(
        _TESTENV_DISCORD_API_BASE_URL_ENV,
        DISCORD_API_BASE_URL,
    ).rstrip("/")


def discord_gateway_url() -> str:
    """Return Discord's Gateway URL or an explicit deterministic test URL."""
    return os.environ.get(
        _TESTENV_DISCORD_GATEWAY_URL_ENV,
        DISCORD_GATEWAY_URL,
    ).rstrip("/")


def discord_test_api_base_url() -> str | None:
    """Return the explicit deterministic REST override when configured."""
    value = os.environ.get(_TESTENV_DISCORD_API_BASE_URL_ENV)
    return value.rstrip("/") if value is not None else None


def discord_test_gateway_url() -> str | None:
    """Return the explicit deterministic Gateway override when configured."""
    value = os.environ.get(_TESTENV_DISCORD_GATEWAY_URL_ENV)
    return value.rstrip("/") if value is not None else None


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
