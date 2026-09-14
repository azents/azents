"""Absence checks for the removed request-scoped Runtime Web protocol."""

from pathlib import Path

from google.protobuf import descriptor_pb2

from azents_runtime_control.proto import (
    runtime_runner_control_pb2,
    runtime_web_session_pb2,
)

_REPOSITORY_ROOT = Path(__file__).resolve().parents[4]
_PROTO_ROOT = _REPOSITORY_ROOT / "proto" / "azents" / "runtime_control" / "v1"
_GENERATED_ROOT = (
    _REPOSITORY_ROOT
    / "python"
    / "libs"
    / "azents-runtime-control"
    / "src"
    / "azents_runtime_control"
    / "proto"
)
_REMOVED_PATHS = (
    "proto/azents/runtime_control/v1/runtime_web_transport.proto",
    "python/apps/azents-runtime-runner/src/azents_runtime_runner/web.py",
    "python/apps/azents-runtime-runner/tests/web_test.py",
    "python/apps/azents/src/azents/repos/runtime_web/transport_repository.py",
    "python/apps/azents/src/azents/repos/runtime_web/transport_repository_test.py",
    "python/apps/azents/src/azents/runtime/control_protocol/grpc/runner_web_registry.py",
    (
        "python/apps/azents/src/azents/runtime/control_protocol/grpc/"
        "runner_web_registry_test.py"
    ),
    "python/apps/azents/src/azents/runtime/control_protocol/grpc/runner_web_server.py",
    (
        "python/apps/azents/src/azents/runtime/control_protocol/grpc/"
        "runner_web_server_test.py"
    ),
    (
        "python/apps/azents/src/azents/runtime/control_protocol/grpc/"
        "runtime_web_proxy_server.py"
    ),
    (
        "python/apps/azents/src/azents/runtime/control_protocol/grpc/"
        "runtime_web_proxy_server_test.py"
    ),
    "python/apps/azents/src/azents/runtime/web_transport_coordinator.py",
    "python/apps/azents/src/azents/runtime/web_transport_dispatcher.py",
    "python/apps/azents/src/azents/runtime_web_gateway/transport.py",
    (
        "python/libs/azents-runtime-control/src/azents_runtime_control/"
        "grpc_runner_web_client.py"
    ),
    ("python/libs/azents-runtime-control/src/azents_runtime_control/runner_web.py"),
    "python/libs/azents-runtime-control/tests/grpc_runner_control_web_intent_test.py",
    "python/libs/azents-runtime-control/tests/grpc_runner_web_client_test.py",
    "python/libs/azents-runtime-control/tests/runner_web_test.py",
)
_REMOVED_ACTIVE_TEXT = (
    "runtime-web-http.v1",
    "runtime_web_transport_pb2",
    "GrpcRuntimeWebProxyClient",
    "RuntimeWebProxySession",
    "RuntimeWebTransportRepository",
    "RuntimeWebTransportCoordinator",
    "RuntimeWebTransportDispatcher",
    "RunnerWebOpenIntent",
    "RunnerWebCancelIntent",
    "RuntimeWebGatewayCapacityExceeded",
    "RuntimeWebAdmissionLimits",
    "runtime_web_gateway_frame_bytes",
    "runtime_web_gateway_http_endpoint_connections",
    "runtime_web_gateway_http_user_connections",
    "runtime_web_gateway_http_agent_connections",
    "runtime_web_gateway_websocket_endpoint_connections",
    "runtime_web_gateway_websocket_user_connections",
    "runtime_web_gateway_websocket_agent_connections",
    "AZ_RUNTIME_WEB_GATEWAY_FRAME_BYTES",
    "AZ_RUNTIME_WEB_GATEWAY_HTTP_ENDPOINT_CONNECTIONS",
    "AZ_RUNTIME_WEB_GATEWAY_WEBSOCKET_ENDPOINT_CONNECTIONS",
)


