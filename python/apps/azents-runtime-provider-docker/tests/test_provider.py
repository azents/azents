"""Docker Runtime Provider lifecycle tests."""

import dataclasses
import os
from collections.abc import Mapping, Sequence
from pathlib import Path

import pytest
from azents_runtime_control.provider import (
    RuntimeContainerAuth as ControlRuntimeContainerAuth,
)
from azents_runtime_control.provider import (
    RuntimeIdentity as ControlRuntimeIdentity,
)
from azents_runtime_control.provider import (
    RuntimeLifecycleCommand as ControlRuntimeLifecycleCommand,
)
from azents_runtime_control.provider import (
    RuntimeLifecycleCommandType as ControlRuntimeLifecycleCommandType,
)
from azents_runtime_control.provider import (
    RuntimeProviderObservedState as ControlRuntimeProviderObservedState,
)

from azents_runtime_provider_docker.docker_api import (
    DockerApi,
    DockerContainerInfo,
    DockerContainerSpec,
    DockerContainerState,
)
from azents_runtime_provider_docker.models import (
    RuntimeContainerAuth,
    RuntimeDesiredState,
    RuntimeIdentity,
    RuntimeLifecycleCommand,
    RuntimeLifecycleCommandType,
    RuntimeProviderObservedState,
)
from azents_runtime_provider_docker.provider import (
    RUNNER_LIMIT_ENV_NAMES,
    DockerRuntimeProvider,
    DockerRuntimeProviderConfig,
    InvalidResetFinalDesiredState,
    InvalidWorkspacePath,
)
from azents_runtime_provider_docker.runtime_control import DockerRuntimeControlAdapter


@dataclasses.dataclass
class FakeContainer:
    """Mutable fake Docker container."""

    spec: DockerContainerSpec
    running: bool = False
    starts: int = 0

    def info(self) -> DockerContainerInfo:
        """Return inspection data."""
        return DockerContainerInfo(
            name=self.spec.name,
            image=self.spec.image,
            user=self.spec.user,
            labels=self.spec.labels,
            env=self.spec.env,
            binds=self.spec.binds,
            state=DockerContainerState(
                running=self.running,
                restarting=False,
                dead=False,
                status="running" if self.running else "created",
            ),
        )


class FakeDockerApi(DockerApi):
    """In-memory Docker API fake."""

    def __init__(self) -> None:
        self.containers: dict[str, FakeContainer] = {}
        self.removed: list[str] = []
        self.networks: list[str] = []
        self.images: list[str] = []

    async def ensure_network(self, name: str) -> None:
        """Record network creation."""
        self.networks.append(name)

    async def ensure_image(self, image: str) -> None:
        """Record image ensure."""
        self.images.append(image)

    async def get_container(self, name: str) -> DockerContainerInfo | None:
        """Return a fake container."""
        container = self.containers.get(name)
        if container is None:
            return None
        return container.info()

    async def create_container(self, spec: DockerContainerSpec) -> None:
        """Create a fake stopped container."""
        self.containers[spec.name] = FakeContainer(spec=spec)

    async def start_container(self, name: str) -> None:
        """Start a fake container."""
        container = self.containers[name]
        container.running = True
        container.starts += 1

    async def remove_container(self, name: str) -> None:
        """Remove a fake container if present."""
        self.removed.append(name)
        self.containers.pop(name, None)

    async def list_containers(
        self,
        labels: Mapping[str, str],
    ) -> Sequence[DockerContainerInfo]:
        """List containers matching labels."""
        return tuple(
            container.info()
            for container in self.containers.values()
            if all(
                container.spec.labels.get(key) == value for key, value in labels.items()
            )
        )


def _provider(tmp_path: Path, docker: FakeDockerApi) -> DockerRuntimeProvider:
    return DockerRuntimeProvider(
        docker,
        DockerRuntimeProviderConfig(
            provider_id="provider-docker",
            host_data_root=tmp_path,
            docker_network="azents-runtime",
            runner_env={},
        ),
    )


