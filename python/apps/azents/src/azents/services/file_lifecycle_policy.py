"""File lifecycle policy helpers."""

import datetime

from azents.core.config import Config


def artifact_expires_at(
    *,
    now: datetime.datetime,
    config: Config,
) -> datetime.datetime:
    """Return Artifact expiration timestamp from configured TTL."""
    return now + config.file_lifecycle.artifact_ttl


def exchange_file_expires_at(
    *,
    now: datetime.datetime,
    config: Config,
) -> datetime.datetime:
    """Return ExchangeFile expiration timestamp from configured TTL."""
    return now + config.file_lifecycle.exchange_file_ttl
