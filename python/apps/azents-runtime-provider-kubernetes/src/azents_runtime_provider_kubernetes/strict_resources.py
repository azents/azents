"""Strict Runtime proxy resource assembly."""

import dataclasses
from collections.abc import Mapping

from azents_runtime_control.runtime_configuration import (
    RuntimeNetworkMode,
    RuntimeProxyRequiredNetworkAccess,
)

from azents_runtime_provider_kubernetes.interception_ca import (
    CA_COMBINED_SECRET_KEY,
    CA_PUBLIC_SECRET_KEY,
    RuntimeCaMaterial,
    runtime_ca_secret_data,
)
from azents_runtime_provider_kubernetes.kubernetes_api import (
    ConfigMapResource,
    ConfigMapVolume,
    ContainerSecurityContext,
    ContainerSpec,
    EmptyDirVolume,
    EnvVar,
    ExecAction,
    KeyToPath,
    LocalObjectReference,
    ObjectMeta,
    PodResource,
    PodSecurityContext,
    PodSpec,
    Probe,
    SeccompProfile,
    SecretResource,
    SecretVolume,
    ServicePort,
    ServiceResource,
    ServiceSpec,
    Toleration,
    VolumeMount,
)
from azents_runtime_provider_kubernetes.network_enforcement import proxy_artifact_digest
from azents_runtime_provider_kubernetes.owned_resources import (
    ANNOTATION_NETWORK_MODE,
    LABEL_CONFIGURATION_MANAGED,
    LABEL_MANAGED_BY,
    LABEL_RESOURCE_ROLE,
    LABEL_RUNTIME_ID,
    MANAGED_BY_VALUE,
    OwnedResourceAnnotations,
    OwnedResourceIdentity,
    ResourceRole,
    owned_annotations,
    owned_labels,
    proxy_policy_resource_name,
    resource_name,
)
from azents_runtime_provider_kubernetes.proxy_policy import (
    ProxyDomainMode,
    ProxyPolicyInput,
    canonical_proxy_policy,
)

_PROXY_POLICY_KEY = "policy.json"
_PROXY_POLICY_VOLUME = "proxy-policy"
_PROXY_CA_VOLUME = "proxy-ca"
_PROXY_RUN_VOLUME = "proxy-run"
_PROXY_POLICY_PATH = "/etc/azents-runtime-proxy/policy.json"
_PROXY_PUBLIC_CA_PATH = "/var/run/secrets/azents/runtime-proxy/ca.crt"
_PROXY_COMBINED_CA_PATH = "/var/run/secrets/azents/runtime-proxy/mitmproxy-ca.pem"
_PROXY_RUN_PATH = "/var/run/azents-proxy"
RUNTIME_CA_VOLUME = "runtime-network-ca"
RUNTIME_CA_MOUNT_PATH = "/var/run/secrets/azents/runtime-network"
RUNTIME_TRUST_VOLUME = "runtime-trust"
RUNTIME_TRUST_MOUNT_PATH = "/var/run/azents-runtime"
RUNNER_PROXY_INPUT_ENV = "AZ_RUNTIME_RUNNER_HTTP_PROXY"


@dataclasses.dataclass(frozen=True)
class ProxyResourceInputs:
    """Deployment and configuration inputs for strict proxy resources."""

    namespace: str
    identity: OwnedResourceIdentity
    desired_generation: int
    configuration_sequence: int
    configuration_digest: str
    network_access: RuntimeProxyRequiredNetworkAccess
    ca: RuntimeCaMaterial
    proxy_image: str
    addon_digest: str
    proxy_port: int
    readiness_port: int
    image_pull_secrets: tuple[LocalObjectReference, ...]
    node_selector: Mapping[str, str]
    tolerations: tuple[Toleration, ...]


@dataclasses.dataclass(frozen=True)
class ProxyResources:
    """Complete desired proxy resources and safe evidence."""

    ca_secret: SecretResource
    policy_config_map: ConfigMapResource
    service: ServiceResource
    pod: PodResource
    policy_digest: str
    artifact_digest: str
    service_hostname: str


