"""Interactive Runtime Terminal product E2E journeys."""

from __future__ import annotations

import json
import re
import struct
import time
from dataclasses import dataclass
from typing import Annotated, Callable, Literal, NamedTuple
from urllib.parse import quote

import azentsadminclient
import azentspublicclient
import requests
from azentspublicclient.api.agent_runtime_v1_api import AgentRuntimeV1Api
from azentspublicclient.api.agent_v1_api import AgentV1Api
from azentspublicclient.api.llm_provider_integration_v1_api import (
    LLMProviderIntegrationV1Api,
)
from azentspublicclient.api.terminal_v1_api import TerminalV1Api
from azentspublicclient.api.workspace_v1_api import WorkspaceV1Api
from azentspublicclient.models.agent_create_request import AgentCreateRequest
from azentspublicclient.models.agent_runtime_capability import AgentRuntimeCapability
from azentspublicclient.models.agent_runtime_response import AgentRuntimeResponse
from azentspublicclient.models.agent_session_response import AgentSessionResponse
from azentspublicclient.models.agent_type import AgentType
from azentspublicclient.models.agent_workspace_stat_response import (
    AgentWorkspaceStatResponse,
)
from azentspublicclient.models.api_key_secrets import ApiKeySecrets
from azentspublicclient.models.create_workspace_request import CreateWorkspaceRequest
from azentspublicclient.models.llm_provider import LLMProvider
from azentspublicclient.models.llm_provider_integration_create_request import (
    LLMProviderIntegrationCreateRequest,
)
from azentspublicclient.models.project_browser_manifest_response import (
    ProjectBrowserManifestResponse,
)
from azentspublicclient.models.runtime_terminal_lifecycle import (
    RuntimeTerminalLifecycle,
)
from azentspublicclient.models.runtime_terminal_projection_response import (
    RuntimeTerminalProjectionResponse,
)
from azentspublicclient.models.runtime_terminal_reason_code import (
    RuntimeTerminalReasonCode,
)
from azentspublicclient.models.runtime_terminal_ticket_status import (
    RuntimeTerminalTicketStatus,
)
from azentspublicclient.models.secrets import Secrets
from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, ValidationError
from testcontainers.core.container import DockerContainer
from websockets.exceptions import ConnectionClosed
from websockets.sync.client import ClientConnection
from websockets.sync.client import connect as ws_connect
from websockets.typing import Origin, Subprotocol

from support.runtime_profiles import create_workspace_runtime_profile
from support.terminal_output_ack import TerminalOutputAcknowledgements
from support.utils import (
    authenticate_user,
    model_selection_from_first_candidate,
    single_candidate_model_options,
    unique,
)

_RUNTIME_PROVIDER_ID = "system-docker"
_SUBPROTOCOL = "azents.terminal.v1"
_MAIN_WEB_ORIGIN = "https://azents-web-gateway:8443"
_FRAME_HEADER = struct.Struct(">BBQ")


class _TerminalControlModel(BaseModel):
    """Closed server control shape mirrored from the canonical Terminal API."""

    model_config = ConfigDict(strict=True, extra="forbid", hide_input_in_errors=True)


class _AcceptedControl(_TerminalControlModel):
    type: Literal["accepted"]
    terminal_id: str
    lifecycle: RuntimeTerminalLifecycle
    attachment_generation: int = Field(ge=1)
    desired_generation: int = Field(ge=1)
    runner_generation: str
    shell_label: str
    working_directory_display: str
    next_input_sequence: int = Field(ge=1)
    replay_min_sequence: int = Field(ge=0)
    replay_max_sequence: int = Field(ge=0)
    replay_truncated: bool


class _ReplayBeginControl(_TerminalControlModel):
    type: Literal["replay_begin"]
    minimum_sequence: int = Field(ge=0)
    maximum_sequence: int = Field(ge=0)


class _ReplayTruncatedControl(_TerminalControlModel):
    type: Literal["replay_truncated"]
    minimum_sequence: int = Field(ge=0)


class _ReplayEndControl(_TerminalControlModel):
    type: Literal["replay_end"]
    maximum_sequence: int = Field(ge=0)


class _InputAckControl(_TerminalControlModel):
    type: Literal["input_ack"]
    sequence: int = Field(ge=1)


