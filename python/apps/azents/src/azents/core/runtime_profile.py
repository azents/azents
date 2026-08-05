"""Typed Runtime infrastructure and Workspace Profile contracts."""

import enum
import hashlib
import ipaddress
import json
from typing import Annotated, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    TypeAdapter,
    field_validator,
    model_validator,
)

type JsonValue = (
    None | bool | int | float | str | list["JsonValue"] | dict[str, "JsonValue"]
)


class RuntimeInfrastructureProfileKind(enum.StrEnum):
    """Provider-specific infrastructure Profile kind."""

    KUBERNETES_POD = "kubernetes_pod"
    DOCKER_CONTAINER = "docker_container"


class RuntimeProfileLifecycle(enum.StrEnum):
    """Mutable Profile lifecycle."""

    ACTIVE = "active"
    DISABLED = "disabled"


class RuntimeConfigurationResolutionStatus(enum.StrEnum):
    """Whether current source configuration can create a Runtime incarnation."""

    READY = "ready"
    BLOCKED = "blocked"


class RuntimeConfigurationApplicationImpact(enum.StrEnum):
    """Physical action required to adopt one desired Runtime configuration."""

    BLOCKED = "blocked"
    CREATE = "create"
    IN_PLACE = "in_place"
    RECREATE = "recreate"


class RuntimeReconcileTaskStatus(enum.StrEnum):
    """Durable desired-configuration reconciliation state."""

    PENDING = "pending"
    RUNNING = "running"
    RETRY_WAIT = "retry_wait"
    COMPLETED = "completed"


class RuntimeReconcileSourceKind(enum.StrEnum):
    """Mutable source that can replace desired Runtime configuration."""

    PROVIDER_CAPABILITY = "provider_capability"
    PROVIDER = "provider"
    INFRASTRUCTURE_PROFILE = "infrastructure_profile"
    WORKSPACE_RUNTIME_PROFILE = "workspace_runtime_profile"
    AGENT_SELECTION = "agent_selection"


class RuntimeRecreationOperationStatus(enum.StrEnum):
    """Aggregate Runtime recreation operation state."""

    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    COMPLETED_WITH_FAILURES = "completed_with_failures"
    FAILED = "failed"


class RuntimeRecreationItemStatus(enum.StrEnum):
    """One Runtime item in a scoped recreation operation."""

    PENDING = "pending"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    SKIPPED = "skipped"
    FAILED = "failed"


class RuntimeRecreationTargetKind(enum.StrEnum):
    """Authority scope targeted by one recreation operation."""

    PROVIDER = "provider"
    INFRASTRUCTURE_PROFILE = "infrastructure_profile"
    WORKSPACE_RUNTIME_PROFILE = "workspace_runtime_profile"


class RuntimeProfileNumericConstraintPath(enum.StrEnum):
    """Azents-defined numeric Profile value constrained by a Provider."""

    RUNNER_CPU_REQUEST = "runner_resources.cpu_request_millicores"
    RUNNER_CPU_RESERVATION = "runner_resources.cpu_reservation_millicores"
    RUNNER_CPU_LIMIT = "runner_resources.cpu_limit_millicores"
    RUNNER_MEMORY_REQUEST = "runner_resources.memory_request_bytes"
    RUNNER_MEMORY_RESERVATION = "runner_resources.memory_reservation_bytes"
    RUNNER_MEMORY_LIMIT = "runner_resources.memory_limit_bytes"
    WORKSPACE_STORAGE = "workspace_volume.storage_request_bytes"
    DIND_ENGINE_CPU_REQUEST = "dind.engine_resources.cpu_request_millicores"
    DIND_ENGINE_CPU_LIMIT = "dind.engine_resources.cpu_limit_millicores"
    DIND_ENGINE_MEMORY_REQUEST = "dind.engine_resources.memory_request_bytes"
    DIND_ENGINE_MEMORY_LIMIT = "dind.engine_resources.memory_limit_bytes"
    DIND_DOCKER_STORAGE = "dind.docker_storage_bytes"
    DIND_SHARED_TEMPORARY_STORAGE = "dind.shared_temporary_storage_bytes"