def build_proxy_resources(
    value: ProxyResourceInputs,
    *,
    existing_cluster_ip: str | None,
) -> ProxyResources:
    """Build the persistent CA, policy revision, stable Service, and proxy Pod."""
    if not 1 <= value.proxy_port <= 65_535:
        raise ValueError("proxy port is invalid")
    if not 1 <= value.readiness_port <= 65_535:
        raise ValueError("proxy readiness port is invalid")
    artifact_digest = proxy_artifact_digest(
        proxy_image=value.proxy_image,
        addon_digest=value.addon_digest,
    )
    policy = canonical_proxy_policy(
        ProxyPolicyInput(
            runtime_id=value.identity.runtime_id,
            configuration_sequence=value.configuration_sequence,
            configuration_digest=value.configuration_digest,
            domain_mode=ProxyDomainMode(value.network_access.domain_policy.mode.value),
            allowed_domains=value.network_access.domain_policy.allowed_domains,
            denied_domains=value.network_access.domain_policy.denied_domains,
            allowed_cidrs=value.network_access.allowed_cidrs,
            denied_cidrs=value.network_access.denied_cidrs,
            ca_fingerprint=value.ca.fingerprint,
            artifact_digest=artifact_digest,
        )
    )
    annotations = owned_annotations(
        OwnedResourceAnnotations(
            configuration_sequence=value.configuration_sequence,
            configuration_digest=value.configuration_digest,
            policy_digest=policy.digest,
            ca_fingerprint=value.ca.fingerprint,
            artifact_digest=artifact_digest,
        )
    )
    service_name = resource_name(
        value.identity.runtime_id,
        ResourceRole.PROXY_SERVICE,
    )
    service_hostname = f"{service_name}.{value.namespace}.svc"
    ca_secret = _ca_secret(value)
    policy_config_map = ConfigMapResource(
        metadata=ObjectMeta(
            name=proxy_policy_resource_name(
                value.identity.runtime_id,
                policy.digest,
            ),
            namespace=value.namespace,
            labels=owned_labels(
                value.identity,
                ResourceRole.PROXY_POLICY,
                desired_generation=value.desired_generation,
            ),
            annotations=annotations,
        ),
        data={_PROXY_POLICY_KEY: policy.document},
        immutable=True,
    )
    service = ServiceResource(
        metadata=ObjectMeta(
            name=service_name,
            namespace=value.namespace,
            labels=owned_labels(
                value.identity,
                ResourceRole.PROXY_SERVICE,
                desired_generation=value.desired_generation,
            ),
            annotations=annotations,
        ),
        spec=ServiceSpec(
            service_type="ClusterIP",
            cluster_ip=existing_cluster_ip,
            selector=_role_selector(
                value.identity.runtime_id,
                ResourceRole.PROXY_POD,
            ),
            ports=(
                ServicePort(
                    name="proxy",
                    protocol="TCP",
                    port=value.proxy_port,
                    target_port=value.proxy_port,
                ),
            ),
        ),
    )
    pod = _proxy_pod(
        value,
        ca_secret=ca_secret,
        policy_config_map=policy_config_map,
        annotations=annotations,
        policy_digest=policy.digest,
        artifact_digest=artifact_digest,
    )
    return ProxyResources(
        ca_secret=ca_secret,
        policy_config_map=policy_config_map,
        service=service,
        pod=pod,
        policy_digest=policy.digest,
        artifact_digest=artifact_digest,
        service_hostname=service_hostname,
    )


def runtime_ca_volume(secret_name: str) -> SecretVolume:
    """Return the Runtime public-only CA volume."""
    return SecretVolume(
        name=RUNTIME_CA_VOLUME,
        secret_name=secret_name,
        items=(
            KeyToPath(
                key=CA_PUBLIC_SECRET_KEY,
                path=CA_PUBLIC_SECRET_KEY,
                mode=0o444,
            ),
        ),
        default_mode=0o444,
    )


