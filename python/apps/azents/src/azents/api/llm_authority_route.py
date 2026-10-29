"""Secret-safe error boundary shared by inference authority HTTP surfaces."""

from collections.abc import Callable, Coroutine
from typing import Any

from fastapi import Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.routing import APIRoute
from starlette.responses import JSONResponse

from azents.core.llm_access import LLMAccessDenied, LLMTargetDenied, LLMTokenConflict


class LLMAuthorityRoute(APIRoute):
    """Never echo validation inputs, including unknown secret-bearing fields."""

    def get_route_handler(self) -> Callable[[Request], Coroutine[Any, Any, Response]]:
        original = super().get_route_handler()

        async def handler(request: Request) -> Response:
            try:
                response = await original(request)
            except RequestValidationError:
                response = JSONResponse(
                    status_code=422, content={"detail": "Invalid authority request."}
                )
            except LLMAccessDenied:
                response = JSONResponse(
                    status_code=401,
                    content={"detail": "Inference credential is unavailable."},
                )
            except LLMTargetDenied:
                response = JSONResponse(
                    status_code=403, content={"detail": "Target is not authorized."}
                )
            except LLMTokenConflict:
                response = JSONResponse(
                    status_code=409,
                    content={
                        "detail": "Supply state changed; inspect before replacing."
                    },
                )
            response.headers["Cache-Control"] = "no-store"
            return response

        return handler
