"""Representative Routine tools, inbox judgment and per-item execution E2E."""

import hashlib
import json
import os
from collections.abc import Callable
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Literal

import azentsadminclient
import azentspublicclient
import requests
from azentspublicclient.api.agent_v1_api import AgentV1Api
from azentspublicclient.api.chat_v1_api import ChatV1Api
from azentspublicclient.api.llm_provider_integration_v1_api import (
    LLMProviderIntegrationV1Api,
)
from azentspublicclient.models.agent_update_request import AgentUpdateRequest
from azentspublicclient.models.api_key_secrets import ApiKeySecrets
from azentspublicclient.models.llm_provider import LLMProvider
from azentspublicclient.models.llm_provider_integration_create_request import (
    LLMProviderIntegrationCreateRequest,
)
from azentspublicclient.models.routine_detail_response import RoutineDetailResponse
from azentspublicclient.models.routine_list_response import RoutineListResponse
from azentspublicclient.models.secrets import Secrets
from azentspublicclient.models.session_context_response import SessionContextResponse
from docker.models.containers import Container
from pydantic import StrictBool, StrictInt, StrictStr, TypeAdapter

from support import routine_model_fixture as model
from support.observations import (
    ExtensionObservation,
    InputMessageObservation,
    ToolResultObservation,
    decode_history_page,
)
from support.utils import (
    AgentSessionSetup,
    authenticate_user,
    create_agent_session_setup,
    model_selection_from_first_candidate,
    single_candidate_model_options,
    unique,
    wait_until,
)
from tests.required.public.test_archived_session_retention import (
    _create_secondary_session,
)
from tests.required.public.test_run_tool_to_file import (
    _history,
    _initialized,
    _live_idle,
)


class _Considered(ExtensionObservation):
    routine_id: StrictStr
    slug: StrictStr
    title: StrictStr


class _Decision(ExtensionObservation):
    routine_id: StrictStr
    act: StrictBool


class _Decisions(ExtensionObservation):
    decisions: list[_Decision]


class _Usage(ExtensionObservation):
    total_tokens: StrictInt


class _Judgment(ExtensionObservation):
    status: Literal["completed", "failed", "cancelled"]
    considered: list[_Considered]
    decision: _Decisions | None
    usage: _Usage | None
    error: StrictStr | None


class _RoutineInput(ExtensionObservation):
    executions: list[_Considered]
    content: StrictStr


class _Turn(ExtensionObservation):
    usage: _Usage | None


class _NotificationFile(ExtensionObservation):
    uri: StrictStr
    name: StrictStr
    size: StrictInt


class _Notification(ExtensionObservation):
    content: StrictStr
    attachments: list[_NotificationFile]


class _ModelEvidence(ExtensionObservation):
    kind: Literal[
        "setup", "judgment", "work", "update", "delete", "hold", "channel_setup"
    ]
    candidate_ids: list[StrictStr]
    candidate_objectives: list[StrictStr]
    candidate_previous_work: list[StrictBool]
    execution_ids: list[StrictStr | None]
    tool_names: list[StrictStr]
    structured: StrictBool
    setup_in_canonical_context: StrictBool
    completed_calls: list[StrictStr]


def _write_evidence(session_id: str, stage: str, payload: dict[str, object]) -> None:
    """Use the existing CI artifact root without storing authorization headers."""
    root = os.environ.get("AZENTS_E2E_ARTIFACT_DIR")
    if root is None:
        return
    path = Path(root) / f"routine-{session_id}-{stage}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "head_sha": os.environ.get("CI_HEAD_SHA"),
                "source": "ci" if os.environ.get("CI_HEAD_SHA") else "local_worktree",
                **payload,
            },
            indent=2,
        )
    )


@dataclass(frozen=True)
class RoutineChannelJourney:
    """Public channel setup and sanitized provider assertions for the same journey."""

    prepare_session: Callable[[AgentSessionSetup], str]
    verify_notification: Callable[[AgentSessionSetup], None]
    delivery_status: Literal["delivered", "failed"]


@dataclass(frozen=True)
class RoutineSession:
    setup: AgentSessionSetup
    primary_session_id: str


