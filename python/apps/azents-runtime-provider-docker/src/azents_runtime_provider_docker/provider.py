"""Docker implementation of the Agent Runtime Provider lifecycle."""

import dataclasses
import json
import logging
import os
import re
import shutil
import stat
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath

from azents_runtime_control.execution_policy import (
    RuntimeExecutionPolicyEvidence,
    validate_standard_execution_policy_envelope,
)

from azents_runtime_provider_docker.docker_api import (
    DockerApi,
    DockerBindMount,
    DockerContainerInfo,
    DockerContainerSpec,
)
from azents_runtime_provider_docker.models import (
    RuntimeDesiredState,
    RuntimeLifecycleCommand,
    RuntimeLifecycleCommandType,
    RuntimeLifecycleResult,
    RuntimeProviderObservedState,
    RuntimeProviderReport,
)

_CONTAINER_MEMORY_BYTES = 2 * 1024 * 1024 * 1024
_CONTAINER_CPU_QUOTA = 100_000
_CONTAINER_CPU_PERIOD = 100_000
_CONTAINER_PREFIX = "azents-runtime-"
_IMAGE_GENERATION = "agent-runtime-docker-v1"
_RUNTIME_ID_RE = re.compile(r"^[A-Za-z0-9_.-]+$")
_RUNNER_UID = 1000
_RUNNER_GID = 1000
_RUNNER_USER = "0:0"
_WORKSPACE_DIR_MODE = 0o755
_NON_ROOT_WORKSPACE_DIR_MODE = 0o777
_CONTROL_HOST_ALIAS = "host.docker.internal:host-gateway"
_LOGGER = logging.getLogger(__name__)
_TRANSFER_STAGING_MOUNT_PATH = "/var/run/azents-transfer"

_LABEL_MANAGED_BY = "azents/managed-by"
_LABEL_PROVIDER_ID = "azents/runtime-provider-id"
_LABEL_RUNTIME_ID = "azents/runtime-id"
_LABEL_AGENT_ID = "azents/agent-id"
_LABEL_WORKSPACE_ID = "azents/workspace-id"
_LABEL_DESIRED_GENERATION = "azents/desired-generation"
_LABEL_PROVIDER_GENERATION = "azents/provider-generation"
_LABEL_WORKSPACE_PATH = "azents/workspace-path"
_LABEL_IMAGE_GENERATION = "azents/image-generation"
_LABEL_POLICY_SNAPSHOT_ID = "azents/execution-policy-snapshot-id"
_LABEL_POLICY_DIGEST = "azents/execution-policy-digest"
_LABEL_POLICY_MODULE_VERSIONS = "azents/execution-policy-module-versions"
_LABEL_POLICY_SOURCE_VERSIONS = "azents/execution-policy-source-versions"

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
_ENV_WORKSPACE_PATH = "AZ_AGENT_WORKSPACE_PATH"
_ENV_POLICY_SNAPSHOT_ID = "AZ_RUNTIME_EXECUTION_POLICY_SNAPSHOT_ID"
_ENV_POLICY_DIGEST = "AZ_RUNTIME_EXECUTION_POLICY_DIGEST"
_ENV_POLICY_DESIRED_GENERATION = "AZ_RUNTIME_EXECUTION_POLICY_DESIRED_GENERATION"
_ENV_POLICY_MODULE_VERSIONS = "AZ_RUNTIME_EXECUTION_POLICY_MODULE_VERSIONS"
_ENV_POLICY_SOURCE_VERSIONS = "AZ_RUNTIME_EXECUTION_POLICY_SOURCE_VERSIONS"
_ENV_TRANSFER_STAGING_DIRECTORY = "AZ_RUNTIME_TRANSFER_STAGING_DIRECTORY"
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


