"""Docker Provider process entrypoint."""

import asyncio
import logging
import os
import signal
import uuid
from pathlib import Path

import grpc
from azents_runtime_control.grpc_provider_client import (
    PROVIDER_AUTH_METHOD_AZENTS_ISSUED_TOKEN,
    GrpcProviderControlClient,
    RuntimeProviderControlStreamClosed,
)
from azents_runtime_control.grpc_tls import GrpcClientTlsConfig
from azents_runtime_control.provider import (
    ProviderConnectionRejected,
    ProviderRegistration,
    ProviderRunLoop,
)

from azents_runtime_provider_docker.aiodocker_api import AioDockerApi
from azents_runtime_provider_docker.provider import (
    RUNNER_LIMIT_ENV_NAMES,
    DockerRuntimeProvider,
    DockerRuntimeProviderConfig,
)
from azents_runtime_provider_docker.runtime_control import DockerRuntimeControlAdapter

_PROTOCOL_VERSION = "agent-runtime-provider-docker-v1"
_CONFIG_SCHEMA_VERSION = "agent-runtime-provider-docker-v1"
_DEFAULT_COMMAND_BLOCK_MS = 5_000
_CONTROL_RECONNECT_DELAY_SECONDS = 1.0
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
            "docker_network": settings.docker_network,
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
    provider = DockerRuntimeProvider(
        docker,
        DockerRuntimeProviderConfig(
            provider_id=settings.provider_id,
            host_data_root=settings.host_data_root,
            docker_network=settings.docker_network,
            runner_env=settings.runner_env,
            workspace_mount_path=settings.workspace_path,
            tmp_mount_path=settings.tmp_path,
        ),
    )
    lifecycle = DockerRuntimeControlAdapter(provider)
    registration = ProviderRegistration(
        provider_id=settings.provider_id,
        provider_type="docker",
        scope="system",
        workspace_id=None,
        protocol_version=_PROTOCOL_VERSION,
        capabilities=(
            "lifecycle",
            "observe",
            "workspace_path",
            "host_directory_persistence",
        ),
        config_schema_version=_CONFIG_SCHEMA_VERSION,
        metadata={
            "workspace_path": settings.workspace_path,
            "tmp_path": settings.tmp_path,
        },
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
            lifecycle=lifecycle,
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
        self.docker_network = _required_env("AZ_RUNTIME_PROVIDER_DOCKER_NETWORK")
        self.host_data_root = Path(_required_env("AZ_RUNTIME_PROVIDER_HOST_DATA_ROOT"))
        self.workspace_path = os.environ.get(
            "AZ_RUNTIME_PROVIDER_WORKSPACE_PATH",
            "/workspace/agent",
        )
        self.tmp_path = os.environ.get("AZ_RUNTIME_PROVIDER_TMP_PATH", "/tmp/agent")
        self.runner_env = _runner_env_from_env()
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