def prepare_routine_session(
    public_api_client: azentspublicclient.ApiClient,
    admin_api_client: azentsadminclient.ApiClient,
    azents_public_server_url: str,
    channel: RoutineChannelJourney | None,
) -> RoutineSession:
    """Create exact Session authority and save explicit model capability evidence."""
    setup = create_agent_session_setup(
        public_api_client, admin_api_client, azents_public_server_url
    )
    common = {
        "server_url": azents_public_server_url,
        "token": setup.access_token,
        "session_id": setup.session_id,
    }
    wait_until(
        lambda: _initialized(**common),
        timeout=120,
        interval=0.5,
        message="Routine setup Session did not initialize",
    )
    primary_session_id = setup.session_id
    setup = replace(
        setup,
        session_id=(
            channel.prepare_session(setup)
            if channel is not None
            else _create_secondary_session(
                server_url=azents_public_server_url,
                token=setup.access_token,
                agent_id=setup.agent_id,
            )
        ),
    )
    common["session_id"] = setup.session_id
    headers = {"Authorization": f"Bearer {setup.access_token}"}
    integration = LLMProviderIntegrationV1Api(
        public_api_client
    ).llm_provider_integration_v1_create_integration(
        handle=setup.workspace_handle,
        llm_provider_integration_create_request=LLMProviderIntegrationCreateRequest(
            provider=LLMProvider.OPENAI,
            name="__testenv_model_listing:deterministic-routine",
            secrets=Secrets(ApiKeySecrets(api_key="sk-test-key")),
        ),
        _headers=headers,
    )
    selection = model_selection_from_first_candidate(
        azents_public_server_url,
        setup.access_token,
        setup.workspace_handle,
        integration.id,
    )
    configured = AgentV1Api(public_api_client).agent_v1_update_agent(
        agent_id=setup.agent_id,
        handle=setup.workspace_handle,
        agent_update_request=AgentUpdateRequest(
            selectable_model_options=single_candidate_model_options(selection),
            routine_check_interval_minutes=30,
            routine_min_action_delay_minutes=30,
        ),
        _headers=headers,
    )
    assert (
        configured.selectable_model_options[0]
        .candidates[0]
        .model_selection.normalized_capabilities.structured_response
    )
    return RoutineSession(setup, primary_session_id)