def _command(
    command_type: RuntimeLifecycleCommandType,
    *,
    final_desired_state: RuntimeDesiredState | None = None,
    desired_generation: int = 1,
    provider_generation: int = 7,
    runner_auth_token: str = "runner-token-1",
    runner_auth_credential_id: str = "runner-credential-1",
) -> RuntimeLifecycleCommand:
    return RuntimeLifecycleCommand(
        command_type=command_type,
        identity=RuntimeIdentity(
            runtime_id="runtime-1",
            agent_id="agent-1",
            workspace_id="workspace-1",
        ),
        desired_generation=desired_generation,
        provider_generation=provider_generation,
        runner_image="runner:latest",
        auth=RuntimeContainerAuth(
            control_endpoint="runtime-control:8020",
            runner_auth_token=runner_auth_token,
            runner_auth_credential_id=runner_auth_credential_id,
            control_tls_ca_pem=None,
            allow_insecure_control=True,
        ),
        reset_final_desired_state=final_desired_state,
    )


def _control_command(
    command_type: ControlRuntimeLifecycleCommandType,
) -> ControlRuntimeLifecycleCommand:
    return ControlRuntimeLifecycleCommand(
        command_type=command_type,
        identity=ControlRuntimeIdentity(
            runtime_id="runtime-1",
            agent_id="agent-1",
            workspace_id="workspace-1",
        ),
        desired_generation=1,
        provider_generation=7,
        runner_image="runner:latest",
        auth=ControlRuntimeContainerAuth(
            control_endpoint="runtime-control:8020",
            runner_auth_token="runner-token-1",
            runner_auth_credential_id="runner-credential-1",
            control_tls_ca_pem=None,
            allow_insecure_control=True,
        ),
    )


@pytest.mark.asyncio
async def test_start_creates_container_with_workspace_bind(tmp_path: Path) -> None:
    docker = FakeDockerApi()
    provider = _provider(tmp_path, docker)

    result = await provider.start(_command(RuntimeLifecycleCommandType.START))

    assert result.report.observed_state is RuntimeProviderObservedState.RUNNING
    assert result.report.workspace_path == "/workspace/agent"
    container = docker.containers["azents-runtime-runtime-1"]
    assert container.spec.user == "1000:1000"
    assert container.spec.working_dir == "/workspace/agent"
    assert any(
        bind.container_path == "/workspace/agent" for bind in container.spec.binds
    )
    assert container.spec.env["AZ_RUNTIME_RUNNER_AUTH_TOKEN"] == "runner-token-1"
    assert (
        container.spec.env["AZ_RUNTIME_RUNNER_AUTH_CREDENTIAL_ID"]
        == "runner-credential-1"
    )
    workspace_path = tmp_path / "agent-runtimes" / "runtime-1" / "workspace"
    assert workspace_path.exists()
    workspace_stat = workspace_path.stat()
    if os.geteuid() == 0:
        assert workspace_stat.st_uid == 1000
        assert workspace_stat.st_gid == 1000
        assert workspace_stat.st_mode & 0o777 == 0o755
    else:
        assert workspace_stat.st_mode & 0o777 == 0o777


@pytest.mark.asyncio
async def test_start_passes_runner_limit_environment_to_container(
    tmp_path: Path,
) -> None:
    docker = FakeDockerApi()
    runner_env = {
        name: str(index) for index, name in enumerate(RUNNER_LIMIT_ENV_NAMES, start=1)
    }
    provider = DockerRuntimeProvider(
        docker,
        DockerRuntimeProviderConfig(
            provider_id="provider-docker",
            host_data_root=tmp_path,
            docker_network="azents-runtime",
            runner_env=runner_env,
        ),
    )

    await provider.start(_command(RuntimeLifecycleCommandType.START))

    container_env = docker.containers["azents-runtime-runtime-1"].spec.env
    assert {name: container_env[name] for name in RUNNER_LIMIT_ENV_NAMES} == runner_env


