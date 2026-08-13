"""Warning-only Kubernetes Provider deployment diagnostics tests."""

import asyncio
import dataclasses
from collections.abc import Mapping, Sequence

from azents_runtime_provider_kubernetes.deployment_diagnostics import (
    DeploymentDiagnosticSettings,
    OperationalDiagnosticsState,
    collect_operational_diagnostics,
    refresh_operational_diagnostics,
)
from azents_runtime_provider_kubernetes.kubernetes_api import (
    LabelSelector,
    LabelSelectorRequirement,
    NamespaceResource,
    NetworkPolicyResource,
    NetworkPolicySpec,
    ObjectMeta,
    ServicePort,
    ServiceResource,
    ServiceSpec,
)
from azents_runtime_provider_kubernetes.network_enforcement import (
    MandatoryServiceReference,
)
from azents_runtime_provider_kubernetes.owned_resources import (
    LABEL_MANAGED_BY,
    MANAGED_BY_VALUE,
)


@dataclasses.dataclass
class FakeDeploymentDiagnosticsApi:
    """Deterministic read-only deployment inspection API."""

    api_resources: dict[str, frozenset[str]]
    api_groups: frozenset[str]
    access_allowed: bool
    namespace: NamespaceResource | None
    services: dict[tuple[str, str], ServiceResource]
    default_deny: NetworkPolicyResource | None
    policies: tuple[NetworkPolicyResource, ...]
    unexpected_discovery_failure: bool
    discovery_called: asyncio.Event

    async def discover_api_resources(self, api_version: str) -> frozenset[str]:
        self.discovery_called.set()
        if self.unexpected_discovery_failure:
            raise RuntimeError("unexpected diagnostic failure")
        return self.api_resources.get(api_version, frozenset())

    async def list_api_groups(self) -> frozenset[str]:
        return self.api_groups

    async def check_resource_access(
        self,
        *,
        namespace: str | None,
        api_group: str,
        resource: str,
        verb: str,
        resource_name: str | None,
    ) -> bool:
        del namespace, api_group, resource, verb, resource_name
        return self.access_allowed

    async def get_namespace(self, name: str) -> NamespaceResource | None:
        del name
        return self.namespace

    async def get_service(
        self,
        name: str,
        namespace: str,
    ) -> ServiceResource | None:
        return self.services.get((namespace, name))

    async def get_network_policy(
        self,
        name: str,
        namespace: str,
    ) -> NetworkPolicyResource | None:
        del name, namespace
        return self.default_deny

    async def list_network_policies(
        self,
        labels: Mapping[str, str],
        namespace: str,
    ) -> Sequence[NetworkPolicyResource]:
        del labels, namespace
        return self.policies


def _settings(
    *,
    attest_proxy_required: bool = True,
    proxy_image: str | None = None,
    proxy_addon_digest: str | None = None,
) -> DeploymentDiagnosticSettings:
    return DeploymentDiagnosticSettings(
        provider_namespace="azents",
        workload_namespace="azents-runtime",
        runtime_control_endpoint="runtime-control:8030",
        mandatory_services=(
            MandatoryServiceReference(
                role="runtime_control",
                namespace="azents",
                name="runtime-control",
                endpoint_hostnames=(
                    "runtime-control",
                    "runtime-control.azents.svc",
                ),
                ports=(8030,),
            ),
            MandatoryServiceReference(
                role="runtime_transfer",
                namespace="azents",
                name="runtime-control",
                endpoint_hostnames=(
                    "runtime-control",
                    "runtime-control.azents.svc.cluster.local",
                ),
                ports=(8030,),
            ),
        ),
        default_deny_labels={
            "app.kubernetes.io/component": "runtime-provider-kubernetes",
            "app.kubernetes.io/instance": "azents",
            "app.kubernetes.io/managed-by": "Helm",
            "app.kubernetes.io/name": "azents",
            "azents/network-policy-role": "runtime-execution-default-deny",
        },
        attest_proxy_required=attest_proxy_required,
        proxy_image=(
            proxy_image if proxy_image is not None else f"repo/proxy@sha256:{'a' * 64}"
        ),
        proxy_addon_digest=(
            proxy_addon_digest if proxy_addon_digest is not None else "b" * 64
        ),
    )


