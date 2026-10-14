"""One assembled product journey through the fixture client's live Chat API."""

import json
import subprocess
import textwrap

import azentsadminclient
import azentspublicclient

from support.consts import REPOSITORY_ROOT
from support.runtime_profiles import start_and_wait_for_agent_runtime
from tests.required.public.test_per_prompt_inference_profile import (
    _QUALITY_MESSAGE,
    _create_profile_agent,
)

_LIVE_HELPER_JOURNEY = textwrap.dedent("""\
    import sys
    from pydantic import BaseModel, ConfigDict
    from testenv.client import build_client
    from testenv.live.events import RunMarkerPayload
    from testenv.live.matchers import has_text_content, run_completed
    from testenv.runtime_config import TestenvConfig
    from testenv.seed.types import Agent, Integration, User, Workspace

    class Input(BaseModel):
        model_config = ConfigDict(
            strict=True, extra="forbid", hide_input_in_errors=True,
        )
        public_url: str
        token: str
        email: str
        handle: str
        agent_id: str
        message: str

    request = Input.model_validate_json(sys.stdin.read())
    config = TestenvConfig(
        public_url=request.public_url,
        admin_url=request.public_url,
        testenv_api_url=request.public_url,
    )
    client = build_client(config)
    user = User(email=request.email, access_token=request.token, refresh_token="unused")
    workspace = Workspace(handle=request.handle, name="E2E Workspace", owner=user)
    integration = Integration(
        id="unused", workspace=workspace, provider="openai", name="E2E",
    )
    agent = Agent(
        id=request.agent_id, workspace=workspace, integration=integration,
        name="E2E Agent", model_slug="unused",
    )
    session = client.chat.start_session(user, agent)
    actions = client.tools.run_and_collect(session, request.message, timeout=120.0)
    run_completed(actions)
    has_text_content(actions)
    event = actions[-1].event
    assert event is not None
    assert isinstance(event.payload, RunMarkerPayload)
    assert event.payload.status == "completed"
    print("Live Chat helper completed the canonical product journey")
    """)


def test_fixture_live_chat_observes_current_product_transport(
    public_api_client: azentspublicclient.ApiClient,
    admin_api_client: azentsadminclient.ApiClient,
    azents_public_server_url: str,
    mock_openai_url: str,
    openai_proxy_url: str,
) -> None:
    """Verify generated REST, confirmed subscription, assistant and run marker.

    Invoke the fixture package in its owning uv project rather than introducing
    backend/fixture dependencies into the separate E2E client-only environment.
    Secret inputs travel on stdin, never in process arguments or test output.
    """
    setup = _create_profile_agent(
        public_api_client,
        admin_api_client,
        azents_public_server_url,
        user_email=None,
        workspace_handle=None,
        speed_targets=False,
    )
    start_and_wait_for_agent_runtime(
        public_api_client,
        token=setup.access_token,
        workspace_handle=setup.workspace_handle,
        agent_id=setup.agent_id,
    )
    result = subprocess.run(
        [
            "uv",
            "run",
            "--project",
            str(REPOSITORY_ROOT / "testenv/azents"),
            "python",
            "-c",
            _LIVE_HELPER_JOURNEY,
        ],
        input=json.dumps(
            {
                "public_url": azents_public_server_url,
                "token": setup.access_token,
                "email": setup.email,
                "handle": setup.workspace_handle,
                "agent_id": setup.agent_id,
                "message": _QUALITY_MESSAGE,
            }
        ),
        text=True,
        capture_output=True,
        timeout=240,
        check=False,
    )
    assert result.returncode == 0, "Live Chat helper product journey failed"
    assert "completed the canonical product journey" in result.stdout
