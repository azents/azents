"""Kubernetes Provider process entrypoint."""

import asyncio
import json
import logging
import os
import signal
import uuid
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path

import grpc
from azents_runtime_control.grpc_provider_client import (
    PROVIDER_AUTH_METHOD_KUBERNETES_SERVICE_ACCOUNT,
    GrpcProviderControlClient,
    RuntimeProviderControlStreamClosed,
)
from azents_runtime_control.grpc_tls import GrpcClientTlsConfig
from azents_runtime_control.provider import (
    ProviderConnectionRejected,
    ProviderRegistration,
    ProviderRunLoop,
)

from azents_runtime_provider_kubernetes.kubernetes_api import (
    ContainerResourceClaim,
    ContainerResources,
    KubernetesResourceQuantity,
    LocalObjectReference,
    Toleration,
)
from azents_runtime_provider_kubernetes.kubernetes_http import KubernetesHttpApi
from azents_runtime_provider_kubernetes.leader import (
    KubernetesLeaderElector,
    LeaderElectionConfig,
)
from azents_runtime_provider_kubernetes.provider import (
    RUNNER_LIMIT_ENV_NAMES,
    KubernetesRuntimeProvider,
    KubernetesRuntimeProviderConfig,
)
from azents_runtime_provider_kubernetes.runtime_control import (
    KubernetesRuntimeControlAdapter,
)

_PROTOCOL_VERSION = "agent-runtime-provider-kubernetes-v1"
_CONFIG_SCHEMA_VERSION = "agent-runtime-provider-kubernetes-v1"
_DEFAULT_COMMAND_BLOCK_MS = 5_000
_CONTROL_RECONNECT_DELAY_SECONDS = 1.0
_CREDENTIAL_POLL_INTERVAL_SECONDS = 1.0
_LEADERSHIP_WAIT_LOG_INTERVAL_SECONDS = 60.0
_LOGGER = logging.getLogger(__name__)


async def _main() -> None:
    _configure_logging()
    settings = _settings_from_env()
    _LOGGER.info(
        "Runtime Kubernetes Provider process starting",
        extra={
            "provider_id": settings.provider_id,
            "connection_id": settings.connection_id,
            "lease_name": settings.lease_name,
            "lease_namespace": settings.namespace,
            "workload_namespace": settings.workload_namespace,
            "control_endpoint": settings.control_endpoint,
        },
    )
    api = await KubernetesHttpApi.from_in_cluster()
    try:
        stop = asyncio.Event()
        loop = asyncio.get_running_loop()
        for signum in (signal.SIGINT, signal.SIGTERM):
            loop.add_signal_handler(signum, stop.set)
        await _wait_for_leadership(settings, api, stop=stop)
        if stop.is_set():
            return
        leader_task = asyncio.create_task(
            _maintain_leadership(settings, api, stop=stop)
        )
        try:
            await _run_control_loop(
                settings,
                api,
                stop=stop,
            )
        finally:
            leader_task.cancel()
            try:
                await leader_task
            except asyncio.CancelledError:
                pass
    finally:
        await api.close()


