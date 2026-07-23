"""Runtime Provider selection service tests."""

import datetime
from typing import Any, cast
from unittest.mock import AsyncMock, Mock

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from azents.core.enums import (
    RuntimeProviderAvailabilityMode,
    RuntimeProviderBindingOrigin,
    RuntimeProviderConfigRevisionState,
    RuntimeProviderConfigValidationStatus,
    RuntimeProviderContractStatus,
    RuntimeProviderKind,
    RuntimeProviderLifecycleState,
    RuntimeProviderRegistrationMethod,
    RuntimeProviderScope,
)
from azents.rdb.session import SessionManager
from azents.repos.runtime_provider.data import RuntimeProvider
from azents.repos.runtime_provider_policy.data import (
    RuntimeProviderConfigRevision,
    RuntimeProviderContractRevision,
)

from .data import RuntimeProviderSelectionUnavailable
from .service import RuntimeProviderSelectionService

_NOW = datetime.datetime.now(datetime.timezone.utc)


def _provider(*, capabilities: dict[str, Any] | None = None) -> RuntimeProvider:
    """Build a valid system Provider aggregate for unit tests."""
    return RuntimeProvider(
        id="provider-resource",
        provider_id="system-kubernetes",
        scope=RuntimeProviderScope.SYSTEM,
        workspace_id=None,
        kind=RuntimeProviderKind.KUBERNETES,
        display_name="Kubernetes",
        registration_method=RuntimeProviderRegistrationMethod.ADMIN,
        enabled=True,
        lifecycle_state=RuntimeProviderLifecycleState.ACTIVE,
        availability_mode=RuntimeProviderAvailabilityMode.PLATFORM_WIDE,
        accepted_contract_revision_id="contract-1",
        active_config_revision_id=None,
        admin_version=1,
        capabilities=capabilities or {"optional_capabilities": ["files"]},
        config_schema=None,
        metadata=None,
        created_at=_NOW,
        updated_at=_NOW,
    )


def _contract(
    *, provider_id: str = "provider-resource"
) -> RuntimeProviderContractRevision:
    """Build an accepted lifecycle contract."""
    return RuntimeProviderContractRevision(
        id="contract-1",
        provider_id=provider_id,
        digest="a" * 64,
        implementation_version="1",
        protocol_version="1",
        contract={
            "schema_version": 1,
            "implementation_key": "kubernetes",
            "implementation_version": "1",
            "protocol_version": "1",
            "core_lifecycle_operations": [
                "start",
                "stop",
                "restart",
                "reset",
                "observe",
                "terminal_delete",
            ],
            "persistence": {
                "kind": "persistent",
                "reset_destroys_workspace": False,
                "terminal_delete_destroys_workspace": True,
            },
            "configuration_fields": [],
        },
        compatibility={},
        status=RuntimeProviderContractStatus.ACCEPTED,
        validation_code=None,
        validation_message=None,
        accepted_by_user_id=None,
        accepted_at=_NOW,
        rejected_by_user_id=None,
        rejected_at=None,
        created_at=_NOW,
    )


def _service() -> RuntimeProviderSelectionService:
    """Build a selection service with mocked collaborators."""
    return RuntimeProviderSelectionService(
        session_manager=cast(SessionManager[AsyncSession], Mock()),
        agent_repository=cast(Any, Mock()),
        runtime_repository=cast(Any, Mock()),
        provider_repository=cast(Any, Mock()),
        control_repository=cast(Any, Mock()),
        policy_repository=cast(Any, Mock()),
        system_setting_repository=cast(Any, Mock()),
    )


@pytest.mark.asyncio
async def test_explicit_candidate_does_not_read_platform_default() -> None:
    """An Agent preference wins without consulting the Platform default."""
    service = _service()
    service.system_setting_repository.get_current = AsyncMock()

    selected_id, origin = await service.resolve_candidate_id(
        cast(AsyncSession, Mock()),
        agent_runtime_provider_id="agent-provider",
        requested_provider_id=None,
    )

    assert selected_id == "agent-provider"
    assert origin is RuntimeProviderBindingOrigin.AGENT_EXPLICIT
    service.system_setting_repository.get_current.assert_not_awaited()


