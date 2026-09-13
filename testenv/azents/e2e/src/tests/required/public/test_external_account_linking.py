"""Required deterministic global External Account OAuth journeys."""

from .external_account_linking_scenarios import (
    test_discord_web_oauth_global_link_replay_and_unlink,
    test_oauth_auth_session_provider_and_conflict_fences,
    test_slack_web_oauth_global_reuse_unlink_and_target_fence,
)

__all__ = [
    "test_discord_web_oauth_global_link_replay_and_unlink",
    "test_oauth_auth_session_provider_and_conflict_fences",
    "test_slack_web_oauth_global_reuse_unlink_and_target_fence",
]
