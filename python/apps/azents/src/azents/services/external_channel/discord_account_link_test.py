"""Discord-native provider account connection presentation tests."""

import datetime

from azents.core.enums import ExternalChannelProvider
from azents.core.external_account_link import (
    ExternalAccountLinkState,
    ExternalAccountLinkView,
    ExternalAccountNativeLinkState,
)
from azents.services.external_account_oauth_system_setting.data import (
    ExternalAccountOAuthEffectiveStatus,
)
from azents.services.external_channel.discord_account_link import (
    discord_account_link_presentation,
)

_NOW = datetime.datetime(2026, 9, 13, tzinfo=datetime.UTC)


def _components(row: dict[str, object]) -> list[dict[str, object]]:
    components = row["components"]
    assert isinstance(components, list)
    assert all(isinstance(component, dict) for component in components)
    return components


def _active_state() -> ExternalAccountNativeLinkState:
    return ExternalAccountNativeLinkState(
        link=ExternalAccountLinkView(
            id="link-1",
            workspace_id=None,
            workspace_name=None,
            workspace_handle=None,
            user_id="user-1",
            provider=ExternalChannelProvider.DISCORD,
            identity_scope="global",
            provider_user_id="discord-user-1",
            provider_tenant_display_label=None,
            provider_display_label="Discord User",
            linked_at=_NOW,
            state=ExternalAccountLinkState.ACTIVE,
        ),
        management_path="/account/external-accounts",
    )


def test_ready_unlinked_presentation_is_one_direct_web_url() -> None:
    """Navigate directly to the protected provider-specific Web connection entry."""
    presentation = discord_account_link_presentation(
        state=ExternalAccountNativeLinkState(
            link=None,
            management_path="/account/external-accounts",
        ),
        provider_status=ExternalAccountOAuthEffectiveStatus.READY,
        web_url="https://azents.example/",
    )

    assert presentation.summary == (
        "Use your Azents account for authorized conversation model settings."
    )
    button = _components(presentation.rows[0])[0]
    assert button == {
        "type": 2,
        "style": 5,
        "label": "Connect Azents account",
        "url": "https://azents.example/account/external-accounts/connect/discord",
    }
    rendered = str(presentation)
    assert "custom_id" not in rendered
    assert "disconnected" not in rendered.lower()
    assert "optional" not in rendered.lower()


def test_unavailable_provider_omits_dead_connect_control() -> None:
    """Omit the account-link surface while preserving surrounding settings."""
    presentation = discord_account_link_presentation(
        state=ExternalAccountNativeLinkState(
            link=None,
            management_path="/account/external-accounts",
        ),
        provider_status=ExternalAccountOAuthEffectiveStatus.INCOMPLETE,
        web_url="https://azents.example",
    )

    assert presentation.summary is None
    assert presentation.rows == []


def test_linked_presentation_retains_global_management_url() -> None:
    """Keep management available without Workspace ownership copy."""
    presentation = discord_account_link_presentation(
        state=_active_state(),
        provider_status=None,
        web_url="https://azents.example",
    )

    assert presentation.summary == "Azents account: Connected as **Discord User**."
    button = _components(presentation.rows[0])[0]
    assert button == {
        "type": 2,
        "style": 5,
        "label": "Manage connected account",
        "url": "https://azents.example/account/external-accounts",
    }
    assert "Workspace" not in str(presentation)
