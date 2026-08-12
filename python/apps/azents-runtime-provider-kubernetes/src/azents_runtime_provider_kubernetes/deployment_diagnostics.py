"""Warning-only Kubernetes Provider deployment diagnostics."""

import asyncio
import dataclasses
import logging
import re
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from typing import Protocol

import aiohttp
from azents_runtime_control.provider import (
    RuntimeProviderOperationalDiagnostics,
    RuntimeProviderOperationalWarning,
    RuntimeProviderOperationalWarningSeverity,
)

from azents_runtime_provider_kubernetes.kubernetes_api import (
    LabelSelector,
    LabelSelectorRequirement,
    NamespaceResource,
    NetworkPolicyResource,
    ServiceResource,
)
from azents_runtime_provider_kubernetes.kubernetes_http import (
    KubernetesApiRequestError,
)
from azents_runtime_provider_kubernetes.network_enforcement import (
    InvalidMandatoryService,
    MandatoryServiceReference,
    endpoint_from_url,
)
from azents_runtime_provider_kubernetes.owned_resources import (
    LABEL_MANAGED_BY,
    LABEL_RESOURCE_ROLE,
    MANAGED_BY_VALUE,
)

_LOGGER = logging.getLogger(__name__)
_DEFAULT_DENY_NAME = "azents-runtime-execution-policy-default-deny"
_CHART_POLICY_ROLE_LABEL = "azents/network-policy-role"
_CHART_POLICY_ROLES = frozenset(
    {
        "runtime-execution-default-deny",
        "runtime-legacy-workload-egress",
    }
)
_DEFAULT_DENY_SELECTOR = {
    LABEL_MANAGED_BY: MANAGED_BY_VALUE,
    "azents/execution-policy-managed": "true",
}
_IMMUTABLE_IMAGE_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/-]*@sha256:[0-9a-f]{64}$")
_ADDON_DIGEST_RE = re.compile(r"^[0-9a-f]{64}$")
_KNOWN_CNI_API_GROUP_MARKERS = (
    "cilium.io",
    "crd.projectcalico.org",
    "antrea.io",
    "k8s.cni.cncf.io",
)
_EXPECTED_API_RESOURCES = {
    "v1": (
        "configmaps",
        "persistentvolumeclaims",
        "pods",
        "secrets",
        "services",
    ),
    "networking.k8s.io/v1": ("networkpolicies",),
}
_WORKLOAD_PERMISSIONS = (
    ("", "pods", ("get", "list", "watch", "create", "update", "patch", "delete")),
    (
        "",
        "persistentvolumeclaims",
        ("get", "list", "create", "update", "patch", "delete"),
    ),
    (
        "",
        "services",
        ("get", "list", "create", "update", "patch", "delete"),
    ),
    (
        "",
        "configmaps",
        ("get", "list", "create", "update", "patch", "delete"),
    ),
    (
        "",
        "secrets",
        ("get", "create", "update", "delete"),
    ),
    (
        "networking.k8s.io",
        "networkpolicies",
        ("get", "list", "create", "update", "patch", "delete"),
    ),
)
_EXPECTED_API_FAILURES = (
    KubernetesApiRequestError,
    aiohttp.ClientError,
    TimeoutError,
    KeyError,
    TypeError,
    ValueError,
)


class DeploymentDiagnosticsApi(Protocol):
    """Read-only Kubernetes operations used by deployment diagnostics."""

    async def discover_api_resources(self, api_version: str) -> frozenset[str]:
        """Return resource names advertised by one API version."""
        ...

    async def list_api_groups(self) -> frozenset[str]:
        """Return visible Kubernetes API group names."""
        ...

    async def check_resource_access(
        self,
        *,
        namespace: str | None,
        api_group: str,
        resource: str,
        verb: str,
        resource_name: str | None,
    ) -> bool:
        """Return whether the Provider has one exact resource permission."""
        ...

    async def get_namespace(self, name: str) -> NamespaceResource | None:
        """Return one Namespace by exact name."""
        ...

    async def get_service(
        self,
        name: str,
        namespace: str,
    ) -> ServiceResource | None:
        """Return one Service by exact name."""
        ...

    async def get_network_policy(
        self,
        name: str,
        namespace: str,
    ) -> NetworkPolicyResource | None:
        """Return one NetworkPolicy by exact name."""
        ...

    async def list_network_policies(
        self,
        labels: Mapping[str, str],
        namespace: str,
    ) -> Sequence[NetworkPolicyResource]:
        """Return NetworkPolicies matching labels in one Namespace."""
        ...


