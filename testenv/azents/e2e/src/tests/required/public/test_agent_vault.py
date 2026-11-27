"""Exercise Agent Vault with the assembled API, Worker and managed Runner."""

import json
from functools import partial
from typing import TypedDict

import azentsadminclient
import azentspublicclient
import requests
from azentspublicclient.api.agent_v1_api import AgentV1Api
from azentspublicclient.models.vault_entry_write_request import VaultEntryWriteRequest
from docker.models.containers import Container

from support.image_generation_openai_proxy import (
    VAULT_CLI_FINAL,
    VAULT_CLI_PROMPT_PREFIX,
    VAULT_REQUEST_OPENED,
    VAULT_REQUEST_PROMPT,
    VAULT_REQUEST_RESUMED,
)
from support.observations import InputMessageObservation, ToolResultObservation
from support.utils import create_agent_session_setup, wait_until
from tests.required.public.test_run_tool_to_file import (
    _history,
    _initialized,
    _live_idle,
)


class _AgentScope(TypedDict):
    agent_id: str
    handle: str


def test_vault_settings_value_reaches_only_nominated_cli_command(
    public_api_client: azentspublicclient.ApiClient,
    admin_api_client: azentsadminclient.ApiClient,
    azents_public_server_url: str,
    azents_engine_worker_container: Container,
) -> None:
    """Prove a saved synthetic value reaches only an explicitly selected command."""
    del azents_engine_worker_container
    setup = create_agent_session_setup(
        public_api_client, admin_api_client, azents_public_server_url
    )
    params = {
        "server_url": azents_public_server_url,
        "token": setup.access_token,
        "session_id": setup.session_id,
    }
    wait_until(
        lambda: _initialized(**params),
        timeout=120,
        interval=0.5,
        message="Initial Vault E2E Run did not complete",
    )
    headers = {"Authorization": f"Bearer {setup.access_token}"}
    scope: _AgentScope = {"handle": setup.workspace_handle, "agent_id": setup.agent_id}
    api = AgentV1Api(public_api_client)
    marker = "synthetic-vault-cli-marker-72d45c80"
    api.agent_v1_create_agent_vault_entry(
        **scope,
        vault_entry_write_request=VaultEntryWriteRequest(
            name="e2e-token", value=marker
        ),
        _headers=headers,
    )
    settings = api.agent_v1_list_agent_vault_entries(**scope, _headers=headers)
    assert [item.name for item in settings.entries] == ["e2e-token"]
    assert marker not in settings.to_json()

    def completed(step: str) -> str | None:
        history = _history(**params)
        assert marker not in json.dumps(history.to_dict(), default=str)
        output = None
        final = False
        for item in history.items:
            if item.kind == "client_tool_result":
                result = ToolResultObservation.model_validate(item.payload)
                if result.call_id == f"call_vault_cli_{step}":
                    assert result.status == "completed"
                    assert isinstance(result.output, str)
                    output = result.output
            if item.kind == "assistant_message":
                final = final or (
                    InputMessageObservation.model_validate(item.payload).content
                    == VAULT_CLI_FINAL
                )
        return output if final and _live_idle(**params) else None

    for step, expected in (("use", str(len(marker))), ("ordinary", "ABSENT")):
        response = requests.post(
            f"{azents_public_server_url}/chat/v1/sessions/{setup.session_id}/inputs",
            headers=headers,
            json={
                "agent_id": setup.agent_id,
                "client_request_id": f"vault-cli-{step}-{setup.session_id}",
                "message": f"{VAULT_CLI_PROMPT_PREFIX}{step}",
                "inference_profile": {
                    "model_target_label": "default",
                    "reasoning_effort": None,
                    "enabled_execution_options": [],
                },
            },
            timeout=10,
        )
        response.raise_for_status()
        output = wait_until(
            partial(completed, step),
            timeout=120,
            interval=0.5,
            message=f"Vault CLI {step} command did not finish",
        )
        assert output is not None and expected in output
    api.agent_v1_delete_agent_vault_entry(**scope, name="e2e-token", _headers=headers)
    assert (
        api.agent_v1_list_agent_vault_entries(**scope, _headers=headers).entries == []
    )


