"""Invalid speed preferences are rejected before the real REST admission boundary."""

from typing import NoReturn

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from azents.api.public.chat import v1 as chat_v1
from azents.broker.deps import get_broker
from azents.core.auth.deps import CurrentUser, get_current_user
from azents.services.agent_session_input import AgentSessionInputService
from azents.services.chat import ChatSessionService
from azents.services.chat.live_events import get_live_event_store
from azents.services.chat_write import ChatWriteService
from azents.services.exchange_file import ExchangeFileService
from azents.services.model_file import ModelFileService
from azents.services.turn_action import TurnActionCapabilityRegistry


def _unused_collaborator() -> None:
    """Supply no external state: invalid bodies must never reach these services."""
    return None


def _user() -> CurrentUser:
    return CurrentUser(user_id="user-1", session_id="auth-session")


@pytest.mark.parametrize(
    "options",
    [
        ["fast", "ultrafast"],
        ["ultrafast", "fast"],
        ["ultrafast", "ultrafast"],
        ["unknown-speed"],
    ],
)
def test_invalid_speed_wire_body_never_reaches_rest_admission(
    monkeypatch: pytest.MonkeyPatch, options: list[str]
) -> None:
    """Retain 422/no-admission wire evidence without a Runtime or provider journal."""
    admitted: list[bool] = []

    async def forbid_admission(*args: object, **kwargs: object) -> NoReturn:
        admitted.append(True)
        raise AssertionError("Invalid speed preferences reached REST admission.")

    monkeypatch.setattr(chat_v1, "_write_input_via_rest", forbid_admission)
    app = FastAPI()
    app.include_router(chat_v1.router)
    app.dependency_overrides[get_current_user] = _user
    for dependency in (
        ChatSessionService,
        AgentSessionInputService,
        ChatWriteService,
        ExchangeFileService,
        ModelFileService,
        get_broker,
        chat_v1.get_ws_broadcast,
        get_live_event_store,
        TurnActionCapabilityRegistry,
    ):
        app.dependency_overrides[dependency] = _unused_collaborator
    with TestClient(app) as client:
        response = client.post(
            "/sessions/" + "a" * 32 + "/inputs",
            json={
                "agent_id": "b" * 32,
                "client_request_id": "invalid-speed",
                "message": "Must not be persisted or dispatched.",
                "inference_profile": {
                    "model_target_label": "Astra",
                    "reasoning_effort": "high",
                    "enabled_execution_options": options,
                },
            },
        )
    assert response.status_code == 422, response.text
    assert "enabled_execution_options" in response.text
    assert admitted == []
