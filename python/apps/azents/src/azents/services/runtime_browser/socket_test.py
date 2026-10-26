"""Browser socket first-content scope, live revocation and cleanup tests."""

import asyncio
import dataclasses
import json
import time
from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from typing import Literal, NamedTuple
from unittest.mock import AsyncMock

import pytest
from azents_runtime_control.browser_source_contract import BrowserScopeState
from azents_runtime_control.browser_viewer_contract import (
    ViewerFieldAttributes,
    ViewerFieldValue,
    ViewerFrame,
    ViewerSource,
    ViewerStatus,
    ViewerTarget,
    encode_viewer_event,
    encode_viewer_frame,
)
from azents_runtime_control.grpc_browser_source_client import (
    BrowserSourceError,
    BrowserSourceScopeRevoked,
    BrowserSourceUnavailable,
    BrowserSourceWebSocketMessage,
)
from azents_runtime_control.runtime_stream_session import (
    BrowserStreamAuthority,
    WebSocketOpcode,
)
from fastapi import WebSocketDisconnect

from azents.services.agent_runtime.lifecycle_data import RuntimeOperationTarget
from azents.services.runtime_browser.authority import (
    DatabaseRuntimeBrowserStreamScopeValidator,
)
from azents.services.runtime_browser.data import (
    RuntimeBrowserAuthority,
    RuntimeBrowserRequestError,
    RuntimeBrowserResource,
    RuntimeBrowserTargetUnavailable,
)
from azents.services.runtime_browser.socket import (
    BrowserSocketFailure,
    RuntimeBrowserSocketService,
    _RateBudget,
)

_NOW = datetime(2026, 10, 15, tzinfo=UTC)
_RESOURCE = RuntimeBrowserResource("workspace", "agent-1", "session-1")
_TARGET = ViewerTarget("task-1", "page-1", "inc-1")
_CURRENT = RuntimeBrowserAuthority(
    _RESOURCE,
    "user-a",
    "auth-a",
    _NOW + timedelta(hours=2),
    RuntimeOperationTarget("runtime-1", 3, 8, 5, 2, "digest", "/reported"),
    "/reported/.azents/sessions/session-1",
    True,
)


class _Connection:
    def __init__(self) -> None:
        self.incoming: asyncio.Queue[
            BrowserSourceWebSocketMessage | BrowserSourceError
        ] = asyncio.Queue()
        self.sent: list[bytes] = []
        self.sent_event = asyncio.Event()
        self.closed = False

    async def receive_websocket(self) -> BrowserSourceWebSocketMessage:
        value = await self.incoming.get()
        if isinstance(value, BrowserSourceError):
            raise value
        return value

    async def send_websocket(self, *, opcode: WebSocketOpcode, payload: bytes) -> None:
        assert opcode is WebSocketOpcode.TEXT
        self.sent.append(payload)
        self.sent_event.set()

    async def close(self) -> None:
        self.closed = True


class _Source:
    def __init__(self, connection: _Connection) -> None:
        self.connection = connection
        self.authorities: list[BrowserStreamAuthority] = []
        self.failure: BrowserSourceError | None = None

    async def connect(self, *, authority: BrowserStreamAuthority) -> _Connection:
        self.authorities.append(authority)
        if self.failure is not None:
            raise self.failure
        return self.connection


class _Socket:
    def __init__(self) -> None:
        self.incoming: asyncio.Queue[Mapping[str, object]] = asyncio.Queue()
        self.texts: list[str] = []
        self.images: list[bytes] = []
        self.text_sent = asyncio.Event()
        self.image_sent = asyncio.Event()

    async def receive(self) -> Mapping[str, object]:
        return await self.incoming.get()

    async def send_text(self, data: str) -> None:
        self.texts.append(data)
        self.text_sent.set()

    async def send_bytes(self, data: bytes) -> None:
        self.images.append(data)
        self.image_sent.set()


