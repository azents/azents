"""Configured Discord conversation provisioning E2E journey."""

from .external_channel_scenarios import (
    test_discord_configured_message_durably_provisions_conversation,
)

__all__ = ["test_discord_configured_message_durably_provisions_conversation"]
