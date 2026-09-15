"""Tests for the inactive persistent one-hop Runtime Web relay."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterable, AsyncIterator, Sequence

import pytest
from azents_runtime_control.proto import runtime_web_session_pb2
from azents_runtime_control.runtime_web_session import (
    RUNTIME_WEB_PROTOCOL_FINGERPRINT,
    OwnerSessionEpoch,
)

from azents.runtime.web_session_broker import BrokerTarget
from azents.runtime.web_session_relay import (
    GrpcPersistentControlRelay,
    RelaySessionKey,
    RuntimeWebRelayPool,
)


def _owner(owner_boot_id: str = "owner") -> OwnerSessionEpoch:
    return OwnerSessionEpoch(
        owner_boot_id=owner_boot_id,
        session_lease_id=f"{owner_boot_id}-lease",
        lease_generation=1,
        runtime_id="runtime",
        desired_generation=1,
        runner_generation=1,
    )


class _Connection:
    def __init__(self, *, fail: bool = False) -> None:
        self.fail = fail
        self.sent: list[runtime_web_session_pb2.RuntimeWebSessionEnvelope] = []
        self.closed = asyncio.Event()

    async def send(
        self, envelope: runtime_web_session_pb2.RuntimeWebSessionEnvelope
    ) -> None:
        if self.fail:
            raise RuntimeError("relay failed")
        copied = runtime_web_session_pb2.RuntimeWebSessionEnvelope()
        copied.CopyFrom(envelope)
        self.sent.append(copied)

    async def close(self) -> None:
        self.closed.set()

    async def wait_closed(self) -> None:
        await self.closed.wait()


class _Connector:
    def __init__(self, connections: list[_Connection]) -> None:
        self.connections = connections
        self.keys: list[RelaySessionKey] = []

    async def __call__(self, key: RelaySessionKey) -> _Connection:
        self.keys.append(key)
        return self.connections[len(self.keys) - 1]


def _source_envelope(
    stream_id: int,
    *,
    source_session_id: str = "gateway-session",
    source_peer_boot_id: str = "gateway-boot",
) -> runtime_web_session_pb2.RuntimeWebSessionEnvelope:
    return runtime_web_session_pb2.RuntimeWebSessionEnvelope(
        protocol_fingerprint=RUNTIME_WEB_PROTOCOL_FINGERPRINT,
        session_id=source_session_id,
        peer_boot_id=source_peer_boot_id,
        stream_id=stream_id,
        open=runtime_web_session_pb2.RuntimeWebSessionOpen(),
    )


def _owner_envelope(
    owner: OwnerSessionEpoch,
    *,
    stream_id: int,
) -> runtime_web_session_pb2.RuntimeWebSessionEnvelope:
    return runtime_web_session_pb2.RuntimeWebSessionEnvelope(
        protocol_fingerprint=RUNTIME_WEB_PROTOCOL_FINGERPRINT,
        session_id=owner.session_lease_id,
        peer_boot_id=owner.owner_boot_id,
        owner_boot_id=owner.owner_boot_id,
        session_lease_id=owner.session_lease_id,
        lease_generation=owner.lease_generation,
        stream_id=stream_id,
    )


def _pool(connector: _Connector) -> RuntimeWebRelayPool:
    return RuntimeWebRelayPool(
        connector=connector,
        maximum_sessions=1,
        peer_boot_id="accepting-control",
    )


@pytest.mark.asyncio
async def test_relay_maps_same_source_stream_id_without_collision() -> None:
    connection = _Connection()
    connector = _Connector([connection])
    pool = _pool(connector)
    target = BrokerTarget(owner=_owner(), local=False, relay_count=1)

    first, second = await asyncio.gather(
        pool.forward(target=target, envelope=_source_envelope(1)),
        pool.forward(
            target=target,
            envelope=_source_envelope(
                1,
                source_session_id="gateway-session-b",
                source_peer_boot_id="gateway-boot-b",
            ),
        ),
    )

    assert len(connector.keys) == 1
    assert first.relay_stream_id != second.relay_stream_id
    assert [message.stream_id for message in connection.sent] == [1, 2]
    for message in connection.sent:
        assert message.session_id == "owner-lease"
        assert message.peer_boot_id == "accepting-control"
        assert message.owner_boot_id == "owner"

    response = _owner_envelope(_owner(), stream_id=second.relay_stream_id)
    response.reset.CopyFrom(
        runtime_web_session_pb2.RuntimeWebSessionReset(
            reason=runtime_web_session_pb2.RUNTIME_WEB_SESSION_CLOSE_REASON_CALLER
        )
    )
    translated = await pool.route_response(
        key=RelaySessionKey(_owner(), RUNTIME_WEB_PROTOCOL_FINGERPRINT),
        envelope=response,
    )
    assert translated is not None
    assert translated.session_id == "gateway-session-b"
    assert translated.peer_boot_id == "accepting-control"
    assert translated.stream_id == 1
    assert (
        await pool.route_response(
            key=RelaySessionKey(_owner(), RUNTIME_WEB_PROTOCOL_FINGERPRINT),
            envelope=response,
        )
        is None
    )
    with pytest.raises(ValueError, match="not reusable"):
        await pool.forward(
            target=target,
            envelope=_source_envelope(
                1,
                source_session_id="gateway-session-b",
                source_peer_boot_id="gateway-boot-b",
            ),
        )
    await pool.close()


@pytest.mark.asyncio
async def test_relay_failure_retires_without_replay() -> None:
    failed = _Connection(fail=True)
    replacement = _Connection()
    connector = _Connector([failed, replacement])
    pool = _pool(connector)
    target = BrokerTarget(owner=_owner(), local=False, relay_count=1)

    with pytest.raises(RuntimeError, match="relay failed"):
        await pool.forward(target=target, envelope=_source_envelope(1))
    assert failed.closed.is_set()
    assert replacement.sent == []
    await pool.forward(target=target, envelope=_source_envelope(2))
    assert [message.stream_id for message in replacement.sent] == [1]
    await pool.close()


@pytest.mark.asyncio
async def test_relay_rejects_local_capacity_and_bad_source_identity() -> None:
    first = _Connection()
    connector = _Connector([first])
    pool = _pool(connector)
    local = BrokerTarget(owner=_owner(), local=True, relay_count=0)
    with pytest.raises(ValueError, match="one remote Owner hop"):
        await pool.forward(target=local, envelope=_source_envelope(1))

    remote = BrokerTarget(owner=_owner(), local=False, relay_count=1)
    await pool.forward(target=remote, envelope=_source_envelope(1))
    other = BrokerTarget(owner=_owner("other"), local=False, relay_count=1)
    with pytest.raises(RuntimeError, match="capacity"):
        await pool.forward(target=other, envelope=_source_envelope(2))
    bad = _source_envelope(3)
    bad.session_id = ""
    with pytest.raises(ValueError, match="source stream identity"):
        await pool.forward(target=remote, envelope=bad)
    await pool.close()


@pytest.mark.asyncio
async def test_relay_rejects_fingerprint_and_owner_response_mismatch() -> None:
    connection = _Connection()
    connector = _Connector([connection])
    pool = _pool(connector)
    target = BrokerTarget(owner=_owner(), local=False, relay_count=1)
    incompatible = _source_envelope(1)
    incompatible.protocol_fingerprint = "incompatible"
    with pytest.raises(ValueError, match="fingerprint"):
        await pool.forward(target=target, envelope=incompatible)
    binding = await pool.forward(target=target, envelope=_source_envelope(2))
    stale = _owner_envelope(_owner(), stream_id=binding.relay_stream_id)
    stale.peer_boot_id = "stale-owner"
    with pytest.raises(ValueError, match="identity"):
        await pool.route_response(
            key=RelaySessionKey(_owner(), RUNTIME_WEB_PROTOCOL_FINGERPRINT),
            envelope=stale,
        )
    await pool.close()


class _RelayDuplexStream:
    def __init__(self, key: RelaySessionKey) -> None:
        self.key = key
        self.sent: asyncio.Queue[runtime_web_session_pb2.RuntimeWebSessionEnvelope] = (
            asyncio.Queue()
        )
        self.responses: asyncio.Queue[
            runtime_web_session_pb2.RuntimeWebSessionEnvelope
        ] = asyncio.Queue()

    def __call__(
        self,
        request_iterator: AsyncIterator[
            runtime_web_session_pb2.RuntimeWebSessionEnvelope
        ],
        /,
        *,
        metadata: Sequence[tuple[str, str]] | None = None,
    ) -> AsyncIterable[runtime_web_session_pb2.RuntimeWebSessionEnvelope]:
        assert metadata is None

        async def exchange() -> AsyncIterator[
            runtime_web_session_pb2.RuntimeWebSessionEnvelope
        ]:
            hello = await anext(request_iterator)
            await self.sent.put(hello)
            accepted = _owner_envelope(self.key.owner, stream_id=0)
            accepted.session_accepted.CopyFrom(
                runtime_web_session_pb2.RuntimeWebSessionAccepted()
            )
            yield accepted
            async for request in request_iterator:
                await self.sent.put(request)
                yield await self.responses.get()

        return exchange()


@pytest.mark.asyncio
async def test_concrete_grpc_relay_persists_and_pins_owner_peer() -> None:
    owner = _owner()
    key = RelaySessionKey(owner, RUNTIME_WEB_PROTOCOL_FINGERPRINT)
    stream = _RelayDuplexStream(key)
    delivered = asyncio.Event()

    async def handler(
        envelope: runtime_web_session_pb2.RuntimeWebSessionEnvelope,
    ) -> None:
        assert envelope.stream_id == 7
        delivered.set()

    hello = _owner_envelope(owner, stream_id=0)
    hello.peer_boot_id = "accepting-control"
    hello.hello.CopyFrom(
        runtime_web_session_pb2.RuntimeWebSessionHello(
            role=runtime_web_session_pb2.RUNTIME_WEB_SESSION_PEER_ROLE_CONTROL,
            runtime_id=owner.runtime_id,
            desired_generation=owner.desired_generation,
            runner_generation=owner.runner_generation,
        )
    )
    relay = await GrpcPersistentControlRelay.connect(
        key=key,
        stream=stream,
        hello=hello,
        handler=handler,
        timeout_seconds=1,
    )
    assert (await stream.sent.get()).WhichOneof("payload") == "hello"
    outbound = _owner_envelope(owner, stream_id=7)
    outbound.peer_boot_id = "accepting-control"
    outbound.cancel.CopyFrom(
        runtime_web_session_pb2.RuntimeWebSessionCancel(
            reason=runtime_web_session_pb2.RUNTIME_WEB_SESSION_CLOSE_REASON_CALLER
        )
    )
    await relay.send(outbound)
    assert (await stream.sent.get()).stream_id == 7
    response = _owner_envelope(owner, stream_id=7)
    response.reset.CopyFrom(
        runtime_web_session_pb2.RuntimeWebSessionReset(
            reason=runtime_web_session_pb2.RUNTIME_WEB_SESSION_CLOSE_REASON_CALLER
        )
    )
    await stream.responses.put(response)
    await asyncio.wait_for(delivered.wait(), timeout=1)
    await relay.close()
