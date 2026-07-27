"""Typed Runtime execution policy catalog and restrictive resolver."""

import enum
import hashlib
import json
from collections.abc import Mapping
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

SYSTEM_STANDARD_PROFILE_ID = "system-standard"

type JsonValue = (
    None | bool | int | float | str | list["JsonValue"] | dict[str, "JsonValue"]
)


class RuntimeExecutionPolicyLayer(enum.StrEnum):
    """Authority layer contributing one effective execution policy value."""

    PROFILE = "profile"
    WORKSPACE = "workspace"
    AGENT = "agent"


class RuntimeExecutionProfileLifecycle(enum.StrEnum):
    """Current lifecycle of one stable execution Profile."""

    ACTIVE = "active"
    RETIRED = "retired"


class RuntimeExecutionStorageMode(enum.StrEnum):
    """Docker data-storage lifecycle ordered from narrowest to broadest."""

    NONE = "none"
    EPHEMERAL = "ephemeral"
    PERSISTENT = "persistent"


class RuntimeExecutionChangeDirection(enum.StrEnum):
    """Security direction for one policy change."""

    METADATA_ONLY = "metadata_only"
    RESTRICTIVE = "restrictive"
    AUTHORITY_EXPANDING = "authority_expanding"
    MIXED = "mixed"
    INCOMPATIBLE = "incompatible"
    APPLICATION = "application"


class RuntimeExecutionPolicyStatus(enum.StrEnum):
    """Server-derived relationship between configured and applied policy."""

    CONFIGURED = "configured"
    PENDING = "pending"
    APPLIED = "applied"
    UNAVAILABLE = "unavailable"
    DIVERGENT = "divergent"


class RuntimeExecutionRequiredAction(enum.StrEnum):
    """Bounded next action for one Runtime execution-policy status."""

    NONE = "none"
    APPLY = "apply"
    WAIT = "wait"
    ADMINISTRATOR_ACTION = "administrator_action"


class RuntimeExecutionManagementLayer(enum.StrEnum):
    """Management authority that produced one metadata audit event."""

    PROFILE = "profile"
    WORKSPACE = "workspace"
    AGENT = "agent"
    RUNTIME = "runtime"


class RuntimeExecutionAuditEventType(enum.StrEnum):
    """Append-only execution-policy management event vocabulary."""

    PROFILE_CREATED = "profile_created"
    PROFILE_REPLACED = "profile_replaced"
    PROFILE_RETIRED = "profile_retired"
    WORKSPACE_POLICY_REPLACED = "workspace_policy_replaced"
    AGENT_SETTINGS_REPLACED = "agent_settings_replaced"
    TARGET_SNAPSHOT_ATTACHED = "target_snapshot_attached"
    APPLIED_SNAPSHOT_PROMOTED = "applied_snapshot_promoted"


class RuntimeExecutionAvailabilityReason(enum.StrEnum):
    """Bounded reason explaining why an execution policy is unavailable."""

    PROFILE_RETIRED = "profile_retired"
    PROFILE_NOT_ALLOWED = "profile_not_allowed"
    DEPENDENCY_UNSATISFIED = "dependency_unsatisfied"
    PROVIDER_MODULE_UNSUPPORTED = "provider_module_unsupported"
    PROVIDER_STORAGE_UNSUPPORTED = "provider_storage_unsupported"
    PROVIDER_LIMIT_EXCEEDED = "provider_limit_exceeded"


class RuntimeExecutionReductionReason(enum.StrEnum):
    """Bounded reason attached to a resolved value reduction."""

    UPPER_LAYER_RESTRICTION = "upper_layer_restriction"


class RuntimeExecutionModuleId(enum.StrEnum):
    """Application-owned execution capability module identifiers."""

    DOCKER = "docker"
    RESOURCES = "runtime.resources"


class _FrozenPolicyModel(BaseModel):
    """Strict immutable base for execution-policy documents."""

    model_config = ConfigDict(extra="forbid", frozen=True)


