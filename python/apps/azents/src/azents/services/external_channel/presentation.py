"""Current Agent attribution for Slack delivery attempts."""

from dataclasses import dataclass
from urllib.parse import quote, urlsplit

from pydantic import ValidationError

from azents.core.enums import ExternalChannelAppMode
from azents.repos.external_channel.work_data import ChannelDeliveryTarget
from azents.services.external_channel.data import ExternalChannelCapabilitySnapshot
from azents.services.uploads.schema import StoredImage

_MAX_AGENT_NAME_LENGTH = 80


@dataclass(frozen=True)
class SlackAgentPresentation:
    """Bounded current Agent attribution for one provider attempt."""

    name: str
    markdown_line: str
    icon_url: str | None
    show_name: bool = True


def resolve_slack_agent_presentation(
    target: ChannelDeliveryTarget | None,
    *,
    avatar_cdn_base_url: str | None,
) -> SlackAgentPresentation | None:
    """Resolve current Agent name and optional public icon from a live target."""
    if target is None or target.agent_name is None:
        return None
    presentation = resolve_slack_agent_name_presentation(target.agent_name)
    assert presentation is not None
    return SlackAgentPresentation(
        name=presentation.name,
        markdown_line=presentation.markdown_line,
        icon_url=_agent_icon_url(
            capabilities=target.capabilities,
            avatar=target.agent_avatar,
            avatar_cdn_base_url=avatar_cdn_base_url,
        ),
        show_name=target.app_mode is ExternalChannelAppMode.MULTI,
    )


def resolve_slack_agent_name_presentation(
    agent_name: str | None,
) -> SlackAgentPresentation | None:
    """Resolve a bounded name-only presentation for retained historical notices."""
    name = normalize_slack_agent_name(agent_name)
    if name is None:
        return None
    return SlackAgentPresentation(
        name=name,
        markdown_line=f"*{_escape_slack_markdown(name)}*",
        icon_url=None,
    )


def normalize_slack_agent_name(agent_name: str | None) -> str | None:
    """Normalize one Agent name before persisting or rendering attribution."""
    if agent_name is None:
        return None
    name = " ".join(agent_name.split())[:_MAX_AGENT_NAME_LENGTH]
    return name or "Agent"


def prepend_agent_markdown(
    presentation: SlackAgentPresentation | None,
    text: str,
) -> str:
    """Prepend the visible bold Agent line to one Markdown message."""
    if presentation is None or not presentation.show_name:
        return text
    return f"{presentation.markdown_line}\n{text}"


def prepend_agent_fallback(
    presentation: SlackAgentPresentation | None,
    text: str,
) -> str:
    """Prepend the current Agent name to one top-level fallback string."""
    if presentation is None or not presentation.show_name:
        return text
    return f"{presentation.name}\n{text}"


def prepend_agent_blocks(
    presentation: SlackAgentPresentation | None,
    blocks: list[dict[str, object]],
) -> list[dict[str, object]]:
    """Prepend one minimal Agent-name section without replacing native blocks."""
    if presentation is None or not presentation.show_name:
        return blocks
    return [
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": presentation.markdown_line,
            },
        },
        *blocks,
    ]


def _agent_icon_url(
    *,
    capabilities: dict[str, object] | None,
    avatar: dict[str, object] | None,
    avatar_cdn_base_url: str | None,
) -> str | None:
    if capabilities is None or avatar is None or avatar_cdn_base_url is None:
        return None
    stored_capabilities = dict(capabilities)
    if stored_capabilities.get("customize_messages") is not True:
        return None
    stored_capabilities.setdefault("download_files", False)
    stored_capabilities.setdefault("upload_files", False)
    try:
        ExternalChannelCapabilitySnapshot.model_validate(stored_capabilities)
        stored_avatar = StoredImage.model_validate(avatar)
    except ValidationError:
        return None
    parsed_base = urlsplit(avatar_cdn_base_url)
    if (
        parsed_base.scheme != "https"
        or parsed_base.hostname is None
        or parsed_base.username is not None
        or parsed_base.password is not None
        or parsed_base.query
        or parsed_base.fragment
    ):
        return None
    image = stored_avatar.thumbnails.medium or stored_avatar.default
    key = image.key.lstrip("/")
    if not key:
        return None
    return f"{avatar_cdn_base_url.rstrip('/')}/{quote(key, safe='/')}"


def _escape_slack_markdown(value: str) -> str:
    return value.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