class RuntimeProfileStringConstraintPath(enum.StrEnum):
    """Azents-defined string Profile value constrained by a Provider."""

    WORKSPACE_STORAGE_CLASS = "workspace_volume.storage_class_name"
    SERVICE_ACCOUNT = "service_account_name"
    DOCKER_NETWORK = "network_name"


class _FrozenProfileModel(BaseModel):
    """Strict immutable base for Profile documents."""

    model_config = ConfigDict(extra="forbid", frozen=True)


class KubernetesContainerResources(_FrozenProfileModel):
    """Explicit Kubernetes resources for one known Runtime component."""

    cpu_request_millicores: int | None = Field(ge=1)
    cpu_limit_millicores: int | None = Field(ge=1)
    memory_request_bytes: int | None = Field(ge=1)
    memory_limit_bytes: int | None = Field(ge=1)

    @model_validator(mode="after")
    def validate_requests(self) -> "KubernetesContainerResources":
        """Keep explicit requests within matching explicit limits."""
        if (
            self.cpu_request_millicores is not None
            and self.cpu_limit_millicores is not None
            and self.cpu_request_millicores > self.cpu_limit_millicores
        ):
            raise ValueError("CPU request cannot exceed CPU limit.")
        if (
            self.memory_request_bytes is not None
            and self.memory_limit_bytes is not None
            and self.memory_request_bytes > self.memory_limit_bytes
        ):
            raise ValueError("Memory request cannot exceed memory limit.")
        return self


class KubernetesWorkspaceVolume(_FrozenProfileModel):
    """Existing per-Runtime Workspace PVC inputs."""

    storage_class_name: Annotated[str, Field(min_length=1, max_length=253)]
    storage_request_bytes: int = Field(ge=1)


class RuntimeNetworkPolicyModule(_FrozenProfileModel):
    """Typed customer-traffic network boundary."""

    allowed_cidrs: tuple[str, ...] = ()
    denied_cidrs: tuple[str, ...] = ()

    @field_validator("allowed_cidrs", "denied_cidrs", mode="before")
    @classmethod
    def canonicalize_cidrs(cls, value: object) -> tuple[str, ...]:
        """Parse and canonicalize IPv4 and IPv6 network boundaries."""
        if not isinstance(value, list | tuple):
            raise ValueError("Network CIDRs must be an array.")
        cidrs: list[str] = []
        for item in value:
            if not isinstance(item, str):
                raise ValueError("Network CIDRs must contain strings.")
            cidrs.append(str(ipaddress.ip_network(item, strict=False)))
        return tuple(cidrs)

    @model_validator(mode="after")
    def validate_unique_cidrs(self) -> "RuntimeNetworkPolicyModule":
        """Reject duplicate CIDR entries before Provider-specific parsing."""
        if len(set(self.allowed_cidrs)) != len(self.allowed_cidrs):
            raise ValueError("Allowed CIDRs must be unique.")
        if len(set(self.denied_cidrs)) != len(self.denied_cidrs):
            raise ValueError("Denied CIDRs must be unique.")
        return self


class KubernetesToleration(_FrozenProfileModel):
    """Typed Kubernetes toleration supported by Pod Profile v1."""

    key: Annotated[str, Field(min_length=1, max_length=253)]
    operator: Literal["Equal", "Exists"]
    value: Annotated[str | None, Field(max_length=253)]
    effect: Literal["NoSchedule", "PreferNoSchedule", "NoExecute"] | None
    toleration_seconds: int | None = Field(ge=0)

    @model_validator(mode="after")
    def validate_value(self) -> "KubernetesToleration":
        """Match Kubernetes Equal and Exists value semantics."""
        if self.operator == "Equal" and self.value is None:
            raise ValueError("Equal toleration requires a value.")
        if self.operator == "Exists" and self.value is not None:
            raise ValueError("Exists toleration must not include a value.")
        return self


class KubernetesSchedulingModule(_FrozenProfileModel):
    """Typed initial Kubernetes scheduling controls."""

    node_selector: dict[str, str] = Field(default_factory=dict)
    tolerations: tuple[KubernetesToleration, ...] = ()


class KubernetesDinDModule(_FrozenProfileModel):
    """Privileged DinD topology owned by a Platform Pod Profile."""

    engine_resources: KubernetesContainerResources
    docker_storage_bytes: int = Field(ge=1)
    shared_temporary_storage_bytes: int = Field(ge=1)