class RuntimeExecutionDockerModule(_FrozenPolicyModel):
    """Complete Docker capability and its private data-volume lifecycle."""

    module_id: Literal[RuntimeExecutionModuleId.DOCKER]
    version: Literal[1]
    enabled: bool
    storage_mode: RuntimeExecutionStorageMode
    storage_capacity_bytes: int | None = Field(ge=1)

    @model_validator(mode="after")
    def validate_storage(self) -> "RuntimeExecutionDockerModule":
        """Require bounded Docker storage exactly when Docker is enabled."""
        if not self.enabled:
            if self.storage_mode is not RuntimeExecutionStorageMode.NONE:
                raise ValueError("Disabled Docker must not allocate storage.")
            if self.storage_capacity_bytes is not None:
                raise ValueError("Disabled Docker must not declare storage capacity.")
        elif self.storage_mode is RuntimeExecutionStorageMode.NONE:
            raise ValueError("Enabled Docker requires a storage mode.")
        elif self.storage_capacity_bytes is None:
            raise ValueError("Enabled Docker requires a storage capacity.")
        return self


class RuntimeExecutionResourceModule(_FrozenPolicyModel):
    """Kubernetes resources for the Runtime workload and Workspace volume."""

    module_id: Literal[RuntimeExecutionModuleId.RESOURCES]
    version: Literal[1]
    cpu_request_millicores: int | None = Field(ge=1)
    cpu_limit_millicores: int | None = Field(ge=1)
    memory_request_bytes: int | None = Field(ge=1)
    memory_limit_bytes: int | None = Field(ge=1)
    ephemeral_storage_bytes: int | None = Field(ge=1)
    persistent_storage_bytes: int | None = Field(ge=1)

    @model_validator(mode="after")
    def validate_requests_do_not_exceed_limits(
        self,
    ) -> "RuntimeExecutionResourceModule":
        """Keep optional Kubernetes requests within their matching limits."""
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


class RuntimeExecutionPolicyDocument(_FrozenPolicyModel):
    """Complete versioned execution-policy document."""

    schema_version: Literal[1]
    docker: RuntimeExecutionDockerModule
    resources: RuntimeExecutionResourceModule


class RuntimeExecutionDockerRestriction(_FrozenPolicyModel):
    """Optional lower-layer Docker authority narrowing."""

    enabled: Literal[False] | None
    storage_mode: RuntimeExecutionStorageMode | None
    storage_capacity_bytes: int | None = Field(ge=1)

    @model_validator(mode="after")
    def validate_storage_narrowing(self) -> "RuntimeExecutionDockerRestriction":
        """Represent Docker disablement independently from storage narrowing."""
        if self.storage_mode is RuntimeExecutionStorageMode.NONE:
            raise ValueError(
                "Disable Docker with enabled=false, not storage_mode=none."
            )
        if self.enabled is False and (
            self.storage_mode is not None or self.storage_capacity_bytes is not None
        ):
            raise ValueError("Disabled Docker must not include storage restrictions.")
        return self


class RuntimeExecutionResourceRestriction(_FrozenPolicyModel):
    """Optional lower-layer resource ceilings."""

    cpu_request_millicores: int | None = Field(ge=1)
    cpu_limit_millicores: int | None = Field(ge=1)
    memory_request_bytes: int | None = Field(ge=1)
    memory_limit_bytes: int | None = Field(ge=1)
    ephemeral_storage_bytes: int | None = Field(ge=1)
    persistent_storage_bytes: int | None = Field(ge=1)


class RuntimeExecutionPolicyRestriction(_FrozenPolicyModel):
    """Restrictive-only Workspace or Agent policy contribution."""

    schema_version: Literal[1]
    docker: RuntimeExecutionDockerRestriction | None
    resources: RuntimeExecutionResourceRestriction | None


class RuntimeExecutionModuleSupport(_FrozenPolicyModel):
    """One exact application-owned module version implemented by a Provider."""

    module_id: RuntimeExecutionModuleId
    version: int = Field(ge=1)


class RuntimeExecutionProviderCapabilities(_FrozenPolicyModel):
    """Typed Provider compatibility projection consumed by the resolver."""

    supported_modules: frozenset[RuntimeExecutionModuleSupport]
    storage_modes: frozenset[RuntimeExecutionStorageMode]
    resource_maxima: RuntimeExecutionResourceModule | None


