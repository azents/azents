"""Configured Slack SDK client security-boundary tests."""

import logging

from azents.services.external_channel.slack_sdk_client import (
    create_slack_web_client,
)


def test_slack_web_client_disables_retries_and_payload_logging() -> None:
    """Keep provider mutations one-attempt and provider content out of SDK logs."""
    client = create_slack_web_client()
    sdk_logger = client._logger  # pyright: ignore[reportPrivateUsage]

    assert client.retry_handlers == []
    assert isinstance(sdk_logger, logging.Logger)
    assert sdk_logger.level == logging.CRITICAL
    assert sdk_logger.propagate is False
    assert any(
        isinstance(handler, logging.NullHandler) for handler in sdk_logger.handlers
    )