async def _run_control_loop(
    settings: "ProviderSettings",
    api: KubernetesHttpApi,
    *,
    stop: asyncio.Event,
) -> None:
    """Keep the Provider registered with Control until process shutdown."""
    provider = KubernetesRuntimeProvider(
        api,
        KubernetesRuntimeProviderConfig(
            provider_id=settings.provider_id,
            namespace=settings.workload_namespace,
            storage_class_name=settings.storage_class_name,
            pvc_storage_request=settings.pvc_storage_request,
            runner_resources=settings.runner_resources,
            runner_env=settings.runner_env,
            image_pull_secrets=settings.image_pull_secrets,
            pod_annotations=settings.pod_annotations,
            pod_node_selector=settings.pod_node_selector,
            pod_tolerations=settings.pod_tolerations,
            workspace_mount_path=settings.workspace_path,
        ),
    )
    lifecycle = KubernetesRuntimeControlAdapter(provider)
    registration = ProviderRegistration(
        provider_id=settings.provider_id,
        provider_type="kubernetes",
        scope="system",
        workspace_id=None,
        protocol_version=_PROTOCOL_VERSION,
        capabilities=(
            "lifecycle",
            "observe",
            "workspace_path",
            "pvc_persistence",
        ),
        config_schema_version=_CONFIG_SCHEMA_VERSION,
        metadata={"workspace_path": settings.workspace_path},
    )
    while not stop.is_set():
        _set_readiness(settings.readiness_file, ready=False)
        provider_credential = read_service_account_token(
            settings.service_account_token_file
        )
        control_client = create_provider_control_client(
            settings,
            provider_credential=provider_credential,
        )
        control_connection_id = _control_connection_id(settings.connection_id)
        _LOGGER.info(
            "Runtime Provider connecting to Control",
            extra={
                "provider_id": settings.provider_id,
                "connection_id": control_connection_id,
                "control_endpoint": settings.control_endpoint,
            },
        )
        run_loop = ProviderRunLoop(
            client=control_client,
            lifecycle=lifecycle,
            registration=registration,
            connection_id=control_connection_id,
            consumer_id=f"{control_connection_id}:provider",
        )
        try:
            await run_loop.start()
            _set_readiness(settings.readiness_file, ready=True)
            watch_task = asyncio.create_task(
                _report_pod_watch_events(
                    lifecycle,
                    run_loop,
                    stop=stop,
                ),
                name="runtime-provider-pod-watch",
            )
            command_task = asyncio.create_task(
                run_loop.run_forever(
                    stop=stop,
                    command_block_ms=_DEFAULT_COMMAND_BLOCK_MS,
                ),
                name="runtime-provider-command-loop",
            )
            credential_task = asyncio.create_task(
                wait_for_provider_credential_change(
                    settings.service_account_token_file,
                    current=provider_credential,
                    stop=stop,
                ),
                name="runtime-provider-credential-watch",
            )
            done, pending = await asyncio.wait(
                {watch_task, command_task, credential_task},
                return_when=asyncio.FIRST_COMPLETED,
            )
            for task in pending:
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass
            for task in done:
                await task
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
            _set_readiness(settings.readiness_file, ready=False)
            await control_client.close()


def create_provider_control_client(
    settings: "ProviderSettings",
    *,
    provider_credential: str,
) -> GrpcProviderControlClient:
    """Create the Kubernetes Provider's explicit workload-identity client."""
    return GrpcProviderControlClient.from_endpoint(
        settings.control_endpoint,
        provider_credential=provider_credential,
        provider_auth_method=PROVIDER_AUTH_METHOD_KUBERNETES_SERVICE_ACCOUNT,
        tls=settings.control_tls,
        allow_insecure=settings.allow_insecure_control,
    )


async def _report_pod_watch_events(
    lifecycle: KubernetesRuntimeControlAdapter,
    run_loop: ProviderRunLoop,
    *,
    stop: asyncio.Event,
) -> None:
    """Forward Kubernetes Pod watch events to Control as Provider reports."""
    while not stop.is_set():
        try:
            async for report in lifecycle.watch_known_runtimes():
                current_report = await run_loop.report_provider_state(report)
                _LOGGER.info(
                    "Runtime Provider watch report sent",
                    extra={
                        "provider_id": current_report.provider_id,
                        "runtime_id": current_report.runtime_id,
                        "provider_generation": current_report.provider_generation,
                        "observed_state": current_report.observed_state.value,
                        "observed_desired_generation": (
                            current_report.observed_desired_generation
                        ),
                        "reason": current_report.reason,
                    },
                )
                if stop.is_set():
                    return
        except asyncio.CancelledError:
            raise
        except (
            RuntimeProviderControlStreamClosed,
            ProviderConnectionRejected,
            TimeoutError,
            grpc.aio.AioRpcError,
        ):
            raise
        except Exception:
            _LOGGER.warning(
                "Runtime Provider Pod watch disconnected; reconnecting",
                exc_info=True,
            )
            await _wait_for_reconnect(stop)


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


