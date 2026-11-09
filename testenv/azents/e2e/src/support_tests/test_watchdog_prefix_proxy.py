"""Prove watchdog fixture wire ordering without a network or real-time delay."""

from http.client import HTTPMessage
from types import SimpleNamespace

import pytest

from support import image_generation_openai_proxy as proxy


class PrefixHandler(proxy._Handler):
    """Record the production fixture dispatch without opening an HTTP listener."""

    def __init__(self) -> None:
        self.path = proxy.WATCHDOG_IDLE_PREFIX_CONTROL
        self.headers = HTTPMessage()
        self.events: list[dict[str, object]] = []
        self.actions: list[str] = []
        self.completed: list[str] = []
        self.close_connection = False

    def _start_sse(self) -> None:
        self.actions.append("headers")

    def _write_sse_events(self, events: list[dict[str, object]]) -> None:
        self.events.extend(events)
        self.actions.append("flushed")

    def _write_json(self, status: int, value: object) -> None:
        assert status == 201
        assert value == {"attempts": 0}

    def _write_text_response(
        self,
        request: proxy._ModelRequestInput,
        text: str,
        *,
        response_id: str,
    ) -> None:
        del request, response_id
        self.completed.append(text)

    def _proxy(self, body: bytes | None = None) -> None:
        raise AssertionError("The explicit watchdog fixture must not reach aimock")


def request(*, title: bool = False) -> proxy._ModelRequest:
    return proxy._decode_model_request(
        {
            "model": "fixture",
            "stream": True,
            "instructions": proxy._SESSION_TITLE_SYSTEM_MARKER if title else "Respond",
            "input": [{"role": "user", "content": proxy.WATCHDOG_IDLE_PREFIX_PROMPT}],
        }
    )


def test_prefix_is_flushed_before_idle_stall_and_retry_has_complete_response(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    handler = PrefixHandler()
    monkeypatch.setattr(proxy._State, "watchdog_idle_prefix_attempts", 0)

    class Stall:
        def wait(self, timeout: float) -> bool:
            assert timeout == 1.0
            assert handler.actions == ["headers", "flushed"]
            assert handler.events[-1]["type"] == "response.output_text.delta"
            assert handler.events[-1]["delta"] == proxy.WATCHDOG_IDLE_PREFIX
            assert not any(
                event["type"] == "response.completed" for event in handler.events
            )
            handler.actions.append("idle")
            return False

    monkeypatch.setattr(proxy, "threading", SimpleNamespace(Event=Stall))
    handler.do_POST()
    # Title work cannot consume the first sampling attempt.
    handler._dispatch_model_request(request(title=True), b"unused")
    assert proxy._State.watchdog_idle_prefix_attempts == 0
    handler._dispatch_model_request(request(), b"unused")
    assert handler.actions == ["headers", "flushed", "idle"]
    assert handler.close_connection
    handler._dispatch_model_request(request(), b"unused")
    assert handler.completed[-1] == proxy.WATCHDOG_IDLE_PREFIX_RECOVERY
    assert proxy._State.watchdog_idle_prefix_attempts == 2
    handler.do_POST()
    assert proxy._State.watchdog_idle_prefix_attempts == 0
