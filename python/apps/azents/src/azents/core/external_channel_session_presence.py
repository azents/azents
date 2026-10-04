"""Provider-neutral External Channel Session presence controls."""

from typing import Literal, assert_never
from urllib.parse import quote, urlencode, urlparse, urlunparse

from azents.core.external_channel_labels import (
    ExternalChannelResourceLabels,
    decode_external_channel_resource_labels,
)

ExternalChannelSessionPresenceState = Literal["joined", "left"]


def build_external_channel_session_url(
    web_url: str | None,
    workspace_handle: str,
    agent_id: str,
    session_id: str,
) -> str | None:
    """Build the canonical Azents Web route for one Agent Session."""
    if web_url is None:
        return None
    parsed = urlparse(web_url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return None
    path = (
        f"/w/{quote(workspace_handle, safe='')}/agents/{quote(agent_id, safe='')}"
        f"/sessions/{quote(session_id, safe='')}"
    )
    return urlunparse(parsed._replace(path=path, query="", fragment=""))


def build_external_channel_scheduled_task_url(
    web_url: str | None,
    workspace_handle: str,
    agent_id: str,
    session_id: str,
    task_id: str,
) -> str | None:
    """Build the exact Web edit route for one Session-owned Scheduled Task."""
    session_url = build_external_channel_session_url(
        web_url,
        workspace_handle,
        agent_id,
        session_id,
    )
    if session_url is None:
        return None
    parsed = urlparse(session_url)
    query = urlencode(
        {
            "page": "scheduled-tasks",
            "taskId": task_id,
            "edit": "1",
        }
    )
    return urlunparse(parsed._replace(query=query))


def session_presence_payload(
    labels: dict[str, object] | None,
    *,
    state: ExternalChannelSessionPresenceState,
) -> dict[str, object]:
    """Build one durable provider target for a Session presence control."""
    return _session_presence_from_labels(
        decode_external_channel_resource_labels(labels), state=state
    )


def _session_presence_from_labels(
    labels: ExternalChannelResourceLabels,
    *,
    state: ExternalChannelSessionPresenceState,
) -> dict[str, object]:
    """Serialize a provider target from validated label decisions."""
    payload: dict[str, object] = {
        "control_kind": "session_presence",
        "control_version": 2,
        "presence_state": state,
    }
    if labels.provider == "slack":
        payload.update(
            {
                "tenant_id": labels.tenant_coordinate,
                "channel_id": labels.channel_coordinate,
            }
        )
        if labels.conversation_scope is not None:
            payload["conversation_scope"] = labels.conversation_scope
        if labels.thread_ts is not None:
            payload["thread_ts"] = labels.thread_ts
        return payload
    if labels.provider == "discord":
        if labels.conversation_scope == "parent_channel":
            payload.update(
                {
                    "guild_id": labels.guild_coordinate,
                    "channel_id": labels.parent_coordinate,
                    "conversation_scope": "parent_channel",
                }
            )
            return payload
        thread_id = labels.delivery_channel_id or labels.thread_coordinate
        payload.update(
            {
                "guild_id": labels.guild_coordinate,
                "channel_id": thread_id,
                "conversation_scope": "thread",
            }
        )
        if (
            labels.delivery_channel_absent
            and labels.parent_channel_id is not None
            and labels.root_message_id is not None
            and labels.root_message_id == labels.thread_id
        ):
            payload["thread_parent_channel_id"] = labels.parent_channel_id
            payload["thread_root_message_id"] = labels.root_message_id
        return payload
    return payload


def setup_required_payload(
    labels: dict[str, object] | None,
    *,
    setup_claim_id: str,
    claim_generation: int,
    source_revision: int,
) -> dict[str, object]:
    """Build one durable provider target for a first-mention setup choice."""
    decoded = decode_external_channel_resource_labels(labels)
    if decoded.provider == "discord":
        parent_channel_id = decoded.parent_channel_id or decoded.source_coordinate
        payload: dict[str, object] = {
            "control_kind": "setup_required",
            "control_version": 2,
            "guild_id": decoded.guild_coordinate,
            "channel_id": parent_channel_id,
            "conversation_scope": "parent_channel",
        }
    else:
        payload = _session_presence_from_labels(decoded, state="joined")
        payload.pop("presence_state")
    payload.update(
        {
            "control_kind": "setup_required",
            "setup_claim_id": setup_claim_id,
            "claim_generation": claim_generation,
            "source_revision": source_revision,
        }
    )
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
