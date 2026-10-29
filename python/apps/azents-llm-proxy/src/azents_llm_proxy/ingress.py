"""Outer request scope and operation closure around the genuine Proxy ASGI app."""

import asyncio

from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from azents_llm_proxy.context import RequestContext

_MAX_BODY = 32 * 1024 * 1024


class AgentIngress:
    def __init__(self, app: ASGIApp, context: RequestContext) -> None:
        self.app = app
        self.context = context

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            if scope["type"] == "websocket":
                await send({"type": "websocket.close", "code": 1008})
                return
            await self.app(scope, receive, send)
            return
        operation = (scope["method"], scope["path"])
        allowed = operation in {("POST", "/v1/responses"), ("GET", "/v1/models")}
        readiness = operation == ("GET", "/health/liveliness")
        headers = scope.get("headers", ())
        bearer = any(name.lower() == b"authorization" for name, _ in headers)
        if scope.get("query_string") or not (allowed or (readiness and not bearer)):
            await JSONResponse(
                {
                    "error": {
                        "message": "Operation is not available.",
                        "type": "permission_error",
                    }
                },
                status_code=403,
            )(scope, receive, send)
            return
        body = bytearray()
        while True:
            message = await receive()
            if message["type"] == "http.disconnect":
                return
            if message["type"] == "http.request":
                fragment = message.get("body", b"")
                if len(body) + len(fragment) > _MAX_BODY:
                    await JSONResponse(
                        {
                            "error": {
                                "message": "Inline request content is too large.",
                                "type": "invalid_request_error",
                            }
                        },
                        status_code=413,
                    )(scope, receive, send)
                    return
                body.extend(fragment)
                if not message.get("more_body", False):
                    break
        buffered: Message | None = {
            "type": "http.request",
            "body": bytes(body),
            "more_body": False,
        }
        body.clear()

        disconnected = False
        cancelled = False
        status: int | None = None
        delivered = False

        async def bounded_receive() -> Message:
            nonlocal buffered, disconnected
            if buffered is not None:
                request = buffered
                buffered = None
                return request
            message = await receive()
            if message["type"] == "http.disconnect" and not delivered:
                disconnected = True
            return message

        async def observed_send(message: Message) -> None:
            nonlocal status, delivered, disconnected
            try:
                await send(message)
            except asyncio.CancelledError:
                raise
            except OSError:
                disconnected = True
                raise
            if message["type"] == "http.response.start":
                status = message["status"]
            elif message["type"] == "http.response.body" and not message.get(
                "more_body", False
            ):
                delivered = True

        async with self.context.request_scope() as state:
            try:
                await self.app(scope, bounded_receive, observed_send)
            except asyncio.CancelledError:
                cancelled = True
                raise
            finally:
                if state.operation is not None:
                    state.operation.finish(
                        disconnected=disconnected,
                        cancelled=cancelled,
                        status=status,
                        delivered=delivered,
                    )
