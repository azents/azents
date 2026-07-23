"""Slack provider endpoint selection with explicit deterministic test boundaries."""

import os
from urllib.parse import urlsplit

SLACK_API_BASE_URL = "https://slack.com/api"
_TESTENV_SLACK_API_BASE_URL_ENV = "AZ_TESTENV_SLACK_API_BASE_URL"
_TESTENV_SLACK_ALLOW_INSECURE_WEBSOCKET_ENV = (
    "AZ_TESTENV_SLACK_ALLOW_INSECURE_WEBSOCKET"
)


def slack_api_base_url() -> str:
    """Return the Slack Web API base URL or an explicit deterministic test URL."""
    return os.environ.get(
        _TESTENV_SLACK_API_BASE_URL_ENV,
        SLACK_API_BASE_URL,
    ).rstrip("/")


def slack_insecure_websocket_allowed() -> bool:
    """Allow ``ws://`` only with both explicit deterministic test overrides."""
    return (
        slack_api_base_url() != SLACK_API_BASE_URL
        and os.environ.get(
            _TESTENV_SLACK_ALLOW_INSECURE_WEBSOCKET_ENV,
            "",
        ).casefold()
        == "true"
    )


def slack_file_url_allowed(url: str) -> bool:
    """Accept HTTPS Slack file URLs or the exact deterministic test origin."""
    parsed = urlsplit(url)
    if parsed.scheme == "https" and parsed.netloc:
        return True
    api_base_url = slack_api_base_url()
    if api_base_url == SLACK_API_BASE_URL:
        return False
    test_endpoint = urlsplit(api_base_url)
    return (
        parsed.scheme == "http"
        and bool(parsed.netloc)
        and parsed.scheme == test_endpoint.scheme
        and parsed.netloc == test_endpoint.netloc
    )