class RuntimeExecutionSourceVersions(_FrozenPolicyModel):
    """Current mutable source versions captured by one resolution."""

    profile: int = Field(ge=1)
    workspace: int = Field(ge=1)
    agent: int = Field(ge=1)


class RuntimeExecutionReduction(_FrozenPolicyModel):
    """One effective value reduced by a governing policy layer."""

    path: str = Field(min_length=1, max_length=255)
    previous: JsonValue
    current: JsonValue
    governing_layer: RuntimeExecutionPolicyLayer
    reason: RuntimeExecutionReductionReason


class RuntimeExecutionFieldChange(_FrozenPolicyModel):
    """Security direction for one canonical policy field change."""

    path: str = Field(min_length=1, max_length=255)
    direction: RuntimeExecutionChangeDirection


class RuntimeExecutionChangeSummary(_FrozenPolicyModel):
    """Aggregate and field-level security direction."""

    direction: RuntimeExecutionChangeDirection
    fields: tuple[RuntimeExecutionFieldChange, ...]


class RuntimeExecutionResolution(_FrozenPolicyModel):
    """Complete hierarchical resolution and explanation."""

    available: bool
    effective_policy: RuntimeExecutionPolicyDocument
    digest: str
    source_versions: RuntimeExecutionSourceVersions
    governing_layers: Mapping[str, RuntimeExecutionPolicyLayer]
    reductions: tuple[RuntimeExecutionReduction, ...]
    change: RuntimeExecutionChangeSummary
    availability_reason: RuntimeExecutionAvailabilityReason | None
    availability_detail: str | None


class RuntimeExecutionRestrictionExpansion(ValueError):
    """A restrictive-only document attempted to broaden its parent authority."""

    def __init__(
        self,
        *,
        path: str,
        governing_layer: RuntimeExecutionPolicyLayer,
    ) -> None:
        """Initialize a bounded expansion failure."""
        self.path = path
        self.governing_layer = governing_layer
        super().__init__(
            f"{path} exceeds the {governing_layer.value} execution-policy boundary."
        )


_STORAGE_RANK = {
    RuntimeExecutionStorageMode.NONE: 0,
    RuntimeExecutionStorageMode.EPHEMERAL: 1,
    RuntimeExecutionStorageMode.PERSISTENT: 2,
}
_RESOURCE_PATHS = (
    "cpu_request_millicores",
    "cpu_limit_millicores",
    "memory_request_bytes",
    "memory_limit_bytes",
    "ephemeral_storage_bytes",
    "persistent_storage_bytes",
)


def standard_runtime_execution_policy() -> RuntimeExecutionPolicyDocument:
    """Return the reserved Standard Profile without Docker authority."""
    return RuntimeExecutionPolicyDocument(
        schema_version=1,
        docker=RuntimeExecutionDockerModule(
            module_id=RuntimeExecutionModuleId.DOCKER,
            version=1,
            enabled=False,
            storage_mode=RuntimeExecutionStorageMode.NONE,
            storage_capacity_bytes=None,
        ),
        resources=RuntimeExecutionResourceModule(
            module_id=RuntimeExecutionModuleId.RESOURCES,
            version=1,
            cpu_request_millicores=None,
            cpu_limit_millicores=None,
            memory_request_bytes=None,
            memory_limit_bytes=None,
            ephemeral_storage_bytes=None,
            persistent_storage_bytes=None,
        ),
    )


def empty_runtime_execution_restriction() -> RuntimeExecutionPolicyRestriction:
    """Return a restriction document that preserves all parent values."""
    return RuntimeExecutionPolicyRestriction(
        schema_version=1,
        docker=None,
        resources=None,
    )


def canonical_runtime_execution_policy(
    policy: RuntimeExecutionPolicyDocument | RuntimeExecutionPolicyRestriction,
) -> dict[str, JsonValue]:
    """Return deterministic JSON for persistence and hashing."""
    value = policy.model_dump(mode="json")
    normalized = _canonical_json(value)
    if not isinstance(normalized, dict):
        raise AssertionError("Execution policy must serialize to an object.")
    return normalized


