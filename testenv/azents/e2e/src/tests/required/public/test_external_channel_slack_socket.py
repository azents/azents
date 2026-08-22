"""External Channel Slack Socket Mode E2E journeys."""

from .external_channel_scenarios import (
    test_socket_mode_recovers_then_acknowledges_and_preserves_route,
)

__all__ = ["test_socket_mode_recovers_then_acknowledges_and_preserves_route"]
