"""Runtime Runner persistent Web session dispatcher tests."""

import asyncio
import datetime
import logging
from collections.abc import AsyncIterator, Callable

import h11
import pytest
from azents_runtime_control.grpc_runner_web_session_client import (
    EnvelopeHandler,
    FailureHandler,
    GrpcRunnerWebSessionClient,
)
from azents_runtime_control.proto import runtime_web_session_pb2
from azents_runtime_control.runtime_web_flow import (
    AbsoluteCreditWindow,
    HierarchicalCredit,
)
from azents_runtime_control.runtime_web_session import (
    APPROVED_SESSION_PROFILE,
    MANDATORY_DATA_FRAME_BYTES,
    MAX_STREAM_TOMBSTONES,
    RUNTIME_WEB_PROTOCOL_FINGERPRINT,
    CloseReason,
    OwnerSessionEpoch,
    RequestHead,
    RunnerSessionOffer,
    StreamAuthority,
    StreamProtocol,
)
from wsproto.events import Event
from wsproto.utilities import RemoteProtocolError as WsprotoRemoteProtocolError

from azents_runtime_runner.web_session import (
    RunnerWebLoopbackPool,
    RunnerWebSessionManager,
    RunnerWebSocket,
)
from azents_runtime_runner.web_session_dispatcher import (
    RunnerWebHardLimits,
    RunnerWebResourceTracker,
    RunnerWebSessionDispatcher,
    _head,
    _RunnerInboundQueue,
    _Stream,
)


class _RecordingClient(GrpcRunnerWebSessionClient):
    def __init__(self) -> None:
        self.sent: list[runtime_web_session_pb2.RuntimeWebSessionEnvelope] = []
        self.closed = False

    async def send(
        self,
        envelope: runtime_web_session_pb2.RuntimeWebSessionEnvelope,
    ) -> None:
        self.sent.append(envelope)

    async def close(self) -> None:
        self.closed = True


class _HandshakeClient(_RecordingClient):
    def __init__(
        self,
        offer: RunnerSessionOffer,
        before_start: Callable[[], None] | None = None,
    ) -> None:
        super().__init__()
        self.offer = offer
        self.before_start = before_start
        self.activated = False

    async def start(
        self,
        hello: runtime_web_session_pb2.RuntimeWebSessionEnvelope,
        handler: EnvelopeHandler,
        failure_handler: FailureHandler,
        *,
        timeout_seconds: float,
    ) -> runtime_web_session_pb2.RuntimeWebSessionEnvelope:
        del hello, handler, failure_handler, timeout_seconds
        if self.before_start is not None:
            self.before_start()
        return _accepted(self.offer)

    def activate(self) -> None:
        self.activated = True


class _RecordingWebSocket(RunnerWebSocket):
    def __init__(self) -> None:
        self.events: list[Event] = []

    async def send(self, event: Event) -> None:
        self.events.append(event)

    async def close(self) -> None:
        pass


class _FailingHandshakePool(RunnerWebLoopbackPool):
    async def websocket(
        self,
        *,
        target: bytes,
        headers: tuple[tuple[bytes, bytes], ...],
        port: int,
        timeout_seconds: float,
    ) -> RunnerWebSocket:
        del target, headers, port, timeout_seconds
        raise h11.LocalProtocolError("raw handshake detail")


class _FailingRemoteHandshakePool(RunnerWebLoopbackPool):
    async def websocket(
        self,
        *,
        target: bytes,
        headers: tuple[tuple[bytes, bytes], ...],
        port: int,
        timeout_seconds: float,
    ) -> RunnerWebSocket:
        del target, headers, port, timeout_seconds
        raise WsprotoRemoteProtocolError("raw handshake detail")


def _offer(*, boot: str = "owner-a", lease: str = "lease-a") -> RunnerSessionOffer:
    return RunnerSessionOffer(
        owner=OwnerSessionEpoch(
            owner_boot_id=boot,
            session_lease_id=lease,
            lease_generation=1,
            runtime_id="runtime-a",
            desired_generation=3,
            runner_generation=4,
        ),
        owner_replica_id="control-a",
        connect_address="control-a.internal:8030",
        tls_server_name="runtime-control.internal",
        session_nonce=f"nonce-{lease}",
        protocol_fingerprint=RUNTIME_WEB_PROTOCOL_FINGERPRINT,
        deadline_at=datetime.datetime.now(datetime.UTC)
        + datetime.timedelta(seconds=10),
    )


