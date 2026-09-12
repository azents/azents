"""Discord-native presentation for optional external account linking."""

from dataclasses import dataclass

from azents.core.external_account_link import (
    ExternalAccountLinkActorMismatch,
    ExternalAccountLinkAttemptLimitReached,
    ExternalAccountLinkBusy,
    ExternalAccountLinkConflict,
    ExternalAccountLinkError,
    ExternalAccountLinkExpired,
    ExternalAccountLinkInvalidCode,
    ExternalAccountLinkNotFound,
    ExternalAccountLinkState,
    ExternalAccountLinkUnavailable,
    ExternalAccountNativeLinkState,
    ExternalAccountOriginCreated,
    ExternalAccountProviderProofResult,
)
from azents.services.external_channel.discord_settings_scope import (
    build_discord_account_link_custom_id,
)

_DISCORD_ACCOUNT_LINK_CODE_COMPONENT_ID = "azents_account_link_code"


@dataclass(frozen=True)
class DiscordAccountLinkPresentation:
    """Private account state summary and provider-native controls."""

    summary: str
    rows: list[dict[str, object]]


def discord_account_link_presentation(
    *,
    state: ExternalAccountNativeLinkState,
    origin_interaction_id: str,
    secret: str,
    web_url: str,
) -> DiscordAccountLinkPresentation:
    """Render a quiet persistent CTA or current personal management access."""
    if state.link is None:
        return DiscordAccountLinkPresentation(
            summary="Azents account: Not connected (optional).",
            rows=[
                _button_row(
                    {
                        "type": 2,
                        "style": 2,
                        "label": "Connect Azents account · optional",
                        "custom_id": build_discord_account_link_custom_id(
                            secret=secret,
                            action="start",
                            origin_interaction_id=origin_interaction_id,
                            origin_id=None,
                        ),
                    }
                )
            ],
        )
    link = state.link
    if link.state is ExternalAccountLinkState.ACTIVE:
        summary = (
            "Azents account: Connected as "
            f"**{_discord_text(link.provider_display_label, 80)}** "
            f"in **{_discord_text(link.workspace_name, 80)}**."
        )
    elif link.state is ExternalAccountLinkState.INACTIVE:
        summary = (
            "Azents account: Linked, but inactive for "
            f"**{_discord_text(link.workspace_name, 80)}**. "
            "Restore Workspace participation to use link-dependent settings."
        )
    else:
        summary = (
            "Azents account: Disconnected for "
            f"**{_discord_text(link.workspace_name, 80)}**."
        )
    return DiscordAccountLinkPresentation(
        summary=summary,
        rows=[
            _button_row(
                {
                    "type": 2,
                    "style": 5,
                    "label": "Manage linked account",
                    "url": _web_url(web_url=web_url, path=state.management_path),
                }
            )
        ],
    )


def discord_account_link_started_response(
    *,
    created: ExternalAccountOriginCreated,
    secret: str,
    web_url: str,
) -> dict[str, object]:
    """Render the browser rendezvous and explicit code-entry control."""
    description = (
        "Open Azents and confirm your own account and Workspace. "
        "Then return here and enter only the code shown on your own "
        "confirmation screen."
    )
    return _ephemeral_update(
        title="Connect Azents account",
        description=description,
        color=0x5865F2,
        rows=[
            _button_row(
                {
                    "type": 2,
                    "style": 5,
                    "label": "Open Azents",
                    "url": _web_url(web_url=web_url, path=created.web_path),
                },
                {
                    "type": 2,
                    "style": 1,
                    "label": "Enter browser code",
                    "custom_id": build_discord_account_link_custom_id(
                        secret=secret,
                        action="enter_code",
                        origin_interaction_id=None,
                        origin_id=created.origin_id,
                    ),
                },
            )
        ],
    )


