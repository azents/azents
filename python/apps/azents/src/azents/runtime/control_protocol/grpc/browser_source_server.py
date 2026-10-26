"""API-only Browser source RPC on the existing ordinary Control listener."""

import asyncio
import secrets
from collections.abc import AsyncIterator, Awaitable, Callable
from datetime import datetime, timedelta

import grpc
from azents_runtime_control.browser_source_contract import (
    BrowserScopeState,
    BrowserSourceCredentialRequest,
)
from azents_runtime_control.proto import runtime_stream_session_pb2 as pb
from azents_runtime_control.proto import runtime_stream_session_pb2_grpc as rpc
from azents_runtime_control.runtime_stream_session import (
    MAX_ENVELOPE_BYTES,
    RUNTIME_STREAM_PROTOCOL_FINGERPRINT,
    BrowserStreamAuthority,
)

from azents.core.runtime_browser_source_credential import (
    RuntimeBrowserSourceCredentialVerifier,
)
from azents.runtime.control_protocol.grpc.runtime_stream_session_server import (
    RuntimeStreamControlDataPlane,
    _acceptance,
    _create_control_task,
)

ScopeValidator = Callable[[BrowserStreamAuthority], Awaitable[BrowserScopeState]]


class RuntimeBrowserSourceGrpcServicer(rpc.RuntimeBrowserSourceSessionServicer):
    """Consume a connection-local proof once, then one immutable Browser OPEN."""

    def __init__(
        self,
        *,
        data_plane: RuntimeStreamControlDataPlane | None,
        verifier: RuntimeBrowserSourceCredentialVerifier,
        validate_scope: ScopeValidator,
        clock: Callable[[], datetime],
    ) -> None:
        self.data_plane = data_plane
        self.verifier = verifier
        self.validate_scope = validate_scope
        self.clock = clock

    async def Connect(
        self,
        request_iterator: AsyncIterator[pb.RuntimeStreamSessionEnvelope],
        context: grpc.aio.ServicerContext,
    ) -> AsyncIterator[pb.RuntimeStreamSessionEnvelope]:
        plane = self.data_plane
        if plane is None:
            await context.abort(
                grpc.StatusCode.UNAVAILABLE, "Browser common transport is unavailable"
            )
            return
        if not plane.resources.try_begin_task():
            await context.abort(
                grpc.StatusCode.RESOURCE_EXHAUSTED,
                "Browser source setup capacity is exhausted",
            )
            return
        source = None
        reader = None
        authority: BrowserStreamAuthority | None = None
        try:
            setup_deadline = asyncio.get_running_loop().time() + 10
            nonce = secrets.token_hex(32)
            deadline = self.clock() + timedelta(seconds=10)
            challenge = pb.RuntimeStreamSessionEnvelope(
                protocol_fingerprint=RUNTIME_STREAM_PROTOCOL_FINGERPRINT,
                peer_boot_id=plane.control_boot_id,
                browser_source_challenge=pb.RuntimeBrowserSourceChallenge(
                    nonce=nonce, control_boot_id=plane.control_boot_id
                ),
            )
            challenge.browser_source_challenge.deadline_at.FromDatetime(deadline)
            yield challenge
            try:
                async with asyncio.timeout_at(setup_deadline) as admission:
                    proof_envelope = await anext(request_iterator)
                    if (
                        not 0 < proof_envelope.ByteSize() <= MAX_ENVELOPE_BYTES
                        or proof_envelope.WhichOneof("payload")
                        != "browser_source_proof"
                        or proof_envelope.protocol_fingerprint
                        != RUNTIME_STREAM_PROTOCOL_FINGERPRINT
                    ):
                        raise ValueError("Browser source proof envelope is invalid")
                    proof = proof_envelope.browser_source_proof
                    request = BrowserSourceCredentialRequest(
                        nonce,
                        plane.control_boot_id,
                        deadline,
                        proof.hello,
                        proof.admitted_open,
                    )
                    self.verifier.verify(proof.credential, request=request)
                    authority = request.validate(self.clock())
                    admission.reschedule(
                        min(
                            setup_deadline,
                            asyncio.get_running_loop().time()
                            + max(
                                0,
                                (
                                    authority.open_deadline_at - self.clock()
                                ).total_seconds(),
                            ),
                        )
                    )
                    try:
                        async with asyncio.timeout(2):
                            scope = await self.validate_scope(authority)
                    except asyncio.CancelledError:
                        raise
                    except TimeoutError:
                        scope = (
                            BrowserScopeState.EXPIRED
                            if self.clock() >= authority.open_deadline_at
                            else BrowserScopeState.UNAVAILABLE
                        )
                    if scope is not BrowserScopeState.CURRENT:
                        await context.abort(
                            {
                                BrowserScopeState.UNAVAILABLE: (
                                    grpc.StatusCode.UNAVAILABLE
                                ),
                                BrowserScopeState.REVOKED: (
                                    grpc.StatusCode.PERMISSION_DENIED
                                ),
                                BrowserScopeState.EXPIRED: (
                                    grpc.StatusCode.DEADLINE_EXCEEDED
                                ),
                            }[scope],
                            "Browser scope is no longer current",
                        )
                        return
                    request.validate(self.clock())
                    source = await plane.register_source(
                        session_id=request.hello.session_id,
                        peer_boot_id=request.hello.peer_boot_id,
                        owner=None,
                        browser_authority=authority,
                    )
                    request.validate(self.clock())
                    await plane.handle(source, request.open_envelope)
            except TimeoutError:
                await context.abort(
                    grpc.StatusCode.UNAUTHENTICATED
                    if authority is None
                    else grpc.StatusCode.DEADLINE_EXCEEDED
                    if self.clock() >= authority.open_deadline_at
                    else grpc.StatusCode.UNAVAILABLE,
                    "Browser source admission timed out",
                )
                return
            except ValueError, StopAsyncIteration:
                await context.abort(
                    grpc.StatusCode.UNAUTHENTICATED,
                    "Browser source admission is invalid or expired",
                )
                return
            yield _acceptance(request.hello, plane.control_boot_id, self.clock)

            async def read() -> None:
                assert source is not None
                try:
                    async for envelope in request_iterator:
                        if envelope.WhichOneof("payload") in {
                            "open",
                            "hello",
                            "browser_source_proof",
                            "browser_source_challenge",
                        }:
                            raise ValueError(
                                "Browser source admission cannot be reused"
                            )
                        await plane.handle(source, envelope)
                finally:
                    await source.queue.close()

            reader = _create_control_task(
                plane.resources, read, name="browser-source-reader"
            )
            async with asyncio.timeout(
                max(0, (authority.transport_deadline_at - self.clock()).total_seconds())
            ):
                async for response in source.queue:
                    yield response
        except TimeoutError:
            await context.abort(
                grpc.StatusCode.DEADLINE_EXCEEDED, "Browser source attachment expired"
            )
        finally:
            try:
                if reader is not None:
                    reader.cancel()
                    await asyncio.gather(reader, return_exceptions=True)
                if source is not None:
                    await plane.unregister_source(source)
            finally:
                plane.resources.end_task()


def add_runtime_browser_source_servicer(
    server: grpc.aio.Server,
    *,
    data_plane: RuntimeStreamControlDataPlane | None,
    verifier: RuntimeBrowserSourceCredentialVerifier,
    validate_scope: ScopeValidator,
    clock: Callable[[], datetime],
) -> None:
    """Register even without a common plane, returning explicit unavailability."""
    rpc.add_RuntimeBrowserSourceSessionServicer_to_server(
        RuntimeBrowserSourceGrpcServicer(
            data_plane=data_plane,
            verifier=verifier,
            validate_scope=validate_scope,
            clock=clock,
        ),
        server,
    )
