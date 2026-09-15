"""Tests for the inactive Runtime Web Gateway session pool."""

from __future__ import annotations

import asyncio
import dataclasses
from datetime import UTC, datetime, timedelta

import pytest
from azents_runtime_control.proto import runtime_web_session_pb2
from azents_runtime_control.runtime_web_flow import AbsoluteCreditWindow
from azents_runtime_control.runtime_web_session import (
    APPROVED_SESSION_PROFILE,
    SESSION_WINDOW_BYTES,
    CloseReason,
    Header,
    OwnerSessionEpoch,
    RequestHead,
    SessionIdentity,
    SessionPeerRole,
    StreamAuthority,
    StreamDirection,
    StreamProtocol,
)

from azents.runtime_web_gateway.web_session_pool import (
    GatewayStreamHandler,
    RuntimeWebGatewaySessionPool,
)


class _Transport:
    def __init__(self) -> None:
        self.request_session_credit = AbsoluteCreditWindow(
            initial_bytes=SESSION_WINDOW_BYTES,
            maximum_bytes=SESSION_WINDOW_BYTES,
        )
        self.response_session_credit = AbsoluteCreditWindow(
            initial_bytes=SESSION_WINDOW_BYTES,
            maximum_bytes=SESSION_WINDOW_BYTES,
        )

    async def bind(
        self,
        stream_id: int,
        handler: GatewayStreamHandler,
    ) -> None:
        pass

    async def unbind(self, stream_id: int) -> None:
        pass

    async def send(
        self, envelope: runtime_web_session_pb2.RuntimeWebSessionEnvelope
    ) -> None:
        pass


_TRANSPORT = _Transport()


def _identity(session_id: str, *, nonce: str | None = None) -> SessionIdentity:
    return SessionIdentity(
        session_id=session_id,
        peer_boot_id=f"{session_id}-boot",
        role=SessionPeerRole.GATEWAY,
        owner=None,
        session_nonce=nonce or f"{session_id}-nonce",
        deadline_at=datetime.now(UTC) + timedelta(minutes=1),
    )


def _authority() -> StreamAuthority:
    now = datetime.now(UTC)
    return StreamAuthority(
        correlation_id="correlation",
        endpoint_id="endpoint",
        cycle_id="cycle",
        endpoint_authority_revision=1,
        close_barrier=1,
        identity_id="identity",
        authentication_session_id="auth-session",
        user_id="user",
        agent_session_id="agent-session",
        runtime_id="runtime",
        desired_generation=1,
        runner_generation=1,
        port=6006,
        open_deadline_at=now + timedelta(seconds=10),
        transport_deadline_at=now + timedelta(minutes=1),
        approval_deadline_at=now + timedelta(hours=1),
    )


def _head() -> RequestHead:
    return RequestHead(
        protocol=StreamProtocol.HTTP,
        method=b"GET",
        target=b"/asset.js?raw=%ff",
        headers=(Header(b"x-raw", b"\xff"),),
    )


async def _complete(pool: RuntimeWebGatewaySessionPool, stream_id: int) -> None:
    binding = await pool.open(
        stream_id=stream_id,
        authority=_authority(),
        request_head=_head(),
    )
    binding.state.accept()
    binding.state.end_direction(StreamDirection.REQUEST, 0)
    binding.state.receive_response_head(200, ())
    binding.state.end_direction(StreamDirection.RESPONSE, 0)
    binding.state.finish()
    assert await pool.release(binding)


@pytest.mark.asyncio
async def test_pool_balances_active_streams_and_releases_terminal_work() -> None:
    pool = RuntimeWebGatewaySessionPool(maximum_sessions=2)
    registrations = [
        await pool.register(
            identity=_identity(session_id),
            profile=APPROVED_SESSION_PROFILE,
            transport=_TRANSPORT,
        )
        for session_id in ("a", "b")
    ]

    first = await pool.open(stream_id=1, authority=_authority(), request_head=_head())
    second = await pool.open(stream_id=2, authority=_authority(), request_head=_head())
    assert (first.session_id, second.session_id) == ("a", "b")
    assert first.state.request_head.target == b"/asset.js?raw=%ff"
    assert first.state.request_head.headers[0].value == b"\xff"

    first.state.reset(CloseReason.CALLER)
    assert await pool.release(first)
    third = await pool.open(stream_id=3, authority=_authority(), request_head=_head())
    assert third.session_id == "a"
    assert await pool.close_session(registrations[0]) == (third,)


