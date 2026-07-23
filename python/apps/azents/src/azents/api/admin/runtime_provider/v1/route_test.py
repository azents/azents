"""Runtime Provider inventory v1 Admin API tests."""

from fastapi import FastAPI
from fastapi.routing import APIRoute

from azents.api.admin.runtime_provider.v1 import mount
from azents.utils.fastapi.route import as_route_mounter


def test_mounts_runtime_provider_inventory_routes() -> None:
    """Expose inventory, policy, and availability routes under Admin API."""
    app = FastAPI()
    mount(as_route_mounter(app))

    paths = {route.path for route in app.routes if isinstance(route, APIRoute)}

    assert "/runtime-provider/v1/providers" in paths
    assert "/runtime-provider/v1/providers/{provider_id}" in paths
    assert "/runtime-provider/v1/providers/{provider_id}/policy" in paths
    assert "/runtime-provider/v1/providers/{provider_id}/availability" in paths