class KubernetesPodProfileSpecV1(_FrozenProfileModel):
    """Kubernetes Pod Profile contract version 1."""

    profile_kind: Literal[RuntimeInfrastructureProfileKind.KUBERNETES_POD]
    contract_family: Literal["kubernetes.pod-profile"]
    schema_version: Literal[1]
    runner_resources: KubernetesContainerResources
    workspace_volume: KubernetesWorkspaceVolume
    network_policy: RuntimeNetworkPolicyModule
    service_account_name: Annotated[str | None, Field(max_length=253)]
    scheduling: KubernetesSchedulingModule
    dind: KubernetesDinDModule | None


class DockerContainerResources(_FrozenProfileModel):
    """Docker-native enforceable Runner resource choices."""

    cpu_reservation_millicores: int | None = Field(ge=1)
    cpu_limit_millicores: int | None = Field(ge=1)
    memory_reservation_bytes: int | None = Field(ge=1)
    memory_limit_bytes: int | None = Field(ge=1)

    @model_validator(mode="after")
    def validate_reservations(self) -> "DockerContainerResources":
        """Keep Docker reservations within matching limits."""
        if (
            self.cpu_reservation_millicores is not None
            and self.cpu_limit_millicores is not None
            and self.cpu_reservation_millicores > self.cpu_limit_millicores
        ):
            raise ValueError("CPU reservation cannot exceed CPU limit.")
        if (
            self.memory_reservation_bytes is not None
            and self.memory_limit_bytes is not None
            and self.memory_reservation_bytes > self.memory_limit_bytes
        ):
            raise ValueError("Memory reservation cannot exceed memory limit.")
        return self


class DockerContainerProfileSpecV1(_FrozenProfileModel):
    """Docker Container Profile contract version 1."""

    profile_kind: Literal[RuntimeInfrastructureProfileKind.DOCKER_CONTAINER]
    contract_family: Literal["docker.container-profile"]
    schema_version: Literal[1]
    runner_resources: DockerContainerResources
    network_name: Annotated[str | None, Field(max_length=255)]


type RuntimeInfrastructureProfileSpec = Annotated[
    KubernetesPodProfileSpecV1 | DockerContainerProfileSpecV1,
    Field(discriminator="profile_kind"),
]


class WorkspaceRuntimeProfilePolicyV1(_FrozenProfileModel):
    """Workspace-owned restrictions attached to one Runtime Profile."""

    schema_version: Literal[1]
    network_restriction: RuntimeNetworkPolicyModule | None


type RuntimeProfileAllowedValues = Annotated[
    frozenset[Annotated[str, Field(min_length=1, max_length=253)]],
    Field(min_length=1),
]


class RuntimeProviderProfileConstraints(_FrozenProfileModel):
    """Bounded Provider support for known typed Profile values."""

    maximums: dict[
        RuntimeProfileNumericConstraintPath,
        Annotated[int, Field(ge=1)],
    ] = Field(default_factory=dict)
    allowed_values: dict[
        RuntimeProfileStringConstraintPath,
        RuntimeProfileAllowedValues,
    ] = Field(default_factory=dict)


class RuntimeProviderProfileContractSupport(_FrozenProfileModel):
    """One Profile contract family supported by a Provider."""

    profile_kind: RuntimeInfrastructureProfileKind
    contract_family: Annotated[str, Field(min_length=1, max_length=120)]
    schema_versions: Annotated[frozenset[int], Field(min_length=1)]
    capabilities: frozenset[Annotated[str, Field(min_length=1, max_length=120)]]
    constraints: RuntimeProviderProfileConstraints = Field(
        default_factory=RuntimeProviderProfileConstraints
    )

    @model_validator(mode="after")
    def validate_versions(self) -> "RuntimeProviderProfileContractSupport":
        """Require positive versions and constraints for the declared Profile kind."""
        if any(version < 1 for version in self.schema_versions):
            raise ValueError("Profile contract schema versions must be positive.")
        allowed_numeric, allowed_string = _constraint_paths_for_kind(self.profile_kind)
        unsupported_numeric = set(self.constraints.maximums) - allowed_numeric
        unsupported_string = set(self.constraints.allowed_values) - allowed_string
        if unsupported_numeric or unsupported_string:
            raise ValueError(
                "Provider Profile constraints do not apply to the declared "
                "Profile kind."
            )
        return self


