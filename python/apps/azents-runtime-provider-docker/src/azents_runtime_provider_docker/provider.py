"""Docker implementation of the Agent Runtime Provider lifecycle."""

import dataclasses
import logging
import os
import re
import shutil
import stat
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath

from azents_runtime_control.provider import (
    RuntimeDesiredState,
    RuntimeLifecycleCommand,
    RuntimeLifecycleCommandType,
    RuntimeLifecycleResult,
    RuntimeProviderObservedState,
    RuntimeProviderReport,
)
from azents_runtime_control.runtime_configuration import (
    DockerContainerProfileV1,
    DockerContainerProfileV2,
    RuntimeConfigurationEvidence,
    parse_configuration_sequence,
    parse_runtime_configuration_envelope,
    serialize_configuration_sequence,
    validate_runtime_configuration_cleanup_envelope,
)

from azents_runtime_provider_docker.docker_api import (
    DockerApi,
    DockerBindMount,
    DockerContainerInfo,
    DockerContainerSpec,
)

_CONTAINER_CPU_PERIOD = 100_000
_CONTAINER_PREFIX = "azents-runtime-"
_IMAGE_GENERATION = "agent-runtime-docker-v1"
_RUNTIME_ID_RE = re.compile(r"^[A-Za-z0-9_.-]+$")
_RUNNER_UID = 1000
_RUNNER_GID = 1000
_RUNNER_USER = f"{_RUNNER_UID}:{_RUNNER_GID}"
_WORKSPACE_DIR_MODE = 0o755
_NON_ROOT_WORKSPACE_DIR_MODE = 0o777
_CONTROL_HOST_ALIAS = "host.docker.internal:host-gateway"
_SECURITY_OPTIONS = ("no-new-privileges",)
_CAP_DROP = ("ALL",)
_LOGGER = logging.getLogger(__name__)

_LABEL_MANAGED_BY = "azents/managed-by"
_LABEL_PROVIDER_ID = "azents/runtime-provider-id"
_LABEL_RUNTIME_ID = "azents/runtime-id"
_LABEL_AGENT_ID = "azents/agent-id"
_LABEL_WORKSPACE_ID = "azents/workspace-id"
_LABEL_DESIRED_GENERATION = "azents/desired-generation"
_LABEL_PROVIDER_GENERATION = "azents/provider-generation"
_LABEL_IMAGE_GENERATION = "azents/image-generation"
_LABEL_CONFIGURATION_SEQUENCE = "azents/runtime-configuration-sequence"
_LABEL_CONFIGURATION_DIGEST = "azents/runtime-configuration-digest"

_ENV_CONTROL_ENDPOINT = "AZ_RUNTIME_CONTROL_ENDPOINT"
_ENV_TRANSFER_ENDPOINT = "AZ_RUNTIME_TRANSFER_ENDPOINT"
_ENV_CONTROL_TLS_CA_PEM = "AZ_RUNTIME_CONTROL_TLS_CA_PEM"
_ENV_CONTROL_ALLOW_INSECURE = "AZ_RUNTIME_CONTROL_ALLOW_INSECURE"
_ENV_RUNTIME_ID = "AZ_RUNTIME_ID"
_ENV_AGENT_ID = "AZ_AGENT_ID"
_ENV_WORKSPACE_ID = "AZ_WORKSPACE_ID"
_ENV_PROVIDER_ID = "AZ_RUNTIME_PROVIDER_ID"
_ENV_PROVIDER_GENERATION = "AZ_RUNTIME_PROVIDER_GENERATION"
_ENV_DESIRED_GENERATION = "AZ_RUNTIME_DESIRED_GENERATION"
_ENV_RUNNER_AUTH_TOKEN = "AZ_RUNTIME_RUNNER_AUTH_TOKEN"
_ENV_RUNNER_AUTH_CREDENTIAL_ID = "AZ_RUNTIME_RUNNER_AUTH_CREDENTIAL_ID"
_ENV_HOME = "HOME"
_ENV_CONFIGURATION_SEQUENCE = "AZ_RUNTIME_CONFIGURATION_SEQUENCE"
_ENV_CONFIGURATION_DIGEST = "AZ_RUNTIME_CONFIGURATION_DIGEST"
_ENV_CONFIGURATION_DESIRED_GENERATION = "AZ_RUNTIME_CONFIGURATION_DESIRED_GENERATION"
RUNNER_LIMIT_ENV_NAMES = (
    "AZ_RUNTIME_RUNNER_MAX_CONCURRENT_OPERATIONS_PER_SESSION",
    "AZ_RUNTIME_RUNNER_MAX_CONCURRENT_SYSTEM_OPERATIONS",
    "AZ_RUNTIME_RUNNER_MAX_CONCURRENT_OPERATIONS",
    "AZ_RUNTIME_RUNNER_MAX_PENDING_OPERATIONS_PER_OWNER",
    "AZ_RUNTIME_RUNNER_MAX_PENDING_OPERATIONS",
    "AZ_RUNTIME_RUNNER_MAX_CONCURRENT_CONTROL_OPERATIONS",
)


