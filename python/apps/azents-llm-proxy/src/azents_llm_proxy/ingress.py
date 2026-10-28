"""Outer request scope and operation closure around the genuine Proxy ASGI app."""

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

        async def bounded_receive() -> Message:
            nonlocal buffered
            if buffered is not None:
                request = buffered
                buffered = None
                return request
            return await receive()

        async with self.context.request_scope():
            await self.app(scope, bounded_receive, send)