async def wait_for_provider_credential_change(
    path: Path,
    *,
    current: str,
    stop: asyncio.Event,
) -> None:
    """Return when the projected Provider credential changes."""
    while not stop.is_set():
        try:
            candidate = read_service_account_token(path)
        except RuntimeError:
            candidate = None
        if candidate is not None and candidate != current:
            _LOGGER.info("Runtime Provider credential changed; reconnecting")
            return
        try:
            await asyncio.wait_for(
                stop.wait(),
                timeout=_CREDENTIAL_POLL_INTERVAL_SECONDS,
            )
        except TimeoutError:
            continue


async def _wait_for_leadership(
    settings: "ProviderSettings",
    api: KubernetesHttpApi,
    *,
    stop: asyncio.Event,
) -> None:
    elector = _elector(settings, api)
    next_waiting_log_at = 0.0
    while not stop.is_set():
        result = await elector.try_acquire(now=datetime.now(UTC))
        if result.acquired:
            _LOGGER.info(
                "Runtime Provider leadership acquired",
                extra={
                    "provider_id": settings.provider_id,
                    "holder_identity": settings.connection_id,
                    "lease_name": settings.lease_name,
                    "lease_namespace": settings.namespace,
                },
            )
            return
        now = asyncio.get_running_loop().time()
        if now >= next_waiting_log_at:
            _LOGGER.info(
                "Runtime Provider waiting for leadership",
                extra={
                    "provider_id": settings.provider_id,
                    "holder_identity": settings.connection_id,
                    "lease_name": settings.lease_name,
                    "lease_namespace": settings.namespace,
                    "current_holder": result.lease.spec.holder_identity,
                },
            )
            next_waiting_log_at = now + _LEADERSHIP_WAIT_LOG_INTERVAL_SECONDS
        try:
            await asyncio.wait_for(
                stop.wait(),
                timeout=max(settings.lease_duration_seconds / 3, 1),
            )
        except TimeoutError:
            continue


async def _maintain_leadership(
    settings: "ProviderSettings",
    api: KubernetesHttpApi,
    *,
    stop: asyncio.Event,
) -> None:
    elector = _elector(settings, api)
    while not stop.is_set():
        result = await elector.try_acquire(now=datetime.now(UTC))
        if not result.acquired:
            _LOGGER.warning(
                "Runtime Provider leadership lost",
                extra={
                    "provider_id": settings.provider_id,
                    "holder_identity": settings.connection_id,
                    "lease_name": settings.lease_name,
                    "lease_namespace": settings.namespace,
                    "current_holder": result.lease.spec.holder_identity,
                },
            )
            stop.set()
            return
        try:
            await asyncio.wait_for(
                stop.wait(),
                timeout=max(settings.lease_duration_seconds / 3, 1),
            )
        except TimeoutError:
            continue


def _elector(
    settings: "ProviderSettings",
    api: KubernetesHttpApi,
) -> KubernetesLeaderElector:
    return KubernetesLeaderElector(
        api,
        LeaderElectionConfig(
            namespace=settings.namespace,
            lease_name=settings.lease_name,
            holder_identity=settings.connection_id,
            lease_duration_seconds=settings.lease_duration_seconds,
        ),
    )