def _accepted(
    offer: RunnerSessionOffer,
) -> runtime_web_session_pb2.RuntimeWebSessionEnvelope:
    envelope = _envelope(offer)
    envelope.peer_boot_id = offer.owner.owner_boot_id
    envelope.session_accepted.data_frame_bytes = 256 * 1024
    envelope.session_accepted.request_stream_window_bytes = 1024 * 1024
    envelope.session_accepted.response_stream_window_bytes = 1024 * 1024
    envelope.session_accepted.request_session_window_bytes = 8 * 1024 * 1024
    envelope.session_accepted.response_session_window_bytes = 8 * 1024 * 1024
    return envelope


def _manager(
    *,
    client_factory: Callable[[RunnerSessionOffer], GrpcRunnerWebSessionClient] | None,
) -> RunnerWebSessionManager:
    return RunnerWebSessionManager(
        runtime_id="runtime-a",
        runner_boot_id="runner-a",
        accepted_desired_generation=lambda: 3,
        accepted_generation=lambda: 4,
        runner_auth_token="token",
        tls=None,
        allow_insecure=True,
        loopback=RunnerWebLoopbackPool(maximum_connections=2),
        client_factory=client_factory,
        outbound_resources=None,
    )


def _resources(
    *,
    maximum_sessions: int = 1,
    maximum_active_streams: int = 128,
    maximum_application_buffer_bytes: int = 256 * 1024 * 1024,
    maximum_control_buffer_bytes: int = 16 * 1024 * 1024,
    maximum_queued_envelopes: int = 1024,
    maximum_pending_tasks: int = 512,
    maximum_event_loop_lag_milliseconds: int = 250,
    maximum_resident_memory_bytes: int = 1536 * 1024 * 1024,
) -> RunnerWebResourceTracker:
    return RunnerWebResourceTracker(
        limits=RunnerWebHardLimits(
            maximum_sessions=maximum_sessions,
            maximum_active_streams=maximum_active_streams,
            maximum_application_buffer_bytes=maximum_application_buffer_bytes,
            maximum_control_buffer_bytes=maximum_control_buffer_bytes,
            maximum_queued_envelopes=maximum_queued_envelopes,
            maximum_pending_tasks=maximum_pending_tasks,
            maximum_event_loop_lag_milliseconds=(maximum_event_loop_lag_milliseconds),
            maximum_resident_memory_bytes=maximum_resident_memory_bytes,
        ),
        resident_memory_bytes=lambda: 1,
    )


def _dispatcher(manager: RunnerWebSessionManager) -> RunnerWebSessionDispatcher:
    return RunnerWebSessionDispatcher(
        manager,
        resources=_resources(),
        monotonic_clock=lambda: 1.0,
    )


def _stream(
    *,
    offer: RunnerSessionOffer,
    client: GrpcRunnerWebSessionClient,
    session_credit: AbsoluteCreditWindow,
    credit_changed: asyncio.Condition | None = None,
) -> _Stream:
    now = datetime.datetime.now(datetime.UTC)
    return _Stream(
        offer=offer,
        client=client,
        authority=StreamAuthority(
            correlation_id="correlation-a",
            endpoint_id="endpoint-a",
            cycle_id="cycle-a",
            endpoint_authority_revision=1,
            close_barrier=1,
            identity_id="identity-a",
            authentication_session_id="authentication-a",
            user_id="user-a",
            agent_session_id="agent-a",
            runtime_id="runtime-a",
            desired_generation=3,
            runner_generation=4,
            port=8040,
            open_deadline_at=now + datetime.timedelta(seconds=5),
            approval_deadline_at=now + datetime.timedelta(minutes=5),
            transport_deadline_at=now + datetime.timedelta(minutes=4),
        ),
        head=RequestHead(
            protocol=StreamProtocol.WEBSOCKET,
            method=b"GET",
            target=b"/socket",
            headers=(),
        ),
        inbound=_RunnerInboundQueue(_resources()),
        response_credit=HierarchicalCredit(
            stream=AbsoluteCreditWindow(
                initial_bytes=APPROVED_SESSION_PROFILE.response_stream_window_bytes,
                maximum_bytes=APPROVED_SESSION_PROFILE.response_stream_window_bytes,
            ),
            session=session_credit,
        ),
        credit_changed=(
            asyncio.Condition() if credit_changed is None else credit_changed
        ),
    )