class RuntimeProfileCompatibility(_FrozenProfileModel):
    """Compatibility of one typed Profile against one Provider advertisement."""

    compatible: bool
    reason_code: str | None
    missing_capabilities: tuple[str, ...]
    incompatible_constraints: tuple[str, ...]


_RUNTIME_INFRASTRUCTURE_PROFILE_ADAPTER = TypeAdapter(RuntimeInfrastructureProfileSpec)


def parse_runtime_infrastructure_profile_spec(
    document: object,
) -> RuntimeInfrastructureProfileSpec:
    """Parse one discriminated infrastructure Profile document."""
    return _RUNTIME_INFRASTRUCTURE_PROFILE_ADAPTER.validate_python(document)


def compose_workspace_runtime_profile(
    spec: RuntimeInfrastructureProfileSpec,
    workspace_policy: WorkspaceRuntimeProfilePolicyV1,
) -> dict[str, JsonValue]:
    """Compose restrictive Workspace policy into one effective Profile."""
    restriction = workspace_policy.network_restriction
    if restriction is None:
        return canonicalize_runtime_profile_document(spec)
    if isinstance(spec, DockerContainerProfileSpecV1):
        raise ValueError("workspace_network_restriction_unsupported")

    base = spec.network_policy
    if base.allowed_cidrs and restriction.allowed_cidrs:
        base_networks = tuple(
            ipaddress.ip_network(cidr, strict=False) for cidr in base.allowed_cidrs
        )
        for cidr in restriction.allowed_cidrs:
            restricted = ipaddress.ip_network(cidr, strict=False)
            if isinstance(restricted, ipaddress.IPv4Network):
                within_boundary = any(
                    isinstance(allowed, ipaddress.IPv4Network)
                    and restricted.subnet_of(allowed)
                    for allowed in base_networks
                )
            else:
                within_boundary = any(
                    isinstance(allowed, ipaddress.IPv6Network)
                    and restricted.subnet_of(allowed)
                    for allowed in base_networks
                )
            if not within_boundary:
                raise ValueError("workspace_network_restriction_expands")
        allowed_cidrs = restriction.allowed_cidrs
    elif restriction.allowed_cidrs:
        allowed_cidrs = restriction.allowed_cidrs
    else:
        allowed_cidrs = base.allowed_cidrs

    effective_network = RuntimeNetworkPolicyModule(
        allowed_cidrs=allowed_cidrs,
        denied_cidrs=tuple(sorted({*base.denied_cidrs, *restriction.denied_cidrs})),
    )
    effective = spec.model_copy(update={"network_policy": effective_network})
    return canonicalize_runtime_profile_document(effective)


def classify_runtime_configuration_application(
    *,
    desired_status: RuntimeConfigurationResolutionStatus,
    desired_configuration: dict[str, JsonValue] | None,
    applied_configuration: dict[str, JsonValue] | None,
) -> RuntimeConfigurationApplicationImpact:
    """Classify exact desired-versus-applied physical Runtime adoption."""
    if (
        desired_status is RuntimeConfigurationResolutionStatus.BLOCKED
        or desired_configuration is None
    ):
        return RuntimeConfigurationApplicationImpact.BLOCKED
    if applied_configuration is None:
        return RuntimeConfigurationApplicationImpact.CREATE
    if desired_configuration == applied_configuration:
        return RuntimeConfigurationApplicationImpact.IN_PLACE

    desired_provider = _configuration_section(desired_configuration, "provider")
    applied_provider = _configuration_section(applied_configuration, "provider")
    if desired_provider != applied_provider:
        return RuntimeConfigurationApplicationImpact.RECREATE
    if desired_provider.get("kind") != "kubernetes":
        return RuntimeConfigurationApplicationImpact.RECREATE
    if desired_configuration.get("schema_version") != applied_configuration.get(
        "schema_version"
    ):
        return RuntimeConfigurationApplicationImpact.RECREATE

    for section_name in (
        "infrastructure_profile",
        "workspace_runtime_profile",
    ):
        desired_section = _configuration_section(
            desired_configuration,
            section_name,
        )
        applied_section = _configuration_section(
            applied_configuration,
            section_name,
        )
        if _without_keys(desired_section, {"version", "digest"}) != _without_keys(
            applied_section,
            {"version", "digest"},
        ):
            return RuntimeConfigurationApplicationImpact.RECREATE

    desired_profile = _configuration_section(
        desired_configuration,
        "effective_profile",
    )
    applied_profile = _configuration_section(
        applied_configuration,
        "effective_profile",
    )
    if (
        desired_profile.get("profile_kind")
        != RuntimeInfrastructureProfileKind.KUBERNETES_POD
        or applied_profile.get("profile_kind")
        != RuntimeInfrastructureProfileKind.KUBERNETES_POD
    ):
        return RuntimeConfigurationApplicationImpact.RECREATE
    if _without_keys(desired_profile, {"network_policy"}) != _without_keys(
        applied_profile,
        {"network_policy"},
    ):
        return RuntimeConfigurationApplicationImpact.RECREATE
    return RuntimeConfigurationApplicationImpact.IN_PLACE


