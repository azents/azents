"""Interactive Runtime Terminal product E2E journeys."""

from __future__ import annotations

import json
import re
import shlex
import struct
import time
from dataclasses import dataclass
from typing import Callable
from urllib.parse import quote

import azentsadminclient
import azentspublicclient
import pytest
import requests
from azentsadminclient.api.runtime_provider_v1_api import RuntimeProviderV1Api
from azentsadminclient.models.runtime_infrastructure_profile_replace_request import (
    RuntimeInfrastructureProfileReplaceRequest,
)
from azentspublicclient.api.agent_runtime_v1_api import AgentRuntimeV1Api
from azentspublicclient.api.agent_v1_api import AgentV1Api
from azentspublicclient.api.llm_provider_integration_v1_api import (
    LLMProviderIntegrationV1Api,
)
from azentspublicclient.api.runtime_profile_v1_api import RuntimeProfileV1Api
from azentspublicclient.api.terminal_v1_api import TerminalV1Api
from azentspublicclient.api.workspace_user_v1_api import WorkspaceUserV1Api
from azentspublicclient.api.workspace_v1_api import WorkspaceV1Api
from azentspublicclient.exceptions import ForbiddenException
from azentspublicclient.models.agent_create_request import AgentCreateRequest
from azentspublicclient.models.agent_runtime_capability import AgentRuntimeCapability
from azentspublicclient.models.agent_runtime_response import AgentRuntimeResponse
from azentspublicclient.models.agent_type import AgentType
from azentspublicclient.models.agent_update_request import AgentUpdateRequest
from azentspublicclient.models.api_key_secrets import ApiKeySecrets
from azentspublicclient.models.create_workspace_request import CreateWorkspaceRequest
from azentspublicclient.models.llm_provider import LLMProvider
from azentspublicclient.models.llm_provider_integration_create_request import (
    LLMProviderIntegrationCreateRequest,
)
from azentspublicclient.models.runtime_terminal_denied_scope import (
    RuntimeTerminalDeniedScope,
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
from azentspublicclient.models.workspace_runtime_profile_replace_request import (
    WorkspaceRuntimeProfileReplaceRequest,
)
from docker.models.containers import Container
from pydantic import TypeAdapter, ValidationError
from testcontainers.core.container import DockerContainer
from websockets.exceptions import ConnectionClosed
from websockets.sync.client import ClientConnection
from websockets.sync.client import connect as ws_connect
from websockets.typing import Origin, Subprotocol

from support.runtime_profiles import create_workspace_runtime_profile
from support.utils import (
    authenticate_user,
    create_two_member_team_session,
    decode_docker_exec_output,
    model_selection_from_first_candidate,
    unique,
)

_RUNTIME_PROVIDER_ID = "system-docker"
_SUBPROTOCOL = "azents.terminal.v1"
_FRAME_HEADER = struct.Struct(">BBQ")
_JSON_OBJECT = TypeAdapter(dict[str, object])


@dataclass(frozen=True)
class _TerminalWorkspace:
    """Product-created authority for one Terminal journey."""

    token: str
    handle: str
    agent_id: str
    session_id: str
    runtime_profile_id: str | None
    infrastructure_profile_id: str | None


@dataclass(frozen=True)
class _AcceptedTerminal:
    """Content-free accepted Terminal attachment evidence."""

    terminal_id: str
    attachment_generation: int
    working_directory: str
    next_input_sequence: int
    replay_maximum_sequence: int


def _headers(token: str) -> dict[str, str]:
    """Return bearer authentication headers."""
    return {"Authorization": f"Bearer {token}"}


def _response_object(response: requests.Response, *, label: str) -> dict[str, object]:
    """Validate one JSON object response."""
    try:
        return _JSON_OBJECT.validate_json(response.text)
    except ValidationError as exc:
        raise AssertionError(f"{label} is not an object: {response.text!r}") from exc


def _primary_session_id(*, server_url: str, token: str, agent_id: str) -> str:
    """Return the Agent Team primary Session ID."""
    response = requests.get(
        f"{server_url}/chat/v1/agents/{agent_id}/team-primary-session",
        headers=_headers(token),
        timeout=10,
    )
    response.raise_for_status()
    session_id = _response_object(response, label="Team primary Session").get("id")
    if not isinstance(session_id, str):
        raise AssertionError(f"Team primary Session omitted id: {response.text!r}")
    return session_id


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
    _wait_terminal_projection(
        public_api_client=public_api_client,
        workspace=workspace,
        predicate=lambda projection: projection.state in {"ready", "active"},
        message="Terminal did not become ready after Session folder preparation",
        timeout=120,
    )


def _create_workspace(
    *,
    public_api_client: azentspublicclient.ApiClient,
    admin_api_client: azentsadminclient.ApiClient,
    server_url: str,
    managed_runtime: bool,
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
    runtime_profile_id = (
        create_workspace_runtime_profile(
            public_api_client,
            token=token,
            workspace_handle=handle,
            provider_id=_RUNTIME_PROVIDER_ID,
        )
        if managed_runtime
        else None
    )
    infrastructure_profile_id: str | None = None
    if runtime_profile_id is not None:
        runtime_profile = RuntimeProfileV1Api(
            public_api_client
        ).runtime_profile_v1_get_workspace_runtime_profile(
            profile_id=runtime_profile_id,
            handle=handle,
            _headers=headers,
        )
        infrastructure_profile_id = runtime_profile.infrastructure_profile_id
    agent = AgentV1Api(public_api_client).agent_v1_create_agent(
        handle=handle,
        agent_create_request=AgentCreateRequest(
            name=f"Runtime Terminal Agent {suffix}",
            model_selection=model_selection,
            lightweight_model_selection=model_selection,
            type=AgentType.PUBLIC,
            runtime_profile_id=runtime_profile_id,
        ),
        _headers=headers,
    )
    assert agent.runtime_capability == (
        AgentRuntimeCapability.MANAGED
        if managed_runtime
        else AgentRuntimeCapability.NONE
    )
    return _TerminalWorkspace(
        token=token,
        handle=handle,
        agent_id=agent.id,
        session_id=_primary_session_id(
            server_url=server_url,
            token=token,
            agent_id=agent.id,
        ),
        runtime_profile_id=runtime_profile_id,
        infrastructure_profile_id=infrastructure_profile_id,
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


def _replace_infrastructure_terminal_policy(
    *,
    admin_api_client: azentsadminclient.ApiClient,
    workspace: _TerminalWorkspace,
    terminal_enabled: bool,
) -> None:
    """Replace the selected infrastructure Profile Terminal policy."""
    profile_id = workspace.infrastructure_profile_id
    if profile_id is None:
        raise AssertionError("managed Runtime omitted infrastructure Profile")
    api = RuntimeProviderV1Api(admin_api_client)
    profile = api.runtime_provider_v1_get_container_profile(
        provider_id=_RUNTIME_PROVIDER_ID,
        profile_id=profile_id,
    )
    if profile.spec is None:
        raise AssertionError("Docker infrastructure Profile omitted its spec")
    replaced = api.runtime_provider_v1_replace_container_profile(
        provider_id=_RUNTIME_PROVIDER_ID,
        profile_id=profile_id,
        runtime_infrastructure_profile_replace_request=(
            RuntimeInfrastructureProfileReplaceRequest(
                expected_version=profile.version,
                display_name=profile.display_name,
                description=profile.description,
                lifecycle=profile.lifecycle,
                spec=profile.spec,
                terminal_enabled=terminal_enabled,
            )
        ),
    )
    assert replaced.terminal_enabled is terminal_enabled


def _replace_workspace_terminal_policy(
    *,
    public_api_client: azentspublicclient.ApiClient,
    workspace: _TerminalWorkspace,
    terminal_enabled: bool,
) -> None:
    """Replace the selected Workspace Runtime Profile Terminal policy."""
    profile_id = workspace.runtime_profile_id
    if profile_id is None:
        raise AssertionError("managed Runtime omitted Workspace Runtime Profile")
    api = RuntimeProfileV1Api(public_api_client)
    profile = api.runtime_profile_v1_get_workspace_runtime_profile(
        profile_id=profile_id,
        handle=workspace.handle,
        _headers=_headers(workspace.token),
    )
    replaced = api.runtime_profile_v1_replace_workspace_runtime_profile(
        profile_id=profile_id,
        handle=workspace.handle,
        workspace_runtime_profile_replace_request=(
            WorkspaceRuntimeProfileReplaceRequest(
                expected_version=profile.version,
                infrastructure_profile_id=profile.infrastructure_profile_id,
                display_name=profile.display_name,
                description=profile.description,
                lifecycle=profile.lifecycle,
                policy=profile.policy,
                terminal_enabled=terminal_enabled,
            )
        ),
        _headers=_headers(workspace.token),
    )
    assert replaced.terminal_enabled is terminal_enabled


def _runtime_container(
    provider_container: DockerContainer,
    *,
    agent_id: str,
) -> Container:
    """Return the one Docker Runtime container for an Agent."""
    client = provider_container.get_wrapped_container().client
    if client is None:
        raise AssertionError("Docker Runtime Provider client is unavailable")
    containers = client.containers.list(
        all=True,
        filters={"label": f"azents/agent-id={agent_id}"},
    )
    if len(containers) != 1:
        names = [container.name for container in containers]
        raise AssertionError(
            f"expected one Runtime container for {agent_id}, found {names!r}"
        )
    return containers[0]


def _runtime_exec(container: Container, command: str) -> str:
    """Run one bounded Runtime-container command and return its output."""
    result = container.exec_run(["sh", "-lc", command])
    output = decode_docker_exec_output(result.output)
    if result.exit_code != 0:
        raise AssertionError(
            f"Runtime command failed with exit {result.exit_code}: {command}\n{output}"
        )
    return output


def _wait_runtime_log(
    container: Container,
    *,
    path: str,
    marker: str,
    timeout: float = 60,
) -> None:
    """Wait for one explicit Runner log marker inside the Runtime container."""
    deadline = time.monotonic() + timeout
    latest = ""
    quoted_path = shlex.quote(path)
    while time.monotonic() < deadline:
        latest = _runtime_exec(
            container,
            f"if [ -f {quoted_path} ]; then cat {quoted_path}; fi",
        )
        if marker in latest:
            return
        time.sleep(0.5)
    raise AssertionError(
        f"Runtime log marker {marker!r} was not observed: {latest[-4096:]!r}"
    )


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
        while True:
            message = connection.recv(timeout=20)
            if isinstance(message, bytes):
                sequence, data = _decode_output_frame(message)
                output_sequence = max(output_sequence, sequence)
                if data:
                    connection.send(
                        json.dumps({"type": "output_ack", "sequence": sequence})
                    )
                continue
            control = _control(message)
            if control.get("type") == "accepted":
                terminal_id = control.get("terminal_id")
                attachment_generation = control.get("attachment_generation")
                working_directory = control.get("working_directory_display")
                next_input_sequence = control.get("next_input_sequence")
                replay_maximum_raw = control.get("replay_max_sequence")
                if not (
                    isinstance(terminal_id, str)
                    and isinstance(attachment_generation, int)
                    and isinstance(working_directory, str)
                    and isinstance(next_input_sequence, int)
                    and isinstance(replay_maximum_raw, int)
                ):
                    raise AssertionError(f"Invalid accepted control: {control!r}")
                replay_maximum = replay_maximum_raw
                accepted = _AcceptedTerminal(
                    terminal_id=terminal_id,
                    attachment_generation=attachment_generation,
                    working_directory=working_directory,
                    next_input_sequence=next_input_sequence,
                    replay_maximum_sequence=replay_maximum,
                )
            elif control.get("type") == "replay_end":
                assert accepted is not None
                assert control.get("maximum_sequence") == replay_maximum
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

    def terminate(self) -> dict[str, object]:
        """Terminate the live PTY and return its exit control."""
        self.connection.send(json.dumps({"type": "terminate"}))
        return self.wait_for_control("exit", timeout=30)

    def wait_for_control(
        self, control_type: str, *, timeout: float
    ) -> dict[str, object]:
        """Wait for one server control while acknowledging output."""
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            try:
                message = self.connection.recv(
                    timeout=max(0.1, deadline - time.monotonic())
                )
            except ConnectionClosed as exc:
                raise AssertionError(
                    f"Terminal closed before {control_type!r}: {exc!r}"
                ) from exc
            if isinstance(message, bytes):
                self._accept_output(message)
                continue
            control = _control(message)
            if control.get("type") == control_type:
                return control
        raise AssertionError(f"Terminal control was not observed: {control_type}")

    def wait_for_invalidation(self, *, timeout: float) -> dict[str, object] | None:
        """Wait for a bounded revocation/exit control or socket close."""
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            try:
                message = self.connection.recv(
                    timeout=max(0.1, deadline - time.monotonic())
                )
            except ConnectionClosed:
                return None
            if isinstance(message, bytes):
                self._accept_output(message)
                continue
            control = _control(message)
            if control.get("type") in {"revoked", "exit"}:
                return control
        raise AssertionError("Terminal was not invalidated within the lifecycle bound")

    def wait_for_output(self, marker: bytes, *, timeout: float = 30) -> bytes:
        """Wait until ordered PTY output includes the requested marker."""
        deadline = time.monotonic() + timeout
        start = len(self.output)
        while time.monotonic() < deadline:
            if marker in self.output[start:]:
                return bytes(self.output[start:])
            message = self.connection.recv(
                timeout=max(0.1, deadline - time.monotonic())
            )
            if isinstance(message, bytes):
                self._accept_output(message)
                continue
            control = _control(message)
            if control.get("type") in {"exit", "revoked", "error"}:
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
        sequence, data = _decode_output_frame(frame)
        assert sequence > self.output_sequence, (sequence, self.output_sequence)
        self.output_sequence = sequence
        self.output.extend(data)
        self.connection.send(json.dumps({"type": "output_ack", "sequence": sequence}))


def _control(message: str) -> dict[str, object]:
    """Validate one server JSON control object."""
    try:
        return _JSON_OBJECT.validate_json(message)
    except ValidationError as exc:
        raise AssertionError(f"Invalid Terminal control: {message!r}") from exc


def _decode_output_frame(frame: bytes) -> tuple[int, bytes]:
    """Decode one versioned ordered Terminal output frame."""
    if len(frame) <= _FRAME_HEADER.size:
        raise AssertionError(f"Truncated Terminal output frame: {frame!r}")
    version, frame_type, sequence = _FRAME_HEADER.unpack_from(frame)
    assert version == 1
    assert frame_type == 2
    assert sequence > 0
    return sequence, frame[_FRAME_HEADER.size :]


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
    azents_main_web_url: str,
    azents_runtime_provider_docker_container: DockerContainer,
) -> None:
    """Prove the real Runner PTY wire, reattachment, and explicit termination."""
    del azents_runtime_provider_docker_container
    workspace = _create_workspace(
        public_api_client=public_api_client,
        admin_api_client=admin_api_client,
        server_url=azents_public_server_url,
        managed_runtime=True,
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
        origin=azents_main_web_url,
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
        origin=azents_main_web_url,
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
    assert exit_control.get("reason") == "caller"
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


def test_runtime_terminal_policy_revocation_and_runtime_lifecycle_priority(
    public_api_client: azentspublicclient.ApiClient,
    admin_api_client: azentsadminclient.ApiClient,
    azents_public_server_url: str,
    azents_main_web_url: str,
    azents_runtime_provider_docker_container: DockerContainer,
) -> None:
    """Prove policy precedence, revocation, and explicit stopped-Runtime start."""
    del azents_runtime_provider_docker_container
    workspace = _create_workspace(
        public_api_client=public_api_client,
        admin_api_client=admin_api_client,
        server_url=azents_public_server_url,
        managed_runtime=True,
    )
    runtime_api = _start_runtime(
        public_api_client=public_api_client,
        workspace=workspace,
        server_url=azents_public_server_url,
    )
    terminal_api = TerminalV1Api(public_api_client)

    try:
        _replace_infrastructure_terminal_policy(
            admin_api_client=admin_api_client,
            workspace=workspace,
            terminal_enabled=False,
        )
        provider_denied = _wait_terminal_projection(
            public_api_client=public_api_client,
            workspace=workspace,
            predicate=lambda projection: (
                projection.reason_code is RuntimeTerminalReasonCode.TERMINAL_DISABLED
                and projection.denied_scope
                is RuntimeTerminalDeniedScope.PROVIDER_PROFILE
            ),
            message="Infrastructure Profile Terminal denial was not projected",
        )
        assert provider_denied.can_open_or_attach is False
        issued = terminal_api.terminal_v1_issue_terminal_ticket(
            handle=workspace.handle,
            agent_id=workspace.agent_id,
            session_id=workspace.session_id,
            _headers=_headers(workspace.token),
        )
        assert issued.status is RuntimeTerminalTicketStatus.DENIED
        assert issued.reason_code is RuntimeTerminalReasonCode.TERMINAL_DISABLED
        assert issued.denied_scope is RuntimeTerminalDeniedScope.PROVIDER_PROFILE
    finally:
        _replace_infrastructure_terminal_policy(
            admin_api_client=admin_api_client,
            workspace=workspace,
            terminal_enabled=True,
        )
    _wait_terminal_projection(
        public_api_client=public_api_client,
        workspace=workspace,
        predicate=lambda projection: projection.state in {"ready", "active"},
        message="Terminal did not recover after infrastructure policy restoration",
    )

    try:
        _replace_workspace_terminal_policy(
            public_api_client=public_api_client,
            workspace=workspace,
            terminal_enabled=False,
        )
        workspace_denied = _wait_terminal_projection(
            public_api_client=public_api_client,
            workspace=workspace,
            predicate=lambda projection: (
                projection.reason_code is RuntimeTerminalReasonCode.TERMINAL_DISABLED
                and projection.denied_scope
                is RuntimeTerminalDeniedScope.WORKSPACE_PROFILE
            ),
            message="Workspace Runtime Profile Terminal denial was not projected",
        )
        assert workspace_denied.can_open_or_attach is False
        issued = terminal_api.terminal_v1_issue_terminal_ticket(
            handle=workspace.handle,
            agent_id=workspace.agent_id,
            session_id=workspace.session_id,
            _headers=_headers(workspace.token),
        )
        assert issued.status is RuntimeTerminalTicketStatus.DENIED
        assert issued.reason_code is RuntimeTerminalReasonCode.TERMINAL_DISABLED
        assert issued.denied_scope is RuntimeTerminalDeniedScope.WORKSPACE_PROFILE
    finally:
        _replace_workspace_terminal_policy(
            public_api_client=public_api_client,
            workspace=workspace,
            terminal_enabled=True,
        )
    _wait_terminal_projection(
        public_api_client=public_api_client,
        workspace=workspace,
        predicate=lambda projection: projection.state in {"ready", "active"},
        message="Terminal did not recover after Workspace policy restoration",
    )

    terminal = _TerminalSocket.connect(
        public_api_client=public_api_client,
        workspace=workspace,
        server_url=azents_public_server_url,
        origin=azents_main_web_url,
    )
    AgentV1Api(public_api_client).agent_v1_update_agent(
        agent_id=workspace.agent_id,
        handle=workspace.handle,
        agent_update_request=AgentUpdateRequest(terminal_enabled=False),
        _headers=_headers(workspace.token),
    )
    revoked = terminal.wait_for_control("revoked", timeout=15)
    assert revoked.get("reason_code") == "terminal_disabled"
    denied = terminal_api.terminal_v1_issue_terminal_ticket(
        handle=workspace.handle,
        agent_id=workspace.agent_id,
        session_id=workspace.session_id,
        _headers=_headers(workspace.token),
    )
    assert denied.status is RuntimeTerminalTicketStatus.DENIED
    assert denied.reason_code is RuntimeTerminalReasonCode.TERMINAL_DISABLED

    AgentV1Api(public_api_client).agent_v1_update_agent(
        agent_id=workspace.agent_id,
        handle=workspace.handle,
        agent_update_request=AgentUpdateRequest(terminal_enabled=True),
        _headers=_headers(workspace.token),
    )
    active = _TerminalSocket.connect(
        public_api_client=public_api_client,
        workspace=workspace,
        server_url=azents_public_server_url,
        origin=azents_main_web_url,
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
    assert invalidation is None or invalidation.get("type") in {"revoked", "exit"}

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
    _prepare_terminal_session(
        public_api_client=public_api_client,
        workspace=workspace,
        server_url=azents_public_server_url,
    )
    resumed = _TerminalSocket.connect(
        public_api_client=public_api_client,
        workspace=workspace,
        server_url=azents_public_server_url,
        origin=azents_main_web_url,
    )
    resumed.command("printf '__REST''ARTED__yes__'", "RESTARTED_DONE")
    resumed.terminate()


def test_runtime_terminal_member_access_revocation_closes_attachment(
    public_api_client: azentspublicclient.ApiClient,
    admin_api_client: azentsadminclient.ApiClient,
    azents_public_server_url: str,
    azents_main_web_url: str,
    azents_runtime_provider_docker_container: DockerContainer,
) -> None:
    """Removing a Workspace member revokes their attached Team Terminal."""
    del azents_runtime_provider_docker_container
    team = create_two_member_team_session(
        public_api_client,
        admin_api_client,
        azents_public_server_url,
    )
    _prepare_session_folder(
        server_url=azents_public_server_url,
        token=team.owner_access_token,
        agent_id=team.agent_id,
        session_id=team.session_id,
    )
    owner_workspace = _TerminalWorkspace(
        token=team.owner_access_token,
        handle=team.workspace_handle,
        agent_id=team.agent_id,
        session_id=team.session_id,
        runtime_profile_id=None,
        infrastructure_profile_id=None,
    )
    member_workspace = _TerminalWorkspace(
        token=team.member_access_token,
        handle=team.workspace_handle,
        agent_id=team.agent_id,
        session_id=team.session_id,
        runtime_profile_id=None,
        infrastructure_profile_id=None,
    )
    _wait_terminal_projection(
        public_api_client=public_api_client,
        workspace=owner_workspace,
        predicate=lambda projection: projection.state in {"ready", "active"},
        message="Member Terminal did not become ready after Session folder preparation",
        timeout=120,
    )
    terminal = _TerminalSocket.connect(
        public_api_client=public_api_client,
        workspace=member_workspace,
        server_url=azents_public_server_url,
        origin=azents_main_web_url,
    )
    terminal.command("printf '__MEM''BER__attached__'", "MEMBER_ATTACHED")

    WorkspaceUserV1Api(public_api_client).workspaceuser_v1_delete_workspace_user(
        workspace_user_id=team.member_workspace_user_id,
        handle=team.workspace_handle,
        _headers=_headers(team.owner_access_token),
    )
    revoked = terminal.wait_for_control("revoked", timeout=15)
    assert revoked.get("reason_code") == "access_denied"
    with pytest.raises(ForbiddenException):
        TerminalV1Api(public_api_client).terminal_v1_issue_terminal_ticket(
            handle=team.workspace_handle,
            agent_id=team.agent_id,
            session_id=team.session_id,
            _headers=_headers(team.member_access_token),
        )


def test_runtime_terminal_runner_capability_mismatch_fails_closed(
    public_api_client: azentspublicclient.ApiClient,
    admin_api_client: azentsadminclient.ApiClient,
    azents_public_server_url: str,
    azents_main_web_url: str,
    azents_runtime_provider_docker_container: DockerContainer,
) -> None:
    """A connected Runner without terminal.v1 cannot admit a Terminal."""
    workspace = _create_workspace(
        public_api_client=public_api_client,
        admin_api_client=admin_api_client,
        server_url=azents_public_server_url,
        managed_runtime=True,
    )
    _start_runtime(
        public_api_client=public_api_client,
        workspace=workspace,
        server_url=azents_public_server_url,
    )
    runtime_container = _runtime_container(
        azents_runtime_provider_docker_container,
        agent_id=workspace.agent_id,
    )
    legacy_suffix = unique()
    legacy_pid_path = f"/tmp/terminal-e2e-legacy-runner-{legacy_suffix}.pid"
    legacy_log_path = f"/tmp/terminal-e2e-legacy-runner-{legacy_suffix}.log"
    legacy_script = (
        "import azents_runtime_runner.main as runner\n"
        "runner._CAPABILITIES = tuple(\n"
        "    capability for capability in runner._CAPABILITIES\n"
        "    if capability != 'terminal.v1'\n"
        ")\n"
        "runner.main()\n"
    )
    original_suspended = False
    try:
        _runtime_exec(runtime_container, "kill -STOP 1")
        original_suspended = True
        _runtime_exec(
            runtime_container,
            (
                "PYTHONUNBUFFERED=1 "
                f"AZ_RUNTIME_RUNNER_ID={shlex.quote(f'legacy-{legacy_suffix}')} "
                "AZ_RUNTIME_RUNNER_CONNECTION_ID="
                f"{shlex.quote(f'legacy-{legacy_suffix}')} "
                f"python -c {shlex.quote(legacy_script)} "
                f"> {shlex.quote(legacy_log_path)} 2>&1 & "
                f"echo $! > {shlex.quote(legacy_pid_path)}"
            ),
        )
        _wait_runtime_log(
            runtime_container,
            path=legacy_log_path,
            marker="Runtime Runner registered",
        )
        unsupported = _wait_terminal_projection(
            public_api_client=public_api_client,
            workspace=workspace,
            predicate=lambda projection: (
                projection.reason_code
                is RuntimeTerminalReasonCode.RUNNER_TERMINAL_UNSUPPORTED
                and projection.denied_scope is RuntimeTerminalDeniedScope.RUNNER
            ),
            message="Terminal did not fail closed for the legacy Runner",
            timeout=45,
        )
        assert unsupported.state == "unavailable"
        assert unsupported.can_open_or_attach is False
        issued = TerminalV1Api(public_api_client).terminal_v1_issue_terminal_ticket(
            handle=workspace.handle,
            agent_id=workspace.agent_id,
            session_id=workspace.session_id,
            _headers=_headers(workspace.token),
        )
        assert issued.status is RuntimeTerminalTicketStatus.UNAVAILABLE
        assert (
            issued.reason_code is RuntimeTerminalReasonCode.RUNNER_TERMINAL_UNSUPPORTED
        )
        assert issued.denied_scope is RuntimeTerminalDeniedScope.RUNNER
    finally:
        if original_suspended:
            _runtime_exec(
                runtime_container,
                (
                    f"if [ -f {legacy_pid_path} ]; then "
                    f'kill "$(cat {legacy_pid_path})" 2>/dev/null || true; '
                    f"rm -f {legacy_pid_path}; fi; "
                    f"rm -f {legacy_log_path}; "
                    "kill -CONT 1"
                ),
            )
    _wait_terminal_projection(
        public_api_client=public_api_client,
        workspace=workspace,
        predicate=lambda projection: projection.state in {"ready", "active"},
        message="Terminal did not recover after the current Runner reconnected",
        timeout=45,
    )
    recovered = _TerminalSocket.connect(
        public_api_client=public_api_client,
        workspace=workspace,
        server_url=azents_public_server_url,
        origin=azents_main_web_url,
    )
    recovered.terminate()


def test_runtime_free_terminal_denies_without_starting_runtime(
    public_api_client: azentspublicclient.ApiClient,
    admin_api_client: azentsadminclient.ApiClient,
    azents_public_server_url: str,
) -> None:
    """Runtime-free Terminal admission fails without creating or starting Runtime."""
    workspace = _create_workspace(
        public_api_client=public_api_client,
        admin_api_client=admin_api_client,
        server_url=azents_public_server_url,
        managed_runtime=False,
    )
    terminal_api = TerminalV1Api(public_api_client)
    projection = terminal_api.terminal_v1_get_terminal_projection(
        handle=workspace.handle,
        agent_id=workspace.agent_id,
        session_id=workspace.session_id,
        _headers=_headers(workspace.token),
    )
    assert projection.state == "absent"
    assert projection.reason_code is RuntimeTerminalReasonCode.RUNTIME_FREE_AGENT
    assert projection.can_start_runtime is False
    assert projection.can_open_or_attach is False
    issued = terminal_api.terminal_v1_issue_terminal_ticket(
        handle=workspace.handle,
        agent_id=workspace.agent_id,
        session_id=workspace.session_id,
        _headers=_headers(workspace.token),
    )
    assert issued.status is RuntimeTerminalTicketStatus.DENIED
    assert issued.reason_code is RuntimeTerminalReasonCode.RUNTIME_FREE_AGENT

    runtime = AgentRuntimeV1Api(public_api_client).agent_runtime_v1_get_agent_runtime(
        agent_id=workspace.agent_id,
        handle=workspace.handle,
        _headers=_headers(workspace.token),
    )
    assert runtime.capability is AgentRuntimeCapability.NONE
    assert runtime.runtime is None
    assert runtime.lifecycle is None