def _envelope(
    offer: RunnerSessionOffer,
    *,
    stream_id: int = 0,
) -> runtime_web_session_pb2.RuntimeWebSessionEnvelope:
    owner = offer.owner
    return runtime_web_session_pb2.RuntimeWebSessionEnvelope(
        protocol_fingerprint=RUNTIME_WEB_PROTOCOL_FINGERPRINT,
        session_id=owner.session_lease_id,
        peer_boot_id=owner.owner_boot_id,
        owner_boot_id=owner.owner_boot_id,
        session_lease_id=owner.session_lease_id,
        lease_generation=owner.lease_generation,
        stream_id=stream_id,
    )


async def test_shared_response_credit_wakes_another_stream() -> None:
    offer = _offer()
    client = _RecordingClient()
    manager = _manager(client_factory=None)
    manager.offer = offer
    manager.client = client
    dispatcher = _dispatcher(manager)
    dispatcher.accepting_envelopes = True
    stream_a = _stream(
        offer=offer,
        client=client,
        session_credit=dispatcher.response_session_credit,
        credit_changed=dispatcher.response_credit_changed,
    )
    stream_b = _stream(
        offer=offer,
        client=client,
        session_credit=dispatcher.response_session_credit,
        credit_changed=dispatcher.response_credit_changed,
    )
    stream_a.response_credit.stream.sent_total = 1
    dispatcher.response_session_credit.sent_total = (
        APPROVED_SESSION_PROFILE.response_session_window_bytes
    )
    dispatcher.streams = {1: stream_a, 2: stream_b}

    waiting = asyncio.create_task(dispatcher._reserve(stream_b, 1))
    with pytest.raises(TimeoutError):
        await asyncio.wait_for(asyncio.shield(waiting), timeout=0.01)

    update = _envelope(offer, stream_id=1)
    update.window_update.direction = (
        runtime_web_session_pb2.RUNTIME_WEB_SESSION_DIRECTION_RESPONSE
    )
    update.window_update.stream_consumed_total = 1
    update.window_update.session_consumed_total = 1
    await dispatcher(update)
    await asyncio.wait_for(waiting, timeout=1)

    assert stream_b.response_credit.stream.sent_total == 1


@pytest.mark.parametrize(
    "payload",
    ["window_update", "direction_end", "cancel", "reset", "stream_end"],
)
async def test_late_terminal_control_for_completed_stream_preserves_session(
    payload: str,
) -> None:
    offer = _offer()
    client = _RecordingClient()
    manager = _manager(client_factory=None)
    manager.offer = offer
    manager.client = client
    dispatcher = _dispatcher(manager)
    dispatcher.accepting_envelopes = True
    dispatcher._retire(7)
    envelope = _envelope(offer, stream_id=7)
    if payload == "window_update":
        envelope.window_update.direction = (
            runtime_web_session_pb2.RUNTIME_WEB_SESSION_DIRECTION_RESPONSE
        )
    elif payload == "direction_end":
        envelope.direction_end.direction = (
            runtime_web_session_pb2.RUNTIME_WEB_SESSION_DIRECTION_REQUEST
        )
    elif payload == "cancel":
        envelope.cancel.reason = (
            runtime_web_session_pb2.RUNTIME_WEB_SESSION_CLOSE_REASON_CALLER
        )
    elif payload == "reset":
        envelope.reset.reason = (
            runtime_web_session_pb2.RUNTIME_WEB_SESSION_CLOSE_REASON_CALLER
        )
    else:
        envelope.stream_end.SetInParent()

    await dispatcher(envelope)

    assert dispatcher.accepting_envelopes
    assert dispatcher.tombstone_set == {7}