@dataclasses.dataclass(frozen=True)
class DockerRuntimeProviderConfig:
    """Configuration for a single Docker Runtime Provider process."""

    provider_id: str
    host_data_root: Path
    docker_network: str
    runner_env: Mapping[str, str]
    workspace_mount_path: str = "/workspace/agent"
    tmp_mount_path: str = "/tmp/agent"


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
        self._validate_command(command)
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
        self._validate_command(command)
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
            ),
        )

    async def restart(
        self,
        command: RuntimeLifecycleCommand,
    ) -> RuntimeLifecycleResult:
        """Recreate the Runtime container while preserving workspace data."""
        self._validate_command(command)
        await self._ensure_container(command, replace=True)
        return RuntimeLifecycleResult(
            command_type=RuntimeLifecycleCommandType.RESTART,
            report=await self.observe(command),
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
            )
        return RuntimeLifecycleResult(
            command_type=RuntimeLifecycleCommandType.RESET,
            report=report,
        )

    async def terminal_delete(
        self,
        command: RuntimeLifecycleCommand,
    ) -> RuntimeLifecycleResult:
        """Remove the Runtime container and all Provider-owned host data."""
        self._validate_command(command)
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
                ),
                workspace_path="",
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
            )
        observed_state, reason = _observed_state(container)
        return self._report(
            command,
            observed_state=observed_state,
            reason=reason,
            provider_runtime_id=container.name,
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
        self._validate_command(command)
        container_name = _container_name(command.identity.runtime_id)
        container = await self._docker.get_container(container_name)
        if container is not None and (
            replace or not self._container_reusable(container, command)
        ):
            await self._docker.remove_container(container_name)
            container = None
        self._ensure_workspace_dirs(command.identity.runtime_id)
        await self._docker.ensure_network(self._config.docker_network)
        await self._docker.ensure_image(command.runner_image)
        if container is None:
            await self._docker.create_container(self._container_spec(command))
        await self._docker.start_container(container_name)

    def _container_spec(self, command: RuntimeLifecycleCommand) -> DockerContainerSpec:
        labels = self._labels(command)
        return DockerContainerSpec(
            name=_container_name(command.identity.runtime_id),
            image=command.runner_image,
            user=_RUNNER_USER,
            working_dir=self._workspace_mount_path,
            env=self._env(command),
            labels=labels,
            binds=self._binds(command.identity.runtime_id),
            network=self._config.docker_network,
            memory_bytes=_CONTAINER_MEMORY_BYTES,
            cpu_quota=_CONTAINER_CPU_QUOTA,
            cpu_period=_CONTAINER_CPU_PERIOD,
            extra_hosts=(_CONTROL_HOST_ALIAS,),
        )

    def _container_reusable(
        self,
        container: DockerContainerInfo,
        command: RuntimeLifecycleCommand,
    ) -> bool:
        if container.image != command.runner_image:
            return False
        if container.user != _RUNNER_USER:
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
        for key, value in self._policy_labels(command).items():
            if labels.get(key) != value:
                return False
        for key, value in self._policy_env(command).items():
            if env.get(key) != value:
                return False
        managed_runner_env = {
            key: env[key] for key in RUNNER_LIMIT_ENV_NAMES if key in env
        }
        if managed_runner_env != self._runner_env:
            return False
        return set(container.binds) == set(self._binds(command.identity.runtime_id))

    def _labels(self, command: RuntimeLifecycleCommand) -> dict[str, str]:
        return {
            **self._stable_labels(command),
            _LABEL_DESIRED_GENERATION: str(command.desired_generation),
            _LABEL_PROVIDER_GENERATION: str(command.provider_generation),
            _LABEL_IMAGE_GENERATION: _IMAGE_GENERATION,
            **self._policy_labels(command),
        }

    def _stable_labels(self, command: RuntimeLifecycleCommand) -> dict[str, str]:
        identity = command.identity
        return {
            _LABEL_MANAGED_BY: "azents-runtime-provider-docker",
            _LABEL_PROVIDER_ID: self._config.provider_id,
            _LABEL_RUNTIME_ID: identity.runtime_id,
            _LABEL_AGENT_ID: identity.agent_id,
            _LABEL_WORKSPACE_ID: identity.workspace_id,
            _LABEL_WORKSPACE_PATH: self._workspace_mount_path,
        }

    def _env(self, command: RuntimeLifecycleCommand) -> dict[str, str]:
        return {
            **self._stable_env(command),
            **self._runner_auth_env(command),
            **self._policy_env(command),
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
            _ENV_WORKSPACE_PATH: self._workspace_mount_path,
            _ENV_TRANSFER_STAGING_DIRECTORY: _TRANSFER_STAGING_MOUNT_PATH,
        }
        if command.auth.control_tls_ca_pem is not None:
            env[_ENV_CONTROL_TLS_CA_PEM] = command.auth.control_tls_ca_pem
        env[_ENV_CONTROL_ALLOW_INSECURE] = str(
            command.auth.allow_insecure_control
        ).lower()
        return env

    def _policy_labels(self, command: RuntimeLifecycleCommand) -> dict[str, str]:
        evidence = command.execution_policy.evidence
        return {
            _LABEL_POLICY_SNAPSHOT_ID: evidence.snapshot_id,
            _LABEL_POLICY_DIGEST: evidence.digest,
            _LABEL_POLICY_MODULE_VERSIONS: _canonical_mapping(evidence.module_versions),
            _LABEL_POLICY_SOURCE_VERSIONS: _canonical_mapping(evidence.source_versions),
        }

    def _policy_env(self, command: RuntimeLifecycleCommand) -> dict[str, str]:
        evidence = command.execution_policy.evidence
        return {
            _ENV_POLICY_SNAPSHOT_ID: evidence.snapshot_id,
            _ENV_POLICY_DIGEST: evidence.digest,
            _ENV_POLICY_DESIRED_GENERATION: str(evidence.desired_generation),
            _ENV_POLICY_MODULE_VERSIONS: _canonical_mapping(evidence.module_versions),
            _ENV_POLICY_SOURCE_VERSIONS: _canonical_mapping(evidence.source_versions),
        }

    def _binds(self, runtime_id: str) -> tuple[DockerBindMount, ...]:
        return (
            DockerBindMount(
                host_path=str(self._workspace_host_dir(runtime_id)),
                container_path=self._workspace_mount_path,
            ),
            DockerBindMount(
                host_path=str(self._tmp_host_dir(runtime_id)),
                container_path=self._tmp_mount_path,
            ),
            DockerBindMount(
                host_path=str(self._transfer_staging_host_dir(runtime_id)),
                container_path=_TRANSFER_STAGING_MOUNT_PATH,
            ),
        )

    def _report(
        self,
        command: RuntimeLifecycleCommand,
        *,
        observed_state: RuntimeProviderObservedState,
        reason: str,
        provider_runtime_id: str | None,
    ) -> RuntimeProviderReport:
        return RuntimeProviderReport(
            runtime_id=command.identity.runtime_id,
            provider_id=self._config.provider_id,
            provider_generation=command.provider_generation,
            observed_state=observed_state,
            observed_desired_generation=command.desired_generation,
            provider_runtime_id=provider_runtime_id,
            workspace_path=self._workspace_mount_path,
            reason=reason,
            diagnostic={},
            reported_at=datetime.now(UTC),
            terminal_delete_acknowledged=False,
            execution_policy=command.execution_policy.evidence,
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
            workspace_path=container.labels.get(
                _LABEL_WORKSPACE_PATH,
                self._workspace_mount_path,
            ),
            reason=reason,
            diagnostic={"source": "docker_container"},
            reported_at=datetime.now(UTC),
            terminal_delete_acknowledged=False,
            execution_policy=_policy_evidence_from_metadata(
                container.labels,
                desired_generation=_int_label(
                    container,
                    _LABEL_DESIRED_GENERATION,
                ),
            ),
        )

    def _validate_command(self, command: RuntimeLifecycleCommand) -> None:
        validate_standard_execution_policy_envelope(
            command.execution_policy,
            desired_generation=command.desired_generation,
        )

    def _runtime_root(self, runtime_id: str) -> Path:
        if not _RUNTIME_ID_RE.fullmatch(runtime_id):
            raise InvalidRuntimeId(runtime_id)
        return self._config.host_data_root / "agent-runtimes" / runtime_id

    def _workspace_host_dir(self, runtime_id: str) -> Path:
        return self._runtime_root(runtime_id) / "workspace"

    def _tmp_host_dir(self, runtime_id: str) -> Path:
        return self._runtime_root(runtime_id) / "tmp-agent"

    def _transfer_staging_host_dir(self, runtime_id: str) -> Path:
        return self._runtime_root(runtime_id) / "transfer-staging"

    def _ensure_workspace_dirs(self, runtime_id: str) -> None:
        _ensure_writable_dir(self._workspace_host_dir(runtime_id))
        _ensure_writable_dir(self._tmp_host_dir(runtime_id))
        _ensure_protected_staging_dir(self._transfer_staging_host_dir(runtime_id))

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


def _ensure_writable_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)
    if os.geteuid() == 0:
        os.chown(path, _RUNNER_UID, _RUNNER_GID)
        expected_mode = _WORKSPACE_DIR_MODE
    else:
        expected_mode = _NON_ROOT_WORKSPACE_DIR_MODE
    current_mode = stat.S_IMODE(path.stat().st_mode)
    if current_mode != expected_mode:
        path.chmod(expected_mode)  # noqa: S103


