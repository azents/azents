"""Runtime execution-policy command and evidence contracts."""

import dataclasses
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
    if evidence.desired_generation < 0:
        raise ValueError("Runtime execution-policy desired generation is invalid.")
    if len(evidence.digest) != 64:
        raise ValueError("Runtime execution-policy digest is invalid.")
    if digest_effective_policy(envelope.effective_policy) != evidence.digest:
        raise ValueError("Runtime execution-policy digest does not match its document.")
    if not evidence.module_versions or any(
        not module_id or version < 1
        for module_id, version in evidence.module_versions.items()
    ):
        raise ValueError("Runtime execution-policy module evidence is incomplete.")
    if set(evidence.source_versions) != {
        "platform",
        "profile",
        "workspace",
        "agent",
    } or any(version < 1 for version in evidence.source_versions.values()):
        raise ValueError("Runtime execution-policy source evidence is incomplete.")


def validate_standard_execution_policy_envelope(
    envelope: RuntimeExecutionPolicyEnvelope,
    *,
    desired_generation: int,
) -> None:
    """Accept only the non-authority-bearing Standard-equivalent policy."""
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
    if policy.get("schema_version") != 1 or set(policy) != {
        "schema_version",
        *expected_modules,
    }:
        raise ValueError("Runtime execution policy is not Standard-equivalent.")
    modules = {
        field: _module(policy, field, module_id)
        for field, module_id in expected_modules.items()
    }
    expected_module_versions = {module_id: 1 for module_id in expected_modules.values()}
    if dict(envelope.evidence.module_versions) != expected_module_versions:
        raise ValueError(
            "Runtime execution-policy module evidence does not match its document."
        )
    for field in ("image_build", "container_run", "compose"):
        module = modules[field]
        if module.get("enabled") is not False:
            raise ValueError("Runtime execution policy grants unsupported authority.")
    resources = modules["resources"]
    if any(
        resources.get(field) is not None
        for field in (
            "cpu_millicores",
            "memory_bytes",
            "pids",
            "container_count",
            "ephemeral_storage_bytes",
        )
    ):
        raise ValueError("Runtime execution policy grants unsupported resources.")
    storage = modules["engine_storage"]
    if storage.get("mode") != "none" or storage.get("capacity_bytes") is not None:
        raise ValueError("Runtime execution policy grants unsupported storage.")
    network = modules["network_egress"]
    if (
        network.get("mode") != "none"
        or network.get("allowed_destinations") not in ([], ())
        or network.get("denied_destinations") not in ([], ())
    ):
        raise ValueError("Runtime execution policy grants unsupported network access.")


def _module(
    policy: Mapping[str, JsonValue],
    field: str,
    module_id: str,
) -> dict[str, JsonValue]:
    value = policy.get(field)
    if (
        not isinstance(value, dict)
        or value.get("module_id") != module_id
        or value.get("version") != 1
    ):
        raise ValueError("Runtime execution-policy module evidence is invalid.")
    return value