class _StatusControl(_TerminalControlModel):
    type: Literal["status"]
    lifecycle: RuntimeTerminalLifecycle
    reason: str | None


class _ExitControl(_TerminalControlModel):
    type: Literal["exit"]
    reason: str
    exit_code: int | None


class _RevokedControl(_TerminalControlModel):
    type: Literal["revoked"]
    reason_code: RuntimeTerminalReasonCode


class _ErrorControl(_TerminalControlModel):
    type: Literal["error"]
    code: str


class _HeartbeatAckControl(_TerminalControlModel):
    type: Literal["heartbeat_ack"]
    sequence: int = Field(ge=1)


_TerminalControl = (
    _AcceptedControl
    | _ReplayBeginControl
    | _ReplayTruncatedControl
    | _ReplayEndControl
    | _InputAckControl
    | _StatusControl
    | _ExitControl
    | _RevokedControl
    | _ErrorControl
    | _HeartbeatAckControl
)
_TERMINAL_CONTROL = TypeAdapter(
    Annotated[_TerminalControl, Field(discriminator="type")]
)


class _PreparationError(BaseModel):
    """Typed HTTP error detail; unrelated response metadata is ignored."""

    model_config = ConfigDict(strict=True, extra="ignore")
    detail: str


@dataclass(frozen=True)
class _TerminalWorkspace:
    """Product-created authority for one Terminal journey."""

    token: str
    handle: str
    agent_id: str
    session_id: str


@dataclass(frozen=True)
class _AcceptedTerminal:
    """Content-free accepted Terminal attachment evidence."""

    terminal_id: str
    attachment_generation: int
    working_directory: str
    next_input_sequence: int
    replay_maximum_sequence: int


class _DecodedOutputFrame(NamedTuple):
    """Decoded ordered Terminal output frame."""

    sequence: int
    data: bytes


def _headers(token: str) -> dict[str, str]:
    """Return bearer authentication headers."""
    return {"Authorization": f"Bearer {token}"}


def _response_payload[Payload: BaseModel](
    response: requests.Response, model: type[Payload], *, label: str
) -> Payload:
    """Decode one REST observation through its operation-specific API model."""
    try:
        return model.model_validate_json(response.text, strict=True)
    except ValidationError as exc:
        raise AssertionError(f"{label} payload is invalid") from exc


def _primary_session_id(*, server_url: str, token: str, agent_id: str) -> str:
    """Return the Agent Team primary Session ID."""
    response = requests.get(
        f"{server_url}/chat/v1/agents/{agent_id}/team-primary-session",
        headers=_headers(token),
        timeout=10,
    )
    response.raise_for_status()
    return _response_payload(
        response, AgentSessionResponse, label="Team primary Session"
    ).id


def _prepare_session_folder(
    *,
    server_url: str,
    token: str,
    agent_id: str,
    session_id: str,
) -> None:
    """Request product-owned Session working-folder preparation."""
    response = requests.post(
        (
            f"{server_url}/chat/v1/agents/{agent_id}/sessions/{session_id}"
            "/workspace/session-folder/prepare"
        ),
        headers={**_headers(token), "Content-Type": "application/json"},
        json={"client_request_id": f"runtime-terminal-prepare-{unique()}"},
        timeout=10,
    )
    response.raise_for_status()