@pytest.mark.asyncio
async def test_pool_returns_only_active_bindings_when_session_fails() -> None:
    pool = RuntimeWebGatewaySessionPool(maximum_sessions=1)
    registration = await pool.register(
        identity=_identity("a"),
        profile=APPROVED_SESSION_PROFILE,
        transport=_TRANSPORT,
    )
    await _complete(pool, 1)
    active = await pool.open(
        stream_id=2,
        authority=_authority(),
        request_head=_head(),
    )
    assert await pool.close_session(registration) == (active,)


@pytest.mark.asyncio
async def test_pool_fences_duplicate_reuse_capacity_and_delayed_close() -> None:
    pool = RuntimeWebGatewaySessionPool(maximum_sessions=1)
    old = await pool.register(
        identity=_identity("a"),
        profile=APPROVED_SESSION_PROFILE,
        transport=_TRANSPORT,
    )
    with pytest.raises(ValueError, match="not reusable"):
        await pool.register(
            identity=_identity("a", nonce="replacement"),
            profile=APPROVED_SESSION_PROFILE,
            transport=_TRANSPORT,
        )
    with pytest.raises(ValueError, match="capacity"):
        await pool.register(
            identity=_identity("b"),
            profile=APPROVED_SESSION_PROFILE,
            transport=_TRANSPORT,
        )
    assert await pool.close_session(old) == ()
    with pytest.raises(ValueError, match="not reusable"):
        await pool.register(
            identity=_identity("a", nonce="later"),
            profile=APPROVED_SESSION_PROFILE,
            transport=_TRANSPORT,
        )
    replacement = await pool.register(
        identity=_identity("b"),
        profile=APPROVED_SESSION_PROFILE,
        transport=_TRANSPORT,
    )
    assert await pool.close_session(old) == ()
    binding = await pool.open(
        stream_id=1,
        authority=_authority(),
        request_head=_head(),
    )
    assert binding.registration == replacement


@pytest.mark.asyncio
async def test_pool_serializes_concurrent_open_and_close() -> None:
    pool = RuntimeWebGatewaySessionPool(maximum_sessions=1)
    registration = await pool.register(
        identity=_identity("a"),
        profile=APPROVED_SESSION_PROFILE,
        transport=_TRANSPORT,
    )
    opens = [
        asyncio.create_task(
            pool.open(
                stream_id=stream_id,
                authority=_authority(),
                request_head=_head(),
            )
        )
        for stream_id in range(1, 9)
    ]
    bindings = await asyncio.gather(*opens)
    failed = await pool.close_session(registration)
    assert failed == tuple(bindings)


@pytest.mark.asyncio
async def test_pool_rejects_non_gateway_and_missing_active_session() -> None:
    pool = RuntimeWebGatewaySessionPool(maximum_sessions=1)
    with pytest.raises(ValueError, match="Gateway session"):
        await pool.register(
            identity=dataclasses.replace(
                _identity("runner"),
                role=SessionPeerRole.RUNNER,
                owner=OwnerSessionEpoch(
                    owner_boot_id="owner",
                    session_lease_id="lease",
                    lease_generation=1,
                    runtime_id="runtime",
                    desired_generation=1,
                    runner_generation=1,
                ),
            ),
            profile=APPROVED_SESSION_PROFILE,
            transport=_TRANSPORT,
        )
    with pytest.raises(RuntimeError, match="no active"):
        await pool.open(
            stream_id=1,
            authority=_authority(),
            request_head=_head(),
        )
