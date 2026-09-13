"""Provider identity OAuth System Settings contract tests."""

import pytest
from pydantic import ValidationError

from azents.core.external_account_oauth_system_setting import (
    DiscordIdentityOAuthConfig,
    ExternalAccountOAuthConfig,
    get_discord_identity_oauth_definition,
    get_slack_identity_oauth_definition,
)
from azents.core.system_setting import SystemSettingActivationMode, SystemSettingSection


def test_slack_definition_is_direct_and_unbound() -> None:
    """Slack identity OAuth is an Admin-owned direct Section."""
    definition = get_slack_identity_oauth_definition()

    assert definition.section is SystemSettingSection.SLACK_IDENTITY_OAUTH
    assert definition.activation_mode is SystemSettingActivationMode.DIRECT
    assert definition.environment_bindings == ()


def test_discord_definition_is_direct_and_unbound() -> None:
    """Discord identity OAuth is an Admin-owned direct Section."""
    definition = get_discord_identity_oauth_definition()

    assert definition.section is SystemSettingSection.DISCORD_IDENTITY_OAUTH
    assert definition.activation_mode is SystemSettingActivationMode.DIRECT
    assert definition.environment_bindings == ()


def test_provider_client_ids_reject_blank_values() -> None:
    """Blank provider client identities cannot become effective configuration."""
    with pytest.raises(ValidationError):
        ExternalAccountOAuthConfig(client_id=" ")
    with pytest.raises(ValidationError):
        DiscordIdentityOAuthConfig(application_id="not-a-snowflake")
