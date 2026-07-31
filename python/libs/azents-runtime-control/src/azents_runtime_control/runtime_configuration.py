"""Runtime configuration command and evidence contracts."""

import dataclasses
import hashlib
import ipaddress
import json
import re
from collections.abc import Mapping
from typing import TypeAlias

JsonValue: TypeAlias = (
    None | bool | int | float | str | list["JsonValue"] | dict[str, "JsonValue"]
)

_DIGEST_RE = re.compile(r"^[0-9a-f]{64}$")


@dataclasses.dataclass(frozen=True)
class RuntimeConfigurationEvidence:
    """Non-secret evidence identifying one exact Runtime configuration revision."""

    revision_id: str
    digest: str
    desired_generation: int


@dataclasses.dataclass(frozen=True)
class RuntimeConfigurationEnvelope:
    """Canonical resolved Runtime configuration sent to a bound Provider."""

    evidence: RuntimeConfigurationEvidence
    resolved_configuration_json: str


@dataclasses.dataclass(frozen=True)
class RuntimeProviderReference:
    """Exact Provider and capability revision used by one configuration."""

    id: str
    logical_id: str
    kind: str
    capability_revision_id: str
    capability_digest: str


@dataclasses.dataclass(frozen=True)
class RuntimeInfrastructureProfileReference:
    """Exact infrastructure Profile source used by one configuration."""

    id: str
    version: int
    digest: str


@dataclasses.dataclass(frozen=True)
class WorkspaceRuntimeProfileReference:
    """Exact Workspace Runtime Profile source used by one configuration."""

    id: str
    version: int
    digest: str


@dataclasses.dataclass(frozen=True)
class RuntimeNetworkPolicy:
    """Typed Runtime network restriction after Workspace composition."""

    allowed_cidrs: tuple[str, ...]
    denied_cidrs: tuple[str, ...]


@dataclasses.dataclass(frozen=True)
class KubernetesContainerResources:
    """Explicit Kubernetes resources for one known Runtime component."""

    cpu_request_millicores: int | None
    cpu_limit_millicores: int | None
    memory_request_bytes: int | None
    memory_limit_bytes: int | None


@dataclasses.dataclass(frozen=True)
class KubernetesWorkspaceVolume:
    """Per-Runtime Kubernetes Workspace PVC inputs."""

    storage_class_name: str
    storage_request_bytes: int


@dataclasses.dataclass(frozen=True)
class KubernetesToleration:
    """Typed Kubernetes toleration supported by Pod Profile v1."""

    key: str
    operator: str
    value: str | None
    effect: str | None
    toleration_seconds: int | None


@dataclasses.dataclass(frozen=True)
class KubernetesScheduling:
    """Typed Kubernetes scheduling controls."""

    node_selector: Mapping[str, str]
    tolerations: tuple[KubernetesToleration, ...]


@dataclasses.dataclass(frozen=True)
class KubernetesDinD:
    """Privileged DinD topology selected by a Kubernetes Pod Profile."""

    engine_resources: KubernetesContainerResources
    docker_storage_bytes: int
    shared_temporary_storage_bytes: int


@dataclasses.dataclass(frozen=True)
class KubernetesPodProfileV1:
    """Resolved Kubernetes Pod Profile contract version 1."""

    runner_resources: KubernetesContainerResources
    workspace_volume: KubernetesWorkspaceVolume
    network_policy: RuntimeNetworkPolicy
    service_account_name: str | None
    scheduling: KubernetesScheduling
    dind: KubernetesDinD | None


@dataclasses.dataclass(frozen=True)
class DockerContainerResources:
    """Docker-native enforceable Runner resource choices."""

    cpu_reservation_millicores: int | None
    cpu_limit_millicores: int | None
    memory_reservation_bytes: int | None
    memory_limit_bytes: int | None


@dataclasses.dataclass(frozen=True)
class DockerContainerProfileV1:
    """Resolved Docker Container Profile contract version 1."""

    runner_resources: DockerContainerResources
    network_name: str | None


RuntimeResolvedProfile: TypeAlias = KubernetesPodProfileV1 | DockerContainerProfileV1


