"""gRPC Provider Control client tests."""

# pyright: reportAttributeAccessIssue=false
# protobuf generated modules expose dynamic message attributes.

import asyncio
from collections.abc import AsyncIterator, Sequence
from datetime import UTC, datetime

import pytest
from google.protobuf import struct_pb2

from azents_runtime_control.execution_policy import (
    JsonValue,
    RuntimeExecutionPolicyEvidence,
    digest_effective_policy,
    validate_standard_execution_policy_envelope,
)
from azents_runtime_control.grpc_provider_client import (
    PROVIDER_AUTH_METHOD_AZENTS_ISSUED_TOKEN,
    PROVIDER_AUTH_METHOD_KUBERNETES_SERVICE_ACCOUNT,
    GrpcProviderControlClient,
    RuntimeProviderControlStreamClosed,
)
from azents_runtime_control.proto import runtime_provider_control_pb2
from azents_runtime_control.provider import (
    ProviderCommandCompletion,
    ProviderRegistration,
    RuntimeProviderObservedState,
    RuntimeProviderReport,
)


@pytest.mark.asyncio
async def test_grpc_client_registers_heartbeats_claims_and_completes() -> None:
    """The client maps the gRPC stream onto the ProviderControlClient protocol."""
    sent: list[runtime_provider_control_pb2.ProviderMessage] = []

    async def stream(
        requests: AsyncIterator[runtime_provider_control_pb2.ProviderMessage],
        *,
        metadata: Sequence[tuple[str, str]] | None = None,
    ) -> AsyncIterator[runtime_provider_control_pb2.ControlMessage]:
        del metadata
        register = await anext(requests)
        sent.append(register)
        yield runtime_provider_control_pb2.ControlMessage(
            request_id=register.request_id,
            register_accepted=runtime_provider_control_pb2.ProviderRegisterAccepted(
                provider_id=register.register.provider_id,
                connection_id=register.connection_id,
                generation=3,
                heartbeat_interval_seconds=20,
            ),
        )
        command_payload = struct_pb2.Struct()
        command_payload.update(
            {"auth": {"runner_auth_credential_id": "runner-credential-1"}}
        )
        execution_policy = _execution_policy_document()
        execution_policy_struct = struct_pb2.Struct()
        execution_policy_struct.update(execution_policy)
        yield runtime_provider_control_pb2.ControlMessage(
            request_id="req-1",
            provider_command=runtime_provider_control_pb2.ProviderCommand(
                runtime_id="runtime-1",
                agent_id="agent-1",
                workspace_id="workspace-1",
                desired_generation=5,
                provider_generation=3,
                command_type="start",
                runner_image="runner:latest",
                control_endpoint="runtime-control:8020",
                runner_auth_token="runner-token",
                payload=command_payload,
                execution_policy=runtime_provider_control_pb2.RuntimeExecutionPolicyEnvelope(
                    evidence=runtime_provider_control_pb2.RuntimeExecutionPolicyEvidence(
                        snapshot_id="snapshot-1",
                        digest=digest_effective_policy(execution_policy),
                        desired_generation=5,
                        module_versions={
                            "container.image_build": 1,
                            "container.run": 1,
                            "container.compose": 1,
                            "container.resources": 1,
                            "engine.storage": 1,
                            "network.egress": 1,
                        },
                        source_versions={
                            "profile": 1,
                            "workspace": 1,
                            "agent": 1,
                        },
                    ),
                    effective_policy=execution_policy_struct,
                ),
            ),
        )
        heartbeat = await anext(requests)
        sent.append(heartbeat)
        yield runtime_provider_control_pb2.ControlMessage(
            request_id=heartbeat.request_id,
            heartbeat_ack=runtime_provider_control_pb2.ProviderHeartbeatAck(
                monotonic_sequence=heartbeat.heartbeat.monotonic_sequence,
            ),
        )
        completion = await anext(requests)
        sent.append(completion)

    client = GrpcProviderControlClient(
        stream,
        provider_credential="provider-secret",
        provider_auth_method=PROVIDER_AUTH_METHOD_AZENTS_ISSUED_TOKEN,
    )
    accepted = await client.register_provider(
        _registration(),
        connection_id="connection-1",
        registered_at=_now(),
    )
    command = await client.claim_next_provider_command(
        provider_id="provider-1",
        generation=accepted.generation,
        consumer_id="consumer-1",
        block_ms=100,
    )

    assert accepted.generation == 3
    assert sent[0].register.capability_contract["schema_version"] == 1
    assert command is not None
    assert command.command.identity.runtime_id == "runtime-1"
    assert command.command.auth.control_endpoint == "runtime-control:8020"
    assert command.command.auth.runner_auth_token == "runner-token"
    assert command.command.auth.runner_auth_credential_id == "runner-credential-1"
    validate_standard_execution_policy_envelope(
        command.command.execution_policy,
        desired_generation=5,
    )
    assert await client.heartbeat_provider(
        provider_id="provider-1",
        generation=accepted.generation,
        heartbeat_at=_now(),
    )

    await client.complete_provider_command(
        ProviderCommandCompletion(
            request_id=command.request_id,
            generation=accepted.generation,
            success=True,
            report=_report(),
            error_code=None,
            error_message=None,
            completed_at=_now(),
        )
    )
    for _ in range(10):
        if len(sent) >= 3:
            break
        await asyncio.sleep(0)

    assert sent[0].WhichOneof("payload") == "register"
    assert sent[1].WhichOneof("payload") == "heartbeat"
    assert sent[2].command_completion.runtime_id == "runtime-1"
    assert sent[2].command_completion.report.workspace_path == "/workspace/agent"
    await client.close()


