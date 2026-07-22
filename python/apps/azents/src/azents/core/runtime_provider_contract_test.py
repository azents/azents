"""Runtime Provider capability contract validation tests."""

import pytest
from pydantic import ValidationError

from azents.core.runtime_provider_contract import (
    RuntimeProviderApplicationImpact,
    RuntimeProviderCapabilityContract,
    RuntimeProviderConfigField,
    RuntimeProviderLifecycleOperation,
    RuntimeProviderPersistenceContract,
    RuntimeProviderPersistenceKind,
    RuntimeProviderPolicyScope,
    RuntimeProviderStringConfigField,
    canonicalize_runtime_provider_contract,
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
