"""Public Browser WebSocket first-message identity and credential privacy tests."""

import json
from unittest.mock import AsyncMock

import pytest
from azents_runtime_control.browser_viewer_contract import ViewerTarget
from fastapi import FastAPI
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from azents.api.public.browser.v1 import mount
from azents.core.auth import jwt as jwt_module
from azents.core.auth.jwt import create_ws_ticket
from azents.core.config import AuthConfig, JWTConfig
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
)
from azents.utils.fastapi.route import as_route_mounter

_PATH = "/browser/v1/workspaces/team/agents/agent-1/sessions/session-1/ws"
_JWT = JWTConfig(secret_key="synthetic-browser-test-secret")


def _app(service: AsyncMock) -> FastAPI:
    app = FastAPI()
    mount(as_route_mounter(app))
    app.dependency_overrides[get_auth_config] = lambda: AuthConfig.model_construct(
        jwt=_JWT
    )
    app.dependency_overrides[get_runtime_browser_socket_service] = lambda: service
    app.dependency_overrides[get_runtime_browser_web_origin] = lambda: (
        "https://web.test"
    )
    return app


def _attach(ticket: str) -> dict[str, object]:
    return {
        "type": "attach",
        "ticket": ticket,
        "target": {
            "task_id": "task-1",
            "page_id": "page-1",
            "resource_incarnation": "inc-1",
        },
    }


def _service() -> AsyncMock:
    service = AsyncMock(spec=RuntimeBrowserSocketService)
    service.serve.side_effect = BrowserSocketFailure(1000, "Browser page closed")
    return service


def test_first_attach_identity_only_ticket_is_verified_and_never_put_in_scope_url() -> (
    None
):
    service = _service()
    ticket = create_ws_ticket(_JWT, "user-a", "auth-a")
    with TestClient(_app(service)) as client:
        with client.websocket_connect(
            _PATH,
            subprotocols=[BROWSER_WEBSOCKET_SUBPROTOCOL],
            headers={"origin": "https://web.test"},
        ) as socket:
            assert socket.accepted_subprotocol == BROWSER_WEBSOCKET_SUBPROTOCOL
            socket.send_json(_attach(ticket))
            with pytest.raises(WebSocketDisconnect) as captured:
                socket.receive_text()
    assert captured.value.code == 1000
    call = service.serve.call_args.kwargs
    assert call["user_id"] == "user-a" and call["authentication_session_id"] == "auth-a"
    assert call["resource"] == RuntimeBrowserResource("team", "agent-1", "session-1")
    assert call["target"] == ViewerTarget("task-1", "page-1", "inc-1")
    assert call["socket"].scope["query_string"] == b""
    assert "ticket" not in call and "authorization" not in call


@pytest.mark.parametrize("ticket", ["invalid", "a.b.9999999999.wrong-signature"])
def test_invalid_identity_ticket_is_denied_before_browser_content(ticket: str) -> None:
    service = _service()
    with TestClient(_app(service)) as client:
        with client.websocket_connect(
            _PATH,
            subprotocols=[BROWSER_WEBSOCKET_SUBPROTOCOL],
            headers={"origin": "https://web.test"},
        ) as socket:
            socket.send_json(_attach(ticket))
            with pytest.raises(WebSocketDisconnect) as captured:
                socket.receive_text()
    assert captured.value.code == 4401
    service.serve.assert_not_awaited()


def test_expired_ticket_is_not_an_authority_to_open_a_source(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(jwt_module, "WS_TICKET_TTL_SECONDS", -1)
    ticket = create_ws_ticket(_JWT, "user-a", "auth-a")
    service = _service()
    with TestClient(_app(service)) as client:
        with client.websocket_connect(
            _PATH,
            subprotocols=[BROWSER_WEBSOCKET_SUBPROTOCOL],
            headers={"origin": "https://web.test"},
        ) as socket:
            socket.send_json(_attach(ticket))
            with pytest.raises(WebSocketDisconnect) as captured:
                socket.receive_text()
    assert captured.value.code == 4401
    service.serve.assert_not_awaited()


@pytest.mark.parametrize(
    "data",
    [
        {},
        {"type": "attach", "target": {}},
        {
            "type": "attach",
            "ticket": "invalid",
            "target": {
                "task_id": "task-1",
                "page_id": "page-1",
                "resource_incarnation": "inc-1",
                "frame_id": "other",
            },
        },
        {
            "type": "attach",
            "ticket": "invalid",
            "working_directory": "/other",
            "target": {
                "task_id": "task-1",
                "page_id": "page-1",
                "resource_incarnation": "inc-1",
            },
        },
    ],
)
def test_attach_is_closed_and_cannot_supply_session_root_frame_or_folder(
    data: dict[str, object],
) -> None:
    service = _service()
    with TestClient(_app(service)) as client:
        with client.websocket_connect(
            _PATH,
            subprotocols=[BROWSER_WEBSOCKET_SUBPROTOCOL],
            headers={"origin": "https://web.test"},
        ) as socket:
            socket.send_json(data)
            with pytest.raises(WebSocketDisconnect) as captured:
                socket.receive_text()
    assert captured.value.code == 4400
    service.serve.assert_not_awaited()


@pytest.mark.parametrize(
    "text,code",
    [
        ('{"type":"attach","type":"input"}', 4400),
        ("x" * 8193, 4429),
    ],
)
def test_duplicate_or_oversized_first_message_is_bounded_before_identity(
    text: str, code: int
) -> None:
    service = _service()
    with TestClient(_app(service)) as client:
        with client.websocket_connect(
            _PATH,
            subprotocols=[BROWSER_WEBSOCKET_SUBPROTOCOL],
            headers={"origin": "https://web.test"},
        ) as socket:
            socket.send_text(text)
            with pytest.raises(WebSocketDisconnect) as captured:
                socket.receive_text()
    assert captured.value.code == code
    service.serve.assert_not_awaited()


@pytest.mark.parametrize(
    "query,origin,subprotocols,code",
    [
        (
            "?ticket=must-not-be-a-credential",
            "https://web.test",
            [BROWSER_WEBSOCKET_SUBPROTOCOL],
            4400,
        ),
        ("", "https://attacker.test", [BROWSER_WEBSOCKET_SUBPROTOCOL], 4403),
        ("", "https://web.test", [], 4400),
    ],
)
def test_origin_subprotocol_and_no_query_are_not_substitutes_for_identity(
    query: str,
    origin: str,
    subprotocols: list[str],
    code: int,
) -> None:
    service = _service()
    with TestClient(_app(service)) as client:
        with pytest.raises(WebSocketDisconnect) as captured:
            with client.websocket_connect(
                _PATH + query, subprotocols=subprotocols, headers={"origin": origin}
            ):
                pass
    assert captured.value.code == code
    service.serve.assert_not_awaited()


def test_binary_attach_is_not_an_alternate_authentication_path() -> None:
    service = _service()
    with TestClient(_app(service)) as client:
        with client.websocket_connect(
            _PATH,
            subprotocols=[BROWSER_WEBSOCKET_SUBPROTOCOL],
            headers={"origin": "https://web.test"},
        ) as socket:
            socket.send_bytes(json.dumps(_attach("invalid")).encode())
            with pytest.raises(WebSocketDisconnect) as captured:
                socket.receive_text()
    assert captured.value.code == 4400
    service.serve.assert_not_awaited()