class InvalidRuntimeId(ValueError):
    """Runtime id cannot be mapped to a provider-managed host path."""


class InvalidWorkspacePath(ValueError):
    """Provider workspace mount path is missing or not absolute."""


class InvalidRunnerEnvironment(ValueError):
    """Runner environment contains a variable not managed by the Provider."""


class InvalidResetFinalDesiredState(ValueError):
    """Reset command did not provide an explicit final desired state."""


class UnsupportedRuntimeConfiguration(ValueError):
    """Resolved configuration cannot be enforced by the Docker Provider."""


@dataclasses.dataclass(frozen=True)
class DockerRuntimeProviderConfig:
    """Configuration for a single Docker Runtime Provider process."""

    provider_id: str
    host_data_root: Path
    runner_env: Mapping[str, str]
    workspace_mount_path: str
    tmp_mount_path: str


class DockerRuntimeProvider:
    """Lifecycle-only Runtime Provider backed by a single Docker host."""

    def __init__(self, docker: DockerApi, config: DockerRuntimeProviderConfig) -> None:
        """Initialize the Docker Provider.

        :param docker: Docker API implementation
        :param config: Provider process configuration
        """
        unknown_runner_env = set(config.runner_env).difference(RUNNER_LIMIT_ENV_NAMES)
        if unknown_runner_env:
            raise InvalidRunnerEnvironment(
                f"unsupported Runner environment variables: "
                f"{', '.join(sorted(unknown_runner_env))}"
            )
        self._docker = docker
        self._config = config
        self._runner_env = dict(config.runner_env)
        self._workspace_mount_path = _absolute_posix_path(config.workspace_mount_path)
        self._tmp_mount_path = _absolute_posix_path(config.tmp_mount_path)

    async def start(
        self,
        command: RuntimeLifecycleCommand,
    ) -> RuntimeLifecycleResult:
        """Start or create the Runtime container while preserving workspace data."""
        await self._ensure_container(command, replace=False)
        return RuntimeLifecycleResult(
            command_type=RuntimeLifecycleCommandType.START,
            report=await self.observe(command),
        )

    async def stop(
        self,
        command: RuntimeLifecycleCommand,
    ) -> RuntimeLifecycleResult:
        """Stop the Runtime container without deleting workspace data."""
        self._validate_cleanup_command(command)
        await self._docker.remove_container(
            _container_name(command.identity.runtime_id)
        )
        return RuntimeLifecycleResult(
            command_type=RuntimeLifecycleCommandType.STOP,
            report=self._report(
                command,
                observed_state=RuntimeProviderObservedState.STOPPED,
                reason="container_removed",
                provider_runtime_id=None,
                diagnostic={},
            ),
        )

    async def restart(
        self,
        command: RuntimeLifecycleCommand,
    ) -> RuntimeLifecycleResult:
        """Delete the Runtime container and preserve workspace data."""
        self._validate_command(command)
        await self._remove_owned_container(command)
        return RuntimeLifecycleResult(
            command_type=RuntimeLifecycleCommandType.RESTART,
            report=self._report(
                command,
                observed_state=RuntimeProviderObservedState.STOPPED,
                reason="restart_container_removed",
                provider_runtime_id=None,
                diagnostic={},
            ),
        )

    async def reset(
        self,
        command: RuntimeLifecycleCommand,
    ) -> RuntimeLifecycleResult:
        """Delete workspace data, then converge to the reset final desired state."""
        self._validate_command(command)
        if command.reset_final_desired_state is None:
            raise InvalidResetFinalDesiredState("reset final desired state is required")
        await self._docker.remove_container(
            _container_name(command.identity.runtime_id)
        )
        self._delete_runtime_root(command.identity.runtime_id)
        if command.reset_final_desired_state is RuntimeDesiredState.RUNNING:
            await self._ensure_container(command, replace=False)
            report = await self.observe(command)
        else:
            self._ensure_workspace_dirs(command.identity.runtime_id)
            report = self._report(
                command,
                observed_state=RuntimeProviderObservedState.STOPPED,
                reason="reset_workspace_recreated",
                provider_runtime_id=None,
                diagnostic={},
            )
        return RuntimeLifecycleResult(
            command_type=RuntimeLifecycleCommandType.RESET,
            report=report,
        )

    async def update_configuration(
        self,
        command: RuntimeLifecycleCommand,
    ) -> RuntimeLifecycleResult:
        """Reject unsupported in-place Docker configuration changes."""
        raise UnsupportedRuntimeConfiguration(
            "Docker Runtime configuration changes require recreation."
        )

    async def terminal_delete(
        self,
        command: RuntimeLifecycleCommand,
    ) -> RuntimeLifecycleResult:
        """Remove the Runtime container and all Provider-owned host data."""
        self._validate_cleanup_command(command)
        await self._docker.remove_container(
            _container_name(command.identity.runtime_id)
        )
        self._delete_runtime_root(command.identity.runtime_id)
        return RuntimeLifecycleResult(
            command_type=RuntimeLifecycleCommandType.TERMINAL_DELETE,
            report=dataclasses.replace(
                self._report(
                    command,
                    observed_state=RuntimeProviderObservedState.STOPPED,
                    reason="terminal_resources_absent",
                    provider_runtime_id=None,
                    diagnostic={},
                ),
                terminal_delete_acknowledged=True,
            ),
        )

    async def observe(
        self,
        command: RuntimeLifecycleCommand,
    ) -> RuntimeProviderReport:
        """Observe one Runtime container and report Provider-owned metadata."""
        self._validate_command(command)
        container = await self._docker.get_container(
            _container_name(command.identity.runtime_id)
        )
        if container is None:
            return self._report(
                command,
                observed_state=RuntimeProviderObservedState.STOPPED,
                reason="container_absent",
                provider_runtime_id=None,
                diagnostic={},
            )
        observed_state, reason = _observed_state(container)
        return self._report(
            command,
            observed_state=observed_state,
            reason=reason,
            provider_runtime_id=container.name,
            diagnostic=_container_diagnostic(container),
        )

    async def observe_known_runtimes(self) -> tuple[RuntimeProviderReport, ...]:
        """Scan labelled containers and host directories after Provider restart."""
        reports: list[RuntimeProviderReport] = []
        seen_runtime_ids: set[str] = set()
        containers = await self._docker.list_containers(
            {
                _LABEL_MANAGED_BY: "azents-runtime-provider-docker",
                _LABEL_PROVIDER_ID: self._config.provider_id,
            }
        )
        for container in containers:
            runtime_id = container.labels.get(_LABEL_RUNTIME_ID)
            if runtime_id is None:
                continue
            try:
                report = self._report_from_container(container)
            except ValueError:
                _LOGGER.warning(
                    "Docker Runtime observation skipped without trusted policy "
                    "evidence",
                    extra={
                        "runtime_id": runtime_id,
                        "provider_id": self._config.provider_id,
                        "container_name": container.name,
                    },
                )
                continue
            seen_runtime_ids.add(runtime_id)
            reports.append(report)

        return tuple(reports)

    async def _ensure_container(
        self,
        command: RuntimeLifecycleCommand,
        *,
        replace: bool,
    ) -> None:
        profile = self._validate_command(command)
        runtime_id = command.identity.runtime_id
        container_name = _container_name(runtime_id)
        container = await self._docker.get_container(container_name)
        if container is not None and (
            replace or not self._container_reusable(container, command, profile)
        ):
            await self._docker.remove_container(container_name)
            container = None
        self._ensure_workspace_dirs(runtime_id)
        if profile.network_name is None:
            raise UnsupportedRuntimeConfiguration(
                "Docker Container Profile requires a Provider-managed network name."
            )
        await self._docker.ensure_network(profile.network_name)
        await self._docker.ensure_image(command.runner_image)
        if container is None:
            await self._docker.create_container(
                self._container_spec(command, profile=profile)
            )
        await self._docker.start_container(container_name)

    async def _remove_owned_container(
        self,
        command: RuntimeLifecycleCommand,
    ) -> None:
        container_name = _container_name(command.identity.runtime_id)
        container = await self._docker.get_container(container_name)
        if container is None:
            return
        labels = dict(container.labels)
        if any(
            labels.get(key) != value
            for key, value in self._stable_labels(command).items()
        ):
            raise UnsupportedRuntimeConfiguration(
                "Docker container name is owned by a different Runtime or Provider."
            )
        await self._docker.remove_container(container_name)

    def _container_spec(
        self,
        command: RuntimeLifecycleCommand,
        *,
        profile: DockerContainerProfileV1 | DockerContainerProfileV2,
    ) -> DockerContainerSpec:
        labels = self._labels(command)
        if profile.network_name is None:
            raise UnsupportedRuntimeConfiguration(
                "Docker Container Profile requires a Provider-managed network name."
            )
        resources = profile.runner_resources
        return DockerContainerSpec(
            name=_container_name(command.identity.runtime_id),
            image=command.runner_image,
            user=_RUNNER_USER,
            working_dir=self._workspace_mount_path,
            env=self._env(command),
            labels=labels,
            binds=self._binds(command.identity.runtime_id),
            network=profile.network_name,
            memory_bytes=resources.memory_limit_bytes,
            memory_reservation_bytes=resources.memory_reservation_bytes,
            cpu_quota=_cpu_quota(resources.cpu_limit_millicores),
            cpu_period=_CONTAINER_CPU_PERIOD,
            cpu_shares=_cpu_shares(resources.cpu_reservation_millicores),
            extra_hosts=(_CONTROL_HOST_ALIAS,),
            cap_add=(),
            cap_drop=_CAP_DROP,
            security_options=_SECURITY_OPTIONS,
            userns_mode=None,
            masked_paths=None,
            readonly_paths=None,
            privileged=False,
        )

    def _container_reusable(
        self,
        container: DockerContainerInfo,
        command: RuntimeLifecycleCommand,
        profile: DockerContainerProfileV1 | DockerContainerProfileV2,
    ) -> bool:
        if container.image != command.runner_image:
            return False
        if _terminal_container(container):
            return False
        labels = dict(container.labels)
        for key, value in self._stable_labels(command).items():
            if labels.get(key) != value:
                return False
        if labels.get(_LABEL_IMAGE_GENERATION) != _IMAGE_GENERATION:
            return False
        env = dict(container.env)
        for key, value in self._stable_env(command).items():
            if env.get(key) != value:
                return False
        for key, value in self._runner_auth_env(command).items():
            if env.get(key) != value:
                return False
        for key, value in self._configuration_labels(command).items():
            if labels.get(key) != value:
                return False
        for key, value in self._configuration_env(command).items():
            if env.get(key) != value:
                return False
        managed_runner_env = {
            key: env[key] for key in RUNNER_LIMIT_ENV_NAMES if key in env
        }
        if managed_runner_env != self._runner_env:
            return False
        expected = self._container_spec(command, profile=profile)
        return bool(
            container.user == expected.user
            and set(container.binds) == set(expected.binds)
            and set(container.cap_add) == set(expected.cap_add)
            and set(container.cap_drop) == set(expected.cap_drop)
            and set(container.security_options) == set(expected.security_options)
            and container.userns_mode == expected.userns_mode
            and (
                expected.masked_paths is None
                or set(container.masked_paths) == set(expected.masked_paths)
            )
            and (
                expected.readonly_paths is None
                or set(container.readonly_paths) == set(expected.readonly_paths)
            )
            and container.privileged == expected.privileged
        )

    def _labels(self, command: RuntimeLifecycleCommand) -> dict[str, str]:
        return {
            **self._stable_labels(command),
            _LABEL_DESIRED_GENERATION: str(command.desired_generation),
            _LABEL_PROVIDER_GENERATION: str(command.provider_generation),
            _LABEL_IMAGE_GENERATION: _IMAGE_GENERATION,
            **self._configuration_labels(command),
        }

    def _stable_labels(self, command: RuntimeLifecycleCommand) -> dict[str, str]:
        identity = command.identity
        return {
            _LABEL_MANAGED_BY: "azents-runtime-provider-docker",
            _LABEL_PROVIDER_ID: self._config.provider_id,
            _LABEL_RUNTIME_ID: identity.runtime_id,
            _LABEL_AGENT_ID: identity.agent_id,
            _LABEL_WORKSPACE_ID: identity.workspace_id,
        }

    def _env(self, command: RuntimeLifecycleCommand) -> dict[str, str]:
        return {
            **self._stable_env(command),
            **self._runner_auth_env(command),
            **self._configuration_env(command),
            _ENV_PROVIDER_GENERATION: str(command.provider_generation),
        }

    def _runner_auth_env(self, command: RuntimeLifecycleCommand) -> dict[str, str]:
        return {
            _ENV_DESIRED_GENERATION: str(command.desired_generation),
            _ENV_RUNNER_AUTH_TOKEN: command.auth.runner_auth_token,
            _ENV_RUNNER_AUTH_CREDENTIAL_ID: command.auth.runner_auth_credential_id,
        }

    def _stable_env(self, command: RuntimeLifecycleCommand) -> dict[str, str]:
        identity = command.identity
        env = {
            **self._runner_env,
            _ENV_CONTROL_ENDPOINT: command.auth.control_endpoint,
            _ENV_TRANSFER_ENDPOINT: command.auth.transfer_endpoint,
            _ENV_RUNTIME_ID: identity.runtime_id,
            _ENV_AGENT_ID: identity.agent_id,
            _ENV_WORKSPACE_ID: identity.workspace_id,
            _ENV_PROVIDER_ID: self._config.provider_id,
            _ENV_HOME: self._workspace_mount_path,
        }
        if command.auth.control_tls_ca_pem is not None:
            env[_ENV_CONTROL_TLS_CA_PEM] = command.auth.control_tls_ca_pem
        env[_ENV_CONTROL_ALLOW_INSECURE] = str(
            command.auth.allow_insecure_control
        ).lower()
        return env

    def _configuration_labels(
        self,
        command: RuntimeLifecycleCommand,
    ) -> dict[str, str]:
        evidence = command.runtime_configuration.evidence
        return {
            _LABEL_CONFIGURATION_SEQUENCE: serialize_configuration_sequence(
                evidence.configuration_sequence
            ),
            _LABEL_CONFIGURATION_DIGEST: evidence.digest,
        }

    def _configuration_env(
        self,
        command: RuntimeLifecycleCommand,
    ) -> dict[str, str]:
        evidence = command.runtime_configuration.evidence
        return {
            _ENV_CONFIGURATION_SEQUENCE: serialize_configuration_sequence(
                evidence.configuration_sequence
            ),
            _ENV_CONFIGURATION_DIGEST: evidence.digest,
            _ENV_CONFIGURATION_DESIRED_GENERATION: str(evidence.desired_generation),
        }

    def _binds(self, runtime_id: str) -> tuple[DockerBindMount, ...]:
        return (
            DockerBindMount(
                host_path=str(self._workspace_host_dir(runtime_id)),
                container_path=self._workspace_mount_path,
                read_only=False,
            ),
            DockerBindMount(
                host_path=str(self._tmp_host_dir(runtime_id)),
                container_path=self._tmp_mount_path,
                read_only=False,
            ),
        )

    def _report(
        self,
        command: RuntimeLifecycleCommand,
        *,
        observed_state: RuntimeProviderObservedState,
        reason: str,
        provider_runtime_id: str | None,
        diagnostic: Mapping[str, str],
    ) -> RuntimeProviderReport:
        return RuntimeProviderReport(
            runtime_id=command.identity.runtime_id,
            provider_id=self._config.provider_id,
            provider_generation=command.provider_generation,
            observed_state=observed_state,
            observed_desired_generation=command.desired_generation,
            provider_runtime_id=provider_runtime_id,
            reason=reason,
            diagnostic=diagnostic,
            reported_at=datetime.now(UTC),
            terminal_delete_acknowledged=False,
            runtime_configuration=command.runtime_configuration.evidence,
            reconciliation=None,
        )

    def _report_from_container(
        self,
        container: DockerContainerInfo,
    ) -> RuntimeProviderReport:
        observed_state, reason = _observed_state(container)
        return RuntimeProviderReport(
            runtime_id=container.labels[_LABEL_RUNTIME_ID],
            provider_id=self._config.provider_id,
            provider_generation=_int_label(container, _LABEL_PROVIDER_GENERATION),
            observed_state=observed_state,
            observed_desired_generation=_int_label(
                container, _LABEL_DESIRED_GENERATION
            ),
            provider_runtime_id=container.name,
            reason=reason,
            diagnostic={
                "source": "docker_container",
                **_container_diagnostic(container),
            },
            reported_at=datetime.now(UTC),
            terminal_delete_acknowledged=False,
            runtime_configuration=_configuration_evidence_from_metadata(
                container.labels,
                desired_generation=_int_label(
                    container,
                    _LABEL_DESIRED_GENERATION,
                ),
            ),
            reconciliation=None,
        )

    def _validate_command(
        self,
        command: RuntimeLifecycleCommand,
    ) -> DockerContainerProfileV1 | DockerContainerProfileV2:
        configuration = parse_runtime_configuration_envelope(
            command.runtime_configuration,
            desired_generation=command.desired_generation,
            expected_provider_kind="docker",
        )
        if configuration.provider.logical_id != self._config.provider_id:
            raise UnsupportedRuntimeConfiguration(
                "Runtime configuration is bound to a different Docker Provider."
            )
        profile = configuration.effective_profile
        if not isinstance(
            profile,
            DockerContainerProfileV1 | DockerContainerProfileV2,
        ):
            raise UnsupportedRuntimeConfiguration(
                "Docker Runtime Provider requires a Docker Container Profile."
            )
        return profile

    def _validate_cleanup_command(self, command: RuntimeLifecycleCommand) -> None:
        provider = validate_runtime_configuration_cleanup_envelope(
            command.runtime_configuration,
            desired_generation=command.desired_generation,
            expected_provider_kind="docker",
        )
        if provider.logical_id != self._config.provider_id:
            raise UnsupportedRuntimeConfiguration(
                "Runtime configuration is bound to a different Docker Provider."
            )

    def _runtime_root(self, runtime_id: str) -> Path:
        if not _RUNTIME_ID_RE.fullmatch(runtime_id):
            raise InvalidRuntimeId(runtime_id)
        return self._config.host_data_root / "agent-runtimes" / runtime_id

    def _workspace_host_dir(self, runtime_id: str) -> Path:
        return self._runtime_root(runtime_id) / "workspace"

    def _tmp_host_dir(self, runtime_id: str) -> Path:
        return self._runtime_root(runtime_id) / "tmp-agent"

    def _ensure_workspace_dirs(self, runtime_id: str) -> None:
        mode = _provider_directory_mode()
        _ensure_writable_dir(self._workspace_host_dir(runtime_id), mode=mode)
        _ensure_writable_dir(self._tmp_host_dir(runtime_id), mode=mode)

    def _delete_runtime_root(self, runtime_id: str) -> None:
        runtime_root = self._runtime_root(runtime_id)
        if runtime_root.exists():
            shutil.rmtree(runtime_root)


