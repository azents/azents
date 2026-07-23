"""Slack provider endpoint selection with explicit deterministic test boundaries."""

import os

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
