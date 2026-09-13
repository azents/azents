"""Credential-free E2E coverage for ordered model candidate fallback."""

import azentsadminclient
import azentspublicclient
import requests

from support.utils import unique
from tests.required.public.test_per_prompt_inference_profile import (
    _headers,
    _history,
    _object,
    _objects,
    _response_object,
    _setup_profile_agent,
    _wait_for_mock_models,
    _wait_for_session_idle,
)

_PROMPT = "Quota fallback uses secondary candidate"
_SUCCESS = "Secondary candidate completed the request."


def _candidate_selection(option: dict[str, object]) -> dict[str, object]:
    """Return the first candidate as a valid update selection input."""
    candidates = _objects(option.get("candidates"), label="model candidates")
    stored = _object(
        candidates[0].get("model_selection"),
        label="candidate model selection",
    )
    integration_id = stored.get("llm_provider_integration_id")
    model_identifier = stored.get("model_identifier")
    if not isinstance(integration_id, str) or not isinstance(model_identifier, str):
        raise AssertionError(f"Stored candidate selection is incomplete: {stored!r}")
    return {
        "llm_provider_integration_id": integration_id,
        "model_identifier": model_identifier,
    }


def test_quota_advances_to_fallback_and_primary_reservation_reconciles(
    public_api_client: azentspublicclient.ApiClient,
    admin_api_client: azentsadminclient.ApiClient,
    azents_public_server_url: str,
    mock_openai_url: str,
) -> None:
    """Quota advances once, records the actual route, and supports Primary-next."""
    suffix = unique()
    handle = f"quota-fallback-{suffix}"
    token, agent_id, session_id = _setup_profile_agent(
        public_api_client,
        admin_api_client,
        azents_public_server_url,
        user_email=f"quota-fallback-{suffix}@example.com",
        workspace_handle=handle,
    )
    agent_url = (
        f"{azents_public_server_url}/agent/v1/workspaces/{handle}/agents/{agent_id}"
    )
    agent = _response_object(
        requests.get(agent_url, headers=_headers(token), timeout=10)
    )
    options = {
        option["label"]: option
        for option in _objects(
            agent.get("selectable_model_options"),
            label="Agent selectable model options",
        )
        if isinstance(option.get("label"), str)
    }
    quality_selection = _candidate_selection(options["Quality"])
    fast_selection = _candidate_selection(options["Fast"])
    patched = requests.patch(
        agent_url,
        headers={**_headers(token), "Content-Type": "application/json"},
        json={
            "selectable_model_options": [
                {
                    "label": "Quality",
                    "candidates": [
                        {"model_selection": quality_selection},
                        {"model_selection": fast_selection},
                    ],
                    "subagent_enabled": True,
                    "subagent_guidance": None,
                },
                {
                    "label": "Fast",
                    "candidates": [{"model_selection": fast_selection}],
                    "subagent_enabled": True,
                    "subagent_guidance": None,
                },
            ],
            "main_model_label": "Quality",
            "lightweight_model_label": "Fast",
        },
        timeout=10,
    )
    patched.raise_for_status()
    requests.delete(f"{mock_openai_url}/v1/_requests", timeout=10).raise_for_status()

    submitted = requests.post(
        f"{azents_public_server_url}/chat/v1/sessions/{session_id}/inputs",
        headers={**_headers(token), "Content-Type": "application/json"},
        json={
            "agent_id": agent_id,
            "client_request_id": f"quota-fallback-{unique()}",
            "message": _PROMPT,
            "inference_profile": {
                "model_target_label": "Quality",
                "reasoning_effort": None,
                "enabled_execution_options": [],
            },
        },
        timeout=10,
    )
    submitted.raise_for_status()
    _wait_for_session_idle(
        server_url=azents_public_server_url,
        token=token,
        agent_id=agent_id,
        session_id=session_id,
    )
    _wait_for_mock_models(mock_openai_url, "gpt-5.5", "gpt-5.5-mini")

    history = _history(azents_public_server_url, token, session_id)
    assistant_contents = [
        _object(event.get("payload"), label="assistant payload").get("content")
        for event in history
        if event.get("kind") == "assistant_message"
    ]
    assert assistant_contents == [_SUCCESS]
    assert all("Fallback" not in str(content) for content in assistant_contents)
    turn_markers = [event for event in history if event.get("kind") == "turn_marker"]
    marker = _object(turn_markers[-1].get("payload"), label="turn marker payload")
    route = _object(marker.get("applied_model_route"), label="applied model route")
    assert route["candidate_ordinal"] == 2
    assert route["candidate_role"] == "fallback"
    assert route["model_identifier"] == "gpt-5.5-mini"

    availability_url = (
        f"{azents_public_server_url}/chat/v1/agents/{agent_id}/sessions/"
        f"{session_id}/model-availability"
    )
    availability = _response_object(
        requests.get(availability_url, headers=_headers(token), timeout=10)
    )
    assert availability["semantic_label"] == "Quality"
    assert availability["state"] == "cooldown"
    assert availability["first_usable_fallback_display_name"]

    reserved = requests.post(
        f"{azents_public_server_url}/chat/v1/agents/{agent_id}/sessions/"
        f"{session_id}/model-reservation",
        headers={**_headers(token), "Content-Type": "application/json"},
        json={
            "semantic_label": availability["semantic_label"],
            "primary": availability["primary"],
        },
        timeout=10,
    )
    reserved.raise_for_status()
    reservation_state = _response_object(reserved)
    assert reservation_state["state"] == "primary_next"
    reservation = _object(
        reservation_state.get("reservation"),
        label="Primary reservation",
    )

    cancelled = requests.post(
        f"{azents_public_server_url}/chat/v1/agents/{agent_id}/sessions/"
        f"{session_id}/model-reservation/cancel",
        headers={**_headers(token), "Content-Type": "application/json"},
        json={"reservation_generation": reservation["reservation_generation"]},
        timeout=10,
    )
    cancelled.raise_for_status()
    assert _response_object(cancelled)["state"] == "cooldown"
