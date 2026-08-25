"""Discord endpoint selection with explicit deterministic test boundaries."""

import hashlib
import hmac
import os
from urllib.parse import urljoin, urlsplit

DISCORD_API_BASE_URL = "https://discord.com/api/v10"
DISCORD_INTERACTIONS_CALLBACK_PATH = "external-channel/v1/discord/interactions/"
_TESTENV_DISCORD_API_BASE_URL_ENV = "AZ_TESTENV_DISCORD_API_BASE_URL"


def discord_api_base_url() -> str:
    """Return Discord's REST base URL or an explicit deterministic test URL."""
    return os.environ.get(
        _TESTENV_DISCORD_API_BASE_URL_ENV,
        DISCORD_API_BASE_URL,
    ).rstrip("/")


def discord_test_api_base_url() -> str | None:
    """Return the explicit deterministic REST override when configured."""
    value = os.environ.get(_TESTENV_DISCORD_API_BASE_URL_ENV)
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


def discord_interactions_endpoint_url(
    *,
    callback_base_url: str,
    selector: str,
) -> str:
    """Build one configured Discord Interaction Endpoint URL."""
    return urljoin(
        callback_base_url.rstrip("/") + "/",
        f"{DISCORD_INTERACTIONS_CALLBACK_PATH}{selector}",
    )


def discord_interactions_endpoint_matches(
    *,
    endpoint_url: str | None,
    callback_base_url: str,
    selector_hash: str,
) -> bool:
    """Match provider endpoint identity without retaining the raw selector."""
    if endpoint_url is None:
        return False
    expected = urlsplit(
        discord_interactions_endpoint_url(
            callback_base_url=callback_base_url,
            selector="",
        )
    )
    candidate = urlsplit(endpoint_url)
    if (
        candidate.scheme != expected.scheme
        or candidate.netloc != expected.netloc
        or candidate.query
        or candidate.fragment
        or not candidate.path.startswith(expected.path)
    ):
        return False
    selector = candidate.path.removeprefix(expected.path)
    if not selector or "/" in selector:
        return False
    candidate_hash = hashlib.sha256(selector.encode()).hexdigest()
    return hmac.compare_digest(candidate_hash, selector_hash)
