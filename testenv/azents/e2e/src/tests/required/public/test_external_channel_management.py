"""External Channel provider and connection management E2E journeys."""

from .external_channel_scenarios import (
    test_connection_update_and_repeated_disconnect,
    test_http_admission_unknown_participant_and_approval_journey,
    test_multi_app_mention_selector_deduplicates_and_binds_open_access_route,
    test_multi_app_workspace_management_default_and_disconnect_journey,
    test_provider_native_channel_work_progress_journey,
    test_slack_binding_response_modes_gate_and_preserve_context,
)

__all__ = [
    "test_connection_update_and_repeated_disconnect",
    "test_http_admission_unknown_participant_and_approval_journey",
    "test_multi_app_mention_selector_deduplicates_and_binds_open_access_route",
    "test_multi_app_workspace_management_default_and_disconnect_journey",
    "test_provider_native_channel_work_progress_journey",
    "test_slack_binding_response_modes_gate_and_preserve_context",
]
