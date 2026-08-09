"""Docker Runtime Provider lifecycle tests."""

import dataclasses
import json
import stat
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import cast

import pytest
from azents_runtime_control.provider import (
    RuntimeContainerAuth,
    RuntimeDesiredState,
    RuntimeIdentity,
    RuntimeLifecycleCommand,
    RuntimeLifecycleCommandType,
    RuntimeProviderObservedState,
)
from azents_runtime_control.runtime_configuration import (
    JsonValue,
    RuntimeConfigurationEnvelope,
    RuntimeConfigurationEvidence,
    canonical_runtime_configuration_json,
)

from azents_runtime_provider_docker.docker_api import (
    DockerApi,
    DockerContainerInfo,
    DockerContainerSpec,
    DockerContainerState,
)
from azents_runtime_provider_docker.provider import (
    RUNNER_LIMIT_ENV_NAMES,
    DockerProcessContainmentConfig,
    DockerRuntimeProvider,
    DockerRuntimeProviderConfig,
    InvalidResetFinalDesiredState,
    InvalidWorkspacePath,
    UnsupportedRuntimeConfiguration,
)


@dataclasses.dataclass
class FakeContainer:
    """Mutable fake Docker container."""

    spec: DockerContainerSpec
    running: bool = False
    starts: int = 0
    dead: bool = False
    status: str | None = None
    exit_code: int | None = None
    oom_killed: bool = False

    def info(self) -> DockerContainerInfo:
        """Return inspection data."""
        return DockerContainerInfo(
            name=self.spec.name,
            image=self.spec.image,
            user=self.spec.user,
            labels=self.spec.labels,
            env=self.spec.env,
            binds=self.spec.binds,
            cap_add=self.spec.cap_add,
            cap_drop=self.spec.cap_drop,
            security_options=self.spec.security_options,
            userns_mode=self.spec.userns_mode,
            masked_paths=()
            if self.spec.masked_paths is None
            else self.spec.masked_paths,
            readonly_paths=(
                () if self.spec.readonly_paths is None else self.spec.readonly_paths
            ),
            privileged=self.spec.privileged,
            state=DockerContainerState(
                running=self.running,
                restarting=False,
                dead=self.dead,
                status=self.status or ("running" if self.running else "created"),
                exit_code=self.exit_code,
                oom_killed=self.oom_killed,
            ),
        )


class FakeDockerApi(DockerApi):
    """In-memory Docker API fake."""

    def __init__(self) -> None:
        self.containers: dict[str, FakeContainer] = {}
        self.removed: list[str] = []
        self.networks: list[str] = []
        self.images: list[str] = []

    async def security_options(self) -> Sequence[str]:
        """Return Docker daemon security-option evidence."""
        return ("name=apparmor",)

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


def _provider(
    tmp_path: Path,
    docker: FakeDockerApi,
    *,
    process_containment: DockerProcessContainmentConfig | None = None,
) -> DockerRuntimeProvider:
    return DockerRuntimeProvider(
        docker,
        DockerRuntimeProviderConfig(
            provider_id="provider-docker",
            workspace_mount_path="/runtime/home",
            host_data_root=tmp_path,
            runner_env={},
            tmp_mount_path="/tmp/agent",
            process_containment=process_containment,
        ),
    )


def _containment_config() -> DockerProcessContainmentConfig:
    return DockerProcessContainmentConfig(
        backend="bwrap",
        security_profile="azents-runtime-bwrap",
        qualification_timeout_seconds=15,
    )


def _command(
    command_type: RuntimeLifecycleCommandType,
    *,
    final_desired_state: RuntimeDesiredState | None = None,
    desired_generation: int = 1,
    provider_generation: int = 7,
    runner_image: str = "runner:latest",
    runner_auth_token: str = "runner-token-1",
    runner_auth_credential_id: str = "runner-credential-1",
    runtime_configuration: RuntimeConfigurationEnvelope | None = None,
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
        runner_image=runner_image,
        auth=RuntimeContainerAuth(
            control_endpoint="runtime-control:8020",
            transfer_endpoint="runtime-transfer:8030",
            runner_auth_token=runner_auth_token,
            runner_auth_credential_id=runner_auth_credential_id,
            control_tls_ca_pem=None,
            allow_insecure_control=True,
        ),
        reset_final_desired_state=final_desired_state,
        runtime_configuration=runtime_configuration
        or _runtime_configuration(desired_generation=desired_generation),
    )


