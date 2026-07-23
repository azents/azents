"""Runtime Provider discovery v1 Public API tests."""

from fastapi import FastAPI
from fastapi.routing import APIRoute

from azents.api.public.runtime_provider.v1 import mount
from azents.utils.fastapi.route import as_route_mounter


def test_mounts_workspace_provider_discovery_route() -> None:
    """Expose Workspace-scoped Provider discovery under the Public API."""
    app = FastAPI()
    mount(as_route_mounter(app))

    paths = {route.path for route in app.routes if isinstance(route, APIRoute)}

    assert "/runtime-provider/v1/workspaces/{handle}/providers" in paths
