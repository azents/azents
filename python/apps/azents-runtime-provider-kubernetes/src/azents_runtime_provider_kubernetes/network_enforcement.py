"""Mode-aware Kubernetes Runtime network enforcement inputs and policies."""

import dataclasses
import hashlib
import ipaddress
from collections.abc import Mapping, Sequence
from urllib.parse import urlsplit

from azents_runtime_control.runtime_configuration import (
    RuntimeDirectNetworkAccess,
    RuntimeNetworkAccess,
    RuntimeNetworkMode,
    RuntimeNoNetworkAccess,
    RuntimeProxyRequiredNetworkAccess,
)

from azents_runtime_provider_kubernetes.kubernetes_api import (
    HostAlias,
    IpBlock,
    LabelSelector,
    NetworkPolicyEgressRule,
    NetworkPolicyIngressRule,
    NetworkPolicyPeer,
    NetworkPolicyPort,
    NetworkPolicyResource,
    NetworkPolicySpec,
    ObjectMeta,
    PodDnsConfig,
    PodDnsConfigOption,
    ServiceResource,
)
from azents_runtime_provider_kubernetes.owned_resources import (
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
    resource_name,
)

STRICT_DNS_POLICY = "None"
STRICT_DNS_CONFIG = PodDnsConfig(
    nameservers=("127.0.0.1",),
    searches=(),
    options=(
        PodDnsConfigOption(name="ndots", value="1"),
        PodDnsConfigOption(name="timeout", value="1"),
        PodDnsConfigOption(name="attempts", value="1"),
    ),
)
_NAMESPACE_LABEL = "kubernetes.io/metadata.name"


class InvalidMandatoryService(ValueError):
    """A mandatory Platform Service cannot be used as Runtime authority."""


@dataclasses.dataclass(frozen=True)
class MandatoryServiceReference:
    """Deployment-owned reference for one Runtime Platform endpoint role."""

    role: str
    namespace: str
    name: str
    endpoint_hostnames: tuple[str, ...]
    ports: tuple[int, ...]

    def __post_init__(self) -> None:
        """Reject incomplete or over-broad deployment references."""
        if self.role not in {"runtime_control", "runtime_transfer"}:
            raise ValueError("mandatory Service role is unsupported")
        if not self.namespace or not self.name:
            raise ValueError("mandatory Service namespace and name are required")
        if not self.endpoint_hostnames or any(
            not _canonical_hostname(item) for item in self.endpoint_hostnames
        ):
            raise ValueError("mandatory Service endpoint hostnames are invalid")
        if len(set(self.endpoint_hostnames)) != len(self.endpoint_hostnames):
            raise ValueError("mandatory Service endpoint hostnames must be unique")
        if not self.ports or any(not 1 <= port <= 65_535 for port in self.ports):
            raise ValueError("mandatory Service ports are invalid")
        if len(set(self.ports)) != len(self.ports):
            raise ValueError("mandatory Service ports must be unique")


@dataclasses.dataclass(frozen=True)
class ObservedMandatoryService:
    """Validated stable Service mapping used by one Runtime incarnation."""

    reference: MandatoryServiceReference
    cluster_ip: str
    selector: Mapping[str, str]
    target_ports: tuple[int | str, ...]


@dataclasses.dataclass(frozen=True)
class RuntimeEndpoint:
    """One exact Runtime command endpoint."""

    hostname: str
    port: int


@dataclasses.dataclass(frozen=True)
class NetworkEnforcementInputs:
    """Pure inputs for complete Runtime and proxy NetworkPolicies."""

    namespace: str
    identity: OwnedResourceIdentity
    desired_generation: int
    configuration_sequence: int
    configuration_digest: str
    network_access: RuntimeNetworkAccess
    mandatory_services: tuple[ObservedMandatoryService, ...]
    runtime_control_namespace: str
    runtime_control_labels: Mapping[str, str]
    network_hard_cap_allowed_cidrs: tuple[str, ...]
    network_hard_cap_denied_cidrs: tuple[str, ...]
    network_hard_cap_extra_egress: tuple[NetworkPolicyEgressRule, ...]
    proxy_port: int