@pytest.mark.asyncio
async def test_start_creates_container_with_workspace_bind(tmp_path: Path) -> None:
    docker = FakeDockerApi()
    provider = _provider(tmp_path, docker)

    result = await provider.start(_command(RuntimeLifecycleCommandType.START))

    assert result.report.observed_state is RuntimeProviderObservedState.RUNNING
    assert result.report.reconciliation is None
    container = docker.containers["azents-runtime-runtime-1"]
    assert container.spec.user == "1000:1000"
    assert container.spec.working_dir == "/runtime/home"
    assert any(bind.container_path == "/runtime/home" for bind in container.spec.binds)
    assert container.spec.env["HOME"] == "/runtime/home"
    assert container.spec.env["AZ_RUNTIME_TRANSFER_ENDPOINT"] == "runtime-transfer:8030"
    assert "AZ_RUNTIME_TRANSFER_STAGING_DIRECTORY" not in container.spec.env
    assert container.spec.env["AZ_RUNTIME_RUNNER_AUTH_TOKEN"] == "runner-token-1"
    assert (
        container.spec.env["AZ_RUNTIME_RUNNER_AUTH_CREDENTIAL_ID"]
        == "runner-credential-1"
    )
    workspace_path = tmp_path / "agent-runtimes" / "runtime-1" / "workspace"
    assert workspace_path.exists()
    workspace_stat = workspace_path.stat()
    assert workspace_stat.st_mode & 0o777 in {0o755, 0o777}


@pytest.mark.asyncio
async def test_start_accepts_direct_v2_without_containment(tmp_path: Path) -> None:
    docker = FakeDockerApi()
    provider = _provider(tmp_path, docker)

    await provider.start(
        _command(
            RuntimeLifecycleCommandType.START,
            runtime_configuration=_runtime_configuration(docker_schema_version=2),
        )
    )

    spec = docker.containers["azents-runtime-runtime-1"].spec
    assert "AZ_RUNTIME_PROCESS_CONTAINMENT_CONFIG" not in spec.env
    assert {bind.container_path for bind in spec.binds} == {
        "/runtime/home",
        "/tmp/agent",
    }
    assert spec.cap_drop == ()
    assert spec.cap_add == ()
    assert spec.security_options == ("seccomp=unconfined",)
    assert spec.userns_mode is None
    assert spec.masked_paths is None
    assert spec.readonly_paths is None
    assert spec.privileged is False


@pytest.mark.asyncio
async def test_contained_v2_requires_deployment_preparation(tmp_path: Path) -> None:
    docker = FakeDockerApi()
    provider = _provider(tmp_path, docker)

    with pytest.raises(
        UnsupportedRuntimeConfiguration,
        match="containment is unavailable",
    ):
        await provider.start(
            _command(
                RuntimeLifecycleCommandType.START,
                runtime_configuration=_runtime_configuration(
                    docker_schema_version=2,
                    process_containment=True,
                ),
            )
        )

    assert docker.containers == {}


