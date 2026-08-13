"""Mode-aware Kubernetes network enforcement builder tests."""

import dataclasses
from collections.abc import Sequence

import pytest
from azents_runtime_control.runtime_configuration import (
    RuntimeDirectNetworkAccess,
    RuntimeNetworkMode,
    RuntimeNoNetworkAccess,
    RuntimeProxyDomainMode,
    RuntimeProxyDomainPolicy,
    RuntimeProxyRequiredNetworkAccess,
)

from azents_runtime_provider_kubernetes.kubernetes_api import (
    HostAlias,
    LabelSelector,
    NetworkPolicyEgressRule,
    NetworkPolicyPeer,
    NetworkPolicyPort,
    ObjectMeta,
    ServicePort,
    ServiceResource,
    ServiceSpec,
)
from azents_runtime_provider_kubernetes.network_enforcement import (
    STRICT_DNS_CONFIG,
    STRICT_DNS_POLICY,
    InvalidMandatoryService,
    MandatoryServiceReference,
    NetworkEnforcementInputs,
    build_proxy_network_inputs,
    build_runtime_network_inputs,
    endpoint_from_url,
    observe_mandatory_service,
    proxy_artifact_digest,
    validate_endpoint_authority,
)
from azents_runtime_provider_kubernetes.owned_resources import (
    LABEL_RESOURCE_ROLE,
    OwnedResourceIdentity,
    ResourceRole,
)


def test_observe_mandatory_service_validates_stable_selected_cluster_ip() -> None:
    observed = observe_mandatory_service(
        _reference("runtime_control", port=8020),
        _service(port=8020, target_port="grpc"),
    )

    assert observed.cluster_ip == "10.96.0.10"
    assert observed.selector == {"app": "runtime-control"}
    assert observed.target_ports == ("grpc",)


@pytest.mark.parametrize(
    ("change", "message"),
    (
        ({"service_type": "ExternalName"}, "ExternalName"),
        ({"cluster_ip": "None"}, "ClusterIP"),
        ({"selector": {}}, "selector"),
        ({"ports": ()}, "port"),
    ),
)
def test_observe_mandatory_service_rejects_unsuitable_service(
    change: dict[str, object],
    message: str,
) -> None:
    service = _service(port=8020, target_port="grpc")
    spec = dataclasses.replace(service.spec, **change)

    with pytest.raises(InvalidMandatoryService, match=message):
        observe_mandatory_service(
            _reference("runtime_control", port=8020),
            dataclasses.replace(service, spec=spec),
        )


def test_endpoint_authority_requires_exact_role_hostname_and_port() -> None:
    observed = (
        observe_mandatory_service(
            _reference("runtime_control", port=8020),
            _service(port=8020, target_port="grpc"),
        ),
    )

    validate_endpoint_authority(
        endpoint_from_url("runtime-control.azents.svc:8020", default_port=None),
        observed,
        role="runtime_control",
    )

    with pytest.raises(InvalidMandatoryService, match="does not match"):
        validate_endpoint_authority(
            endpoint_from_url("other.azents.svc:8020", default_port=None),
            observed,
            role="runtime_control",
        )


def test_direct_runtime_retains_dns_platform_and_customer_cidrs() -> None:
    value = _inputs(
        RuntimeDirectNetworkAccess(
            mode=RuntimeNetworkMode.DIRECT,
            allowed_cidrs=("203.0.113.0/24",),
            denied_cidrs=("203.0.113.128/25",),
        )
    )

    result = build_runtime_network_inputs(
        value,
        proxy_service_ip=None,
        proxy_hostname=None,
    )

    assert result.dns_policy is None
    assert result.dns_config is None
    assert result.host_aliases == ()
    assert len(result.runtime_policy.spec.egress) == 5
    assert _has_dns_rule(result.runtime_policy.spec.egress)
    assert _cidr_blocks(result.runtime_policy.spec.egress) == {
        ("203.0.113.0/24", ("203.0.113.128/25",)),
    }