@dataclasses.dataclass(frozen=True)
class RuntimeResolvedConfiguration:
    """Parsed schema-version-1 Runtime configuration."""

    provider: RuntimeProviderReference
    infrastructure_profile: RuntimeInfrastructureProfileReference
    workspace_runtime_profile: WorkspaceRuntimeProfileReference
    effective_profile: RuntimeResolvedProfile


def canonical_runtime_configuration_json(
    configuration: Mapping[str, JsonValue],
) -> str:
    """Serialize one resolved configuration as deterministic JSON."""
    return json.dumps(
        configuration,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )


def runtime_configuration_from_json(value: str) -> dict[str, JsonValue]:
    """Parse one canonical resolved Runtime configuration JSON object."""
    try:
        parsed: JsonValue = json.loads(value)
    except (json.JSONDecodeError, TypeError) as error:
        raise ValueError("Runtime configuration JSON is invalid.") from error
    if not isinstance(parsed, dict):
        raise ValueError("Runtime configuration JSON must contain an object.")
    if canonical_runtime_configuration_json(parsed) != value:
        raise ValueError("Runtime configuration JSON is not canonical.")
    return parsed


def validate_runtime_configuration_evidence(
    evidence: RuntimeConfigurationEvidence,
) -> None:
    """Reject incomplete revision, digest, or generation evidence."""
    if (
        not evidence.revision_id.strip()
        or evidence.revision_id != evidence.revision_id.strip()
    ):
        raise ValueError("Runtime configuration revision ID is required.")
    if _DIGEST_RE.fullmatch(evidence.digest) is None:
        raise ValueError("Runtime configuration digest is invalid.")
    if isinstance(evidence.desired_generation, bool) or evidence.desired_generation < 0:
        raise ValueError("Runtime configuration desired generation is invalid.")


def parse_runtime_configuration_envelope(
    envelope: RuntimeConfigurationEnvelope,
    *,
    desired_generation: int,
    expected_provider_kind: str | None,
) -> RuntimeResolvedConfiguration:
    """Validate and parse one full Runtime configuration envelope."""
    validate_runtime_configuration_evidence(envelope.evidence)
    if envelope.evidence.desired_generation != desired_generation:
        raise ValueError(
            "Runtime configuration evidence generation does not match the command."
        )
    document = runtime_configuration_from_json(envelope.resolved_configuration_json)
    _require_exact_fields(
        document,
        {
            "schema_version",
            "provider",
            "infrastructure_profile",
            "workspace_runtime_profile",
            "effective_profile",
        },
        "Runtime configuration",
    )
    if _required_int(document, "schema_version") != 1:
        raise ValueError("Runtime configuration schema version is unsupported.")
    provider = _provider_reference(_required_mapping(document, "provider"))
    if expected_provider_kind is not None and provider.kind != expected_provider_kind:
        raise ValueError(
            "Runtime configuration Provider kind does not match this Provider."
        )
    infrastructure_profile = _infrastructure_reference(
        _required_mapping(document, "infrastructure_profile")
    )
    workspace_runtime_profile = _workspace_reference(
        _required_mapping(document, "workspace_runtime_profile")
    )
    effective_profile = _effective_profile(
        _required_mapping(document, "effective_profile")
    )
    if isinstance(effective_profile, KubernetesPodProfileV1):
        if provider.kind != "kubernetes":
            raise ValueError("Kubernetes Pod Profile requires a Kubernetes Provider.")
    else:
        if provider.kind != "docker":
            raise ValueError("Docker Container Profile requires a Docker Provider.")
    return RuntimeResolvedConfiguration(
        provider=provider,
        infrastructure_profile=infrastructure_profile,
        workspace_runtime_profile=workspace_runtime_profile,
        effective_profile=effective_profile,
    )


def configuration_document_digest(configuration: Mapping[str, JsonValue]) -> str:
    """Return a canonical SHA-256 digest for diagnostics and tests."""
    return hashlib.sha256(
        canonical_runtime_configuration_json(configuration).encode()
    ).hexdigest()