class _Harness(NamedTuple):
    service: RuntimeBrowserSocketService
    validator: AsyncMock
    source: _Source
    connection: _Connection
    socket: _Socket


def _harness() -> _Harness:
    validator = AsyncMock(spec=DatabaseRuntimeBrowserStreamScopeValidator)
    validator.admit.return_value = _CURRENT
    validator.return_value = BrowserScopeState.CURRENT
    connection = _Connection()
    source = _Source(connection)
    return _Harness(
        RuntimeBrowserSocketService(validator, source, lambda: _NOW, time.monotonic),
        validator,
        source,
        connection,
        _Socket(),
    )


def _start(h: _Harness) -> asyncio.Task[None]:
    return asyncio.create_task(
        h.service.serve(
            socket=h.socket,
            resource=_RESOURCE,
            user_id="user-a",
            authentication_session_id="auth-a",
            target=_TARGET,
        )
    )


def _status(
    *, allow_input: bool = True, target: ViewerTarget = _TARGET
) -> BrowserSourceWebSocketMessage:
    return BrowserSourceWebSocketMessage(
        WebSocketOpcode.TEXT,
        encode_viewer_event(
            ViewerStatus(
                "attachment-1",
                target,
                "connected",
                allow_input,
                800,
                600,
                "nav-1",
                None,
                False,
                None,
            )
        ),
    )


def _frame() -> BrowserSourceWebSocketMessage:
    return BrowserSourceWebSocketMessage(
        WebSocketOpcode.BINARY,
        encode_viewer_frame(
            ViewerFrame(
                "attachment-1",
                _TARGET,
                ViewerSource(1, "nav-1", 800, 600),
                b"jpeg-fixture",
                (),
            )
        ),
    )


def _input(sequence: int = 1) -> Mapping[str, object]:
    return {
        "type": "websocket.receive",
        "text": json.dumps(
            {
                "type": "input",
                "attachment_id": "attachment-1",
                "sequence": sequence,
                "source": {
                    "frame_sequence": 1,
                    "navigation_id": "nav-1",
                    "width": 800,
                    "height": 600,
                },
                "action": {"kind": "key", "phase": "down", "key": "a"},
            }
        ),
    }


async def _connected(h: _Harness) -> asyncio.Task[None]:
    h.connection.incoming.put_nowait(
        _status(allow_input=h.validator.admit.return_value.allow_input)
    )
    task = _start(h)
    await asyncio.wait_for(h.socket.text_sent.wait(), 2)
    return task


async def _disconnect(h: _Harness, task: asyncio.Task[None]) -> None:
    h.socket.incoming.put_nowait({"type": "websocket.disconnect"})
    with pytest.raises(WebSocketDisconnect):
        await asyncio.wait_for(task, 2)
    assert h.connection.closed


async def test_admitted_first_status_then_original_binary_pair_are_forwarded() -> None:
    h = _harness()
    task = await _connected(h)
    authority = h.source.authorities[0]
    assert authority.session_id == "session-1" and authority.allow_input
    assert authority.transport_deadline_at == _NOW + timedelta(hours=1)
    assert authority.open_deadline_at <= authority.transport_deadline_at
    h.connection.incoming.put_nowait(_frame())
    await asyncio.wait_for(h.socket.image_sent.wait(), 2)
    assert h.socket.images == [_frame().payload]
    await _disconnect(h, task)


@pytest.mark.parametrize("status", [401, 403, 404])
async def test_denied_admission_sends_no_title_frame_or_source(
    status: Literal[401, 403, 404],
) -> None:
    h = _harness()
    h.validator.admit.side_effect = RuntimeBrowserRequestError(status, "private")
    with pytest.raises(BrowserSocketFailure) as captured:
        await _start(h)
    assert captured.value.code == (4401 if status == 401 else 4403)
    assert "private" not in str(captured.value)
    assert h.source.authorities == [] and not h.socket.texts and not h.socket.images


