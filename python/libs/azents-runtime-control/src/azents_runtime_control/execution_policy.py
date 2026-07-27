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
    effective_policy_json: str


class RuntimeExecutionStorageMode(enum.StrEnum):
    """Supported Docker data-storage lifecycle."""

    NONE = "none"
    EPHEMERAL = "ephemeral"
    PERSISTENT = "persistent"


@dataclasses.dataclass(frozen=True)
class RuntimeExecutionResources:
    """Typed Kubernetes Runtime resources from one policy."""

    cpu_request_millicores: int | None
    cpu_limit_millicores: int | None
    memory_request_bytes: int | None
    memory_limit_bytes: int | None
    ephemeral_storage_bytes: int | None
    persistent_storage_bytes: int | None


@dataclasses.dataclass(frozen=True)
class RuntimeExecutionDocker:
    """Complete Docker authority and its private data-volume lifecycle."""

    enabled: bool
    storage_mode: RuntimeExecutionStorageMode
    storage_capacity_bytes: int | None


@dataclasses.dataclass(frozen=True)
class RuntimeExecutionPolicy:
    """Complete typed execution policy consumed by Providers."""

    docker: RuntimeExecutionDocker
    resources: RuntimeExecutionResources


def digest_effective_policy(policy: Mapping[str, JsonValue]) -> str:
    """Return the canonical SHA-256 digest for an effective policy document."""
    return hashlib.sha256(canonical_effective_policy_json(policy).encode()).hexdigest()


def canonical_effective_policy_json(policy: Mapping[str, JsonValue]) -> str:
    """Serialize an effective policy as deterministic JSON for storage and transport."""
    return json.dumps(
        policy,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )


def effective_policy_from_json(value: str) -> dict[str, JsonValue]:
    """Parse one canonical effective-policy JSON object."""
    try:
        parsed: JsonValue = json.loads(value)
    except (json.JSONDecodeError, TypeError) as error:
        raise ValueError("Runtime execution-policy JSON is invalid.") from error
    if not isinstance(parsed, dict):
        raise ValueError("Runtime execution-policy JSON must contain an object.")
    if canonical_effective_policy_json(parsed) != value:
        raise ValueError("Runtime execution-policy JSON is not canonical.")
    return parsed


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
    policy = effective_policy_from_json(envelope.effective_policy_json)
    if digest_effective_policy(policy) != evidence.digest:
        raise ValueError("Runtime execution-policy digest does not match its document.")
    if not evidence.module_versions or any(
        not module_id or isinstance(version, bool) or version < 1
        for module_id, version in evidence.module_versions.items()
    ):
        raise ValueError("Runtime execution-policy module evidence is incomplete.")
    if set(evidence.source_versions) != {
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
    if policy.docker.enabled:
        raise ValueError("Runtime execution policy grants unsupported authority.")
    if any(dataclasses.astuple(policy.resources)):
        raise ValueError("Runtime execution policy grants unsupported resources.")
    if (
        policy.docker.storage_mode is not RuntimeExecutionStorageMode.NONE
        or policy.docker.storage_capacity_bytes is not None
    ):
        raise ValueError("Runtime execution policy grants unsupported storage.")


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
    policy = effective_policy_from_json(envelope.effective_policy_json)
    expected_modules = {
        "docker": "docker",
        "resources": "runtime.resources",
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
        "docker": {"enabled", "storage_mode", "storage_capacity_bytes"},
        "resources": {
            "cpu_request_millicores",
            "cpu_limit_millicores",
            "memory_request_bytes",
            "memory_limit_bytes",
            "ephemeral_storage_bytes",
            "persistent_storage_bytes",
        },
    }
    modules = {
        field: _module(
            policy,
            field,
            module_id,
            expected_version=1,
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
        docker=_docker_module(modules["docker"]),
        resources=RuntimeExecutionResources(
            **{
                field: _optional_positive_int(modules["resources"], field)
                for field in (
                    "cpu_request_millicores",
                    "cpu_limit_millicores",
                    "memory_request_bytes",
                    "memory_limit_bytes",
                    "ephemeral_storage_bytes",
                    "persistent_storage_bytes",
                )
            }
        ),
    )
    if parsed.docker.enabled and parsed.resources.ephemeral_storage_bytes is None:
        raise ValueError("Docker requires a Kubernetes ephemeral-storage allocation.")
    if (
        parsed.resources.cpu_request_millicores is not None
        and parsed.resources.cpu_limit_millicores is not None
        and parsed.resources.cpu_request_millicores
        > parsed.resources.cpu_limit_millicores
    ):
        raise ValueError("CPU request cannot exceed CPU limit.")
    if (
        parsed.resources.memory_request_bytes is not None
        and parsed.resources.memory_limit_bytes is not None
        and parsed.resources.memory_request_bytes > parsed.resources.memory_limit_bytes
    ):
        raise ValueError("Memory request cannot exceed memory limit.")
    return parsed


def _module(
    policy: Mapping[str, JsonValue],
    field: str,
    module_id: str,
    *,
    expected_version: int,
    expected_fields: set[str],
) -> dict[str, JsonValue]:
    value = policy.get(field)
    version = value.get("version") if isinstance(value, dict) else None
    if (
        not isinstance(value, dict)
        or value.get("module_id") != module_id
        or isinstance(version, bool)
        or not isinstance(version, int)
        or version != expected_version
        or set(value) != {"module_id", "version", *expected_fields}
    ):
        raise ValueError("Runtime execution-policy module evidence is invalid.")
    return value


def _docker_module(module: Mapping[str, JsonValue]) -> RuntimeExecutionDocker:
    enabled = module.get("enabled")
    if not isinstance(enabled, bool):
        raise ValueError("Runtime execution-policy Docker module is invalid.")
    try:
        storage_mode = RuntimeExecutionStorageMode(str(module.get("storage_mode")))
    except ValueError as error:
        raise ValueError("Runtime execution-policy storage mode is invalid.") from error
    storage_capacity = _optional_positive_int(module, "storage_capacity_bytes")
    if not enabled:
        if storage_mode is not RuntimeExecutionStorageMode.NONE:
            raise ValueError("Disabled Docker must not allocate storage.")
        if storage_capacity is not None:
            raise ValueError("Disabled Docker must not declare storage capacity.")
    elif storage_mode is RuntimeExecutionStorageMode.NONE:
        raise ValueError("Enabled Docker requires a storage mode.")
    elif storage_capacity is None:
        raise ValueError("Enabled Docker requires a storage capacity.")
    return RuntimeExecutionDocker(
        enabled=enabled,
        storage_mode=storage_mode,
        storage_capacity_bytes=storage_capacity,
    )


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