async def test_tombstoned_stream_rejects_new_data_and_reused_open() -> None:
    offer = _offer()
    client = _RecordingClient()
    manager = _manager(client_factory=None)
    manager.offer = offer
    manager.client = client
    dispatcher = _dispatcher(manager)
    dispatcher.accepting_envelopes = True
    dispatcher.accepting_streams = True
    dispatcher._claim_stream_id(7)
    dispatcher._retire(7)
    data = _envelope(offer, stream_id=7)
    data.frame_sequence = 1
    data.data.direction = runtime_web_session_pb2.RUNTIME_WEB_SESSION_DIRECTION_REQUEST
    data.data.data = b"new"
    opening = _envelope(offer, stream_id=7)
    opening.open.SetInParent()

    with pytest.raises(ValueError, match="tombstoned"):
        await dispatcher(data)
    with pytest.raises(ValueError, match="stream ID"):
        await dispatcher(opening)


async def test_sequential_completed_stream_late_credit_keeps_epoch_active() -> None:
    offer = _offer()
    client = _RecordingClient()
    manager = _manager(client_factory=None)
    manager.offer = offer
    manager.client = client
    dispatcher = _dispatcher(manager)
    dispatcher.accepting_envelopes = True
    dispatcher.accepting_streams = True
    dispatcher._retire(1)
    dispatcher._retire(2)
    late = _envelope(offer, stream_id=1)
    late.window_update.direction = (
        runtime_web_session_pb2.RUNTIME_WEB_SESSION_DIRECTION_RESPONSE
    )

    await dispatcher(late)

    assert dispatcher.accepting_envelopes
    assert dispatcher.accepting_streams
    assert dispatcher.tombstone_set == {1, 2}


def test_runner_stream_tombstones_are_bounded() -> None:
    dispatcher = _dispatcher(_manager(client_factory=None))

    for stream_id in range(1, MAX_STREAM_TOMBSTONES + 2):
        dispatcher._claim_stream_id(stream_id)
        dispatcher._retire(stream_id)

    assert len(dispatcher.tombstones) == MAX_STREAM_TOMBSTONES
    assert 1 not in dispatcher.tombstone_set
    assert MAX_STREAM_TOMBSTONES + 1 in dispatcher.tombstone_set
    with pytest.raises(ValueError, match="monotonic"):
        dispatcher._claim_stream_id(1)
    dispatcher._claim_stream_id(MAX_STREAM_TOMBSTONES + 2)
    assert dispatcher.last_stream_id == MAX_STREAM_TOMBSTONES + 2


async def test_websocket_request_returns_absolute_credit_past_one_window() -> None:
    offer = _offer()
    client = _RecordingClient()
    dispatcher = _dispatcher(_manager(client_factory=None))
    stream = _stream(
        offer=offer,
        client=client,
        session_credit=dispatcher.response_session_credit,
    )
    websocket = _RecordingWebSocket()
    frame_count = 5
    for sequence in range(1, frame_count + 1):
        envelope = _envelope(offer, stream_id=7)
        envelope.frame_sequence = sequence
        envelope.websocket.direction = (
            runtime_web_session_pb2.RUNTIME_WEB_SESSION_DIRECTION_REQUEST
        )
        envelope.websocket.opcode = (
            runtime_web_session_pb2.RUNTIME_WEB_SESSION_WEBSOCKET_OPCODE_BINARY
        )
        envelope.websocket.final = True
        envelope.websocket.data = b"x" * MANDATORY_DATA_FRAME_BYTES
        await stream.inbound.put(envelope)
    end = _envelope(offer, stream_id=7)
    end.direction_end.direction = (
        runtime_web_session_pb2.RUNTIME_WEB_SESSION_DIRECTION_REQUEST
    )
    end.direction_end.final_sequence = frame_count
    await stream.inbound.put(end)

    await dispatcher._ws_from_browser(stream, websocket)

    updates = [item.window_update for item in client.sent]
    expected = frame_count * MANDATORY_DATA_FRAME_BYTES
    assert len(updates) == frame_count
    assert updates[-1].stream_consumed_total == expected
    assert updates[-1].session_consumed_total == expected
    assert len(websocket.events) == frame_count


