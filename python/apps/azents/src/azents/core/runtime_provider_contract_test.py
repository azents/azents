"""Runtime Provider capability-contract tests."""

import pytest
from pydantic import ValidationError

from azents.core.runtime_provider_contract import (
    RuntimeProviderCapabilityContract,
    canonicalize_runtime_provider_contract,
)


def _contract() -> RuntimeProviderCapabilityContract:
    return RuntimeProviderCapabilityContract.model_validate(
        {
            "schema_version": 1,
            "implementation_key": "kubernetes",
            "implementation_version": "0.1.0",
            "protocol_version": "agent-runtime-provider-kubernetes-v1",
            "core_lifecycle_operations": [
                "start",
                "stop",
                "restart",
                "reset",
                "observe",
                "terminal_delete",
            ],
            "optional_capabilities": [
                "docker_privileged_dind",
                "docker_storage_ephemeral",
            ],
            "persistence": {
                "kind": "persistent",
                "reset_destroys_workspace": True,
                "terminal_delete_destroys_workspace": True,
            },
            "configuration_fields": [],
            "profile_contracts": [
                {
                    "profile_kind": "kubernetes_pod",
                    "contract_family": "kubernetes.pod-profile",
                    "schema_versions": [2, 1],
                    "capabilities": [
                        "runtime.resources",
                        "kubernetes.pod-profile",
                    ],
                    "constraints": {},
                }
            ],
        }
    )


def test_contract_accepts_profile_capability() -> None:
    contract = _contract()

    assert contract.profile_contracts[0].contract_family == "kubernetes.pod-profile"


def test_contract_rejects_removed_execution_policy_branch() -> None:
    payload = _contract().model_dump(mode="json")
    payload["execution_policy"] = {"schema_version": 1}

    with pytest.raises(ValidationError, match="execution_policy"):
        RuntimeProviderCapabilityContract.model_validate(payload)


def test_contract_canonicalization_sorts_set_backed_fields() -> None:
    first = canonicalize_runtime_provider_contract(_contract())
    second = canonicalize_runtime_provider_contract(
        RuntimeProviderCapabilityContract.model_validate(
            _contract().model_dump(mode="json")
        )
    )

    assert first.digest == second.digest
    profile_contracts = first.canonical_json["profile_contracts"]
    assert isinstance(profile_contracts, list)
    profile_contract = profile_contracts[0]
    assert isinstance(profile_contract, dict)
    assert profile_contract["schema_versions"] == [1, 2]
    assert profile_contract["capabilities"] == [
        "kubernetes.pod-profile",
        "runtime.resources",
    ]
