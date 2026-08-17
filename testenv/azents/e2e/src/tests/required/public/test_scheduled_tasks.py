"""Focused Scheduled Task public API and execution E2E tests."""

from typing import cast

import azentsadminclient
import azentspublicclient
import requests
from azentspublicclient.api.scheduled_task_v1_api import ScheduledTaskV1Api
from azentspublicclient.models.scheduled_task_create_request import (
    ScheduledTaskCreateRequest,
)
from docker.models.containers import Container

from support.utils import (
    AgentSessionSetup,
    create_agent_session_setup,
    wait_until,
)

_ONCE_AT = "2099-01-02T03:04:05Z"
_ONCE_TITLE = "Scheduled Task E2E once"
_ONCE_OBJECTIVE = "Submit the deterministic Scheduled Task E2E result."
_ONCE_RESULT = "SCHEDULED_TASK_E2E_FINISHED"
_CREATION_TITLE = "Scheduled Task E2E creation"
_CREATION_OBJECTIVE = "Verify Scheduled Task creation and retrieval."
_CREATION_AT = "2099-05-01T00:00:00Z"
_INITIAL_RESPONSE = "Upload session initialized."


def _headers(token: str) -> dict[str, str]:
    """Return bearer authorization headers."""
    return {"Authorization": f"Bearer {token}"}


def _dispatch_at(testenv_server_url: str, *, now: str) -> dict[str, object]:
    """Run one deterministic user Scheduled Task dispatcher pass."""
    response = requests.post(
        f"{testenv_server_url}/scheduler/v1/scheduled-tasks/dispatch",
        json={"now": now},
        timeout=30,
    )
    if not response.ok:
        raise AssertionError(
            "Scheduled Task dispatch failed with "
            f"{response.status_code}: {response.text}"
        )
    payload = response.json()
    if not isinstance(payload, dict):
        raise AssertionError(f"Scheduled Task dispatch was not an object: {payload!r}")
    return cast(dict[str, object], payload)


def _scheduled_result(
    *,
    public_server_url: str,
    token: str,
    session_id: str,
    expected_result: str,
) -> dict[str, object] | None:
    """Return one matching durable Scheduled Task result Event payload."""
    response = requests.get(
        f"{public_server_url}/chat/v1/sessions/{session_id}/history",
        headers=_headers(token),
        params={"limit": 100},
        timeout=10,
    )
    response.raise_for_status()
    payload = response.json()
    if not isinstance(payload, dict):
        raise AssertionError(f"Session history was not an object: {payload!r}")
    raw_items = payload.get("items")
    if not isinstance(raw_items, list):
        raise AssertionError(f"Session history items were not a list: {payload!r}")
    for raw_item in raw_items:
        if (
            not isinstance(raw_item, dict)
            or raw_item.get("kind") != "scheduled_task_result"
        ):
            continue
        raw_event_payload = raw_item.get("payload")
        if not isinstance(raw_event_payload, dict):
            continue
        if raw_event_payload.get("result") == expected_result:
            return cast(dict[str, object], raw_event_payload)
    return None


def _session_initialized(
    *,
    public_server_url: str,
    token: str,
    session_id: str,
) -> bool:
    """Return whether the setup Run is durable and the Session is idle."""
    history_response = requests.get(
        f"{public_server_url}/chat/v1/sessions/{session_id}/history",
        headers=_headers(token),
        params={"limit": 100},
        timeout=10,
    )
    history_response.raise_for_status()
    history = history_response.json()
    if not isinstance(history, dict):
        raise AssertionError(f"Session history was not an object: {history!r}")
    items = history.get("items")
    initialized = isinstance(items, list) and any(
        isinstance(item, dict)
        and item.get("kind") == "assistant_message"
        and _INITIAL_RESPONSE in str(item.get("payload"))
        for item in items
    )
    if not initialized:
        return False

    live_response = requests.get(
        f"{public_server_url}/chat/v1/sessions/{session_id}/live",
        headers=_headers(token),
        timeout=10,
    )
    live_response.raise_for_status()
    live = live_response.json()
    return isinstance(live, dict) and live.get("session_run_state") == "idle"


