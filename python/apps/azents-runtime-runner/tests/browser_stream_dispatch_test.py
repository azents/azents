"""Browser owned dispatch shares accounting without forwarding through Web."""

import asyncio
import datetime
from dataclasses import replace

import pytest
from azents_runtime_control.proto import runtime_stream_session_pb2
from azents_runtime_control.runtime_stream_authority_codec import (
    encode_stream_authority,
)
from azents_runtime_control.runtime_stream_session import (
    MANDATORY_DATA_FRAME_BYTES,
    BrowserStreamAuthority,
    WebSocketOpcode,
)
from web_session_dispatcher_test import (
    _dispatcher,
    _envelope,
    _manager,
    _offer,
    _RecordingClient,
    _stream,
)

from azents_runtime_runner.browser_viewer import (
    RunnerBrowserViewer,
    ViewerReceive,
    ViewerSend,
)


class Consumer(RunnerBrowserViewer):
    def __init__(self) -> None:
        self.received: list[bytes | None] = []
        self.checked: list[BrowserStreamAuthority] = []
        self.done = asyncio.Event()

    def validate(self, authority: BrowserStreamAuthority) -> None:
        self.checked.append(authority)

    async def run(
        self,
        authority: BrowserStreamAuthority,
        receive: ViewerReceive,
        send: ViewerSend,
    ) -> None:
        self.validate(authority)
        await send(WebSocketOpcode.TEXT, b"{}")
        await send(WebSocketOpcode.BINARY, b"x" * (MANDATORY_DATA_FRAME_BYTES * 2 + 7))
        self.received.append(await receive())
        self.done.set()


def authority() -> BrowserStreamAuthority:
    now = datetime.datetime.now(datetime.UTC)
    return BrowserStreamAuthority(
        "correlation",
        "authentication",
        "user",
        "agent",
        "runtime-a",
        3,
        4,
        now + datetime.timedelta(seconds=5),
        now + datetime.timedelta(minutes=1),
        "session",
        "task",
        "page",
        "incarnation",
        True,
    )


async def test_owned_browser_fragmented_send_and_receive_never_uses_loopback() -> None:
    offer = _offer()
    client = _RecordingClient()
    manager = _manager(client_factory=None)
    dispatcher = _dispatcher(manager)
    consumer = Consumer()
    dispatcher.browser = consumer
    stream = replace(
        _stream(
            offer=offer,
            client=client,
            session_credit=dispatcher.response_session_credit,
        ),
        authority=authority(),
    )
    for sequence, part in [(1, b'{"type":'), (2, b'"fixture"}')]:
        item = _envelope(offer, stream_id=1)
        item.frame_sequence = sequence
        item.websocket.direction = (
            runtime_stream_session_pb2.RUNTIME_STREAM_SESSION_DIRECTION_REQUEST
        )
        item.websocket.opcode = (
            runtime_stream_session_pb2.RUNTIME_STREAM_SESSION_WEBSOCKET_OPCODE_TEXT
            if sequence == 1
            else (
                runtime_stream_session_pb2.RUNTIME_STREAM_SESSION_WEBSOCKET_OPCODE_CONTINUATION
            )
        )
        item.websocket.final = sequence == 2
        item.websocket.data = part
        assert await stream.inbound.put(item)
    running = asyncio.create_task(dispatcher._browser(1, stream, authority()))
    async with asyncio.timeout(5):
        await consumer.done.wait()
        async with stream.credit_changed:
            sent = stream.response_credit.stream.sent_total
            stream.response_credit.update_consumed(
                stream_consumed_total=sent, session_consumed_total=sent
            )
            stream.credit_changed.notify_all()
        await running
    assert consumer.received == [b'{"type":"fixture"}']
    assert manager.loopback.http_pool is None
    frames = [item for item in client.sent if item.WhichOneof("payload") == "websocket"]
    assert [item.frame_sequence for item in frames] == [1, 2, 3, 4]
    assert all(
        len(item.websocket.data) <= MANDATORY_DATA_FRAME_BYTES for item in frames
    )
    assert b"".join(item.websocket.data for item in frames[1:]) == b"x" * (
        MANDATORY_DATA_FRAME_BYTES * 2 + 7
    )
    assert frames[-1].websocket.final is True
    assert dispatcher.resources.pending_tasks == 0
    assert stream.request_consumed_total == len(consumer.received[0] or b"")
    with pytest.raises(ValueError, match="cannot open Web loopback"):
        await dispatcher._websocket(1, stream)
    with pytest.raises(ValueError, match="cannot open Web loopback"):
        await dispatcher._http(1, stream)
    await stream.inbound.close()
    stream.response_credit.close()


@pytest.mark.parametrize("browser_domain", [True, False])
async def test_open_cancel_before_consumer_start_releases_both_domains(
    browser_domain: bool,
) -> None:
    offer = _offer()
    client = _RecordingClient()
    manager = _manager(client_factory=None)
    manager.offer, manager.client = offer, client
    dispatcher = _dispatcher(manager)
    consumer = Consumer()
    dispatcher.browser = consumer
    dispatcher.accepting_envelopes = dispatcher.accepting_streams = True
    opening = _envelope(offer, stream_id=1)
    admitted = (
        authority()
        if browser_domain
        else _stream(
            offer=offer,
            client=client,
            session_credit=dispatcher.response_session_credit,
        ).authority
    )
    opening.open.authority.CopyFrom(encode_stream_authority(admitted))
    opening.open.request_head.protocol = (
        runtime_stream_session_pb2.RUNTIME_STREAM_SESSION_PROTOCOL_WEBSOCKET
    )
    opening.open.request_head.method = b"GET"
    opening.open.request_head.target = b"/browser"
    await dispatcher(opening)
    assert len(consumer.checked) == (1 if browser_domain else 0)
    if browser_domain:
        assert consumer.checked[0].task_id == "task"
    assert manager.loopback.http_pool is None
    await dispatcher.close()
    assert not dispatcher.streams and dispatcher.resources.active_streams == 0
    assert dispatcher.resources.pending_tasks == 0


async def test_browser_generation_change_cannot_dispatch_input() -> None:
    offer = _offer()
    client = _RecordingClient()
    manager = _manager(client_factory=None)
    dispatcher = _dispatcher(manager)
    consumer = Consumer()
    dispatcher.browser = consumer
    stream = replace(
        _stream(
            offer=offer,
            client=client,
            session_credit=dispatcher.response_session_credit,
        ),
        authority=replace(authority(), runner_generation=5),
    )
    current = stream.authority
    assert isinstance(current, BrowserStreamAuthority)
    with pytest.raises(RuntimeError, match="generation"):
        await dispatcher._browser(1, stream, current)
    assert consumer.received == []
    await stream.inbound.close()
    stream.response_credit.close()
