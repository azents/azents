"""Credential-free E2E coverage for ordered model candidate fallback."""

import azentsadminclient
import azentspublicclient
import requests
from azentspublicclient.models.agent_response import AgentResponse
from azentspublicclient.models.agent_session_model_availability_response import (
    AgentSessionModelAvailabilityResponse,
)
from azentspublicclient.models.selectable_model_option_response import (
    SelectableModelOptionResponse,
)
from pydantic import StrictInt, StrictStr

from support.observations import (
    ExtensionObservation,
    InputMessageObservation,
)
from support.utils import unique
from tests.required.public.test_per_prompt_inference_profile import (
    _headers,
    _response_object,
    _setup_profile_agent,
    _typed_history,
    _wait_for_mock_models,
    _wait_for_session_idle,
)

_PROMPT = "Quota fallback uses secondary candidate"
_SUCCESS = "Secondary candidate completed the request."
_PRIMARY_RETRY_PROMPT = "Reserved Primary retry uses primary candidate"
_PRIMARY_RETRY_SUCCESS = "Reserved Primary candidate completed the request."


class _AppliedRoute(ExtensionObservation):
    candidate_ordinal: StrictInt
    candidate_role: StrictStr
    model_identifier: StrictStr


class _RouteMarker(ExtensionObservation):
    applied_model_route: _AppliedRoute


def _candidate_selection(option: SelectableModelOptionResponse) -> dict[str, object]:
    """Select only declared fields from the validated stored candidate."""
    stored = option.candidates[0].model_selection
    return {
        "llm_provider_integration_id": stored.llm_provider_integration_id,
        "model_identifier": stored.model_identifier,
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
    agent = AgentResponse.model_validate(
        _response_object(requests.get(agent_url, headers=_headers(token), timeout=10))
    )
    options = {option.label: option for option in agent.selectable_model_options}
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

    history = _typed_history(azents_public_server_url, token, session_id)
    assistant_contents = [
        InputMessageObservation.model_validate(event.payload).content
        for event in history
        if event.kind == "assistant_message"
    ]
    assert assistant_contents == [_SUCCESS]
    assert all("Fallback" not in str(content) for content in assistant_contents)
    turn_markers = [event for event in history if event.kind == "turn_marker"]
    route = _RouteMarker.model_validate(turn_markers[-1].payload).applied_model_route
    assert route.candidate_ordinal == 2
    assert route.candidate_role == "fallback"
    assert route.model_identifier == "gpt-5.5-mini"

    availability_url = (
        f"{azents_public_server_url}/chat/v1/agents/{agent_id}/sessions/"
        f"{session_id}/model-availability"
    )
    availability = AgentSessionModelAvailabilityResponse.model_validate(
        _response_object(
            requests.get(availability_url, headers=_headers(token), timeout=10)
        )
    )
    assert availability.semantic_label == "Quality"
    assert availability.state == "cooldown"
    assert availability.first_usable_fallback_display_name

    reserved = requests.post(
        f"{azents_public_server_url}/chat/v1/agents/{agent_id}/sessions/"
        f"{session_id}/model-reservation",
        headers={**_headers(token), "Content-Type": "application/json"},
        json={
            "semantic_label": availability.semantic_label,
            "primary": availability.primary.to_dict(),
        },
        timeout=10,
    )
    reserved.raise_for_status()
    reservation_state = AgentSessionModelAvailabilityResponse.model_validate(
        _response_object(reserved)
    )
    assert reservation_state.state == "primary_next"
    reservation = reservation_state.reservation
    assert reservation is not None

    cancelled = requests.post(
        f"{azents_public_server_url}/chat/v1/agents/{agent_id}/sessions/"
        f"{session_id}/model-reservation/cancel",
        headers={**_headers(token), "Content-Type": "application/json"},
        json={"reservation_generation": reservation.reservation_generation},
        timeout=10,
    )
    cancelled.raise_for_status()
    assert (
        AgentSessionModelAvailabilityResponse.model_validate(
            _response_object(cancelled)
        ).state
        == "cooldown"
    )

    reserved_again = requests.post(
        f"{azents_public_server_url}/chat/v1/agents/{agent_id}/sessions/"
        f"{session_id}/model-reservation",
        headers={**_headers(token), "Content-Type": "application/json"},
        json={
            "semantic_label": availability.semantic_label,
            "primary": availability.primary.to_dict(),
        },
        timeout=10,
    )
    reserved_again.raise_for_status()
    second_reservation_state = AgentSessionModelAvailabilityResponse.model_validate(
        _response_object(reserved_again)
    )
    assert second_reservation_state.state == "primary_next"
    second_reservation = second_reservation_state.reservation
    assert second_reservation is not None
    first_generation = reservation.reservation_generation
    second_generation = second_reservation.reservation_generation
    assert isinstance(first_generation, int)
    assert isinstance(second_generation, int)
    assert second_generation > first_generation

    stale_cancel = requests.post(
        f"{azents_public_server_url}/chat/v1/agents/{agent_id}/sessions/"
        f"{session_id}/model-reservation/cancel",
        headers={**_headers(token), "Content-Type": "application/json"},
        json={"reservation_generation": first_generation},
        timeout=10,
    )
    assert stale_cancel.status_code == 409
    assert (
        AgentSessionModelAvailabilityResponse.model_validate(stale_cancel.json()).state
        == "primary_next"
    )

    requests.delete(f"{mock_openai_url}/v1/_requests", timeout=10).raise_for_status()
    retried = requests.post(
        f"{azents_public_server_url}/chat/v1/sessions/{session_id}/inputs",
        headers={**_headers(token), "Content-Type": "application/json"},
        json={
            "agent_id": agent_id,
            "client_request_id": f"primary-retry-{unique()}",
            "message": _PRIMARY_RETRY_PROMPT,
            "inference_profile": {
                "model_target_label": "Quality",
                "reasoning_effort": None,
                "enabled_execution_options": [],
            },
        },
        timeout=10,
    )
    retried.raise_for_status()
    _wait_for_session_idle(
        server_url=azents_public_server_url,
        token=token,
        agent_id=agent_id,
        session_id=session_id,
    )
    primary_journal = _wait_for_mock_models(mock_openai_url, "gpt-5.5")
    assert "gpt-5.5-mini" not in primary_journal

    retried_history = _typed_history(azents_public_server_url, token, session_id)
    retried_assistant_contents = [
        InputMessageObservation.model_validate(event.payload).content
        for event in retried_history
        if event.kind == "assistant_message"
    ]
    assert retried_assistant_contents[-1] == _PRIMARY_RETRY_SUCCESS
    retried_markers = [
        event for event in retried_history if event.kind == "turn_marker"
    ]
    retried_route = _RouteMarker.model_validate(
        retried_markers[-1].payload
    ).applied_model_route
    assert retried_route.candidate_ordinal == 1
    assert retried_route.candidate_role == "primary"
    assert retried_route.model_identifier == "gpt-5.5"

    recovered = AgentSessionModelAvailabilityResponse.model_validate(
        _response_object(
            requests.get(availability_url, headers=_headers(token), timeout=10)
        )
    )
    assert recovered.state == "available"
    assert recovered.reservation is None
