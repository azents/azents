"""Google creation visibility without changing the executable provider registry."""

from typing import Any
from unittest.mock import create_autospec

import pytest

from azents.api.public.toolkit.v1 import list_toolkits
from azents.core.tools import ToolkitProvider
from azents.engine.tools.brave_search import BraveSearchToolkitProvider
from azents.engine.tools.google import GoogleToolkitProvider
from azents.repos.engine_tool_repositories import EngineMcpSnapshotFactory
from azents.services.artifact import ArtifactService
from azents.services.google_application.service import GoogleApplicationService
from azents.services.google_oauth.runtime import GoogleRuntimeService


@pytest.mark.asyncio
@pytest.mark.parametrize("available", [False, True])
async def test_catalog_filters_google_creation_only(available: bool) -> None:
    google = GoogleToolkitProvider(
        create_autospec(GoogleRuntimeService, instance=True),
        create_autospec(EngineMcpSnapshotFactory, instance=True),
        create_autospec(ArtifactService, instance=True),
    )
    brave = BraveSearchToolkitProvider(transport=None)
    registry: dict[str, ToolkitProvider[Any]] = {
        "google": google,
        "brave_search": brave,
    }
    application = create_autospec(GoogleApplicationService, instance=True)
    application.creation_available.return_value = available
    output = await list_toolkits(registry, application)
    assert [item.slug for item in output.items] == (
        ["google", "brave_search"] if available else ["brave_search"]
    )
    assert registry["google"] is google
    application.creation_available.assert_awaited_once_with()
    assert "client_secret" not in output.model_dump_json()
