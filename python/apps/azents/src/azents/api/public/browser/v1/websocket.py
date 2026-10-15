"""First-message identity admission for the public Session Browser WebSocket."""

import asyncio
import json
from typing import Annotated

from azents_runtime_control.browser_viewer_contract import ViewerTarget
from fastapi import APIRouter, Depends, WebSocket, WebSocketDisconnect
from pydantic import ValidationError
from starlette.websockets import WebSocketState

from azents.api.public.browser.v1.data import BrowserAttachRequest
from azents.core.auth.jwt import InvalidTokenError, verify_ws_ticket
from azents.core.config import AuthConfig
from azents.core.deps import get_auth_config
from azents.services.runtime_browser.data import RuntimeBrowserResource
from azents.services.runtime_browser.deps import (
    get_runtime_browser_socket_service,
    get_runtime_browser_web_origin,
)
from azents.services.runtime_browser.socket import (
    BROWSER_WEBSOCKET_SUBPROTOCOL,
    BrowserSocketFailure,
    RuntimeBrowserSocketService,
    unique_json_object,
)

router = APIRouter()
_MAX_ATTACH_BYTES = 8192


async def _receive_attach(websocket: WebSocket) -> BrowserAttachRequest:
    message = await websocket.receive()
    if message["type"] == "websocket.disconnect":
        raise WebSocketDisconnect()
    text = message.get("text")
    if message["type"] != "websocket.receive" or not isinstance(text, str):
        raise BrowserSocketFailure(4400, "Browser attach text is required")
    if len(text.encode()) > _MAX_ATTACH_BYTES:
        raise BrowserSocketFailure(4429, "Browser attach exceeds its bound")
    try:
        json.loads(text, object_pairs_hook=unique_json_object)
        return BrowserAttachRequest.model_validate_json(text)
    except ValueError, ValidationError:
        raise BrowserSocketFailure(4400, "Invalid Browser attach") from None


@router.websocket("/workspaces/{handle}/agents/{agent_id}/sessions/{session_id}/ws")
async def browser_websocket(
    websocket: WebSocket,
    handle: str,
    agent_id: str,
    session_id: str,
    auth_config: Annotated[AuthConfig, Depends(get_auth_config)],
    expected_origin: Annotated[str, Depends(get_runtime_browser_web_origin)],
    service: Annotated[
        RuntimeBrowserSocketService, Depends(get_runtime_browser_socket_service)
    ],
) -> None:
    """Authenticate identity inside attach; no credential URL or scope resumption."""
    query_present = bool(websocket.scope.get("query_string"))
    websocket.scope["query_string"] = b""
    if query_present:
        await websocket.close(
            code=4400, reason="Browser URL credentials are not accepted"
        )
        return
    if websocket.headers.get("origin") != expected_origin:
        await websocket.close(code=4403, reason="Browser origin is not allowed")
        return
    if BROWSER_WEBSOCKET_SUBPROTOCOL not in websocket.scope.get("subprotocols", []):
        await websocket.close(code=4400, reason="Browser subprotocol is required")
        return
    await websocket.accept(subprotocol=BROWSER_WEBSOCKET_SUBPROTOCOL)
    try:
        try:
            async with asyncio.timeout(10):
                attach = await _receive_attach(websocket)
        except TimeoutError:
            raise BrowserSocketFailure(4408, "Browser attach timed out") from None
        try:
            identity = verify_ws_ticket(auth_config.jwt, attach.ticket)
        except InvalidTokenError:
            raise BrowserSocketFailure(
                4401, "Browser identity is not authenticated"
            ) from None
        target = ViewerTarget(
            attach.target.task_id,
            attach.target.page_id,
            attach.target.resource_incarnation,
        )
        del attach
        await service.serve(
            socket=websocket,
            resource=RuntimeBrowserResource(handle, agent_id, session_id),
            user_id=identity.user_id,
            authentication_session_id=identity.session_id,
            target=target,
        )
    except asyncio.CancelledError:
        raise
    except WebSocketDisconnect:
        return
    except BrowserSocketFailure as error:
        if (
            websocket.application_state is WebSocketState.CONNECTED
            and websocket.client_state is not WebSocketState.DISCONNECTED
        ):
            await websocket.close(code=error.code, reason=error.reason)