def canonical_runtime_execution_policy_json(
    policy: RuntimeExecutionPolicyDocument | RuntimeExecutionPolicyRestriction,
) -> str:
    """Return deterministic JSON text for persistence and transport."""
    return json.dumps(
        canonical_runtime_execution_policy(policy),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )


def digest_runtime_execution_policy(
    policy: RuntimeExecutionPolicyDocument | RuntimeExecutionPolicyRestriction,
) -> str:
    """Return the canonical SHA-256 execution-policy digest."""
    encoded = canonical_runtime_execution_policy_json(policy).encode()
    return hashlib.sha256(encoded).hexdigest()


def validate_runtime_execution_restriction(
    parent: RuntimeExecutionPolicyDocument,
    restriction: RuntimeExecutionPolicyRestriction,
    *,
    governing_layer: RuntimeExecutionPolicyLayer,
) -> None:
    """Reject a lower-layer document that explicitly exceeds its parent."""
    if restriction.resources is not None:
        for field_name in _RESOURCE_PATHS:
            parent_value = getattr(parent.resources, field_name)
            requested = getattr(restriction.resources, field_name)
            if (
                requested is not None
                and parent_value is not None
                and requested > parent_value
            ):
                raise RuntimeExecutionRestrictionExpansion(
                    path=f"resources.{field_name}",
                    governing_layer=governing_layer,
                )
    docker = restriction.docker
    if docker is not None:
        if (
            docker.storage_mode is not None
            and _STORAGE_RANK[docker.storage_mode]
            > _STORAGE_RANK[parent.docker.storage_mode]
        ):
            raise RuntimeExecutionRestrictionExpansion(
                path="docker.storage_mode",
                governing_layer=governing_layer,
            )
        if (
            docker.storage_capacity_bytes is not None
            and parent.docker.storage_capacity_bytes is not None
            and docker.storage_capacity_bytes > parent.docker.storage_capacity_bytes
        ):
            raise RuntimeExecutionRestrictionExpansion(
                path="docker.storage_capacity_bytes",
                governing_layer=governing_layer,
            )


def resolve_runtime_execution_policy(
    *,
    profile_policy: RuntimeExecutionPolicyDocument,
    workspace_restriction: RuntimeExecutionPolicyRestriction,
    agent_restriction: RuntimeExecutionPolicyRestriction,
    source_versions: RuntimeExecutionSourceVersions,
    provider_capabilities: RuntimeExecutionProviderCapabilities,
    profile_active: bool,
    profile_allowed: bool,
    applied_policy: RuntimeExecutionPolicyDocument | None,
) -> RuntimeExecutionResolution:
    """Resolve Profile, Workspace, and Agent authority fail closed."""
    policy = profile_policy
    governing = {
        path: RuntimeExecutionPolicyLayer.PROFILE
        for path in _flatten_policy(profile_policy)
    }
    reductions: list[RuntimeExecutionReduction] = []
    policy = _apply_restriction(
        policy,
        workspace_restriction,
        layer=RuntimeExecutionPolicyLayer.WORKSPACE,
        governing=governing,
        reductions=reductions,
    )
    policy = _apply_restriction(
        policy,
        agent_restriction,
        layer=RuntimeExecutionPolicyLayer.AGENT,
        governing=governing,
        reductions=reductions,
    )

    reason: RuntimeExecutionAvailabilityReason | None = None
    detail: str | None = None
    if not profile_active:
        reason = RuntimeExecutionAvailabilityReason.PROFILE_RETIRED
        detail = "The selected execution Profile is retired."
    elif not profile_allowed:
        reason = RuntimeExecutionAvailabilityReason.PROFILE_NOT_ALLOWED
        detail = "The selected execution Profile is not allowed in this Workspace."
    else:
        dependency_error = _dependency_error(policy)
        if dependency_error is not None:
            reason = RuntimeExecutionAvailabilityReason.DEPENDENCY_UNSATISFIED
            detail = dependency_error
        else:
            provider_error = _provider_compatibility_error(
                policy,
                provider_capabilities,
            )
            if provider_error is not None:
                reason, detail = provider_error

    change = (
        RuntimeExecutionChangeSummary(
            direction=RuntimeExecutionChangeDirection.INCOMPATIBLE,
            fields=(),
        )
        if reason is not None
        else classify_runtime_execution_change(applied_policy, policy)
    )
    return RuntimeExecutionResolution(
        available=reason is None,
        effective_policy=policy,
        digest=digest_runtime_execution_policy(policy),
        source_versions=source_versions,
        governing_layers=dict(sorted(governing.items())),
        reductions=tuple(reductions),
        change=change,
        availability_reason=reason,
        availability_detail=detail,
    )