def test_vault_request_submits_once_and_wakes_the_original_session(
    public_api_client: azentspublicclient.ApiClient,
    admin_api_client: azentsadminclient.ApiClient,
    azents_public_server_url: str,
    azents_engine_worker_container: Container,
) -> None:
    """Create through the model tool and settle through the public request route."""
    del azents_engine_worker_container
    setup = create_agent_session_setup(
        public_api_client, admin_api_client, azents_public_server_url
    )
    params = {
        "server_url": azents_public_server_url,
        "token": setup.access_token,
        "session_id": setup.session_id,
    }
    wait_until(
        lambda: _initialized(**params),
        timeout=120,
        interval=0.5,
        message="Initial Vault request E2E Run did not complete",
    )
    headers = {"Authorization": f"Bearer {setup.access_token}"}
    chat_url = f"{azents_public_server_url}/chat/v1/sessions/{setup.session_id}"
    response = requests.post(
        f"{chat_url}/inputs",
        headers=headers,
        json={
            "agent_id": setup.agent_id,
            "client_request_id": f"vault-request-{setup.session_id}",
            "message": VAULT_REQUEST_PROMPT,
            "inference_profile": {
                "model_target_label": "default",
                "reasoning_effort": None,
                "enabled_execution_options": [],
            },
        },
        timeout=10,
    )
    response.raise_for_status()

    def request_identity() -> str | None:
        items = _history(**params).items
        opened = any(
            item.kind == "assistant_message"
            and InputMessageObservation.model_validate(item.payload).content
            == VAULT_REQUEST_OPENED
            for item in items
        )
        if not opened or not _live_idle(**params):
            return None
        anchors = [item for item in items if item.kind == "vault_request"]
        assert len(anchors) == 1
        identity = anchors[0].payload["request_id"]
        assert isinstance(identity, str)
        return identity

    request_id = wait_until(
        request_identity,
        timeout=120,
        interval=0.5,
        message="No standalone Vault anchor followed by an idle Session",
    )
    assert request_id is not None
    url = (
        f"{azents_public_server_url}/agent/v1/workspaces/{setup.workspace_handle}"
        f"/agents/{setup.agent_id}/sessions/{setup.session_id}"
        f"/vault/requests/{request_id}"
    )
    current = requests.get(url, headers=headers, timeout=10)
    current.raise_for_status()
    assert current.json()["can_submit"] is True
    secrets = ("synthetic-account-659a", "synthetic-password-e034")
    body = {
        "values": [
            {"name": name, "value": value}
            for name, value in zip(("account", "password"), secrets, strict=True)
        ]
    }
    submitted = requests.post(url, headers=headers, json=body, timeout=10)
    assert submitted.status_code == 204, submitted.status_code

    def completed() -> bool:
        history = _history(**params)
        assert all(
            value not in json.dumps(history.to_dict(), default=str) for value in secrets
        )
        if not any(
            item.kind == "assistant_message"
            and InputMessageObservation.model_validate(item.payload).content
            == VAULT_REQUEST_RESUMED
            for item in history.items
        ):
            return False
        completion = [
            item for item in history.items if item.kind == "vault_request_completed"
        ]
        assert len(completion) == 1
        assert completion[0].payload["request_id"] == request_id
        assert set(completion[0].payload) <= {
            "request_id",
            "mailbox_item_id",
            "mailbox_item_key",
        }
        return _live_idle(**params)

    wait_until(
        completed,
        timeout=120,
        interval=0.5,
        message="Vault completion did not wake the original Session",
    )
    assert requests.post(url, headers=headers, json=body, timeout=10).status_code == 409
    current = requests.get(url, headers=headers, timeout=10)
    current.raise_for_status()
    assert current.json()["status"] == "submitted"
    assert current.json()["can_submit"] is False
