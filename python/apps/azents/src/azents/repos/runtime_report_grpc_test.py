"""Real report persistence between gRPC authentication, output and gate effects."""

import asyncio
from collections.abc import AsyncIterator
from datetime import datetime
from typing import NoReturn

import grpc
import pytest
from azents_runtime_control.proto import runtime_runner_control_pb2

from azents.core.runtime_runner_credential import RuntimeRunnerCredential
from azents.rdb.session import SessionManager
from azents.rdb.session_capabilities import WriteSession
from azents.repos.runtime_report_operations_test import (
    _Boundary,
    _Fixture,
    _fixture,
    _GenerationGate,
    _InjectedWriteError,
)
from azents.runtime.control_protocol.grpc.runner_server import (
    RuntimeRunnerControlGrpcServicer,
    _RunnerOutbound,
)
from azents.runtime.control_protocol.grpc.runner_server_test import (
    FakeGrpcContext,
    FakeRunnerAuthenticator,
    RecordingTransferResultSink,
    _NoStreamOfferProvider,
    _register_message,
    _state_report_message,
)
from azents.runtime.control_protocol.grpc.state_sinks import (
    RuntimeRunnerStateRepositorySink,
)
from azents.runtime.control_server import _RuntimeWebRunnerStateSink
from azents.runtime.coordination.memory import InMemoryRuntimeCoordinationStore
from azents.testing.grpc import GrpcMetadata
from azents.testing.runtime_coordination import (
    FakeRuntimeConnectionRegistrar,
    FakeRuntimeControlProtocolService,
)


class _Authenticator(FakeRunnerAuthenticator):
    """Assert that authentication and generation authority run outside report SQL."""

    def __init__(self, fixture: _Fixture) -> None:
        super().__init__(
            credential=RuntimeRunnerCredential(
                credential_id="credential-1",
                runtime_id=fixture.runtime_id,
                desired_generation=fixture.evidence.desired_generation,
            )
        )
        self.boundary = fixture.boundary
        self.calls = 0

    async def authorize_runner(self, credential: RuntimeRunnerCredential) -> bool:
        self.boundary.closed()
        self.calls += 1
        return await super().authorize_runner(credential)


class _Protocol(FakeRuntimeControlProtocolService):
    """Fake only external coordination while report queries use PostgreSQL."""

    def __init__(self, fixture: _Fixture) -> None:
        super().__init__(InMemoryRuntimeCoordinationStore())
        self.boundary = fixture.boundary
        self.heartbeats = 0

    async def heartbeat_runner(
        self, *, runtime_id: str, generation: int, heartbeat_at: datetime
    ) -> bool:
        self.boundary.closed()
        self.heartbeats += 1
        return True


class _Outgoing(asyncio.Queue[_RunnerOutbound]):
    """Observe gRPC output publication only after completed report/read operations."""

    def __init__(self, boundary: _Boundary) -> None:
        super().__init__()
        self.boundary = boundary
        self.published: list[_RunnerOutbound] = []

    async def put(self, item: _RunnerOutbound) -> None:
        self.boundary.closed()
        self.published.append(item)
        await super().put(item)


class _Context(FakeGrpcContext):
    """Observe the actual gRPC registration rejection after its completed read."""

    def __init__(self, boundary: _Boundary) -> None:
        super().__init__()
        self.boundary = boundary
        self.aborted: list[grpc.StatusCode] = []

    async def abort(
        self,
        code: grpc.StatusCode,
        details: str = "",
        trailing_metadata: GrpcMetadata = (),
    ) -> NoReturn:
        self.boundary.closed()
        self.aborted.append(code)
        await super().abort(code, details, trailing_metadata)


