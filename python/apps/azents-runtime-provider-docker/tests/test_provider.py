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
        ),
    )


def _command(
    command_type: RuntimeLifecycleCommandType,
    *,
    final_desired_state: RuntimeDesiredState | None = None,
    desired_generation: int = 1,
    provider_generation: int = 7,
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
            runner_auth_token="runtime-runner:runtime-1:1",
            control_token="control-token",
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
            runner_auth_token="runtime-runner:runtime-1:1",
            control_token="control-token",
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
    assert container.spec.env["AZ_RUNTIME_CONTROL_AUTH_TOKEN"] == "control-token"
    assert (
        container.spec.env["AZ_RUNTIME_RUNNER_AUTH_CREDENTIAL_ID"]
        == "runtime-runner:runtime-1:1"
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
async def test_start_reuses_container_across_generation_changes(
    tmp_path: Path,
) -> None:
    docker = FakeDockerApi()
    provider = _provider(tmp_path, docker)
    await provider.start(_command(RuntimeLifecycleCommandType.START))

    await provider.start(
        _command(
            RuntimeLifecycleCommandType.START,
            desired_generation=2,
            provider_generation=8,
        )
    )

    assert docker.removed == []
    container = docker.containers["azents-runtime-runtime-1"]
    assert container.spec.labels["azents/desired-generation"] == "1"
    assert container.starts == 2


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
                workspace_mount_path="relative/path",
            ),
        )


@pytest.mark.asyncio
async def test_reset_requires_explicit_final_desired_state(tmp_path: Path) -> None:
    docker = FakeDockerApi()
    provider = _provider(tmp_path, docker)

    with pytest.raises(InvalidResetFinalDesiredState):
        await provider.reset(_command(RuntimeLifecycleCommandType.RESET))
