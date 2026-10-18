"""Actual Runtime-held work establishes Routine FIFO and explicit Stop boundaries."""

import azentsadminclient
import azentspublicclient
import pytest
import requests
from azentspublicclient.api.chat_v1_api import ChatV1Api
from azentspublicclient.models.routine_detail_response import RoutineDetailResponse
from azentspublicclient.models.routine_list_response import RoutineListResponse
from docker.models.containers import Container
from pydantic import StrictBool, TypeAdapter

from support import routine_model_fixture as model
from support.observations import ExtensionObservation, InputMessageObservation
from support.utils import unique, wait_until
from tests.required.public.test_routines import (
    _Judgment,
    _ModelEvidence,
    _write_evidence,
    prepare_routine_session,
)
from tests.required.public.test_run_tool_to_file import _history, _live_idle


class _Barrier(ExtensionObservation):
    armed: StrictBool
    reached: StrictBool
    released: StrictBool


def test_held_runtime_tool_defers_judgment_and_stop_closes_incomplete_work(
    request: pytest.FixtureRequest,
    public_api_client: azentspublicclient.ApiClient,
    admin_api_client: azentsadminclient.ApiClient,
    azents_public_server_url: str,
    azents_admin_server_url: str,
    azents_engine_worker_container: Container,
    openai_proxy_url: str,
) -> None:
    """No timing sleep or second owner is needed to hold actual product work."""
    del azents_engine_worker_container
    setup = prepare_routine_session(
        public_api_client, admin_api_client, azents_public_server_url, None
    ).setup
    common = {
        "server_url": azents_public_server_url,
        "token": setup.access_token,
        "session_id": setup.session_id,
    }
    headers = {"Authorization": f"Bearer {setup.access_token}"}
    resource = (
        f"{azents_public_server_url}/chat/v1/agents/{setup.agent_id}"
        f"/sessions/{setup.session_id}/routines"
    )
    barrier = openai_proxy_url + model.RUNTIME_BARRIER_PATH
    request.addfinalizer(
        lambda: requests.post(barrier + "/release", timeout=10).raise_for_status()
    )
    requests.delete(
        openai_proxy_url + model.JOURNAL_PATH, timeout=10
    ).raise_for_status()

    def submit(message: str) -> None:
        requests.post(
            f"{azents_public_server_url}/chat/v1/sessions/{setup.session_id}/inputs",
            headers=headers,
            json={
                "agent_id": setup.agent_id,
                "client_request_id": f"routine-boundary-{unique()}",
                "message": message,
                "inference_profile": {
                    "model_target_label": "default",
                    "reasoning_effort": None,
                    "enabled_execution_options": [],
                },
            },
            timeout=10,
        ).raise_for_status()

    def assistant(text: str) -> bool:
        return any(
            item.kind == "assistant_message"
            and InputMessageObservation.model_validate(item.payload).content == text
            for item in _history(**common).items
        )

    def inventory() -> RoutineListResponse:
        response = requests.get(resource, headers=headers, timeout=10)
        response.raise_for_status()
        return RoutineListResponse.model_validate(response.json())

    def journal() -> list[_ModelEvidence]:
        response = requests.get(openai_proxy_url + model.JOURNAL_PATH, timeout=10)
        response.raise_for_status()
        return TypeAdapter(list[_ModelEvidence]).validate_python(response.json())

    def reached() -> bool:
        response = requests.get(barrier, timeout=10)
        response.raise_for_status()
        return _Barrier.model_validate(response.json()).reached

    def dispatch(now: str) -> None:
        response = requests.post(
            f"{azents_admin_server_url}/scheduler/v1/routines/dispatch",
            json={"now": now},
            timeout=30,
        )
        response.raise_for_status()
        assert response.json()["enqueued"] == 1

    submit(model.SETUP)
    wait_until(
        lambda: (
            assistant(model.READY)
            and len(inventory().items) == 2
            and _live_idle(**common)
        ),
        timeout=120,
        interval=0.2,
    )
    identities = {item.id for item in inventory().items}
    requests.post(barrier, timeout=10).raise_for_status()
    submit(model.HOLD)
    wait_until(
        reached,
        timeout=60,
        interval=0.1,
        message="Actual Runtime tool did not reach the held I/O boundary",
    )
    assert not _live_idle(**common)
    dispatch("2099-01-01T00:00:00Z")
    assert not any(item.kind == "judgment" for item in journal())
    requests.post(barrier + "/release", timeout=10).raise_for_status()

    def no_action() -> bool:
        judgments = [
            _Judgment.model_validate(item.payload)
            for item in _history(**common).items
            if item.kind == "routine_judgment"
        ]
        assert all(item.status == "completed" for item in judgments)
        return (
            assistant(model.HOLD_DONE) and len(judgments) == 1 and _live_idle(**common)
        )

    wait_until(no_action, timeout=120, interval=0.2)
    ordered = journal()
    assert next(
        index for index, item in enumerate(ordered) if item.kind == "hold"
    ) < next(index for index, item in enumerate(ordered) if item.kind == "judgment")
    requests.post(barrier, timeout=10).raise_for_status()
    dispatch("2099-01-01T00:30:00Z")
    wait_until(
        reached,
        timeout=60,
        interval=0.1,
        message="Selected Routine work did not reach actual Runtime I/O",
    )
    ChatV1Api(public_api_client).chat_v1_stop_session_run(
        setup.session_id, _headers=headers
    )
    wait_until(lambda: _live_idle(**common), timeout=30, interval=0.1)
    requests.post(barrier + "/release", timeout=10).raise_for_status()
    assert {item.id for item in inventory().items} == identities
    snapshots: list[RoutineDetailResponse] = []
    for definition in inventory().items:
        response = requests.get(
            f"{resource}/{definition.slug}", headers=headers, timeout=10
        )
        response.raise_for_status()
        snapshot = RoutineDetailResponse.model_validate(response.json())
        assert snapshot.records == []
        assert (
            snapshot.execution is not None and snapshot.execution.phase == "cancelled"
        )
        snapshots.append(snapshot)
    _write_evidence(
        setup.session_id,
        "fifo-stop",
        {
            "provider_requests": [item.model_dump(mode="json") for item in journal()],
            "after_stop": [item.model_dump(mode="json") for item in snapshots],
            "preserved_definition_ids": sorted(identities),
        },
    )
