"""Deterministic Kubernetes ownership metadata and safe comparison views."""

import dataclasses
import enum
import hashlib
import re
from collections.abc import Mapping

from azents_runtime_provider_kubernetes.kubernetes_api import (
    ConfigMapResource,
    ObjectMeta,
    SecretResource,
    ServiceResource,
)

LABEL_MANAGED_BY = "azents/managed-by"
LABEL_PROVIDER_ID = "azents/runtime-provider-id"
LABEL_RUNTIME_ID = "azents/runtime-id"
LABEL_AGENT_ID = "azents/agent-id"
LABEL_WORKSPACE_ID = "azents/workspace-id"
LABEL_RESOURCE_ROLE = "azents/resource-role"
LABEL_DESIRED_GENERATION = "azents/desired-generation"
LABEL_CONFIGURATION_MANAGED = "azents/runtime-configuration-managed"
ANNOTATION_CONFIGURATION_SEQUENCE = "azents/runtime-configuration-sequence"
ANNOTATION_CONFIGURATION_DIGEST = "azents/runtime-configuration-digest"
ANNOTATION_POLICY_DIGEST = "azents/proxy-policy-digest"
ANNOTATION_CA_FINGERPRINT = "azents/runtime-ca-fingerprint"
ANNOTATION_ARTIFACT_DIGEST = "azents/proxy-artifact-digest"
ANNOTATION_NETWORK_MODE = "azents/runtime-network-mode"
MANAGED_BY_VALUE = "azents-runtime-provider-kubernetes"

_RUNTIME_ID_RE = re.compile(r"^[A-Za-z0-9_.-]+$")
_KUBERNETES_NAME_RE = re.compile(r"^[a-z0-9](?:[-a-z0-9.]*[a-z0-9])?$")
_DIGEST_RE = re.compile(r"^[0-9a-f]{64}$")
_MAX_KUBERNETES_NAME_LENGTH = 253


class InvalidRuntimeId(ValueError):
    """Runtime id cannot be mapped to Kubernetes resource names."""


class InvalidOwnedResourceMetadata(ValueError):
    """Provider-owned resource metadata is incomplete or inconsistent."""


class ResourceRole(enum.StrEnum):
    """One Provider-owned Kubernetes resource role."""

    RUNTIME_POD = "runtime-pod"
    WORKSPACE_PVC = "workspace-pvc"
    RUNTIME_NETWORK_POLICY = "runtime-network-policy"
    RUNTIME_CA = "runtime-ca"
    PROXY_POLICY = "proxy-policy"
    PROXY_SERVICE = "proxy-service"
    PROXY_POD = "proxy-pod"
    PROXY_INGRESS_NETWORK_POLICY = "proxy-ingress-network-policy"
    PROXY_EGRESS_NETWORK_POLICY = "proxy-egress-network-policy"


@dataclasses.dataclass(frozen=True)
class OwnedResourceIdentity:
    """Stable logical identity shared by one Runtime's owned resources."""

    provider_id: str
    runtime_id: str
    workspace_id: str
    agent_id: str


@dataclasses.dataclass(frozen=True)
class OwnedResourceAnnotations:
    """Safe non-secret annotations for one owned resource."""

    configuration_sequence: int | None
    configuration_digest: str | None
    policy_digest: str | None
    ca_fingerprint: str | None
    artifact_digest: str | None


@dataclasses.dataclass(frozen=True)
class SecretComparisonView:
    """Redacted Secret comparison containing key digests only."""

    metadata: ObjectMeta
    key_digests: Mapping[str, str]
    secret_type: str
    immutable: bool | None


@dataclasses.dataclass(frozen=True)
class ConfigMapComparisonView:
    """ConfigMap comparison containing key digests instead of raw policy text."""

    metadata: ObjectMeta
    key_digests: Mapping[str, str]
    immutable: bool | None


def resource_name(runtime_id: str, role: ResourceRole) -> str:
    """Return the deterministic Kubernetes name for one Runtime resource role."""
    safe_id = validate_runtime_id(runtime_id)
    base = f"azents-runtime-{safe_id}"
    suffix = {
        ResourceRole.RUNTIME_POD: "",
        ResourceRole.WORKSPACE_PVC: "-workspace",
        ResourceRole.RUNTIME_NETWORK_POLICY: "-execution",
        ResourceRole.RUNTIME_CA: "-ca",
        ResourceRole.PROXY_POLICY: "-proxy-policy",
        ResourceRole.PROXY_SERVICE: "-proxy",
        ResourceRole.PROXY_POD: "-proxy",
        ResourceRole.PROXY_INGRESS_NETWORK_POLICY: "-proxy-ingress",
        ResourceRole.PROXY_EGRESS_NETWORK_POLICY: "-proxy-egress",
    }[role]
    name = f"{base}{suffix}"
    if (
        len(name) > _MAX_KUBERNETES_NAME_LENGTH
        or _KUBERNETES_NAME_RE.fullmatch(name) is None
    ):
        raise InvalidRuntimeId(runtime_id)
    return name


