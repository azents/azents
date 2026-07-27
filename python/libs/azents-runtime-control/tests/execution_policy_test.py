"""Runtime execution-policy envelope validation tests."""

import dataclasses

import pytest

from azents_runtime_control.execution_policy import (
    JsonValue,
    RuntimeExecutionNetworkMode,
    RuntimeExecutionPolicyEnvelope,
    RuntimeExecutionPolicyEvidence,
    RuntimeExecutionStorageMode,
    digest_effective_policy,
    parse_execution_policy_envelope,
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
            "version": 2,
            "cpu_request_millicores": None,
            "cpu_limit_millicores": None,
            "memory_request_bytes": None,
            "memory_limit_bytes": None,
            "pids": None,
            "container_count": None,
            "ephemeral_storage_bytes": None,
            "persistent_storage_bytes": None,
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
    if image_build:
        resources = policy["resources"]
        storage = policy["engine_storage"]
        assert isinstance(resources, dict)
        assert isinstance(storage, dict)
        resources.update(
            {
                "cpu_request_millicores": 500,
                "cpu_limit_millicores": 1000,
                "memory_request_bytes": 1_073_741_824,
                "memory_limit_bytes": 2_147_483_648,
                "pids": 256,
                "container_count": 8,
                "ephemeral_storage_bytes": 10_737_418_240,
            }
        )
        storage.update({"mode": "ephemeral", "capacity_bytes": 8_589_934_592})
    return RuntimeExecutionPolicyEnvelope(
        evidence=RuntimeExecutionPolicyEvidence(
            snapshot_id="snapshot-1",
            digest=digest_effective_policy(policy),
            desired_generation=3,
            module_versions={
                "container.image_build": 1,
                "container.run": 1,
                "container.compose": 1,
                "container.resources": 2,
                "engine.storage": 1,
                "network.egress": 1,
            },
            source_versions={
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


def test_authority_bearing_policy_parses_as_typed_contract() -> None:
    policy = _policy(image_build=True)
    resources = policy["resources"]
    storage = policy["engine_storage"]
    network = policy["network_egress"]
    assert isinstance(resources, dict)
    assert isinstance(storage, dict)
    assert isinstance(network, dict)
    resources.update(
        {
            "cpu_request_millicores": 500,
            "cpu_limit_millicores": 1000,
            "memory_request_bytes": 1_073_741_824,
            "memory_limit_bytes": 2_147_483_648,
            "pids": 256,
            "container_count": 8,
            "ephemeral_storage_bytes": 10_737_418_240,
        }
    )
    storage.update({"mode": "ephemeral", "capacity_bytes": 8_589_934_592})
    network.update(
        {
            "mode": "restricted",
            "allowed_destinations": ["203.0.113.0/24"],
        }
    )
    envelope = RuntimeExecutionPolicyEnvelope(
        evidence=dataclasses.replace(
            _envelope().evidence,
            digest=digest_effective_policy(policy),
        ),
        effective_policy=policy,
    )

    parsed = parse_execution_policy_envelope(envelope, desired_generation=3)

    assert parsed.image_build is True
    assert parsed.engine_storage.mode is RuntimeExecutionStorageMode.EPHEMERAL
    assert parsed.network_egress.mode is RuntimeExecutionNetworkMode.RESTRICTED
    assert parsed.network_egress.allowed_destinations == ("203.0.113.0/24",)


def test_removed_proxy_network_mode_is_rejected() -> None:
    policy = _policy()
    network = policy["network_egress"]
    assert isinstance(network, dict)
    network["mode"] = "proxy_required"
    envelope = RuntimeExecutionPolicyEnvelope(
        evidence=dataclasses.replace(
            _envelope().evidence,
            digest=digest_effective_policy(policy),
        ),
        effective_policy=policy,
    )

    with pytest.raises(ValueError, match="network mode is invalid"):
        parse_execution_policy_envelope(envelope, desired_generation=3)


def test_engine_policy_requires_ephemeral_storage() -> None:
    policy = _policy(image_build=True)
    envelope = RuntimeExecutionPolicyEnvelope(
        evidence=dataclasses.replace(
            _envelope().evidence,
            digest=digest_effective_policy(policy),
        ),
        effective_policy=policy,
    )

    with pytest.raises(ValueError, match="ephemeral storage"):
        parse_execution_policy_envelope(
            envelope,
            desired_generation=3,
        )


def test_unknown_module_field_is_rejected() -> None:
    policy = _policy()
    resources = policy["resources"]
    assert isinstance(resources, dict)
    resources["unbounded"] = True
    envelope = RuntimeExecutionPolicyEnvelope(
        evidence=dataclasses.replace(
            _envelope().evidence,
            digest=digest_effective_policy(policy),
        ),
        effective_policy=policy,
    )

    with pytest.raises(ValueError, match="module evidence is invalid"):
        parse_execution_policy_envelope(envelope, desired_generation=3)


def test_boolean_schema_version_is_rejected() -> None:
    policy = _policy()
    policy["schema_version"] = True
    envelope = RuntimeExecutionPolicyEnvelope(
        evidence=dataclasses.replace(
            _envelope().evidence,
            digest=digest_effective_policy(policy),
        ),
        effective_policy=policy,
    )

    with pytest.raises(ValueError, match="document shape is invalid"):
        parse_execution_policy_envelope(envelope, desired_generation=3)
