"""Provider presentation of value-free Agent Vault request metadata."""

import re
from dataclasses import dataclass
from html import escape

from azents.rdb.models.agent_vault_request import VaultRequestStatus

_TITLE = "Vault request"
_OPEN = "Enter values"
_STATUS = {
    VaultRequestStatus.SUBMITTED: "Input complete",
    VaultRequestStatus.EXPIRED: "Expired",
}
_LINK_SEPARATOR = re.compile(r":(?=//)|(?<=[\w.-])[.。．｡](?=[\w.-])")
_DISCORD_MARKDOWN = re.compile(r"[\\`*_~|[\]#>!+\-]|\.(?=\s)")


@dataclass(frozen=True)
class DiscordVaultRequest:
    """One embed with one URL or disabled status button."""

    embeds: list[dict[str, object]]
    components: list[dict[str, object]]


@dataclass(frozen=True)
class SlackVaultRequest:
    """One Block Kit message and non-interactive fallback."""

    text: str
    blocks: list[dict[str, object]]


def _break_autolinks(value: str) -> str:
    return _LINK_SEPARATOR.sub(r"\g<0>" + "\u200b", value).replace("@", "@\u200b")


def _discord_literal(value: str) -> str:
    # Discord has no plain-text Embed field. Break auto-links and mentions before
    # escaping Markdown; the sole navigation action is the product-owned button.
    return _DISCORD_MARKDOWN.sub(
        r"\\\g<0>", _break_autolinks(value).replace("<", "<\u200b")
    )


def render_discord_vault_request(
    *,
    purpose: str,
    labels: tuple[str, ...],
    status: VaultRequestStatus,
    url: str | None,
) -> DiscordVaultRequest:
    """Preserve the request embed when changing only the action on settlement."""
    if status is VaultRequestStatus.OPEN:
        if url is None:
            raise ValueError("Open Vault request requires its dialog URL.")
        button: dict[str, object] = {
            "type": 2,
            "style": 5,
            "label": _OPEN,
            "url": url,
        }
    else:
        button = {
            "type": 2,
            "style": 2,
            "label": _STATUS[status],
            "disabled": True,
            "custom_id": "azents_vault_request_closed",
        }
    return DiscordVaultRequest(
        embeds=[
            {
                "title": _TITLE,
                "description": _discord_literal(purpose),
                "fields": [
                    {
                        "name": "Requested fields",
                        "value": "\n".join(
                            f"• {_discord_literal(label)}" for label in group
                        ),
                        "inline": False,
                    }
                    for start in range(0, len(labels), 2)
                    if (group := labels[start : start + 2])
                ],
            }
        ],
        components=[{"type": 1, "components": [button]}],
    )


def _slack_plain_text(text: str) -> dict[str, object]:
    return {"type": "plain_text", "text": text}


def render_slack_vault_request(
    *,
    purpose: str,
    labels: tuple[str, ...],
    status: VaultRequestStatus,
    url: str | None,
) -> SlackVaultRequest:
    """Keep authored text literal and replace the action with terminal status."""
    field_lines = tuple(f"• {label}" for label in labels)
    blocks: list[dict[str, object]] = [
        {"type": "header", "text": _slack_plain_text(_TITLE)},
        {"type": "section", "text": _slack_plain_text(purpose)},
    ]
    for start in range(0, len(field_lines), 8):
        section = "\n".join(field_lines[start : start + 8])
        if start == 0:
            section = f"Requested fields\n{section}"
        blocks.append({"type": "section", "text": _slack_plain_text(section)})
    action_or_status = _OPEN if status is VaultRequestStatus.OPEN else _STATUS[status]
    # Slack screen readers use the top-level fallback instead of reading blocks.
    # Escape Slack control characters and omit the dialog URL.
    text = escape(
        _break_autolinks(
            "\n".join(
                (_TITLE, purpose, "Requested fields", *field_lines, action_or_status)
            )
        ),
        quote=False,
    )
    if status is VaultRequestStatus.OPEN:
        if url is None:
            raise ValueError("Open Vault request requires its dialog URL.")
        blocks.append(
            {
                "type": "actions",
                "elements": [
                    {
                        "type": "button",
                        "action_id": "open_azents_vault_request",
                        "text": _slack_plain_text(_OPEN),
                        "url": url,
                    }
                ],
            }
        )
    else:
        blocks.append(
            {"type": "context", "elements": [_slack_plain_text(action_or_status)]}
        )
    return SlackVaultRequest(text=text, blocks=blocks)