async def test_selected_stale_page_does_not_open_source_or_choose_another_target() -> (
    None
):
    h = _harness()
    h.validator.admit.side_effect = RuntimeBrowserTargetUnavailable()
    with pytest.raises(BrowserSocketFailure) as captured:
        await _start(h)
    assert captured.value.code == 4409 and h.source.authorities == []


async def test_post_source_scope_check_precedes_any_first_frame() -> None:
    h = _harness()
    h.validator.return_value = BrowserScopeState.REVOKED
    h.connection.incoming.put_nowait(_frame())
    with pytest.raises(BrowserSocketFailure) as captured:
        await _start(h)
    assert captured.value.code == 4403 and h.connection.closed
    assert not h.socket.texts and not h.socket.images


@pytest.mark.parametrize("navigation", [False, True])
async def test_read_only_can_ack_frames_but_cannot_send_input(navigation: bool) -> None:
    h = _harness()
    h.validator.admit.return_value = dataclasses.replace(_CURRENT, allow_input=False)
    task = await _connected(h)
    h.connection.incoming.put_nowait(_frame())
    await asyncio.wait_for(h.socket.image_sent.wait(), 2)
    h.socket.incoming.put_nowait(
        {
            "type": "websocket.receive",
            "text": json.dumps(
                {
                    "type": "frame_ack",
                    "attachment_id": "attachment-1",
                    "frame_sequence": 1,
                }
            ),
        }
    )
    await asyncio.wait_for(h.connection.sent_event.wait(), 2)
    assert len(h.connection.sent) == 1
    if navigation:
        message: Mapping[str, object] = {
            "type": "websocket.receive",
            "text": json.dumps(
                {
                    "type": "input",
                    "attachment_id": "attachment-1",
                    "sequence": 1,
                    "source": {
                        "frame_sequence": 1,
                        "navigation_id": "nav-1",
                        "width": 800,
                        "height": 600,
                    },
                    "action": {"kind": "navigation", "action": "reload", "url": None},
                }
            ),
        }
    else:
        message = _input()
    h.socket.incoming.put_nowait(message)
    with pytest.raises(BrowserSocketFailure) as captured:
        await asyncio.wait_for(task, 2)
    assert captured.value.code == 4403 and len(h.connection.sent) == 1
    assert h.connection.closed


async def test_preinput_revocation_stops_forwarding_and_closes_source() -> None:
    h = _harness()
    task = await _connected(h)
    h.validator.return_value = BrowserScopeState.REVOKED
    h.socket.incoming.put_nowait(_input())
    with pytest.raises(BrowserSocketFailure) as captured:
        await asyncio.wait_for(task, 2)
    assert captured.value.code == 4403 and not h.connection.sent and h.connection.closed


async def test_idle_live_revocation_closes_within_five_second_contract() -> None:
    h = _harness()
    task = await _connected(h)
    h.validator.return_value = BrowserScopeState.REVOKED
    with pytest.raises(BrowserSocketFailure) as captured:
        await asyncio.wait_for(task, 5)
    assert captured.value.code == 4403 and h.connection.closed


async def test_auth_expiry_bounds_transport_and_expired_scope_has_no_source() -> None:
    h = _harness()
    h.validator.admit.return_value = dataclasses.replace(
        _CURRENT, authentication_session_expires_at=_NOW + timedelta(seconds=30)
    )
    task = await _connected(h)
    assert h.source.authorities[0].transport_deadline_at == _NOW + timedelta(seconds=30)
    await _disconnect(h, task)
    h = _harness()
    h.validator.admit.return_value = dataclasses.replace(
        _CURRENT, authentication_session_expires_at=_NOW
    )
    with pytest.raises(BrowserSocketFailure) as captured:
        await _start(h)
    assert captured.value.code == 4408 and not h.source.authorities


async def test_old_scope_frame_is_never_sent_to_public_socket() -> None:
    h = _harness()
    h.connection.incoming.put_nowait(
        _status(target=dataclasses.replace(_TARGET, task_id="other"))
    )
    with pytest.raises(BrowserSocketFailure) as captured:
        await _start(h)
    assert captured.value.code == 4403 and not h.socket.texts and h.connection.closed