def classify_runtime_execution_change(
    previous: RuntimeExecutionPolicyDocument | None,
    current: RuntimeExecutionPolicyDocument,
) -> RuntimeExecutionChangeSummary:
    """Classify field-level authority direction between canonical policies."""
    if previous is None:
        fields = tuple(
            RuntimeExecutionFieldChange(
                path=path,
                direction=RuntimeExecutionChangeDirection.AUTHORITY_EXPANDING,
            )
            for path, value in _flatten_policy(current).items()
            if _value_grants_authority(path, value)
        )
        direction = (
            RuntimeExecutionChangeDirection.METADATA_ONLY
            if not fields
            else RuntimeExecutionChangeDirection.AUTHORITY_EXPANDING
        )
        return RuntimeExecutionChangeSummary(direction=direction, fields=fields)

    before = _flatten_policy(previous)
    after = _flatten_policy(current)
    docker_direction: RuntimeExecutionChangeDirection | None = None
    if previous.docker.enabled != current.docker.enabled:
        docker_direction = (
            RuntimeExecutionChangeDirection.AUTHORITY_EXPANDING
            if current.docker.enabled
            else RuntimeExecutionChangeDirection.RESTRICTIVE
        )
    changes: list[RuntimeExecutionFieldChange] = []
    for path in sorted(before):
        if before[path] == after[path]:
            continue
        changes.append(
            RuntimeExecutionFieldChange(
                path=path,
                direction=(
                    docker_direction
                    if docker_direction is not None and path.startswith("docker.")
                    else _field_change_direction(path, before[path], after[path])
                ),
            )
        )
    directions = {change.direction for change in changes}
    if not changes:
        aggregate = RuntimeExecutionChangeDirection.METADATA_ONLY
    elif directions == {RuntimeExecutionChangeDirection.RESTRICTIVE}:
        aggregate = RuntimeExecutionChangeDirection.RESTRICTIVE
    elif directions == {RuntimeExecutionChangeDirection.AUTHORITY_EXPANDING}:
        aggregate = RuntimeExecutionChangeDirection.AUTHORITY_EXPANDING
    else:
        aggregate = RuntimeExecutionChangeDirection.MIXED
    return RuntimeExecutionChangeSummary(
        direction=aggregate,
        fields=tuple(changes),
    )


def meet_runtime_execution_policies(
    left: RuntimeExecutionPolicyDocument,
    right: RuntimeExecutionPolicyDocument,
) -> RuntimeExecutionPolicyDocument:
    """Return the greatest valid policy no broader than either input."""
    resource_values = {
        name: _minimum_bound(
            getattr(left.resources, name),
            getattr(right.resources, name),
        )
        for name in _RESOURCE_PATHS
    }
    for request_name, limit_name in (
        ("cpu_request_millicores", "cpu_limit_millicores"),
        ("memory_request_bytes", "memory_limit_bytes"),
    ):
        request = resource_values[request_name]
        limit = resource_values[limit_name]
        if request is not None and limit is not None and request > limit:
            resource_values[request_name] = limit

    docker_enabled = left.docker.enabled and right.docker.enabled
    storage_mode = min(
        left.docker.storage_mode,
        right.docker.storage_mode,
        key=_STORAGE_RANK.__getitem__,
    )
    storage_capacity = (
        None
        if not docker_enabled or storage_mode is RuntimeExecutionStorageMode.NONE
        else _minimum_bound(
            left.docker.storage_capacity_bytes,
            right.docker.storage_capacity_bytes,
        )
    )
    if not docker_enabled:
        storage_mode = RuntimeExecutionStorageMode.NONE

    return RuntimeExecutionPolicyDocument(
        schema_version=1,
        docker=RuntimeExecutionDockerModule(
            module_id=RuntimeExecutionModuleId.DOCKER,
            version=1,
            enabled=docker_enabled,
            storage_mode=storage_mode,
            storage_capacity_bytes=storage_capacity,
        ),
        resources=RuntimeExecutionResourceModule(
            module_id=RuntimeExecutionModuleId.RESOURCES,
            version=1,
            **resource_values,
        ),
    )


