"""Configured public Slack SDK clients for External Channel operations."""

import logging

from slack_sdk.web.async_client import AsyncWebClient

from azents.services.external_channel.slack_endpoint import slack_api_base_url


def create_slack_web_client() -> AsyncWebClient:
    """Create a non-retrying Slack client that cannot log provider content."""
    return AsyncWebClient(
        base_url=f"{slack_api_base_url().rstrip('/')}/",
        timeout=20,
        retry_handlers=[],
        logger=_slack_sdk_logger(),
    )


def _slack_sdk_logger() -> logging.Logger:
    """Create a silent SDK logger for payload-bearing Web API operations."""
    sdk_logger = logging.Logger(
        "azents.services.external_channel.slack_sdk",
        level=logging.CRITICAL,
    )
    sdk_logger.addHandler(logging.NullHandler())
    sdk_logger.propagate = False
    return sdk_logger
