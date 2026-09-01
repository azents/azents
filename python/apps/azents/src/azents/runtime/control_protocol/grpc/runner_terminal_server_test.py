"""Dedicated Runtime Runner Terminal gRPC servicer tests."""

import asyncio
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from typing import NoReturn

import grpc
import pytest
from azents_runtime_control.proto import runtime_runner_terminal_pb2 as pb
from azents_runtime_control.runner_terminal import (
    RunnerTerminalControlFrame,
    RunnerTerminalHeartbeatAcknowledgement,
    RunnerTerminalOutputFrame,
    RunnerTerminalStreamAccepted,
    RunnerTerminalStreamErrorCode,
    RunnerTerminalStreamRegistration,
)

from azents.core.runtime_runner_credential import (
    RuntimeRunnerCredential,
    RuntimeRunnerCredentialInvalid,
)
from azents.runtime.control_protocol.grpc.runner_terminal_server import (
    RuntimeRunnerTerminalAdmissionError,
    RuntimeRunnerTerminalAuthority,
    RuntimeRunnerTerminalGrpcServicer,
)
from azents.testing.grpc import FakeGrpcContext, GrpcMetadata


class _Abort(RuntimeError):
    def __init__(self, code: grpc.StatusCode) -> None:
        self.code = code


class _Context(FakeGrpcContext[pb.RunnerTerminalMessage, pb.TerminalControlMessage]):
    def __init__(self, *, token: str | None = "token") -> None:
        super().__init__(
            metadata=(() if token is None else (("authorization", f"Bearer {token}"),))
        )

    async def abort(
        self,
        code: grpc.StatusCode,
        details: str = "",
        trailing_metadata: GrpcMetadata = (),
    ) -> NoReturn:
        del details, trailing_metadata
        raise _Abort(code)


class _Authenticator:
    def __init__(self, *, authorized: bool = True) -> None:
        self.credential = RuntimeRunnerCredential(
            credential_id="credential-1",
            runtime_id="runtime-1",
            desired_generation=7,
        )
        self.authorized = authorized

    async def authenticate_runner(self, secret: str) -> RuntimeRunnerCredential:
        if secret != "token":
            raise RuntimeRunnerCredentialInvalid("invalid")
        return self.credential

    async def authorize_runner(self, credential: RuntimeRunnerCredential) -> bool:
        return self.authorized and credential == self.credential


class _Stream:
    def __init__(self) -> None:
        self.received: list[object] = []
        self.received_event = asyncio.Event()
        self.closed = False
        self.accepted = RunnerTerminalStreamAccepted(
            stream_generation=3,
            resume_from_output_sequence=4,
            next_input_sequence=5,
        )

    async def receive(self, frame: object) -> None:
        self.received.append(frame)
        self.received_event.set()

    async def control_frames(self) -> AsyncIterator[RunnerTerminalControlFrame]:
        yield RunnerTerminalHeartbeatAcknowledgement(monotonic_sequence=9)
        await asyncio.Future()

    async def close(self) -> None:
        self.closed = True


class _Broker:
    def __init__(
        self,
        *,
        rejection: RunnerTerminalStreamErrorCode | None = None,
    ) -> None:
        self.stream = _Stream()
        self.rejection = rejection
        self.registration: RunnerTerminalStreamRegistration | None = None
        self.authority: RuntimeRunnerTerminalAuthority | None = None
        self.connected_at: datetime | None = None

    async def connect(
        self,
        registration: RunnerTerminalStreamRegistration,
        *,
        authority: RuntimeRunnerTerminalAuthority,
        connected_at: datetime,
    ) -> _Stream:
        if self.rejection is not None:
            raise RuntimeRunnerTerminalAdmissionError(self.rejection)
        self.registration = registration
        self.authority = authority
        self.connected_at = connected_at
        return self.stream


@pytest.mark.asyncio
async def test_terminal_stream_authenticates_fences_and_bridges_frames() -> None:
    broker = _Broker()
    servicer = RuntimeRunnerTerminalGrpcServicer(
        broker=broker,
        runner_authenticator=_Authenticator(),
    )
    release = asyncio.Event()
    responses = servicer.ConnectTerminal(_requests(release), _Context())

    accepted = await anext(responses)
    control = await anext(responses)
    await asyncio.wait_for(broker.stream.received_event.wait(), timeout=1)

    assert accepted.accepted.stream_generation == 3
    assert accepted.accepted.resume_from_output_sequence == 4
    assert accepted.accepted.next_input_sequence == 5
    assert control.heartbeat_ack.monotonic_sequence == 9
    assert broker.registration is not None
    assert broker.registration.identity.terminal_id == "terminal-1"
    assert broker.authority == RuntimeRunnerTerminalAuthority(
        credential_id="credential-1",
        runtime_id="runtime-1",
        desired_generation=7,
        runner_generation=2,
    )
    assert broker.connected_at is not None
    assert broker.connected_at.tzinfo is UTC
    assert broker.stream.received == [
        RunnerTerminalOutputFrame(sequence=1, data=b"output")
    ]

    release.set()
    with pytest.raises(StopAsyncIteration):
        await anext(responses)
    assert broker.stream.closed is True