@dataclasses.dataclass(frozen=True)
class DeploymentDiagnosticSettings:
    """Deployment-owned inputs for warning-only validation."""

    provider_namespace: str
    workload_namespace: str
    runtime_control_endpoint: str
    mandatory_services: tuple[MandatoryServiceReference, ...]
    default_deny_labels: Mapping[str, str]
    attest_proxy_required: bool
    proxy_image: str | None
    proxy_addon_digest: str | None


class OperationalDiagnosticsState:
    """Mutable current diagnostics snapshot supplied to Provider heartbeats."""

    def __init__(self, current: RuntimeProviderOperationalDiagnostics) -> None:
        self.current = current

    def snapshot(self) -> RuntimeProviderOperationalDiagnostics:
        """Return the current immutable snapshot."""
        return self.current

    def replace(self, current: RuntimeProviderOperationalDiagnostics) -> None:
        """Replace the current immutable snapshot."""
        self.current = current


async def collect_operational_diagnostics(
    api: DeploymentDiagnosticsApi,
    settings: DeploymentDiagnosticSettings,
) -> RuntimeProviderOperationalDiagnostics:
    """Collect one bounded warning-only deployment snapshot."""
    try:
        return await _collect_operational_diagnostics(api, settings)
    except asyncio.CancelledError:
        raise
    except Exception:
        _LOGGER.exception("Runtime Provider deployment diagnostics collection failed")
        return _diagnostics_failure_snapshot()


async def _collect_operational_diagnostics(
    api: DeploymentDiagnosticsApi,
    settings: DeploymentDiagnosticSettings,
) -> RuntimeProviderOperationalDiagnostics:
    """Collect one deployment snapshot from individually bounded checks."""
    warnings: dict[str, RuntimeProviderOperationalWarning] = {}
    await _check_api_resources(api, warnings)
    await _check_rbac(api, settings, warnings)
    await _check_namespace_and_policies(api, settings, warnings)
    await _check_mandatory_services(api, settings, warnings)
    await _check_cni(api, warnings)
    _check_proxy_artifacts(settings, warnings)
    snapshot = RuntimeProviderOperationalDiagnostics(
        checked_at=datetime.now(UTC),
        warnings=tuple(warnings[code] for code in sorted(warnings)),
    )
    for warning in snapshot.warnings:
        _LOGGER.warning(
            "Runtime Provider deployment validation warning",
            extra={"warning_code": warning.code, **warning.metadata},
        )
    return snapshot


def _diagnostics_failure_snapshot() -> RuntimeProviderOperationalDiagnostics:
    return RuntimeProviderOperationalDiagnostics(
        checked_at=datetime.now(UTC),
        warnings=(
            RuntimeProviderOperationalWarning(
                code="rbac_incomplete",
                severity=RuntimeProviderOperationalWarningSeverity.WARNING,
                metadata={
                    "resource_kind": "networkpolicies",
                    "required_verb": "get",
                },
            ),
        ),
    )


async def refresh_operational_diagnostics(
    state: OperationalDiagnosticsState,
    api: DeploymentDiagnosticsApi,
    settings: DeploymentDiagnosticSettings,
    *,
    interval_seconds: float,
    stop: asyncio.Event,
) -> None:
    """Refresh diagnostics periodically without affecting Provider authority."""
    while not stop.is_set():
        try:
            await asyncio.wait_for(stop.wait(), timeout=interval_seconds)
            return
        except TimeoutError:
            state.replace(await collect_operational_diagnostics(api, settings))


async def _check_api_resources(
    api: DeploymentDiagnosticsApi,
    warnings: dict[str, RuntimeProviderOperationalWarning],
) -> None:
    for api_version, expected_resources in _EXPECTED_API_RESOURCES.items():
        try:
            resources = await api.discover_api_resources(api_version)
        except _EXPECTED_API_FAILURES:
            _add_warning(
                warnings,
                "rbac_incomplete",
                {"resource_kind": expected_resources[0], "required_verb": "get"},
            )
            continue
        for resource in expected_resources:
            if resource not in resources:
                _add_warning(
                    warnings,
                    "rbac_incomplete",
                    {"resource_kind": resource, "required_verb": "get"},
                )


