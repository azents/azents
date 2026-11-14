"""Typed operation results for the injected deterministic Discord fixture."""

from dataclasses import dataclass
from typing import Annotated, Self

from pydantic import BaseModel, ConfigDict, Field, RootModel, StrictInt, field_validator

from azents.core.external_channel_projection import (
    is_external_channel_projection,
    is_external_channel_projection_list,
)
from azents.services.external_channel.discord_sdk import DiscordSDKUnavailable

FixtureString = Annotated[str, Field(strict=True, min_length=1)]


class FixtureResult(BaseModel):
    """Consumed fields are strict; provider-compatible extensions are ignored."""

    model_config = ConfigDict(extra="ignore", hide_input_in_errors=True)


class LoginResult(FixtureResult):
    bot_user_id: FixtureString


class ApplicationResult(FixtureResult):
    application_id: FixtureString
    verify_key: FixtureString


class CommandResult(FixtureResult):
    id: FixtureString
    name: FixtureString
    type: StrictInt
    description: str | None = None

    @field_validator("description", mode="before")
    @classmethod
    def optional_text(cls, value: object) -> str | None:
        return value if isinstance(value, str) else None


class CommandsResult(FixtureResult):
    commands: list[CommandResult]


class ThreadResult(FixtureResult):
    id: FixtureString
    parent_id: FixtureString
    guild_id: FixtureString
    name: FixtureString


class ThreadLookupResult(FixtureResult):
    thread: ThreadResult | None = None


class MessageResult(FixtureResult):
    id: FixtureString
    channel_id: FixtureString
    guild_id: FixtureString


class AttachmentResult(FixtureResult):
    attachment_id: FixtureString
    filename: FixtureString
    size: Annotated[StrictInt, Field(ge=0)]
    content_type: str | None = None
    download_url: FixtureString

    @field_validator("content_type", mode="before")
    @classmethod
    def optional_text(cls, value: object) -> str | None:
        return value if isinstance(value, str) else None


class HistoryResult(FixtureResult):
    """Message bodies remain opaque until the existing message projector."""

    messages: list[dict[str, object]]


class ProjectionResult(RootModel[dict[str, object]]):
    """Opaque message forwarded directly to its existing canonical decoder."""


@dataclass(frozen=True)
class GatewayGuild:
    channels: dict[str, str]
    managed_roles: dict[str, str]

    @classmethod
    def decode(cls, raw: dict[str, object]) -> Self:
        """Preserve permissive optional guild metadata and ignore unknown rows."""
        channels: dict[str, str] = {}
        roles: dict[str, str] = {}
        raw_channels = raw.get("channels")
        for item in raw_channels if isinstance(raw_channels, list) else ():
            if not is_external_channel_projection(item):
                continue
            identity, name = item.get("id"), item.get("name")
            if isinstance(identity, str) and isinstance(name, str):
                channels[identity] = name
        raw_roles = raw.get("roles")
        for item in raw_roles if isinstance(raw_roles, list) else ():
            if not is_external_channel_projection(item):
                continue
            identity, tags = item.get("id"), item.get("tags")
            if not isinstance(identity, str) or not is_external_channel_projection(
                tags
            ):
                continue
            bot = tags.get("bot_id")
            if isinstance(bot, str):
                roles[identity] = bot
        return cls(channels=channels, managed_roles=roles)


@dataclass(frozen=True)
class GatewayMessage:
    """Typed envelope fields; full message belongs to the canonical projector."""

    raw: dict[str, object]
    channel_id: str
    mention_roles: tuple[str, ...]

    @classmethod
    def decode(cls, raw: dict[str, object]) -> Self:
        channel = required_string(raw, "channel_id")
        mentions = raw.get("mention_roles")
        return cls(
            raw=raw,
            channel_id=channel,
            mention_roles=tuple(value for value in mentions if isinstance(value, str))
            if isinstance(mentions, list)
            else (),
        )


@dataclass(frozen=True)
class GatewayIgnoredDispatch:
    """An extension event with no consumed payload fields."""

    event_type: str


type GatewayDispatch = GatewayGuild | GatewayMessage | GatewayIgnoredDispatch


@dataclass(frozen=True)
class GatewayAttempt:
    scenario: str
    dispatches: tuple[GatewayDispatch, ...]

    @classmethod
    def decode(cls, value: object) -> Self:
        """Decode known dispatch kinds once without tightening reconnect bodies."""
        if not is_external_channel_projection(value):
            raise ValueError("Discord Gateway fixture response is invalid.")
        scenario = required_string(value, "scenario")
        if scenario != "open":
            return cls(scenario=scenario, dispatches=())
        raw_dispatches = value.get("dispatches")
        if not is_external_channel_projection_list(raw_dispatches):
            raise DiscordSDKUnavailable(
                "Discord Gateway fixture dispatches are invalid."
            )
        dispatches: list[GatewayDispatch] = []
        for dispatch in raw_dispatches:
            kind = required_string(dispatch, "event_type")
            payload = dispatch.get("payload")
            if not is_external_channel_projection(payload):
                raise DiscordSDKUnavailable(
                    "Discord Gateway fixture payload is invalid."
                )
            match kind:
                case "GUILD_CREATE":
                    dispatches.append(GatewayGuild.decode(payload))
                case "MESSAGE_CREATE":
                    dispatches.append(GatewayMessage.decode(payload))
                case _:
                    dispatches.append(GatewayIgnoredDispatch(event_type=kind))
        return cls(scenario=scenario, dispatches=tuple(dispatches))


def required_string(payload: dict[str, object], key: str) -> str:
    """Validate a required fixture identity without exposing its value."""
    value = payload.get(key)
    if not isinstance(value, str) or not value:
        raise DiscordSDKUnavailable(f"Discord SDK fixture field '{key}' is invalid.")
    return value