@pytest.mark.parametrize(
    "replacement_env",
    (
        {"AZ_RUNTIME_RUNNER_MAX_CONCURRENT_OPERATIONS": "25"},
        {},
    ),
)
@pytest.mark.asyncio
async def test_start_replaces_container_when_runner_limit_environment_changes(
    tmp_path: Path,
    replacement_env: Mapping[str, str],
) -> None:
    docker = FakeDockerApi()
    initial_env = {"AZ_RUNTIME_RUNNER_MAX_CONCURRENT_OPERATIONS": "50"}
    initial_provider = DockerRuntimeProvider(
        docker,
        DockerRuntimeProviderConfig(
            provider_id="provider-docker",
            host_data_root=tmp_path,
            docker_network="azents-runtime",
            runner_env=initial_env,
        ),
    )
    await initial_provider.start(_command(RuntimeLifecycleCommandType.START))
    replacement_provider = DockerRuntimeProvider(
        docker,
        DockerRuntimeProviderConfig(
            provider_id="provider-docker",
            host_data_root=tmp_path,
            docker_network="azents-runtime",
            runner_env=replacement_env,
        ),
    )

    await replacement_provider.start(_command(RuntimeLifecycleCommandType.START))

    assert docker.removed == ["azents-runtime-runtime-1"]
    container_env = docker.containers["azents-runtime-runtime-1"].spec.env
    assert {
        name: container_env[name]
        for name in RUNNER_LIMIT_ENV_NAMES
        if name in container_env
    } == replacement_env


@pytest.mark.asyncio
async def test_start_replaces_container_for_new_runner_credential(
    tmp_path: Path,
) -> None:
    docker = FakeDockerApi()
    provider = _provider(tmp_path, docker)
    await provider.start(_command(RuntimeLifecycleCommandType.START))
    workspace_path = tmp_path / "agent-runtimes" / "runtime-1" / "workspace"
    marker = workspace_path / "keep.txt"
    marker.write_text("preserved")
    original_binds = docker.containers["azents-runtime-runtime-1"].spec.binds

    await provider.start(
        _command(
            RuntimeLifecycleCommandType.START,
            desired_generation=2,
            provider_generation=8,
            runner_auth_token="runner-token-2",
            runner_auth_credential_id="runner-credential-2",
        )
    )

    assert docker.removed == ["azents-runtime-runtime-1"]
    container = docker.containers["azents-runtime-runtime-1"]
    assert container.spec.labels["azents/desired-generation"] == "2"
    assert container.spec.env["AZ_RUNTIME_RUNNER_AUTH_TOKEN"] == "runner-token-2"
    assert (
        container.spec.env["AZ_RUNTIME_RUNNER_AUTH_CREDENTIAL_ID"]
        == "runner-credential-2"
    )
    assert container.spec.binds == original_binds
    assert marker.read_text() == "preserved"


@pytest.mark.asyncio
async def test_runtime_control_adapter_reports_provider_workspace_path(
    tmp_path: Path,
) -> None:
    docker = FakeDockerApi()
    provider = _provider(tmp_path, docker)
    adapter = DockerRuntimeControlAdapter(provider)

    result = await adapter.start(
        _control_command(ControlRuntimeLifecycleCommandType.START)
    )

    assert result.report.observed_state is ControlRuntimeProviderObservedState.RUNNING
    assert result.report.workspace_path == "/workspace/agent"
    assert "azents-runtime-runtime-1" in docker.containers


@pytest.mark.asyncio
async def test_stop_preserves_workspace_data(tmp_path: Path) -> None:
    docker = FakeDockerApi()
    provider = _provider(tmp_path, docker)
    await provider.start(_command(RuntimeLifecycleCommandType.START))
    marker = tmp_path / "agent-runtimes" / "runtime-1" / "workspace" / "keep.txt"
    marker.write_text("preserved")

    result = await provider.stop(_command(RuntimeLifecycleCommandType.STOP))

    assert result.report.observed_state is RuntimeProviderObservedState.STOPPED
    assert "azents-runtime-runtime-1" not in docker.containers
    assert marker.read_text() == "preserved"


@pytest.mark.asyncio
async def test_restart_replaces_container_and_preserves_workspace_data(
    tmp_path: Path,
) -> None:
    docker = FakeDockerApi()
    provider = _provider(tmp_path, docker)
    await provider.start(_command(RuntimeLifecycleCommandType.START))
    marker = tmp_path / "agent-runtimes" / "runtime-1" / "workspace" / "keep.txt"
    marker.write_text("preserved")

    result = await provider.restart(_command(RuntimeLifecycleCommandType.RESTART))

    assert result.report.observed_state is RuntimeProviderObservedState.RUNNING
    assert docker.removed == ["azents-runtime-runtime-1"]
    assert marker.read_text() == "preserved"