@dataclasses.dataclass(frozen=True)
class RuntimeNetworkInputs:
    """Runtime Pod DNS, hosts, and complete policy inputs."""

    dns_policy: str | None
    dns_config: PodDnsConfig | None
    host_aliases: tuple[HostAlias, ...]
    runtime_policy: NetworkPolicyResource


@dataclasses.dataclass(frozen=True)
class ProxyNetworkInputs:
    """Proxy-specific complete ingress and egress policies."""

    ingress_policy: NetworkPolicyResource
    egress_policy: NetworkPolicyResource


def proxy_artifact_digest(*, proxy_image: str, addon_digest: str) -> str:
    """Return one evidence digest for the immutable proxy image and addon."""
    image_digest = _immutable_image_digest(proxy_image)
    if not _sha256_digest(addon_digest):
        raise ValueError("proxy addon artifact digest must be SHA-256")
    return hashlib.sha256(
        f"proxy-image:{image_digest}\naddon:{addon_digest}\n".encode("ascii")
    ).hexdigest()


def endpoint_from_url(value: str, *, default_port: int | None) -> RuntimeEndpoint:
    """Parse one command endpoint into an exact canonical hostname and port."""
    parsed = urlsplit(value if "://" in value else f"//{value}")
    hostname = parsed.hostname
    if hostname is None or not _canonical_hostname(hostname):
        raise InvalidMandatoryService("Runtime endpoint hostname is invalid")
    try:
        port = parsed.port
    except ValueError as error:
        raise InvalidMandatoryService("Runtime endpoint port is invalid") from error
    if port is None:
        port = default_port
    if port is None or not 1 <= port <= 65_535:
        raise InvalidMandatoryService("Runtime endpoint port is required")
    return RuntimeEndpoint(hostname=hostname, port=port)


def observe_mandatory_service(
    reference: MandatoryServiceReference,
    service: ServiceResource | None,
) -> ObservedMandatoryService:
    """Validate one explicit mandatory Service and return its stable mapping."""
    if service is None:
        raise InvalidMandatoryService(
            f"mandatory Service is missing for role {reference.role}"
        )
    if (
        service.metadata.namespace != reference.namespace
        or service.metadata.name != reference.name
    ):
        raise InvalidMandatoryService(
            f"mandatory Service identity mismatch for role {reference.role}"
        )
    if service.spec.service_type == "ExternalName":
        raise InvalidMandatoryService(
            f"mandatory Service cannot be ExternalName for role {reference.role}"
        )
    cluster_ip = service.spec.cluster_ip
    if cluster_ip is None or cluster_ip == "None":
        raise InvalidMandatoryService(
            f"mandatory Service ClusterIP is unavailable for role {reference.role}"
        )
    try:
        address = ipaddress.ip_address(cluster_ip)
    except ValueError as error:
        raise InvalidMandatoryService(
            f"mandatory Service ClusterIP is invalid for role {reference.role}"
        ) from error
    if not service.spec.selector:
        raise InvalidMandatoryService(
            f"mandatory Service selector is unavailable for role {reference.role}"
        )
    selected_ports = tuple(
        item
        for item in service.spec.ports
        if item.protocol == "TCP" and item.port in reference.ports
    )
    if {item.port for item in selected_ports} != set(reference.ports):
        raise InvalidMandatoryService(
            f"mandatory Service port is unavailable for role {reference.role}"
        )
    return ObservedMandatoryService(
        reference=reference,
        cluster_ip=address.compressed,
        selector=dict(service.spec.selector),
        target_ports=tuple(item.target_port for item in selected_ports),
    )


def validate_endpoint_authority(
    endpoint: RuntimeEndpoint,
    observed: Sequence[ObservedMandatoryService],
    *,
    role: str,
) -> None:
    """Require a command endpoint to match its explicit Service reference."""
    matches = tuple(item for item in observed if item.reference.role == role)
    if len(matches) != 1:
        raise InvalidMandatoryService(
            f"mandatory Service reference count is invalid for role {role}"
        )
    reference = matches[0].reference
    if (
        endpoint.hostname not in reference.endpoint_hostnames
        or endpoint.port not in reference.ports
    ):
        raise InvalidMandatoryService(
            f"Runtime endpoint does not match mandatory Service role {role}"
        )