class ProviderSettings:
    """Runtime Provider process settings from environment variables."""

    def __init__(self) -> None:
        """Load settings without implicit defaults for deployment-critical fields."""
        self.control_endpoint: str = _required_env("AZ_RUNTIME_CONTROL_ENDPOINT")
        self.control_tls = _control_tls_from_env()
        self.allow_insecure_control = _required_bool_env(
            "AZ_RUNTIME_CONTROL_ALLOW_INSECURE"
        )
        self.readiness_file = Path(_required_env("AZ_RUNTIME_PROVIDER_READINESS_FILE"))
        self.service_account_token_file = Path(
            _required_env("AZ_RUNTIME_PROVIDER_SERVICE_ACCOUNT_TOKEN_FILE")
        )
        self.provider_id: str = _required_env("AZ_RUNTIME_PROVIDER_ID")
        self.namespace: str = _required_env("AZ_RUNTIME_PROVIDER_LEASE_NAMESPACE")
        self.workload_namespace: str = _required_env(
            "AZ_RUNTIME_PROVIDER_WORKLOAD_NAMESPACE"
        )
        self.lease_name: str = _required_env("AZ_RUNTIME_PROVIDER_LEASE_NAME")
        self.workspace_path: str = _required_env("AZ_RUNTIME_PROVIDER_WORKSPACE_PATH")
        self.storage_class_name: str = _required_env(
            "AZ_RUNTIME_PROVIDER_STORAGE_CLASS"
        )
        self.pvc_storage_request: str = _required_env("AZ_RUNTIME_PROVIDER_PVC_SIZE")
        self.runner_resources: ContainerResources | None = (
            _json_container_resources_env("AZ_RUNTIME_RUNNER_RESOURCES")
        )
        self.runner_env: Mapping[str, str] = _selected_env(RUNNER_LIMIT_ENV_NAMES)
        self.image_pull_secrets: tuple[LocalObjectReference, ...] = (
            _json_local_object_references_env(
                "AZ_RUNTIME_PROVIDER_POD_IMAGE_PULL_SECRETS"
            )
        )
        self.pod_annotations: Mapping[str, str] = _json_string_map_env(
            "AZ_RUNTIME_PROVIDER_POD_ANNOTATIONS"
        )
        self.pod_node_selector: Mapping[str, str] = _json_string_map_env(
            "AZ_RUNTIME_PROVIDER_POD_NODE_SELECTOR"
        )
        self.pod_tolerations: tuple[Toleration, ...] = _json_tolerations_env(
            "AZ_RUNTIME_PROVIDER_POD_TOLERATIONS"
        )
        self.lease_duration_seconds: int = int(
            _required_env("AZ_RUNTIME_PROVIDER_LEASE_DURATION_SECONDS")
        )
        self.connection_id: str = os.environ.get(
            "AZ_RUNTIME_PROVIDER_CONNECTION_ID",
            f"{self.provider_id}:{uuid.uuid4().hex}",
        )


def _settings_from_env() -> ProviderSettings:
    return ProviderSettings()


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


def read_service_account_token(path: Path) -> str:
    """Read the projected Kubernetes ServiceAccount token."""
    try:
        token = path.read_text().strip()
    except OSError as exc:
        raise RuntimeError(
            f"Runtime Provider ServiceAccount token file cannot be read: {path}"
        ) from exc
    if not token:
        raise RuntimeError("Runtime Provider ServiceAccount token file is empty")
    return token


def _control_tls_from_env() -> GrpcClientTlsConfig | None:
    path = os.environ.get("AZ_RUNTIME_CONTROL_TLS_CA_FILE")
    if path is None:
        return None
    return GrpcClientTlsConfig(root_certificates=Path(path).read_bytes())


def _set_readiness(path: Path, *, ready: bool) -> None:
    if ready:
        path.write_text("ready\n")
        return
    path.unlink(missing_ok=True)


def _selected_env(names: tuple[str, ...]) -> Mapping[str, str]:
    return {name: os.environ[name] for name in names if name in os.environ}


def _json_container_resources_env(name: str) -> ContainerResources | None:
    value = os.environ.get(name)
    if value is None or value.strip() == "":
        return None
    parsed = json.loads(value)
    if parsed is None:
        return None
    if not isinstance(parsed, dict):
        raise RuntimeError(f"{name} must be a JSON object or null")
    return ContainerResources(
        requests=_resource_quantity_map(parsed, "requests", name),
        limits=_resource_quantity_map(parsed, "limits", name),
        claims=_resource_claims(parsed, name),
    )


