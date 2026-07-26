"""Runtime execution-policy envelope validation tests."""

import pytest

from azents_runtime_control.execution_policy import (
    JsonValue,
    RuntimeExecutionPolicyEnvelope,
    RuntimeExecutionPolicyEvidence,
    digest_effective_policy,
    validate_standard_execution_policy_envelope,
)


def _policy(*, image_build: bool = False) -> dict[str, JsonValue]:
    return {
        "schema_version": 1,
        "image_build": {
            "module_id": "container.image_build",
            "version": 1,
            "enabled": image_build,
        },
        "container_run": {
            "module_id": "container.run",
            "version": 1,
            "enabled": False,
        },
        "compose": {
            "module_id": "container.compose",
            "version": 1,
            "enabled": False,
        },
        "resources": {
            "module_id": "container.resources",
            "version": 1,
            "cpu_millicores": None,
            "memory_bytes": None,
            "pids": None,
            "container_count": None,
            "ephemeral_storage_bytes": None,
        },
        "engine_storage": {
            "module_id": "engine.storage",
            "version": 1,
            "mode": "none",
            "capacity_bytes": None,
        },
        "network_egress": {
            "module_id": "network.egress",
            "version": 1,
            "mode": "none",
            "allowed_destinations": [],
            "denied_destinations": [],
        },
    }


def _envelope(*, image_build: bool = False) -> RuntimeExecutionPolicyEnvelope:
    policy = _policy(image_build=image_build)
    return RuntimeExecutionPolicyEnvelope(
        evidence=RuntimeExecutionPolicyEvidence(
            snapshot_id="snapshot-1",
            digest=digest_effective_policy(policy),
            desired_generation=3,
            module_versions={
                "container.image_build": 1,
                "container.run": 1,
                "container.compose": 1,
                "container.resources": 1,
                "engine.storage": 1,
                "network.egress": 1,
            },
            source_versions={
                "platform": 1,
                "profile": 2,
                "workspace": 3,
                "agent": 4,
            },
        ),
        effective_policy=policy,
    )


def test_standard_equivalent_policy_is_accepted() -> None:
    validate_standard_execution_policy_envelope(
        _envelope(),
        desired_generation=3,
    )


def test_authority_bearing_policy_is_rejected() -> None:
    with pytest.raises(ValueError, match="unsupported authority"):
        validate_standard_execution_policy_envelope(
            _envelope(image_build=True),
            desired_generation=3,
        )


def test_digest_mismatch_is_rejected() -> None:
    envelope = _envelope()
    invalid = RuntimeExecutionPolicyEnvelope(
        evidence=RuntimeExecutionPolicyEvidence(
            snapshot_id=envelope.evidence.snapshot_id,
            digest="a" * 64,
            desired_generation=envelope.evidence.desired_generation,
            module_versions=envelope.evidence.module_versions,
            source_versions=envelope.evidence.source_versions,
        ),
        effective_policy=envelope.effective_policy,
    )
    with pytest.raises(ValueError, match="digest does not match"):
        validate_standard_execution_policy_envelope(
            invalid,
            desired_generation=3,
        )


def test_command_generation_mismatch_is_rejected() -> None:
    with pytest.raises(ValueError, match="generation does not match"):
        validate_standard_execution_policy_envelope(
            _envelope(),
            desired_generation=4,
        )


def test_module_version_evidence_mismatch_is_rejected() -> None:
    envelope = _envelope()
    invalid = RuntimeExecutionPolicyEnvelope(
        evidence=RuntimeExecutionPolicyEvidence(
            snapshot_id=envelope.evidence.snapshot_id,
            digest=envelope.evidence.digest,
            desired_generation=envelope.evidence.desired_generation,
            module_versions={
                **envelope.evidence.module_versions,
                "container.run": 2,
            },
            source_versions=envelope.evidence.source_versions,
        ),
        effective_policy=envelope.effective_policy,
    )

    with pytest.raises(ValueError, match="module evidence does not match"):
        validate_standard_execution_policy_envelope(
            invalid,
            desired_generation=3,
        )
