"""Compiled System Settings registry provider."""

from azents.core.external_account_oauth_system_setting import (
    get_discord_identity_oauth_definition,
    get_slack_identity_oauth_definition,
)
from azents.core.external_channel_file_system_setting import (
    get_external_channel_files_definition,
)
from azents.core.github_system_setting import get_platform_github_app_definition
from azents.core.platform_runtime_system_setting import get_platform_runtime_definition
from azents.core.system_setting import SystemSettingRegistry


def get_system_setting_registry() -> SystemSettingRegistry:
    """Return the compiled System Settings Section registry."""
    return SystemSettingRegistry(
        definitions=(
            get_external_channel_files_definition(),
            get_platform_github_app_definition(),
            get_platform_runtime_definition(),
            get_slack_identity_oauth_definition(),
            get_discord_identity_oauth_definition(),
        ),
    )