def build_runtime_network_inputs(
    value: NetworkEnforcementInputs,
    *,
    proxy_service_ip: str | None,
    proxy_hostname: str | None,
) -> RuntimeNetworkInputs:
    """Build strict Pod inputs and one complete Runtime NetworkPolicy."""
    mode = value.network_access.mode
    if mode is RuntimeNetworkMode.DIRECT:
        if proxy_service_ip is not None or proxy_hostname is not None:
            raise ValueError("direct mode cannot include proxy host inputs")
        dns_policy = None
        dns_config = None
        host_aliases: tuple[HostAlias, ...] = ()
        egress = (
            _dns_egress_rule(),
            *_mandatory_service_rules(value.mandatory_services),
            *_permitted_cidr_rules(value),
            *value.network_hard_cap_extra_egress,
        )
    elif mode is RuntimeNetworkMode.PROXY_REQUIRED:
        if proxy_service_ip is None or proxy_hostname is None:
            raise ValueError("proxy-required mode requires proxy host inputs")
        dns_policy = STRICT_DNS_POLICY
        dns_config = STRICT_DNS_CONFIG
        host_aliases = _host_aliases(
            value.mandatory_services,
            proxy_service_ip=proxy_service_ip,
            proxy_hostname=proxy_hostname,
        )
        egress = (
            *_mandatory_service_rules(value.mandatory_services),
            _proxy_service_rule(value),
        )
    elif mode is RuntimeNetworkMode.NO_NETWORK:
        if proxy_service_ip is not None or proxy_hostname is not None:
            raise ValueError("no-network mode cannot include proxy host inputs")
        dns_policy = STRICT_DNS_POLICY
        dns_config = STRICT_DNS_CONFIG
        host_aliases = _host_aliases(value.mandatory_services)
        egress = _mandatory_service_rules(value.mandatory_services)
    else:
        raise AssertionError(f"unsupported Runtime network mode: {mode}")
    return RuntimeNetworkInputs(
        dns_policy=dns_policy,
        dns_config=dns_config,
        host_aliases=host_aliases,
        runtime_policy=_network_policy(
            value,
            ResourceRole.RUNTIME_NETWORK_POLICY,
            policy_types=("Ingress", "Egress"),
            ingress=(),
            egress=egress,
        ),
    )


def build_proxy_network_inputs(value: NetworkEnforcementInputs) -> ProxyNetworkInputs:
    """Build complete matching-Runtime ingress and bounded proxy egress policies."""
    if not isinstance(value.network_access, RuntimeProxyRequiredNetworkAccess):
        raise ValueError("proxy policies require proxy-required network access")
    ingress = NetworkPolicyIngressRule(
        peers=(
            NetworkPolicyPeer(
                namespace_selector=LabelSelector(
                    match_labels={_NAMESPACE_LABEL: value.namespace},
                    match_expressions=(),
                ),
                pod_selector=LabelSelector(
                    match_labels={
                        LABEL_MANAGED_BY: MANAGED_BY_VALUE,
                        LABEL_RUNTIME_ID: value.identity.runtime_id,
                        LABEL_RESOURCE_ROLE: ResourceRole.RUNTIME_POD.value,
                        LABEL_CONFIGURATION_MANAGED: "true",
                    },
                    match_expressions=(),
                ),
                ip_block=None,
            ),
        ),
        ports=(NetworkPolicyPort(protocol="TCP", port=value.proxy_port),),
    )
    egress = (
        _dns_egress_rule(),
        *_permitted_cidr_rules(value),
    )
    return ProxyNetworkInputs(
        ingress_policy=_network_policy(
            value,
            ResourceRole.PROXY_INGRESS_NETWORK_POLICY,
            policy_types=("Ingress",),
            ingress=(ingress,),
            egress=(),
        ),
        egress_policy=_network_policy(
            value,
            ResourceRole.PROXY_EGRESS_NETWORK_POLICY,
            policy_types=("Egress",),
            ingress=(),
            egress=egress,
        ),
    )