def _absolute_posix_path(raw_path: str) -> str:
    path = PurePosixPath(raw_path.strip())
    if not raw_path.strip() or not path.is_absolute():
        raise InvalidWorkspacePath(raw_path)
    return str(path)


def _container_name(runtime_id: str) -> str:
    if not _RUNTIME_ID_RE.fullmatch(runtime_id):
        raise InvalidRuntimeId(runtime_id)
    return f"{_CONTAINER_PREFIX}{runtime_id}"


def _provider_directory_mode() -> int:
    return _WORKSPACE_DIR_MODE if os.geteuid() == 0 else _NON_ROOT_WORKSPACE_DIR_MODE


def _ensure_writable_dir(path: Path, *, mode: int) -> None:
    path.mkdir(parents=True, exist_ok=True)
    if os.geteuid() == 0:
        os.chown(path, _RUNNER_UID, _RUNNER_GID)
    current_mode = stat.S_IMODE(path.stat().st_mode)
    if current_mode != mode:
        path.chmod(mode)  # noqa: S103


def _observed_state(
    container: DockerContainerInfo,
) -> tuple[RuntimeProviderObservedState, str]:
    if container.state.running:
        return RuntimeProviderObservedState.RUNNING, "container_running"
    if container.state.restarting:
        return RuntimeProviderObservedState.STARTING, "container_restarting"
    if container.state.oom_killed:
        return RuntimeProviderObservedState.FAILED, "container_oom_killed"
    if container.state.dead:
        return RuntimeProviderObservedState.FAILED, "container_dead"
    if container.state.status == "exited":
        return RuntimeProviderObservedState.FAILED, "container_exited"
    if container.state.status == "removing":
        return RuntimeProviderObservedState.FAILED, "container_removing"
    return RuntimeProviderObservedState.STARTING, "container_created"


