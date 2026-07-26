"""Runtime execution-policy command and evidence contracts."""

import dataclasses
import enum
import hashlib
import json
from collections.abc import Mapping
from typing import TypeAlias

JsonValue: TypeAlias = (
    None | bool | int | float | str | list["JsonValue"] | dict[str, "JsonValue"]
)


@dataclasses.dataclass(frozen=True)
class RuntimeExecutionPolicyEvidence:
    """Non-secret evidence identifying one exact applied execution policy."""

    snapshot_id: str
    digest: str
    desired_generation: int
    module_versions: Mapping[str, int]
    source_versions: Mapping[str, int]


@dataclasses.dataclass(frozen=True)
class RuntimeExecutionPolicyEnvelope:
    """Validated effective execution policy sent to a bound Provider."""

    evidence: RuntimeExecutionPolicyEvidence
    effective_policy: Mapping[str, JsonValue]


class RuntimeExecutionStorageMode(enum.StrEnum):
    """Supported nested-engine storage lifecycle."""

    NONE = "none"
    EPHEMERAL = "ephemeral"
    PERSISTENT = "persistent"


class RuntimeExecutionNetworkMode(enum.StrEnum):
    """Supported optional Runtime egress mode."""

    NONE = "none"
    PROXY_REQUIRED = "proxy_required"
    RESTRICTED = "restricted"
    DIRECT = "direct"


@dataclasses.dataclass(frozen=True)
class RuntimeExecutionResources:
    """Typed aggregate resource ceilings from one effective policy."""

    cpu_millicores: int | None
    memory_bytes: int | None
    pids: int | None
    container_count: int | None
    ephemeral_storage_bytes: int | None


@dataclasses.dataclass(frozen=True)
class RuntimeExecutionEngineStorage:
    """Typed nested-engine storage policy."""

    mode: RuntimeExecutionStorageMode
    capacity_bytes: int | None


@dataclasses.dataclass(frozen=True)
class RuntimeExecutionNetworkEgress:
    """Typed optional Runtime egress policy."""

    mode: RuntimeExecutionNetworkMode
    allowed_destinations: tuple[str, ...]
    denied_destinations: tuple[str, ...]


@dataclasses.dataclass(frozen=True)
class RuntimeExecutionPolicy:
    """Complete typed execution policy consumed by Providers."""

    image_build: bool
    container_run: bool
    compose: bool
    resources: RuntimeExecutionResources
    engine_storage: RuntimeExecutionEngineStorage
    network_egress: RuntimeExecutionNetworkEgress