async def test_replacement_offer_closes_old_stream_before_new_client_starts() -> None:
    first_offer = _offer()
    second_offer = _offer(boot="owner-b", lease="lease-b")
    old_task_finished = asyncio.Event()
    old_task_started = asyncio.Event()
    created: dict[str, _HandshakeClient] = {}

    async def old_work() -> None:
        try:
            old_task_started.set()
            await asyncio.Event().wait()
        finally:
            old_task_finished.set()

    def client_factory(offer: RunnerSessionOffer) -> GrpcRunnerWebSessionClient:
        before_start = None
        if offer == second_offer:

            def before_start() -> None:
                _require_set(old_task_finished)

        client = _HandshakeClient(offer, before_start)
        created[offer.owner.session_lease_id] = client
        return client

    manager = _manager(client_factory=client_factory)
    dispatcher = _dispatcher(manager)
    await dispatcher.handle_offer(first_offer)
    first_client = created["lease-a"]
    stream = _stream(
        offer=first_offer,
        client=first_client,
        session_credit=dispatcher.response_session_credit,
    )
    stream.task = asyncio.create_task(old_work())
    dispatcher.streams[1] = stream
    dispatcher._claim_stream_id(1)
    dispatcher._retire(99)
    await old_task_started.wait()

    await dispatcher.handle_offer(second_offer)

    assert old_task_finished.is_set()
    assert first_client.closed
    assert manager.offer == second_offer
    assert created["lease-b"].activated
    assert dispatcher.streams == {}
    assert dispatcher.tombstone_set == set()
    assert dispatcher.last_stream_id == 0
    await dispatcher.close()
    await manager.close()


async def test_pinned_stream_reset_never_uses_replacement_client() -> None:
    first_offer = _offer()
    second_offer = _offer(boot="owner-b", lease="lease-b")
    first_client = _RecordingClient()
    second_client = _RecordingClient()
    manager = _manager(client_factory=None)
    manager.offer = second_offer
    manager.client = second_client
    dispatcher = _dispatcher(manager)
    stream = _stream(
        offer=first_offer,
        client=first_client,
        session_credit=dispatcher.response_session_credit,
    )

    await dispatcher._reset(1, CloseReason.GENERATION_REPLACED, stream=stream)

    assert len(first_client.sent) == 1
    assert first_client.sent[0].session_id == "lease-a"
    assert first_client.sent[0].WhichOneof("payload") == "reset"
    assert second_client.sent == []


async def test_go_away_refuses_new_streams_with_service_drain_reset() -> None:
    offer = _offer()
    client = _RecordingClient()
    manager = _manager(client_factory=None)
    manager.offer = offer
    manager.client = client
    dispatcher = _dispatcher(manager)
    dispatcher.accepting_envelopes = True
    dispatcher.accepting_streams = True
    go_away = _envelope(offer)
    go_away.go_away.last_accepted_stream_id = 4
    go_away.go_away.reason = (
        runtime_web_session_pb2.RUNTIME_WEB_SESSION_CLOSE_REASON_SERVICE_DRAIN
    )
    go_away.go_away.drain_deadline_at.FromDatetime(
        datetime.datetime.now(datetime.UTC) + datetime.timedelta(seconds=1)
    )

    await dispatcher(go_away)
    await dispatcher.handle_offer(offer)
    opening = _envelope(offer, stream_id=5)
    opening.open.SetInParent()
    await dispatcher(opening)

    assert not dispatcher.accepting_streams
    assert len(client.sent) == 1
    assert client.sent[0].stream_id == 5
    assert client.sent[0].reset.reason == (
        runtime_web_session_pb2.RUNTIME_WEB_SESSION_CLOSE_REASON_SERVICE_DRAIN
    )
    await dispatcher.close()


