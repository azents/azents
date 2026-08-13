"""Typed Runtime infrastructure and Workspace Profile contracts."""

import enum
import hashlib
import ipaddress
import json
import re
from collections.abc import Mapping
from typing import Annotated, Literal, assert_never

from pydantic import (
    BaseModel,
    ConfigDict,
    Discriminator,
    Field,
    Tag,
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


class RuntimeConfigurationStateStatus(enum.StrEnum):
    """Current desired Runtime configuration slot status."""

    UNCONFIGURED = "unconfigured"
    BLOCKED = "blocked"
    READY = "ready"


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


class RuntimeNetworkMode(enum.StrEnum):
    """Ordered Runtime network authority."""

    DIRECT = "direct"
    PROXY_REQUIRED = "proxy_required"
    NO_NETWORK = "no_network"


class RuntimeProxyDomainMode(enum.StrEnum):
    """Ordered proxy domain authority."""

    UNRESTRICTED = "unrestricted"
    ALLOWLIST = "allowlist"


class _FrozenProfileModel(BaseModel):
    """Strict immutable base for Profile documents."""

    model_config = ConfigDict(extra="forbid", frozen=True)


class RuntimeConfigurationDocument(_FrozenProfileModel):
    """Canonical schema-versioned current Runtime configuration envelope."""

    schema_version: Literal[1]
    source_trace: dict[str, JsonValue]
    provider_id: str
    provider_capability_revision_id: str | None
    infrastructure_profile_id: str
    infrastructure_profile_version: int = Field(ge=1)
    workspace_runtime_profile_id: str
    workspace_runtime_profile_version: int
    agent_selection_version: int = Field(ge=1)
    required_capabilities: tuple[str, ...]
    missing_capabilities: tuple[str, ...]
    resolved_configuration: dict[str, JsonValue] | None

    @model_validator(mode="after")
    def validate_resolution(self) -> "RuntimeConfigurationDocument":
        """Require a resolved document only when capability resolution is ready."""
        if self.missing_capabilities and self.resolved_configuration is not None:
            raise ValueError(
                "A document with missing capabilities cannot contain resolved "
                "configuration."
            )
        return self


class _DirectProfileSpecV2(_FrozenProfileModel):
    """Profile v2 compatibility for the removed containment field."""

    @model_validator(mode="before")
    @classmethod
    def normalize_removed_process_containment(cls, value: object) -> object:
        """Ignore only the historical null serialization of the removed field."""
        if (
            not isinstance(value, Mapping)
            or "process_containment" not in value
            or value.get("process_containment") is not None
        ):
            return value
        normalized = dict(value)
        normalized.pop("process_containment")
        return normalized


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


class RuntimeDirectNetworkAccess(_FrozenProfileModel):
    """Direct customer egress within one CIDR boundary."""

    mode: Literal[RuntimeNetworkMode.DIRECT]
    allowed_cidrs: tuple[str, ...]
    denied_cidrs: tuple[str, ...]

    @field_validator("allowed_cidrs", "denied_cidrs", mode="before")
    @classmethod
    def canonicalize_cidrs(cls, value: object) -> tuple[str, ...]:
        """Reuse the legacy direct CIDR contract."""
        return RuntimeNetworkPolicyModule.canonicalize_cidrs(value)

    @model_validator(mode="after")
    def validate_unique_cidrs(self) -> "RuntimeDirectNetworkAccess":
        """Reject duplicate CIDRs after canonicalization."""
        if len(set(self.allowed_cidrs)) != len(self.allowed_cidrs):
            raise ValueError("Allowed CIDRs must be unique.")
        if len(set(self.denied_cidrs)) != len(self.denied_cidrs):
            raise ValueError("Denied CIDRs must be unique.")
        return self


class _RuntimeProxyDomainPolicyBase(_FrozenProfileModel):
    """Canonical proxy destination domain policy."""

    allowed_domains: tuple[str, ...]
    denied_domains: tuple[str, ...]

    @field_validator("allowed_domains", "denied_domains", mode="before")
    @classmethod
    def canonicalize_domains(cls, value: object) -> tuple[str, ...]:
        """Canonicalize exact and leading-label wildcard domain patterns."""
        if not isinstance(value, list | tuple):
            raise ValueError("Domain patterns must be an array.")
        patterns: list[str] = []
        for item in value:
            if not isinstance(item, str):
                raise ValueError("Domain patterns must contain strings.")
            patterns.append(_canonical_domain_pattern(item))
        if len(set(patterns)) != len(patterns):
            raise ValueError("Domain patterns must be unique.")
        return tuple(sorted(patterns))


class RuntimeProxyDomainPolicyUnrestricted(_RuntimeProxyDomainPolicyBase):
    """Unrestricted hostname authority before final denials."""

    mode: Literal[RuntimeProxyDomainMode.UNRESTRICTED]

    @model_validator(mode="after")
    def validate_unrestricted_policy(
        self,
    ) -> "RuntimeProxyDomainPolicyUnrestricted":
        """Keep unrestricted authority explicit rather than list-derived."""
        if self.allowed_domains:
            raise ValueError(
                "Unrestricted domain policy cannot declare allowed domains."
            )
        return self


class RuntimeProxyDomainPolicyAllowlist(_RuntimeProxyDomainPolicyBase):
    """Explicit allowlist hostname authority with final denials."""

    mode: Literal[RuntimeProxyDomainMode.ALLOWLIST]


type RuntimeProxyDomainPolicy = Annotated[
    RuntimeProxyDomainPolicyUnrestricted | RuntimeProxyDomainPolicyAllowlist,
    Field(discriminator="mode"),
]


class RuntimeProxyRequiredNetworkAccess(_FrozenProfileModel):
    """Inspected HTTP proxy authority within CIDR and domain boundaries."""

    mode: Literal[RuntimeNetworkMode.PROXY_REQUIRED]
    allowed_cidrs: tuple[str, ...]
    denied_cidrs: tuple[str, ...]
    domain_policy: RuntimeProxyDomainPolicy

    @field_validator("allowed_cidrs", "denied_cidrs", mode="before")
    @classmethod
    def canonicalize_cidrs(cls, value: object) -> tuple[str, ...]:
        """Reuse the legacy direct CIDR contract."""
        return RuntimeNetworkPolicyModule.canonicalize_cidrs(value)

    @model_validator(mode="after")
    def validate_unique_cidrs(self) -> "RuntimeProxyRequiredNetworkAccess":
        """Reject duplicate CIDRs after canonicalization."""
        if len(set(self.allowed_cidrs)) != len(self.allowed_cidrs):
            raise ValueError("Allowed CIDRs must be unique.")
        if len(set(self.denied_cidrs)) != len(self.denied_cidrs):
            raise ValueError("Denied CIDRs must be unique.")
        return self


class RuntimeNoNetworkAccess(_FrozenProfileModel):
    """No customer or external network authority."""

    mode: Literal[RuntimeNetworkMode.NO_NETWORK]


type RuntimeNetworkAccess = Annotated[
    RuntimeDirectNetworkAccess
    | RuntimeProxyRequiredNetworkAccess
    | RuntimeNoNetworkAccess,
    Field(discriminator="mode"),
]


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


class KubernetesPodProfileSpecV2(_DirectProfileSpecV2):
    """Kubernetes Pod Profile contract version 2."""

    profile_kind: Literal[RuntimeInfrastructureProfileKind.KUBERNETES_POD]
    contract_family: Literal["kubernetes.pod-profile"]
    schema_version: Literal[2]
    runner_resources: KubernetesContainerResources
    workspace_volume: KubernetesWorkspaceVolume
    network_policy: RuntimeNetworkPolicyModule
    service_account_name: Annotated[str | None, Field(max_length=253)]
    scheduling: KubernetesSchedulingModule
    dind: KubernetesDinDModule | None


class KubernetesPodProfileSpecV3(_FrozenProfileModel):
    """Kubernetes Pod Profile contract version 3."""

    profile_kind: Literal[RuntimeInfrastructureProfileKind.KUBERNETES_POD]
    contract_family: Literal["kubernetes.pod-profile"]
    schema_version: Literal[3]
    runner_resources: KubernetesContainerResources
    workspace_volume: KubernetesWorkspaceVolume
    network_access: RuntimeNetworkAccess
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


class DockerContainerProfileSpecV2(_DirectProfileSpecV2):
    """Docker Container Profile contract version 2."""

    profile_kind: Literal[RuntimeInfrastructureProfileKind.DOCKER_CONTAINER]
    contract_family: Literal["docker.container-profile"]
    schema_version: Literal[2]
    runner_resources: DockerContainerResources
    network_name: Annotated[str | None, Field(max_length=255)]


def _runtime_profile_discriminator(value: object) -> str | None:
    """Return one exact Profile kind and schema-version discriminator."""
    match value:
        case KubernetesPodProfileSpecV1():
            return "kubernetes_pod:1"
        case KubernetesPodProfileSpecV2():
            return "kubernetes_pod:2"
        case KubernetesPodProfileSpecV3():
            return "kubernetes_pod:3"
        case DockerContainerProfileSpecV1():
            return "docker_container:1"
        case DockerContainerProfileSpecV2():
            return "docker_container:2"
        case dict():
            profile_kind = value.get("profile_kind")
            schema_version = value.get("schema_version")
        case _:
            return None
    if isinstance(profile_kind, enum.Enum):
        profile_kind = profile_kind.value
    if not isinstance(profile_kind, str) or not isinstance(schema_version, int):
        return None
    return f"{profile_kind}:{schema_version}"


type RuntimeInfrastructureProfileInternalSpec = Annotated[
    Annotated[
        KubernetesPodProfileSpecV1,
        Tag("kubernetes_pod:1"),
    ]
    | Annotated[
        KubernetesPodProfileSpecV2,
        Tag("kubernetes_pod:2"),
    ]
    | Annotated[
        KubernetesPodProfileSpecV3,
        Tag("kubernetes_pod:3"),
    ]
    | Annotated[
        DockerContainerProfileSpecV1,
        Tag("docker_container:1"),
    ]
    | Annotated[
        DockerContainerProfileSpecV2,
        Tag("docker_container:2"),
    ],
    Discriminator(_runtime_profile_discriminator),
]


type RuntimeInfrastructureProfileSpec = Annotated[
    Annotated[
        KubernetesPodProfileSpecV1,
        Tag("kubernetes_pod:1"),
    ]
    | Annotated[
        KubernetesPodProfileSpecV2,
        Tag("kubernetes_pod:2"),
    ]
    | Annotated[
        KubernetesPodProfileSpecV3,
        Tag("kubernetes_pod:3"),
    ]
    | Annotated[
        DockerContainerProfileSpecV1,
        Tag("docker_container:1"),
    ]
    | Annotated[
        DockerContainerProfileSpecV2,
        Tag("docker_container:2"),
    ],
    Discriminator(_runtime_profile_discriminator),
]


class WorkspaceRuntimeProfilePolicyV1(_FrozenProfileModel):
    """Workspace-owned restrictions attached to one Runtime Profile."""

    schema_version: Literal[1]
    network_restriction: RuntimeNetworkPolicyModule | None


class WorkspaceRuntimeNetworkRestrictionInherit(_FrozenProfileModel):
    """Preserve the infrastructure Profile network authority."""

    mode: Literal["inherit"]


class WorkspaceRuntimeNetworkRestrictionDirect(_FrozenProfileModel):
    """Retain direct mode while narrowing its CIDR authority."""

    mode: Literal[RuntimeNetworkMode.DIRECT]
    allowed_cidrs: tuple[str, ...]
    denied_cidrs: tuple[str, ...]

    @field_validator("allowed_cidrs", "denied_cidrs", mode="before")
    @classmethod
    def canonicalize_cidrs(cls, value: object) -> tuple[str, ...]:
        """Reuse the legacy direct CIDR contract."""
        return RuntimeNetworkPolicyModule.canonicalize_cidrs(value)

    @model_validator(mode="after")
    def validate_unique_cidrs(
        self,
    ) -> "WorkspaceRuntimeNetworkRestrictionDirect":
        """Reject duplicate CIDRs after canonicalization."""
        if len(set(self.allowed_cidrs)) != len(self.allowed_cidrs):
            raise ValueError("Allowed CIDRs must be unique.")
        if len(set(self.denied_cidrs)) != len(self.denied_cidrs):
            raise ValueError("Denied CIDRs must be unique.")
        return self


class WorkspaceRuntimeNetworkRestrictionProxyRequired(_FrozenProfileModel):
    """Select proxy-required mode and restrictive destination policy."""

    mode: Literal[RuntimeNetworkMode.PROXY_REQUIRED]
    allowed_cidrs: tuple[str, ...]
    denied_cidrs: tuple[str, ...]
    domain_policy: RuntimeProxyDomainPolicy

    @field_validator("allowed_cidrs", "denied_cidrs", mode="before")
    @classmethod
    def canonicalize_cidrs(cls, value: object) -> tuple[str, ...]:
        """Reuse the legacy direct CIDR contract."""
        return RuntimeNetworkPolicyModule.canonicalize_cidrs(value)

    @model_validator(mode="after")
    def validate_unique_cidrs(
        self,
    ) -> "WorkspaceRuntimeNetworkRestrictionProxyRequired":
        """Reject duplicate CIDRs after canonicalization."""
        if len(set(self.allowed_cidrs)) != len(self.allowed_cidrs):
            raise ValueError("Allowed CIDRs must be unique.")
        if len(set(self.denied_cidrs)) != len(self.denied_cidrs):
            raise ValueError("Denied CIDRs must be unique.")
        return self


class WorkspaceRuntimeNetworkRestrictionNoNetwork(_FrozenProfileModel):
    """Select no customer or external network authority."""

    mode: Literal[RuntimeNetworkMode.NO_NETWORK]


type WorkspaceRuntimeNetworkRestriction = Annotated[
    WorkspaceRuntimeNetworkRestrictionInherit
    | WorkspaceRuntimeNetworkRestrictionDirect
    | WorkspaceRuntimeNetworkRestrictionProxyRequired
    | WorkspaceRuntimeNetworkRestrictionNoNetwork,
    Field(discriminator="mode"),
]


class WorkspaceRuntimeProfilePolicyV2(_FrozenProfileModel):
    """Workspace-owned hierarchical network restriction."""

    schema_version: Literal[2]
    network_restriction: WorkspaceRuntimeNetworkRestriction


type WorkspaceRuntimeProfilePolicy = Annotated[
    WorkspaceRuntimeProfilePolicyV1 | WorkspaceRuntimeProfilePolicyV2,
    Field(discriminator="schema_version"),
]


class RuntimeNetworkProjection(_FrozenProfileModel):
    """Safe server-authored Runtime network authority projection."""

    mode: RuntimeNetworkMode
    allowed_cidrs: tuple[str, ...]
    denied_cidrs: tuple[str, ...]
    domain_mode: RuntimeProxyDomainMode | None
    allowed_domains: tuple[str, ...]
    denied_domains: tuple[str, ...]


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


_RUNTIME_INFRASTRUCTURE_PROFILE_ADAPTER = TypeAdapter(
    RuntimeInfrastructureProfileInternalSpec
)
_RUNTIME_INFRASTRUCTURE_PROFILE_API_ADAPTER = TypeAdapter(
    RuntimeInfrastructureProfileSpec
)
_WORKSPACE_RUNTIME_PROFILE_POLICY_ADAPTER = TypeAdapter(WorkspaceRuntimeProfilePolicy)


def parse_runtime_infrastructure_profile_spec(
    document: object,
) -> RuntimeInfrastructureProfileInternalSpec:
    """Parse one discriminated infrastructure Profile document."""
    return _RUNTIME_INFRASTRUCTURE_PROFILE_ADAPTER.validate_python(document)


def parse_runtime_infrastructure_profile_api_spec(
    document: object,
) -> RuntimeInfrastructureProfileSpec:
    """Parse one API-visible infrastructure Profile contract."""
    return _RUNTIME_INFRASTRUCTURE_PROFILE_API_ADAPTER.validate_python(document)


def parse_workspace_runtime_profile_policy(
    document: object,
) -> WorkspaceRuntimeProfilePolicy:
    """Parse one discriminated Workspace Runtime Profile policy."""
    return _WORKSPACE_RUNTIME_PROFILE_POLICY_ADAPTER.validate_python(document)


def compose_workspace_runtime_profile(
    spec: RuntimeInfrastructureProfileInternalSpec,
    workspace_policy: WorkspaceRuntimeProfilePolicy,
) -> dict[str, JsonValue]:
    """Compose restrictive Workspace policy into one effective Profile."""
    match workspace_policy:
        case WorkspaceRuntimeProfilePolicyV1():
            return _compose_workspace_runtime_profile_v1(spec, workspace_policy)
        case WorkspaceRuntimeProfilePolicyV2():
            return _compose_workspace_runtime_profile_v2(spec, workspace_policy)
        case _:
            assert_never(workspace_policy)


def project_runtime_network(
    spec: RuntimeInfrastructureProfileInternalSpec,
) -> RuntimeNetworkProjection:
    """Project one infrastructure or effective Profile into safe network authority."""
    match spec:
        case DockerContainerProfileSpecV1() | DockerContainerProfileSpecV2():
            return RuntimeNetworkProjection(
                mode=RuntimeNetworkMode.DIRECT,
                allowed_cidrs=(),
                denied_cidrs=(),
                domain_mode=None,
                allowed_domains=(),
                denied_domains=(),
            )
        case KubernetesPodProfileSpecV1() | KubernetesPodProfileSpecV2():
            return RuntimeNetworkProjection(
                mode=RuntimeNetworkMode.DIRECT,
                allowed_cidrs=spec.network_policy.allowed_cidrs,
                denied_cidrs=spec.network_policy.denied_cidrs,
                domain_mode=None,
                allowed_domains=(),
                denied_domains=(),
            )
        case KubernetesPodProfileSpecV3():
            match spec.network_access:
                case RuntimeDirectNetworkAccess():
                    return RuntimeNetworkProjection(
                        mode=RuntimeNetworkMode.DIRECT,
                        allowed_cidrs=spec.network_access.allowed_cidrs,
                        denied_cidrs=spec.network_access.denied_cidrs,
                        domain_mode=None,
                        allowed_domains=(),
                        denied_domains=(),
                    )
                case RuntimeProxyRequiredNetworkAccess():
                    return RuntimeNetworkProjection(
                        mode=RuntimeNetworkMode.PROXY_REQUIRED,
                        allowed_cidrs=spec.network_access.allowed_cidrs,
                        denied_cidrs=spec.network_access.denied_cidrs,
                        domain_mode=spec.network_access.domain_policy.mode,
                        allowed_domains=(
                            spec.network_access.domain_policy.allowed_domains
                        ),
                        denied_domains=(
                            spec.network_access.domain_policy.denied_domains
                        ),
                    )
                case RuntimeNoNetworkAccess():
                    return RuntimeNetworkProjection(
                        mode=RuntimeNetworkMode.NO_NETWORK,
                        allowed_cidrs=(),
                        denied_cidrs=(),
                        domain_mode=None,
                        allowed_domains=(),
                        denied_domains=(),
                    )
                case _:
                    assert_never(spec.network_access)
        case _:
            assert_never(spec)


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
    if _without_keys(
        desired_provider,
        {"capability_revision_id", "capability_digest"},
    ) != _without_keys(
        applied_provider,
        {"capability_revision_id", "capability_digest"},
    ):
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
    desired_profile_version = desired_profile.get("schema_version")
    applied_profile_version = applied_profile.get("schema_version")
    if desired_profile_version != applied_profile_version:
        return RuntimeConfigurationApplicationImpact.RECREATE
    if desired_profile_version in {1, 2}:
        if _without_keys(desired_profile, {"network_policy"}) != _without_keys(
            applied_profile,
            {"network_policy"},
        ):
            return RuntimeConfigurationApplicationImpact.RECREATE
        return RuntimeConfigurationApplicationImpact.IN_PLACE
    if desired_profile_version != 3:
        return RuntimeConfigurationApplicationImpact.RECREATE
    if _without_keys(desired_profile, {"network_access"}) != _without_keys(
        applied_profile,
        {"network_access"},
    ):
        return RuntimeConfigurationApplicationImpact.RECREATE
    desired_network = _configuration_section(desired_profile, "network_access")
    applied_network = _configuration_section(applied_profile, "network_access")
    network_mode = desired_network.get("mode")
    if network_mode != applied_network.get("mode"):
        return RuntimeConfigurationApplicationImpact.RECREATE
    if network_mode not in {
        RuntimeNetworkMode.DIRECT,
        RuntimeNetworkMode.PROXY_REQUIRED,
        RuntimeNetworkMode.NO_NETWORK,
    }:
        return RuntimeConfigurationApplicationImpact.RECREATE
    if not _network_enforcement_change_is_in_place(
        desired_configuration=desired_configuration,
        applied_configuration=applied_configuration,
        network_mode=network_mode,
    ):
        return RuntimeConfigurationApplicationImpact.RECREATE
    return RuntimeConfigurationApplicationImpact.IN_PLACE


def required_runtime_profile_capabilities(
    spec: RuntimeInfrastructureProfileInternalSpec,
) -> frozenset[str]:
    """Derive exact Provider capabilities required by a typed Profile spec."""
    match spec:
        case KubernetesPodProfileSpecV1() | KubernetesPodProfileSpecV2():
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
        case KubernetesPodProfileSpecV3():
            required = {
                "kubernetes.pod-profile",
                "runtime.resources",
                "workspace.persistent-volume",
            }
            match spec.network_access:
                case RuntimeDirectNetworkAccess():
                    required.add("runtime.network-policy")
                case RuntimeProxyRequiredNetworkAccess():
                    required.update(
                        {
                            "runtime.inspected-http-proxy",
                            "runtime.network-enforcement",
                        }
                    )
                case RuntimeNoNetworkAccess():
                    required.update(
                        {
                            "runtime.external-network-denial",
                            "runtime.network-enforcement",
                        }
                    )
                case _:
                    assert_never(spec.network_access)
            if spec.service_account_name is not None:
                required.add("kubernetes.service-account")
            if spec.scheduling.node_selector or spec.scheduling.tolerations:
                required.add("kubernetes.scheduling")
            if spec.dind is not None:
                required.update({"docker.dind", "docker.storage.ephemeral"})
            return frozenset(required)
        case DockerContainerProfileSpecV1() | DockerContainerProfileSpecV2():
            required = {
                "docker.container-profile",
                "runtime.resources",
                "workspace.host-directory",
            }
            return frozenset(required)
        case _:
            assert_never(spec)


def evaluate_runtime_profile_compatibility(
    spec: RuntimeInfrastructureProfileInternalSpec,
    supported_contracts: list[RuntimeProviderProfileContractSupport],
    *,
    provider_protocol_version: str | None,
) -> RuntimeProfileCompatibility:
    """Evaluate exact family, schema, and typed capability compatibility."""
    if (
        isinstance(spec, KubernetesPodProfileSpecV3)
        and provider_protocol_version != "agent-runtime-provider-kubernetes-v3"
    ):
        return RuntimeProfileCompatibility(
            compatible=False,
            reason_code="profile_protocol_version_unsupported",
            missing_capabilities=(),
            incompatible_constraints=(),
        )
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


_DOMAIN_LABEL_RE = re.compile(r"^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$")


def _canonical_domain_pattern(value: str) -> str:
    """Return one canonical exact-host or leading-label wildcard pattern."""
    raw = value.strip()
    wildcard = raw.startswith("*.")
    hostname = raw[2:] if wildcard else raw
    if hostname.endswith("."):
        hostname = hostname[:-1]
    if not hostname or hostname.endswith(".") or "*" in hostname:
        raise ValueError("Domain pattern must be an exact host or leading wildcard.")
    if any(character in hostname for character in "/:@?#[]"):
        raise ValueError("Domain pattern must not contain URL components.")
    try:
        canonical = hostname.lower().encode("idna").decode("ascii")
    except UnicodeError as error:
        raise ValueError("Domain pattern is not valid IDNA.") from error
    if len(canonical) > 253:
        raise ValueError("Domain pattern exceeds the hostname length limit.")
    labels = canonical.split(".")
    if any(not _DOMAIN_LABEL_RE.fullmatch(label) for label in labels):
        raise ValueError("Domain pattern contains an invalid hostname label.")
    try:
        ipaddress.ip_address(canonical)
    except ValueError:
        pass
    else:
        raise ValueError("Domain policy does not accept IP literals.")
    return f"*.{canonical}" if wildcard else canonical


def _compose_workspace_runtime_profile_v1(
    spec: RuntimeInfrastructureProfileInternalSpec,
    workspace_policy: WorkspaceRuntimeProfilePolicyV1,
) -> dict[str, JsonValue]:
    """Preserve the legacy direct-only composition contract."""
    restriction = workspace_policy.network_restriction
    match spec:
        case DockerContainerProfileSpecV1() | DockerContainerProfileSpecV2():
            if restriction is None:
                return canonicalize_runtime_profile_document(spec)
            raise ValueError("workspace_network_restriction_unsupported")
        case KubernetesPodProfileSpecV1() | KubernetesPodProfileSpecV2():
            if restriction is None:
                return canonicalize_runtime_profile_document(spec)
            effective_network = _compose_cidr_boundary(
                base_allowed_cidrs=spec.network_policy.allowed_cidrs,
                base_denied_cidrs=spec.network_policy.denied_cidrs,
                restricted_allowed_cidrs=restriction.allowed_cidrs,
                restricted_denied_cidrs=restriction.denied_cidrs,
            )
            effective = spec.model_copy(update={"network_policy": effective_network})
            return canonicalize_runtime_profile_document(effective)
        case KubernetesPodProfileSpecV3():
            match spec.network_access:
                case RuntimeDirectNetworkAccess():
                    if restriction is None:
                        return canonicalize_runtime_profile_document(spec)
                    effective_network = _compose_cidr_boundary(
                        base_allowed_cidrs=spec.network_access.allowed_cidrs,
                        base_denied_cidrs=spec.network_access.denied_cidrs,
                        restricted_allowed_cidrs=restriction.allowed_cidrs,
                        restricted_denied_cidrs=restriction.denied_cidrs,
                    )
                    effective = spec.model_copy(
                        update={
                            "network_access": RuntimeDirectNetworkAccess(
                                mode=RuntimeNetworkMode.DIRECT,
                                allowed_cidrs=effective_network.allowed_cidrs,
                                denied_cidrs=effective_network.denied_cidrs,
                            )
                        }
                    )
                    return canonicalize_runtime_profile_document(effective)
                case RuntimeProxyRequiredNetworkAccess() | RuntimeNoNetworkAccess():
                    raise ValueError("workspace_network_restriction_unsupported")
                case _:
                    assert_never(spec.network_access)
        case _:
            assert_never(spec)


def _compose_workspace_runtime_profile_v2(
    spec: RuntimeInfrastructureProfileInternalSpec,
    workspace_policy: WorkspaceRuntimeProfilePolicyV2,
) -> dict[str, JsonValue]:
    """Compose explicit hierarchical network authority into Profile v3."""
    match spec:
        case DockerContainerProfileSpecV1() | DockerContainerProfileSpecV2():
            raise ValueError("workspace_network_policy_unsupported")
        case (
            KubernetesPodProfileSpecV1()
            | KubernetesPodProfileSpecV2()
            | KubernetesPodProfileSpecV3()
        ):
            base = _kubernetes_profile_v3(spec)
        case _:
            assert_never(spec)

    restriction = workspace_policy.network_restriction
    match restriction:
        case WorkspaceRuntimeNetworkRestrictionInherit():
            effective_network = base.network_access
        case WorkspaceRuntimeNetworkRestrictionDirect():
            match base.network_access:
                case RuntimeDirectNetworkAccess():
                    effective_cidrs = _compose_cidr_boundary(
                        base_allowed_cidrs=base.network_access.allowed_cidrs,
                        base_denied_cidrs=base.network_access.denied_cidrs,
                        restricted_allowed_cidrs=restriction.allowed_cidrs,
                        restricted_denied_cidrs=restriction.denied_cidrs,
                    )
                    effective_network = RuntimeDirectNetworkAccess(
                        mode=RuntimeNetworkMode.DIRECT,
                        allowed_cidrs=effective_cidrs.allowed_cidrs,
                        denied_cidrs=effective_cidrs.denied_cidrs,
                    )
                case RuntimeProxyRequiredNetworkAccess() | RuntimeNoNetworkAccess():
                    raise ValueError("workspace_network_mode_expands")
                case _:
                    assert_never(base.network_access)
        case WorkspaceRuntimeNetworkRestrictionProxyRequired():
            match base.network_access:
                case RuntimeDirectNetworkAccess():
                    base_domain_policy: RuntimeProxyDomainPolicy = (
                        RuntimeProxyDomainPolicyUnrestricted(
                            mode=RuntimeProxyDomainMode.UNRESTRICTED,
                            allowed_domains=(),
                            denied_domains=(),
                        )
                    )
                case RuntimeProxyRequiredNetworkAccess():
                    base_domain_policy = base.network_access.domain_policy
                case RuntimeNoNetworkAccess():
                    raise ValueError("workspace_network_mode_expands")
                case _:
                    assert_never(base.network_access)
            effective_cidrs = _compose_cidr_boundary(
                base_allowed_cidrs=base.network_access.allowed_cidrs,
                base_denied_cidrs=base.network_access.denied_cidrs,
                restricted_allowed_cidrs=restriction.allowed_cidrs,
                restricted_denied_cidrs=restriction.denied_cidrs,
            )
            effective_network = RuntimeProxyRequiredNetworkAccess(
                mode=RuntimeNetworkMode.PROXY_REQUIRED,
                allowed_cidrs=effective_cidrs.allowed_cidrs,
                denied_cidrs=effective_cidrs.denied_cidrs,
                domain_policy=_compose_domain_policy(
                    base=base_domain_policy,
                    restriction=restriction.domain_policy,
                ),
            )
        case WorkspaceRuntimeNetworkRestrictionNoNetwork():
            effective_network = RuntimeNoNetworkAccess(
                mode=RuntimeNetworkMode.NO_NETWORK
            )
        case _:
            assert_never(restriction)
    effective = base.model_copy(update={"network_access": effective_network})
    return canonicalize_runtime_profile_document(effective)


def _kubernetes_profile_v3(
    spec: (
        KubernetesPodProfileSpecV1
        | KubernetesPodProfileSpecV2
        | KubernetesPodProfileSpecV3
    ),
) -> KubernetesPodProfileSpecV3:
    """Return the canonical v3 view of one Kubernetes Profile."""
    match spec:
        case KubernetesPodProfileSpecV3():
            return spec
        case KubernetesPodProfileSpecV1() | KubernetesPodProfileSpecV2():
            return KubernetesPodProfileSpecV3(
                profile_kind=RuntimeInfrastructureProfileKind.KUBERNETES_POD,
                contract_family="kubernetes.pod-profile",
                schema_version=3,
                runner_resources=spec.runner_resources,
                workspace_volume=spec.workspace_volume,
                network_access=RuntimeDirectNetworkAccess(
                    mode=RuntimeNetworkMode.DIRECT,
                    allowed_cidrs=spec.network_policy.allowed_cidrs,
                    denied_cidrs=spec.network_policy.denied_cidrs,
                ),
                service_account_name=spec.service_account_name,
                scheduling=spec.scheduling,
                dind=spec.dind,
            )
        case _:
            assert_never(spec)


def _compose_cidr_boundary(
    *,
    base_allowed_cidrs: tuple[str, ...],
    base_denied_cidrs: tuple[str, ...],
    restricted_allowed_cidrs: tuple[str, ...],
    restricted_denied_cidrs: tuple[str, ...],
) -> RuntimeNetworkPolicyModule:
    """Compose a restrictive child CIDR policy within its parent boundary."""
    if base_allowed_cidrs and restricted_allowed_cidrs:
        base_networks = tuple(
            ipaddress.ip_network(cidr, strict=False) for cidr in base_allowed_cidrs
        )
        for cidr in restricted_allowed_cidrs:
            restricted = ipaddress.ip_network(cidr, strict=False)
            if not any(
                _subnet_of_same_family(restricted, allowed) for allowed in base_networks
            ):
                raise ValueError("workspace_network_restriction_expands")
        allowed_cidrs = restricted_allowed_cidrs
    elif restricted_allowed_cidrs:
        allowed_cidrs = restricted_allowed_cidrs
    else:
        allowed_cidrs = base_allowed_cidrs
    return RuntimeNetworkPolicyModule(
        allowed_cidrs=allowed_cidrs,
        denied_cidrs=tuple(sorted({*base_denied_cidrs, *restricted_denied_cidrs})),
    )


def _compose_domain_policy(
    *,
    base: RuntimeProxyDomainPolicy,
    restriction: RuntimeProxyDomainPolicy,
) -> RuntimeProxyDomainPolicy:
    """Compose a restrictive child proxy domain policy."""
    match base:
        case RuntimeProxyDomainPolicyUnrestricted():
            pass
        case RuntimeProxyDomainPolicyAllowlist():
            if not isinstance(restriction, RuntimeProxyDomainPolicyAllowlist):
                raise ValueError("workspace_network_domain_expands")
            for pattern in restriction.allowed_domains:
                if not any(
                    _domain_pattern_within(pattern, parent)
                    for parent in base.allowed_domains
                ):
                    raise ValueError("workspace_network_domain_expands")
        case _:
            assert_never(base)
    denied_domains = tuple(sorted({*base.denied_domains, *restriction.denied_domains}))
    match restriction:
        case RuntimeProxyDomainPolicyUnrestricted():
            return RuntimeProxyDomainPolicyUnrestricted(
                mode=RuntimeProxyDomainMode.UNRESTRICTED,
                allowed_domains=(),
                denied_domains=denied_domains,
            )
        case RuntimeProxyDomainPolicyAllowlist():
            return RuntimeProxyDomainPolicyAllowlist(
                mode=RuntimeProxyDomainMode.ALLOWLIST,
                allowed_domains=restriction.allowed_domains,
                denied_domains=denied_domains,
            )
        case _:
            assert_never(restriction)


def _domain_pattern_within(candidate: str, parent: str) -> bool:
    """Return whether one canonical domain pattern is a structural subset."""
    candidate_wildcard = candidate.startswith("*.")
    parent_wildcard = parent.startswith("*.")
    candidate_host = candidate[2:] if candidate_wildcard else candidate
    parent_host = parent[2:] if parent_wildcard else parent
    if not parent_wildcard:
        return not candidate_wildcard and candidate_host == parent_host
    if candidate_wildcard:
        return candidate_host == parent_host or candidate_host.endswith(
            f".{parent_host}"
        )
    return candidate_host != parent_host and candidate_host.endswith(f".{parent_host}")


def _network_enforcement_change_is_in_place(
    *,
    desired_configuration: dict[str, JsonValue],
    applied_configuration: dict[str, JsonValue],
    network_mode: object,
) -> bool:
    """Classify server-known enforcement inputs outside the effective Profile."""
    desired = _configuration_section(desired_configuration, "network_enforcement")
    applied = _configuration_section(applied_configuration, "network_enforcement")
    if desired == applied:
        return True
    if not desired or not applied:
        return False
    if (
        desired.get("mode") != applied.get("mode")
        or desired.get("mode") != network_mode
    ):
        return False
    if network_mode == RuntimeNetworkMode.DIRECT:
        in_place_keys = {"policy_digest"}
    elif network_mode == RuntimeNetworkMode.PROXY_REQUIRED:
        in_place_keys = {"policy_digest", "proxy_artifact_revision"}
    else:
        return False
    return _without_keys(desired, in_place_keys) == _without_keys(
        applied,
        in_place_keys,
    )


def _subnet_of_same_family(
    candidate: ipaddress.IPv4Network | ipaddress.IPv6Network,
    container: ipaddress.IPv4Network | ipaddress.IPv6Network,
) -> bool:
    """Return whether two same-family networks have a subset relationship."""
    if isinstance(candidate, ipaddress.IPv4Network) and isinstance(
        container,
        ipaddress.IPv4Network,
    ):
        return candidate.subnet_of(container)
    if isinstance(candidate, ipaddress.IPv6Network) and isinstance(
        container,
        ipaddress.IPv6Network,
    ):
        return candidate.subnet_of(container)
    return False


def _profile_value_at_path(
    spec: RuntimeInfrastructureProfileInternalSpec,
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
