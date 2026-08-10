"""Docker Provider process entrypoint."""

import asyncio
import logging
import os
import signal
import uuid
from collections.abc import Sequence
from pathlib import Path

import grpc
from azents_runtime_control.grpc_provider_client import (
    PROVIDER_AUTH_METHOD_AZENTS_ISSUED_TOKEN,
    GrpcProviderControlClient,
    RuntimeProviderControlStreamClosed,
)
from azents_runtime_control.grpc_tls import GrpcClientTlsConfig
from azents_runtime_control.provider import (
    JsonValue,
    ProviderConnectionRejected,
    ProviderRegistration,
    ProviderRunLoop,
)

from azents_runtime_provider_docker.aiodocker_api import AioDockerApi
from azents_runtime_provider_docker.provider import (
    DOCKER_BWRAP_APPARMOR_PROFILE,
    RUNNER_LIMIT_ENV_NAMES,
    DockerProcessContainmentConfig,
    DockerRuntimeProvider,
    DockerRuntimeProviderConfig,
)

_PROTOCOL_VERSION = "agent-runtime-provider-docker-v1"
_CONFIG_SCHEMA_VERSION = "agent-runtime-provider-docker-v1"
_DEFAULT_COMMAND_BLOCK_MS = 5_000
_CONTROL_RECONNECT_DELAY_SECONDS = 1.0
_DOCKER_APPARMOR_SECURITY_OPTION = "name=apparmor"
_LOGGER = logging.getLogger(__name__)