def _apply_restriction(
    policy: RuntimeExecutionPolicyDocument,
    restriction: RuntimeExecutionPolicyRestriction,
    *,
    layer: RuntimeExecutionPolicyLayer,
    governing: dict[str, RuntimeExecutionPolicyLayer],
    reductions: list[RuntimeExecutionReduction],
) -> RuntimeExecutionPolicyDocument:
    docker_enabled = policy.docker.enabled
    if restriction.docker is not None and restriction.docker.enabled is False:
        docker_enabled = False
    resources = policy.resources
    if restriction.resources is not None:
        resources = RuntimeExecutionResourceModule(
            module_id=RuntimeExecutionModuleId.RESOURCES,
            version=1,
            **{
                name: _minimum_bound(
                    getattr(policy.resources, name),
                    getattr(restriction.resources, name),
                )
                for name in _RESOURCE_PATHS
            },
        )
    storage_mode = policy.docker.storage_mode
    storage_capacity = policy.docker.storage_capacity_bytes
    if restriction.docker is not None:
        if restriction.docker.storage_mode is not None:
            storage_mode = min(
                storage_mode,
                restriction.docker.storage_mode,
                key=_STORAGE_RANK.__getitem__,
            )
        storage_capacity = _minimum_bound(
            storage_capacity,
            restriction.docker.storage_capacity_bytes,
        )
    if not docker_enabled or storage_mode is RuntimeExecutionStorageMode.NONE:
        storage_mode = RuntimeExecutionStorageMode.NONE
        storage_capacity = None

    result = RuntimeExecutionPolicyDocument(
        schema_version=1,
        docker=RuntimeExecutionDockerModule(
            module_id=RuntimeExecutionModuleId.DOCKER,
            version=1,
            enabled=docker_enabled,
            storage_mode=storage_mode,
            storage_capacity_bytes=storage_capacity,
        ),
        resources=resources,
    )
    _record_reductions(policy, result, layer, governing, reductions)
    return result


def _record_reductions(
    previous: RuntimeExecutionPolicyDocument,
    current: RuntimeExecutionPolicyDocument,
    layer: RuntimeExecutionPolicyLayer,
    governing: dict[str, RuntimeExecutionPolicyLayer],
    reductions: list[RuntimeExecutionReduction],
) -> None:
    before = _flatten_policy(previous)
    after = _flatten_policy(current)
    for path in sorted(before):
        if before[path] == after[path]:
            continue
        governing[path] = layer
        reductions.append(
            RuntimeExecutionReduction(
                path=path,
                previous=before[path],
                current=after[path],
                governing_layer=layer,
                reason=RuntimeExecutionReductionReason.UPPER_LAYER_RESTRICTION,
            )
        )


def _dependency_error(policy: RuntimeExecutionPolicyDocument) -> str | None:
    if policy.docker.enabled and policy.resources.ephemeral_storage_bytes is None:
        return "Docker requires a Kubernetes ephemeral-storage allocation."
    return None


