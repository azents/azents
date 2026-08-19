"""Public API E2E coverage for Session model-profile replacement."""

import azentsadminclient
import azentspublicclient
import requests
from pydantic import TypeAdapter, ValidationError

from support.utils import unique
from tests.required.public.test_per_prompt_inference_profile import (
    _headers,
    _history,
    _response_object,
    _setup_profile_agent,
    _wait_for_session_profile,
)

_JSON_OBJECT_LIST = TypeAdapter(list[dict[str, object]])


def _journal(
    mock_openai_url: str,
) -> list[dict[str, object]]:
    """Read the deterministic provider request journal."""
    response = requests.get(f"{mock_openai_url}/v1/_requests", timeout=10)
    response.raise_for_status()
    try:
        return _JSON_OBJECT_LIST.validate_python(response.json())
    except ValidationError as exc:
        raise AssertionError(
            f"Provider journal was not an object list: {response.text}"
        ) from exc


def _replace_profile(
    *,
    server_url: str,
    token: str,
    session_id: str,
    target: str,
    client_request_id: str,
) -> requests.Response:
    """Replace a Session model profile through the public API."""
    return requests.put(
        f"{server_url}/chat/v1/sessions/{session_id}/model-profile",
        headers={**_headers(token), "Content-Type": "application/json"},
        json={
            "client_request_id": client_request_id,
            "model_target_label": target,
            "reasoning_effort": None,
        },
        timeout=10,
    )


def test_model_only_profile_is_idempotent_side_effect_free(
    public_api_client: azentspublicclient.ApiClient,
    admin_api_client: azentsadminclient.ApiClient,
    azents_public_server_url: str,
    mock_openai_url: str,
) -> None:
    """Apply Fast without a message and verify replay and execution side effects."""
    token, agent_id, session_id = _setup_profile_agent(
        public_api_client,
        admin_api_client,
        azents_public_server_url,
    )
    requests.delete(f"{mock_openai_url}/v1/_requests", timeout=10).raise_for_status()
    before_history = _history(azents_public_server_url, token, session_id)
    before_journal = _journal(mock_openai_url)
    client_request_id = f"model-only-{unique()}"

    accepted = _replace_profile(
        server_url=azents_public_server_url,
        token=token,
        session_id=session_id,
        target="Fast",
        client_request_id=client_request_id,
    )
    accepted_payload = _response_object(accepted)
    assert accepted_payload == {
        "session_id": session_id,
        "model_target_label": "Fast",
        "reasoning_effort": None,
    }
    applied = _wait_for_session_profile(
        server_url=azents_public_server_url,
        token=token,
        agent_id=agent_id,
        session_id=session_id,
        target="Fast",
        effort=None,
    )
    assert _history(azents_public_server_url, token, session_id) == before_history
    assert _journal(mock_openai_url) == before_journal
    assert applied["current_model_target_label"] == "Fast"

    replay = _replace_profile(
        server_url=azents_public_server_url,
        token=token,
        session_id=session_id,
        target="Fast",
        client_request_id=client_request_id,
    )
    assert _response_object(replay) == accepted_payload
    conflict = _replace_profile(
        server_url=azents_public_server_url,
        token=token,
        session_id=session_id,
        target="Quality",
        client_request_id=client_request_id,
    )
    assert conflict.status_code == 409
    assert _history(azents_public_server_url, token, session_id) == before_history
    assert _journal(mock_openai_url) == before_journal


def test_model_only_profile_rejects_invalid_target_without_side_effects(
    public_api_client: azentspublicclient.ApiClient,
    admin_api_client: azentsadminclient.ApiClient,
    azents_public_server_url: str,
    mock_openai_url: str,
) -> None:
    """Reject an unknown target while preserving Session and execution state."""
    token, agent_id, session_id = _setup_profile_agent(
        public_api_client,
        admin_api_client,
        azents_public_server_url,
    )
    requests.delete(f"{mock_openai_url}/v1/_requests", timeout=10).raise_for_status()
    before = _response_object(
        requests.get(
            f"{azents_public_server_url}/chat/v1/agents/{agent_id}/sessions/{session_id}",
            headers=_headers(token),
            timeout=10,
        )
    )
    before_history = _history(azents_public_server_url, token, session_id)

    response = _replace_profile(
        server_url=azents_public_server_url,
        token=token,
        session_id=session_id,
        target="Missing",
        client_request_id=f"invalid-profile-{unique()}",
    )
    assert response.status_code == 422
    assert response.json() == {"detail": "Model target label is not available"}
    after = _response_object(
        requests.get(
            f"{azents_public_server_url}/chat/v1/agents/{agent_id}/sessions/{session_id}",
            headers=_headers(token),
            timeout=10,
        )
    )
    assert (
        after["current_model_target_label"],
        after["current_reasoning_effort"],
    ) == (
        before["current_model_target_label"],
        before["current_reasoning_effort"],
    )
    assert _history(azents_public_server_url, token, session_id) == before_history
    assert _journal(mock_openai_url) == []