@pytest.mark.asyncio
async def test_contained_v2_emits_exact_bootstrap_mounts_and_security(
    tmp_path: Path,
) -> None:
    docker = FakeDockerApi()
    provider = _provider(
        tmp_path,
        docker,
        process_containment=_containment_config(),
    )

    await provider.start(
        _command(
            RuntimeLifecycleCommandType.START,
            runtime_configuration=_runtime_configuration(
                docker_schema_version=2,
                process_containment=True,
            ),
        )
    )

    spec = docker.containers["azents-runtime-runtime-1"].spec
    bootstrap = json.loads(spec.env["AZ_RUNTIME_PROCESS_CONTAINMENT_CONFIG"])
    assert bootstrap == {
        "schema_version": 1,
        "backend": "bwrap",
        "agent_workspace_path": "/runtime/home",
        "agent_temporary_path": "/run/azents/agent-tmp",
        "runner_private_paths": [
            "/run/azents/runner-private",
            "/workspace/python/apps/azents-runtime-runner/.venv",
            "/var/run/azents-engine/docker.sock",
        ],
        "qualification_timeout_seconds": 15,
    }
    assert {bind.container_path for bind in spec.binds} == {
        "/runtime/home",
        "/run/azents/agent-tmp",
        "/run/azents/runner-private",
    }
    assert "/tmp/agent" not in {bind.container_path for bind in spec.binds}
    assert spec.user == "1000:1000"
    assert spec.cap_add == (
        "SYS_ADMIN",
        "SYS_CHROOT",
        "NET_ADMIN",
        "SETUID",
        "SETGID",
        "SYS_PTRACE",
        "SETPCAP",
    )
    assert spec.cap_drop == ("ALL",)
    assert spec.security_options == (
        "seccomp=unconfined",
        "apparmor=azents-runtime-bwrap",
    )
    assert spec.userns_mode == "host"
    assert spec.masked_paths == ()
    assert spec.readonly_paths == ()
    assert spec.privileged is False
    runtime_root = tmp_path / "agent-runtimes" / "runtime-1"
    assert (runtime_root / "workspace").is_dir()
    assert (runtime_root / "tmp-agent-contained").is_dir()
    assert (runtime_root / "runner-private").is_dir()
    assert stat.S_IMODE((runtime_root / "workspace").stat().st_mode) == 0o777
    assert stat.S_IMODE((runtime_root / "tmp-agent-contained").stat().st_mode) == 0o777
    assert stat.S_IMODE((runtime_root / "runner-private").stat().st_mode) == 0o777
    assert not (runtime_root / "tmp-agent").exists()


@pytest.mark.asyncio
async def test_contained_restart_preserves_workspace_and_clears_temporary_storage(
    tmp_path: Path,
) -> None:
    docker = FakeDockerApi()
    provider = _provider(
        tmp_path,
        docker,
        process_containment=_containment_config(),
    )
    command = _command(
        RuntimeLifecycleCommandType.START,
        runtime_configuration=_runtime_configuration(
            docker_schema_version=2,
            process_containment=True,
        ),
    )
    await provider.start(command)
    runtime_root = tmp_path / "agent-runtimes" / "runtime-1"
    workspace_marker = runtime_root / "workspace" / "keep.txt"
    temporary_marker = runtime_root / "tmp-agent-contained" / "discard.txt"
    workspace_marker.write_text("preserved")
    temporary_marker.write_text("discarded")

    await provider.restart(
        dataclasses.replace(command, command_type=RuntimeLifecycleCommandType.RESTART)
    )

    assert workspace_marker.read_text() == "preserved"
    assert not temporary_marker.exists()
    assert (runtime_root / "tmp-agent-contained").is_dir()


@pytest.mark.asyncio
async def test_containment_adoption_and_rollback_never_restore_direct_temporary_files(
    tmp_path: Path,
) -> None:
    docker = FakeDockerApi()
    provider = _provider(
        tmp_path,
        docker,
        process_containment=_containment_config(),
    )
    direct_command = _command(RuntimeLifecycleCommandType.START)
    contained_command = _command(
        RuntimeLifecycleCommandType.START,
        runtime_configuration=_runtime_configuration(
            docker_schema_version=2,
            process_containment=True,
        ),
    )
    await provider.start(direct_command)
    runtime_root = tmp_path / "agent-runtimes" / "runtime-1"
    stale_direct_marker = runtime_root / "tmp-agent" / "stale-secret.txt"
    stale_direct_marker.write_text("must not return")

    await provider.start(contained_command)

    assert not (runtime_root / "tmp-agent").exists()
    assert (runtime_root / "tmp-agent-contained").is_dir()

    await provider.start(direct_command)

    assert not stale_direct_marker.exists()
    assert (runtime_root / "tmp-agent").is_dir()
    assert not (runtime_root / "tmp-agent-contained").exists()
    assert not (runtime_root / "runner-private").exists()