def _ensure_protected_staging_dir(path: Path) -> None:
    if os.geteuid() != 0:
        raise PermissionError(
            "protected Runtime transfer staging requires a root Docker provider"
        )
    try:
        path.mkdir(parents=True)
    except FileExistsError:
        pass
    descriptor = os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        metadata = os.fstat(descriptor)
        if not stat.S_ISDIR(metadata.st_mode):
            raise OSError("transfer staging path is not a directory")
        os.fchown(descriptor, 0, 0)
        os.fchmod(descriptor, 0o700)
        metadata = os.fstat(descriptor)
        if metadata.st_uid != 0 or stat.S_IMODE(metadata.st_mode) != 0o700:
            raise PermissionError(
                "transfer staging directory protection was not applied"
            )
    finally:
        os.close(descriptor)


def _observed_state(
    container: DockerContainerInfo,
) -> tuple[RuntimeProviderObservedState, str]:
    if container.state.running:
        return RuntimeProviderObservedState.RUNNING, "container_running"
    if container.state.restarting:
        return RuntimeProviderObservedState.STARTING, "container_restarting"
    if _terminal_container(container):
        return RuntimeProviderObservedState.FAILED, "container_terminal"
    return RuntimeProviderObservedState.STARTING, "container_created"


def _terminal_container(container: DockerContainerInfo) -> bool:
    return bool(
        container.state.dead or container.state.status in {"exited", "removing"}
    )