def _provider_reference(value: Mapping[str, JsonValue]) -> RuntimeProviderReference:
    _require_exact_fields(
        value,
        {
            "id",
            "logical_id",
            "kind",
            "capability_revision_id",
            "capability_digest",
        },
        "Runtime configuration Provider",
    )
    kind = _required_string(value, "kind")
    if kind not in {"kubernetes", "docker"}:
        raise ValueError("Runtime configuration Provider kind is unsupported.")
    capability_digest = _required_string(value, "capability_digest")
    if _DIGEST_RE.fullmatch(capability_digest) is None:
        raise ValueError("Runtime configuration capability digest is invalid.")
    return RuntimeProviderReference(
        id=_required_string(value, "id"),
        logical_id=_required_string(value, "logical_id"),
        kind=kind,
        capability_revision_id=_required_string(value, "capability_revision_id"),
        capability_digest=capability_digest,
    )


def _infrastructure_reference(
    value: Mapping[str, JsonValue],
) -> RuntimeInfrastructureProfileReference:
    _require_exact_fields(value, {"id", "version", "digest"}, "Infrastructure Profile")
    return RuntimeInfrastructureProfileReference(
        id=_required_string(value, "id"),
        version=_positive_int(value, "version"),
        digest=_sha256(value, "digest"),
    )


def _workspace_reference(
    value: Mapping[str, JsonValue],
) -> WorkspaceRuntimeProfileReference:
    _require_exact_fields(
        value, {"id", "version", "digest"}, "Workspace Runtime Profile"
    )
    return WorkspaceRuntimeProfileReference(
        id=_required_string(value, "id"),
        version=_positive_int(value, "version"),
        digest=_sha256(value, "digest"),
    )


def _effective_profile(value: Mapping[str, JsonValue]) -> RuntimeResolvedProfile:
    profile_kind = _required_string(value, "profile_kind")
    if profile_kind == "kubernetes_pod":
        return _kubernetes_profile(value)
    if profile_kind == "docker_container":
        return _docker_profile(value)
    raise ValueError("Runtime configuration Profile kind is unsupported.")


def _kubernetes_profile(value: Mapping[str, JsonValue]) -> KubernetesPodProfileV1:
    _require_exact_fields(
        value,
        {
            "profile_kind",
            "contract_family",
            "schema_version",
            "runner_resources",
            "workspace_volume",
            "network_policy",
            "service_account_name",
            "scheduling",
            "dind",
        },
        "Kubernetes Pod Profile",
    )
    if _required_string(value, "profile_kind") != "kubernetes_pod":
        raise ValueError("Kubernetes Pod Profile kind is invalid.")
    if _required_string(value, "contract_family") != "kubernetes.pod-profile":
        raise ValueError("Kubernetes Pod Profile contract family is unsupported.")
    if _required_int(value, "schema_version") != 1:
        raise ValueError("Kubernetes Pod Profile schema version is unsupported.")
    dind_value = value.get("dind")
    return KubernetesPodProfileV1(
        runner_resources=_kubernetes_resources(
            _required_mapping(value, "runner_resources")
        ),
        workspace_volume=_workspace_volume(
            _required_mapping(value, "workspace_volume")
        ),
        network_policy=_network_policy(_required_mapping(value, "network_policy")),
        service_account_name=_optional_string(value, "service_account_name"),
        scheduling=_scheduling(_required_mapping(value, "scheduling")),
        dind=None
        if dind_value is None
        else _dind(_mapping_value(dind_value, "Kubernetes DinD")),
    )


def _docker_profile(value: Mapping[str, JsonValue]) -> DockerContainerProfileV1:
    _require_exact_fields(
        value,
        {
            "profile_kind",
            "contract_family",
            "schema_version",
            "runner_resources",
            "network_name",
        },
        "Docker Container Profile",
    )
    if _required_string(value, "profile_kind") != "docker_container":
        raise ValueError("Docker Container Profile kind is invalid.")
    if _required_string(value, "contract_family") != "docker.container-profile":
        raise ValueError("Docker Container Profile contract family is unsupported.")
    if _required_int(value, "schema_version") != 1:
        raise ValueError("Docker Container Profile schema version is unsupported.")
    resources = _required_mapping(value, "runner_resources")
    _require_exact_fields(
        resources,
        {
            "cpu_reservation_millicores",
            "cpu_limit_millicores",
            "memory_reservation_bytes",
            "memory_limit_bytes",
        },
        "Docker resources",
    )
    parsed_resources = DockerContainerResources(
        cpu_reservation_millicores=_optional_positive_int(
            resources, "cpu_reservation_millicores"
        ),
        cpu_limit_millicores=_optional_positive_int(resources, "cpu_limit_millicores"),
        memory_reservation_bytes=_optional_positive_int(
            resources, "memory_reservation_bytes"
        ),
        memory_limit_bytes=_optional_positive_int(resources, "memory_limit_bytes"),
    )
    _validate_bounds(
        parsed_resources.cpu_reservation_millicores,
        parsed_resources.cpu_limit_millicores,
        "Docker CPU reservation cannot exceed its limit.",
    )
    _validate_bounds(
        parsed_resources.memory_reservation_bytes,
        parsed_resources.memory_limit_bytes,
        "Docker memory reservation cannot exceed its limit.",
    )
    return DockerContainerProfileV1(
        runner_resources=parsed_resources,
        network_name=_optional_string(value, "network_name"),
    )