@pytest.mark.asyncio
async def test_reset_running_deletes_workspace_data(tmp_path: Path) -> None:
    docker = FakeDockerApi()
    provider = _provider(tmp_path, docker)
    await provider.start(_command(RuntimeLifecycleCommandType.START))
    marker = tmp_path / "agent-runtimes" / "runtime-1" / "workspace" / "delete.txt"
    marker.write_text("gone")

    result = await provider.reset(
        _command(
            RuntimeLifecycleCommandType.RESET,
            final_desired_state=RuntimeDesiredState.RUNNING,
        )
    )

    assert result.report.observed_state is RuntimeProviderObservedState.RUNNING
    assert not marker.exists()
    assert "azents-runtime-runtime-1" in docker.containers


@pytest.mark.asyncio
async def test_reset_stopped_deletes_workspace_data_and_does_not_start_container(
    tmp_path: Path,
) -> None:
    docker = FakeDockerApi()
    provider = _provider(tmp_path, docker)
    await provider.start(_command(RuntimeLifecycleCommandType.START))
    marker = tmp_path / "agent-runtimes" / "runtime-1" / "workspace" / "delete.txt"
    marker.write_text("gone")

    result = await provider.reset(
        _command(
            RuntimeLifecycleCommandType.RESET,
            final_desired_state=RuntimeDesiredState.STOPPED,
        )
    )

    assert result.report.observed_state is RuntimeProviderObservedState.STOPPED
    assert not marker.exists()
    assert "azents-runtime-runtime-1" not in docker.containers
    assert (tmp_path / "agent-runtimes" / "runtime-1" / "workspace").exists()


@pytest.mark.asyncio
async def test_terminal_delete_removes_container_and_workspace_idempotently(
    tmp_path: Path,
) -> None:
    docker = FakeDockerApi()
    provider = _provider(tmp_path, docker)
    await provider.start(_command(RuntimeLifecycleCommandType.START))
    marker = tmp_path / "agent-runtimes" / "runtime-1" / "workspace" / "delete.txt"
    marker.write_text("gone")

    first = await provider.terminal_delete(
        _command(RuntimeLifecycleCommandType.TERMINAL_DELETE)
    )
    second = await provider.terminal_delete(
        _command(RuntimeLifecycleCommandType.TERMINAL_DELETE)
    )

    assert first.report.terminal_delete_acknowledged is True
    assert first.report.workspace_path == ""
    assert second.report.terminal_delete_acknowledged is True
    assert "azents-runtime-runtime-1" not in docker.containers
    assert not marker.exists()


@pytest.mark.asyncio
async def test_observe_known_runtimes_reports_container_and_directory(
    tmp_path: Path,
) -> None:
    docker = FakeDockerApi()
    provider = _provider(tmp_path, docker)
    await provider.start(_command(RuntimeLifecycleCommandType.START))
    (tmp_path / "agent-runtimes" / "runtime-2" / "workspace").mkdir(parents=True)

    reports = await provider.observe_known_runtimes()

    by_runtime = {report.runtime_id: report for report in reports}
    assert (
        by_runtime["runtime-1"].observed_state is RuntimeProviderObservedState.RUNNING
    )
    assert (
        by_runtime["runtime-2"].observed_state is RuntimeProviderObservedState.STOPPED
    )
    assert by_runtime["runtime-2"].reason == "workspace_directory_without_container"


def test_invalid_workspace_path_is_rejected(tmp_path: Path) -> None:
    docker = FakeDockerApi()

    with pytest.raises(InvalidWorkspacePath):
        DockerRuntimeProvider(
            docker,
            DockerRuntimeProviderConfig(
                provider_id="provider-docker",
                host_data_root=tmp_path,
                docker_network="azents-runtime",
                runner_env={},
                workspace_mount_path="relative/path",
            ),
        )


@pytest.mark.asyncio
async def test_reset_requires_explicit_final_desired_state(tmp_path: Path) -> None:
    docker = FakeDockerApi()
    provider = _provider(tmp_path, docker)

    with pytest.raises(InvalidResetFinalDesiredState):
        await provider.reset(_command(RuntimeLifecycleCommandType.RESET))
