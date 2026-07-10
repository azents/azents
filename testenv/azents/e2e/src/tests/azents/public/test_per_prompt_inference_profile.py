"""Per-prompt inference profile product E2E tests."""

import json
import time
from typing import cast

import azentsadminclient
import azentspublicclient
import requests
from azentspublicclient.api.llm_provider_integration_v1_api import (
    LLMProviderIntegrationV1Api,
)
from azentspublicclient.api.workspace_v1_api import WorkspaceV1Api
from azentspublicclient.models.api_key_secrets import ApiKeySecrets
from azentspublicclient.models.create_workspace_request import CreateWorkspaceRequest
from azentspublicclient.models.llm_provider import LLMProvider
from azentspublicclient.models.llm_provider_integration_create_request import (
    LLMProviderIntegrationCreateRequest,
)
from azentspublicclient.models.secrets import Secrets
from pydantic import TypeAdapter, ValidationError

from support.utils import authenticate_user, unique, wait_until

_JSON_OBJECT = TypeAdapter(dict[str, object])
_JSON_OBJECT_LIST = TypeAdapter(list[dict[str, object]])
_QUALITY_MESSAGE = "Per prompt quality profile"
_FAST_MESSAGE = "Per prompt fast profile"


def _headers(token: str) -> dict[str, str]:
    """Build bearer headers."""
    return {"Authorization": f"Bearer {token}"}


def _object(value: object, *, label: str) -> dict[str, object]:
    """Validate a JSON object."""
    try:
        return _JSON_OBJECT.validate_python(value)
    except ValidationError as exc:
        raise AssertionError(f"{label} is not an object: {value!r}") from exc


def _objects(value: object, *, label: str) -> list[dict[str, object]]:
    """Validate a JSON object list."""
    try:
        return _JSON_OBJECT_LIST.validate_python(value)
    except ValidationError as exc:
        raise AssertionError(f"{label} is not an object list: {value!r}") from exc


def _response_object(response: requests.Response) -> dict[str, object]:
    """Validate an HTTP JSON object response."""
    response.raise_for_status()
    return _object(response.json(), label="HTTP response")


def _setup_profile_agent(
    public_api_client: azentspublicclient.ApiClient,
    admin_api_client: azentsadminclient.ApiClient,
    server_url: str,
) -> tuple[str, str, str]:
    """Create a workspace and Agent with deterministic Quality/Fast targets."""
    uniq = unique()
    token, _, _ = authenticate_user(
        public_api_client,
        admin_api_client,
        email=f"per-prompt-profile-{uniq}@example.com",
    )
    handle = f"per-prompt-profile-{uniq}"
    WorkspaceV1Api(public_api_client).workspace_v1_create_workspace(
        CreateWorkspaceRequest(
            workspace_name=f"Per Prompt Profile QA {uniq}",
            workspace_handle=handle,
            owner_name=f"Owner {uniq}",
        ),
        _headers=_headers(token),
    )
    integration = LLMProviderIntegrationV1Api(
        public_api_client
    ).llm_provider_integration_v1_create_integration(
        handle=handle,
        llm_provider_integration_create_request=LLMProviderIntegrationCreateRequest(
            provider=LLMProvider.OPENAI,
            name="__testenv_model_listing:deterministic-success",
            secrets=Secrets(ApiKeySecrets(api_key="sk-per-prompt-profile-qa")),
        ),
        _headers=_headers(token),
    )
    sync_url = (
        f"{server_url}/llm-provider-integration/v1/workspaces/{handle}/"
        f"llm-provider-integrations/{integration.id}/catalog-sync"
    )
    sync_response = wait_until(
        lambda: requests.post(sync_url, headers=_headers(token), timeout=10),
        timeout=10,
        interval=0.2,
        message="Catalog sync did not become available",
    )
    sync_response.raise_for_status()

    entries_url = (
        f"{server_url}/llm-provider-integration/v1/workspaces/{handle}/"
        f"llm-provider-integrations/{integration.id}/catalog-entries"
    )

    def populated_entries() -> list[dict[str, object]] | None:
        response = requests.get(entries_url, headers=_headers(token), timeout=10)
        response.raise_for_status()
        entries = _objects(
            _response_object(response).get("entries"),
            label="catalog entries",
        )
        identifiers = {entry.get("provider_model_identifier") for entry in entries}
        if {"gpt-5.5", "gpt-5.5-mini"}.issubset(identifiers):
            return entries
        return None

    entries = wait_until(
        populated_entries,
        timeout=10,
        interval=0.2,
        message="Deterministic catalog entries did not become readable",
    )
    assert entries is not None
    by_identifier = {
        cast(str, entry["provider_model_identifier"]): entry for entry in entries
    }

    def selection(identifier: str) -> dict[str, str]:
        return {
            "llm_provider_integration_id": integration.id,
            "model_identifier": identifier,
        }

    created = _response_object(
        requests.post(
            f"{server_url}/agent/v1/workspaces/{handle}/agents",
            headers={**_headers(token), "Content-Type": "application/json"},
            json={
                "name": "Per Prompt Profile QA Agent",
                "type": "public",
                "selectable_model_options": [
                    {
                        "label": "Quality",
                        "model_selection": selection(
                            cast(
                                str,
                                by_identifier["gpt-5.5"]["provider_model_identifier"],
                            )
                        ),
                    },
                    {
                        "label": "Fast",
                        "model_selection": selection(
                            cast(
                                str,
                                by_identifier["gpt-5.5-mini"][
                                    "provider_model_identifier"
                                ],
                            )
                        ),
                    },
                ],
                "main_model_label": "Quality",
                "lightweight_model_label": "Fast",
            },
            timeout=10,
        )
    )
    agent_id = created.get("id")
    if not isinstance(agent_id, str):
        raise AssertionError(f"Agent response did not include id: {created!r}")
    session = _response_object(
        requests.get(
            f"{server_url}/chat/v1/agents/{agent_id}/team-primary-session",
            headers=_headers(token),
            timeout=10,
        )
    )
    session_id = session.get("id")
    if not isinstance(session_id, str):
        raise AssertionError(f"Session response did not include id: {session!r}")
    return token, agent_id, session_id