def _network_policy(
    value: NetworkEnforcementInputs,
    role: ResourceRole,
    *,
    policy_types: tuple[str, ...],
    ingress: tuple[NetworkPolicyIngressRule, ...],
    egress: tuple[NetworkPolicyEgressRule, ...],
) -> NetworkPolicyResource:
    return NetworkPolicyResource(
        metadata=ObjectMeta(
            name=resource_name(value.identity.runtime_id, role),
            namespace=value.namespace,
            labels=owned_labels(
                value.identity,
                role,
                desired_generation=value.desired_generation,
            ),
            annotations=owned_annotations(
                OwnedResourceAnnotations(
                    configuration_sequence=value.configuration_sequence,
                    configuration_digest=value.configuration_digest,
                    policy_digest=None,
                    ca_fingerprint=None,
                    artifact_digest=None,
                )
            ),
        ),
        spec=NetworkPolicySpec(
            pod_selector=LabelSelector(
                match_labels={
                    LABEL_MANAGED_BY: MANAGED_BY_VALUE,
                    LABEL_RUNTIME_ID: value.identity.runtime_id,
                    LABEL_RESOURCE_ROLE: (
                        ResourceRole.RUNTIME_POD.value
                        if role is ResourceRole.RUNTIME_NETWORK_POLICY
                        else ResourceRole.PROXY_POD.value
                    ),
                    LABEL_CONFIGURATION_MANAGED: "true",
                },
                match_expressions=(),
            ),
            policy_types=policy_types,
            ingress=ingress,
            egress=egress,
        ),
    )


def _mandatory_service_rules(
    observed: Sequence[ObservedMandatoryService],
) -> tuple[NetworkPolicyEgressRule, ...]:
    return tuple(
        NetworkPolicyEgressRule(
            peers=(
                NetworkPolicyPeer(
                    namespace_selector=LabelSelector(
                        match_labels={
                            _NAMESPACE_LABEL: item.reference.namespace,
                        },
                        match_expressions=(),
                    ),
                    pod_selector=LabelSelector(
                        match_labels=item.selector,
                        match_expressions=(),
                    ),
                    ip_block=None,
                ),
            ),
            ports=tuple(
                NetworkPolicyPort(protocol="TCP", port=port)
                for port in item.target_ports
            ),
        )
        for item in sorted(
            observed,
            key=lambda item: (
                item.reference.role,
                item.reference.namespace,
                item.reference.name,
            ),
        )
    )


def _proxy_service_rule(value: NetworkEnforcementInputs) -> NetworkPolicyEgressRule:
    return NetworkPolicyEgressRule(
        peers=(
            NetworkPolicyPeer(
                namespace_selector=LabelSelector(
                    match_labels={_NAMESPACE_LABEL: value.namespace},
                    match_expressions=(),
                ),
                pod_selector=LabelSelector(
                    match_labels={
                        LABEL_MANAGED_BY: MANAGED_BY_VALUE,
                        LABEL_RUNTIME_ID: value.identity.runtime_id,
                        LABEL_RESOURCE_ROLE: ResourceRole.PROXY_POD.value,
                        LABEL_CONFIGURATION_MANAGED: "true",
                    },
                    match_expressions=(),
                ),
                ip_block=None,
            ),
        ),
        ports=(NetworkPolicyPort(protocol="TCP", port=value.proxy_port),),
    )


def _dns_egress_rule() -> NetworkPolicyEgressRule:
    return NetworkPolicyEgressRule(
        peers=(
            NetworkPolicyPeer(
                namespace_selector=LabelSelector(
                    match_labels={_NAMESPACE_LABEL: "kube-system"},
                    match_expressions=(),
                ),
                pod_selector=LabelSelector(
                    match_labels={"k8s-app": "kube-dns"},
                    match_expressions=(),
                ),
                ip_block=None,
            ),
        ),
        ports=(
            NetworkPolicyPort(protocol="UDP", port=53),
            NetworkPolicyPort(protocol="TCP", port=53),
        ),
    )


