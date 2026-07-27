"""Typed Runtime execution policy catalog and restrictive resolver."""

import enum
import hashlib
import json
from collections.abc import Mapping
from typing import Annotated, Literal

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
    """Nested-engine storage lifecycle ordered from narrowest to broadest."""

    NONE = "none"
    EPHEMERAL = "ephemeral"
    PERSISTENT = "persistent"


class RuntimeExecutionNetworkMode(enum.StrEnum):
    """Optional egress authority ordered from narrowest to broadest."""

    NONE = "none"
    RESTRICTED = "restricted"
    DIRECT = "direct"


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
    PROVIDER_ENGINE_UNSUPPORTED = "provider_engine_unsupported"
    PROVIDER_STORAGE_UNSUPPORTED = "provider_storage_unsupported"
    PROVIDER_NETWORK_UNSUPPORTED = "provider_network_unsupported"
    PROVIDER_LIMIT_EXCEEDED = "provider_limit_exceeded"


class RuntimeExecutionReductionReason(enum.StrEnum):
    """Bounded reason attached to a resolved value reduction."""

    UPPER_LAYER_RESTRICTION = "upper_layer_restriction"


class RuntimeExecutionModuleId(enum.StrEnum):
    """Application-owned execution capability module identifiers."""

    IMAGE_BUILD = "container.image_build"
    CONTAINER_RUN = "container.run"
    COMPOSE = "container.compose"
    RESOURCES = "container.resources"
    ENGINE_STORAGE = "engine.storage"
    NETWORK_EGRESS = "network.egress"


class _FrozenPolicyModel(BaseModel):
    """Strict immutable base for execution-policy documents."""

    model_config = ConfigDict(extra="forbid", frozen=True)


class RuntimeExecutionBooleanModule(_FrozenPolicyModel):
    """One versioned boolean execution capability module."""

    module_id: Literal[
        RuntimeExecutionModuleId.IMAGE_BUILD,
        RuntimeExecutionModuleId.CONTAINER_RUN,
        RuntimeExecutionModuleId.COMPOSE,
    ]
    version: Literal[1]
    enabled: bool


class RuntimeExecutionResourceModule(_FrozenPolicyModel):
    """Aggregate Runtime and nested-workload resource ceilings."""

    module_id: Literal[RuntimeExecutionModuleId.RESOURCES]
    version: Literal[1]
    cpu_millicores: int | None = Field(ge=1)
    memory_bytes: int | None = Field(ge=1)
    pids: int | None = Field(ge=1)
    container_count: int | None = Field(ge=1)
    ephemeral_storage_bytes: int | None = Field(ge=1)


class RuntimeExecutionStorageModule(_FrozenPolicyModel):
    """Nested-engine storage mode and capacity ceiling."""

    module_id: Literal[RuntimeExecutionModuleId.ENGINE_STORAGE]
    version: Literal[1]
    mode: RuntimeExecutionStorageMode
    capacity_bytes: int | None = Field(ge=1)

    @model_validator(mode="after")
    def validate_capacity(self) -> "RuntimeExecutionStorageModule":
        """Require capacity exactly when engine storage exists."""
        if self.mode is RuntimeExecutionStorageMode.NONE:
            if self.capacity_bytes is not None:
                raise ValueError("Engine storage capacity requires a storage mode.")
        elif self.capacity_bytes is None:
            raise ValueError("Engine storage mode requires a capacity ceiling.")
        return self


class RuntimeExecutionNetworkModule(_FrozenPolicyModel):
    """Nested-workload optional egress authority."""

    module_id: Literal[RuntimeExecutionModuleId.NETWORK_EGRESS]
    version: Literal[1]
    mode: RuntimeExecutionNetworkMode
    allowed_destinations: frozenset[Annotated[str, Field(min_length=1, max_length=255)]]
    denied_destinations: frozenset[Annotated[str, Field(min_length=1, max_length=255)]]

    @model_validator(mode="after")
    def validate_destinations(self) -> "RuntimeExecutionNetworkModule":
        """Reject overlapping allow and deny rules and rules in no-egress mode."""
        overlap = self.allowed_destinations & self.denied_destinations
        if overlap:
            raise ValueError("Network destinations cannot be both allowed and denied.")
        if self.mode is RuntimeExecutionNetworkMode.NONE and self.allowed_destinations:
            raise ValueError("No-egress mode cannot declare allowed destinations.")
        return self


