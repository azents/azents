"""Workspace Runtime Provider discovery tests."""

import datetime
from typing import Any, cast
from unittest.mock import AsyncMock, Mock

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
from azents.repos.runtime_provider.data import RuntimeProvider

from .service import RuntimeProviderPublicService

_NOW = datetime.datetime.now(datetime.timezone.utc)


def _provider(
    provider_id: str,
    *,
    lifecycle_state: RuntimeProviderLifecycleState = (
        RuntimeProviderLifecycleState.ACTIVE
    ),
    availability_mode: RuntimeProviderAvailabilityMode = (
        RuntimeProviderAvailabilityMode.PLATFORM_WIDE
    ),
) -> RuntimeProvider:
    """Build a discovery fixture."""
    return RuntimeProvider(
        id=f"resource-{provider_id}",
        provider_id=provider_id,
        scope=RuntimeProviderScope.SYSTEM,
        workspace_id=None,
        kind=RuntimeProviderKind.KUBERNETES,
        display_name=provider_id,
        registration_method=RuntimeProviderRegistrationMethod.ADMIN,
        enabled=True,
        lifecycle_state=lifecycle_state,
        availability_mode=availability_mode,
        accepted_contract_revision_id="contract-1",
        active_config_revision_id=None,
        admin_version=1,
        capabilities={},
        config_schema=None,
        metadata=None,
        created_at=_NOW,
        updated_at=_NOW,
    )


def _service(providers: list[RuntimeProvider]) -> RuntimeProviderPublicService:
    """Build the discovery service with repository mocks."""
    repository = cast(Any, Mock())
    repository.list_available = AsyncMock(return_value=providers)
    repository.is_available_to_workspace = AsyncMock(return_value=True)
    return RuntimeProviderPublicService(
        session_manager=cast(SessionManager[AsyncSession], Mock()),
        repository=repository,
    )


@pytest.mark.asyncio
async def test_discovery_excludes_non_active_lifecycle_states() -> None:
    """Decommissioned Providers are not offered as new preference options."""
    service = _service(
        [
            _provider("active"),
            _provider(
                "decommissioning",
                lifecycle_state=RuntimeProviderLifecycleState.DECOMMISSIONING,
            ),
            _provider(
                "retired",
                lifecycle_state=RuntimeProviderLifecycleState.FORCE_RETIRED,
            ),
        ]
    )
    session = Mock()
    context = Mock()
    context.__aenter__ = AsyncMock(return_value=session)
    context.__aexit__ = AsyncMock(return_value=None)
    service.session_manager = cast(Any, Mock(return_value=context))

    providers = await service.list_for_workspace("workspace-1")

    assert [provider.provider_id for provider in providers] == ["active"]


@pytest.mark.asyncio
async def test_discovery_applies_selected_workspace_allow_list() -> None:
    """Selected-Workspace Providers are omitted outside their allow-list."""
    allowed = _provider(
        "allowed",
        availability_mode=RuntimeProviderAvailabilityMode.SELECTED_WORKSPACES,
    )
    blocked = _provider(
        "blocked",
        availability_mode=RuntimeProviderAvailabilityMode.SELECTED_WORKSPACES,
    )
    service = _service([allowed, blocked])
    service.repository.is_available_to_workspace = AsyncMock(
        side_effect=lambda _session, **kwargs: kwargs["provider_id"] == allowed.id
    )
    session = Mock()
    context = Mock()
    context.__aenter__ = AsyncMock(return_value=session)
    context.__aexit__ = AsyncMock(return_value=None)
    service.session_manager = cast(Any, Mock(return_value=context))

    providers = await service.list_for_workspace("workspace-1")

    assert [provider.provider_id for provider in providers] == ["allowed"]
