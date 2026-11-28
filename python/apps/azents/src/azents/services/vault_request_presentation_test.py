"""Render authored Vault metadata and a single distinct provider action."""

import json
from html import unescape

import pytest

from azents.core.vault_request import VaultRequestField, VaultRequestSpec
from azents.rdb.models.agent_vault_request import VaultRequestStatus
from azents.services.vault_request_presentation import (
    render_discord_vault_request,
    render_slack_vault_request,
)

_URL = "https://azents.example.test/w/example?vaultRequest=test"
_PURPOSE = "Connect the reporting account."
_LABELS = ("Account", "API token")


@pytest.mark.parametrize(
    ("status", "label"),
    [
        (VaultRequestStatus.SUBMITTED, "Input complete"),
        (VaultRequestStatus.EXPIRED, "Expired"),
    ],
)
def test_discord_preserves_embed_and_replaces_link_button(
    status: VaultRequestStatus, label: str
) -> None:
    opened = render_discord_vault_request(
        purpose=_PURPOSE, labels=_LABELS, status=VaultRequestStatus.OPEN, url=_URL
    )
    closed = render_discord_vault_request(
        purpose=_PURPOSE, labels=_LABELS, status=status, url=_URL
    )
    assert opened.embeds == closed.embeds
    assert opened.embeds[0]["description"] == _PURPOSE
    assert opened.embeds[0]["fields"] == [
        {"name": "Requested fields", "value": "• Account\n• API token", "inline": False}
    ]
    assert opened.components == [
        {
            "type": 1,
            "components": [
                {"type": 2, "style": 5, "label": "Enter values", "url": _URL}
            ],
        }
    ]
    assert closed.components == [
        {
            "type": 1,
            "components": [
                {
                    "type": 2,
                    "style": 2,
                    "label": label,
                    "disabled": True,
                    "custom_id": "azents_vault_request_closed",
                }
            ],
        }
    ]
    assert _URL not in json.dumps(closed.components)


@pytest.mark.parametrize(
    ("status", "label"),
    [
        (VaultRequestStatus.SUBMITTED, "Input complete"),
        (VaultRequestStatus.EXPIRED, "Expired"),
    ],
)
def test_slack_preserves_blocks_and_replaces_button_with_status(
    status: VaultRequestStatus, label: str
) -> None:
    purpose = "<!everyone> *literal* <https://example.test|not a link>"
    opened = render_slack_vault_request(
        purpose=purpose, labels=_LABELS, status=VaultRequestStatus.OPEN, url=_URL
    )
    closed = render_slack_vault_request(
        purpose=purpose, labels=_LABELS, status=status, url=_URL
    )
    assert opened.blocks[:-1] == closed.blocks[:-1]
    assert opened.blocks[1]["text"] == {"type": "plain_text", "text": purpose}
    assert opened.blocks[-1] == {
        "type": "actions",
        "elements": [
            {
                "type": "button",
                "action_id": "open_azents_vault_request",
                "text": {"type": "plain_text", "text": "Enter values"},
                "url": _URL,
            }
        ],
    }
    assert closed.blocks[-1] == {
        "type": "context",
        "elements": [{"type": "plain_text", "text": label}],
    }
    assert opened.text.splitlines()[-4:] == [
        "Requested fields",
        "• Account",
        "• API token",
        "Enter values",
    ]
    assert closed.text.splitlines()[-1] == label
    assert "<!everyone>" not in closed.text
    assert "https://" not in closed.text
    assert _URL not in json.dumps(closed.blocks)


def test_discord_escapes_each_markup_token_and_breaks_auto_links() -> None:
    rendered = render_discord_vault_request(
        purpose=(
            "1. [a](https://example.test) **important** [b](https://127.0.0.1) "
            "@everyone <@123> 국제화.테스트"
        ),
        labels=(r"\**<first>**",),
        status=VaultRequestStatus.OPEN,
        url=_URL,
    )
    description = rendered.embeds[0]["description"]
    assert isinstance(description, str)
    assert description.startswith(r"1\. \[a\]")
    assert r"\*\*important\*\* \[b\]" in description
    assert "https://" not in description
    assert "@everyone" not in description
    assert "<@123>" not in description
    assert "국제화.\u200b테스트" in description
    assert rendered.embeds[0]["fields"] == [
        {
            "name": "Requested fields",
            "value": "• " + r"\\\*\*" + "<\u200bfirst" + r"\>\*\*",
            "inline": False,
        }
    ]


def _utf16_length(value: str) -> int:
    return len(value.encode("utf-16-le")) // 2


@pytest.mark.parametrize("unit", ["🧪", "\\", "<", "&"])
def test_provider_limits_preserve_maximum_unicode_metadata(unit: str) -> None:
    spec = VaultRequestSpec(
        purpose=unit * 500,
        fields=tuple(
            VaultRequestField(name=f"field-{index}", label=f"{index:02}{unit * 118}")
            for index in range(16)
        ),
    )
    labels = tuple(field.label for field in spec.fields)
    discord = render_discord_vault_request(
        purpose=spec.purpose, labels=labels, status=VaultRequestStatus.OPEN, url=_URL
    )
    embed = discord.embeds[0]
    description, title, fields = embed["description"], embed["title"], embed["fields"]
    assert isinstance(description, str) and _utf16_length(description) <= 4096
    assert isinstance(title, str) and isinstance(fields, list) and len(fields) <= 25
    total = _utf16_length(description) + _utf16_length(title)
    displayed_indices = []
    for field in fields:
        value = field["value"]
        assert _utf16_length(value) <= 1024
        total += _utf16_length(value) + _utf16_length(field["name"])
        displayed_indices.extend(line[2:4] for line in value.splitlines())
    assert total <= 6000
    assert displayed_indices == [label[:2] for label in labels]
    slack = render_slack_vault_request(
        purpose=spec.purpose, labels=labels, status=VaultRequestStatus.OPEN, url=_URL
    )
    for block in slack.blocks:
        if block["type"] == "section":
            text = block["text"]
            assert isinstance(text, dict) and _utf16_length(text["text"]) <= 3000
    assert len(slack.text) <= 40_000
    assert unescape(slack.text).splitlines()[3:-1] == [f"• {label}" for label in labels]
