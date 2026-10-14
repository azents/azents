"""Public API E2E coverage for Session model-profile replacement."""

from functools import partial

import azentsadminclient
import azentspublicclient
import requests
from azentspublicclient.models.chat_session_model_profile_response import (
    ChatSessionModelProfileResponse,
)
from pydantic import TypeAdapter, ValidationError

from support.utils import unique
from tests.required.public.test_per_prompt_inference_profile import (
    _headers,
    _history,
    _typed_wait_for_session_profile,
    setup_profile_api_agent,
)

_JSON_OBJECT_LIST = TypeAdapter(list[dict[str, object]])


def _journal_snapshot(response: requests.Response) -> list[dict[str, object]]:
    """Preserve opaque object-list equality without interpreting provider fields."""
    response.raise_for_status()
    try:
        return _JSON_OBJECT_LIST.validate_python(response.json())
    except ValidationError as error:
        raise AssertionError("Provider journal was not an object list.") from error


def _journal(mock_openai_url: str) -> list[dict[str, object]]:
    """Read the mock provider request journal from its base URL."""
    return _journal_snapshot(
        requests.get(f"{mock_openai_url}/v1/_requests", timeout=10)
    )


def _image_generation_journal(openai_proxy_url: str) -> list[dict[str, object]]:
    """Read the separate image-generation proxy journal from its base URL."""
    return _journal_snapshot(
        requests.get(
            f"{openai_proxy_url}/v1/_image_generation_requests",
            timeout=10,
        )
    )


def _profile(response: requests.Response) -> ChatSessionModelProfileResponse:
    """Decode the current model-profile replacement response at HTTP ingress."""
    response.raise_for_status()
    return ChatSessionModelProfileResponse.model_validate_json(response.text)


def _replace_profile(
    *,
    server_url: str,
    token: str,
    session_id: str,
    target: str,
    effort: str | None,
    enabled_execution_options: list[str],
    client_request_id: str,
) -> requests.Response:
    """Replace a Session model profile through the public API."""
    return requests.put(
        f"{server_url}/chat/v1/sessions/{session_id}/model-profile",
        headers={**_headers(token), "Content-Type": "application/json"},
        json={
            "client_request_id": client_request_id,
            "model_target_label": target,
            "reasoning_effort": effort,
            "enabled_execution_options": enabled_execution_options,
        },
        timeout=10,
    )


def test_complete_profile_is_idempotent_side_effect_free(
    public_api_client: azentspublicclient.ApiClient,
    admin_api_client: azentsadminclient.ApiClient,
    azents_public_server_url: str,
    mock_openai_url: str,
    openai_proxy_url: str,
) -> None:
    """Save and reload Ultrafast intent without a message or provider call."""
    token, agent_id, session_id = setup_profile_api_agent(
        public_api_client,
        admin_api_client,
        azents_public_server_url,
        speed_targets=True,
    )
    target = "Astra"
    enabled_execution_options = ["ultrafast"]
    before_history = _history(azents_public_server_url, token, session_id)
    before_journal = _journal(mock_openai_url)
    before_proxy = _image_generation_journal(openai_proxy_url)
    client_request_id = f"model-only-{unique()}"
    replace_profile = partial(
        _replace_profile,
        server_url=azents_public_server_url,
        token=token,
        session_id=session_id,
        target=target,
        effort="xhigh",
        enabled_execution_options=enabled_execution_options,
        client_request_id=client_request_id,
    )
    accepted = _profile(replace_profile())
    assert accepted.session_id == session_id
    assert accepted.model_target_label == target
    assert accepted.reasoning_effort == "xhigh"
    assert accepted.enabled_execution_options == enabled_execution_options
    applied = _typed_wait_for_session_profile(
        server_url=azents_public_server_url,
        token=token,
        agent_id=agent_id,
        session_id=session_id,
        target=target,
        effort="xhigh",
        enabled_execution_options=enabled_execution_options,
    )
    assert applied.current_enabled_execution_options == enabled_execution_options
    assert _profile(replace_profile()) == accepted
    conflict = _replace_profile(
        server_url=azents_public_server_url,
        token=token,
        session_id=session_id,
        target=target,
        effort="xhigh",
        enabled_execution_options=[],
        client_request_id=client_request_id,
    )
    assert conflict.status_code == 409
    _typed_wait_for_session_profile(
        server_url=azents_public_server_url,
        token=token,
        agent_id=agent_id,
        session_id=session_id,
        target=target,
        effort="xhigh",
        enabled_execution_options=enabled_execution_options,
    )
    assert _history(azents_public_server_url, token, session_id) == before_history
    assert _journal(mock_openai_url) == before_journal
    assert _image_generation_journal(openai_proxy_url) == before_proxy
