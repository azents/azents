"""Discord-native presentation for provider account connection."""

from dataclasses import dataclass

from azents.core.external_account_link import (
    ExternalAccountLinkState,
    ExternalAccountNativeLinkState,
)
from azents.services.external_account_oauth_system_setting.data import (
    ExternalAccountOAuthEffectiveStatus,
)

_DISCORD_CONNECT_PATH = "/account/external-accounts/connect/discord"


@dataclass(frozen=True)
class DiscordAccountLinkPresentation:
    """Private account state summary and provider-native controls."""

    summary: str
    rows: list[dict[str, object]]


def discord_account_link_presentation(
    *,
    state: ExternalAccountNativeLinkState,
    provider_status: ExternalAccountOAuthEffectiveStatus | None,
    web_url: str,
) -> DiscordAccountLinkPresentation:
    """Render one direct Web connection or current management control."""
    if state.link is None:
        if provider_status is not ExternalAccountOAuthEffectiveStatus.READY:
            return discord_account_link_state_unavailable()
        return DiscordAccountLinkPresentation(
            summary=(
                "Use your Azents account for authorized conversation model settings."
            ),
            rows=[
                _button_row(
                    {
                        "type": 2,
                        "style": 5,
                        "label": "Connect Azents account",
                        "url": _web_url(
                            web_url=web_url,
                            path=_DISCORD_CONNECT_PATH,
                        ),
                    }
                )
            ],
        )
    link = state.link
    summary = (
        "Azents account: Connected as "
        f"**{_discord_text(link.provider_display_label, 80)}**."
        if link.state is ExternalAccountLinkState.ACTIVE
        else "Azents account connection needs attention."
    )
    return DiscordAccountLinkPresentation(
        summary=summary,
        rows=[
            _button_row(
                {
                    "type": 2,
                    "style": 5,
                    "label": "Manage connected account",
                    "url": _web_url(web_url=web_url, path=state.management_path),
                }
            )
        ],
    )


def discord_account_link_state_unavailable() -> DiscordAccountLinkPresentation:
    """Render one quiet provider-specific unavailable line without a dead link."""
    return DiscordAccountLinkPresentation(
        summary="Discord account connection is currently unavailable.",
        rows=[],
    )


def _button_row(*buttons: dict[str, object]) -> dict[str, object]:
    return {"type": 1, "components": list(buttons)}


def _web_url(*, web_url: str, path: str) -> str:
    return f"{web_url.rstrip('/')}/{path.lstrip('/')}"


def _discord_text(value: str | None, limit: int) -> str:
    escaped = (value or "provider account").replace("\\", "\\\\")
    for character in ("*", "_", "`", "~", "|", ">", "#"):
        escaped = escaped.replace(character, f"\\{character}")
    return escaped[:limit]