@pytest.mark.asyncio
async def test_missing_platform_default_is_explicitly_unavailable() -> None:
    """No environment fallback is used when the Platform default is absent."""
    service = _service()
    service.system_setting_repository.get_current = AsyncMock(return_value=None)

    with pytest.raises(RuntimeProviderSelectionUnavailable) as raised:
        await service.resolve_candidate_id(
            cast(AsyncSession, Mock()),
            agent_runtime_provider_id=None,
            requested_provider_id=None,
        )

    assert raised.value.code == "platform_default_unset"


@pytest.mark.asyncio
async def test_capability_mismatch_is_not_fallback() -> None:
    """An exact Provider that lacks a required capability is rejected."""
    service = _service()
    service.control_repository.has_connected_connection = AsyncMock(return_value=True)
    provider = _provider(capabilities={"optional_capabilities": ["files"]})

    with pytest.raises(RuntimeProviderSelectionUnavailable) as raised:
        await service.validate_provider_candidate(
            cast(AsyncSession, Mock()),
            provider_logical_id=provider.provider_id,
            provider=provider,
            workspace_id="workspace-1",
            required_capabilities={"git"},
        )

    assert raised.value.code == "provider_capability_mismatch"


@pytest.mark.asyncio
async def test_contract_and_config_must_match_bound_provider() -> None:
    """Provider pointers cannot authorize revisions belonging to another resource."""
    service = _service()
    service.control_repository.has_connected_connection = AsyncMock(return_value=True)
    service.policy_repository.get_contract_by_id = AsyncMock(
        return_value=_contract(provider_id="different-provider")
    )
    provider = _provider()

    with pytest.raises(RuntimeProviderSelectionUnavailable) as raised:
        await service.validate_provider_candidate(
            cast(AsyncSession, Mock()),
            provider_logical_id=provider.provider_id,
            provider=provider,
            workspace_id="workspace-1",
            required_capabilities=None,
        )

    assert raised.value.code == "provider_contract_unaccepted"


@pytest.mark.asyncio
async def test_active_configuration_requires_valid_matching_revision() -> None:
    """A stale or invalid active configuration cannot enter a Runtime snapshot."""
    service = _service()
    service.control_repository.has_connected_connection = AsyncMock(return_value=True)
    contract = _contract()
    contract.contract["configuration_fields"] = [
        {
            "name": "region",
            "scope": "platform",
            "type": "string",
            "application_impact": "immediate",
        }
    ]
    service.policy_repository.get_contract_by_id = AsyncMock(return_value=contract)
    service.policy_repository.get_active_config = AsyncMock(
        return_value=RuntimeProviderConfigRevision(
            id="config-1",
            provider_id="provider-resource",
            revision=1,
            base_revision_id=None,
            contract_revision_id="different-contract",
            config={"region": "us-east-1"},
            encrypted_secrets=None,
            secret_metadata={},
            state=RuntimeProviderConfigRevisionState.ACTIVE,
            validation_status=RuntimeProviderConfigValidationStatus.VALID,
            validation_request_id=None,
            validation_code=None,
            validation_message=None,
            validation_metadata=None,
            impact=None,
            created_by_user_id=None,
            activated_by_user_id=None,
            activated_at=_NOW,
            created_at=_NOW,
            updated_at=_NOW,
        )
    )

    with pytest.raises(RuntimeProviderSelectionUnavailable) as raised:
        await service.validate_provider_candidate(
            cast(AsyncSession, Mock()),
            provider_logical_id="system-kubernetes",
            provider=_provider(),
            workspace_id="workspace-1",
            required_capabilities=None,
        )

    assert raised.value.code == "provider_configuration_unavailable"
