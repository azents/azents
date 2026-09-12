"""Provider return navigation tests."""

import datetime

from azents.core.enums import ExternalChannelProvider
from azents.rdb.models.external_account_link import RDBExternalAccountLinkOrigin

from . import _provider_return_url


def test_discord_return_prefers_exact_thread_channel() -> None:
    """Return to a Discord thread, which is itself a provider channel."""
    origin = _origin(
        provider=ExternalChannelProvider.DISCORD,
        provider_channel_id="parent channel",
        provider_thread_id="thread channel",
    )

    assert _provider_return_url(origin) == (
        "https://discord.com/channels/guild%20id/thread%20channel"
    )


def test_slack_return_uses_supported_team_channel_redirect() -> None:
    """Keep Slack return navigation on the supported team/channel surface."""
    origin = _origin(
        provider=ExternalChannelProvider.SLACK,
        provider_channel_id="channel id",
        provider_thread_id="thread timestamp",
    )

    assert _provider_return_url(origin) == (
        "https://slack.com/app_redirect?team=team%20id&channel=channel%20id"
    )


def _origin(
    *,
    provider: ExternalChannelProvider,
    provider_channel_id: str,
    provider_thread_id: str | None,
) -> RDBExternalAccountLinkOrigin:
    now = datetime.datetime(2026, 9, 12, tzinfo=datetime.UTC)
    return RDBExternalAccountLinkOrigin(
        workspace_id="workspace",
        connection_id="connection",
        connection_configuration_generation=1,
        principal_id="principal",
        provider=provider,
        identity_scope="scope",
        provider_tenant_id="guild id"
        if provider is ExternalChannelProvider.DISCORD
        else "team id",
        provider_tenant_display_label="Tenant",
        provider_user_id="provider-user",
        provider_display_label="Provider User",
        provider_interaction_id="interaction",
        provider_channel_id=provider_channel_id,
        provider_thread_id=provider_thread_id,
        expires_at=now + datetime.timedelta(minutes=10),
        candidate_count=0,
        invalid_code_count=0,
        cancelled_at=None,
        consumed_at=None,
    )