def test_proxy_required_runtime_is_platform_and_own_proxy_only() -> None:
    value = _inputs(_proxy_access())

    result = build_runtime_network_inputs(
        value,
        proxy_service_ip="10.96.0.20",
        proxy_hostname="azents-runtime-runtime-1-proxy.azents-runtime.svc",
    )

    assert result.dns_policy == STRICT_DNS_POLICY
    assert result.dns_config == STRICT_DNS_CONFIG
    assert result.host_aliases == (
        _host_alias("10.96.0.10", "runtime-control.azents.svc"),
        _host_alias(
            "10.96.0.20",
            "azents-runtime-runtime-1-proxy.azents-runtime.svc",
        ),
    )
    assert len(result.runtime_policy.spec.egress) == 3
    assert not _has_dns_rule(result.runtime_policy.spec.egress)
    assert _cidr_blocks(result.runtime_policy.spec.egress) == set()
    proxy_rule = result.runtime_policy.spec.egress[-1]
    assert proxy_rule.ports == (NetworkPolicyPort(protocol="TCP", port=8080),)
    assert proxy_rule.peers[0].pod_selector == LabelSelector(
        match_labels={
            "azents/managed-by": "azents-runtime-provider-kubernetes",
            "azents/runtime-id": "runtime-1",
            "azents/resource-role": "proxy-pod",
            "azents/runtime-configuration-managed": "true",
        },
        match_expressions=(),
    )


def test_no_network_runtime_is_platform_only_without_dns() -> None:
    result = build_runtime_network_inputs(
        _inputs(RuntimeNoNetworkAccess(mode=RuntimeNetworkMode.NO_NETWORK)),
        proxy_service_ip=None,
        proxy_hostname=None,
    )

    assert result.dns_policy == STRICT_DNS_POLICY
    assert result.dns_config == STRICT_DNS_CONFIG
    assert result.host_aliases == (
        _host_alias("10.96.0.10", "runtime-control.azents.svc"),
    )
    assert len(result.runtime_policy.spec.egress) == 2
    assert not _has_dns_rule(result.runtime_policy.spec.egress)
    assert _cidr_blocks(result.runtime_policy.spec.egress) == set()


def test_proxy_policies_select_matching_roles_and_destination_boundary() -> None:
    result = build_proxy_network_inputs(_inputs(_proxy_access()))

    assert result.ingress_policy.spec.policy_types == ("Ingress",)
    assert result.ingress_policy.spec.egress == ()
    ingress = result.ingress_policy.spec.ingress[0]
    assert ingress.ports == (NetworkPolicyPort(protocol="TCP", port=8080),)
    assert ingress.peers[0].pod_selector is not None
    assert ingress.peers[0].pod_selector.match_labels[LABEL_RESOURCE_ROLE] == (
        ResourceRole.RUNTIME_POD.value
    )
    assert result.egress_policy.spec.policy_types == ("Egress",)
    assert result.egress_policy.spec.ingress == ()
    assert _has_dns_rule(result.egress_policy.spec.egress)
    assert _cidr_blocks(result.egress_policy.spec.egress) == {
        ("203.0.113.0/24", ("203.0.113.128/25",)),
    }
    assert all(
        peer.namespace_selector
        != LabelSelector(match_labels={"extra": "true"}, match_expressions=())
        for rule in result.egress_policy.spec.egress
        for peer in rule.peers
    )


def test_proxy_artifact_digest_covers_image_and_addon() -> None:
    first = proxy_artifact_digest(
        proxy_image=f"repo/proxy@sha256:{'a' * 64}",
        addon_digest="b" * 64,
    )

    assert first == proxy_artifact_digest(
        proxy_image=f"repo/proxy@sha256:{'a' * 64}",
        addon_digest="b" * 64,
    )
    assert first != proxy_artifact_digest(
        proxy_image=f"repo/proxy@sha256:{'c' * 64}",
        addon_digest="b" * 64,
    )
    assert first != proxy_artifact_digest(
        proxy_image=f"repo/proxy@sha256:{'a' * 64}",
        addon_digest="d" * 64,
    )


