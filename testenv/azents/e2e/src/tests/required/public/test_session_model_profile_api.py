"""Public API E2E coverage for Session model-profile replacement."""

from functools import partial

import azentsadminclient
import azentspublicclient
import requests
from azentspublicclient.models.chat_session_model_profile_response import (
    ChatSessionModelProfileResponse,
)

from support.utils import unique
from tests.required.public.test_per_prompt_inference_profile import (
    _headers,
    _history,
    _typed_wait_for_session_profile,
    setup_profile_api_agent,
)


def _journal(url: str) -> bytes:
    """Snapshot opaque journal bytes to prove no provider side effects."""
    response = requests.get(url, timeout=10)
    response.raise_for_status()
    return response.content


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
    journal_url = f"{mock_openai_url}/v1/_requests"
    before_journal = _journal(journal_url)
    proxy_url = f"{openai_proxy_url}/v1/_image_generation_requests"
    before_proxy = _journal(proxy_url)
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
    assert _journal(journal_url) == before_journal
    assert _journal(proxy_url) == before_proxy