async def _check_rbac(
    api: DeploymentDiagnosticsApi,
    settings: DeploymentDiagnosticSettings,
    warnings: dict[str, RuntimeProviderOperationalWarning],
) -> None:
    for api_group, resource, verbs in _WORKLOAD_PERMISSIONS:
        for verb in verbs:
            try:
                allowed = await api.check_resource_access(
                    namespace=settings.workload_namespace,
                    api_group=api_group,
                    resource=resource,
                    verb=verb,
                    resource_name=None,
                )
            except _EXPECTED_API_FAILURES:
                allowed = False
            if not allowed:
                _add_warning(
                    warnings,
                    "rbac_incomplete",
                    {"resource_kind": resource, "required_verb": verb},
                )
    for reference in settings.mandatory_services:
        try:
            allowed = await api.check_resource_access(
                namespace=reference.namespace,
                api_group="",
                resource="services",
                verb="get",
                resource_name=reference.name,
            )
        except _EXPECTED_API_FAILURES:
            allowed = False
        if not allowed:
            _add_warning(
                warnings,
                "rbac_incomplete",
                {"resource_kind": "services", "required_verb": "get"},
            )


async def _check_namespace_and_policies(
    api: DeploymentDiagnosticsApi,
    settings: DeploymentDiagnosticSettings,
    warnings: dict[str, RuntimeProviderOperationalWarning],
) -> None:
    try:
        namespace = await api.get_namespace(settings.workload_namespace)
    except _EXPECTED_API_FAILURES:
        namespace = None
    if settings.provider_namespace == settings.workload_namespace:
        _add_warning(
            warnings,
            "namespace_identity_unconfirmed",
            {"reason": "namespace_mismatch"},
        )
    elif namespace is None:
        _add_warning(
            warnings,
            "namespace_identity_unconfirmed",
            {"reason": "namespace_unavailable"},
        )
    elif (
        namespace.name != settings.workload_namespace
        or namespace.labels.get("kubernetes.io/metadata.name")
        != settings.workload_namespace
    ):
        _add_warning(
            warnings,
            "namespace_identity_unconfirmed",
            {"reason": "namespace_mismatch"},
        )

    try:
        default_deny = await api.get_network_policy(
            _DEFAULT_DENY_NAME,
            settings.workload_namespace,
        )
    except _EXPECTED_API_FAILURES:
        default_deny = None
    if default_deny is None:
        _add_warning(
            warnings,
            "namespace_default_deny_unconfirmed",
            {"reason": "policy_missing"},
        )
    elif any(
        default_deny.metadata.labels.get(key) != value
        for key, value in settings.default_deny_labels.items()
    ):
        _add_warning(
            warnings,
            "namespace_default_deny_unconfirmed",
            {"reason": "policy_ownership_mismatch"},
        )
    elif (
        dict(default_deny.spec.pod_selector.match_labels) != _DEFAULT_DENY_SELECTOR
        or default_deny.spec.pod_selector.match_expressions
        or set(default_deny.spec.policy_types) != {"Ingress", "Egress"}
        or default_deny.spec.ingress
        or default_deny.spec.egress
    ):
        _add_warning(
            warnings,
            "namespace_default_deny_unconfirmed",
            {"reason": "policy_selector_mismatch"},
        )

    try:
        policies = await api.list_network_policies({}, settings.workload_namespace)
    except _EXPECTED_API_FAILURES:
        return
    unexpected_count = sum(1 for policy in policies if _policy_is_unexpected(policy))
    if unexpected_count:
        _add_warning(
            warnings,
            "unexpected_network_policy",
            {"policy_count": str(unexpected_count)},
        )


async def _check_mandatory_services(
    api: DeploymentDiagnosticsApi,
    settings: DeploymentDiagnosticSettings,
    warnings: dict[str, RuntimeProviderOperationalWarning],
) -> None:
    for reference in settings.mandatory_services:
        try:
            service = await api.get_service(reference.name, reference.namespace)
        except _EXPECTED_API_FAILURES:
            service = None
        if service is None:
            _add_warning(
                warnings,
                "mandatory_service_unavailable",
                {"reason": "service_missing", "service_role": reference.role},
            )
            continue
        if (
            service.spec.service_type == "ExternalName"
            or service.spec.cluster_ip in {None, "None"}
            or not service.spec.selector
            or not set(reference.ports).issubset(
                {port.port for port in service.spec.ports if port.protocol == "TCP"}
            )
        ):
            _add_warning(
                warnings,
                "mandatory_service_unavailable",
                {
                    "reason": "cluster_ip_unavailable",
                    "service_role": reference.role,
                },
            )
            continue
        if reference.role != "runtime_control":
            continue
        try:
            endpoint = endpoint_from_url(
                settings.runtime_control_endpoint,
                default_port=None,
            )
        except InvalidMandatoryService:
            endpoint = None
        if (
            endpoint is None
            or endpoint.hostname not in reference.endpoint_hostnames
            or endpoint.port not in reference.ports
        ):
            _add_warning(
                warnings,
                "mandatory_service_unavailable",
                {
                    "reason": "endpoint_hostname_mismatch",
                    "service_role": reference.role,
                },
            )