def proxy_policy_resource_name(runtime_id: str, policy_digest: str) -> str:
    """Return one digest-revisioned proxy policy ConfigMap name."""
    if _DIGEST_RE.fullmatch(policy_digest) is None:
        raise InvalidOwnedResourceMetadata(
            "proxy policy resource name requires a SHA-256 digest"
        )
    base = resource_name(runtime_id, ResourceRole.PROXY_POLICY)
    suffix = f"-{policy_digest[:12]}"
    candidate = f"{base[: _MAX_KUBERNETES_NAME_LENGTH - len(suffix)]}{suffix}"
    candidate = candidate.rstrip("-.")
    if _KUBERNETES_NAME_RE.fullmatch(candidate) is None:
        raise InvalidRuntimeId(runtime_id)
    return candidate


def validate_runtime_id(runtime_id: str) -> str:
    """Validate the existing logical Runtime identifier contract."""
    if _RUNTIME_ID_RE.fullmatch(runtime_id) is None:
        raise InvalidRuntimeId(runtime_id)
    return runtime_id


def owned_labels(
    identity: OwnedResourceIdentity,
    role: ResourceRole,
    *,
    desired_generation: int | None,
) -> dict[str, str]:
    """Build exact ownership labels for one Provider-owned resource."""
    validate_runtime_id(identity.runtime_id)
    if not identity.provider_id or not identity.workspace_id or not identity.agent_id:
        raise InvalidOwnedResourceMetadata("owned resource identity is incomplete")
    labels = {
        LABEL_MANAGED_BY: MANAGED_BY_VALUE,
        LABEL_PROVIDER_ID: identity.provider_id,
        LABEL_RUNTIME_ID: identity.runtime_id,
        LABEL_WORKSPACE_ID: identity.workspace_id,
        LABEL_AGENT_ID: identity.agent_id,
        LABEL_RESOURCE_ROLE: role.value,
        LABEL_CONFIGURATION_MANAGED: "true",
    }
    if desired_generation is not None:
        if desired_generation < 1:
            raise InvalidOwnedResourceMetadata(
                "desired generation must be greater than zero"
            )
        labels[LABEL_DESIRED_GENERATION] = str(desired_generation)
    return labels


def owned_annotations(values: OwnedResourceAnnotations) -> dict[str, str]:
    """Build bounded non-secret annotations for one owned resource."""
    result: dict[str, str] = {}
    if values.configuration_sequence is not None:
        if values.configuration_sequence < 1:
            raise InvalidOwnedResourceMetadata(
                "configuration sequence must be greater than zero"
            )
        result[ANNOTATION_CONFIGURATION_SEQUENCE] = str(values.configuration_sequence)
    for key, value in (
        (ANNOTATION_CONFIGURATION_DIGEST, values.configuration_digest),
        (ANNOTATION_POLICY_DIGEST, values.policy_digest),
        (ANNOTATION_CA_FINGERPRINT, values.ca_fingerprint),
        (ANNOTATION_ARTIFACT_DIGEST, values.artifact_digest),
    ):
        if value is None:
            continue
        if _DIGEST_RE.fullmatch(value) is None:
            raise InvalidOwnedResourceMetadata(f"{key} must be a SHA-256 digest")
        result[key] = value
    return result


def validate_owned_metadata(
    metadata: ObjectMeta,
    identity: OwnedResourceIdentity,
    role: ResourceRole,
    *,
    desired_generation: int | None,
) -> None:
    """Reject name-only, foreign, or incomplete ownership matches."""
    if metadata.name != resource_name(identity.runtime_id, role):
        raise InvalidOwnedResourceMetadata("owned resource name mismatch")
    expected = owned_labels(
        identity,
        role,
        desired_generation=desired_generation,
    )
    for key, value in expected.items():
        if metadata.labels.get(key) != value:
            raise InvalidOwnedResourceMetadata(f"owned resource label mismatch: {key}")
    if desired_generation is None and LABEL_DESIRED_GENERATION in metadata.labels:
        raise InvalidOwnedResourceMetadata(
            f"owned resource label mismatch: {LABEL_DESIRED_GENERATION}"
        )


def validate_proxy_policy_metadata(
    metadata: ObjectMeta,
    identity: OwnedResourceIdentity,
    *,
    desired_generation: int,
    policy_digest: str,
) -> None:
    """Reject foreign or stale revisioned proxy policy metadata."""
    if metadata.name != proxy_policy_resource_name(
        identity.runtime_id,
        policy_digest,
    ):
        raise InvalidOwnedResourceMetadata("proxy policy resource name mismatch")
    expected = owned_labels(
        identity,
        ResourceRole.PROXY_POLICY,
        desired_generation=desired_generation,
    )
    for key, value in expected.items():
        if metadata.labels.get(key) != value:
            raise InvalidOwnedResourceMetadata(f"owned resource label mismatch: {key}")


def service_comparison_view(service: ServiceResource) -> ServiceResource:
    """Return the exact safe comparison view for one Service."""
    return service


def config_map_comparison_view(
    config_map: ConfigMapResource,
) -> ConfigMapComparisonView:
    """Return a digest-only ConfigMap comparison view."""
    return ConfigMapComparisonView(
        metadata=config_map.metadata,
        key_digests={
            key: hashlib.sha256(value.encode("utf-8")).hexdigest()
            for key, value in sorted(config_map.data.items())
        },
        immutable=config_map.immutable,
    )


def secret_comparison_view(secret: SecretResource) -> SecretComparisonView:
    """Return a digest-only Secret comparison view."""
    return SecretComparisonView(
        metadata=secret.metadata,
        key_digests={
            key: hashlib.sha256(value).hexdigest()
            for key, value in sorted(secret.data.items())
        },
        secret_type=secret.secret_type,
        immutable=secret.immutable,
    )