def _provider_compatibility_error(
    policy: RuntimeExecutionPolicyDocument,
    provider: RuntimeExecutionProviderCapabilities,
) -> tuple[RuntimeExecutionAvailabilityReason, str] | None:
    required = _required_module_support(policy)
    missing = required - provider.supported_modules
    if missing:
        module = sorted(missing, key=lambda item: item.module_id.value)[0]
        return (
            RuntimeExecutionAvailabilityReason.PROVIDER_MODULE_UNSUPPORTED,
            "The bound Provider does not support "
            f"{module.module_id.value}/v{module.version}.",
        )
    if (
        policy.docker.storage_mode is not RuntimeExecutionStorageMode.NONE
        and policy.docker.storage_mode not in provider.storage_modes
    ):
        return (
            RuntimeExecutionAvailabilityReason.PROVIDER_STORAGE_UNSUPPORTED,
            "The bound Provider cannot enforce the selected Docker data storage mode.",
        )
    if provider.resource_maxima is not None:
        for field_name in _RESOURCE_PATHS:
            requested = getattr(policy.resources, field_name)
            maximum = getattr(provider.resource_maxima, field_name)
            if requested is not None and maximum is not None and requested > maximum:
                return (
                    RuntimeExecutionAvailabilityReason.PROVIDER_LIMIT_EXCEEDED,
                    f"The requested resources.{field_name} exceeds Provider support.",
                )
    return None


def _required_module_support(
    policy: RuntimeExecutionPolicyDocument,
) -> frozenset[RuntimeExecutionModuleSupport]:
    module_ids: set[RuntimeExecutionModuleId] = set()
    if policy.docker.enabled:
        module_ids.add(RuntimeExecutionModuleId.DOCKER)
    if any(getattr(policy.resources, name) is not None for name in _RESOURCE_PATHS):
        module_ids.add(RuntimeExecutionModuleId.RESOURCES)
    return frozenset(
        RuntimeExecutionModuleSupport(
            module_id=module_id,
            version=1,
        )
        for module_id in module_ids
    )


def _flatten_policy(policy: RuntimeExecutionPolicyDocument) -> dict[str, JsonValue]:
    return {
        "docker.enabled": policy.docker.enabled,
        "docker.storage_mode": policy.docker.storage_mode.value,
        "docker.storage_capacity_bytes": policy.docker.storage_capacity_bytes,
        **{
            f"resources.{name}": getattr(policy.resources, name)
            for name in _RESOURCE_PATHS
        },
    }


def _field_change_direction(
    path: str,
    before: JsonValue,
    after: JsonValue,
) -> RuntimeExecutionChangeDirection:
    if path.endswith(".enabled"):
        return (
            RuntimeExecutionChangeDirection.AUTHORITY_EXPANDING
            if after is True
            else RuntimeExecutionChangeDirection.RESTRICTIVE
        )
    if path.startswith("resources.") or path == "docker.storage_capacity_bytes":
        before_bound = _numeric_authority(before)
        after_bound = _numeric_authority(after)
        return (
            RuntimeExecutionChangeDirection.AUTHORITY_EXPANDING
            if after_bound > before_bound
            else RuntimeExecutionChangeDirection.RESTRICTIVE
        )
    if path == "docker.storage_mode":
        return (
            RuntimeExecutionChangeDirection.AUTHORITY_EXPANDING
            if _STORAGE_RANK[RuntimeExecutionStorageMode(str(after))]
            > _STORAGE_RANK[RuntimeExecutionStorageMode(str(before))]
            else RuntimeExecutionChangeDirection.RESTRICTIVE
        )
    raise AssertionError(f"Unsupported execution-policy path: {path}")


def _value_grants_authority(path: str, value: JsonValue) -> bool:
    if path.endswith(".enabled"):
        return value is True
    if path.startswith("resources."):
        return value is not None
    if path == "docker.storage_mode":
        return value != RuntimeExecutionStorageMode.NONE.value
    if path == "docker.storage_capacity_bytes":
        return value is not None
    return False


def _minimum_bound(left: int | None, right: int | None) -> int | None:
    if left is None:
        return right
    if right is None:
        return left
    return min(left, right)


def _numeric_authority(value: JsonValue) -> float:
    if value is None:
        return float("inf")
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise AssertionError("Expected a numeric execution-policy bound.")
    return float(value)


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
    raise TypeError(f"Unsupported execution-policy JSON value: {type(value).__name__}")