def _wait_session_folder_ready(
    *,
    server_url: str,
    token: str,
    agent_id: str,
    session_id: str,
    deadline: float,
) -> None:
    """Wait until Runner-backed stat proves the bound Session folder exists."""
    manifest_path = (
        f"/chat/v1/agents/{agent_id}/sessions/{session_id}"
        "/workspace/project-browser-manifest"
    )
    stat_path = f"/chat/v1/agents/{agent_id}/workspace/stat"
    last_observation: object = None
    session_folder_path: str | None = None
    while time.monotonic() < deadline:
        if session_folder_path is None:
            manifest_response = requests.get(
                f"{server_url}{manifest_path}",
                headers=_headers(token),
                timeout=10,
            )
            if not manifest_response.ok:
                manifest_error = _response_payload(
                    manifest_response,
                    _PreparationError,
                    label="Session Project browser manifest error",
                )
                last_observation = {
                    "status_code": manifest_response.status_code,
                    "body": manifest_error,
                }
                if not (
                    manifest_response.status_code == 400
                    and manifest_error.detail
                    == "Session working-folder binding is unavailable."
                ):
                    manifest_response.raise_for_status()
                time.sleep(0.5)
                continue
            manifest = _response_payload(
                manifest_response,
                ProjectBrowserManifestResponse,
                label="Session Project browser manifest",
            )
            session_paths = [
                entry.path
                for entry in manifest.entries
                if entry.source.type == "session_folder"
            ]
            if len(session_paths) != 1:
                raise AssertionError(
                    f"Session manifest omitted one Session folder: {manifest!r}"
                )
            session_folder_path = session_paths[0]
        response = requests.get(
            f"{server_url}{stat_path}",
            headers=_headers(token),
            params={"path": session_folder_path},
            timeout=10,
        )
        if response.status_code == 404:
            last_observation = {
                "status_code": response.status_code,
                "body": response.text,
            }
            time.sleep(0.5)
            continue
        response.raise_for_status()
        stat = _response_payload(
            response,
            AgentWorkspaceStatResponse,
            label="Session working-folder stat",
        )
        last_observation = stat
        if stat.path == session_folder_path and stat.kind == "directory":
            return
        time.sleep(0.5)
    raise AssertionError(
        "Runner-backed Session working folder did not become ready: "
        f"{last_observation!r}"
    )


def _prepare_terminal_session(
    *,
    public_api_client: azentspublicclient.ApiClient,
    workspace: _TerminalWorkspace,
    server_url: str,
) -> None:
    """Prepare and observe authoritative Session working-folder readiness."""
    _prepare_session_folder(
        server_url=server_url,
        token=workspace.token,
        agent_id=workspace.agent_id,
        session_id=workspace.session_id,
    )
    deadline = time.monotonic() + 120
    _wait_session_folder_ready(
        server_url=server_url,
        token=workspace.token,
        agent_id=workspace.agent_id,
        session_id=workspace.session_id,
        deadline=deadline,
    )
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise AssertionError(
            "Terminal readiness deadline expired after Session folder preparation"
        )
    _wait_terminal_projection(
        public_api_client=public_api_client,
        workspace=workspace,
        predicate=lambda projection: projection.can_open_or_attach,
        message="Terminal did not become openable after Session folder preparation",
        timeout=remaining,
    )


def _create_workspace(
    *,
    public_api_client: azentspublicclient.ApiClient,
    admin_api_client: azentsadminclient.ApiClient,
    server_url: str,
) -> _TerminalWorkspace:
    """Create Terminal E2E state through Public and Admin APIs only."""
    suffix = unique()
    token, _, _ = authenticate_user(
        public_api_client,
        admin_api_client,
        email=f"runtime-terminal-{suffix}@example.com",
    )
    handle = f"runtime-terminal-{suffix}"
    headers = _headers(token)
    WorkspaceV1Api(public_api_client).workspace_v1_create_workspace(
        CreateWorkspaceRequest(
            workspace_name=f"Runtime Terminal {suffix}",
            workspace_handle=handle,
            owner_name=f"Owner {suffix}",
        ),
        _headers=headers,
    )
    integration = LLMProviderIntegrationV1Api(
        public_api_client
    ).llm_provider_integration_v1_create_integration(
        handle=handle,
        llm_provider_integration_create_request=LLMProviderIntegrationCreateRequest(
            provider=LLMProvider.OPENAI,
            name="__testenv_model_listing:deterministic-success",
            secrets=Secrets(ApiKeySecrets(api_key="sk-runtime-terminal")),
        ),
        _headers=headers,
    )
    model_selection = model_selection_from_first_candidate(
        server_url,
        token,
        handle,
        integration.id,
    )
    runtime_profile_id = create_workspace_runtime_profile(
        public_api_client,
        token=token,
        workspace_handle=handle,
        provider_id=_RUNTIME_PROVIDER_ID,
    )
    agent = AgentV1Api(public_api_client).agent_v1_create_agent(
        handle=handle,
        agent_create_request=AgentCreateRequest(
            name=f"Runtime Terminal Agent {suffix}",
            selectable_model_options=single_candidate_model_options(model_selection),
            main_model_label="default",
            lightweight_model_label="default",
            type=AgentType.PUBLIC,
            runtime_profile_id=runtime_profile_id,
        ),
        _headers=headers,
    )
    assert agent.runtime_capability is AgentRuntimeCapability.MANAGED
    return _TerminalWorkspace(
        token=token,
        handle=handle,
        agent_id=agent.id,
        session_id=_primary_session_id(
            server_url=server_url,
            token=token,
            agent_id=agent.id,
        ),
    )