def _terminal_container(container: DockerContainerInfo) -> bool:
    return bool(
        container.state.dead or container.state.status in {"exited", "removing"}
    )


def _container_diagnostic(container: DockerContainerInfo) -> dict[str, str]:
    if not _terminal_container(container):
        return {}
    diagnostic = {
        "source": "docker_container",
        "oom_killed": str(container.state.oom_killed).lower(),
    }
    if container.state.exit_code is not None:
        diagnostic["exit_code"] = str(container.state.exit_code)
    return diagnostic


def _int_label(container: DockerContainerInfo, key: str) -> int:
    value = container.labels.get(key)
    if value is None:
        return 0
    try:
        return int(value)
    except ValueError:
        return 0


def _configuration_evidence_from_metadata(
    values: Mapping[str, str],
    *,
    desired_generation: int,
) -> RuntimeConfigurationEvidence:
    configuration_sequence = values.get(_LABEL_CONFIGURATION_SEQUENCE)
    digest = values.get(_LABEL_CONFIGURATION_DIGEST)
    if configuration_sequence is None or digest is None:
        raise ValueError("Runtime configuration metadata is incomplete.")
    return RuntimeConfigurationEvidence(
        configuration_sequence=parse_configuration_sequence(configuration_sequence),
        digest=digest,
        desired_generation=desired_generation,
    )


def _cpu_quota(limit_millicores: int | None) -> int | None:
    if limit_millicores is None:
        return None
    return max(1, limit_millicores * _CONTAINER_CPU_PERIOD // 1000)


def _cpu_shares(reservation_millicores: int | None) -> int | None:
    if reservation_millicores is None:
        return None
    return max(2, reservation_millicores * 1024 // 1000)
