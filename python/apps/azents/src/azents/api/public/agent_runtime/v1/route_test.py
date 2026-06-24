"""Agent Runtime v1 public route tests."""

from fastapi import FastAPI
from fastapi.routing import APIRoute

from azents.api.public.agent_runtime.v1 import mount
from azents.utils.fastapi.route import as_route_mounter


def _make_app() -> FastAPI:
    """Create a test app with Agent Runtime public endpoints mounted."""
    app = FastAPI()
    mount(as_route_mounter(app))
    return app


class TestRouteMount:
    """Test Agent Runtime v1 mount paths."""

    def test_mounts_agent_scoped_runtime_routes(self) -> None:
        """Mount lifecycle routes based on Agent ID."""
        app = _make_app()

        paths = {route.path for route in app.routes if isinstance(route, APIRoute)}

        assert (
            "/agent-runtime/v1/workspaces/{handle}/agents/{agent_id}/runtime" in paths
        )
        assert (
            "/agent-runtime/v1/workspaces/{handle}/agents/{agent_id}/runtime/start"
            in paths
        )
        assert (
            "/agent-runtime/v1/workspaces/{handle}/agents/{agent_id}/runtime/reset"
            in paths
        )