class RuntimeExecutionPolicyDocument(_FrozenPolicyModel):
    """Complete versioned execution-policy document."""

    schema_version: Literal[1]
    image_build: RuntimeExecutionBooleanModule
    container_run: RuntimeExecutionBooleanModule
    compose: RuntimeExecutionBooleanModule
    resources: RuntimeExecutionResourceModule
    engine_storage: RuntimeExecutionStorageModule
    network_egress: RuntimeExecutionNetworkModule

    @model_validator(mode="after")
    def validate_module_identities(self) -> "RuntimeExecutionPolicyDocument":
        """Reject a typed module placed in the wrong catalog slot."""
        expected = (
            (self.image_build.module_id, RuntimeExecutionModuleId.IMAGE_BUILD),
            (self.container_run.module_id, RuntimeExecutionModuleId.CONTAINER_RUN),
            (self.compose.module_id, RuntimeExecutionModuleId.COMPOSE),
        )
        for actual, required in expected:
            if actual is not required:
                raise ValueError(f"{required.value}/v1 is in the wrong module slot.")
        return self


class RuntimeExecutionBooleanRestriction(_FrozenPolicyModel):
    """Boolean authority can only be explicitly disabled."""

    enabled: Literal[False]


class RuntimeExecutionResourceRestriction(_FrozenPolicyModel):
    """Optional lower-layer resource ceilings."""

    cpu_millicores: int | None = Field(ge=1)
    memory_bytes: int | None = Field(ge=1)
    pids: int | None = Field(ge=1)
    container_count: int | None = Field(ge=1)
    ephemeral_storage_bytes: int | None = Field(ge=1)


class RuntimeExecutionStorageRestriction(_FrozenPolicyModel):
    """Optional lower-layer engine-storage narrowing."""

    mode: RuntimeExecutionStorageMode | None
    capacity_bytes: int | None = Field(ge=1)


class RuntimeExecutionNetworkRestriction(_FrozenPolicyModel):
    """Optional lower-layer egress narrowing."""

    mode: RuntimeExecutionNetworkMode | None
    allowed_destinations: (
        frozenset[Annotated[str, Field(min_length=1, max_length=255)]] | None
    )
    denied_destinations: frozenset[Annotated[str, Field(min_length=1, max_length=255)]]


class RuntimeExecutionPolicyRestriction(_FrozenPolicyModel):
    """Restrictive-only Workspace or Agent policy contribution."""

    schema_version: Literal[1]
    image_build: RuntimeExecutionBooleanRestriction | None
    container_run: RuntimeExecutionBooleanRestriction | None
    compose: RuntimeExecutionBooleanRestriction | None
    resources: RuntimeExecutionResourceRestriction | None
    engine_storage: RuntimeExecutionStorageRestriction | None
    network_egress: RuntimeExecutionNetworkRestriction | None


class RuntimeExecutionModuleSupport(_FrozenPolicyModel):
    """One exact application-owned module version implemented by a Provider."""

    module_id: RuntimeExecutionModuleId
    version: Literal[1]


class RuntimeExecutionProviderCapabilities(_FrozenPolicyModel):
    """Typed Provider compatibility projection consumed by the resolver."""

    supported_modules: frozenset[RuntimeExecutionModuleSupport]
    privileged_engine: bool
    storage_modes: frozenset[RuntimeExecutionStorageMode]
    network_modes: frozenset[RuntimeExecutionNetworkMode]
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
_NETWORK_RANK = {
    RuntimeExecutionNetworkMode.NONE: 0,
    RuntimeExecutionNetworkMode.RESTRICTED: 1,
    RuntimeExecutionNetworkMode.DIRECT: 2,
}
_RESOURCE_PATHS = (
    "cpu_millicores",
    "memory_bytes",
    "pids",
    "container_count",
    "ephemeral_storage_bytes",
)