async def _check_cni(
    api: DeploymentDiagnosticsApi,
    warnings: dict[str, RuntimeProviderOperationalWarning],
) -> None:
    try:
        network_resources = await api.discover_api_resources("networking.k8s.io/v1")
    except _EXPECTED_API_FAILURES:
        _add_warning(
            warnings,
            "cni_support_unconfirmed",
            {"reason": "api_discovery_unavailable"},
        )
        return
    if "networkpolicies" not in network_resources:
        _add_warning(
            warnings,
            "cni_support_unconfirmed",
            {"reason": "network_policy_support_unconfirmed"},
        )
        return
    try:
        groups = await api.list_api_groups()
    except _EXPECTED_API_FAILURES:
        _add_warning(
            warnings,
            "cni_support_unconfirmed",
            {"reason": "api_discovery_unavailable"},
        )
        return
    if not any(
        marker in group for marker in _KNOWN_CNI_API_GROUP_MARKERS for group in groups
    ):
        _add_warning(
            warnings,
            "cni_support_unconfirmed",
            {"reason": "cni_identity_unavailable"},
        )


def _check_proxy_artifacts(
    settings: DeploymentDiagnosticSettings,
    warnings: dict[str, RuntimeProviderOperationalWarning],
) -> None:
    if not settings.attest_proxy_required:
        return
    if settings.proxy_image is None:
        _add_warning(
            warnings,
            "proxy_artifact_invalid",
            {"artifact_role": "proxy_image", "reason": "configuration_missing"},
        )
        return
    if _IMMUTABLE_IMAGE_RE.fullmatch(settings.proxy_image) is None:
        _add_warning(
            warnings,
            "proxy_artifact_invalid",
            {"artifact_role": "proxy_image", "reason": "digest_missing"},
        )
        return
    if settings.proxy_addon_digest is None:
        _add_warning(
            warnings,
            "proxy_artifact_invalid",
            {"artifact_role": "policy_addon", "reason": "configuration_missing"},
        )
    elif _ADDON_DIGEST_RE.fullmatch(settings.proxy_addon_digest) is None:
        _add_warning(
            warnings,
            "proxy_artifact_invalid",
            {"artifact_role": "policy_addon", "reason": "digest_mismatch"},
        )


def _policy_is_unexpected(policy: NetworkPolicyResource) -> bool:
    labels = policy.metadata.labels
    if labels.get(_CHART_POLICY_ROLE_LABEL) in _CHART_POLICY_ROLES:
        return False
    if (
        labels.get(LABEL_MANAGED_BY) == MANAGED_BY_VALUE
        and labels.get(LABEL_RESOURCE_ROLE) is not None
    ):
        return False
    return _selector_can_select_managed_pod(policy.spec.pod_selector)


def _selector_can_select_managed_pod(selector: LabelSelector) -> bool:
    managed_label = selector.match_labels.get(LABEL_MANAGED_BY)
    if managed_label is not None and managed_label != MANAGED_BY_VALUE:
        return False
    return all(
        _requirement_can_select_managed_pod(requirement)
        for requirement in selector.match_expressions
    )


def _requirement_can_select_managed_pod(
    requirement: LabelSelectorRequirement,
) -> bool:
    if requirement.key != LABEL_MANAGED_BY:
        return True
    if requirement.operator == "In":
        return MANAGED_BY_VALUE in requirement.values
    if requirement.operator == "NotIn":
        return MANAGED_BY_VALUE not in requirement.values
    if requirement.operator == "Exists":
        return True
    if requirement.operator == "DoesNotExist":
        return False
    raise ValueError("unsupported Kubernetes label selector operator")


def _add_warning(
    warnings: dict[str, RuntimeProviderOperationalWarning],
    code: str,
    metadata: dict[str, str],
) -> None:
    if code in warnings:
        return
    warnings[code] = RuntimeProviderOperationalWarning(
        code=code,
        severity=RuntimeProviderOperationalWarningSeverity.WARNING,
        metadata=metadata,
    )