def _inputs(
    network_access: (
        RuntimeDirectNetworkAccess
        | RuntimeProxyRequiredNetworkAccess
        | RuntimeNoNetworkAccess
    ),
) -> NetworkEnforcementInputs:
    control = observe_mandatory_service(
        _reference("runtime_control", port=8020),
        _service(port=8020, target_port="grpc-control"),
    )
    transfer = observe_mandatory_service(
        _reference("runtime_transfer", port=8030),
        _service(port=8030, target_port=8030),
    )
    return NetworkEnforcementInputs(
        namespace="azents-runtime",
        identity=OwnedResourceIdentity(
            provider_id="provider-k8s",
            runtime_id="runtime-1",
            workspace_id="workspace-1",
            agent_id="agent-1",
        ),
        desired_generation=3,
        configuration_sequence=7,
        configuration_digest="d" * 64,
        network_access=network_access,
        mandatory_services=(control, transfer),
        runtime_control_namespace="azents",
        runtime_control_labels={"app": "runtime-control"},
        network_hard_cap_allowed_cidrs=(),
        network_hard_cap_denied_cidrs=(),
        network_hard_cap_extra_egress=(_extra_egress(),),
        proxy_port=8080,
    )


def _reference(role: str, *, port: int) -> MandatoryServiceReference:
    return MandatoryServiceReference(
        role=role,
        namespace="azents",
        name="runtime-control",
        endpoint_hostnames=("runtime-control.azents.svc",),
        ports=(port,),
    )


def _service(*, port: int, target_port: int | str) -> ServiceResource:
    return ServiceResource(
        metadata=ObjectMeta(
            name="runtime-control",
            namespace="azents",
            labels={},
            annotations={},
        ),
        spec=ServiceSpec(
            service_type="ClusterIP",
            cluster_ip="10.96.0.10",
            selector={"app": "runtime-control"},
            ports=(
                ServicePort(
                    name="grpc",
                    protocol="TCP",
                    port=port,
                    target_port=target_port,
                ),
            ),
        ),
    )


def _proxy_access() -> RuntimeProxyRequiredNetworkAccess:
    return RuntimeProxyRequiredNetworkAccess(
        mode=RuntimeNetworkMode.PROXY_REQUIRED,
        allowed_cidrs=("203.0.113.0/24",),
        denied_cidrs=("203.0.113.128/25",),
        domain_policy=RuntimeProxyDomainPolicy(
            mode=RuntimeProxyDomainMode.ALLOWLIST,
            allowed_domains=("*.example.com",),
            denied_domains=("blocked.example.com",),
        ),
    )


def _extra_egress() -> NetworkPolicyEgressRule:
    return NetworkPolicyEgressRule(
        peers=(
            NetworkPolicyPeer(
                namespace_selector=LabelSelector(
                    match_labels={"extra": "true"},
                    match_expressions=(),
                ),
                pod_selector=None,
                ip_block=None,
            ),
        ),
        ports=(NetworkPolicyPort(protocol="TCP", port=443),),
    )


def _has_dns_rule(rules: Sequence[NetworkPolicyEgressRule]) -> bool:
    return any(
        {port.port for port in rule.ports} == {53}
        and {port.protocol for port in rule.ports} == {"TCP", "UDP"}
        for rule in rules
    )


def _cidr_blocks(
    rules: Sequence[NetworkPolicyEgressRule],
) -> set[tuple[str, tuple[str, ...]]]:
    return {
        (peer.ip_block.cidr, tuple(peer.ip_block.except_cidrs))
        for rule in rules
        for peer in rule.peers
        if peer.ip_block is not None
    }


def _host_alias(ip: str, hostname: str) -> HostAlias:
    return HostAlias(ip=ip, hostnames=(hostname,))