@pytest.mark.parametrize(
    "message",
    [
        {"type": "websocket.receive", "bytes": b"input"},
        {"type": "websocket.receive", "text": "{}"},
        {"type": "websocket.receive", "text": '{"type":"input","type":"frame_ack"}'},
    ],
)
async def test_malformed_or_binary_client_input_is_not_forwarded(
    message: Mapping[str, object],
) -> None:
    h = _harness()
    task = await _connected(h)
    h.socket.incoming.put_nowait(message)
    with pytest.raises(BrowserSocketFailure) as captured:
        await asyncio.wait_for(task, 2)
    assert captured.value.code == 4400 and not h.connection.sent and h.connection.closed


async def test_no_replay_of_input_sequence_on_the_current_attachment() -> None:
    h = _harness()
    task = await _connected(h)
    h.socket.incoming.put_nowait(_input())
    await asyncio.wait_for(h.connection.sent_event.wait(), 2)
    h.socket.incoming.put_nowait(_input())
    with pytest.raises(BrowserSocketFailure) as captured:
        await asyncio.wait_for(task, 2)
    assert (
        captured.value.code == 4400
        and len(h.connection.sent) == 1
        and h.connection.closed
    )


async def test_cancellation_cleans_source_and_does_not_replay_pending_input() -> None:
    h = _harness()
    task = await _connected(h)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert h.connection.closed and not h.connection.sent


async def test_source_failure_has_fixed_reason_and_no_success_fallback() -> None:
    h = _harness()
    h.source.failure = BrowserSourceUnavailable("private source error")
    with pytest.raises(BrowserSocketFailure) as captured:
        await _start(h)
    assert captured.value.code == 4500 and "private" not in str(captured.value)
    assert not h.socket.texts and not h.socket.images


@pytest.mark.parametrize(
    "reason,code",
    [
        ("unauthenticated", 4401),
        ("access_revoked", 4403),
        ("expired", 4408),
        ("stale_target", 4409),
    ],
)
@pytest.mark.parametrize("live", [False, True])
async def test_source_denial_is_not_a_transient_stale_image_close(
    reason: Literal["unauthenticated", "access_revoked", "expired", "stale_target"],
    code: int,
    live: bool,
) -> None:
    h = _harness()
    if live:
        task = await _connected(h)
        h.connection.incoming.put_nowait(BrowserSourceScopeRevoked(reason))
        h.connection.incoming.put_nowait(_frame())
    else:
        h.source.failure = BrowserSourceScopeRevoked(reason)
        task = _start(h)
    with pytest.raises(BrowserSocketFailure) as captured:
        await asyncio.wait_for(task, 2)
    assert captured.value.code == code
    assert not h.socket.images
    assert not live or h.connection.closed


async def test_binary_frame_before_current_attachment_status_is_not_forwarded() -> None:
    h = _harness()
    h.connection.incoming.put_nowait(_frame())
    with pytest.raises(BrowserSocketFailure) as captured:
        await asyncio.wait_for(_start(h), 2)
    assert captured.value.code == 4409 and not h.socket.images and h.connection.closed


def test_rate_budget_bounds_both_message_count_and_bytes() -> None:
    budget = _RateBudget(0, 120, 256 * 1024)
    for _ in range(120):
        budget.consume(1, 0)
    with pytest.raises(BrowserSocketFailure) as captured:
        budget.consume(1, 0)
    assert captured.value.code == 4429
    budget.consume(1, 1)
    budget = _RateBudget(0, 120, 256 * 1024)
    budget.consume(256 * 1024, 0)
    with pytest.raises(BrowserSocketFailure):
        budget.consume(1, 0)