def standard_runtime_execution_policy() -> RuntimeExecutionPolicyDocument:
    """Return the reserved Standard Profile with direct outbound networking."""
    return RuntimeExecutionPolicyDocument(
        schema_version=1,
        image_build=RuntimeExecutionBooleanModule(
            module_id=RuntimeExecutionModuleId.IMAGE_BUILD,
            version=1,
            enabled=False,
        ),
        container_run=RuntimeExecutionBooleanModule(
            module_id=RuntimeExecutionModuleId.CONTAINER_RUN,
            version=1,
            enabled=False,
        ),
        compose=RuntimeExecutionBooleanModule(
            module_id=RuntimeExecutionModuleId.COMPOSE,
            version=1,
            enabled=False,
        ),
        resources=RuntimeExecutionResourceModule(
            module_id=RuntimeExecutionModuleId.RESOURCES,
            version=1,
            cpu_millicores=None,
            memory_bytes=None,
            pids=None,
            container_count=None,
            ephemeral_storage_bytes=None,
        ),
        engine_storage=RuntimeExecutionStorageModule(
            module_id=RuntimeExecutionModuleId.ENGINE_STORAGE,
            version=1,
            mode=RuntimeExecutionStorageMode.NONE,
            capacity_bytes=None,
        ),
        network_egress=RuntimeExecutionNetworkModule(
            module_id=RuntimeExecutionModuleId.NETWORK_EGRESS,
            version=1,
            mode=RuntimeExecutionNetworkMode.DIRECT,
            allowed_destinations=frozenset(),
            denied_destinations=frozenset(),
        ),
    )