def _int_label(container: DockerContainerInfo, key: str) -> int:
    value = container.labels.get(key)
    if value is None:
        return 0
    try:
        return int(value)
    except ValueError:
        return 0


def _canonical_mapping(values: Mapping[str, int]) -> str:
    return json.dumps(dict(values), sort_keys=True, separators=(",", ":"))


def _policy_evidence_from_metadata(
    values: Mapping[str, str],
    *,
    desired_generation: int,
) -> RuntimeExecutionPolicyEvidence:
    snapshot_id = values.get(_LABEL_POLICY_SNAPSHOT_ID)
    digest = values.get(_LABEL_POLICY_DIGEST)
    module_versions = values.get(_LABEL_POLICY_MODULE_VERSIONS)
    source_versions = values.get(_LABEL_POLICY_SOURCE_VERSIONS)
    if (
        snapshot_id is None
        or digest is None
        or module_versions is None
        or source_versions is None
    ):
        raise ValueError("Runtime execution-policy metadata is incomplete.")
    try:
        parsed_modules = json.loads(module_versions)
        parsed_sources = json.loads(source_versions)
        if not isinstance(parsed_modules, dict) or not isinstance(parsed_sources, dict):
            raise ValueError("Runtime execution-policy metadata is invalid.")
        return RuntimeExecutionPolicyEvidence(
            snapshot_id=str(snapshot_id),
            digest=str(digest),
            desired_generation=desired_generation,
            module_versions={
                str(key): int(value) for key, value in parsed_modules.items()
            },
            source_versions={
                str(key): int(value) for key, value in parsed_sources.items()
            },
        )
    except (TypeError, ValueError, json.JSONDecodeError) as error:
        raise ValueError("Runtime execution-policy metadata is invalid.") from error
