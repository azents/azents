"""Provider-tool live activity product-path E2E coverage."""

import json
import time
from collections.abc import Callable

import azentsadminclient
import azentspublicclient
import requests
from websockets.sync.connection import Connection

from support.utils import unique
from tests.azents.public.test_agent_execution_persistence import (
    auth_headers,
    connect_chat,
    history_events,
    json_object_list_payload,
    json_object_payload,
    list_history,
    list_live,
)
from tests.azents.public.test_per_prompt_inference_profile import (
    setup_profile_agent,
)

_PROMPT = "Provider tool live activity handoff"
_RESPONSE = "PROVIDER_TOOL_LIVE_ACTIVITY_COMPLETED"


def _provider_call_event(
    events: list[dict[str, object]],
    *,
    status: str,
) -> dict[str, object] | None:
    """Return the provider-tool call with the requested canonical status."""
    for event in events:
        if event.get("kind") != "provider_tool_call":
            continue
        payload = json_object_payload(
            event.get("payload"),
            label="provider-tool payload",
        )
        if payload.get("name") == "web_search" and payload.get("status") == status:
            return event
    return None


def _live_events(payload: dict[str, object]) -> list[dict[str, object]]:
    """Return live partial-history events."""
    partial_history = json_object_payload(
        payload.get("partial_history"),
        label="live partial history",
    )
    return json_object_list_payload(
        partial_history.get("items"),
        label="live partial history items",
    )


def _wait_for_action(
    websocket: Connection,
    predicate: Callable[[dict[str, object]], bool],
    *,
    timeout: float = 15,
) -> dict[str, object]:
    """Wait for one WebSocket action matching a semantic predicate."""
    deadline = time.monotonic() + timeout
    observed: list[object] = []
    while time.monotonic() < deadline:
        try:
            raw = websocket.recv(timeout=max(0.1, deadline - time.monotonic()))
        except TimeoutError:
            continue
        action = json_object_payload(json.loads(raw), label="WebSocket action")
        observed.append(action.get("type"))
        if predicate(action):
            return action
    raise TimeoutError(f"matching WebSocket action was not observed: {observed!r}")


def _provider_upsert_with_status(status: str) -> Callable[[dict[str, object]], bool]:
    """Build a predicate for one provider-tool live upsert status."""

    def matches(action: dict[str, object]) -> bool:
        if action.get("type") != "live_event_upserted":
            return False
        event = json_object_payload(action.get("event"), label="live upsert event")
        return _provider_call_event([event], status=status) is not None

    return matches


def _provider_history_appended(action: dict[str, object]) -> bool:
    """Return whether an action appends the durable completed provider call."""
    if action.get("type") != "history_event_appended":
        return False
    event = json_object_payload(action.get("event"), label="history appended event")
    return _provider_call_event([event], status="completed") is not None


def _submit_quality_prompt(
    *,
    server_url: str,
    token: str,
    agent_id: str,
    session_id: str,
) -> None:
    """Start the deterministic hosted-tool response through the public API."""
    response = requests.post(
        f"{server_url}/chat/v1/sessions/{session_id}/inputs",
        headers={**auth_headers(token), "Content-Type": "application/json"},
        json={
            "agent_id": agent_id,
            "client_request_id": f"provider-tool-live-{unique()}",
            "message": _PROMPT,
            "inference_profile": {
                "model_target_label": "Quality",
                "reasoning_effort": None,
            },
        },
        timeout=10,
    )
    response.raise_for_status()


class TestProviderToolLiveActivity:
    """Validate live projection, resync, and durable semantic handoff."""

    def test_running_activity_resyncs_and_hands_off_without_duplication(
        self,
        public_api_client: azentspublicclient.ApiClient,
        admin_api_client: azentsadminclient.ApiClient,
        azents_public_server_url: str,
        azents_engine_worker_container: object,
    ) -> None:
        """One running web-search card becomes one durable completed call."""
        del azents_engine_worker_container
        token, agent_id, session_id = setup_profile_agent(
            public_api_client,
            admin_api_client,
            azents_public_server_url,
        )

        with connect_chat(
            public_api_client=public_api_client,
            server_url=azents_public_server_url,
            token=token,
            session_id=session_id,
        ) as websocket:
            _wait_for_action(
                websocket,
                lambda action: action.get("type") == "subscribed",
            )
            _submit_quality_prompt(
                server_url=azents_public_server_url,
                token=token,
                agent_id=agent_id,
                session_id=session_id,
            )

            running_action = _wait_for_action(
                websocket,
                _provider_upsert_with_status("running"),
            )
            running_event = json_object_payload(
                running_action.get("event"),
                label="running provider-tool event",
            )
            running_payload = json_object_payload(
                running_event.get("payload"),
                label="running provider-tool payload",
            )
            call_id = running_payload.get("call_id")
            live_event_id = running_event.get("id")
            assert isinstance(call_id, str) and call_id
            assert isinstance(live_event_id, str) and live_event_id
            assert running_event.get("adapter") == "azents-live"
            assert running_event.get("external_id") == call_id

            restored = list_live(
                server_url=azents_public_server_url,
                token=token,
                session_id=session_id,
            )
            restored_event = _provider_call_event(
                _live_events(restored),
                status="running",
            )
            assert restored_event is not None
            assert restored_event.get("id") == live_event_id

            completed_action = _wait_for_action(
                websocket,
                _provider_upsert_with_status("completed"),
            )
            completed_event = json_object_payload(
                completed_action.get("event"),
                label="completed provider-tool live event",
            )
            assert completed_event.get("id") == live_event_id

            durable_action = _wait_for_action(
                websocket,
                _provider_history_appended,
            )
            durable_event = json_object_payload(
                durable_action.get("event"),
                label="durable provider-tool event",
            )
            durable_payload = json_object_payload(
                durable_event.get("payload"),
                label="durable provider-tool payload",
            )
            assert durable_payload.get("call_id") == call_id

            removed_action = _wait_for_action(
                websocket,
                lambda action: (
                    action.get("type") == "live_event_removed"
                    and action.get("event_id") == live_event_id
                ),
            )
            assert removed_action.get("session_id") == session_id

        deadline = time.monotonic() + 15
        final_history: dict[str, object] | None = None
        while time.monotonic() < deadline:
            final_history = list_history(
                server_url=azents_public_server_url,
                token=token,
                session_id=session_id,
            )
            completed = _provider_call_event(
                history_events(final_history),
                status="completed",
            )
            contents = [
                json_object_payload(event.get("payload"), label="history payload").get(
                    "content"
                )
                for event in history_events(final_history)
                if event.get("kind") == "assistant_message"
            ]
            if completed is not None and _RESPONSE in contents:
                break
            time.sleep(0.1)
        else:
            raise TimeoutError(
                f"durable provider-tool handoff was not observed: {final_history!r}"
            )

        final_live = list_live(
            server_url=azents_public_server_url,
            token=token,
            session_id=session_id,
        )
        assert all(
            json_object_payload(event.get("payload"), label="final live payload").get(
                "call_id"
            )
            != call_id
            for event in _live_events(final_live)
            if event.get("kind") == "provider_tool_call"
        )