def test_request_scoped_runtime_web_proto_and_generated_modules_are_absent() -> None:
    """Keep the persistent session protocol as the sole generated surface."""
    assert not (_PROTO_ROOT / "runtime_web_transport.proto").exists()
    for suffix in ("_pb2.py", "_pb2.pyi", "_pb2_grpc.py", "_pb2_grpc.pyi"):
        assert not (_GENERATED_ROOT / f"runtime_web_transport{suffix}").exists()


def test_removed_runtime_web_source_and_test_paths_are_absent() -> None:
    """Pin complete deletion of the request-scoped implementation inventory."""
    for relative_path in _REMOVED_PATHS:
        assert not (_REPOSITORY_ROOT / relative_path).exists(), relative_path


def test_removed_runtime_web_symbols_and_settings_are_absent_from_active_files() -> (
    None
):
    """Prevent compatibility, capability, and configuration surfaces returning."""
    violations: list[str] = []
    for root_name in ("proto", "python", "infra", "testenv"):
        for path in (_REPOSITORY_ROOT / root_name).rglob("*"):
            if not path.is_file() or path.suffix not in {
                ".json",
                ".proto",
                ".py",
                ".pyi",
                ".toml",
                ".tpl",
                ".yaml",
                ".yml",
            }:
                continue
            relative = path.relative_to(_REPOSITORY_ROOT)
            relative_text = relative.as_posix()
            if (
                "migrations/versions" in relative_text
                or relative_text
                in {
                    ("python/apps/azents-runtime-runner/tests/main_test.py"),
                    (
                        "python/apps/azents/src/azents/runtime_web_gateway/"
                        "settings_test.py"
                    ),
                    (
                        "python/libs/azents-runtime-control/tests/"
                        "runtime_web_removal_test.py"
                    ),
                    ("proto/azents/runtime_control/v1/runtime_runner_control.proto"),
                }
                or path.name.startswith("runtime_runner_control_pb2")
            ):
                continue
            text = path.read_text(errors="ignore")
            for removed in _REMOVED_ACTIVE_TEXT:
                if removed in text:
                    violations.append(f"{relative}: {removed}")
    assert not violations, "\n".join(violations)


def test_runner_control_exposes_only_the_session_offer() -> None:
    """Prevent old open/cancel intent fields from re-entering Runner Control."""
    payload = runtime_runner_control_pb2.RunnerControlMessage.DESCRIPTOR.oneofs_by_name[
        "payload"
    ]
    field_names = {field.name for field in payload.fields}

    assert "web_session_offer" in field_names
    assert "web_open_intent" not in field_names
    assert "web_cancel_intent" not in field_names
    file_descriptor = descriptor_pb2.FileDescriptorProto.FromString(
        runtime_runner_control_pb2.DESCRIPTOR.serialized_pb
    )
    message = next(
        message
        for message in file_descriptor.message_type
        if message.name == "RunnerControlMessage"
    )
    assert {(value.start, value.end) for value in message.reserved_range} == {
        (27, 28),
        (28, 29),
    }
    assert set(message.reserved_name) == {
        "web_open_intent",
        "web_cancel_intent",
    }
    offer = runtime_runner_control_pb2.RunnerSessionOffer.DESCRIPTOR
    assert {field.name for field in offer.fields} == {
        "runtime_id",
        "desired_generation",
        "runner_generation",
        "owner_replica_id",
        "owner_boot_id",
        "session_lease_id",
        "lease_generation",
        "connect_address",
        "tls_server_name",
        "join_nonce",
        "protocol_fingerprint",
        "registration_deadline_at",
    }


def test_open_acceptance_uses_the_bounded_route_path_enum() -> None:
    """Expose only local or one-hop relay path classification."""
    field = (
        runtime_web_session_pb2.RuntimeWebSessionOpenAccepted.DESCRIPTOR.fields_by_name[
            "route_path"
        ]
    )
    assert field.number == 4
    assert field.enum_type is not None
    assert {value.name: value.number for value in field.enum_type.values} == {
        "RUNTIME_WEB_SESSION_ROUTE_PATH_UNSPECIFIED": 0,
        "RUNTIME_WEB_SESSION_ROUTE_PATH_LOCAL": 1,
        "RUNTIME_WEB_SESSION_ROUTE_PATH_RELAY": 2,
    }