def _kubernetes_resources(
    value: Mapping[str, JsonValue],
) -> KubernetesContainerResources:
    _require_exact_fields(
        value,
        {
            "cpu_request_millicores",
            "cpu_limit_millicores",
            "memory_request_bytes",
            "memory_limit_bytes",
        },
        "Kubernetes resources",
    )
    resources = KubernetesContainerResources(
        cpu_request_millicores=_optional_positive_int(value, "cpu_request_millicores"),
        cpu_limit_millicores=_optional_positive_int(value, "cpu_limit_millicores"),
        memory_request_bytes=_optional_positive_int(value, "memory_request_bytes"),
        memory_limit_bytes=_optional_positive_int(value, "memory_limit_bytes"),
    )
    _validate_bounds(
        resources.cpu_request_millicores,
        resources.cpu_limit_millicores,
        "Kubernetes CPU request cannot exceed its limit.",
    )
    _validate_bounds(
        resources.memory_request_bytes,
        resources.memory_limit_bytes,
        "Kubernetes memory request cannot exceed its limit.",
    )
    return resources


def _workspace_volume(value: Mapping[str, JsonValue]) -> KubernetesWorkspaceVolume:
    _require_exact_fields(
        value,
        {"storage_class_name", "storage_request_bytes"},
        "Kubernetes Workspace volume",
    )
    return KubernetesWorkspaceVolume(
        storage_class_name=_required_string(value, "storage_class_name"),
        storage_request_bytes=_positive_int(value, "storage_request_bytes"),
    )


def _network_policy(value: Mapping[str, JsonValue]) -> RuntimeNetworkPolicy:
    _require_exact_fields(value, {"allowed_cidrs", "denied_cidrs"}, "Network policy")
    return RuntimeNetworkPolicy(
        allowed_cidrs=_cidrs(value, "allowed_cidrs"),
        denied_cidrs=_cidrs(value, "denied_cidrs"),
    )


def _scheduling(value: Mapping[str, JsonValue]) -> KubernetesScheduling:
    _require_exact_fields(
        value, {"node_selector", "tolerations"}, "Kubernetes scheduling"
    )
    selector_value = _required_mapping(value, "node_selector")
    node_selector: dict[str, str] = {}
    for key, item in selector_value.items():
        if not isinstance(item, str) or not key or not item:
            raise ValueError("Kubernetes node selector is invalid.")
        node_selector[key] = item
    tolerations_value = value.get("tolerations")
    if not isinstance(tolerations_value, list):
        raise ValueError("Kubernetes tolerations must be an array.")
    return KubernetesScheduling(
        node_selector=node_selector,
        tolerations=tuple(
            _toleration(_mapping_value(item, "Kubernetes toleration"))
            for item in tolerations_value
        ),
    )


def _toleration(value: Mapping[str, JsonValue]) -> KubernetesToleration:
    _require_exact_fields(
        value,
        {"key", "operator", "value", "effect", "toleration_seconds"},
        "Kubernetes toleration",
    )
    operator = _required_string(value, "operator")
    if operator not in {"Equal", "Exists"}:
        raise ValueError("Kubernetes toleration operator is unsupported.")
    item_value = _optional_string(value, "value")
    if operator == "Equal" and item_value is None:
        raise ValueError("Equal toleration requires a value.")
    if operator == "Exists" and item_value is not None:
        raise ValueError("Exists toleration must not include a value.")
    effect = _optional_string(value, "effect")
    if effect not in {None, "NoSchedule", "PreferNoSchedule", "NoExecute"}:
        raise ValueError("Kubernetes toleration effect is unsupported.")
    seconds = _optional_non_negative_int(value, "toleration_seconds")
    return KubernetesToleration(
        key=_required_string(value, "key"),
        operator=operator,
        value=item_value,
        effect=effect,
        toleration_seconds=seconds,
    )