def _wait_runtime(
    *,
    runtime_api: AgentRuntimeV1Api,
    workspace: _TerminalWorkspace,
    predicate: Callable[[AgentRuntimeResponse], bool],
    message: str,
    timeout: float = 180,
) -> AgentRuntimeResponse:
    """Wait for one authoritative Runtime projection."""
    deadline = time.monotonic() + timeout
    last_runtime: AgentRuntimeResponse | None = None
    while time.monotonic() < deadline:
        last_runtime = runtime_api.agent_runtime_v1_get_agent_runtime(
            agent_id=workspace.agent_id,
            handle=workspace.handle,
            _headers=_headers(workspace.token),
        )
        if predicate(last_runtime):
            return last_runtime
        time.sleep(1)
    raise AssertionError(f"{message}: {last_runtime!r}")


def _start_runtime(
    *,
    public_api_client: azentspublicclient.ApiClient,
    workspace: _TerminalWorkspace,
    server_url: str,
) -> AgentRuntimeV1Api:
    """Start the managed Runtime and bind the Session working folder."""
    runtime_api = AgentRuntimeV1Api(public_api_client)
    runtime_api.agent_runtime_v1_start_agent_runtime(
        agent_id=workspace.agent_id,
        handle=workspace.handle,
        _headers=_headers(workspace.token),
    )
    _wait_runtime(
        runtime_api=runtime_api,
        workspace=workspace,
        predicate=lambda runtime: (
            runtime.lifecycle is not None
            and runtime.lifecycle.availability == "ready"
            and runtime.lifecycle.runner.state == "ready"
            and runtime.actions.use_runner
        ),
        message="Runtime Runner did not become ready",
    )
    _prepare_terminal_session(
        public_api_client=public_api_client,
        workspace=workspace,
        server_url=server_url,
    )
    return runtime_api


def _wait_terminal_projection(
    *,
    public_api_client: azentspublicclient.ApiClient,
    workspace: _TerminalWorkspace,
    predicate: Callable[[RuntimeTerminalProjectionResponse], bool],
    message: str,
    timeout: float = 30,
) -> RuntimeTerminalProjectionResponse:
    """Wait for one authoritative Terminal projection."""
    api = TerminalV1Api(public_api_client)
    deadline = time.monotonic() + timeout
    last_projection: RuntimeTerminalProjectionResponse | None = None
    while time.monotonic() < deadline:
        last_projection = api.terminal_v1_get_terminal_projection(
            handle=workspace.handle,
            agent_id=workspace.agent_id,
            session_id=workspace.session_id,
            _headers=_headers(workspace.token),
        )
        if predicate(last_projection):
            return last_projection
        time.sleep(0.5)
    raise AssertionError(f"{message}: {last_projection!r}")


def _websocket_url(
    *,
    server_url: str,
    workspace: _TerminalWorkspace,
    ticket: str,
) -> str:
    """Build the resource-bound Terminal WebSocket URL."""
    scheme = "wss" if server_url.startswith("https://") else "ws"
    authority = server_url.split("://", 1)[1].rstrip("/")
    return (
        f"{scheme}://{authority}/terminal/v1/workspaces/{workspace.handle}"
        f"/agents/{workspace.agent_id}/sessions/{workspace.session_id}/ws"
        f"?ticket={quote(ticket, safe='')}"
    )


