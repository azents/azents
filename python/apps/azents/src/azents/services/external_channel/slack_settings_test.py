"""Signed Slack conversation-settings locator tests."""

import pytest

from azents.services.external_channel.slack_settings import (
    SlackSettingsLocator,
    build_slack_parent_settings_locator,
    build_slack_settings_locator,
    parse_slack_settings_locator,
)


def test_settings_locator_round_trips_exact_connected_binding_scope() -> None:
    """Authenticate every identifier needed to revalidate a settings action."""
    metadata = build_slack_settings_locator(
        secret="secret",
        connection_id="connection-1",
        provider_parent_channel_id="channel-1",
        resource_id="resource-1",
        binding_id="binding-1",
    )

    assert parse_slack_settings_locator(
        metadata=metadata,
        secret="secret",
    ) == SlackSettingsLocator(
        connection_id="connection-1",
        provider_parent_channel_id="channel-1",
        resource_id="resource-1",
        binding_id="binding-1",
    )


def test_parent_settings_locator_round_trips_without_binding_scope() -> None:
    """A first-mention setup action authenticates only its parent conversation."""
    metadata = build_slack_parent_settings_locator(
        secret="secret",
        connection_id="connection-1",
        provider_parent_channel_id="channel-1",
    )

    assert parse_slack_settings_locator(
        metadata=metadata,
        secret="secret",
    ) == SlackSettingsLocator(
        connection_id="connection-1",
        provider_parent_channel_id="channel-1",
        resource_id=None,
        binding_id=None,
    )


@pytest.mark.parametrize("mutation", ["payload", "signature"])
def test_settings_locator_rejects_tampering(mutation: str) -> None:
    """A modified provider control cannot select another conversation scope."""
    metadata = build_slack_settings_locator(
        secret="secret",
        connection_id="connection-1",
        provider_parent_channel_id="channel-1",
        resource_id="resource-1",
        binding_id="binding-1",
    )
    payload, signature = metadata.split(".", maxsplit=1)
    tampered = (
        f"{payload[:-1]}A.{signature}"
        if mutation == "payload"
        else f"{payload}.{signature[:-1]}A"
    )

    with pytest.raises(ValueError, match="locator is invalid"):
        parse_slack_settings_locator(metadata=tampered, secret="secret")
