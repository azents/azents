"""Runtime Provider capability-contract tests."""

import pytest
from pydantic import ValidationError

from azents.core.runtime_execution_policy import (
    RuntimeExecutionModuleId,
    RuntimeExecutionStorageMode,
)
from azents.core.runtime_provider_contract import (
    RuntimeProviderCapabilityContract,
    canonicalize_runtime_provider_contract,
    runtime_execution_capabilities_from_provider_contract,
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
            "execution_policy": {
                "schema_version": 1,
                "supported_modules": [
                    {"module_id": "docker", "version": 1},
                    {"module_id": "runtime.resources", "version": 1},
                ],
                "storage_modes": ["none", "ephemeral"],
                "resource_maxima": None,
            },
        }
    )


def test_contract_accepts_complete_v1_docker_capability() -> None:
    contract = _contract()

    assert contract.execution_policy is not None
    assert {
        module.module_id for module in contract.execution_policy.supported_modules
    } == {
        RuntimeExecutionModuleId.DOCKER,
        RuntimeExecutionModuleId.RESOURCES,
    }


def test_contract_rejects_removed_execution_capability_fields() -> None:
    payload = _contract().model_dump(mode="json")
    execution_policy = payload["execution_policy"]
    assert isinstance(execution_policy, dict)
    execution_policy["privileged_engine"] = True

    with pytest.raises(ValidationError, match="privileged_engine"):
        RuntimeProviderCapabilityContract.model_validate(payload)


def test_contract_canonicalization_sorts_set_backed_fields() -> None:
    first = canonicalize_runtime_provider_contract(_contract())
    second = canonicalize_runtime_provider_contract(
        RuntimeProviderCapabilityContract.model_validate(
            _contract().model_dump(mode="json")
        )
    )

    assert first.digest == second.digest
    execution_policy = first.canonical_json["execution_policy"]
    assert isinstance(execution_policy, dict)
    assert execution_policy["supported_modules"] == [
        {"module_id": "docker", "version": 1},
        {"module_id": "runtime.resources", "version": 1},
    ]


def test_execution_capabilities_project_only_declared_support() -> None:
    capabilities = runtime_execution_capabilities_from_provider_contract(_contract())

    assert {module.module_id for module in capabilities.supported_modules} == {
        RuntimeExecutionModuleId.DOCKER,
        RuntimeExecutionModuleId.RESOURCES,
    }
    assert capabilities.storage_modes == {
        RuntimeExecutionStorageMode.NONE,
        RuntimeExecutionStorageMode.EPHEMERAL,
    }


def test_contract_without_execution_policy_is_fail_closed() -> None:
    payload = _contract().model_dump(mode="json")
    payload["execution_policy"] = None
    contract = RuntimeProviderCapabilityContract.model_validate(payload)

    capabilities = runtime_execution_capabilities_from_provider_contract(contract)

    assert capabilities.supported_modules == frozenset()
    assert capabilities.storage_modes == {RuntimeExecutionStorageMode.NONE}
