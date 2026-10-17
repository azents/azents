"""Fresh real Chat route apps for focused HTTP contract tests."""

from fastapi import APIRouter, FastAPI
from fastapi.routing import APIRoute

from azents.api.public.chat.v1 import router
from azents.utils.fastapi.route import generate_short_operation_id


def focused_chat_app(path: str) -> FastAPI:
    """Retain every method of the selected production path and its dependencies."""
    routes = [
        route
        for route in router.routes
        if isinstance(route, APIRoute) and route.path == path
    ]
    assert routes, f"The production Chat route is missing: {path}"
    focused = APIRouter()
    focused.routes.extend(routes)
    app = FastAPI(generate_unique_id_function=generate_short_operation_id)
    app.include_router(focused, prefix="/chat/v1", tags=["Chat v1"])
    return app
