"""External Channel multi-app workspace management E2E journeys."""

from .external_channel_scenarios import (
    test_multi_app_mention_selector_deduplicates_and_binds_open_access_route,
    test_multi_app_workspace_management_default_and_disconnect_journey,
)

E2E_PLANNER_FALLBACK_WEIGHT = 12.0

__all__ = [
    "test_multi_app_mention_selector_deduplicates_and_binds_open_access_route",
    "test_multi_app_workspace_management_default_and_disconnect_journey",
]