def _healthy_api() -> FakeDeploymentDiagnosticsApi:
    default_deny = _policy(
        name="azents-runtime-execution-policy-default-deny",
        labels={
            "app.kubernetes.io/component": "runtime-provider-kubernetes",
            "app.kubernetes.io/instance": "azents",
            "app.kubernetes.io/managed-by": "Helm",
            "app.kubernetes.io/name": "azents",
            "azents/network-policy-role": "runtime-execution-default-deny",
        },
        selector={
            LABEL_MANAGED_BY: MANAGED_BY_VALUE,
            "azents/execution-policy-managed": "true",
        },
    )
    service = ServiceResource(
        metadata=ObjectMeta(
            name="runtime-control",
            namespace="azents",
            labels={},
            annotations={},
        ),
        spec=ServiceSpec(
            service_type="ClusterIP",
            cluster_ip="10.96.0.10",
            selector={"app.kubernetes.io/component": "runtime-control"},
            ports=(
                ServicePort(
                    name="grpc",
                    protocol="TCP",
                    port=8030,
                    target_port="grpc",
                ),
            ),
        ),
    )
    return FakeDeploymentDiagnosticsApi(
        api_resources={
            "v1": frozenset(
                {
                    "configmaps",
                    "persistentvolumeclaims",
                    "pods",
                    "secrets",
                    "services",
                }
            ),
            "networking.k8s.io/v1": frozenset({"networkpolicies"}),
        },
        api_groups=frozenset({"cilium.io", "networking.k8s.io"}),
        access_allowed=True,
        namespace=NamespaceResource(
            name="azents-runtime",
            labels={"kubernetes.io/metadata.name": "azents-runtime"},
        ),
        services={("azents", "runtime-control"): service},
        default_deny=default_deny,
        policies=(default_deny,),
        unexpected_discovery_failure=False,
        discovery_called=asyncio.Event(),
    )


def _policy(
    *,
    name: str,
    labels: Mapping[str, str],
    selector: Mapping[str, str],
    expressions: tuple[LabelSelectorRequirement, ...] = (),
) -> NetworkPolicyResource:
    return NetworkPolicyResource(
        metadata=ObjectMeta(
            name=name,
            namespace="azents-runtime",
            labels=labels,
            annotations={},
        ),
        spec=NetworkPolicySpec(
            pod_selector=LabelSelector(
                match_labels=selector,
                match_expressions=expressions,
            ),
            policy_types=("Ingress", "Egress"),
            ingress=(),
            egress=(),
        ),
    )


async def test_healthy_deployment_has_no_operational_warnings() -> None:
    diagnostics = await collect_operational_diagnostics(_healthy_api(), _settings())

    assert diagnostics.checked_at.tzinfo is not None
    assert diagnostics.warnings == ()


async def test_deployment_concerns_are_bounded_warning_only_diagnostics() -> None:
    api = _healthy_api()
    api.api_resources = {}
    api.api_groups = frozenset()
    api.access_allowed = False
    api.namespace = None
    api.services = {}
    api.default_deny = None
    api.policies = (_policy(name="additive", labels={}, selector={}),)

    diagnostics = await collect_operational_diagnostics(
        api,
        _settings(proxy_image="mutable:latest"),
    )

    warnings = {warning.code: warning.metadata for warning in diagnostics.warnings}
    assert warnings == {
        "cni_support_unconfirmed": {"reason": "network_policy_support_unconfirmed"},
        "mandatory_service_unavailable": {
            "reason": "service_missing",
            "service_role": "runtime_control",
        },
        "namespace_default_deny_unconfirmed": {"reason": "policy_missing"},
        "namespace_identity_unconfirmed": {"reason": "namespace_unavailable"},
        "proxy_artifact_invalid": {
            "artifact_role": "proxy_image",
            "reason": "digest_missing",
        },
        "rbac_incomplete": {
            "resource_kind": "configmaps",
            "required_verb": "get",
        },
        "unexpected_network_policy": {"policy_count": "1"},
    }
    assert all(warning.severity.value == "warning" for warning in diagnostics.warnings)
    assert "mutable:latest" not in repr(warnings)
    assert "10.96.0.10" not in repr(warnings)


