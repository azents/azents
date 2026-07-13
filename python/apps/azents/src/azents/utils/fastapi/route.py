"""Route mounting utilities."""

import logging
import re
from collections.abc import Sequence
from typing import Protocol

from fastapi import APIRouter, FastAPI, params
from fastapi.routing import APIRoute

logger = logging.getLogger(__name__)


def generate_short_operation_id(route: APIRoute) -> str:
    """Create short operationId within 60 characters.

    Google ADK OpenAPIToolset limits tool names to 60 characters.
    Default FastAPI generation pattern ({function}_{path}_{method}) is too long
    and causes tool names to be truncated.

    This function combines tag and function name to create short meaningful operationId.
    Example: "Health v1" tag + "readiness" function → "health_v1_readiness"

    :param route: FastAPI route object
    :return: operationId within 60 characters
    """
    # Extract prefix from tag (e.g. "Health v1" → "health_v1")
    tag_prefix = ""
    if route.tags:
        tag = str(route.tags[0])
        # Convert to snake_case
        tag_prefix = re.sub(r"[^a-zA-Z0-9]+", "_", tag).lower().strip("_")

    # Function name
    func_name = route.name

    # Combine
    if tag_prefix:
        operation_id = f"{tag_prefix}_{func_name}"
    else:
        operation_id = func_name

    # Warn when exceeding 60 characters (for development-time check)
    if len(operation_id) > 60:
        logger.warning(
            "operationId '%s' exceeds 60 chars (%d). "
            "Consider shortening the function name.",
            operation_id,
            len(operation_id),
        )

    return operation_id


class RouteMounter(Protocol):
    """Function protocol mounting APIRouter."""

    def __call__(
        self,
        router: APIRouter,
        *,
        prefix: str,
        tag: str,
        description: str | None = None,
        dependencies: Sequence[params.Depends] | None = None,
    ) -> None: ...


def as_route_mounter(app: FastAPI) -> RouteMounter:
    """Convert FastAPI app to RouteMounter."""

    def mounter(
        router: APIRouter,
        *,
        prefix: str,
        tag: str,
        description: str | None = None,
        dependencies: Sequence[params.Depends] | None = None,
    ) -> None:
        app.include_router(
            router,
            prefix=prefix,
            tags=[tag],
            dependencies=dependencies,
        )
        app.openapi_tags = [
            *(app.openapi_tags or []),
            {
                "name": tag,
                "description": description,
            },
        ]

    return mounter