def _servicer(
    fixture: _Fixture, protocol: _Protocol, authenticator: _Authenticator
) -> RuntimeRunnerControlGrpcServicer:
    return RuntimeRunnerControlGrpcServicer(
        control_protocol=protocol,
        coordination_store=protocol.store,
        connection_registrar=FakeRuntimeConnectionRegistrar(protocol.store),
        state_sink=_RuntimeWebRunnerStateSink(
            delegate=RuntimeRunnerStateRepositorySink(repository=fixture.operations),
            generation_gate=_GenerationGate(fixture.boundary),
        ),
        owner_replica_id="control-report-test",
        consumer_id="runner-report-test",
        runner_authenticator=authenticator,
        transfer_result_sink=RecordingTransferResultSink(),
        stream_session_offer_provider=_NoStreamOfferProvider(),
        operation_block_ms=1,
    )


@pytest.mark.parametrize("outcome", ["success", "noop", "error", "cancel"])
async def test_actual_grpc_report_and_heartbeat_have_closed_database_boundaries(
    rdb_session_manager: SessionManager[WriteSession], outcome: str
) -> None:
    fixture = await _fixture(
        rdb_session_manager,
        stage="runner" if outcome in {"error", "cancel"} else None,
        cancel=outcome == "cancel",
    )
    protocol = _Protocol(fixture)
    authenticator = _Authenticator(fixture)
    servicer = _servicer(fixture, protocol, authenticator)
    outbound = _Outgoing(fixture.boundary)
    state = _state_report_message()
    state.runtime_id = fixture.runtime_id
    state.runner_state = "busy"
    state.runtime_configuration.desired_generation = (
        fixture.evidence.desired_generation + (1 if outcome == "noop" else 0)
    )

    async def messages() -> AsyncIterator[runtime_runner_control_pb2.RunnerMessage]:
        yield runtime_runner_control_pb2.RunnerMessage(
            generation=1,
            request_id="report",
            state_report=state,
        )
        fixture.boundary.closed()
        yield runtime_runner_control_pb2.RunnerMessage(
            generation=1,
            request_id="heartbeat",
            heartbeat=runtime_runner_control_pb2.RunnerHeartbeat(monotonic_sequence=1),
        )
        fixture.boundary.closed()

    if outcome in {"error", "cancel"}:
        with pytest.raises(
            asyncio.CancelledError if outcome == "cancel" else _InjectedWriteError
        ):
            await servicer._consume_runner_messages(
                messages(),
                outbound,
                authentication=authenticator.credential,
                runtime_id=fixture.runtime_id,
                generation=1,
                active_transfer_dispatches={},
            )
        fixture.boundary.closed()
        assert outbound.published == []
        assert authenticator.calls == protocol.heartbeats == 1
    else:
        await servicer._consume_runner_messages(
            messages(),
            outbound,
            authentication=authenticator.credential,
            runtime_id=fixture.runtime_id,
            generation=1,
            active_transfer_dispatches={},
        )
        fixture.boundary.closed()
        assert authenticator.calls == protocol.heartbeats == 2
        assert len(outbound.published) == 1
        reply = await outbound.get()
        assert isinstance(reply, runtime_runner_control_pb2.RunnerControlMessage)
        assert reply.heartbeat_ack.monotonic_sequence == 1


async def test_grpc_registration_abort_follows_completed_evidence_read(
    rdb_session_manager: SessionManager[WriteSession],
) -> None:
    fixture = await _fixture(rdb_session_manager, stage=None, cancel=False)
    authenticator = _Authenticator(fixture)
    servicer = _servicer(fixture, _Protocol(fixture), authenticator)
    context = _Context(fixture.boundary)
    registration = _register_message()
    registration.register.runtime_id = fixture.runtime_id
    registration.register.runtime_configuration.desired_generation = (
        fixture.evidence.desired_generation
    )
    registration.register.runtime_configuration.digest = "e" * 64

    async def messages() -> AsyncIterator[runtime_runner_control_pb2.RunnerMessage]:
        yield registration

    stream = servicer.ConnectRunner(messages(), context)
    with pytest.raises(RuntimeError, match="FAILED_PRECONDITION"):
        await anext(stream)
    fixture.boundary.closed()
    assert fixture.probe.calls == ["get", "current", "applied"]
    assert context.aborted == [grpc.StatusCode.FAILED_PRECONDITION]