def main() -> None:
    """Start the Docker Runtime Provider process."""
    logging.basicConfig(
        level=os.environ.get("AZ_LOG_LEVEL", "INFO").upper(),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    asyncio.run(_main())


async def _main() -> None:
    settings = _settings_from_env()
    _LOGGER.info(
        "Runtime Docker Provider process starting",
        extra={
            "provider_id": settings.provider_id,
            "connection_id": settings.connection_id,
            "control_endpoint": settings.control_endpoint,
            "host_data_root": str(settings.host_data_root),
        },
    )
    docker = AioDockerApi(docker_host=settings.docker_host)
    try:
        stop = asyncio.Event()
        loop = asyncio.get_running_loop()
        for signum in (signal.SIGINT, signal.SIGTERM):
            loop.add_signal_handler(signum, stop.set)
        await _run_control_loop(settings, docker, stop=stop)
    finally:
        await docker.close()


async def _run_control_loop(
    settings: "ProviderSettings",
    docker: AioDockerApi,
    *,
    stop: asyncio.Event,
) -> None:
    process_containment = settings.process_containment
    if process_containment is not None:
        process_containment = _effective_process_containment(
            settings,
            await docker.security_options(),
        )
    provider = DockerRuntimeProvider(
        docker,
        DockerRuntimeProviderConfig(
            provider_id=settings.provider_id,
            host_data_root=settings.host_data_root,
            runner_env=settings.runner_env,
            workspace_mount_path=settings.workspace_path,
            tmp_mount_path=settings.tmp_path,
            process_containment=process_containment,
        ),
    )
    registration = _provider_registration(
        settings,
        process_containment=process_containment,
    )
    while not stop.is_set():
        control_client = create_provider_control_client(settings)
        connection_id = _control_connection_id(settings.connection_id)
        _LOGGER.info(
            "Runtime Provider connecting to Control",
            extra={
                "provider_id": settings.provider_id,
                "connection_id": connection_id,
                "control_endpoint": settings.control_endpoint,
            },
        )
        run_loop = ProviderRunLoop(
            client=control_client,
            lifecycle=provider,
            registration=registration,
            connection_id=connection_id,
            consumer_id=f"{connection_id}:provider",
        )
        try:
            await run_loop.run_forever(
                stop=stop,
                command_block_ms=_DEFAULT_COMMAND_BLOCK_MS,
            )
        except asyncio.CancelledError:
            raise
        except (
            RuntimeProviderControlStreamClosed,
            ProviderConnectionRejected,
            TimeoutError,
            grpc.aio.AioRpcError,
        ):
            if stop.is_set():
                return
            _LOGGER.warning(
                "Runtime Provider Control stream disconnected; reconnecting",
                exc_info=True,
                extra={"provider_id": settings.provider_id},
            )
            await _wait_for_reconnect(stop)
        finally:
            await control_client.close()


def create_provider_control_client(
    settings: "ProviderSettings",
) -> GrpcProviderControlClient:
    """Create the Docker Provider's explicit issued-token Control client."""
    return GrpcProviderControlClient.from_endpoint(
        settings.control_endpoint,
        provider_credential=settings.provider_credential,
        provider_auth_method=PROVIDER_AUTH_METHOD_AZENTS_ISSUED_TOKEN,
        tls=settings.control_tls,
        allow_insecure=settings.allow_insecure_control,
    )


class ProviderSettings:
    """Runtime Docker Provider process settings from environment variables."""

    def __init__(self) -> None:
        """Load deployment-critical settings from the environment."""
        self.control_endpoint = _required_env("AZ_RUNTIME_CONTROL_ENDPOINT")
        self.control_tls = _control_tls_from_env()
        self.allow_insecure_control = _required_bool_env(
            "AZ_RUNTIME_CONTROL_ALLOW_INSECURE"
        )
        self.provider_id = _required_env("AZ_RUNTIME_PROVIDER_ID")
        self.host_data_root = Path(_required_env("AZ_RUNTIME_PROVIDER_HOST_DATA_ROOT"))
        self.workspace_path = _required_env("AZ_RUNTIME_PROVIDER_WORKSPACE_PATH")
        self.tmp_path = os.environ.get("AZ_RUNTIME_PROVIDER_TMP_PATH", "/tmp/agent")
        self.runner_env = _runner_env_from_env()
        self.process_containment = _process_containment_from_env()
        self.docker_host = os.environ.get("AZ_RUNTIME_PROVIDER_DOCKER_HOST")
        self.connection_id = os.environ.get(
            "AZ_RUNTIME_PROVIDER_CONNECTION_ID",
            f"{self.provider_id}:{uuid.uuid4().hex}",
        )
        self.provider_credential = _required_env("AZ_RUNTIME_PROVIDER_CREDENTIAL")


def _settings_from_env() -> ProviderSettings:
    return ProviderSettings()


def _runner_env_from_env() -> dict[str, str]:
    return {
        name: value
        for name in RUNNER_LIMIT_ENV_NAMES
        if (value := os.environ.get(name)) is not None
    }


def _process_containment_from_env() -> DockerProcessContainmentConfig | None:
    backend = os.environ.get("AZ_RUNTIME_PROVIDER_PROCESS_CONTAINMENT_BACKEND")
    security_profile = os.environ.get(
        "AZ_RUNTIME_PROVIDER_PROCESS_CONTAINMENT_SECURITY_PROFILE"
    )
    timeout = os.environ.get(
        "AZ_RUNTIME_PROVIDER_PROCESS_CONTAINMENT_QUALIFICATION_TIMEOUT_SECONDS"
    )
    if backend is None:
        if security_profile is not None or timeout is not None:
            raise RuntimeError(
                "Docker process containment settings require a configured backend."
            )
        return None
    if backend != "bwrap":
        raise RuntimeError("Docker process containment backend is unsupported.")
    if security_profile is None or not security_profile:
        raise RuntimeError("Docker process containment security profile is required.")
    if security_profile != DOCKER_BWRAP_APPARMOR_PROFILE:
        raise RuntimeError(
            "Docker process containment security profile is unsupported."
        )
    if timeout is None:
        raise RuntimeError(
            "Docker process containment qualification timeout is required."
        )
    try:
        timeout_seconds = int(timeout)
    except ValueError as error:
        raise RuntimeError(
            "Docker process containment qualification timeout is invalid."
        ) from error
    return DockerProcessContainmentConfig(
        backend="bwrap",
        security_profile=security_profile,
        qualification_timeout_seconds=timeout_seconds,
    )


def _provider_registration(
    settings: ProviderSettings,
    *,
    process_containment: DockerProcessContainmentConfig | None,
) -> ProviderRegistration:
    containment_enabled = process_containment is not None
    metadata = {"tmp_path": settings.tmp_path}
    if process_containment is not None:
        metadata["process_containment_backend"] = process_containment.backend
    return ProviderRegistration(
        provider_id=settings.provider_id,
        provider_type="docker",
        scope="system",
        workspace_id=None,
        protocol_version=_PROTOCOL_VERSION,
        capabilities=(
            "lifecycle",
            "observe",
            "host_directory_persistence",
        ),
        config_schema_version=_CONFIG_SCHEMA_VERSION,
        metadata=metadata,
        capability_contract=_capability_contract(
            containment_enabled=containment_enabled
        ),
    )


def _effective_process_containment(
    settings: ProviderSettings,
    security_options: Sequence[str],
) -> DockerProcessContainmentConfig | None:
    process_containment = settings.process_containment
    if process_containment is None:
        return None
    if any(
        option == _DOCKER_APPARMOR_SECURITY_OPTION
        or option.startswith(f"{_DOCKER_APPARMOR_SECURITY_OPTION},")
        for option in security_options
    ):
        return process_containment
    _LOGGER.warning(
        "Docker process containment unavailable; continuing with direct Profiles",
        extra={
            "provider_id": settings.provider_id,
            "containment_unavailable_reason": "apparmor_unavailable",
        },
    )
    return None


def _capability_contract(*, containment_enabled: bool) -> dict[str, JsonValue]:
    capabilities = [
        "docker.container-profile",
        "runtime.resources",
        "workspace.host-directory",
    ]
    schema_versions = [1]
    if containment_enabled:
        capabilities.append("runtime.process-containment")
        schema_versions.append(2)
    return {
        "schema_version": 1,
        "implementation_key": "docker",
        "implementation_version": "0.1.0",
        "protocol_version": _PROTOCOL_VERSION,
        "core_lifecycle_operations": [
            "start",
            "stop",
            "restart",
            "reset",
            "observe",
            "terminal_delete",
        ],
        "optional_capabilities": [],
        "persistence": {
            "kind": "persistent",
            "reset_destroys_workspace": True,
            "terminal_delete_destroys_workspace": True,
        },
        "configuration_fields": [],
        "profile_contracts": [
            {
                "profile_kind": "docker_container",
                "contract_family": "docker.container-profile",
                "schema_versions": schema_versions,
                "capabilities": capabilities,
                "constraints": {
                    "maximums": {},
                    "allowed_values": {},
                },
            }
        ],
    }


def _control_connection_id(base_connection_id: str) -> str:
    return f"{base_connection_id}:control:{uuid.uuid4().hex}"


async def _wait_for_reconnect(stop: asyncio.Event) -> None:
    try:
        await asyncio.wait_for(
            stop.wait(),
            timeout=_CONTROL_RECONNECT_DELAY_SECONDS,
        )
    except TimeoutError:
        return


def _required_env(name: str) -> str:
    value = os.environ.get(name)
    if value is None or not value:
        raise RuntimeError(f"required environment variable is missing: {name}")
    return value


def _required_bool_env(name: str) -> bool:
    value = _required_env(name).lower()
    if value == "true":
        return True
    if value == "false":
        return False
    raise RuntimeError(f"{name} must be true or false")


def _control_tls_from_env() -> GrpcClientTlsConfig | None:
    path = os.environ.get("AZ_RUNTIME_CONTROL_TLS_CA_FILE")
    if path is None:
        return None
    return GrpcClientTlsConfig(root_certificates=Path(path).read_bytes())


if __name__ == "__main__":
    main()
