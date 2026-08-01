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
    JsonValue,
    ProviderConnectionRejected,
    ProviderRegistration,
    ProviderRunLoop,
)

from azents_runtime_provider_kubernetes.kubernetes_api import (
    IpBlock,
    LabelSelector,
    LocalObjectReference,
    NetworkPolicyEgressRule,
    NetworkPolicyPeer,
    NetworkPolicyPort,
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

_PROTOCOL_VERSION = "agent-runtime-provider-kubernetes-v1"
_CONFIG_SCHEMA_VERSION = "agent-runtime-provider-kubernetes-v1"
_DEFAULT_COMMAND_BLOCK_MS = 5_000
_CONTROL_RECONNECT_DELAY_SECONDS = 1.0
_CREDENTIAL_POLL_INTERVAL_SECONDS = 1.0
_LEADERSHIP_WAIT_LOG_INTERVAL_SECONDS = 60.0
_MIN_LEADERSHIP_POLL_SECONDS = 1.0
_LOGGER = logging.getLogger(__name__)

_CAPABILITY_CONTRACT: dict[str, JsonValue] = {
    "schema_version": 1,
    "implementation_key": "kubernetes",
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
            "profile_kind": "kubernetes_pod",
            "contract_family": "kubernetes.pod-profile",
            "schema_versions": [1],
            "capabilities": [
                "kubernetes.pod-profile",
                "runtime.resources",
                "workspace.persistent-volume",
                "runtime.network-policy",
                "kubernetes.service-account",
                "kubernetes.scheduling",
                "docker.dind",
                "docker.storage.ephemeral",
            ],
            "constraints": {
                "maximums": {},
                "allowed_values": {},
            },
        }
    ],
}


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
        await wait_for_leadership(settings, api, stop=stop)
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
            runner_env=settings.runner_env,
            engine_image=settings.engine_image,
            runtime_control_namespace=settings.runtime_control_namespace,
            runtime_control_labels=settings.runtime_control_labels,
            runtime_control_port=settings.runtime_control_port,
            network_hard_cap_allowed_cidrs=settings.network_hard_cap_allowed_cidrs,
            network_hard_cap_denied_cidrs=settings.network_hard_cap_denied_cidrs,
            network_hard_cap_extra_egress=settings.network_hard_cap_extra_egress,
            image_pull_secrets=settings.image_pull_secrets,
            pod_annotations=settings.pod_annotations,
            workspace_mount_path=settings.workspace_path,
        ),
    )
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
        capability_contract=_CAPABILITY_CONTRACT,
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
            lifecycle=provider,
            registration=registration,
            connection_id=control_connection_id,
            consumer_id=f"{control_connection_id}:provider",
        )
        try:
            await run_loop.start()
            _set_readiness(settings.readiness_file, ready=True)
            watch_task = asyncio.create_task(
                _report_pod_watch_events(
                    provider,
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
    lifecycle: KubernetesRuntimeProvider,
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


async def wait_for_leadership(
    settings: "ProviderSettings",
    api: KubernetesHttpApi,
    *,
    stop: asyncio.Event,
) -> None:
    _set_readiness(settings.readiness_file, ready=False)
    elector = _elector(settings, api)
    next_waiting_log_at = 0.0
    while not stop.is_set():
        result = await elector.try_acquire(now=datetime.now(UTC))
        if result.acquired:
            _set_readiness(settings.readiness_file, ready=False)
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
        _set_readiness(settings.readiness_file, ready=True)
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
                timeout=max(
                    settings.lease_duration_seconds / 3,
                    _MIN_LEADERSHIP_POLL_SECONDS,
                ),
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
                timeout=max(
                    settings.lease_duration_seconds / 3,
                    _MIN_LEADERSHIP_POLL_SECONDS,
                ),
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
        self.runner_env: Mapping[str, str] = _selected_env(RUNNER_LIMIT_ENV_NAMES)
        self.engine_image = _required_env("AZ_RUNTIME_PROVIDER_ENGINE_IMAGE")
        self.runtime_control_namespace = _required_env(
            "AZ_RUNTIME_PROVIDER_RUNTIME_CONTROL_NAMESPACE"
        )
        self.runtime_control_labels = _json_string_map_env(
            "AZ_RUNTIME_PROVIDER_RUNTIME_CONTROL_LABELS"
        )
        if not self.runtime_control_labels:
            raise RuntimeError(
                "AZ_RUNTIME_PROVIDER_RUNTIME_CONTROL_LABELS must not be empty"
            )
        self.runtime_control_port = int(
            _required_env("AZ_RUNTIME_PROVIDER_RUNTIME_CONTROL_PORT")
        )
        if not 1 <= self.runtime_control_port <= 65_535:
            raise RuntimeError(
                "AZ_RUNTIME_PROVIDER_RUNTIME_CONTROL_PORT must be between 1 and 65535"
            )
        self.network_hard_cap_allowed_cidrs = _json_string_tuple_env(
            "AZ_RUNTIME_PROVIDER_NETWORK_HARD_CAP_ALLOWED_CIDRS"
        )
        self.network_hard_cap_denied_cidrs = _json_string_tuple_env(
            "AZ_RUNTIME_PROVIDER_NETWORK_HARD_CAP_DENIED_CIDRS"
        )
        self.network_hard_cap_extra_egress = _json_network_policy_egress_env(
            "AZ_RUNTIME_PROVIDER_NETWORK_HARD_CAP_EXTRA_EGRESS"
        )
        self.image_pull_secrets: tuple[LocalObjectReference, ...] = (
            _json_local_object_references_env(
                "AZ_RUNTIME_PROVIDER_POD_IMAGE_PULL_SECRETS"
            )
        )
        self.pod_annotations: Mapping[str, str] = _json_string_map_env(
            "AZ_RUNTIME_PROVIDER_POD_ANNOTATIONS"
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


def _json_string_tuple_env(name: str) -> tuple[str, ...]:
    value = _required_env(name)
    parsed = json.loads(value)
    if not isinstance(parsed, list) or not all(
        isinstance(item, str) and item for item in parsed
    ):
        raise RuntimeError(f"{name} must be a JSON array of non-empty strings")
    return tuple(parsed)


def _json_network_policy_egress_env(
    name: str,
) -> tuple[NetworkPolicyEgressRule, ...]:
    value = _required_env(name)
    parsed = json.loads(value)
    if not isinstance(parsed, list):
        raise RuntimeError(f"{name} must be a JSON array")
    return tuple(_network_policy_egress_rule(item, name) for item in parsed)


def _network_policy_egress_rule(
    value: object,
    env_name: str,
) -> NetworkPolicyEgressRule:
    if not isinstance(value, dict):
        raise RuntimeError(f"{env_name} must contain JSON objects")
    to = value.get("to", [])
    ports = value.get("ports", [])
    if not isinstance(to, list) or not isinstance(ports, list):
        raise RuntimeError(f"{env_name} rules require array to/ports fields")
    return NetworkPolicyEgressRule(
        peers=tuple(_network_policy_peer(item, env_name) for item in to),
        ports=tuple(_network_policy_port(item, env_name) for item in ports),
    )


def _network_policy_peer(value: object, env_name: str) -> NetworkPolicyPeer:
    if not isinstance(value, dict):
        raise RuntimeError(f"{env_name}.to must contain JSON objects")
    namespace_selector = _network_policy_selector(
        value.get("namespaceSelector"), env_name
    )
    pod_selector = _network_policy_selector(value.get("podSelector"), env_name)
    ip_block_value = value.get("ipBlock")
    ip_block: IpBlock | None = None
    if ip_block_value is not None:
        if not isinstance(ip_block_value, dict):
            raise RuntimeError(f"{env_name}.ipBlock must be a JSON object")
        cidr = ip_block_value.get("cidr")
        except_cidrs = ip_block_value.get("except", [])
        if not isinstance(cidr, str) or not cidr or not isinstance(except_cidrs, list):
            raise RuntimeError(f"{env_name}.ipBlock requires CIDR and except fields")
        if not all(isinstance(item, str) and item for item in except_cidrs):
            raise RuntimeError(f"{env_name}.ipBlock.except must contain CIDRs")
        ip_block = IpBlock(cidr=cidr, except_cidrs=tuple(except_cidrs))
    if namespace_selector is None and pod_selector is None and ip_block is None:
        raise RuntimeError(f"{env_name}.to entries must select a destination")
    if ip_block is not None and (
        namespace_selector is not None or pod_selector is not None
    ):
        raise RuntimeError(f"{env_name}.ipBlock cannot be combined with selectors")
    return NetworkPolicyPeer(
        namespace_selector=namespace_selector,
        pod_selector=pod_selector,
        ip_block=ip_block,
    )


def _network_policy_selector(value: object, env_name: str) -> LabelSelector | None:
    if value is None:
        return None
    if not isinstance(value, dict):
        raise RuntimeError(f"{env_name} selectors must be JSON objects")
    match_labels = value.get("matchLabels", {})
    if not isinstance(match_labels, dict) or not all(
        isinstance(key, str) and isinstance(item, str)
        for key, item in match_labels.items()
    ):
        raise RuntimeError(f"{env_name} selector labels must map strings to strings")
    return LabelSelector(match_labels=dict(match_labels))


def _network_policy_port(value: object, env_name: str) -> NetworkPolicyPort:
    if not isinstance(value, dict):
        raise RuntimeError(f"{env_name}.ports must contain JSON objects")
    protocol = value.get("protocol", "TCP")
    port = value.get("port")
    if not isinstance(protocol, str) or protocol not in {"TCP", "UDP", "SCTP"}:
        raise RuntimeError(f"{env_name}.ports protocol is invalid")
    if isinstance(port, bool) or not isinstance(port, int | str):
        raise RuntimeError(f"{env_name}.ports port must be an integer or name")
    if isinstance(port, int) and not 1 <= port <= 65_535:
        raise RuntimeError(f"{env_name}.ports integer port is invalid")
    if isinstance(port, str) and not port:
        raise RuntimeError(f"{env_name}.ports named port is invalid")
    return NetworkPolicyPort(protocol=protocol, port=port)


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
