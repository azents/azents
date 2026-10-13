"""Agent Runtime environment settings to Runner command credential-free E2E."""

import hashlib
from functools import partial

import azentsadminclient
import azentspublicclient
import requests
from azentspublicclient.api.agent_runtime_v1_api import AgentRuntimeV1Api
from azentspublicclient.models.replace_runtime_environment_request import (
    ReplaceRuntimeEnvironmentRequest,
)
from azentspublicclient.models.replacement_runtime_environment_value import (
    ReplacementRuntimeEnvironmentValue,
)
from azentspublicclient.models.runtime_environment_entry_edit import (
    RuntimeEnvironmentEntryEdit,
)
from azentspublicclient.models.value import Value
from docker.models.containers import Container
from pydantic import SecretStr

from support.image_generation_openai_proxy import (
    RUNTIME_ENVIRONMENT_FINAL,
    RUNTIME_ENVIRONMENT_PROMPT_PREFIX,
)
from support.observations import InputMessageObservation, ToolResultObservation
from support.utils import create_agent_session_setup, wait_until
from tests.required.public.test_run_tool_to_file import (
    _history,
    _initialized,
    _live_idle,
)


def test_agent_environment_settings_apply_to_subsequent_runtime_commands(
    public_api_client: azentspublicclient.ApiClient,
    admin_api_client: azentsadminclient.ApiClient,
    azents_public_server_url: str,
    azents_engine_worker_container: Container,
) -> None:
    """Save, replace, and delete; shell commands receive only current values."""
    del azents_engine_worker_container
    setup = create_agent_session_setup(
        public_api_client, admin_api_client, azents_public_server_url
    )
    wait_until(
        lambda: _initialized(
            server_url=azents_public_server_url,
            token=setup.access_token,
            session_id=setup.session_id,
        ),
        timeout=120,
        interval=0.5,
        message="Initial environment E2E Run did not complete",
    )
    api = AgentRuntimeV1Api(public_api_client)
    headers = {"Authorization": f"Bearer {setup.access_token}"}

    def completed_output(call_id: str) -> str | None:
        history = _history(
            server_url=azents_public_server_url,
            token=setup.access_token,
            session_id=setup.session_id,
        )
        output: str | None = None
        final = False
        for item in history.items:
            if item.kind == "client_tool_result":
                result = ToolResultObservation.model_validate(item.payload)
                if result.call_id == call_id:
                    assert result.status == "completed"
                    assert isinstance(result.output, str)
                    output = result.output
            if item.kind == "assistant_message":
                final = (
                    final
                    or InputMessageObservation.model_validate(item.payload).content
                    == RUNTIME_ENVIRONMENT_FINAL
                )
        if (
            output is None
            or not final
            or not _live_idle(
                server_url=azents_public_server_url,
                token=setup.access_token,
                session_id=setup.session_id,
            )
        ):
            return None
        return output

    for step, fake_value in (
        ("first", "fake-runtime-env-first"),
        ("next", "fake-runtime-env-next"),
        ("deleted", None),
    ):
        entries = (
            []
            if fake_value is None
            else [
                RuntimeEnvironmentEntryEdit(
                    name="E2E_AGENT_SECRET",
                    value=Value(
                        actual_instance=ReplacementRuntimeEnvironmentValue(
                            type="replace", value=SecretStr(fake_value)
                        )
                    ),
                )
            ]
        )
        settings = api.agent_runtime_v1_replace_runtime_environment(
            handle=setup.workspace_handle,
            agent_id=setup.agent_id,
            replace_runtime_environment_request=ReplaceRuntimeEnvironmentRequest(
                entries=entries
            ),
            _headers=headers,
        )
        assert [entry.name for entry in settings.entries] == (
            [] if fake_value is None else ["E2E_AGENT_SECRET"]
        )
        assert settings.can_manage
        assert fake_value is None or fake_value not in settings.to_json()
        redacted = api.agent_runtime_v1_get_runtime_environment(
            handle=setup.workspace_handle, agent_id=setup.agent_id, _headers=headers
        )
        assert redacted.to_dict() == settings.to_dict()
        response = requests.post(
            f"{azents_public_server_url}/chat/v1/sessions/{setup.session_id}/inputs",
            headers=headers,
            json={
                "agent_id": setup.agent_id,
                "client_request_id": f"runtime-env-{step}-{setup.session_id}",
                "message": f"{RUNTIME_ENVIRONMENT_PROMPT_PREFIX}{step}",
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
            partial(completed_output, f"call_runtime_environment_{step}"),
            timeout=120,
            interval=0.5,
            message=f"Runtime environment {step} command did not complete",
        )
        assert output is not None
        assert (
            "ABSENT"
            if fake_value is None
            else hashlib.sha256(fake_value.encode()).hexdigest()
        ) in output
        assert fake_value is None or fake_value not in output
