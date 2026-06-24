"""Testenv broker inject-resume endpoint tests."""

from typing import cast
from unittest.mock import AsyncMock

from fastapi import FastAPI
from fastapi.testclient import TestClient

from azents.api.testenv.broker.v1 import mount
from azents.broker.deps import get_broker
from azents.broker.types import SessionWakeUp
from azents.utils.fastapi.route import as_route_mounter


def _make_app(broker_mock: AsyncMock) -> FastAPI:
    """Create a FastAPI app with the inject-resume endpoint mounted."""
    app = FastAPI()
    mount(as_route_mounter(app))
    app.dependency_overrides[get_broker] = lambda: broker_mock
    return app


class TestInjectResume:
    """Tests for POST /broker/v1/inject-resume."""

    def test_success_sends_resume_message_to_broker(self) -> None:
        """Return 200 OK and call broker.send_message with wake-up."""
        broker = AsyncMock()
        app = _make_app(broker)
        client = TestClient(app)

        resp = client.post(
            "/broker/v1/inject-resume",
            json={"session_id": "sess-1", "agent_id": "agent-1"},
        )

        assert resp.status_code == 200
        assert resp.json() == {"ok": True}
        broker.send_message.assert_awaited_once()
        call_args = broker.send_message.await_args
        assert call_args is not None
        message = cast(SessionWakeUp, call_args.args[0])
        assert isinstance(message, SessionWakeUp)
        assert message.session_id == "sess-1"
        assert message.agent_id == "agent-1"

    def test_missing_fields_rejected(self) -> None:
        """Return 422 when session_id or agent_id is absent."""
        broker = AsyncMock()
        app = _make_app(broker)
        client = TestClient(app)

        resp = client.post(
            "/broker/v1/inject-resume",
            json={"session_id": "sess-1"},
        )
        assert resp.status_code == 422
        broker.send_message.assert_not_called()
