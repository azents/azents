"""Runtime output materialization product E2E coverage."""

import hashlib

import azentsadminclient
import azentspublicclient
import requests
from docker.models.containers import Container

from support.utils import create_agent_session_setup, wait_until

_PROMPT = "Run tool to file E2E"
_FINAL_RESPONSE = "RUN_TOOL_TO_FILE_E2E_COMPLETED"
_CREATE_CALL_ID = "call_run_tool_to_file_create"
_STORE_CALL_ID = "call_run_tool_to_file_store"
_INSPECT_CALL_ID = "call_run_tool_to_file_inspect"
_SOURCE_PATH = "/workspace/agent/run-tool-to-file-source/source.txt"
_READ_OUTPUT = f"Content of {_SOURCE_PATH} (characters 0-35050):\n\n{'x' * 35_050}"
_EXPECTED_SIZE = len(_READ_OUTPUT.encode())
_EXPECTED_SHA256 = hashlib.sha256(_READ_OUTPUT.encode()).hexdigest()


def _headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _history(
    *,
    server_url: str,
    token: str,
    session_id: str,
) -> dict[str, object]:
    response = requests.get(
        f"{server_url}/chat/v1/sessions/{session_id}/history",
        headers=_headers(token),
        params={"limit": 100},
        timeout=10,
    )
    response.raise_for_status()
    payload = response.json()
    if not isinstance(payload, dict):
        raise AssertionError(f"Session history was not an object: {payload!r}")
    return {str(key): value for key, value in payload.items()}


def _live_idle(
    *,
    server_url: str,
    token: str,
    session_id: str,
) -> bool:
    response = requests.get(
        f"{server_url}/chat/v1/sessions/{session_id}/live",
        headers=_headers(token),
        timeout=10,
    )
    response.raise_for_status()
    payload = response.json()
    return isinstance(payload, dict) and payload.get("session_run_state") == "idle"


def _history_items(payload: dict[str, object]) -> list[dict[str, object]]:
    raw_items = payload.get("items")
    if not isinstance(raw_items, list):
        raise AssertionError(f"History items were not a list: {payload!r}")
    return [
        {str(key): value for key, value in raw_item.items()}
        for raw_item in raw_items
        if isinstance(raw_item, dict)
    ]


def _event_payload(item: dict[str, object]) -> dict[str, object] | None:
    raw_payload = item.get("payload")
    if not isinstance(raw_payload, dict):
        return None
    return {str(key): value for key, value in raw_payload.items()}


def _completed_history(
    *,
    server_url: str,
    token: str,
    session_id: str,
) -> dict[str, object] | None:
    payload = _history(
        server_url=server_url,
        token=token,
        session_id=session_id,
    )
    completed = False
    for item in _history_items(payload):
        event_payload = _event_payload(item)
        if (
            item.get("kind") == "assistant_message"
            and event_payload is not None
            and event_payload.get("content") == _FINAL_RESPONSE
        ):
            completed = True
            break
    if not completed:
        return None
    if not _live_idle(
        server_url=server_url,
        token=token,
        session_id=session_id,
    ):
        return None
    return payload


def _initialized(
    *,
    server_url: str,
    token: str,
    session_id: str,
) -> bool:
    payload = _history(
        server_url=server_url,
        token=token,
        session_id=session_id,
    )
    has_assistant = any(
        item.get("kind") == "assistant_message" for item in _history_items(payload)
    )
    return has_assistant and _live_idle(
        server_url=server_url,
        token=token,
        session_id=session_id,
    )


def _tool_result_output(
    payload: dict[str, object],
    *,
    call_id: str,
) -> str:
    for item in _history_items(payload):
        if item.get("kind") != "client_tool_result":
            continue
        event_payload = _event_payload(item)
        if event_payload is None:
            continue
        if event_payload.get("call_id") != call_id:
            continue
        output = event_payload.get("output")
        if not isinstance(output, str):
            raise AssertionError(f"Tool result output was not text: {output!r}")
        return output
    raise AssertionError(f"Tool result was not found: {call_id}")


def test_run_tool_to_file_stores_full_read_output_without_model_body(
    public_api_client: azentspublicclient.ApiClient,
    admin_api_client: azentsadminclient.ApiClient,
    azents_public_server_url: str,
    azents_engine_worker_container: Container,
) -> None:
    """Store text above the Engine cap and expose only bounded result evidence."""
    del azents_engine_worker_container
    setup = create_agent_session_setup(
        public_api_client,
        admin_api_client,
        azents_public_server_url,
    )
    wait_until(
        lambda: _initialized(
            server_url=azents_public_server_url,
            token=setup.access_token,
            session_id=setup.session_id,
        ),
        timeout=120,
        interval=0.5,
        message="Initial Agent Run did not complete",
    )

    response = requests.post(
        f"{azents_public_server_url}/chat/v1/sessions/{setup.session_id}/inputs",
        headers={**_headers(setup.access_token), "Content-Type": "application/json"},
        json={
            "agent_id": setup.agent_id,
            "client_request_id": f"run-tool-to-file-{setup.session_id}",
            "message": _PROMPT,
            "inference_profile": {
                "model_target_label": "default",
                "reasoning_effort": None,
            },
        },
        timeout=10,
    )
    response.raise_for_status()

    history = wait_until(
        lambda: _completed_history(
            server_url=azents_public_server_url,
            token=setup.access_token,
            session_id=setup.session_id,
        ),
        timeout=120,
        interval=0.5,
        message="run_tool_to_file E2E did not complete",
    )
    assert history is not None

    store_output = _tool_result_output(history, call_id=_STORE_CALL_ID)
    assert "Ran read and stored 1 output part(s)" in store_output
    assert "x" * 100 not in store_output

    inspect_output = _tool_result_output(history, call_id=_INSPECT_CALL_ID)
    assert str(_EXPECTED_SIZE) in inspect_output
    assert _EXPECTED_SHA256 in inspect_output
    assert '"target_tool_name":"read"' in inspect_output

    call_ids: set[object] = set()
    for item in _history_items(history):
        event_payload = _event_payload(item)
        if item.get("kind") == "client_tool_call" and event_payload is not None:
            call_ids.add(event_payload.get("call_id"))
    assert {_CREATE_CALL_ID, _STORE_CALL_ID, _INSPECT_CALL_ID} <= call_ids