async def test_proxy_artifacts_are_not_checked_without_proxy_attestation() -> None:
    diagnostics = await collect_operational_diagnostics(
        _healthy_api(),
        _settings(
            attest_proxy_required=False,
            proxy_image="mutable:latest",
            proxy_addon_digest="invalid",
        ),
    )

    assert diagnostics.warnings == ()


async def test_shared_provider_and_workload_namespace_emits_warning_only() -> None:
    settings = dataclasses.replace(
        _settings(),
        provider_namespace="azents-runtime",
    )

    diagnostics = await collect_operational_diagnostics(_healthy_api(), settings)

    assert {warning.code: warning.metadata for warning in diagnostics.warnings} == {
        "namespace_identity_unconfirmed": {"reason": "namespace_mismatch"},
    }


async def test_chart_and_provider_owned_policies_are_not_unexpected() -> None:
    api = _healthy_api()
    default_deny = api.default_deny
    assert default_deny is not None
    api.policies = (
        default_deny,
        _policy(
            name="legacy",
            labels={
                "azents/network-policy-role": "runtime-legacy-workload-egress",
            },
            selector={LABEL_MANAGED_BY: MANAGED_BY_VALUE},
        ),
        _policy(
            name="runtime-owned",
            labels={
                LABEL_MANAGED_BY: MANAGED_BY_VALUE,
                "azents/resource-role": "runtime-network-policy",
            },
            selector={LABEL_MANAGED_BY: MANAGED_BY_VALUE},
        ),
    )

    diagnostics = await collect_operational_diagnostics(api, _settings())

    assert diagnostics.warnings == ()


async def test_unexpected_policy_match_expressions_are_evaluated() -> None:
    api = _healthy_api()
    default_deny = api.default_deny
    assert default_deny is not None
    api.policies = (
        default_deny,
        _policy(
            name="additive",
            labels={},
            selector={"ordinary": "label"},
            expressions=(
                LabelSelectorRequirement(
                    key=LABEL_MANAGED_BY,
                    operator="In",
                    values=(MANAGED_BY_VALUE,),
                ),
            ),
        ),
        _policy(
            name="excluded",
            labels={},
            selector={},
            expressions=(
                LabelSelectorRequirement(
                    key=LABEL_MANAGED_BY,
                    operator="DoesNotExist",
                    values=(),
                ),
            ),
        ),
    )

    diagnostics = await collect_operational_diagnostics(api, _settings())

    assert {warning.code: warning.metadata for warning in diagnostics.warnings} == {
        "unexpected_network_policy": {"policy_count": "1"},
    }


async def test_unexpected_collection_failure_remains_warning_only() -> None:
    api = _healthy_api()
    api.unexpected_discovery_failure = True

    diagnostics = await collect_operational_diagnostics(api, _settings())

    assert {warning.code: warning.metadata for warning in diagnostics.warnings} == {
        "rbac_incomplete": {
            "resource_kind": "networkpolicies",
            "required_verb": "get",
        },
    }


async def test_periodic_collection_failure_keeps_refresh_task_running() -> None:
    api = _healthy_api()
    api.unexpected_discovery_failure = True
    state = OperationalDiagnosticsState(
        await collect_operational_diagnostics(_healthy_api(), _settings())
    )
    stop = asyncio.Event()
    task = asyncio.create_task(
        refresh_operational_diagnostics(
            state,
            api,
            _settings(),
            interval_seconds=0.001,
            stop=stop,
        )
    )

    await asyncio.wait_for(api.discovery_called.wait(), timeout=1)
    assert not task.done()
    stop.set()
    await task
    assert {warning.code for warning in state.snapshot().warnings} == {
        "rbac_incomplete"
    }
