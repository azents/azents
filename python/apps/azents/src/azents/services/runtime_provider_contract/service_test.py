"""Runtime Provider capability advertisement lifecycle tests."""

import datetime

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from azents.core.enums import (
    RuntimeProviderAvailabilityMode,
    RuntimeProviderKind,
    RuntimeProviderLifecycleState,
    RuntimeProviderRegistrationMethod,
    RuntimeProviderScope,
)
from azents.rdb.session import SessionManager
from azents.repos.runtime_profile.repository import RuntimeProfileRepository
from azents.repos.runtime_provider.data import RuntimeProviderCreate
from azents.repos.runtime_provider.repository import RuntimeProviderRepository
from azents.repos.runtime_provider_policy.repository import (
    RuntimeProviderPolicyRepository,
)

from .service import (
    RuntimeProviderContractService,
    RuntimeProviderContractUnavailable,
)

_PROTOCOL_VERSION = "agent-runtime-provider-kubernetes-v1"


def _contract_payload() -> dict[str, object]:
    """Build the Kubernetes contract submitted by the production Provider."""
    return {
        "schema_version": 1,
        "implementation_key": "kubernetes",
        "implementation_version": "0.1.0",
        "protocol_version": _PROTOCOL_VERSION,
        "core_lifecycle_operations": [
            "start",
            "stop",
            "restart",
            "reset",
            "observe",
            "terminal_delete",
        ],
        "optional_capabilities": ["execution_policy_v1"],
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
                "schema_versions": [1],
                "capabilities": [
                    "kubernetes.pod-profile",
                    "runtime.resources",
                    "runtime.network-policy",
                    "workspace.persistent-volume",
                ],
                "constraints": {},
            }
        ],
    }


async def _create_provider(
    session_manager: SessionManager[AsyncSession],
) -> str:
    """Create the durable Provider used by advertisement tests."""
    async with session_manager() as session:
        provider = await RuntimeProviderRepository().create(
            session,
            RuntimeProviderCreate(
                provider_id="system-kubernetes-contract-test",
                scope=RuntimeProviderScope.SYSTEM,
                workspace_id=None,
                kind=RuntimeProviderKind.KUBERNETES,
                display_name="Kubernetes",
                registration_method=RuntimeProviderRegistrationMethod.ADMIN,
                enabled=True,
                lifecycle_state=RuntimeProviderLifecycleState.ACTIVE,
                availability_mode=RuntimeProviderAvailabilityMode.PLATFORM_WIDE,
                capabilities={},
                config_schema=None,
                metadata=None,
            ),
        )
    return provider.id


def _service(
    session_manager: SessionManager[AsyncSession],
) -> RuntimeProviderContractService:
    """Build the production contract service."""
    return RuntimeProviderContractService(
        session_manager=session_manager,
        provider_repository=RuntimeProviderRepository(),
        policy_repository=RuntimeProviderPolicyRepository(),
        profile_repository=RuntimeProfileRepository(),
    )


async def test_advertisement_is_immediately_authoritative_and_idempotent(
    rdb_session_manager: SessionManager[AsyncSession],
) -> None:
    """A valid advertisement immediately becomes current without Admin action."""
    provider_resource_id = await _create_provider(rdb_session_manager)
    service = _service(rdb_session_manager)

    first = await service.propose_contract(
        provider_resource_id=provider_resource_id,
        provider_type="kubernetes",
        protocol_version=_PROTOCOL_VERSION,
        contract_payload=_contract_payload(),
    )
    repeated = await service.propose_contract(
        provider_resource_id=provider_resource_id,
        provider_type="kubernetes",
        protocol_version=_PROTOCOL_VERSION,
        contract_payload=_contract_payload(),
    )

    assert repeated.id == first.id
    assert await service.list_contracts("system-kubernetes-contract-test") == [first]
    async with rdb_session_manager() as session:
        provider = await RuntimeProviderRepository().get_by_id(
            session,
            provider_id=provider_resource_id,
            for_update=False,
        )
    assert provider is not None
    assert provider.current_contract_revision_id == first.id
    assert provider.admin_version == 0
    assert provider.capabilities == first.contract


