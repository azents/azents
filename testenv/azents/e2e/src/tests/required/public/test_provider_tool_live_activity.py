"""Provider-tool live activity product-path E2E coverage."""

import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Literal

import azentsadminclient
import azentspublicclient
import requests
from azentspublicclient.models.chat_event_page_response import ChatEventPageResponse
from azentspublicclient.models.chat_event_response import ChatEventResponse
from azentspublicclient.models.live_event_list_response import LiveEventListResponse
from pydantic import Field, JsonValue, StrictStr, model_validator
from typing_extensions import Self
from websockets.sync.connection import Connection

from support.observations import (
    ChatActionObservation,
    ExtensionObservation,
    decode_history_page,
)
from support.utils import unique
from tests.required.public.test_agent_execution_persistence import (
    auth_headers,
    connect_chat,
    list_history,
    list_live,
)
from tests.required.public.test_per_prompt_inference_profile import setup_profile_agent

_PROMPT = "Provider tool live activity handoff"
_RESPONSE = "PROVIDER_TOOL_LIVE_ACTIVITY_COMPLETED"
_BARRIER_PATH = "/v1/_provider_tool_live_barrier"


class _ProviderCallPayload(ExtensionObservation):
    """Interpret provider-call fields while retaining forward-compatible evidence."""

    call_id: StrictStr = Field(min_length=1)
    name: StrictStr = Field(min_length=1)
    status: Literal["running", "completed", "failed", "cancelled", "interrupted"] | None


class _AssistantPayload(ExtensionObservation):
    """Interpret assistant text at the selected event payload boundary."""

    content: StrictStr | list[dict[str, JsonValue]]


class _ProviderAction(ChatActionObservation):
    """Require fields belonging to this flow's interpreted live-action variants."""

    event_id: StrictStr | None = None

    @model_validator(mode="after")
    def validate_provider_variant(self) -> Self:
        if self.type == "live_event_upserted" and self.event is None:
            raise ValueError("Live event upsert must include event")
        if self.type == "live_event_removed" and self.event_id is None:
            raise ValueError("Live event removal must include event_id")
        return self


@dataclass(frozen=True)
class _ProviderCall:
    event: ChatEventResponse
    payload: _ProviderCallPayload


def _provider_call_event(
    events: list[ChatEventResponse], *, status: str
) -> _ProviderCall | None:
    """Return the provider-tool call with the requested canonical status."""
    for event in events:
        if event.kind != "provider_tool_call":
            continue
        payload = _ProviderCallPayload.model_validate(event.payload)
        if payload.name == "web_search" and payload.status == status:
            return _ProviderCall(event=event, payload=payload)
    return None


def _live_events(payload: LiveEventListResponse) -> list[ChatEventResponse]:
    """Return live partial-history events from the generated wire contract."""
    return payload.partial_history.items


def _wait_for_action(
    websocket: Connection,
    predicate: Callable[[_ProviderAction], bool],
    *,
    timeout: float = 15,
) -> _ProviderAction:
    """Wait for one validated WebSocket action matching a semantic predicate."""
    deadline = time.monotonic() + timeout
    observed: list[str] = []
    while time.monotonic() < deadline:
        try:
            raw = websocket.recv(timeout=max(0.1, deadline - time.monotonic()))
        except TimeoutError:
            continue
        action = _ProviderAction.model_validate_json(raw)
        observed.append(action.type)
        if predicate(action):
            return action
    raise TimeoutError(f"matching WebSocket action was not observed: {observed!r}")


def _provider_upsert_with_status(status: str) -> Callable[[_ProviderAction], bool]:
    """Build a predicate for one provider-tool live upsert status."""

    def matches(action: _ProviderAction) -> bool:
        if action.type != "live_event_upserted":
            return False
        assert action.event is not None
        return _provider_call_event([action.event], status=status) is not None

    return matches


def _provider_history_appended(action: _ProviderAction) -> bool:
    """Return whether an action appends the durable completed provider call."""
    if action.type != "history_event_appended":
        return False
    assert action.event is not None
    return _provider_call_event([action.event], status="completed") is not None


def _wait_for_live_provider_call(
    *,
    server_url: str,
    token: str,
    session_id: str,
    status: str,
    timeout: float = 120,
) -> _ProviderCall:
    """Poll the public live snapshot until one provider call reaches status."""
    deadline = time.monotonic() + timeout
    latest: LiveEventListResponse | None = None
    while time.monotonic() < deadline:
        latest = LiveEventListResponse.model_validate(
            list_live(server_url=server_url, token=token, session_id=session_id)
        )
        event = _provider_call_event(_live_events(latest), status=status)
        if event is not None:
            return event
        time.sleep(0.01)
    raise TimeoutError(
        f"provider-tool live status {status!r} was not restored: {latest!r}"
    )


