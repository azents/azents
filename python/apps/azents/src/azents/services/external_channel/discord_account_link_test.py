"""Discord-native external account linking presentation tests."""

import datetime

from azents.core.enums import ExternalChannelProvider
from azents.core.external_account_link import (
    ExternalAccountLinkInvalidCode,
    ExternalAccountLinkState,
    ExternalAccountLinkView,
    ExternalAccountNativeLinkState,
    ExternalAccountOriginCreated,
)
from azents.services.external_channel.discord_account_link import (
    discord_account_link_code_modal,
    discord_account_link_error_response,
    discord_account_link_presentation,
    discord_account_link_started_response,
)
from azents.services.external_channel.discord_settings_scope import (
    parse_discord_account_link_custom_id,
)

_NOW = datetime.datetime(2026, 9, 12, tzinfo=datetime.UTC)


def _data(response: dict[str, object]) -> dict[str, object]:
    data = response["data"]
    assert isinstance(data, dict)
    return data


def _rows(data: dict[str, object]) -> list[dict[str, object]]:
    rows = data["components"]
    assert isinstance(rows, list)
    assert all(isinstance(row, dict) for row in rows)
    return rows


def _components(row: dict[str, object]) -> list[dict[str, object]]:
    components = row["components"]
    assert isinstance(components, list)
    assert all(isinstance(component, dict) for component in components)
    return components


def test_unlinked_presentation_is_small_optional_signed_cta() -> None:
    """Keep account linking visible, private, and nonblocking."""
    presentation = discord_account_link_presentation(
        state=ExternalAccountNativeLinkState(
            link=None,
            management_path="/account/external-accounts",
        ),
        origin_interaction_id="interaction-1",
        secret="secret",
        web_url="https://azents.example",
    )

    assert presentation.summary == "Azents account: Not connected (optional)."
    button = _components(presentation.rows[0])[0]
    assert button["label"] == "Connect Azents account · optional"
    custom_id = button["custom_id"]
    assert isinstance(custom_id, str)
    scope = parse_discord_account_link_custom_id(
        custom_id=custom_id,
        secret="secret",
    )
    assert scope.action == "start"
    assert scope.origin_interaction_id == "interaction-1"


def test_linked_presentation_uses_personal_management_url_only() -> None:
    """Render current own state without another public or DM path."""
    link = ExternalAccountLinkView(
        id="link-1",
        workspace_id="workspace-1",
        workspace_name="Workspace One",
        workspace_handle="workspace-one",
        user_id="user-1",
        provider=ExternalChannelProvider.DISCORD,
        identity_scope="global",
        provider_user_id="discord-user-1",
        provider_tenant_display_label="Guild One",
        provider_display_label="Discord User",
        linked_at=_NOW,
        state=ExternalAccountLinkState.ACTIVE,
    )
    presentation = discord_account_link_presentation(
        state=ExternalAccountNativeLinkState(
            link=link,
            management_path="/account/external-accounts",
        ),
        origin_interaction_id="interaction-1",
        secret="secret",
        web_url="https://azents.example/",
    )

    assert "Discord User" in presentation.summary
    button = _components(presentation.rows[0])[0]
    assert button == {
        "type": 2,
        "style": 5,
        "label": "Manage linked account",
        "url": "https://azents.example/account/external-accounts",
    }


def test_inactive_link_reports_recovery_without_replacement_cta() -> None:
    """Keep own management access while membership-dependent authority is inactive."""
    link = ExternalAccountLinkView(
        id="link-1",
        workspace_id="workspace-1",
        workspace_name="Workspace One",
        workspace_handle="workspace-one",
        user_id="user-1",
        provider=ExternalChannelProvider.DISCORD,
        identity_scope="global",
        provider_user_id="discord-user-1",
        provider_tenant_display_label="Guild One",
        provider_display_label="Discord User",
        linked_at=_NOW,
        state=ExternalAccountLinkState.INACTIVE,
    )
    presentation = discord_account_link_presentation(
        state=ExternalAccountNativeLinkState(
            link=link,
            management_path="/account/external-accounts",
        ),
        origin_interaction_id="interaction-1",
        secret="secret",
        web_url="https://azents.example",
    )

    assert "Linked, but inactive" in presentation.summary
    assert "Restore Workspace participation" in presentation.summary
    button = _components(presentation.rows[0])[0]
    assert button["label"] == "Manage linked account"
    assert "Connect Azents account" not in str(presentation.rows)


def test_link_start_then_type_nine_code_modal_keeps_code_out_of_scope() -> None:
    """Use a browser locator followed by one native request-local text input."""
    started = discord_account_link_started_response(
        created=ExternalAccountOriginCreated(
            origin_id="origin-1",
            expires_at=_NOW + datetime.timedelta(minutes=10),
            web_path="/external-channel/link/origin-1",
            management_path="/account/external-accounts",
        ),
        secret="secret",
        web_url="https://azents.example",
    )
    started_data = _data(started)
    assert started["type"] == 7
    buttons = _components(_rows(started_data)[0])
    assert buttons[0]["url"] == "https://azents.example/external-channel/link/origin-1"
    enter_id = buttons[1]["custom_id"]
    assert isinstance(enter_id, str)

    scope = parse_discord_account_link_custom_id(
        custom_id=enter_id,
        secret="secret",
    )
    modal = discord_account_link_code_modal(
        origin_id=scope.origin_id or "",
        secret="secret",
    )
    modal_data = _data(modal)
    assert modal["type"] == 9
    assert modal_data["custom_id"] == enter_id
    input_component = _components(_rows(modal_data)[0])[0]
    assert input_component["custom_id"] == "azents_account_link_code"
    assert input_component["max_length"] == 128
    assert "code" not in repr(scope).lower().replace("enter_code", "")


def test_invalid_code_response_reports_budget_without_echoing_code() -> None:
    """Provide private recovery while leaving raw code outside presentation state."""
    response = discord_account_link_error_response(
        ExternalAccountLinkInvalidCode(remaining_attempts=3)
    )

    data = _data(response)
    assert response["type"] == 7
    assert "3 attempts remain" in str(data["content"])
    assert data["components"] == []