def runtime_trust_volume() -> EmptyDirVolume:
    """Return the bounded writable Runner trust workspace."""
    return EmptyDirVolume(
        name=RUNTIME_TRUST_VOLUME,
        medium="Memory",
        size_limit="16Mi",
    )


def runtime_proxy_url(hostname: str, port: int) -> str:
    """Return the canonical child-process HTTP proxy URL."""
    if not _canonical_hostname(hostname) or not 1 <= port <= 65_535:
        raise ValueError("Runtime proxy endpoint is invalid")
    return f"http://{hostname}:{port}"


def runtime_proxy_environment(hostname: str, port: int) -> dict[str, str]:
    """Return the Provider-only Runner child-proxy input."""
    return {RUNNER_PROXY_INPUT_ENV: runtime_proxy_url(hostname, port)}


def _ca_secret(value: ProxyResourceInputs) -> SecretResource:
    return SecretResource(
        metadata=ObjectMeta(
            name=resource_name(value.identity.runtime_id, ResourceRole.RUNTIME_CA),
            namespace=value.namespace,
            labels=owned_labels(
                value.identity,
                ResourceRole.RUNTIME_CA,
                desired_generation=None,
            ),
            annotations=owned_annotations(
                OwnedResourceAnnotations(
                    configuration_sequence=None,
                    configuration_digest=None,
                    policy_digest=None,
                    ca_fingerprint=value.ca.fingerprint,
                    artifact_digest=None,
                )
            ),
        ),
        data=runtime_ca_secret_data(value.ca),
        secret_type="Opaque",
        immutable=False,
    )


