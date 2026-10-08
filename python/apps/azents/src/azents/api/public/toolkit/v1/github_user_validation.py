"""Keep transient OAuth credential inputs out of public validation failures."""

from collections.abc import Callable, Coroutine
from typing import Any

from fastapi import HTTPException, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.routing import APIRoute


class GitHubUserRoute(APIRoute):
    """Scope sanitized request errors to the GitHub user authorization endpoints."""

    def get_route_handler(self) -> Callable[[Request], Coroutine[Any, Any, Response]]:
        handler = super().get_route_handler()

        async def safe_handler(request: Request) -> Response:
            try:
                return await handler(request)
            except RequestValidationError:
                raise HTTPException(
                    status_code=422,
                    detail=[
                        {
                            "type": "value_error",
                            "loc": ["body"],
                            "msg": "Invalid GitHub user authorization request.",
                        }
                    ],
                ) from None

        return safe_handler
