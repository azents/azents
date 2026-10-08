"""Public API E2E coverage for Session model-profile replacement."""

import azentsadminclient
import azentspublicclient
import pytest
import requests
from pydantic import TypeAdapter, ValidationError

from support.utils import unique
from tests.required.public.test_per_prompt_inference_profile import (
    _headers,
    _history,
    _response_object,
    _wait_for_session_profile,
    setup_profile_api_agent,
)

_JSON_OBJECT_LIST = TypeAdapter(list[dict[str, object]])


def _journal(mock_openai_url: str) -> list[dict[str, object]]:
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


@pytest.mark.parametrize(
    ("target", "enabled_execution_options"),
    [
        ("Quality", []),
        ("Quality", ["fast"]),
        ("Astra", ["ultrafast"]),
        ("Sol", ["ultrafast"]),
    ],
)
def test_complete_profile_is_idempotent_side_effect_free(
    public_api_client: azentspublicclient.ApiClient,
    admin_api_client: azentsadminclient.ApiClient,
    azents_public_server_url: str,
    mock_openai_url: str,
    openai_proxy_url: str,
    target: str,
    enabled_execution_options: list[str],
) -> None:
    """Save and reload complete speed intent without a message/provider call."""
    token, agent_id, session_id = setup_profile_api_agent(
        public_api_client,
        admin_api_client,
        azents_public_server_url,
        speed_targets=True,
    )
    before_history = _history(azents_public_server_url, token, session_id)
    before_journal = _journal(mock_openai_url)
    proxy_url = f"{openai_proxy_url}/v1/_image_generation_requests"
    before_proxy = requests.get(proxy_url, timeout=10).json()
    client_request_id = f"model-only-{unique()}"
    kwargs = {
        "server_url": azents_public_server_url,
        "token": token,
        "session_id": session_id,
        "target": target,
        "effort": "xhigh",
        "enabled_execution_options": enabled_execution_options,
        "client_request_id": client_request_id,
    }
    accepted_payload = _response_object(_replace_profile(**kwargs))
    assert accepted_payload == {
        "session_id": session_id,
        "model_target_label": target,
        "reasoning_effort": "xhigh",
        "enabled_execution_options": enabled_execution_options,
    }
    applied = _wait_for_session_profile(
        server_url=azents_public_server_url,
        token=token,
        agent_id=agent_id,
        session_id=session_id,
        target=target,
        effort="xhigh",
        enabled_execution_options=enabled_execution_options,
    )
    assert applied["current_enabled_execution_options"] == enabled_execution_options
    assert _response_object(_replace_profile(**kwargs)) == accepted_payload
    conflict = _replace_profile(
        server_url=azents_public_server_url,
        token=token,
        session_id=session_id,
        target=target,
        effort="xhigh",
        enabled_execution_options=[] if enabled_execution_options else ["fast"],
        client_request_id=client_request_id,
    )
    assert conflict.status_code == 409
    _wait_for_session_profile(
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
    assert requests.get(proxy_url, timeout=10).json() == before_proxy


@pytest.mark.parametrize(
    ("target", "enabled_execution_options", "expected_detail"),
    [
        ("Missing", [], "Model target label is not available"),
        ("Fast", ["fast"], "Enabled execution option is not supported by the model."),
        (
            "Fast",
            ["ultrafast"],
            "Enabled execution option is not supported by the model.",
        ),
        (
            "Quality",
            ["ultrafast"],
            "Enabled execution option is not supported by the model.",
        ),
        ("Astra", ["fast", "ultrafast"], None),
        ("Astra", ["ultrafast", "fast"], None),
        ("Astra", ["ultrafast", "ultrafast"], None),
        ("Astra", ["unknown-speed"], None),
    ],
)
def test_model_profile_rejects_invalid_input_without_side_effects(
    public_api_client: azentspublicclient.ApiClient,
    admin_api_client: azentsadminclient.ApiClient,
    azents_public_server_url: str,
    mock_openai_url: str,
    openai_proxy_url: str,
    target: str,
    enabled_execution_options: list[str],
    expected_detail: str | None,
) -> None:
    """Reject invalid profiles atomically, preserving a saved Ultrafast choice."""
    token, agent_id, session_id = setup_profile_api_agent(
        public_api_client,
        admin_api_client,
        azents_public_server_url,
        speed_targets=True,
    )
    _replace_profile(
        server_url=azents_public_server_url,
        token=token,
        session_id=session_id,
        target="Astra",
        effort="high",
        enabled_execution_options=["ultrafast"],
        client_request_id=f"seed-profile-{unique()}",
    ).raise_for_status()
    before_history = _history(azents_public_server_url, token, session_id)
    before_journal = _journal(mock_openai_url)
    proxy_url = f"{openai_proxy_url}/v1/_image_generation_requests"
    before_proxy = requests.get(proxy_url, timeout=10).json()
    response = _replace_profile(
        server_url=azents_public_server_url,
        token=token,
        session_id=session_id,
        target=target,
        effort=None,
        enabled_execution_options=enabled_execution_options,
        client_request_id=f"invalid-profile-{unique()}",
    )
    assert response.status_code == 422, response.text
    if expected_detail is not None:
        assert response.json() == {"detail": expected_detail}
    _wait_for_session_profile(
        server_url=azents_public_server_url,
        token=token,
        agent_id=agent_id,
        session_id=session_id,
        target="Astra",
        effort="high",
        enabled_execution_options=["ultrafast"],
    )
    assert _history(azents_public_server_url, token, session_id) == before_history
    assert _journal(mock_openai_url) == before_journal
    assert requests.get(proxy_url, timeout=10).json() == before_proxy