class _TerminalSocket:
    """Typed synchronous client for the Public Terminal wire contract."""

    def __init__(
        self,
        connection: ClientConnection,
        accepted: _AcceptedTerminal,
        *,
        output_sequence: int,
    ) -> None:
        self.connection = connection
        self.accepted = accepted
        self.input_sequence = accepted.next_input_sequence
        self.resize_sequence = 0
        self.output_sequence = output_sequence
        self.output = bytearray()
        self.output_acks = TerminalOutputAcknowledgements(
            output_sequence, time.monotonic
        )

    @classmethod
    def connect(
        cls,
        *,
        public_api_client: azentspublicclient.ApiClient,
        workspace: _TerminalWorkspace,
        server_url: str,
        origin: str,
        last_output_sequence: int | None = None,
    ) -> "_TerminalSocket":
        """Issue a one-time ticket and complete the attach/replay handshake."""
        terminal_api = TerminalV1Api(public_api_client)
        issued = terminal_api.terminal_v1_issue_terminal_ticket(
            handle=workspace.handle,
            agent_id=workspace.agent_id,
            session_id=workspace.session_id,
            _headers=_headers(workspace.token),
        )
        assert issued.status is RuntimeTerminalTicketStatus.ISSUED
        assert issued.ticket is not None
        connection = ws_connect(
            _websocket_url(
                server_url=server_url,
                workspace=workspace,
                ticket=issued.ticket,
            ),
            origin=Origin(origin.rstrip("/")),
            subprotocols=[Subprotocol(_SUBPROTOCOL)],
            compression=None,
            ping_interval=None,
        )
        connection.send(
            json.dumps(
                {
                    "type": "attach",
                    "columns": 80,
                    "rows": 24,
                    "last_output_sequence": last_output_sequence,
                }
            )
        )
        accepted: _AcceptedTerminal | None = None
        replay_maximum = 0
        output_sequence = 0
        replay_acks = TerminalOutputAcknowledgements(0, time.monotonic)
        while True:
            message = connection.recv(timeout=20)
            if isinstance(message, bytes):
                decoded = _decode_output_frame(message)
                output_sequence = max(output_sequence, decoded.sequence)
                acknowledge = replay_acks.observe(decoded.sequence, len(decoded.data))
                if acknowledge is not None:
                    connection.send(
                        json.dumps({"type": "output_ack", "sequence": acknowledge})
                    )
                continue
            control = _control(message)
            if isinstance(control, _AcceptedControl):
                replay_maximum = control.replay_max_sequence
                accepted = _AcceptedTerminal(
                    terminal_id=control.terminal_id,
                    attachment_generation=control.attachment_generation,
                    working_directory=control.working_directory_display,
                    next_input_sequence=control.next_input_sequence,
                    replay_maximum_sequence=replay_maximum,
                )
            elif isinstance(control, _ReplayEndControl):
                assert accepted is not None
                assert control.maximum_sequence == replay_maximum
                connection.send(
                    json.dumps(
                        {
                            "type": "output_ack",
                            "sequence": max(output_sequence, replay_maximum),
                        }
                    )
                )
                return cls(
                    connection,
                    accepted,
                    output_sequence=max(output_sequence, replay_maximum),
                )

    def close(self) -> None:
        """Close the browser attachment without terminating the PTY."""
        self._flush_output_ack()
        self.connection.close()

    def send(self, data: bytes) -> None:
        """Send one ordered opaque input frame."""
        self.connection.send(_FRAME_HEADER.pack(1, 1, self.input_sequence) + data)
        self.input_sequence += 1

    def resize(self, *, columns: int, rows: int) -> None:
        """Send one ordered resize control."""
        self.resize_sequence += 1
        self.connection.send(
            json.dumps(
                {
                    "type": "resize",
                    "sequence": self.resize_sequence,
                    "columns": columns,
                    "rows": rows,
                }
            )
        )

    def terminate(self) -> _ExitControl:
        """Terminate the live PTY and return its exit control."""
        self._flush_output_ack()
        self.connection.send(json.dumps({"type": "terminate"}))
        control = self.wait_for_control("exit", timeout=30)
        assert isinstance(control, _ExitControl)
        return control

    def wait_for_control(
        self, control_type: str, *, timeout: float
    ) -> _TerminalControl:
        """Wait for one server control while acknowledging output."""
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            try:
                message = self._receive(timeout=max(0.1, deadline - time.monotonic()))
            except ConnectionClosed as exc:
                raise AssertionError(
                    f"Terminal closed before {control_type!r}: {exc!r}"
                ) from exc
            if isinstance(message, bytes):
                self._accept_output(message)
                continue
            control = _control(message)
            if control.type == control_type:
                return control
        raise AssertionError(f"Terminal control was not observed: {control_type}")

    def wait_for_invalidation(
        self, *, timeout: float
    ) -> _RevokedControl | _ExitControl | None:
        """Wait for a bounded revocation/exit control or socket close."""
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            try:
                message = self._receive(timeout=max(0.1, deadline - time.monotonic()))
            except ConnectionClosed:
                return None
            if isinstance(message, bytes):
                self._accept_output(message)
                continue
            control = _control(message)
            if isinstance(control, _RevokedControl | _ExitControl):
                return control
        raise AssertionError("Terminal was not invalidated within the lifecycle bound")

    def wait_for_output(self, marker: bytes, *, timeout: float = 30) -> bytes:
        """Wait until ordered PTY output includes the requested marker."""
        deadline = time.monotonic() + timeout
        start = len(self.output)
        while time.monotonic() < deadline:
            if marker in self.output[start:]:
                self._flush_output_ack()
                return bytes(self.output[start:])
            message = self._receive(timeout=max(0.1, deadline - time.monotonic()))
            if isinstance(message, bytes):
                self._accept_output(message)
                continue
            control = _control(message)
            if isinstance(control, _ExitControl | _RevokedControl | _ErrorControl):
                raise AssertionError(
                    f"Terminal ended before output marker {marker!r}: {control!r}"
                )
        raise AssertionError(
            f"Terminal output marker was not observed: {marker!r}; "
            f"tail={bytes(self.output[-4096:])!r}"
        )

    def command(self, command: str, marker: str) -> bytes:
        """Run one shell command and return output through a unique marker."""
        encoded_marker = marker.encode()
        split_at = max(1, len(marker) // 2)
        marker_prefix = marker[:split_at]
        marker_suffix = marker[split_at:]
        self.send(
            (f"{command}; printf '\\n{marker_prefix}''{marker_suffix}\\n'\n").encode()
        )
        return self.wait_for_output(encoded_marker)

    def _accept_output(self, frame: bytes) -> None:
        decoded = _decode_output_frame(frame)
        assert decoded.sequence > self.output_sequence, (
            decoded.sequence,
            self.output_sequence,
        )
        self.output_sequence = decoded.sequence
        self.output.extend(decoded.data)
        sequence = self.output_acks.observe(decoded.sequence, len(decoded.data))
        if sequence is not None:
            self._send_output_ack(sequence)

    def _send_output_ack(self, sequence: int) -> None:
        try:
            self.connection.send(
                json.dumps({"type": "output_ack", "sequence": sequence})
            )
        except ConnectionClosed:
            return

    def _flush_output_ack(self) -> None:
        sequence = self.output_acks.flush()
        if sequence is not None:
            self._send_output_ack(sequence)

    def _receive(self, *, timeout: float) -> str | bytes:
        """Flush cumulative ACKs while waiting, without delaying input or sleeping."""
        deadline = time.monotonic() + timeout
        while True:
            now = time.monotonic()
            ack_deadline = self.output_acks.deadline
            if ack_deadline is not None and now >= ack_deadline:
                self._flush_output_ack()
                continue
            remaining = deadline - now
            if remaining <= 0:
                raise TimeoutError("Terminal receive deadline expired")
            if ack_deadline is not None:
                remaining = min(remaining, ack_deadline - now)
            try:
                return self.connection.recv(timeout=remaining)
            except TimeoutError:
                if ack_deadline is None or time.monotonic() < ack_deadline:
                    raise
                self._flush_output_ack()


def _control(message: str) -> _TerminalControl:
    """Validate every canonical server control before interpreting its fields."""
    try:
        return _TERMINAL_CONTROL.validate_json(message, strict=True)
    except ValidationError as exc:
        raise AssertionError("Invalid Terminal control payload") from exc


def _decode_output_frame(frame: bytes) -> _DecodedOutputFrame:
    """Decode one versioned ordered Terminal output frame."""
    if len(frame) <= _FRAME_HEADER.size:
        raise AssertionError(f"Truncated Terminal output frame: {frame!r}")
    version, frame_type, sequence = _FRAME_HEADER.unpack_from(frame)
    assert version == 1
    assert frame_type == 2
    assert sequence > 0
    return _DecodedOutputFrame(
        sequence=sequence,
        data=frame[_FRAME_HEADER.size :],
    )


def _marked_value(output: bytes, label: str) -> str:
    """Extract one ASCII-delimited value from PTY output."""
    match = re.search(rb"__" + label.encode() + rb"__(.*?)__", output, re.DOTALL)
    if match is None:
        raise AssertionError(f"Marked value {label!r} missing from output: {output!r}")
    return match.group(1).decode(errors="replace").strip()


def test_runtime_terminal_protocol_reconnect_resize_ctrl_c_and_terminate(
    public_api_client: azentspublicclient.ApiClient,
    admin_api_client: azentsadminclient.ApiClient,
    azents_public_server_url: str,
    azents_runtime_provider_docker_container: DockerContainer,
) -> None:
    """Prove the real Runner PTY wire, reattachment, and explicit termination."""
    del azents_runtime_provider_docker_container
    workspace = _create_workspace(
        public_api_client=public_api_client,
        admin_api_client=admin_api_client,
        server_url=azents_public_server_url,
    )
    _start_runtime(
        public_api_client=public_api_client,
        workspace=workspace,
        server_url=azents_public_server_url,
    )
    terminal = _TerminalSocket.connect(
        public_api_client=public_api_client,
        workspace=workspace,
        server_url=azents_public_server_url,
        origin=_MAIN_WEB_ORIGIN,
    )

    pwd_output = terminal.command("printf '__P''WD__%s__' \"$PWD\"", "PWD_DONE")
    assert _marked_value(pwd_output, "PWD") == terminal.accepted.working_directory

    utf8_output = terminal.command("printf '__UT''F8__안녕 Terminal__'", "UTF8_DONE")
    assert _marked_value(utf8_output, "UTF8") == "안녕 Terminal"

    pid_output = terminal.command("printf '__P''ID__%s__' \"$$\"", "PID_DONE")
    shell_pid = _marked_value(pid_output, "PID")
    assert shell_pid.isdigit()

    terminal.resize(columns=100, rows=41)
    size_output = terminal.command(
        "printf '__SI''ZE__%s__' \"$(stty size)\"", "SIZE_DONE"
    )
    assert _marked_value(size_output, "SIZE") == "41 100"

    terminal.send(b"sleep 30\n")
    terminal.wait_for_output(b"sleep 30")
    terminal.send(b"\x03")
    alive_output = terminal.command("printf '__AL''IVE__yes__'", "ALIVE_DONE")
    assert _marked_value(alive_output, "ALIVE") == "yes"

    terminal_id = terminal.accepted.terminal_id
    output_sequence = terminal.output_sequence
    terminal.close()
    reattached = _TerminalSocket.connect(
        public_api_client=public_api_client,
        workspace=workspace,
        server_url=azents_public_server_url,
        origin=_MAIN_WEB_ORIGIN,
        last_output_sequence=output_sequence,
    )
    assert reattached.accepted.terminal_id == terminal_id
    assert (
        reattached.accepted.next_input_sequence > terminal.accepted.next_input_sequence
    )
    assert reattached.accepted.replay_maximum_sequence >= output_sequence
    reattached_pid = reattached.command(
        "printf '__P''ID__%s__' \"$$\"",
        "REATTACHED_PID_DONE",
    )
    assert _marked_value(reattached_pid, "PID") == shell_pid

    terminal_api = TerminalV1Api(public_api_client)
    try:
        exit_control = reattached.terminate()
    except TimeoutError as exc:
        timed_out_projection = terminal_api.terminal_v1_get_terminal_projection(
            handle=workspace.handle,
            agent_id=workspace.agent_id,
            session_id=workspace.session_id,
            _headers=_headers(workspace.token),
        )
        raise AssertionError(
            f"Terminal exit control timed out; projection={timed_out_projection!r}"
        ) from exc
    assert exit_control.reason == "caller"
    projection = terminal_api.terminal_v1_get_terminal_projection(
        handle=workspace.handle,
        agent_id=workspace.agent_id,
        session_id=workspace.session_id,
        _headers=_headers(workspace.token),
    )
    deadline = time.monotonic() + 30
    while projection.state != "ended" and time.monotonic() < deadline:
        time.sleep(0.5)
        projection = terminal_api.terminal_v1_get_terminal_projection(
            handle=workspace.handle,
            agent_id=workspace.agent_id,
            session_id=workspace.session_id,
            _headers=_headers(workspace.token),
        )
    assert projection.state == "ended"
    assert projection.terminal is not None
    assert projection.terminal.terminal_id == terminal_id
    assert projection.terminal.input_bytes > 0
    assert projection.terminal.output_bytes > 0


def test_runtime_terminal_runtime_lifecycle_priority(
    public_api_client: azentspublicclient.ApiClient,
    admin_api_client: azentsadminclient.ApiClient,
    azents_public_server_url: str,
    azents_runtime_provider_docker_container: DockerContainer,
) -> None:
    """Prove Runtime stop priority and explicit restart with fresh authority."""
    del azents_runtime_provider_docker_container
    workspace = _create_workspace(
        public_api_client=public_api_client,
        admin_api_client=admin_api_client,
        server_url=azents_public_server_url,
    )
    runtime_api = _start_runtime(
        public_api_client=public_api_client,
        workspace=workspace,
        server_url=azents_public_server_url,
    )
    terminal_api = TerminalV1Api(public_api_client)

    active = _TerminalSocket.connect(
        public_api_client=public_api_client,
        workspace=workspace,
        server_url=azents_public_server_url,
        origin=_MAIN_WEB_ORIGIN,
    )
    active.command("printf '__LIFE''CYCLE__ready__'", "LIFECYCLE_READY")
    before_stop = runtime_api.agent_runtime_v1_get_agent_runtime(
        agent_id=workspace.agent_id,
        handle=workspace.handle,
        _headers=_headers(workspace.token),
    )
    before_stop_lifecycle = before_stop.lifecycle
    assert before_stop_lifecycle is not None
    runtime_api.agent_runtime_v1_stop_agent_runtime(
        agent_id=workspace.agent_id,
        handle=workspace.handle,
        _headers=_headers(workspace.token),
    )
    stopped = _wait_runtime(
        runtime_api=runtime_api,
        workspace=workspace,
        predicate=lambda runtime: (
            runtime.lifecycle is not None
            and runtime.lifecycle.availability == "stopped"
            and runtime.lifecycle.desired_generation
            > before_stop_lifecycle.desired_generation
        ),
        message="Runtime stop did not converge while Terminal was active",
    )
    assert stopped.lifecycle is not None
    stopped_generation = stopped.lifecycle.desired_generation
    projection = terminal_api.terminal_v1_get_terminal_projection(
        handle=workspace.handle,
        agent_id=workspace.agent_id,
        session_id=workspace.session_id,
        _headers=_headers(workspace.token),
    )
    assert projection.state == "stopped"
    assert projection.reason_code is RuntimeTerminalReasonCode.RUNTIME_STOPPED
    invalidation = active.wait_for_invalidation(timeout=15)
    assert invalidation is None or invalidation.type in {"revoked", "exit"}

    stopped_ticket = terminal_api.terminal_v1_issue_terminal_ticket(
        handle=workspace.handle,
        agent_id=workspace.agent_id,
        session_id=workspace.session_id,
        _headers=_headers(workspace.token),
    )
    assert stopped_ticket.status is RuntimeTerminalTicketStatus.RUNTIME_STOPPED
    assert stopped_ticket.reason_code is RuntimeTerminalReasonCode.RUNTIME_STOPPED
    still_stopped = runtime_api.agent_runtime_v1_get_agent_runtime(
        agent_id=workspace.agent_id,
        handle=workspace.handle,
        _headers=_headers(workspace.token),
    )
    assert still_stopped.lifecycle is not None
    assert still_stopped.lifecycle.availability == "stopped"
    assert still_stopped.lifecycle.desired_generation == stopped_generation

    runtime_api.agent_runtime_v1_start_agent_runtime(
        agent_id=workspace.agent_id,
        handle=workspace.handle,
        _headers=_headers(workspace.token),
    )
    restarted = _wait_runtime(
        runtime_api=runtime_api,
        workspace=workspace,
        predicate=lambda runtime: (
            runtime.lifecycle is not None
            and runtime.lifecycle.availability == "ready"
            and runtime.lifecycle.runner.state == "ready"
            and runtime.lifecycle.desired_generation > stopped_generation
        ),
        message="Explicit Runtime Start did not restore Terminal authority",
    )
    assert restarted.lifecycle is not None
    resumed = _TerminalSocket.connect(
        public_api_client=public_api_client,
        workspace=workspace,
        server_url=azents_public_server_url,
        origin=_MAIN_WEB_ORIGIN,
    )
    assert resumed.accepted.terminal_id != active.accepted.terminal_id
    resumed.command("printf '__REST''ARTED__yes__'", "RESTARTED_DONE")
    resumed.terminate()