async def test_receiver_eof_retires_manager_and_dispatcher_work() -> None:
    offer = _offer()
    release = asyncio.Event()
    created: list[GrpcRunnerWebSessionClient] = []

    async def transport(
        requests: AsyncIterator[runtime_web_session_pb2.RuntimeWebSessionEnvelope],
        *,
        metadata: object = None,
    ) -> AsyncIterator[runtime_web_session_pb2.RuntimeWebSessionEnvelope]:
        del metadata
        await anext(requests)
        yield _accepted(offer)
        await release.wait()

    def client_factory(candidate: RunnerSessionOffer) -> GrpcRunnerWebSessionClient:
        assert candidate == offer
        client = GrpcRunnerWebSessionClient(
            transport,
            runner_auth_token="token",
            channel=None,
            outbound_resources=None,
        )
        created.append(client)
        return client

    manager = _manager(client_factory=client_factory)
    dispatcher = _dispatcher(manager)
    await dispatcher.handle_offer(offer)
    client = created[0]
    stream = _stream(
        offer=offer,
        client=client,
        session_credit=dispatcher.response_session_credit,
        credit_changed=dispatcher.response_credit_changed,
    )

    async def wait_for_failure() -> None:
        await asyncio.Event().wait()

    stream_task = asyncio.create_task(wait_for_failure())
    stream.task = stream_task
    dispatcher.streams[1] = stream
    release.set()
    assert client.receiver_task is not None
    await client.receiver_task

    assert manager.offer is None
    assert manager.client is None
    assert not dispatcher.accepting_envelopes
    assert not dispatcher.accepting_streams
    assert dispatcher.streams == {}
    assert stream_task.done()


async def test_go_away_deadline_marks_pending_stream_service_drain() -> None:
    offer = _offer()
    client = _RecordingClient()
    dispatcher = _dispatcher(_manager(client_factory=None))
    stream = _stream(
        offer=offer,
        client=client,
        session_credit=dispatcher.response_session_credit,
    )
    observed: list[CloseReason] = []
    started = asyncio.Event()

    async def active() -> None:
        try:
            started.set()
            await asyncio.Event().wait()
        finally:
            observed.append(stream.close_reason)

    stream.task = asyncio.create_task(active())
    dispatcher.streams[1] = stream
    await started.wait()
    await dispatcher._drain(datetime.datetime.now(datetime.UTC))

    assert observed == [CloseReason.SERVICE_DRAIN]


def test_request_head_rejects_unspecified_protocol() -> None:
    message = runtime_web_session_pb2.RuntimeWebSessionRequestHead(
        protocol=runtime_web_session_pb2.RUNTIME_WEB_SESSION_PROTOCOL_UNSPECIFIED,
        method=b"GET",
        target=b"/",
    )

    with pytest.raises(ValueError, match="protocol"):
        _head(message)


@pytest.mark.parametrize(
    "pool_type",
    [_FailingHandshakePool, _FailingRemoteHandshakePool],
)
async def test_websocket_protocol_failure_emits_stream_reset(
    caplog: pytest.LogCaptureFixture,
    pool_type: type[RunnerWebLoopbackPool],
) -> None:
    offer = _offer()
    client = _RecordingClient()
    manager = _manager(client_factory=None)
    manager.loopback = pool_type(maximum_connections=1)
    stream = _stream(
        offer=offer,
        client=client,
        session_credit=AbsoluteCreditWindow(
            initial_bytes=APPROVED_SESSION_PROFILE.response_session_window_bytes,
            maximum_bytes=APPROVED_SESSION_PROFILE.response_session_window_bytes,
        ),
    )
    dispatcher = _dispatcher(manager)
    dispatcher.streams[1] = stream
    caplog.set_level(
        logging.WARNING, logger="azents_runtime_runner.web_session_dispatcher"
    )

    await dispatcher._run(1, stream)

    assert dispatcher.streams == {}
    assert dispatcher.tombstone_set == {1}
    assert len(client.sent) == 1
    assert client.sent[0].WhichOneof("payload") == "reset"
    assert client.sent[0].reset.reason == (
        runtime_web_session_pb2.RUNTIME_WEB_SESSION_CLOSE_REASON_PROTOCOL_VIOLATION
    )
    assert "Runtime Web Runner WebSocket protocol failed" in caplog.text
    assert "raw handshake detail" not in caplog.text