def _setup(
    public_api_client: azentspublicclient.ApiClient,
    admin_api_client: azentsadminclient.ApiClient,
    public_server_url: str,
) -> AgentSessionSetup:
    """Create one initialized Session with a ready deterministic Runtime."""
    setup = create_agent_session_setup(
        public_api_client,
        admin_api_client,
        public_server_url,
    )
    wait_until(
        lambda: _session_initialized(
            public_server_url=public_server_url,
            token=setup.access_token,
            session_id=setup.session_id,
        ),
        timeout=120,
        interval=0.5,
        message="Session setup Run did not finish before Scheduled Task validation",
    )
    return setup


def test_schedule_creation_is_readable(
    public_api_client: azentspublicclient.ApiClient,
    admin_api_client: azentsadminclient.ApiClient,
    azents_public_server_url: str,
    azents_engine_worker_container: Container,
) -> None:
    """A created Schedule is immediately readable through get and list."""
    del azents_engine_worker_container
    setup = _setup(
        public_api_client,
        admin_api_client,
        azents_public_server_url,
    )
    headers = _headers(setup.access_token)
    scheduled_api = ScheduledTaskV1Api(public_api_client)
    created = scheduled_api.scheduled_task_v1_create_scheduled_task(
        setup.agent_id,
        setup.workspace_handle,
        ScheduledTaskCreateRequest(
            session_id=setup.session_id,
            title=_CREATION_TITLE,
            objective=_CREATION_OBJECTIVE,
            at=_CREATION_AT,
            cron=None,
            timezone=None,
            channel_id=None,
        ),
        _headers=headers,
    )
    fetched = scheduled_api.scheduled_task_v1_get_scheduled_task(
        setup.agent_id,
        created.id,
        setup.workspace_handle,
        _headers=headers,
    )
    listed = scheduled_api.scheduled_task_v1_list_scheduled_tasks(
        setup.agent_id,
        setup.workspace_handle,
        _headers=headers,
    )
    assert fetched.id == created.id
    assert fetched.session.id == setup.session_id
    assert fetched.target is None
    assert fetched.title == _CREATION_TITLE
    assert fetched.objective == _CREATION_OBJECTIVE
    assert fetched.next_eligible_at.isoformat() == "2099-05-01T00:00:00+00:00"
    assert [task.id for task in listed.items] == [created.id]

    scheduled_api.scheduled_task_v1_delete_scheduled_task(
        setup.agent_id,
        created.id,
        setup.workspace_handle,
        _headers=headers,
    )


def test_session_only_one_time_task_due_now_dispatches_and_terminalizes(
    public_api_client: azentspublicclient.ApiClient,
    admin_api_client: azentsadminclient.ApiClient,
    azents_public_server_url: str,
    azents_admin_server_url: str,
    azents_engine_worker_container: Container,
) -> None:
    """A one-time Task due at the controlled pass instant runs immediately."""
    del azents_engine_worker_container
    setup = _setup(
        public_api_client,
        admin_api_client,
        azents_public_server_url,
    )
    scheduled_api = ScheduledTaskV1Api(public_api_client)
    headers = _headers(setup.access_token)
    created = scheduled_api.scheduled_task_v1_create_scheduled_task(
        setup.agent_id,
        setup.workspace_handle,
        ScheduledTaskCreateRequest(
            session_id=setup.session_id,
            title=_ONCE_TITLE,
            objective=_ONCE_OBJECTIVE,
            at=_ONCE_AT,
            cron=None,
            timezone=None,
            channel_id=None,
        ),
        _headers=headers,
    )

    assert created.session.id == setup.session_id
    assert created.target is None
    assert created.execution_state == "idle"
    dispatch = _dispatch_at(
        azents_admin_server_url,
        now=_ONCE_AT,
    )
    assert dispatch == {
        "now": _ONCE_AT,
        "claimed": 1,
        "admitted": 1,
        "coalesced": 0,
        "skipped": 0,
        "wake_failed": 0,
    }

    result = wait_until(
        lambda: _scheduled_result(
            public_server_url=azents_public_server_url,
            token=setup.access_token,
            session_id=setup.session_id,
            expected_result=_ONCE_RESULT,
        ),
        timeout=120,
        interval=0.5,
        message="Scheduled Task terminal result did not reach Session history",
    )
    assert result == {
        "title": _ONCE_TITLE,
        "scheduled_for": _ONCE_AT,
        "status": "finished",
        "result": _ONCE_RESULT,
    }
    remaining = scheduled_api.scheduled_task_v1_list_scheduled_tasks(
        setup.agent_id,
        setup.workspace_handle,
        _headers=headers,
    )
    assert all(task.id != created.id for task in remaining.items)
