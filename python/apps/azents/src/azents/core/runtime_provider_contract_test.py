"""Runtime Provider capability contract validation tests."""

import pytest
from pydantic import ValidationError

from azents.core.runtime_execution_policy import (
    RuntimeExecutionModuleId,
    RuntimeExecutionNetworkMode,
    RuntimeExecutionStorageMode,
)
from azents.core.runtime_provider_contract import (
    RuntimeProviderApplicationImpact,
    RuntimeProviderCapabilityContract,
    RuntimeProviderConfigField,
    RuntimeProviderExecutionPolicyContract,
    RuntimeProviderLifecycleOperation,
    RuntimeProviderPersistenceContract,
    RuntimeProviderPersistenceKind,
    RuntimeProviderPolicyScope,
    RuntimeProviderStringConfigField,
    canonicalize_runtime_provider_contract,
    runtime_execution_capabilities_from_provider_contract,
)

_REQUIRED_OPERATIONS = set(RuntimeProviderLifecycleOperation)


def _contract(
    *,
    configuration_fields: list[RuntimeProviderConfigField] | None = None,
) -> RuntimeProviderCapabilityContract:
    """Build a complete valid capability contract for tests."""
    return RuntimeProviderCapabilityContract(
        schema_version=1,
        implementation_key="test-provider",
        implementation_version="1.0.0",
        protocol_version="1",
        core_lifecycle_operations=_REQUIRED_OPERATIONS,
        persistence=RuntimeProviderPersistenceContract(
            kind=RuntimeProviderPersistenceKind.PERSISTENT,
            reset_destroys_workspace=False,
            terminal_delete_destroys_workspace=True,
        ),
        configuration_fields=configuration_fields or [],
    )


def test_contract_requires_every_lifecycle_operation() -> None:
    """A Provider cannot advertise a partial lifecycle contract."""
    with pytest.raises(ValidationError, match="omits required lifecycle operations"):
        RuntimeProviderCapabilityContract(
            schema_version=1,
            implementation_key="test-provider",
            implementation_version="1.0.0",
            protocol_version="1",
            core_lifecycle_operations={RuntimeProviderLifecycleOperation.START},
            persistence=RuntimeProviderPersistenceContract(
                kind=RuntimeProviderPersistenceKind.EPHEMERAL,
                reset_destroys_workspace=True,
                terminal_delete_destroys_workspace=True,
            ),
        )


def test_secret_configuration_field_rejects_default() -> None:
    """Secret fields must never carry plaintext defaults in a contract."""
    with pytest.raises(ValidationError, match="must not declare a default"):
        _contract(
            configuration_fields=[
                RuntimeProviderStringConfigField(
                    type="string",
                    name="api_key",
                    scope=RuntimeProviderPolicyScope.PLATFORM,
                    secret=True,
                    application_impact=RuntimeProviderApplicationImpact.IMMEDIATE,
                    default="plaintext",
                )
            ]
        )


def test_contract_canonicalization_produces_stable_digest() -> None:
    """Equivalent canonicalization calls produce the same semantic digest."""
    contract = _contract()

    first = canonicalize_runtime_provider_contract(contract)
    second = canonicalize_runtime_provider_contract(contract)

    assert first.canonical_json == second.canonical_json
    assert first.digest == second.digest
    assert len(first.digest) == 64
    assert "execution_policy" not in first.canonical_json


def test_execution_policy_capabilities_are_typed_and_canonical() -> None:
    """Execution support is stable contract authority rather than metadata."""
    contract = _contract().model_copy(
        update={
            "execution_policy": RuntimeProviderExecutionPolicyContract.model_validate(
                {
                    "schema_version": 1,
                    "supported_modules": [
                        {"module_id": "container.run", "version": 1},
                        {"module_id": "container.image_build", "version": 1},
                    ],
                    "privileged_engine": True,
                    "storage_modes": ["ephemeral", "none"],
                    "network_modes": ["none"],
                    "resource_maxima": None,
                }
            )
        }
    )

    canonical = canonicalize_runtime_provider_contract(contract)
    capabilities = runtime_execution_capabilities_from_provider_contract(contract)

    execution_policy = canonical.canonical_json["execution_policy"]
    assert isinstance(execution_policy, dict)
    assert execution_policy["supported_modules"] == [
        {"module_id": "container.image_build", "version": 1},
        {"module_id": "container.run", "version": 1},
    ]
    assert execution_policy["storage_modes"] == ["ephemeral", "none"]
    assert capabilities.privileged_engine
    assert {support.module_id for support in capabilities.supported_modules} == {
        RuntimeExecutionModuleId.IMAGE_BUILD,
        RuntimeExecutionModuleId.CONTAINER_RUN,
    }


def test_missing_execution_policy_contract_fails_closed() -> None:
    """Legacy accepted contracts cannot grant nested-engine authority."""
    capabilities = runtime_execution_capabilities_from_provider_contract(_contract())

    assert not capabilities.privileged_engine
    assert not capabilities.supported_modules
    assert capabilities.storage_modes == {RuntimeExecutionStorageMode.NONE}
    assert capabilities.network_modes == {RuntimeExecutionNetworkMode.NONE}
