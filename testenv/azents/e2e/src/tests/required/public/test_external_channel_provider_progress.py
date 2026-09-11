"""External Channel provider-native progress E2E journey."""

from .external_channel_scenarios import (
    test_provider_native_channel_work_progress_journey,
)

E2E_PLANNER_FALLBACK_WEIGHT = 10.0

__all__ = ["test_provider_native_channel_work_progress_journey"]
