"""Runtime Provider capability contract lifecycle tests."""

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from azents.core.enums import (
    RuntimeProviderAvailabilityMode,
    RuntimeProviderContractStatus,
    RuntimeProviderKind,
    RuntimeProviderLifecycleState,
    RuntimeProviderRegistrationMethod,
    RuntimeProviderScope,
)
from azents.rdb.session import SessionManager
from azents.repos.runtime_provider.data import RuntimeProviderCreate
from azents.repos.runtime_provider.repository import RuntimeProviderRepository
from azents.repos.runtime_provider_policy.repository import (
    RuntimeProviderPolicyRepository,
)
from azents.repos.user import UserRepository
from azents.repos.user.data import UserCreate

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
    }


async def _create_provider_and_admin(
    session_manager: SessionManager[AsyncSession],
) -> tuple[str, str]:
    """Create the durable Provider and Admin actor used by lifecycle tests."""
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
        user = await UserRepository().create(
            session,
            UserCreate(email="runtime-contract-admin@example.com"),
        )
    return provider.id, user.id


def _service(
    session_manager: SessionManager[AsyncSession],
) -> RuntimeProviderContractService:
    """Build the production contract service."""
    return RuntimeProviderContractService(
        session_manager=session_manager,
        provider_repository=RuntimeProviderRepository(),
        policy_repository=RuntimeProviderPolicyRepository(),
    )


async def test_provider_proposal_is_idempotent_and_admin_accepts_explicitly(
    rdb_session_manager: SessionManager[AsyncSession],
) -> None:
    """Registration creates one candidate and acceptance advances the Provider."""
    provider_resource_id, actor_user_id = await _create_provider_and_admin(
        rdb_session_manager
    )
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
    assert first.status is RuntimeProviderContractStatus.CANDIDATE
    assert first.accepted_at is None
    listed = await service.list_contracts("system-kubernetes-contract-test")
    assert [contract.id for contract in listed] == [first.id]

    accepted = await service.accept_contract(
        "system-kubernetes-contract-test",
        first.id,
        expected_admin_version=0,
        actor_user_id=actor_user_id,
    )

    assert accepted.status is RuntimeProviderContractStatus.ACCEPTED
    assert accepted.accepted_by_user_id == actor_user_id
    assert accepted.accepted_at is not None
    async with rdb_session_manager() as session:
        provider = await RuntimeProviderRepository().get_by_id(
            session,
            provider_id=provider_resource_id,
            for_update=False,
        )
    assert provider is not None
    assert provider.accepted_contract_revision_id == first.id
    assert provider.admin_version == 1
    assert provider.capabilities["optional_capabilities"] == ["execution_policy_v1"]


async def test_accept_rejects_stale_provider_version(
    rdb_session_manager: SessionManager[AsyncSession],
) -> None:
    """Contract acceptance cannot overwrite a concurrently changed Provider."""
    provider_resource_id, actor_user_id = await _create_provider_and_admin(
        rdb_session_manager
    )
    service = _service(rdb_session_manager)
    candidate = await service.propose_contract(
        provider_resource_id=provider_resource_id,
        provider_type="kubernetes",
        protocol_version=_PROTOCOL_VERSION,
        contract_payload=_contract_payload(),
    )

    with pytest.raises(
        RuntimeProviderContractUnavailable,
        match="changed before contract acceptance",
    ) as raised:
        await service.accept_contract(
            "system-kubernetes-contract-test",
            candidate.id,
            expected_admin_version=3,
            actor_user_id=actor_user_id,
        )

    assert raised.value.code == "stale_provider_version"
    assert raised.value.current_admin_version == 0


async def test_only_latest_contract_proposal_can_be_accepted(
    rdb_session_manager: SessionManager[AsyncSession],
) -> None:
    """A stale candidate cannot replace a newer Provider contract."""
    provider_resource_id, actor_user_id = await _create_provider_and_admin(
        rdb_session_manager
    )
    service = _service(rdb_session_manager)
    first = await service.propose_contract(
        provider_resource_id=provider_resource_id,
        provider_type="kubernetes",
        protocol_version=_PROTOCOL_VERSION,
        contract_payload=_contract_payload(),
    )
    latest_payload = _contract_payload()
    latest_payload["implementation_version"] = "0.1.1"
    latest = await service.propose_contract(
        provider_resource_id=provider_resource_id,
        provider_type="kubernetes",
        protocol_version=_PROTOCOL_VERSION,
        contract_payload=latest_payload,
    )

    listed = await service.list_contracts("system-kubernetes-contract-test")
    assert [(item.id, item.status) for item in listed] == [
        (latest.id, RuntimeProviderContractStatus.CANDIDATE),
    ]
    with pytest.raises(RuntimeProviderContractUnavailable) as raised:
        await service.accept_contract(
            "system-kubernetes-contract-test",
            first.id,
            expected_admin_version=0,
            actor_user_id=actor_user_id,
        )

    assert raised.value.code == "contract_not_acceptable"
    accepted = await service.accept_contract(
        "system-kubernetes-contract-test",
        latest.id,
        expected_admin_version=0,
        actor_user_id=actor_user_id,
    )
    assert accepted.status is RuntimeProviderContractStatus.ACCEPTED