def run_routine_journey(
    public_api_client: azentspublicclient.ApiClient,
    admin_api_client: azentsadminclient.ApiClient,
    azents_public_server_url: str,
    azents_admin_server_url: str,
    openai_proxy_url: str,
    inspect_web: Callable[[AgentSessionSetup], None] | None,
    channel: RoutineChannelJourney | None,
) -> None:
    """Exercise real Routine boundaries, optionally inspecting the deployed Web."""
    prepared = prepare_routine_session(
        public_api_client, admin_api_client, azents_public_server_url, channel
    )
    setup = prepared.setup
    primary_session_id = prepared.primary_session_id
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

    def inventory() -> RoutineListResponse:
        response = requests.get(resource, headers=headers, timeout=10)
        response.raise_for_status()
        return RoutineListResponse.model_validate(response.json())

    def detail(slug: str) -> RoutineDetailResponse:
        response = requests.get(f"{resource}/{slug}", headers=headers, timeout=10)
        response.raise_for_status()
        return RoutineDetailResponse.model_validate(response.json())

    def journal() -> list[_ModelEvidence]:
        response = requests.get(openai_proxy_url + model.JOURNAL_PATH, timeout=10)
        response.raise_for_status()
        return TypeAdapter(list[_ModelEvidence]).validate_python(response.json())

    requests.delete(
        openai_proxy_url + model.JOURNAL_PATH, timeout=10
    ).raise_for_status()
    created = requests.post(
        f"{azents_public_server_url}/chat/v1/sessions/{setup.session_id}/inputs",
        headers=headers,
        json={
            "agent_id": setup.agent_id,
            "client_request_id": f"routine-create-{unique()}",
            "message": model.SETUP,
            "inference_profile": {
                "model_target_label": "default",
                "reasoning_effort": None,
                "enabled_execution_options": [],
            },
        },
        timeout=10,
    )
    created.raise_for_status()

    def setup_ready() -> bool:
        ready = any(
            item.kind == "assistant_message"
            and InputMessageObservation.model_validate(item.payload).content
            == model.READY
            for item in _history(**common).items
        )
        return ready and len(inventory().items) == 2 and _live_idle(**common)

    wait_until(
        setup_ready,
        timeout=120,
        interval=0.5,
        message="Routine tools did not create definitions",
    )
    definitions = inventory().items
    assert {item.content.title for item in definitions} == {
        "ROUTINE_E2E Alpha",
        "ROUTINE_E2E Beta",
    }
    assert not any(item.kind == "routine_judgment" for item in _history(**common).items)
    assert all(detail(item.slug).execution is None for item in definitions)

    def dispatch(now: str) -> None:
        barrier = openai_proxy_url + model.JUDGMENT_BARRIER_PATH
        requests.post(barrier, timeout=10).raise_for_status()
        try:
            response = requests.post(
                f"{azents_admin_server_url}/scheduler/v1/routines/dispatch",
                json={"now": now},
                timeout=30,
            )
            response.raise_for_status()
            assert response.json()["enqueued"] == 1
        finally:
            requests.post(barrier + "/release", timeout=10).raise_for_status()

    def context() -> SessionContextResponse:
        response = requests.get(
            resource.removesuffix("/routines") + "/context",
            headers=headers,
            timeout=10,
        )
        response.raise_for_status()
        return SessionContextResponse.model_validate(response.json())

    ordinary_context = context()
    ordinary_turns = sum(
        item.kind == "turn_marker" for item in _history(**common).items
    )
    dispatch("2099-01-01T00:00:00Z")

    def no_action() -> bool:
        observations = [
            _Judgment.model_validate(item.payload)
            for item in _history(**common).items
            if item.kind == "routine_judgment"
        ]
        for item in observations:
            assert item.status == "completed", item.error
        return len(observations) == 1 and _live_idle(**common)

    wait_until(
        no_action,
        timeout=120,
        interval=0.5,
        message="First tick did not settle no-action judgment",
    )
    first_judgment = next(
        _Judgment.model_validate(item.payload)
        for item in _history(**common).items
        if item.kind == "routine_judgment"
    )
    assert first_judgment.decision is not None
    assert all(not item.act for item in first_judgment.decision.decisions)
    assert not any(item.kind == "work" for item in journal())
    assert all(detail(item.slug).execution is None for item in definitions)
    after_no_action = context()
    assert after_no_action.usage == ordinary_context.usage
    assert after_no_action.system_prompt == ordinary_context.system_prompt
    assert after_no_action.breakdown == ordinary_context.breakdown
    assert (
        sum(item.kind == "turn_marker" for item in _history(**common).items)
        == ordinary_turns
    )

    # Source cadence is controlled; no prior action has advanced the real
    # Worker's delay reference, so the next tick needs no wall-clock sleep.
    dispatch("2099-01-01T00:30:00Z")

    def completed() -> list[RoutineDetailResponse] | None:
        for event in _history(**common).items:
            if event.kind == "routine_judgment":
                judgment = _Judgment.model_validate(event.payload)
                assert judgment.status == "completed", judgment.error
        snapshots = [detail(item.slug) for item in definitions]
        if not all(len(item.records) == 1 for item in snapshots):
            return None
        return snapshots if _live_idle(**common) else None

    snapshots = wait_until(
        completed,
        timeout=120,
        interval=0.5,
        message="Independent Routine records and continuation did not finish",
    )
    assert snapshots is not None
    by_title = {item.routine.content.title: item for item in snapshots}
    alpha, beta = by_title["ROUTINE_E2E Alpha"], by_title["ROUTINE_E2E Beta"]
    assert alpha.records[0].work.objective_outcome == "finished"
    assert alpha.records[0].work.notify is False
    assert alpha.records[0].work.message is None
    assert alpha.records[0].delivery_status == "not_requested"
    assert beta.records[0].work.objective_outcome == "failed"
    assert beta.records[0].work.notify is True
    assert beta.records[0].work.message == "ROUTINE_E2E_NOTIFICATION"
    assert beta.records[0].delivery_status == (
        channel.delivery_status if channel is not None else "delivered"
    )
    history = _history(**common).items
    if channel is None:
        notifications = [
            _Notification.model_validate(item.payload)
            for item in history
            if item.kind == "routine_notification"
        ]
        assert len(notifications) == 1
        assert len(notifications[0].attachments) == 1
        attached = notifications[0].attachments[0]
        assert attached.name == "routine-e2e-proof.txt"
        assert attached.uri.startswith("exchange://") and attached.size > 0
    judgments = [
        _Judgment.model_validate(item.payload)
        for item in history
        if item.kind == "routine_judgment"
    ]
    assert len(judgments) == 2
    assert all(
        item.status == "completed"
        and item.usage is not None
        and item.usage.total_tokens == 99999
        for item in judgments
    )
    trigger = [
        _RoutineInput.model_validate(item.payload)
        for item in history
        if item.kind == "routine_trigger"
    ]
    continuation = [
        _RoutineInput.model_validate(item.payload)
        for item in history
        if item.kind == "routine_continuation"
    ]
    assert len(trigger) == 1 and len(trigger[0].executions) == 2
    assert len(continuation) == 1 and len(continuation[0].executions) == 1
    for definition in definitions:
        assert definition.content.objective in trigger[0].content
    outputs = [
        ToolResultObservation.model_validate(item.payload)
        for item in history
        if item.kind == "client_tool_result"
    ]
    commands = [
        item for item in outputs if item.call_id.startswith("call_routine_e2e_command_")
    ]
    assert len(commands) == 2
    assert all(
        item.status == "completed" and model.RUNTIME_PROOF in str(item.output)
        for item in commands
    )
    primary_history = _history(
        server_url=azents_public_server_url,
        token=setup.access_token,
        session_id=primary_session_id,
    ).items
    notifications = [
        _Notification.model_validate(item.payload)
        for item in history
        if item.kind == "routine_notification"
    ]
    if channel is None:
        assert [item.content for item in notifications] == ["ROUTINE_E2E_NOTIFICATION"]
    else:
        assert notifications == []
        channel.verify_notification(setup)
    assert not any(item.kind == "routine_notification" for item in primary_history)
    normal = [
        _Turn.model_validate(item.payload)
        for item in history
        if item.kind == "turn_marker"
    ]
    assert normal and all(
        item.usage is None or item.usage.total_tokens != 99999 for item in normal
    )
    evidence = [item for item in journal() if item.kind == "judgment"]
    assert len(evidence) == 2
    for item in evidence:
        assert item.tool_names == [] and item.structured
        assert item.setup_in_canonical_context
        assert set(item.candidate_ids) == {definition.id for definition in definitions}
        assert set(item.candidate_objectives) == {
            definition.content.objective for definition in definitions
        }
    assert all(len(detail(item.slug).records) == 1 for item in definitions)
    prompt = ordinary_context.system_prompt
    _write_evidence(
        setup.session_id,
        "execution",
        {
            "clock_transitions": [
                "2099-01-01T00:00:00Z",
                "2099-01-01T00:30:00Z",
            ],
            "provider_requests": [item.model_dump(mode="json") for item in journal()],
            "work_snapshots": [item.model_dump(mode="json") for item in snapshots],
            "judgments": [item.model_dump(mode="json") for item in judgments],
            "ordinary_usage_before": ordinary_context.usage,
            "ordinary_usage_after_no_action": after_no_action.usage,
            "ordinary_prompt_sha256": hashlib.sha256(
                (prompt.model_dump_json() if prompt is not None else "").encode()
            ).hexdigest(),
            "ordinary_turn_count_before_no_action": ordinary_turns,
            "runtime_outputs": [
                item.model_dump(mode="json", include={"call_id", "status", "output"})
                for item in commands
            ],
        },
    )

    if inspect_web is not None:
        inspect_web(setup)

    secondary = _create_secondary_session(
        server_url=azents_public_server_url,
        token=setup.access_token,
        agent_id=setup.agent_id,
    )
    secondary_resource = resource.replace(setup.session_id, secondary)
    other = requests.get(secondary_resource, headers=headers, timeout=10)
    other.raise_for_status()
    assert RoutineListResponse.model_validate(other.json()).items == []
    assert (
        requests.get(
            f"{secondary_resource}/{definitions[0].slug}",
            headers=headers,
            timeout=10,
        ).status_code
        == 404
    )
    outsider, _, _ = authenticate_user(
        public_api_client,
        admin_api_client,
        email=f"routine-outside-{unique()}@example.com",
    )
    assert (
        requests.get(
            resource,
            headers={"Authorization": f"Bearer {outsider}"},
            timeout=10,
        ).status_code
        == 404
    )

    def request_action(message: str, expected: str) -> None:
        response = requests.post(
            f"{azents_public_server_url}/chat/v1/sessions/{setup.session_id}/inputs",
            headers=headers,
            json={
                "agent_id": setup.agent_id,
                "client_request_id": f"routine-manage-{unique()}",
                "message": message,
                "inference_profile": {
                    "model_target_label": "default",
                    "reasoning_effort": None,
                    "enabled_execution_options": [],
                },
            },
            timeout=10,
        )
        response.raise_for_status()

        def finished() -> bool:
            return any(
                item.kind == "assistant_message"
                and InputMessageObservation.model_validate(item.payload).content
                == expected
                for item in _history(**common).items
            ) and _live_idle(**common)

        wait_until(
            finished,
            timeout=120,
            interval=0.5,
            message=f"Routine management did not finish: {expected}",
        )

    target = alpha.routine
    request_action(model.UPDATE_PREFIX + target.slug, model.UPDATED)
    updated = detail(target.slug)
    assert updated.routine.content.objective == model.UPDATED_OBJECTIVE
    assert updated.routine.content.title == target.content.title
    assert updated.routine.content.sources == target.content.sources
    assert updated.records == alpha.records
    management = [
        ToolResultObservation.model_validate(item.payload)
        for item in _history(**common).items
        if item.kind == "client_tool_result"
    ]
    stale = next(
        item
        for item in management
        if item.call_id == f"call_routine_e2e_stale_{target.slug}"
    )
    applied = next(
        item
        for item in management
        if item.call_id == f"call_routine_e2e_update_{target.slug}"
    )
    assert stale.status == "failed" and applied.status == "completed"
    request_action(model.DELETE_PREFIX + target.slug, model.DELETED)
    assert (
        requests.get(
            f"{resource}/{target.slug}",
            headers=headers,
            timeout=10,
        ).status_code
        == 404
    )
    assert [item.id for item in inventory().items] == [beta.routine.id]
    _write_evidence(
        setup.session_id,
        "management",
        {
            "updated": updated.model_dump(mode="json"),
            "results": [
                item.model_dump(mode="json", include={"call_id", "status", "output"})
                for item in management
                if item.call_id.startswith("call_routine_e2e_")
            ],
            "remaining_inventory": inventory().model_dump(mode="json"),
            "provider_requests": [item.model_dump(mode="json") for item in journal()],
        },
    )

    chat = ChatV1Api(public_api_client)
    chat.chat_v1_archive_agent_session(
        setup.agent_id,
        setup.session_id,
        _headers=headers,
    )
    assert requests.get(resource, headers=headers, timeout=10).status_code == 404
    restored = chat.chat_v1_restore_agent_session(
        setup.agent_id,
        setup.session_id,
        _headers=headers,
    )
    assert restored.status == "active"
    assert inventory().items == []
    assert (
        requests.get(
            f"{resource}/{beta.routine.slug}",
            headers=headers,
            timeout=10,
        ).status_code
        == 404
    )
    original_judgment_ids = {
        item.id for item in history if item.kind == "routine_judgment"
    }
    page = _history(**common)
    retained_ids = {item.id for item in page.items}
    for _ in range(10):
        if original_judgment_ids <= retained_ids or not page.has_more:
            break
        response = requests.get(
            f"{azents_public_server_url}/chat/v1/sessions/{setup.session_id}/history",
            headers=headers,
            params={"limit": 100, "before": min(retained_ids)},
            timeout=10,
        )
        response.raise_for_status()
        page = decode_history_page(response.json())
        retained_ids.update(item.id for item in page.items)
    assert original_judgment_ids <= retained_ids
    _write_evidence(
        setup.session_id,
        "restore",
        {
            "restored_status": restored.status,
            "inventory": inventory().model_dump(mode="json"),
            "retained_judgment_ids": sorted(original_judgment_ids),
        },
    )


def test_joint_tick_uses_canonical_context_and_independent_work_results(
    public_api_client: azentspublicclient.ApiClient,
    admin_api_client: azentsadminclient.ApiClient,
    azents_public_server_url: str,
    azents_admin_server_url: str,
    azents_engine_worker_container: Container,
    openai_proxy_url: str,
) -> None:
    """Tool-created work crosses Scheduler, inbox, Worker and real Runtime paths."""
    del azents_engine_worker_container
    run_routine_journey(
        public_api_client,
        admin_api_client,
        azents_public_server_url,
        azents_admin_server_url,
        openai_proxy_url,
        None,
        None,
    )
