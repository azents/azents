"""Runtime execution-policy envelope validation tests."""

import dataclasses

import pytest

from azents_runtime_control.execution_policy import (
    JsonValue,
    RuntimeExecutionPolicyEnvelope,
    RuntimeExecutionPolicyEvidence,
    RuntimeExecutionStorageMode,
    canonical_effective_policy_json,
    digest_effective_policy,
    parse_execution_policy_envelope,
    validate_standard_execution_policy_envelope,
)


def _policy(*, docker: bool = False) -> dict[str, JsonValue]:
    return {
        "schema_version": 1,
        "docker": {
            "module_id": "docker",
            "version": 1,
            "enabled": docker,
            "storage_mode": "ephemeral" if docker else "none",
            "storage_capacity_bytes": 8_589_934_592 if docker else None,
        },
        "resources": {
            "module_id": "runtime.resources",
            "version": 1,
            "cpu_request_millicores": 500 if docker else None,
            "cpu_limit_millicores": 1_000 if docker else None,
            "memory_request_bytes": 1_073_741_824 if docker else None,
            "memory_limit_bytes": 2_147_483_648 if docker else None,
            "ephemeral_storage_bytes": 10_737_418_240 if docker else None,
            "persistent_storage_bytes": None,
        },
    }


def _envelope(*, docker: bool = False) -> RuntimeExecutionPolicyEnvelope:
    policy = _policy(docker=docker)
    return RuntimeExecutionPolicyEnvelope(
        evidence=RuntimeExecutionPolicyEvidence(
            snapshot_id="snapshot-1",
            digest=digest_effective_policy(policy),
            desired_generation=3,
            module_versions={"docker": 1, "runtime.resources": 1},
            source_versions={"profile": 2, "workspace": 3, "agent": 4},
        ),
        effective_policy_json=canonical_effective_policy_json(policy),
    )


def _replace_policy(
    envelope: RuntimeExecutionPolicyEnvelope,
    policy: dict[str, JsonValue],
) -> RuntimeExecutionPolicyEnvelope:
    return RuntimeExecutionPolicyEnvelope(
        evidence=dataclasses.replace(
            envelope.evidence,
            digest=digest_effective_policy(policy),
        ),
        effective_policy_json=canonical_effective_policy_json(policy),
    )


def test_standard_equivalent_policy_is_accepted() -> None:
    validate_standard_execution_policy_envelope(_envelope(), desired_generation=3)


def test_docker_policy_parses_as_typed_contract() -> None:
    parsed = parse_execution_policy_envelope(
        _envelope(docker=True), desired_generation=3
    )

    assert parsed.docker.enabled
    assert parsed.docker.storage_mode is RuntimeExecutionStorageMode.EPHEMERAL
    assert parsed.docker.storage_capacity_bytes == 8_589_934_592
    assert parsed.resources.ephemeral_storage_bytes == 10_737_418_240


def test_authority_bearing_policy_is_rejected_by_standard_provider() -> None:
    with pytest.raises(ValueError, match="unsupported authority"):
        validate_standard_execution_policy_envelope(
            _envelope(docker=True), desired_generation=3
        )


def test_digest_mismatch_is_rejected() -> None:
    envelope = _envelope()
    invalid = dataclasses.replace(
        envelope,
        evidence=dataclasses.replace(envelope.evidence, digest="a" * 64),
    )
    with pytest.raises(ValueError, match="digest does not match"):
        parse_execution_policy_envelope(invalid, desired_generation=3)


def test_command_generation_mismatch_is_rejected() -> None:
    with pytest.raises(ValueError, match="generation does not match"):
        parse_execution_policy_envelope(_envelope(), desired_generation=4)


def test_module_version_evidence_mismatch_is_rejected() -> None:
    envelope = _envelope()
    invalid = dataclasses.replace(
        envelope,
        evidence=dataclasses.replace(
            envelope.evidence,
            module_versions={"docker": 1, "runtime.resources": 2},
        ),
    )
    with pytest.raises(ValueError, match="module evidence does not match"):
        parse_execution_policy_envelope(invalid, desired_generation=3)


def test_enabled_docker_requires_ephemeral_storage_allocation() -> None:
    envelope = _envelope(docker=True)
    policy = _policy(docker=True)
    resources = policy["resources"]
    assert isinstance(resources, dict)
    resources["ephemeral_storage_bytes"] = None

    with pytest.raises(ValueError, match="ephemeral-storage"):
        parse_execution_policy_envelope(
            _replace_policy(envelope, policy), desired_generation=3
        )


def test_unknown_module_field_is_rejected() -> None:
    envelope = _envelope()
    policy = _policy()
    resources = policy["resources"]
    assert isinstance(resources, dict)
    resources["unbounded"] = True

    with pytest.raises(ValueError, match="module evidence is invalid"):
        parse_execution_policy_envelope(
            _replace_policy(envelope, policy), desired_generation=3
        )


def test_boolean_schema_version_is_rejected() -> None:
    envelope = _envelope()
    policy = _policy()
    policy["schema_version"] = True

    with pytest.raises(ValueError, match="document shape is invalid"):
        parse_execution_policy_envelope(
            _replace_policy(envelope, policy), desired_generation=3
        )
