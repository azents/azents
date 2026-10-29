"""Fragment count cannot amplify retained request frames or quadratic replay."""

import asyncio
import logging

import pytest
from starlette.types import Message, Receive, Scope, Send

from azents_llm_proxy import ingress
from azents_llm_proxy.authority_test import binding
from azents_llm_proxy.context import RequestContext
from azents_llm_proxy.ingress import AgentIngress
from azents_llm_proxy.observability import LOGGER


async def test_fragmented_body_is_coalesced_once_then_disconnect_is_delegated(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(ingress, "_MAX_BODY", 8)
    received = 0
    sent: list[Message] = []
    context = RequestContext(clients=None)

    async def receive() -> Message:
        nonlocal received
        received += 1
        if received < 20_000:
            return {"type": "http.request", "body": b"", "more_body": True}
        if received == 20_000:
            return {"type": "http.request", "body": b"12345678", "more_body": False}
        return {"type": "http.disconnect"}

    async def send(message: Message) -> None:
        sent.append(message)

    async def application(scope: Scope, receive: Receive, send: Send) -> None:
        assert context.current.get() is not None
        assert await receive() == {
            "type": "http.request",
            "body": b"12345678",
            "more_body": False,
        }
        assert await receive() == {"type": "http.disconnect"}
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b"ok"})

    scope: Scope = {"type": "http", "method": "POST", "path": "/v1/responses"}
    await AgentIngress(application, context)(scope, receive, send)
    assert received == 20_001
    assert sent[0]["status"] == 200
    assert context.current.get() is None


async def test_oversize_fragmented_body_is_rejected_before_inner_authentication(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(ingress, "_MAX_BODY", 8)
    received = 0
    sent: list[Message] = []

    async def receive() -> Message:
        nonlocal received
        received += 1
        return {"type": "http.request", "body": b"1234", "more_body": True}

    async def send(message: Message) -> None:
        sent.append(message)

    async def application(scope: Scope, receive: Receive, send: Send) -> None:
        pytest.fail("Oversize ingress reached the inner application.")

    scope: Scope = {"type": "http", "method": "POST", "path": "/v1/responses"}
    await AgentIngress(application, RequestContext(clients=None))(scope, receive, send)
    assert received == 3
    assert sent[0]["status"] == 413


@pytest.mark.parametrize("failure", ["cancelled", "disconnected"])
async def test_termination_overrides_provider_success_without_duplicate_event(
    failure: str, caplog: pytest.LogCaptureFixture
) -> None:
    context = RequestContext(clients=None)
    caplog.set_level(logging.INFO, logger=LOGGER.name)

    async def receive() -> Message:
        return {"type": "http.request", "body": b"{}", "more_body": False}

    async def send(message: Message) -> None:
        if failure == "disconnected":
            raise OSError("private-downstream-error")
        raise asyncio.CancelledError

    async def application(scope: Scope, receive: Receive, send: Send) -> None:
        await receive()
        context.observe(binding())
        state = context.current.get()
        assert state is not None and state.operation is not None
        state.operation.terminal = "success"
        await send({"type": "http.response.start", "status": 200, "headers": []})

    scope: Scope = {"type": "http", "method": "POST", "path": "/v1/responses"}
    with pytest.raises(
        OSError if failure == "disconnected" else asyncio.CancelledError
    ):
        await AgentIngress(application, context)(scope, receive, send)
    assert context.current.get() is None
    events = [r.__dict__ for r in caplog.records if r.name == LOGGER.name]
    assert len(events) == 1
    assert events[0]["outcome"] == failure
    assert "private-downstream-error" not in caplog.text