def required_runtime_profile_capabilities(
    spec: RuntimeInfrastructureProfileSpec,
) -> frozenset[str]:
    """Derive exact Provider capabilities required by a typed Profile spec."""
    if isinstance(spec, KubernetesPodProfileSpecV1):
        required = {
            "kubernetes.pod-profile",
            "runtime.resources",
            "workspace.persistent-volume",
            "runtime.network-policy",
        }
        if spec.service_account_name is not None:
            required.add("kubernetes.service-account")
        if spec.scheduling.node_selector or spec.scheduling.tolerations:
            required.add("kubernetes.scheduling")
        if spec.dind is not None:
            required.update({"docker.dind", "docker.storage.ephemeral"})
        return frozenset(required)
    return frozenset(
        {
            "docker.container-profile",
            "runtime.resources",
            "workspace.host-directory",
        }
    )


def evaluate_runtime_profile_compatibility(
    spec: RuntimeInfrastructureProfileSpec,
    supported_contracts: list[RuntimeProviderProfileContractSupport],
) -> RuntimeProfileCompatibility:
    """Evaluate exact family, schema, and typed capability compatibility."""
    support = next(
        (
            candidate
            for candidate in supported_contracts
            if candidate.profile_kind == spec.profile_kind
            and candidate.contract_family == spec.contract_family
        ),
        None,
    )
    if support is None:
        return RuntimeProfileCompatibility(
            compatible=False,
            reason_code="profile_contract_unsupported",
            missing_capabilities=(),
            incompatible_constraints=(),
        )
    if spec.schema_version not in support.schema_versions:
        return RuntimeProfileCompatibility(
            compatible=False,
            reason_code="profile_schema_version_unsupported",
            missing_capabilities=(),
            incompatible_constraints=(),
        )
    missing = tuple(
        sorted(required_runtime_profile_capabilities(spec) - support.capabilities)
    )
    if missing:
        return RuntimeProfileCompatibility(
            compatible=False,
            reason_code="profile_capability_missing",
            missing_capabilities=missing,
            incompatible_constraints=(),
        )
    exceeded = tuple(
        sorted(
            path.value
            for path, maximum in support.constraints.maximums.items()
            if (value := _profile_value_at_path(spec, path.value)) is not None
            and isinstance(value, int)
            and value > maximum
        )
    )
    unsupported_values = tuple(
        sorted(
            path.value
            for path, allowed in support.constraints.allowed_values.items()
            if (value := _profile_value_at_path(spec, path.value)) is not None
            and isinstance(value, str)
            and value not in allowed
        )
    )
    if exceeded or unsupported_values:
        if exceeded and unsupported_values:
            reason_code = "profile_constraint_unsupported"
        elif exceeded:
            reason_code = "profile_constraint_exceeded"
        else:
            reason_code = "profile_value_unsupported"
        return RuntimeProfileCompatibility(
            compatible=False,
            reason_code=reason_code,
            missing_capabilities=(),
            incompatible_constraints=tuple(sorted((*exceeded, *unsupported_values))),
        )
    return RuntimeProfileCompatibility(
        compatible=True,
        reason_code=None,
        missing_capabilities=(),
        incompatible_constraints=(),
    )