def test_runner_resource_tracker_rejects_and_releases_process_ceilings() -> None:
    resources = _resources(
        maximum_sessions=1,
        maximum_active_streams=1,
        maximum_application_buffer_bytes=4,
        maximum_control_buffer_bytes=64,
        maximum_queued_envelopes=1,
        maximum_pending_tasks=1,
        maximum_resident_memory_bytes=8,
    )
    data = runtime_web_session_pb2.RuntimeWebSessionEnvelope()
    data.data.data = b"four"

    assert resources.try_open_session()
    assert not resources.try_open_session()
    assert resources.try_open_stream(StreamProtocol.HTTP)
    assert not resources.try_open_stream(StreamProtocol.WEBSOCKET)
    assert resources.try_begin_tasks()
    assert not resources.try_begin_tasks()
    assert resources.try_reserve_envelope(data)
    assert not resources.try_reserve_envelope(data)

    resources.release_envelope(data)
    resources.end_tasks()
    resources.close_stream(StreamProtocol.HTTP)
    resources.close_session()
    snapshot = resources.snapshot()
    assert snapshot.active_sessions == 0
    assert snapshot.active_streams == 0
    assert snapshot.application_buffer_bytes == 0
    assert snapshot.queued_envelopes == 0
    assert snapshot.pending_tasks == 0


async def test_runner_inbound_queue_rejects_without_blocking_other_streams() -> None:
    offer = _offer()
    client = _RecordingClient()
    manager = _manager(client_factory=None)
    manager.offer = offer
    manager.client = client
    resources = _resources(maximum_queued_envelopes=1)
    dispatcher = RunnerWebSessionDispatcher(
        manager,
        resources=resources,
        monotonic_clock=lambda: 1.0,
    )
    dispatcher.accepting_envelopes = True
    stream = _stream(
        offer=offer,
        client=client,
        session_credit=dispatcher.response_session_credit,
    )
    stream.inbound = _RunnerInboundQueue(resources)
    cancelled = asyncio.Event()
    started = asyncio.Event()

    async def active() -> None:
        try:
            started.set()
            await asyncio.Event().wait()
        finally:
            cancelled.set()

    stream.task = asyncio.create_task(active())
    await started.wait()
    dispatcher.streams[7] = stream
    first = _envelope(offer, stream_id=7)
    first.frame_sequence = 1
    first.data.direction = runtime_web_session_pb2.RUNTIME_WEB_SESSION_DIRECTION_REQUEST
    first.data.data = b"one"
    second = _envelope(offer, stream_id=7)
    second.frame_sequence = 2
    second.data.direction = (
        runtime_web_session_pb2.RUNTIME_WEB_SESSION_DIRECTION_REQUEST
    )
    second.data.data = b"two"

    assert await stream.inbound.put(first)
    await dispatcher(second)
    await cancelled.wait()

    assert stream.close_reason is CloseReason.RESOURCE_EXHAUSTED
    assert resources.snapshot().queued_envelopes == 1
    await stream.inbound.close()
    assert resources.snapshot().queued_envelopes == 0


def test_runner_openmetrics_are_bounded_content_free_aggregates() -> None:
    resources = _resources()
    resources.record_open_accepted(StreamProtocol.HTTP, 0.25)
    resources.record_open_rejected(CloseReason.RESOURCE_EXHAUSTED)
    resources.record_frame(StreamProtocol.HTTP, "request", 4)
    resources.record_frame(StreamProtocol.HTTP, "response", 8)
    resources.record_ttfb(0.5)
    resources.record_close(
        CloseReason.CALLER,
        duration_seconds=2.0,
        application_bytes=12,
    )
    resources.credit_stalls = 1
    resources.credit_stall_seconds = 0.75
    resources.heartbeats = 2
    resources.go_aways = 1
    resources.epoch_transitions = 1

    snapshot = resources.system_metrics_snapshot()
    rendered = resources.render_openmetrics()

    assert snapshot.maximum_sessions == resources.limits.maximum_sessions
    assert snapshot.maximum_active_streams == resources.limits.maximum_active_streams
    assert 'protocol="http",outcome="accepted"} 1' in rendered
    assert 'reason="resource_exhausted"} 1' in rendered
    assert "runtime_web_runner_ttfb_seconds_sum 0.5" in rendered
    assert "runtime_web_runner_goodput_bytes_per_second 6.0" in rendered
    assert "runtime_web_runner_credit_stall_seconds_total 0.75" in rendered
    assert "runtime_web_runner_heartbeat_total 2" in rendered
    for forbidden in (
        "runtime_id=",
        "session_id=",
        "endpoint=",
        'path="/',
        "query=",
        "user=",
    ):
        assert forbidden not in rendered


def _require_set(event: asyncio.Event) -> None:
    if not event.is_set():
        raise AssertionError("old Runner Web stream must finish before replacement")
