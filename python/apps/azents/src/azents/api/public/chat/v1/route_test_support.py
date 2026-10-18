"""Fresh real Chat route apps for focused HTTP contract tests."""

from fastapi import APIRouter, FastAPI
from fastapi.routing import APIRoute

from azents.api.public.chat.v1 import router
from azents.utils.fastapi.route import generate_short_operation_id


def focused_chat_app(*paths: str) -> FastAPI:
    """Retain every method of selected production paths and their dependencies."""
    assert paths, "At least one production Chat path must be selected"
    routes = [
        route
        for route in router.routes
        if isinstance(route, APIRoute) and route.path in paths
    ]
    for path in paths:
        assert any(route.path == path for route in routes), (
            f"The production Chat route is missing: {path}"
        )
    focused = APIRouter()
    focused.routes.extend(routes)
    app = FastAPI(generate_unique_id_function=generate_short_operation_id)
    app.include_router(focused, prefix="/chat/v1", tags=["Chat v1"])
    return app
