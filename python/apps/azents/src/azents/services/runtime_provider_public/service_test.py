"""Workspace Runtime Provider discovery service tests."""

from unittest.mock import AsyncMock, Mock

from azents.repos.runtime_provider.discovery import RuntimeProviderDiscoveryRepository
from azents.services.runtime_provider_public.service import RuntimeProviderPublicService


async def test_discovery_delegates_the_complete_repository_operation() -> None:
    """The service opens no session and preserves completed repository results."""
    repository = Mock(spec=RuntimeProviderDiscoveryRepository)
    providers = []
    repository.list_for_workspace = AsyncMock(return_value=providers)
    service = RuntimeProviderPublicService(repository=repository)

    assert await service.list_for_workspace("workspace-1") is providers
    repository.list_for_workspace.assert_awaited_once_with("workspace-1")