def _constraint_paths_for_kind(
    profile_kind: RuntimeInfrastructureProfileKind,
) -> tuple[
    frozenset[RuntimeProfileNumericConstraintPath],
    frozenset[RuntimeProfileStringConstraintPath],
]:
    if profile_kind is RuntimeInfrastructureProfileKind.KUBERNETES_POD:
        return (
            frozenset(
                {
                    RuntimeProfileNumericConstraintPath.RUNNER_CPU_REQUEST,
                    RuntimeProfileNumericConstraintPath.RUNNER_CPU_LIMIT,
                    RuntimeProfileNumericConstraintPath.RUNNER_MEMORY_REQUEST,
                    RuntimeProfileNumericConstraintPath.RUNNER_MEMORY_LIMIT,
                    RuntimeProfileNumericConstraintPath.WORKSPACE_STORAGE,
                    RuntimeProfileNumericConstraintPath.DIND_ENGINE_CPU_REQUEST,
                    RuntimeProfileNumericConstraintPath.DIND_ENGINE_CPU_LIMIT,
                    RuntimeProfileNumericConstraintPath.DIND_ENGINE_MEMORY_REQUEST,
                    RuntimeProfileNumericConstraintPath.DIND_ENGINE_MEMORY_LIMIT,
                    RuntimeProfileNumericConstraintPath.DIND_DOCKER_STORAGE,
                    RuntimeProfileNumericConstraintPath.DIND_SHARED_TEMPORARY_STORAGE,
                }
            ),
            frozenset(
                {
                    RuntimeProfileStringConstraintPath.WORKSPACE_STORAGE_CLASS,
                    RuntimeProfileStringConstraintPath.SERVICE_ACCOUNT,
                }
            ),
        )
    return (
        frozenset(
            {
                RuntimeProfileNumericConstraintPath.RUNNER_CPU_RESERVATION,
                RuntimeProfileNumericConstraintPath.RUNNER_CPU_LIMIT,
                RuntimeProfileNumericConstraintPath.RUNNER_MEMORY_RESERVATION,
                RuntimeProfileNumericConstraintPath.RUNNER_MEMORY_LIMIT,
            }
        ),
        frozenset({RuntimeProfileStringConstraintPath.DOCKER_NETWORK}),
    )


def _profile_value_at_path(
    spec: RuntimeInfrastructureProfileSpec,
    path: str,
) -> object:
    value: object = spec
    for segment in path.split("."):
        if value is None:
            return None
        if not isinstance(value, BaseModel):
            raise AssertionError("Profile constraint path traversed a non-model value.")
        value = getattr(value, segment)
    return value


def _configuration_section(
    configuration: dict[str, JsonValue],
    key: str,
) -> dict[str, JsonValue]:
    value = configuration.get(key)
    if not isinstance(value, dict):
        return {}
    return value


def _without_keys(
    value: dict[str, JsonValue],
    keys: set[str],
) -> dict[str, JsonValue]:
    return {key: item for key, item in value.items() if key not in keys}


def canonicalize_runtime_profile_document(
    document: BaseModel,
) -> dict[str, JsonValue]:
    """Return deterministic semantic JSON for one typed Profile document."""
    value = document.model_dump(mode="json")
    normalized = _canonical_json(value)
    if not isinstance(normalized, dict):
        raise AssertionError("Runtime Profile document must serialize to an object.")
    return normalized


def digest_runtime_profile_document(document: BaseModel) -> str:
    """Return the canonical SHA-256 digest of one Profile document."""
    encoded = json.dumps(
        canonicalize_runtime_profile_document(document),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode()
    return hashlib.sha256(encoded).hexdigest()


def _canonical_json(value: object) -> JsonValue:
    if value is None or isinstance(value, bool | int | float | str):
        return value
    if isinstance(value, dict):
        return {
            str(key): _canonical_json(item)
            for key, item in sorted(value.items(), key=lambda pair: str(pair[0]))
        }
    if isinstance(value, list | tuple | set | frozenset):
        items = [_canonical_json(item) for item in value]
        return sorted(
            items,
            key=lambda item: json.dumps(
                item,
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=False,
            ),
        )
    raise TypeError(f"Unsupported Runtime Profile JSON value: {type(value).__name__}")