def _dind(value: Mapping[str, JsonValue]) -> KubernetesDinD:
    _require_exact_fields(
        value,
        {"engine_resources", "docker_storage_bytes", "shared_temporary_storage_bytes"},
        "Kubernetes DinD",
    )
    return KubernetesDinD(
        engine_resources=_kubernetes_resources(
            _required_mapping(value, "engine_resources")
        ),
        docker_storage_bytes=_positive_int(value, "docker_storage_bytes"),
        shared_temporary_storage_bytes=_positive_int(
            value, "shared_temporary_storage_bytes"
        ),
    )


def _cidrs(value: Mapping[str, JsonValue], field: str) -> tuple[str, ...]:
    raw = value.get(field)
    if not isinstance(raw, list) or any(not isinstance(item, str) for item in raw):
        raise ValueError(
            "Runtime configuration network CIDRs must be an array of strings."
        )
    cidrs = tuple(item for item in raw if isinstance(item, str))
    try:
        canonical = tuple(
            str(ipaddress.ip_network(item, strict=False)) for item in cidrs
        )
    except ValueError as error:
        raise ValueError("Runtime configuration network CIDR is invalid.") from error
    if cidrs != canonical or len(set(canonical)) != len(canonical):
        raise ValueError("Runtime configuration network CIDRs are not canonical.")
    return canonical


def _required_mapping(
    value: Mapping[str, JsonValue], field: str
) -> Mapping[str, JsonValue]:
    return _mapping_value(value.get(field), field)


def _mapping_value(value: JsonValue, label: str) -> Mapping[str, JsonValue]:
    if not isinstance(value, dict):
        raise ValueError(f"{label} must contain an object.")
    return value


def _required_string(value: Mapping[str, JsonValue], field: str) -> str:
    raw = value.get(field)
    if not isinstance(raw, str) or not raw.strip() or raw != raw.strip():
        raise ValueError(f"Runtime configuration {field} is invalid.")
    return raw


def _optional_string(value: Mapping[str, JsonValue], field: str) -> str | None:
    raw = value.get(field)
    if raw is None:
        return None
    if not isinstance(raw, str) or not raw.strip() or raw != raw.strip():
        raise ValueError(f"Runtime configuration {field} is invalid.")
    return raw


def _required_int(value: Mapping[str, JsonValue], field: str) -> int:
    raw = value.get(field)
    if isinstance(raw, bool) or not isinstance(raw, int):
        raise ValueError(f"Runtime configuration {field} is invalid.")
    return raw


def _positive_int(value: Mapping[str, JsonValue], field: str) -> int:
    parsed = _required_int(value, field)
    if parsed < 1:
        raise ValueError(f"Runtime configuration {field} must be positive.")
    return parsed


def _optional_positive_int(value: Mapping[str, JsonValue], field: str) -> int | None:
    raw = value.get(field)
    if raw is None:
        return None
    if isinstance(raw, bool) or not isinstance(raw, int) or raw < 1:
        raise ValueError(f"Runtime configuration {field} must be positive.")
    return raw


def _optional_non_negative_int(
    value: Mapping[str, JsonValue], field: str
) -> int | None:
    raw = value.get(field)
    if raw is None:
        return None
    if isinstance(raw, bool) or not isinstance(raw, int) or raw < 0:
        raise ValueError(f"Runtime configuration {field} must be non-negative.")
    return raw


def _sha256(value: Mapping[str, JsonValue], field: str) -> str:
    digest = _required_string(value, field)
    if _DIGEST_RE.fullmatch(digest) is None:
        raise ValueError(f"Runtime configuration {field} is invalid.")
    return digest


def _require_exact_fields(
    value: Mapping[str, JsonValue], expected: set[str], label: str
) -> None:
    if set(value) != expected:
        raise ValueError(f"{label} document shape is invalid.")


def _validate_bounds(lower: int | None, upper: int | None, message: str) -> None:
    if lower is not None and upper is not None and lower > upper:
        raise ValueError(message)