def _submit_quality_prompt(
    *, server_url: str, token: str, agent_id: str, session_id: str
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
                "enabled_execution_options": [],
            },
        },
        timeout=10,
    )
    response.raise_for_status()


def _arm_provider_tool_live_barrier(openai_proxy_url: str) -> None:
    """Hold provider completion until the running live snapshot is verified."""
    response = requests.post(f"{openai_proxy_url}{_BARRIER_PATH}", timeout=10)
    response.raise_for_status()


def _release_provider_tool_live_barrier(openai_proxy_url: str) -> None:
    """Allow the deterministic provider stream to complete."""
    response = requests.post(f"{openai_proxy_url}{_BARRIER_PATH}/release", timeout=10)
    response.raise_for_status()


class TestProviderToolLiveActivity:
    """Validate live projection, resync, and durable semantic handoff."""

    def test_running_activity_resyncs_and_hands_off_without_duplication(
        self,
        public_api_client: azentspublicclient.ApiClient,
        admin_api_client: azentsadminclient.ApiClient,
        azents_public_server_url: str,
        azents_engine_worker_container: object,
        openai_proxy_url: str,
    ) -> None:
        """One running web-search card becomes one durable completed call."""
        del azents_engine_worker_container
        token, agent_id, session_id = setup_profile_agent(
            public_api_client, admin_api_client, azents_public_server_url
        )

        _arm_provider_tool_live_barrier(openai_proxy_url)
        try:
            with connect_chat(
                public_api_client=public_api_client,
                server_url=azents_public_server_url,
                token=token,
                session_id=session_id,
            ) as websocket:
                _wait_for_action(websocket, lambda action: action.type == "subscribed")
                _submit_quality_prompt(
                    server_url=azents_public_server_url,
                    token=token,
                    agent_id=agent_id,
                    session_id=session_id,
                )
                running_action = _wait_for_action(
                    websocket, _provider_upsert_with_status("running")
                )
                running_event = running_action.event
                assert running_event is not None

                restored_event = _wait_for_live_provider_call(
                    server_url=azents_public_server_url,
                    token=token,
                    session_id=session_id,
                    status="running",
                )
                call_id = restored_event.payload.call_id
                live_event_id = restored_event.event.id
                assert call_id
                assert live_event_id
                assert restored_event.event.adapter == "azents-live"
                assert restored_event.event.external_id == call_id
                assert running_event.id == live_event_id

                _release_provider_tool_live_barrier(openai_proxy_url)
                completed_action = _wait_for_action(
                    websocket, _provider_upsert_with_status("completed")
                )
                completed_event = completed_action.event
                assert completed_event is not None
                assert completed_event.id == live_event_id

                durable_action = _wait_for_action(websocket, _provider_history_appended)
                durable_event = durable_action.event
                assert durable_event is not None
                durable_payload = _ProviderCallPayload.model_validate(
                    durable_event.payload
                )
                assert durable_payload.call_id == call_id

                removed_action = _wait_for_action(
                    websocket,
                    lambda action: (
                        action.type == "live_event_removed"
                        and action.event_id == live_event_id
                    ),
                )
                assert removed_action.session_id == session_id
        finally:
            _release_provider_tool_live_barrier(openai_proxy_url)

        deadline = time.monotonic() + 15
        final_history: ChatEventPageResponse | None = None
        while time.monotonic() < deadline:
            final_history = decode_history_page(
                list_history(
                    server_url=azents_public_server_url,
                    token=token,
                    session_id=session_id,
                )
            )
            completed = _provider_call_event(final_history.items, status="completed")
            contents = [
                _AssistantPayload.model_validate(event.payload).content
                for event in final_history.items
                if event.kind == "assistant_message"
            ]
            if completed is not None and _RESPONSE in contents:
                break
            time.sleep(0.1)
        else:
            raise TimeoutError(
                f"durable provider-tool handoff was not observed: {final_history!r}"
            )

        final_live = LiveEventListResponse.model_validate(
            list_live(
                server_url=azents_public_server_url,
                token=token,
                session_id=session_id,
            )
        )
        assert all(
            _ProviderCallPayload.model_validate(event.payload).call_id != call_id
            for event in _live_events(final_live)
            if event.kind == "provider_tool_call"
        )