async def test_new_proposal_deletes_older_never_accepted_contracts(
    rdb_session_manager: SessionManager[AsyncSession],
) -> None:
    """Only the current never-accepted proposal remains an approval target."""
    provider_resource_id, _actor_user_id = await _create_provider_and_admin(
        rdb_session_manager
    )
    service = _service(rdb_session_manager)
    first = await service.propose_contract(
        provider_resource_id=provider_resource_id,
        provider_type="kubernetes",
        protocol_version=_PROTOCOL_VERSION,
        contract_payload=_contract_payload(),
    )
    latest_payload = _contract_payload()
    latest_payload["implementation_version"] = "0.1.1"
    latest = await service.propose_contract(
        provider_resource_id=provider_resource_id,
        provider_type="kubernetes",
        protocol_version=_PROTOCOL_VERSION,
        contract_payload=latest_payload,
    )

    assert latest.id != first.id
    assert await service.list_contracts("system-kubernetes-contract-test") == [latest]


async def test_current_provider_contract_is_reproposed_after_drift(
    rdb_session_manager: SessionManager[AsyncSession],
) -> None:
    """A previously superseded digest becomes a new candidate when advertised again."""
    provider_resource_id, actor_user_id = await _create_provider_and_admin(
        rdb_session_manager
    )
    service = _service(rdb_session_manager)
    original_payload = _contract_payload()
    original = await service.propose_contract(
        provider_resource_id=provider_resource_id,
        provider_type="kubernetes",
        protocol_version=_PROTOCOL_VERSION,
        contract_payload=original_payload,
    )
    await service.accept_contract(
        "system-kubernetes-contract-test",
        original.id,
        expected_admin_version=0,
        actor_user_id=actor_user_id,
    )

    drifted_payload = _contract_payload()
    drifted_payload["implementation_version"] = "0.1.1"
    drifted = await service.propose_contract(
        provider_resource_id=provider_resource_id,
        provider_type="kubernetes",
        protocol_version=_PROTOCOL_VERSION,
        contract_payload=drifted_payload,
    )
    await service.accept_contract(
        "system-kubernetes-contract-test",
        drifted.id,
        expected_admin_version=1,
        actor_user_id=actor_user_id,
    )

    reproposed = await service.propose_contract(
        provider_resource_id=provider_resource_id,
        provider_type="kubernetes",
        protocol_version=_PROTOCOL_VERSION,
        contract_payload=original_payload,
    )
    repeated = await service.propose_contract(
        provider_resource_id=provider_resource_id,
        provider_type="kubernetes",
        protocol_version=_PROTOCOL_VERSION,
        contract_payload=original_payload,
    )

    assert reproposed.id != original.id
    assert repeated.id == reproposed.id
    assert reproposed.status is RuntimeProviderContractStatus.CANDIDATE
    listed = await service.list_contracts("system-kubernetes-contract-test")
    assert listed[0].id == reproposed.id
    assert listed[1].id == drifted.id
    assert listed[1].status is RuntimeProviderContractStatus.ACCEPTED
    assert listed[-1].id == original.id
    assert listed[-1].status is RuntimeProviderContractStatus.SUPERSEDED

    accepted = await service.accept_contract(
        "system-kubernetes-contract-test",
        reproposed.id,
        expected_admin_version=2,
        actor_user_id=actor_user_id,
    )
    assert accepted.status is RuntimeProviderContractStatus.ACCEPTED


async def test_proposal_rejects_registration_contract_identity_mismatch(
    rdb_session_manager: SessionManager[AsyncSession],
) -> None:
    """Authenticated registration claims cannot substitute another implementation."""
    provider_resource_id, _actor_user_id = await _create_provider_and_admin(
        rdb_session_manager
    )
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