def discord_account_link_code_modal(
    *,
    origin_id: str,
    secret: str,
) -> dict[str, object]:
    """Open the native type-9 modal for one request-local browser code."""
    return {
        "type": 9,
        "data": {
            "custom_id": build_discord_account_link_custom_id(
                secret=secret,
                action="enter_code",
                origin_interaction_id=None,
                origin_id=origin_id,
            ),
            "title": "Enter Azents code",
            "components": [
                {
                    "type": 1,
                    "components": [
                        {
                            "type": 4,
                            "custom_id": _DISCORD_ACCOUNT_LINK_CODE_COMPONENT_ID,
                            "label": "Browser code",
                            "style": 1,
                            "min_length": 1,
                            "max_length": 128,
                            "required": True,
                            "placeholder": "Code from your Azents confirmation screen",
                        }
                    ],
                }
            ],
        },
    }


def discord_account_link_verified_response(
    *,
    result: ExternalAccountProviderProofResult,
    origin_id: str,
    web_url: str,
) -> dict[str, object]:
    """Confirm provider proof without claiming the browser finalized the link."""
    del result
    description = (
        "Code verified for this Discord account. "
        "Return to Azents and choose Connect to finish linking."
    )
    return _ephemeral_update(
        title="Discord account verified",
        description=description,
        color=0x57F287,
        rows=[
            _button_row(
                {
                    "type": 2,
                    "style": 5,
                    "label": "Return to Azents",
                    "url": _web_url(
                        web_url=web_url,
                        path=f"/external-channel/link/{origin_id}",
                    ),
                }
            )
        ],
    )


def discord_account_link_error_response(
    error: ExternalAccountLinkError,
) -> dict[str, object]:
    """Map typed link failures to private nondisclosing recovery guidance."""
    if isinstance(error, ExternalAccountLinkInvalidCode):
        description = (
            "That code did not match an eligible confirmation. "
            f"{error.remaining_attempts} attempt"
            f"{'' if error.remaining_attempts == 1 else 's'} remain."
        )
    elif isinstance(error, ExternalAccountLinkAttemptLimitReached):
        description = (
            "This linking attempt has no code attempts remaining. "
            "Reopen settings and start again."
        )
    elif isinstance(error, ExternalAccountLinkExpired):
        description = "This linking attempt expired. Reopen settings and start again."
    elif isinstance(error, ExternalAccountLinkConflict):
        description = (
            "This account cannot be linked with the current confirmation. "
            "Review your account in Azents or start a fresh linking attempt."
        )
    elif isinstance(
        error,
        (
            ExternalAccountLinkActorMismatch,
            ExternalAccountLinkNotFound,
            ExternalAccountLinkUnavailable,
        ),
    ):
        description = (
            "This linking control is unavailable. Reopen settings and start again."
        )
    elif isinstance(error, ExternalAccountLinkBusy):
        description = "Azents is busy. Reopen settings and try again."
    else:
        raise AssertionError("Discord account-link failure is not exhaustive.")
    return _ephemeral_update(
        title="Account linking unavailable",
        description=description,
        color=0x99AAB5,
        rows=[],
    )


def discord_account_link_state_unavailable() -> DiscordAccountLinkPresentation:
    """Render a private fail-closed state without exposing another fallback."""
    return DiscordAccountLinkPresentation(
        summary="Azents account linking is temporarily unavailable.",
        rows=[],
    )


def _ephemeral_update(
    *,
    title: str,
    description: str,
    color: int,
    rows: list[dict[str, object]],
) -> dict[str, object]:
    return {
        "type": 7,
        "data": {
            "content": description,
            "embeds": [
                {
                    "title": title,
                    "description": description,
                    "color": color,
                }
            ],
            "components": rows,
            "allowed_mentions": {"parse": []},
        },
    }


def _button_row(*buttons: dict[str, object]) -> dict[str, object]:
    return {"type": 1, "components": list(buttons)}


def _web_url(*, web_url: str, path: str) -> str:
    return f"{web_url.rstrip('/')}/{path.lstrip('/')}"


def _discord_text(value: str, limit: int) -> str:
    escaped = value.replace("\\", "\\\\")
    for character in ("*", "_", "`", "~", "|", ">", "#"):
        escaped = escaped.replace(character, f"\\{character}")
    return escaped[:limit]
