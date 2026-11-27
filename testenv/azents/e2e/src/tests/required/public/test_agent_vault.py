"""Exercise Agent Vault settings through the actual CLI tool and managed Runner."""

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