def _field_value(
    *, sequence: int = 1, editable_id: str = "native-1"
) -> BrowserSourceWebSocketMessage:
    return BrowserSourceWebSocketMessage(
        WebSocketOpcode.TEXT,
        encode_viewer_event(
            ViewerFieldValue(
                "attachment-1",
                sequence,
                editable_id,
                "edit-1",
                "password",
                ViewerFieldAttributes(
                    "password",
                    None,
                    "current-password",
                    None,
                    None,
                    False,
                    None,
                    None,
                    None,
                    "",
                    False,
                    False,
                    "",
                    "password",
                ),
                "Synthetic private value",
            )
        ),
    )


@pytest.mark.parametrize(
    "patch",
    [
        {"form": "not allowed"},
        {"input_type": "email"},
        {"autocomplete": "x" * 257},
    ],
)
async def test_private_native_attributes_fail_closed(
    patch: dict[str, object],
) -> None:
    h = _harness()
    task = await _connected(h)
    await _open_field(h)
    value = json.loads(_field_value().payload)
    value["attributes"].update(patch)
    h.connection.incoming.put_nowait(
        BrowserSourceWebSocketMessage(WebSocketOpcode.TEXT, json.dumps(value).encode())
    )
    with pytest.raises(BrowserSocketFailure) as captured:
        await asyncio.wait_for(task, 2)
    assert captured.value.code == 4500 and len(h.socket.texts) == 1
    assert "Synthetic private value" not in str(captured.value)


async def _open_field(h: _Harness) -> None:
    request = dict(_input())
    value = json.loads(str(request["text"]))
    value["action"] = {"kind": "field_open", "editable_id": "native-1"}
    request["text"] = json.dumps(value)
    h.socket.incoming.put_nowait(request)
    await asyncio.wait_for(h.connection.sent_event.wait(), 2)


async def test_private_field_response_requires_explicit_correlated_read() -> None:
    h = _harness()
    task = await _connected(h)
    await _open_field(h)
    h.socket.text_sent.clear()
    h.connection.incoming.put_nowait(_field_value())
    await asyncio.wait_for(h.socket.text_sent.wait(), 2)
    assert h.socket.texts[-1] == _field_value().payload.decode()
    h.socket.text_sent.clear()
    h.connection.incoming.put_nowait(
        BrowserSourceWebSocketMessage(
            WebSocketOpcode.TEXT,
            json.dumps(
                {
                    "type": "input_ack",
                    "attachment_id": "attachment-1",
                    "sequence": 1,
                    "accepted": True,
                    "reason_code": None,
                    "outcome": "dispatched",
                }
            ).encode(),
        )
    )
    await asyncio.wait_for(h.socket.text_sent.wait(), 2)
    assert json.loads(h.socket.texts[-1])["type"] == "input_ack"
    await _disconnect(h, task)


@pytest.mark.parametrize(
    "case",
    [
        "unsolicited",
        "wrong-sequence",
        "wrong-field",
        "revoked",
        "readonly",
        "duplicate",
    ],
)
async def test_private_field_response_fails_closed_without_forwarding(
    case: str,
) -> None:
    h = _harness()
    if case == "readonly":
        h.validator.admit.return_value = dataclasses.replace(
            _CURRENT, allow_input=False
        )
    task = await _connected(h)
    if case not in {"unsolicited", "readonly"}:
        await _open_field(h)
    if case == "revoked":
        h.validator.return_value = BrowserScopeState.REVOKED
    if case == "duplicate":
        h.socket.text_sent.clear()
        h.connection.incoming.put_nowait(_field_value())
        await asyncio.wait_for(h.socket.text_sent.wait(), 2)
    count = len(h.socket.texts)
    h.connection.incoming.put_nowait(
        _field_value(
            sequence=2 if case == "wrong-sequence" else 1,
            editable_id="other" if case == "wrong-field" else "native-1",
        )
    )
    with pytest.raises(BrowserSocketFailure) as captured:
        await asyncio.wait_for(task, 2)
    assert captured.value.code == (4403 if case == "revoked" else 4500)
    assert len(h.socket.texts) == count
    assert "Synthetic private value" not in str(captured.value)