@pytest.mark.asyncio
async def test_grpc_client_close_suppresses_completed_stream_failure() -> None:
    """A control-plane stream close should not escape during client cleanup."""
    closed = asyncio.Event()

    async def stream(
        requests: AsyncIterator[runtime_provider_control_pb2.ProviderMessage],
        *,
        metadata: Sequence[tuple[str, str]] | None = None,
    ) -> AsyncIterator[runtime_provider_control_pb2.ControlMessage]:
        del metadata
        register = await anext(requests)
        yield runtime_provider_control_pb2.ControlMessage(
            request_id=register.request_id,
            register_accepted=runtime_provider_control_pb2.ProviderRegisterAccepted(
                provider_id=register.register.provider_id,
                connection_id=register.connection_id,
                generation=3,
                heartbeat_interval_seconds=20,
            ),
        )
        closed.set()
        raise RuntimeProviderControlStreamClosed("stream closed")

    client = GrpcProviderControlClient(
        stream,
        provider_credential="provider-secret",
        provider_auth_method=PROVIDER_AUTH_METHOD_AZENTS_ISSUED_TOKEN,
    )
    await client.register_provider(
        _registration(),
        connection_id="connection-1",
        registered_at=_now(),
    )
    await asyncio.wait_for(closed.wait(), timeout=1)
    await asyncio.sleep(0)

    await client.close()


@pytest.mark.asyncio
async def test_grpc_client_sends_explicit_provider_auth_metadata() -> None:
    """The client sends bearer evidence with one explicit Provider auth method."""
    observed_metadata: list[tuple[str, str]] = []

    async def stream(
        requests: AsyncIterator[runtime_provider_control_pb2.ProviderMessage],
        *,
        metadata: Sequence[tuple[str, str]] | None = None,
    ) -> AsyncIterator[runtime_provider_control_pb2.ControlMessage]:
        del requests
        observed_metadata.extend(metadata or ())
        yield runtime_provider_control_pb2.ControlMessage(
            request_id="register",
            register_accepted=runtime_provider_control_pb2.ProviderRegisterAccepted(
                provider_id="provider-1",
                connection_id="connection-1",
                generation=3,
                heartbeat_interval_seconds=20,
            ),
        )

    client = GrpcProviderControlClient(
        stream,
        provider_credential="provider-secret",
        provider_auth_method=PROVIDER_AUTH_METHOD_KUBERNETES_SERVICE_ACCOUNT,
    )
    await client.register_provider(
        _registration(),
        connection_id="connection-1",
        registered_at=_now(),
    )
    await client.close()

    assert observed_metadata == [
        ("authorization", "Bearer provider-secret"),
        (
            "x-azents-runtime-provider-auth-method",
            "kubernetes_service_account",
        ),
    ]


def _registration() -> ProviderRegistration:
    return ProviderRegistration(
        provider_id="provider-1",
        provider_type="docker",
        scope="system",
        workspace_id=None,
        protocol_version="agent-runtime-provider.v1",
        capabilities=("lifecycle", "observe"),
        config_schema_version="v1",
        metadata={"workspace_path_source": "provider"},
        capability_contract={"schema_version": 1},
    )


def _report() -> RuntimeProviderReport:
    return RuntimeProviderReport(
        runtime_id="runtime-1",
        provider_id="provider-1",
        provider_generation=3,
        observed_state=RuntimeProviderObservedState.RUNNING,
        observed_desired_generation=5,
        provider_runtime_id="runtime-provider-id",
        workspace_path="/workspace/agent",
        reason="container_running",
        diagnostic={},
        reported_at=_now(),
        terminal_delete_acknowledged=False,
        execution_policy=_execution_policy_evidence(),
    )


def _execution_policy_evidence() -> RuntimeExecutionPolicyEvidence:
    return RuntimeExecutionPolicyEvidence(
        snapshot_id="snapshot-1",
        digest="d" * 64,
        desired_generation=5,
        module_versions={"container.run": 1},
        source_versions={"profile": 1, "workspace": 1, "agent": 1},
    )


def _execution_policy_document() -> dict[str, JsonValue]:
    return {
        "schema_version": 1,
        "image_build": {
            "module_id": "container.image_build",
            "version": 1,
            "enabled": False,
        },
        "container_run": {
            "module_id": "container.run",
            "version": 1,
            "enabled": False,
        },
        "compose": {
            "module_id": "container.compose",
            "version": 1,
            "enabled": False,
        },
        "resources": {
            "module_id": "container.resources",
            "version": 1,
            "cpu_millicores": None,
            "memory_bytes": None,
            "pids": None,
            "container_count": None,
            "ephemeral_storage_bytes": None,
        },
        "engine_storage": {
            "module_id": "engine.storage",
            "version": 1,
            "mode": "none",
            "capacity_bytes": None,
        },
        "network_egress": {
            "module_id": "network.egress",
            "version": 1,
            "mode": "none",
            "allowed_destinations": [],
            "denied_destinations": [],
        },
    }


def _now() -> datetime:
    return datetime(2026, 5, 25, tzinfo=UTC)
