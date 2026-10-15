"""Normal Engine Browser capture, model image and original-file publication."""

import hashlib
import struct
from typing import Literal

import azentsadminclient
import azentspublicclient
import requests
from pydantic import BaseModel, ConfigDict, TypeAdapter

from support.exchange_download import download_fixture_exchange_file
from support.observations import HistoryEventObservation, ToolResultObservation
from support.utils import unique, wait_until
from tests.required.public.test_agent_execution_persistence import (
    history_events,
    list_history,
)
from tests.required.public.test_per_prompt_inference_profile import _setup_profile_agent
from tests.required.public.test_runtime_terminal import (
    _prepare_terminal_session,
    _TerminalWorkspace,
)
from tests.web.public.test_runtime_web_gateway import _RuntimeApplicationCommands
from tests.web.public.test_session_browser import _start_application

_PROMPT = "Session Browser capture and publication handoff"
_PREFIX = "call_browser_files_"


class _Part(BaseModel):
    model_config = ConfigDict(extra="allow")
    type: str
    text: str | None = None
    kind: str | None = None
    media_type: str | None = None
    model_file_id: str | None = None
    attachment_id: str | None = None
    uri: str | None = None
    size: int | None = None


class _Capture(BaseModel):
    model_config = ConfigDict(extra="forbid")
    path: str
    media_type: Literal["image/png"]
    size: int
    width: int
    height: int


class _CaptureResult(BaseModel):
    model_config = ConfigDict(extra="allow")
    capture: _Capture


class _OriginalEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid")
    size: int
    sha256: str
    png: bool


class _ModelEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid")
    model: str
    completed_calls: list[str]
    model_image_count: int
    model_images_are_data: bool


def _results(
    server_url: str, token: str, session_id: str
) -> dict[str, ToolResultObservation]:
    results = {}
    for raw in history_events(
        list_history(server_url=server_url, token=token, session_id=session_id)
    ):
        event = HistoryEventObservation.model_validate(raw)
        if event.kind != "client_tool_result":
            continue
        result = ToolResultObservation.model_validate(event.payload)
        if result.call_id.startswith(_PREFIX):
            results[result.call_id.removeprefix(_PREFIX)] = result
    return results


def _parts(result: ToolResultObservation) -> list[_Part]:
    assert result.status == "completed"
    return TypeAdapter(list[_Part]).validate_python(result.output)


def test_session_browser_capture_model_image_and_original_publication(
    public_api_client: azentspublicclient.ApiClient,
    admin_api_client: azentsadminclient.ApiClient,
    azents_public_server_url: str,
    azents_runtime_provider_docker_container: object,
    azents_browser_s3_endpoint_url: str,
    openai_proxy_url: str,
) -> None:
    del azents_runtime_provider_docker_container
    handle = f"browser-files-{unique()}"
    token, agent_id, session_id = _setup_profile_agent(
        public_api_client,
        admin_api_client,
        azents_public_server_url,
        workspace_handle=handle,
    )
    workspace = _TerminalWorkspace(
        token=token,
        handle=handle,
        agent_id=agent_id,
        session_id=session_id,
    )
    _prepare_terminal_session(
        public_api_client=public_api_client,
        workspace=workspace,
        server_url=azents_public_server_url,
    )
    commands = _RuntimeApplicationCommands(
        public_api_client=public_api_client,
        workspace=workspace,
        server_url=azents_public_server_url,
    )
    _start_application(commands)
    cleared = requests.delete(
        f"{openai_proxy_url}/v1/_browser_files_requests",
        timeout=10,
    )
    cleared.raise_for_status()
    assert cleared.json() == {"cleared": True}
    response = requests.post(
        f"{azents_public_server_url}/chat/v1/sessions/{session_id}/inputs",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "agent_id": agent_id,
            "client_request_id": f"browser-files-{unique()}",
            "message": _PROMPT,
            "inference_profile": {
                "model_target_label": "Quality",
                "reasoning_effort": None,
                "enabled_execution_options": [],
            },
        },
        timeout=10,
    )
    response.raise_for_status()
    wait_until(
        lambda: "publish" in _results(azents_public_server_url, token, session_id),
        timeout=120,
        interval=0.2,
        message="Browser capture publication did not finish",
    )
    results = _results(azents_public_server_url, token, session_id)
    assert set(results) == {"skill", "open", "capture", "inspect", "publish"}
    skill = results["skill"]
    assert skill.status == "completed" and isinstance(skill.output, str)
    assert "azents://skills/azents/browser/SKILL.md" in skill.output
    capture_parts = _parts(results["capture"])
    text = capture_parts[0].text
    assert text is not None
    capture = _CaptureResult.model_validate_json(text).capture
    assert capture.path.endswith(".png")
    assert capture.width > 0 and capture.height > 0 and capture.size > 0
    [model_image] = [part for part in capture_parts if part.kind == "image"]
    assert model_image.model_file_id and model_image.media_type == "image/jpeg"
    assert results["inspect"].status == "completed"
    inspection = results["inspect"].output
    assert isinstance(inspection, str)
    # exec_command wraps the actual stdout in its normal bounded process report.
    lines = [line for line in inspection.splitlines() if line.startswith('{"size":')]
    [evidence_line] = lines
    original = _OriginalEvidence.model_validate_json(evidence_line)
    assert original.png and original.size == capture.size
    [attachment] = [
        part for part in _parts(results["publish"]) if part.type == "attachment"
    ]
    assert attachment.attachment_id and attachment.uri
    assert attachment.uri.startswith("exchange://")
    assert attachment.media_type == "image/png" and attachment.size == capture.size
    downloaded = download_fixture_exchange_file(
        server_url=azents_public_server_url,
        access_token=token,
        attachment_id=attachment.attachment_id,
        storage_endpoint_url=azents_browser_s3_endpoint_url,
    )
    assert downloaded.startswith(b"\x89PNG\r\n\x1a\n")
    assert len(downloaded) == original.size
    assert hashlib.sha256(downloaded).hexdigest() == original.sha256
    assert downloaded[12:16] == b"IHDR"
    assert struct.unpack(">II", downloaded[16:24]) == (capture.width, capture.height)
    journal = requests.get(
        f"{openai_proxy_url}/v1/_browser_files_requests",
        timeout=10,
    )
    journal.raise_for_status()
    observations = TypeAdapter(list[_ModelEvidence]).validate_python(journal.json())
    assert any(
        _PREFIX + "capture" in observation.completed_calls
        and observation.model_image_count > 0
        and observation.model_images_are_data
        for observation in observations
    )
