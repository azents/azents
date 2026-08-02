"""Provider-neutral External Channel Session presence controls."""

from typing import Literal, assert_never
from urllib.parse import quote, urlparse, urlunparse

ExternalChannelSessionPresenceState = Literal["joined", "left"]


def build_external_channel_session_url(
    web_url: str,
    workspace_handle: str,
    agent_id: str,
    session_id: str,
) -> str | None:
    """Build the canonical Azents Web route for one Agent Session."""
    parsed = urlparse(web_url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return None
    path = (
        f"/w/{quote(workspace_handle, safe='')}/agents/{quote(agent_id, safe='')}"
        f"/sessions/{quote(session_id, safe='')}"
    )
    return urlunparse(parsed._replace(path=path, query="", fragment=""))


def session_presence_payload(
    labels: dict[str, object] | None,
    *,
    state: ExternalChannelSessionPresenceState,
) -> dict[str, object]:
    """Build one durable provider target for a Session presence control."""
    labels = labels or {}
    payload: dict[str, object] = {
        "control_kind": "session_presence",
        "presence_state": state,
    }
    provider = labels.get("provider")
    if provider == "slack":
        payload.update(
            {
                "tenant_id": labels.get("tenant_id"),
                "channel_id": labels.get("channel_id"),
            }
        )
        conversation_scope = labels.get("conversation_scope")
        if isinstance(conversation_scope, str) and conversation_scope:
            payload["conversation_scope"] = conversation_scope
        thread_ts = labels.get("thread_ts")
        if isinstance(thread_ts, str) and thread_ts:
            payload["thread_ts"] = thread_ts
        return payload
    if provider == "discord":
        delivery_channel_id = labels.get("delivery_channel_id")
        thread_id = (
            delivery_channel_id
            if isinstance(delivery_channel_id, str) and delivery_channel_id
            else labels.get("thread_id")
        )
        payload.update(
            {
                "guild_id": labels.get("guild_id"),
                "channel_id": thread_id,
            }
        )
        parent_channel_id = labels.get("parent_channel_id")
        root_message_id = labels.get("root_message_id")
        if (
            delivery_channel_id is None
            and isinstance(parent_channel_id, str)
            and parent_channel_id
            and isinstance(root_message_id, str)
            and root_message_id == thread_id
        ):
            payload["thread_parent_channel_id"] = parent_channel_id
            payload["thread_root_message_id"] = root_message_id
        return payload
    return payload


def session_presence_sentence(
    agent_name: str,
    state: ExternalChannelSessionPresenceState,
) -> str:
    """Render the approved Session presence sentence."""
    match state:
        case "joined":
            return f"{agent_name} joined this conversation."
        case "left":
            return f"{agent_name} left this conversation."
        case _ as unreachable:
            assert_never(unreachable)