def _permitted_cidr_rules(
    value: NetworkEnforcementInputs,
) -> tuple[NetworkPolicyEgressRule, ...]:
    access = value.network_access
    if isinstance(access, RuntimeNoNetworkAccess):
        return ()
    if not isinstance(
        access,
        RuntimeDirectNetworkAccess | RuntimeProxyRequiredNetworkAccess,
    ):
        raise AssertionError(f"unsupported Runtime network access: {access!r}")
    allowed = _network_intersection(
        value.network_hard_cap_allowed_cidrs,
        access.allowed_cidrs,
    )
    denied = tuple(
        _network(item)
        for item in (
            *value.network_hard_cap_denied_cidrs,
            *access.denied_cidrs,
        )
    )
    return tuple(
        NetworkPolicyEgressRule(
            peers=(
                NetworkPolicyPeer(
                    namespace_selector=None,
                    pod_selector=None,
                    ip_block=IpBlock(
                        cidr=str(network),
                        except_cidrs=tuple(
                            str(item)
                            for item in denied
                            if _subnet_of_same_family(item, network)
                        ),
                    ),
                ),
            ),
            ports=(),
        )
        for network in allowed
    )


def _network_intersection(
    first: tuple[str, ...],
    second: tuple[str, ...],
) -> tuple[ipaddress.IPv4Network | ipaddress.IPv6Network, ...]:
    first_networks = tuple(_network(item) for item in first)
    second_networks = tuple(_network(item) for item in second)
    if not first_networks:
        return second_networks or (
            ipaddress.ip_network("0.0.0.0/0"),
            ipaddress.ip_network("::/0"),
        )
    if not second_networks:
        return first_networks
    intersections: set[ipaddress.IPv4Network | ipaddress.IPv6Network] = set()
    for left in first_networks:
        for right in second_networks:
            if _subnet_of_same_family(left, right):
                intersections.add(left)
            elif _subnet_of_same_family(right, left):
                intersections.add(right)
    return tuple(
        sorted(
            intersections,
            key=lambda item: (item.version, item.network_address, item.prefixlen),
        )
    )


def _host_aliases(
    observed: Sequence[ObservedMandatoryService],
    *,
    proxy_service_ip: str | None = None,
    proxy_hostname: str | None = None,
) -> tuple[HostAlias, ...]:
    by_ip: dict[str, set[str]] = {}
    for item in observed:
        by_ip.setdefault(item.cluster_ip, set()).update(
            item.reference.endpoint_hostnames
        )
    if proxy_service_ip is not None and proxy_hostname is not None:
        by_ip.setdefault(
            ipaddress.ip_address(proxy_service_ip).compressed,
            set(),
        ).add(proxy_hostname)
    return tuple(
        HostAlias(ip=address, hostnames=tuple(sorted(hostnames)))
        for address, hostnames in sorted(
            by_ip.items(),
            key=lambda item: (ipaddress.ip_address(item[0]).version, item[0]),
        )
    )


def _network(value: str) -> ipaddress.IPv4Network | ipaddress.IPv6Network:
    return ipaddress.ip_network(value, strict=True)


def _subnet_of_same_family(
    candidate: ipaddress.IPv4Network | ipaddress.IPv6Network,
    container: ipaddress.IPv4Network | ipaddress.IPv6Network,
) -> bool:
    return candidate.version == container.version and candidate.subnet_of(container)


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


def _immutable_image_digest(value: str) -> str:
    marker = "@sha256:"
    if marker not in value:
        raise ValueError("proxy image must use an immutable SHA-256 digest")
    digest = value.rsplit(marker, 1)[1]
    if not _sha256_digest(digest):
        raise ValueError("proxy image must use an immutable SHA-256 digest")
    return digest


def _sha256_digest(value: str) -> bool:
    return len(value) == 64 and all(
        character in "0123456789abcdef" for character in value
    )