def digest_effective_policy(policy: Mapping[str, JsonValue]) -> str:
    """Return the canonical SHA-256 digest for an effective policy document."""
    encoded = json.dumps(
        policy,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode()
    return hashlib.sha256(encoded).hexdigest()


def validate_execution_policy_envelope(
    envelope: RuntimeExecutionPolicyEnvelope,
) -> None:
    """Reject incomplete, generation-mismatched, or non-canonical evidence."""
    evidence = envelope.evidence
    if not evidence.snapshot_id:
        raise ValueError("Runtime execution-policy snapshot ID is required.")
    if isinstance(evidence.desired_generation, bool) or evidence.desired_generation < 0:
        raise ValueError("Runtime execution-policy desired generation is invalid.")
    if len(evidence.digest) != 64:
        raise ValueError("Runtime execution-policy digest is invalid.")
    if digest_effective_policy(envelope.effective_policy) != evidence.digest:
        raise ValueError("Runtime execution-policy digest does not match its document.")
    if not evidence.module_versions or any(
        not module_id or isinstance(version, bool) or version < 1
        for module_id, version in evidence.module_versions.items()
    ):
        raise ValueError("Runtime execution-policy module evidence is incomplete.")
    if set(evidence.source_versions) != {
        "platform",
        "profile",
        "workspace",
        "agent",
    } or any(
        isinstance(version, bool) or version < 1
        for version in evidence.source_versions.values()
    ):
        raise ValueError("Runtime execution-policy source evidence is incomplete.")


def validate_standard_execution_policy_envelope(
    envelope: RuntimeExecutionPolicyEnvelope,
    *,
    desired_generation: int,
) -> None:
    """Accept only the non-authority-bearing Standard-equivalent policy."""
    policy = parse_execution_policy_envelope(
        envelope,
        desired_generation=desired_generation,
    )
    if policy.image_build or policy.container_run or policy.compose:
        raise ValueError("Runtime execution policy grants unsupported authority.")
    if any(dataclasses.astuple(policy.resources)):
        raise ValueError("Runtime execution policy grants unsupported resources.")
    if (
        policy.engine_storage.mode is not RuntimeExecutionStorageMode.NONE
        or policy.engine_storage.capacity_bytes is not None
    ):
        raise ValueError("Runtime execution policy grants unsupported storage.")
    if (
        policy.network_egress.mode is not RuntimeExecutionNetworkMode.NONE
        or policy.network_egress.allowed_destinations
        or policy.network_egress.denied_destinations
    ):
        raise ValueError("Runtime execution policy grants unsupported network access.")


def parse_execution_policy_envelope(
    envelope: RuntimeExecutionPolicyEnvelope,
    *,
    desired_generation: int,
) -> RuntimeExecutionPolicy:
    """Validate and parse the complete application-owned policy catalog."""
    validate_execution_policy_envelope(envelope)
    if envelope.evidence.desired_generation != desired_generation:
        raise ValueError(
            "Runtime execution-policy evidence generation does not match the command."
        )
    policy = envelope.effective_policy
    expected_modules = {
        "image_build": "container.image_build",
        "container_run": "container.run",
        "compose": "container.compose",
        "resources": "container.resources",
        "engine_storage": "engine.storage",
        "network_egress": "network.egress",
    }
    schema_version = policy.get("schema_version")
    if (
        isinstance(schema_version, bool)
        or not isinstance(schema_version, int)
        or schema_version != 1
        or set(policy)
        != {
            "schema_version",
            *expected_modules,
        }
    ):
        raise ValueError("Runtime execution-policy document shape is invalid.")
    module_fields = {
        "image_build": {"enabled"},
        "container_run": {"enabled"},
        "compose": {"enabled"},
        "resources": {
            "cpu_millicores",
            "memory_bytes",
            "pids",
            "container_count",
            "ephemeral_storage_bytes",
        },
        "engine_storage": {"mode", "capacity_bytes"},
        "network_egress": {
            "mode",
            "allowed_destinations",
            "denied_destinations",
        },
    }
    modules = {
        field: _module(
            policy,
            field,
            module_id,
            expected_fields=module_fields[field],
        )
        for field, module_id in expected_modules.items()
    }
    expected_module_versions = {module_id: 1 for module_id in expected_modules.values()}
    if dict(envelope.evidence.module_versions) != expected_module_versions:
        raise ValueError(
            "Runtime execution-policy module evidence does not match its document."
        )
    parsed = RuntimeExecutionPolicy(
        image_build=_boolean_module(modules["image_build"]),
        container_run=_boolean_module(modules["container_run"]),
        compose=_boolean_module(modules["compose"]),
        resources=RuntimeExecutionResources(
            **{
                field: _optional_positive_int(modules["resources"], field)
                for field in (
                    "cpu_millicores",
                    "memory_bytes",
                    "pids",
                    "container_count",
                    "ephemeral_storage_bytes",
                )
            }
        ),
        engine_storage=_engine_storage(modules["engine_storage"]),
        network_egress=_network_egress(modules["network_egress"]),
    )
    if parsed.compose and not parsed.container_run:
        raise ValueError("container.compose/v1 requires container.run/v1.")
    engine_required = parsed.image_build or parsed.container_run
    if engine_required and any(
        value is None for value in dataclasses.astuple(parsed.resources)
    ):
        raise ValueError("Container execution requires bounded resources.")
    if (
        engine_required
        and parsed.engine_storage.mode is RuntimeExecutionStorageMode.NONE
    ):
        raise ValueError("Container execution requires engine storage.")
    return parsed


def _module(
    policy: Mapping[str, JsonValue],
    field: str,
    module_id: str,
    *,
    expected_fields: set[str],
) -> dict[str, JsonValue]:
    value = policy.get(field)
    version = value.get("version") if isinstance(value, dict) else None
    if (
        not isinstance(value, dict)
        or value.get("module_id") != module_id
        or isinstance(version, bool)
        or not isinstance(version, int)
        or version != 1
        or set(value) != {"module_id", "version", *expected_fields}
    ):
        raise ValueError("Runtime execution-policy module evidence is invalid.")
    return value


def _boolean_module(module: Mapping[str, JsonValue]) -> bool:
    enabled = module.get("enabled")
    if not isinstance(enabled, bool):
        raise ValueError("Runtime execution-policy boolean module is invalid.")
    return enabled


def _optional_positive_int(
    module: Mapping[str, JsonValue],
    field: str,
) -> int | None:
    value = module.get(field)
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise ValueError("Runtime execution-policy resource bound is invalid.")
    return value


def _engine_storage(
    module: Mapping[str, JsonValue],
) -> RuntimeExecutionEngineStorage:
    try:
        mode = RuntimeExecutionStorageMode(str(module.get("mode")))
    except ValueError as error:
        raise ValueError("Runtime execution-policy storage mode is invalid.") from error
    capacity = _optional_positive_int(module, "capacity_bytes")
    if mode is RuntimeExecutionStorageMode.NONE:
        if capacity is not None:
            raise ValueError("Engine storage capacity requires a storage mode.")
    elif capacity is None:
        raise ValueError("Engine storage mode requires a capacity ceiling.")
    return RuntimeExecutionEngineStorage(mode=mode, capacity_bytes=capacity)


def _network_egress(
    module: Mapping[str, JsonValue],
) -> RuntimeExecutionNetworkEgress:
    try:
        mode = RuntimeExecutionNetworkMode(str(module.get("mode")))
    except ValueError as error:
        raise ValueError("Runtime execution-policy network mode is invalid.") from error
    allowed = _string_tuple(module, "allowed_destinations")
    denied = _string_tuple(module, "denied_destinations")
    if set(allowed) & set(denied):
        raise ValueError("Network destinations cannot be both allowed and denied.")
    if mode is RuntimeExecutionNetworkMode.NONE and allowed:
        raise ValueError("No-egress mode cannot declare allowed destinations.")
    return RuntimeExecutionNetworkEgress(
        mode=mode,
        allowed_destinations=allowed,
        denied_destinations=denied,
    )


def _string_tuple(
    module: Mapping[str, JsonValue],
    field: str,
) -> tuple[str, ...]:
    value = module.get(field)
    if not isinstance(value, list):
        raise ValueError("Runtime execution-policy destination list is invalid.")
    result: list[str] = []
    for item in value:
        if not isinstance(item, str) or not item:
            raise ValueError("Runtime execution-policy destination list is invalid.")
        result.append(item)
    return tuple(sorted(result))