def _write_profile(
    *,
    server_url: str,
    token: str,
    agent_id: str,
    session_id: str,
    message: str,
    target: str,
    effort: str | None,
) -> None:
    """Submit one explicit per-prompt profile."""
    response = requests.post(
        f"{server_url}/chat/v1/sessions/{session_id}/inputs",
        headers={**_headers(token), "Content-Type": "application/json"},
        json={
            "agent_id": agent_id,
            "client_request_id": f"per-prompt-profile-{unique()}",
            "message": message,
            "inference_profile": {
                "model_target_label": target,
                "reasoning_effort": effort,
            },
        },
        timeout=10,
    )
    response.raise_for_status()


def _history(server_url: str, token: str, session_id: str) -> list[dict[str, object]]:
    """Fetch the current history page."""
    response = requests.get(
        f"{server_url}/chat/v1/sessions/{session_id}/history?limit=100",
        headers=_headers(token),
        timeout=10,
    )
    return _objects(_response_object(response).get("items"), label="history items")


def _user_event(
    events: list[dict[str, object]], message: str
) -> dict[str, object] | None:
    """Find a user event by content."""
    for event in events:
        if event.get("kind") != "user_message":
            continue
        payload = _object(event.get("payload"), label="user event payload")
        if payload.get("content") == message:
            return event
    return None


def _wait_for_summary(
    *,
    server_url: str,
    token: str,
    session_id: str,
    message: str,
    status: str,
    timeout: float = 120,
) -> dict[str, object]:
    """Wait for a user event with the requested run-summary status."""
    deadline = time.monotonic() + timeout
    last_event: dict[str, object] | None = None
    while time.monotonic() < deadline:
        event = _user_event(_history(server_url, token, session_id), message)
        last_event = event
        if event is not None:
            raw_summary = event.get("inference_run_summary")
            if raw_summary is not None:
                summary = _object(raw_summary, label="inference run summary")
                if summary.get("status") == status:
                    return summary
        time.sleep(0.5)
    raise TimeoutError(f"Run summary did not reach {status}: {last_event!r}")


class TestPerPromptInferenceProfile:
    """Per-prompt routing and provenance E2E coverage."""

    def test_target_effort_resolution_and_safe_failure(
        self,
        public_api_client: azentspublicclient.ApiClient,
        admin_api_client: azentsadminclient.ApiClient,
        azents_public_server_url: str,
        azents_engine_worker_container: object,
        mock_openai_url: str,
    ) -> None:
        """Resolve distinct targets and expose an unsupported effort safely."""
        del azents_engine_worker_container
        token, agent_id, session_id = _setup_profile_agent(
            public_api_client,
            admin_api_client,
            azents_public_server_url,
        )
        requests.delete(
            f"{mock_openai_url}/v1/_requests", timeout=10
        ).raise_for_status()

        _write_profile(
            server_url=azents_public_server_url,
            token=token,
            agent_id=agent_id,
            session_id=session_id,
            message=_QUALITY_MESSAGE,
            target="Quality",
            effort="high",
        )
        quality = _wait_for_summary(
            server_url=azents_public_server_url,
            token=token,
            session_id=session_id,
            message=_QUALITY_MESSAGE,
            status="completed",
        )
        assert quality["requested_profile"] == {
            "model_target_label": "Quality",
            "reasoning_effort": "high",
        }
        quality_resolved = _object(
            quality.get("resolved_profile"), label="Quality resolved profile"
        )
        assert quality_resolved["model_identifier"] == "gpt-5.5"
        assert quality["resolved_reasoning_effort"] == "high"
        assert quality["effective_context_window_tokens"] == 64_000

        _write_profile(
            server_url=azents_public_server_url,
            token=token,
            agent_id=agent_id,
            session_id=session_id,
            message=_FAST_MESSAGE,
            target="Fast",
            effort=None,
        )
        fast = _wait_for_summary(
            server_url=azents_public_server_url,
            token=token,
            session_id=session_id,
            message=_FAST_MESSAGE,
            status="completed",
        )
        fast_resolved = _object(
            fast.get("resolved_profile"), label="Fast resolved profile"
        )
        assert fast_resolved["model_identifier"] == "gpt-5.5-mini"
        assert fast["effective_context_window_tokens"] == 64_000
        assert fast["run_id"] != quality["run_id"]

        journal = json.dumps(
            requests.get(f"{mock_openai_url}/v1/_requests", timeout=10).json()
        )
        assert "gpt-5.5" in journal
        assert "gpt-5.5-mini" in journal

        unsupported_message = "Unsupported effort must fail safely"
        _write_profile(
            server_url=azents_public_server_url,
            token=token,
            agent_id=agent_id,
            session_id=session_id,
            message=unsupported_message,
            target="Fast",
            effort="high",
        )
        failed = _wait_for_summary(
            server_url=azents_public_server_url,
            token=token,
            session_id=session_id,
            message=unsupported_message,
            status="failed",
        )
        assert failed["failure_code"] == "reasoning_effort_unsupported"
        assert isinstance(failed["failure_message"], str)
        assert failed["resolved_profile"] is None
