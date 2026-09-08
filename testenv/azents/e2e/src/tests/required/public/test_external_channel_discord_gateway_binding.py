"""Discord gateway location binding E2E journey."""

from .external_channel_scenarios import (
    test_discord_gateway_message_waits_for_location_then_binds,
)

__all__ = ["test_discord_gateway_message_waits_for_location_then_binds"]