def empty_runtime_execution_restriction() -> RuntimeExecutionPolicyRestriction:
    """Return a restriction document that preserves all parent values."""
    return RuntimeExecutionPolicyRestriction(
        schema_version=1,
        image_build=None,
        container_run=None,
        compose=None,
        resources=None,
        engine_storage=None,
        network_egress=None,
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


def digest_runtime_execution_policy(
    policy: RuntimeExecutionPolicyDocument | RuntimeExecutionPolicyRestriction,
) -> str:
    """Return the canonical SHA-256 execution-policy digest."""
    encoded = json.dumps(
        canonical_runtime_execution_policy(policy),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode()
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
    storage = restriction.engine_storage
    if storage is not None:
        if (
            storage.mode is not None
            and _STORAGE_RANK[storage.mode] > _STORAGE_RANK[parent.engine_storage.mode]
        ):
            raise RuntimeExecutionRestrictionExpansion(
                path="engine_storage.mode",
                governing_layer=governing_layer,
            )
        if (
            storage.capacity_bytes is not None
            and parent.engine_storage.capacity_bytes is not None
            and storage.capacity_bytes > parent.engine_storage.capacity_bytes
        ):
            raise RuntimeExecutionRestrictionExpansion(
                path="engine_storage.capacity_bytes",
                governing_layer=governing_layer,
            )
    network = restriction.network_egress
    if network is not None:
        if (
            network.mode is not None
            and _NETWORK_RANK[network.mode] > _NETWORK_RANK[parent.network_egress.mode]
        ):
            raise RuntimeExecutionRestrictionExpansion(
                path="network_egress.mode",
                governing_layer=governing_layer,
            )
        if (
            network.allowed_destinations is not None
            and parent.network_egress.allowed_destinations
            and not network.allowed_destinations.issubset(
                parent.network_egress.allowed_destinations
            )
        ):
            raise RuntimeExecutionRestrictionExpansion(
                path="network_egress.allowed_destinations",
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
    changes: list[RuntimeExecutionFieldChange] = []
    for path in sorted(before):
        if before[path] == after[path]:
            continue
        changes.append(
            RuntimeExecutionFieldChange(
                path=path,
                direction=_field_change_direction(path, before[path], after[path]),
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


def _apply_restriction(
    policy: RuntimeExecutionPolicyDocument,
    restriction: RuntimeExecutionPolicyRestriction,
    *,
    layer: RuntimeExecutionPolicyLayer,
    governing: dict[str, RuntimeExecutionPolicyLayer],
    reductions: list[RuntimeExecutionReduction],
) -> RuntimeExecutionPolicyDocument:
    image_build = (
        False if restriction.image_build is not None else policy.image_build.enabled
    )
    container_run = (
        False if restriction.container_run is not None else policy.container_run.enabled
    )
    compose = False if restriction.compose is not None else policy.compose.enabled
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
    storage_mode = policy.engine_storage.mode
    storage_capacity = policy.engine_storage.capacity_bytes
    if restriction.engine_storage is not None:
        if restriction.engine_storage.mode is not None:
            storage_mode = min(
                storage_mode,
                restriction.engine_storage.mode,
                key=_STORAGE_RANK.__getitem__,
            )
        storage_capacity = _minimum_bound(
            storage_capacity,
            restriction.engine_storage.capacity_bytes,
        )
    if storage_mode is RuntimeExecutionStorageMode.NONE:
        storage_capacity = None

    network_mode = policy.network_egress.mode
    allowed = policy.network_egress.allowed_destinations
    denied = policy.network_egress.denied_destinations
    if restriction.network_egress is not None:
        if restriction.network_egress.mode is not None:
            network_mode = min(
                network_mode,
                restriction.network_egress.mode,
                key=_NETWORK_RANK.__getitem__,
            )
        if restriction.network_egress.allowed_destinations is not None:
            allowed = allowed & restriction.network_egress.allowed_destinations
        denied = denied | restriction.network_egress.denied_destinations
    if network_mode is RuntimeExecutionNetworkMode.NONE:
        allowed = frozenset()

    result = RuntimeExecutionPolicyDocument(
        schema_version=1,
        image_build=policy.image_build.model_copy(update={"enabled": image_build}),
        container_run=policy.container_run.model_copy(
            update={"enabled": container_run}
        ),
        compose=policy.compose.model_copy(update={"enabled": compose}),
        resources=resources,
        engine_storage=RuntimeExecutionStorageModule(
            module_id=RuntimeExecutionModuleId.ENGINE_STORAGE,
            version=1,
            mode=storage_mode,
            capacity_bytes=storage_capacity,
        ),
        network_egress=RuntimeExecutionNetworkModule(
            module_id=RuntimeExecutionModuleId.NETWORK_EGRESS,
            version=1,
            mode=network_mode,
            allowed_destinations=allowed - denied,
            denied_destinations=denied,
        ),
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
    if policy.compose.enabled and not policy.container_run.enabled:
        return "container.compose/v1 requires container.run/v1."
    engine_needed = policy.image_build.enabled or policy.container_run.enabled
    if engine_needed and policy.engine_storage.mode is RuntimeExecutionStorageMode.NONE:
        return "Container execution capabilities require engine.storage/v1."
    if engine_needed and any(
        getattr(policy.resources, name) is None for name in _RESOURCE_PATHS
    ):
        return "Container execution capabilities require bounded resources."
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
            f"The bound Provider does not support {module.module_id.value}/v1.",
        )
    engine_needed = policy.image_build.enabled or policy.container_run.enabled
    if engine_needed and not provider.privileged_engine:
        return (
            RuntimeExecutionAvailabilityReason.PROVIDER_ENGINE_UNSUPPORTED,
            "The bound Provider does not support the required engine implementation.",
        )
    if (
        policy.engine_storage.mode is not RuntimeExecutionStorageMode.NONE
        and policy.engine_storage.mode not in provider.storage_modes
    ):
        return (
            RuntimeExecutionAvailabilityReason.PROVIDER_STORAGE_UNSUPPORTED,
            "The bound Provider cannot enforce the selected engine storage mode.",
        )
    if (
        policy.network_egress.mode is not RuntimeExecutionNetworkMode.NONE
        and policy.network_egress.mode not in provider.network_modes
    ):
        return (
            RuntimeExecutionAvailabilityReason.PROVIDER_NETWORK_UNSUPPORTED,
            "The bound Provider cannot enforce the selected network mode.",
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
    if policy.image_build.enabled:
        module_ids.add(RuntimeExecutionModuleId.IMAGE_BUILD)
    if policy.container_run.enabled:
        module_ids.add(RuntimeExecutionModuleId.CONTAINER_RUN)
    if policy.compose.enabled:
        module_ids.add(RuntimeExecutionModuleId.COMPOSE)
    if policy.image_build.enabled or policy.container_run.enabled:
        module_ids.update(
            {
                RuntimeExecutionModuleId.RESOURCES,
                RuntimeExecutionModuleId.ENGINE_STORAGE,
            }
        )
    if policy.network_egress.mode is not RuntimeExecutionNetworkMode.NONE:
        module_ids.add(RuntimeExecutionModuleId.NETWORK_EGRESS)
    return frozenset(
        RuntimeExecutionModuleSupport(module_id=module_id, version=1)
        for module_id in module_ids
    )


def _flatten_policy(policy: RuntimeExecutionPolicyDocument) -> dict[str, JsonValue]:
    allowed_destinations: list[JsonValue] = []
    for destination in sorted(policy.network_egress.allowed_destinations):
        allowed_destinations.append(destination)
    denied_destinations: list[JsonValue] = []
    for destination in sorted(policy.network_egress.denied_destinations):
        denied_destinations.append(destination)
    return {
        "image_build.enabled": policy.image_build.enabled,
        "container_run.enabled": policy.container_run.enabled,
        "compose.enabled": policy.compose.enabled,
        **{
            f"resources.{name}": getattr(policy.resources, name)
            for name in _RESOURCE_PATHS
        },
        "engine_storage.mode": policy.engine_storage.mode.value,
        "engine_storage.capacity_bytes": policy.engine_storage.capacity_bytes,
        "network_egress.mode": policy.network_egress.mode.value,
        "network_egress.allowed_destinations": allowed_destinations,
        "network_egress.denied_destinations": denied_destinations,
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
    if path.startswith("resources.") or path == "engine_storage.capacity_bytes":
        before_bound = _numeric_authority(before)
        after_bound = _numeric_authority(after)
        return (
            RuntimeExecutionChangeDirection.AUTHORITY_EXPANDING
            if after_bound > before_bound
            else RuntimeExecutionChangeDirection.RESTRICTIVE
        )
    if path == "engine_storage.mode":
        return (
            RuntimeExecutionChangeDirection.AUTHORITY_EXPANDING
            if _STORAGE_RANK[RuntimeExecutionStorageMode(str(after))]
            > _STORAGE_RANK[RuntimeExecutionStorageMode(str(before))]
            else RuntimeExecutionChangeDirection.RESTRICTIVE
        )
    if path == "network_egress.mode":
        return (
            RuntimeExecutionChangeDirection.AUTHORITY_EXPANDING
            if _NETWORK_RANK[RuntimeExecutionNetworkMode(str(after))]
            > _NETWORK_RANK[RuntimeExecutionNetworkMode(str(before))]
            else RuntimeExecutionChangeDirection.RESTRICTIVE
        )
    before_set = set(_string_list(before))
    after_set = set(_string_list(after))
    if path == "network_egress.allowed_destinations":
        expanding = bool(after_set - before_set)
    else:
        expanding = bool(before_set - after_set)
    restrictive = (
        bool(before_set - after_set)
        if path == "network_egress.allowed_destinations"
        else bool(after_set - before_set)
    )
    if expanding and restrictive:
        return RuntimeExecutionChangeDirection.MIXED
    if expanding:
        return RuntimeExecutionChangeDirection.AUTHORITY_EXPANDING
    return RuntimeExecutionChangeDirection.RESTRICTIVE


def _value_grants_authority(path: str, value: JsonValue) -> bool:
    if path.endswith(".enabled"):
        return value is True
    if path.startswith("resources."):
        return value is not None
    if path == "engine_storage.mode":
        return value != RuntimeExecutionStorageMode.NONE.value
    if path == "engine_storage.capacity_bytes":
        return value is not None
    if path == "network_egress.mode":
        return value != RuntimeExecutionNetworkMode.NONE.value
    if path == "network_egress.allowed_destinations":
        return bool(value)
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


def _string_list(value: JsonValue) -> list[str]:
    if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
        raise AssertionError("Expected a string-list execution-policy value.")
    return [item for item in value if isinstance(item, str)]


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