def _json_local_object_references_env(name: str) -> tuple[LocalObjectReference, ...]:
    value = os.environ.get(name)
    if value is None or value.strip() == "":
        return ()
    parsed = json.loads(value)
    if not isinstance(parsed, list):
        raise RuntimeError(f"{name} must be a JSON array")
    references: list[LocalObjectReference] = []
    for item in parsed:
        if not isinstance(item, dict):
            raise RuntimeError(f"{name} must contain JSON objects")
        reference_name = item.get("name")
        if not isinstance(reference_name, str) or reference_name == "":
            raise RuntimeError(f"{name}.name must be a non-empty string")
        references.append(LocalObjectReference(name=reference_name))
    return tuple(references)


def _resource_quantity_map(
    data: Mapping[object, object],
    key: str,
    env_name: str,
) -> Mapping[str, KubernetesResourceQuantity] | None:
    value = data.get(key)
    if value is None:
        return None
    if not isinstance(value, dict):
        raise RuntimeError(f"{env_name}.{key} must be a JSON object")
    result: dict[str, KubernetesResourceQuantity] = {}
    for resource_name, quantity in value.items():
        if not isinstance(resource_name, str):
            raise RuntimeError(f"{env_name}.{key} must map string resource names")
        result[resource_name] = _resource_quantity(quantity, f"{env_name}.{key}")
    return result


def _resource_quantity(
    value: object,
    path: str,
) -> KubernetesResourceQuantity:
    if isinstance(value, bool) or value is None:
        raise RuntimeError(f"{path} values must be string or number quantities")
    if isinstance(value, str | int | float):
        return value
    raise RuntimeError(f"{path} values must be string or number quantities")


def _resource_claims(
    data: Mapping[object, object],
    env_name: str,
) -> tuple[ContainerResourceClaim, ...] | None:
    value = data.get("claims")
    if value is None:
        return None
    if not isinstance(value, list):
        raise RuntimeError(f"{env_name}.claims must be a JSON array")
    claims: list[ContainerResourceClaim] = []
    for item in value:
        if not isinstance(item, dict):
            raise RuntimeError(f"{env_name}.claims must contain JSON objects")
        name = item.get("name")
        if not isinstance(name, str) or name == "":
            raise RuntimeError(f"{env_name}.claims.name must be a non-empty string")
        request = _optional_string(item, "request", f"{env_name}.claims")
        claims.append(ContainerResourceClaim(name=name, request=request))
    return tuple(claims)


def _json_string_map_env(name: str) -> Mapping[str, str]:
    value = os.environ.get(name)
    if value is None or value.strip() == "":
        return {}
    parsed = json.loads(value)
    if not isinstance(parsed, dict):
        raise RuntimeError(f"{name} must be a JSON object")
    result: dict[str, str] = {}
    for key, item in parsed.items():
        if not isinstance(key, str) or not isinstance(item, str):
            raise RuntimeError(f"{name} must map string keys to string values")
        result[key] = item
    return result


def _json_tolerations_env(name: str) -> tuple[Toleration, ...]:
    value = os.environ.get(name)
    if value is None or value.strip() == "":
        return ()
    parsed = json.loads(value)
    if not isinstance(parsed, list):
        raise RuntimeError(f"{name} must be a JSON array")
    tolerations: list[Toleration] = []
    for item in parsed:
        if not isinstance(item, dict):
            raise RuntimeError(f"{name} must contain JSON objects")
        tolerations.append(
            Toleration(
                key=_optional_string(item, "key", name),
                operator=_optional_string(item, "operator", name),
                value=_optional_string(item, "value", name),
                effect=_optional_string(item, "effect", name),
            )
        )
    return tuple(tolerations)


def _optional_string(
    data: Mapping[object, object],
    key: str,
    env_name: str,
) -> str | None:
    value = data.get(key)
    if value is None:
        return None
    if not isinstance(value, str):
        raise RuntimeError(f"{env_name}.{key} must be a string")
    return value


def _configure_logging() -> None:
    logging.basicConfig(
        level=os.environ.get("AZ_RUNTIME_PROVIDER_LOG_LEVEL", "INFO"),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )


def main() -> None:
    """Run the Kubernetes Runtime Provider."""
    asyncio.run(_main())


if __name__ == "__main__":
    main()
