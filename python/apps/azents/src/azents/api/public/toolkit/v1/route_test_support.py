"""Fresh production Toolkit paths for focused native HTTP contracts."""

from fastapi import APIRouter, FastAPI
from fastapi.routing import APIRoute

from azents.utils.fastapi.route import generate_short_operation_id


def focused_toolkit_app(*selections: tuple[APIRouter, str]) -> FastAPI:
    """Preserve actual selected route types, methods and dependencies."""
    focused = APIRouter()
    for router, suffix in selections:
        routes = [
            route
            for route in router.routes
            if isinstance(route, APIRoute) and route.path.endswith(suffix)
        ]
        assert routes, f"The production Toolkit path is missing: {suffix}"
        focused.routes.extend(routes)
    app = FastAPI(generate_unique_id_function=generate_short_operation_id)
    app.include_router(focused)
    return app