@pytest.mark.asyncio
async def test_contained_security_drift_forces_recreation(tmp_path: Path) -> None:
    docker = FakeDockerApi()
    provider = _provider(
        tmp_path,
        docker,
        process_containment=_containment_config(),
    )
    command = _command(
        RuntimeLifecycleCommandType.START,
        runtime_configuration=_runtime_configuration(
            docker_schema_version=2,
            process_containment=True,
        ),
    )
    await provider.start(command)
    current = docker.containers["azents-runtime-runtime-1"]
    current.spec = dataclasses.replace(current.spec, cap_add=())

    await provider.start(command)

    assert docker.removed == ["azents-runtime-runtime-1"]
    replacement = docker.containers["azents-runtime-runtime-1"].spec
    assert replacement.cap_add == (
        "SYS_ADMIN",
        "SYS_CHROOT",
        "NET_ADMIN",
        "SETUID",
        "SETGID",
        "SYS_PTRACE",
        "SETPCAP",
    )
    assert replacement.cap_drop == ("ALL",)


@pytest.mark.asyncio
async def test_terminal_container_reports_bounded_exit_diagnostic(
    tmp_path: Path,
) -> None:
    docker = FakeDockerApi()
    provider = _provider(tmp_path, docker)
    command = _command(RuntimeLifecycleCommandType.START)
    await provider.start(command)
    container = docker.containers["azents-runtime-runtime-1"]
    container.running = False
    container.status = "exited"
    container.exit_code = 23

    report = await provider.observe(command)

    assert report.observed_state is RuntimeProviderObservedState.FAILED
    assert report.reason == "container_exited"
    assert report.diagnostic == {
        "source": "docker_container",
        "oom_killed": "false",
        "exit_code": "23",
    }


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
            workspace_mount_path="/runtime/home",
            host_data_root=tmp_path,
            runner_env=runner_env,
            tmp_mount_path="/tmp/agent",
            process_containment=None,
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
            workspace_mount_path="/runtime/home",
            host_data_root=tmp_path,
            runner_env=initial_env,
            tmp_mount_path="/tmp/agent",
            process_containment=None,
        ),
    )
    await initial_provider.start(_command(RuntimeLifecycleCommandType.START))
    replacement_provider = DockerRuntimeProvider(
        docker,
        DockerRuntimeProviderConfig(
            provider_id="provider-docker",
            workspace_mount_path="/runtime/home",
            host_data_root=tmp_path,
            runner_env=replacement_env,
            tmp_mount_path="/tmp/agent",
            process_containment=None,
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
async def test_start_replaces_stale_runner_image_and_preserves_workspace(
    tmp_path: Path,
) -> None:
    docker = FakeDockerApi()
    provider = _provider(tmp_path, docker)
    await provider.start(
        _command(RuntimeLifecycleCommandType.START, runner_image="runner:old")
    )
    marker = tmp_path / "agent-runtimes" / "runtime-1" / "workspace" / "keep.txt"
    marker.write_text("preserved")

    await provider.start(
        _command(RuntimeLifecycleCommandType.START, runner_image="runner:new")
    )

    assert docker.removed == ["azents-runtime-runtime-1"]
    assert docker.containers["azents-runtime-runtime-1"].spec.image == "runner:new"
    assert marker.read_text() == "preserved"


@pytest.mark.asyncio
async def test_start_reuses_container_when_runner_image_and_config_are_unchanged(
    tmp_path: Path,
) -> None:
    docker = FakeDockerApi()
    provider = _provider(tmp_path, docker)
    command = _command(RuntimeLifecycleCommandType.START)
    await provider.start(command)
    container = docker.containers["azents-runtime-runtime-1"]

    await provider.start(command)

    assert docker.removed == []
    assert docker.containers["azents-runtime-runtime-1"] is container


@pytest.mark.asyncio
async def test_configuration_update_requires_recreation_without_mutation(
    tmp_path: Path,
) -> None:
    docker = FakeDockerApi()
    provider = _provider(tmp_path, docker)
    await provider.start(_command(RuntimeLifecycleCommandType.START))
    container = docker.containers["azents-runtime-runtime-1"]
    networks = list(docker.networks)
    images = list(docker.images)

    with pytest.raises(
        UnsupportedRuntimeConfiguration,
        match="configuration changes require recreation",
    ):
        await provider.update_configuration(
            _command(RuntimeLifecycleCommandType.UPDATE_CONFIGURATION)
        )

    assert docker.containers["azents-runtime-runtime-1"] is container
    assert docker.removed == []
    assert docker.networks == networks
    assert docker.images == images


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
    assert second.report.terminal_delete_acknowledged is True
    assert "azents-runtime-runtime-1" not in docker.containers
    assert not marker.exists()


@pytest.mark.asyncio
async def test_observe_known_runtimes_ignores_unproven_directory(
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
    assert "runtime-2" not in by_runtime


@pytest.mark.asyncio
async def test_legacy_container_is_skipped_until_command_replaces_it(
    tmp_path: Path,
) -> None:
    """Legacy resources stay untrusted without terminating Provider recovery."""
    docker = FakeDockerApi()
    provider = _provider(tmp_path, docker)
    command = _command(RuntimeLifecycleCommandType.START)
    await provider.start(command)
    container = docker.containers["azents-runtime-runtime-1"]
    labels = cast(dict[str, str], container.spec.labels)
    for key in (
        "azents/runtime-configuration-revision-id",
        "azents/runtime-configuration-digest",
    ):
        labels.pop(key)

    assert await provider.observe_known_runtimes() == ()

    result = await provider.start(command)

    assert result.report.runtime_configuration == command.runtime_configuration.evidence
    replaced = docker.containers["azents-runtime-runtime-1"]
    assert (
        replaced.spec.labels["azents/runtime-configuration-revision-id"] == "revision-1"
    )


def test_invalid_workspace_path_is_rejected(tmp_path: Path) -> None:
    docker = FakeDockerApi()

    with pytest.raises(InvalidWorkspacePath):
        DockerRuntimeProvider(
            docker,
            DockerRuntimeProviderConfig(
                provider_id="provider-docker",
                host_data_root=tmp_path,
                runner_env={},
                workspace_mount_path="relative/path",
                tmp_mount_path="/tmp/agent",
                process_containment=None,
            ),
        )


@pytest.mark.parametrize(
    "security_profile",
    (
        "unconfined",
        "azents-runtime-bwrap-typo",
        " azents-runtime-bwrap",
    ),
)
def test_invalid_process_containment_security_profile_is_rejected(
    tmp_path: Path,
    security_profile: str,
) -> None:
    docker = FakeDockerApi()

    with pytest.raises(ValueError, match="security profile is unsupported"):
        DockerRuntimeProvider(
            docker,
            DockerRuntimeProviderConfig(
                provider_id="provider-docker",
                host_data_root=tmp_path,
                runner_env={},
                workspace_mount_path="/runtime/home",
                tmp_mount_path="/tmp/agent",
                process_containment=dataclasses.replace(
                    _containment_config(),
                    security_profile=security_profile,
                ),
            ),
        )


@pytest.mark.asyncio
async def test_reset_requires_explicit_final_desired_state(tmp_path: Path) -> None:
    docker = FakeDockerApi()
    provider = _provider(tmp_path, docker)

    with pytest.raises(InvalidResetFinalDesiredState):
        await provider.reset(_command(RuntimeLifecycleCommandType.RESET))


@pytest.mark.asyncio
async def test_runtime_configuration_evidence_is_persisted_and_reported(
    tmp_path: Path,
) -> None:
    docker = FakeDockerApi()
    provider = _provider(tmp_path, docker)
    configuration = _runtime_configuration()

    result = await provider.start(
        _command(RuntimeLifecycleCommandType.START, runtime_configuration=configuration)
    )

    container = docker.containers["azents-runtime-runtime-1"]
    assert container.spec.env["AZ_RUNTIME_CONFIGURATION_REVISION_ID"] == "revision-1"
    assert result.report.runtime_configuration == configuration.evidence


@pytest.mark.asyncio
async def test_kubernetes_profile_is_rejected(tmp_path: Path) -> None:
    docker = FakeDockerApi()
    provider = _provider(tmp_path, docker)

    with pytest.raises(ValueError, match="Kubernetes Pod Profile"):
        await provider.start(
            _command(
                RuntimeLifecycleCommandType.START,
                runtime_configuration=_runtime_configuration(kubernetes_profile=True),
            )
        )

    assert docker.containers == {}


@pytest.mark.asyncio
async def test_configuration_bound_to_another_provider_is_rejected(
    tmp_path: Path,
) -> None:
    docker = FakeDockerApi()
    provider = _provider(tmp_path, docker)

    with pytest.raises(UnsupportedRuntimeConfiguration, match="different Docker"):
        await provider.start(
            _command(
                RuntimeLifecycleCommandType.START,
                runtime_configuration=_runtime_configuration(
                    provider_logical_id="provider-docker-other",
                ),
            )
        )

    assert docker.containers == {}


def _runtime_configuration(
    *,
    kubernetes_profile: bool = False,
    desired_generation: int = 1,
    provider_logical_id: str = "provider-docker",
    docker_schema_version: int = 1,
    process_containment: bool = False,
) -> RuntimeConfigurationEnvelope:
    effective_profile: dict[str, JsonValue]
    if kubernetes_profile:
        effective_profile = {
            "profile_kind": "kubernetes_pod",
            "contract_family": "kubernetes.pod-profile",
            "schema_version": 1,
            "runner_resources": {
                "cpu_request_millicores": None,
                "cpu_limit_millicores": None,
                "memory_request_bytes": None,
                "memory_limit_bytes": None,
            },
            "workspace_volume": {
                "storage_class_name": "standard",
                "storage_request_bytes": 1_073_741_824,
            },
            "network_policy": {"allowed_cidrs": [], "denied_cidrs": []},
            "service_account_name": None,
            "scheduling": {"node_selector": {}, "tolerations": []},
            "dind": None,
        }
    else:
        effective_profile = {
            "profile_kind": "docker_container",
            "contract_family": "docker.container-profile",
            "schema_version": docker_schema_version,
            "runner_resources": {
                "cpu_reservation_millicores": None,
                "cpu_limit_millicores": None,
                "memory_reservation_bytes": None,
                "memory_limit_bytes": None,
            },
            "network_name": "azents-runtime",
        }
        if docker_schema_version == 2:
            effective_profile["process_containment"] = (
                {"schema_version": 1} if process_containment else None
            )
    configuration: dict[str, JsonValue] = {
        "schema_version": 1,
        "provider": {
            "id": "provider-resource-1",
            "logical_id": provider_logical_id,
            "kind": "docker",
            "capability_revision_id": "capability-1",
            "capability_digest": "a" * 64,
        },
        "infrastructure_profile": {
            "id": "infrastructure-1",
            "version": 1,
            "digest": "b" * 64,
        },
        "workspace_runtime_profile": {
            "id": "workspace-profile-1",
            "version": 1,
            "digest": "c" * 64,
        },
        "effective_profile": effective_profile,
    }
    return RuntimeConfigurationEnvelope(
        evidence=RuntimeConfigurationEvidence(
            revision_id="revision-1",
            digest="d" * 64,
            desired_generation=desired_generation,
        ),
        resolved_configuration_json=canonical_runtime_configuration_json(configuration),
    )