@pytest.mark.asyncio
async def test_terminal_stream_rejects_runtime_identity_mismatch() -> None:
    broker = _Broker()
    servicer = RuntimeRunnerTerminalGrpcServicer(
        broker=broker,
        runner_authenticator=_Authenticator(),
    )

    with pytest.raises(_Abort) as error:
        await anext(
            servicer.ConnectTerminal(
                _single_registration(runtime_id="runtime-2"),
                _Context(),
            )
        )

    assert error.value.code is grpc.StatusCode.PERMISSION_DENIED
    assert broker.registration is None


@pytest.mark.asyncio
async def test_terminal_stream_rejects_stale_durable_runner_authority() -> None:
    broker = _Broker()
    servicer = RuntimeRunnerTerminalGrpcServicer(
        broker=broker,
        runner_authenticator=_Authenticator(authorized=False),
    )

    with pytest.raises(_Abort) as error:
        await anext(
            servicer.ConnectTerminal(
                _single_registration(),
                _Context(),
            )
        )

    assert error.value.code is grpc.StatusCode.UNAUTHENTICATED
    assert broker.registration is None


@pytest.mark.asyncio
async def test_terminal_stream_rejects_unspecified_event_enum() -> None:
    authenticator = _Authenticator()
    servicer = RuntimeRunnerTerminalGrpcServicer(
        broker=_Broker(),
        runner_authenticator=authenticator,
    )
    stream = _Stream()

    async def messages() -> AsyncIterator[pb.RunnerTerminalMessage]:
        yield pb.RunnerTerminalMessage(
            exit=pb.TerminalExit(reason=pb.TERMINAL_TERMINATION_REASON_UNSPECIFIED)
        )

    with pytest.raises(_Abort) as error:
        await servicer._consume_runner_frames(
            messages(),
            _Context(),
            stream=stream,
            credential=authenticator.credential,
        )

    assert error.value.code is grpc.StatusCode.INVALID_ARGUMENT
    assert stream.received == []


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("rejection", "expected_status"),
    [
        (
            RunnerTerminalStreamErrorCode.STALE_AUTHORITY,
            grpc.StatusCode.PERMISSION_DENIED,
        ),
        (
            RunnerTerminalStreamErrorCode.STALE_STREAM_GENERATION,
            grpc.StatusCode.ABORTED,
        ),
        (
            RunnerTerminalStreamErrorCode.PROTOCOL_VIOLATION,
            grpc.StatusCode.INVALID_ARGUMENT,
        ),
        (
            RunnerTerminalStreamErrorCode.RESOURCE_EXHAUSTED,
            grpc.StatusCode.RESOURCE_EXHAUSTED,
        ),
    ],
)
async def test_terminal_broker_rejections_use_bounded_grpc_status(
    rejection: RunnerTerminalStreamErrorCode,
    expected_status: grpc.StatusCode,
) -> None:
    servicer = RuntimeRunnerTerminalGrpcServicer(
        broker=_Broker(rejection=rejection),
        runner_authenticator=_Authenticator(),
    )

    with pytest.raises(_Abort) as error:
        await anext(
            servicer.ConnectTerminal(
                _single_registration(),
                _Context(),
            )
        )

    assert error.value.code is expected_status


async def _requests(
    release: asyncio.Event,
) -> AsyncIterator[pb.RunnerTerminalMessage]:
    yield _registration()
    yield pb.RunnerTerminalMessage(
        output=pb.TerminalOutputFrame(sequence=1, data=b"output")
    )
    await release.wait()


async def _single_registration(
    *,
    runtime_id: str = "runtime-1",
) -> AsyncIterator[pb.RunnerTerminalMessage]:
    yield _registration(runtime_id=runtime_id)


def _registration(
    *,
    runtime_id: str = "runtime-1",
) -> pb.RunnerTerminalMessage:
    return pb.RunnerTerminalMessage(
        register=pb.TerminalStreamRegistration(
            identity=pb.TerminalIdentity(
                terminal_id="terminal-1",
                runtime_id=runtime_id,
                runner_generation=2,
            ),
            stream_generation=3,
            stream_nonce="nonce-1",
            last_control_acknowledged_output_sequence=4,
            highest_completely_applied_input_sequence=4,
        )
    )