def _proxy_pod(
    value: ProxyResourceInputs,
    *,
    ca_secret: SecretResource,
    policy_config_map: ConfigMapResource,
    annotations: Mapping[str, str],
    policy_digest: str,
    artifact_digest: str,
) -> PodResource:
    return PodResource(
        metadata=ObjectMeta(
            name=resource_name(value.identity.runtime_id, ResourceRole.PROXY_POD),
            namespace=value.namespace,
            labels=owned_labels(
                value.identity,
                ResourceRole.PROXY_POD,
                desired_generation=value.desired_generation,
            ),
            annotations={
                **annotations,
                ANNOTATION_NETWORK_MODE: RuntimeNetworkMode.PROXY_REQUIRED.value,
            },
        ),
        spec=PodSpec(
            service_account_name=None,
            automount_service_account_token=False,
            image_pull_secrets=value.image_pull_secrets,
            security_context=PodSecurityContext(
                run_as_user=None,
                run_as_group=None,
                fs_group=1000,
                fs_group_change_policy="OnRootMismatch",
            ),
            node_selector=value.node_selector,
            tolerations=value.tolerations,
            dns_policy=None,
            dns_config=None,
            host_aliases=(),
            containers=(
                ContainerSpec(
                    name="proxy",
                    image=value.proxy_image,
                    command=None,
                    args=(),
                    working_dir="/home/azents-proxy",
                    resources=None,
                    security_context=_proxy_security_context(),
                    readiness_probe=Probe(
                        exec_action=ExecAction(
                            command=(
                                (
                                    "/workspace/python/apps/"
                                    "azents-runtime-proxy/.venv/bin/python"
                                ),
                                "-m",
                                "azents_runtime_proxy.main",
                                "ready",
                            )
                        ),
                        initial_delay_seconds=1,
                        period_seconds=2,
                        timeout_seconds=1,
                        failure_threshold=30,
                    ),
                    env=tuple(
                        EnvVar(name=name, value=item)
                        for name, item in (
                            ("AZ_RUNTIME_PROXY_POLICY_PATH", _PROXY_POLICY_PATH),
                            ("AZ_RUNTIME_PROXY_POLICY_DIGEST", policy_digest),
                            (
                                "AZ_RUNTIME_PROXY_ARTIFACT_DIGEST",
                                artifact_digest,
                            ),
                            (
                                "AZ_RUNTIME_PROXY_PUBLIC_CA_PATH",
                                _PROXY_PUBLIC_CA_PATH,
                            ),
                            (
                                "AZ_RUNTIME_PROXY_COMBINED_CA_PATH",
                                _PROXY_COMBINED_CA_PATH,
                            ),
                            (
                                "AZ_RUNTIME_PROXY_MITMPROXY_CONFDIR",
                                f"{_PROXY_RUN_PATH}/mitmproxy",
                            ),
                            ("AZ_RUNTIME_PROXY_LISTEN_HOST", "0.0.0.0"),
                            (
                                "AZ_RUNTIME_PROXY_LISTEN_PORT",
                                str(value.proxy_port),
                            ),
                            (
                                "AZ_RUNTIME_PROXY_READINESS_PORT",
                                str(value.readiness_port),
                            ),
                        )
                    ),
                    volume_mounts=(
                        VolumeMount(
                            name=_PROXY_POLICY_VOLUME,
                            mount_path="/etc/azents-runtime-proxy",
                            read_only=True,
                        ),
                        VolumeMount(
                            name=_PROXY_CA_VOLUME,
                            mount_path="/var/run/secrets/azents/runtime-proxy",
                            read_only=True,
                        ),
                        VolumeMount(
                            name=_PROXY_RUN_VOLUME,
                            mount_path=_PROXY_RUN_PATH,
                            read_only=False,
                        ),
                    ),
                ),
            ),
            volumes=(
                ConfigMapVolume(
                    name=_PROXY_POLICY_VOLUME,
                    config_map_name=policy_config_map.metadata.name,
                    items=(
                        KeyToPath(
                            key=_PROXY_POLICY_KEY,
                            path=_PROXY_POLICY_KEY,
                            mode=0o444,
                        ),
                    ),
                    default_mode=0o444,
                ),
                SecretVolume(
                    name=_PROXY_CA_VOLUME,
                    secret_name=ca_secret.metadata.name,
                    items=(
                        KeyToPath(
                            key=CA_COMBINED_SECRET_KEY,
                            path=CA_COMBINED_SECRET_KEY,
                            mode=0o400,
                        ),
                        KeyToPath(
                            key=CA_PUBLIC_SECRET_KEY,
                            path=CA_PUBLIC_SECRET_KEY,
                            mode=0o444,
                        ),
                    ),
                    default_mode=0o400,
                ),
                EmptyDirVolume(
                    name=_PROXY_RUN_VOLUME,
                    medium="Memory",
                    size_limit="16Mi",
                ),
            ),
        ),
    )


def _role_selector(runtime_id: str, role: ResourceRole) -> dict[str, str]:
    return {
        LABEL_MANAGED_BY: MANAGED_BY_VALUE,
        LABEL_RUNTIME_ID: runtime_id,
        LABEL_RESOURCE_ROLE: role.value,
        LABEL_CONFIGURATION_MANAGED: "true",
    }


def _proxy_security_context() -> ContainerSecurityContext:
    return ContainerSecurityContext(
        privileged=False,
        allow_privilege_escalation=False,
        read_only_root_filesystem=False,
        run_as_non_root=True,
        run_as_user=1000,
        run_as_group=1000,
        capabilities_add=(),
        capabilities_drop=("ALL",),
        proc_mount=None,
        seccomp_profile=SeccompProfile(
            profile_type="RuntimeDefault",
            localhost_profile=None,
        ),
    )


def _canonical_hostname(value: str) -> bool:
    if not value or value != value.lower() or value.endswith(".") or len(value) > 253:
        return False
    labels = value.split(".")
    return all(
        label
        and len(label) <= 63
        and label[0].isalnum()
        and label[-1].isalnum()
        and all(
            character.isascii() and (character.isalnum() or character == "-")
            for character in label
        )
        for label in labels
    )