async def test_new_advertisement_moves_current_and_preserves_history(
    rdb_session_manager: SessionManager[AsyncSession],
) -> None:
    """Capability changes retain immutable history while replacing authority."""
    provider_resource_id = await _create_provider(rdb_session_manager)
    service = _service(rdb_session_manager)
    first = await service.propose_contract(
        provider_resource_id=provider_resource_id,
        provider_type="kubernetes",
        protocol_version=_PROTOCOL_VERSION,
        contract_payload=_contract_payload(),
    )
    changed_payload = _contract_payload()
    changed_payload["implementation_version"] = "0.1.1"
    latest = await service.propose_contract(
        provider_resource_id=provider_resource_id,
        provider_type="kubernetes",
        protocol_version=_PROTOCOL_VERSION,
        contract_payload=changed_payload,
    )

    assert latest.id != first.id
    assert await service.list_contracts("system-kubernetes-contract-test") == [
        latest,
        first,
    ]
    async with rdb_session_manager() as session:
        provider = await RuntimeProviderRepository().get_by_id(
            session,
            provider_id=provider_resource_id,
            for_update=False,
        )
    assert provider is not None
    assert provider.current_contract_revision_id == latest.id
    assert provider.capabilities["implementation_version"] == "0.1.1"


async def test_restored_advertisement_appends_new_revision(
    rdb_session_manager: SessionManager[AsyncSession],
) -> None:
    """Re-advertised historical content appends evidence instead of reactivating it."""
    provider_resource_id = await _create_provider(rdb_session_manager)
    service = _service(rdb_session_manager)
    original = await service.propose_contract(
        provider_resource_id=provider_resource_id,
        provider_type="kubernetes",
        protocol_version=_PROTOCOL_VERSION,
        contract_payload=_contract_payload(),
    )
    changed_payload = _contract_payload()
    changed_payload["implementation_version"] = "0.1.1"
    changed = await service.propose_contract(
        provider_resource_id=provider_resource_id,
        provider_type="kubernetes",
        protocol_version=_PROTOCOL_VERSION,
        contract_payload=changed_payload,
    )
    restored = await service.propose_contract(
        provider_resource_id=provider_resource_id,
        provider_type="kubernetes",
        protocol_version=_PROTOCOL_VERSION,
        contract_payload=_contract_payload(),
    )

    assert restored.id != original.id
    assert changed.id != restored.id
    assert restored.digest == original.digest
    assert await service.list_contracts("system-kubernetes-contract-test") == [
        restored,
        changed,
        original,
    ]
    async with rdb_session_manager() as session:
        provider = await RuntimeProviderRepository().get_by_id(
            session,
            provider_id=provider_resource_id,
            for_update=False,
        )
    assert provider is not None
    assert provider.current_contract_revision_id == restored.id
    assert provider.capabilities["implementation_version"] == "0.1.0"
    async with rdb_session_manager() as session:
        tasks = await RuntimeProfileRepository().claim_reconcile_tasks(
            session,
            available_before=datetime.datetime.now(datetime.UTC)
            + datetime.timedelta(seconds=1),
            reclaim_running_before=datetime.datetime.now(datetime.UTC)
            - datetime.timedelta(minutes=5),
            limit=10,
        )
    assert {task.source_version for task in tasks} == {
        original.id,
        changed.id,
        restored.id,
    }


async def test_advertisement_rejects_registration_contract_identity_mismatch(
    rdb_session_manager: SessionManager[AsyncSession],
) -> None:
    """Authenticated registration claims cannot substitute another implementation."""
    provider_resource_id = await _create_provider(rdb_session_manager)
    service = _service(rdb_session_manager)

    with pytest.raises(
        RuntimeProviderContractUnavailable,
        match="does not match registration",
    ) as raised:
        await service.propose_contract(
            provider_resource_id=provider_resource_id,
            provider_type="docker",
            protocol_version=_PROTOCOL_VERSION,
            contract_payload=_contract_payload(),
        )

    assert raised.value.code == "contract_identity_mismatch"


async def test_advertisement_rejects_invalid_profile_contract_declarations(
    rdb_session_manager: SessionManager[AsyncSession],
) -> None:
    """Duplicate Profile contract families fail before current authority moves."""
    provider_resource_id = await _create_provider(rdb_session_manager)
    service = _service(rdb_session_manager)
    invalid_payload = _contract_payload()
    declarations = invalid_payload["profile_contracts"]
    assert isinstance(declarations, list)
    declarations.append(dict(declarations[0]))

    with pytest.raises(RuntimeProviderContractUnavailable) as raised:
        await service.propose_contract(
            provider_resource_id=provider_resource_id,
            provider_type="kubernetes",
            protocol_version=_PROTOCOL_VERSION,
            contract_payload=invalid_payload,
        )

    assert raised.value.code == "contract_invalid"
    async with rdb_session_manager() as session:
        provider = await RuntimeProviderRepository().get_by_id(
            session,
            provider_id=provider_resource_id,
            for_update=False,
        )
    assert provider is not None
    assert provider.current_contract_revision_id is None
