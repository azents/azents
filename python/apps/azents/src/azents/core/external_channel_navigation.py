"""Independent semantic navigation actions and provider presentation."""

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Literal
from urllib.parse import unquote, urlsplit

from pydantic import BaseModel, ConfigDict, Field, model_validator


class ChannelNavigationAction(BaseModel):
    """Describe a product destination without a tool-call/result dependency."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    type: Literal["browser", "web_service"]
    label: str | None = Field(default=None, min_length=1, max_length=75)
    service_id: str | None = Field(
        default=None,
        min_length=32,
        max_length=32,
        description="Known service ID for web_service; null for browser.",
    )
    path: str | None = Field(
        default=None,
        min_length=1,
        max_length=2048,
        description=(
            "Service-relative absolute path, including optional query/fragment. "
            "Defaults to /. Null for browser."
        ),
    )

    @model_validator(mode="after")
    def validate_destination(self) -> "ChannelNavigationAction":
        """Keep cross-field semantics out of provider JSON Schema dialects."""
        if self.label is not None and not self.label.strip():
            raise ValueError("Action label must not be blank.")
        if self.type == "browser":
            if self.service_id is not None or self.path is not None:
                raise ValueError(
                    "Browser actions use the current Session, "
                    "without service_id or path."
                )
        else:
            if self.service_id is None:
                raise ValueError("Web service actions require service_id.")
            validate_service_path(self.path or "/")
        return self


def validate_service_path(path: str) -> str:
    """Accept navigation within one service, never a new origin or authority."""
    decoded = path
    for _ in range(4):
        if (
            not decoded.startswith("/")
            or decoded.startswith("//")
            or "\\" in decoded
            or any(ord(char) < 32 or ord(char) == 127 for char in decoded)
        ):
            raise ValueError("Action path must stay within the selected web service.")
        parsed = urlsplit(decoded)
        if parsed.scheme or parsed.netloc:
            raise ValueError("Action path must not contain an origin.")
        next_value = unquote(decoded)
        if next_value == decoded:
            return path
        decoded = next_value
    raise ValueError("Action path contains excessive URL encoding.")


@dataclass(frozen=True)
class ChannelNavigationContext:
    """Authorized current publication scope and detached service locators."""

    workspace_handle: str
    service_hosts: dict[str, str]


@dataclass(frozen=True)
class ChannelNavigationLink:
    """Resolved process-local navigation presentation, without an access grant."""

    label: str
    url: str


def slack_navigation_block(links: Sequence[ChannelNavigationLink]) -> dict[str, object]:
    """Render native Slack URL controls with readable plain-text labels."""
    return {
        "type": "actions",
        "elements": [
            {
                "type": "button",
                "text": {"type": "plain_text", "text": link.label},
                "url": link.url,
                "action_id": f"azents_navigation_{index}",
            }
            for index, link in enumerate(links)
        ],
    }


def discord_navigation_rows(
    links: Sequence[ChannelNavigationLink],
) -> list[dict[str, object]]:
    """Render Discord link buttons without interaction or execution callbacks."""
    return [
        {
            "type": 1,
            "components": [
                {"type": 2, "style": 5, "label": link.label, "url": link.url}
                for link in links
            ],
        }
    ]
