"""Runtime Runner process entrypoint."""

import argparse
import asyncio
import dataclasses
import json
import logging
import os
import platform
import uuid
from datetime import UTC, datetime
from pathlib import Path

import grpc
from azents_runtime_control.grpc_runner_client import (
    GrpcRunnerControlClient,
    RuntimeRunnerControlStreamClosed,
)
from azents_runtime_control.grpc_runner_transfer_client import (
    GrpcRunnerTransferClient,
)
from azents_runtime_control.grpc_tls import GrpcClientTlsConfig
from azents_runtime_control.runner import (
    RunnerConnectionRejected,
    RunnerRegistration,
    RunnerRunLoop,
)
from azents_runtime_control.runtime_configuration import (
    RuntimeConfigurationEvidence,
    parse_configuration_sequence,
)
from azents_runtime_control.system_metrics import RUNNER_SYSTEM_METRICS_CAPABILITY
from azents_runtime_control.transfer import (
    RUNNER_TRANSFER_CAPABILITY,
    RUNNER_TRANSFER_PROTOCOL_VERSION,
)

from azents_runtime_runner.execution import DirectExecutionBackend
from azents_runtime_runner.network import prepare_runner_network_environment
from azents_runtime_runner.operations import RunnerOperations
from azents_runtime_runner.pixi import prepare_pixi_environment
from azents_runtime_runner.system_metrics import create_system_metrics_collector
from azents_runtime_runner.transfer import RunnerTransferManager
from azents_runtime_runner.trust import prepare_runner_trust_environment
from azents_runtime_runner.workspace import Workspace

_PROTOCOL_VERSION = RUNNER_TRANSFER_PROTOCOL_VERSION
_CAPABILITIES = (
    "bash",
    "file.read",
    "file.read_text",
    "file.write",
    "file.upload",
    "file.download",
    "file.list",
    "file.glob",
    "file.grep",
    "file.stat",
    "process.start",
    "process.write",
    "file.delete",
    "file.mkdir",
    "file.move",
    "file.bulk_delete",
    "file.bulk_move",
    RUNNER_TRANSFER_CAPABILITY,
    RUNNER_SYSTEM_METRICS_CAPABILITY,
)
_CONTROL_RECONNECT_DELAY_SECONDS = 1.0
_CONTROL_CLIENT_CLOSE_TIMEOUT_SECONDS = 5.0
_DEFAULT_MAX_CONCURRENT_OPERATIONS_PER_SESSION = 10
_DEFAULT_MAX_CONCURRENT_SYSTEM_OPERATIONS = 10
_DEFAULT_MAX_CONCURRENT_OPERATIONS = 50
_DEFAULT_MAX_PENDING_OPERATIONS_PER_OWNER = 100
_DEFAULT_MAX_PENDING_OPERATIONS = 1_000
_DEFAULT_MAX_CONCURRENT_CONTROL_OPERATIONS = 4
_REMOVED_CONTAINMENT_ENV = "AZ_RUNTIME_PROCESS_CONTAINMENT_CONFIG"
_LOGGER = logging.getLogger(__name__)
_STANDARD_LOG_RECORD_FIELDS = frozenset(logging.makeLogRecord({}).__dict__) | {
    "asctime",
    "message",
}


class StructuredLogFormatter(logging.Formatter):
    """Serialize Runner logs and structured extras as one JSON object."""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, object] = {
            "timestamp": datetime.fromtimestamp(record.created, UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        payload.update(
            {
                key: value
                for key, value in record.__dict__.items()
                if key not in _STANDARD_LOG_RECORD_FIELDS
            }
        )
        if record.exc_info is not None:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload, default=str, separators=(",", ":"))


@dataclasses.dataclass(frozen=True)
class RunnerLimitConfig:
    """Validated Runtime Runner operation limits."""

    max_concurrent_operations_per_session: int
    max_concurrent_system_operations: int
    max_concurrent_operations: int
    max_pending_operations_per_owner: int
    max_pending_operations: int
    max_concurrent_control_operations: int


def main() -> None:
    """Start the Runtime Runner process."""
    handler = logging.StreamHandler()
    handler.setFormatter(StructuredLogFormatter())
    logging.basicConfig(
        level=os.environ.get("AZ_LOG_LEVEL", "INFO").upper(),
        handlers=[handler],
    )
    parser = argparse.ArgumentParser(description="Run the Azents Runtime Runner")
    parser.add_argument(
        "--workspace-path",
        help="Agent Workspace absolute path; defaults to HOME",
    )
    args = parser.parse_args()
    asyncio.run(run_runtime_runner(workspace_path=args.workspace_path))


async def run_runtime_runner(*, workspace_path: str | None = None) -> None:
    _reject_removed_containment_env()
    endpoint = _required_env("AZ_RUNTIME_CONTROL_ENDPOINT")
    transfer_endpoint = _required_env("AZ_RUNTIME_TRANSFER_ENDPOINT")
    runtime_id = _required_env("AZ_RUNTIME_ID")
    workspace_path = resolve_workspace_path(workspace_path)
    runner_id = os.environ.get("AZ_RUNTIME_RUNNER_ID") or f"runner-{uuid.uuid4()}"
    credential_id = _required_env("AZ_RUNTIME_RUNNER_AUTH_CREDENTIAL_ID")
    runner_auth_token = _required_env("AZ_RUNTIME_RUNNER_AUTH_TOKEN")
    runtime_configuration = _runtime_configuration_evidence_from_env()
    control_tls = _control_tls_from_env()
    allow_insecure_control = _required_bool_env("AZ_RUNTIME_CONTROL_ALLOW_INSECURE")
    base_connection_id = (
        os.environ.get("AZ_RUNTIME_RUNNER_CONNECTION_ID") or uuid.uuid4().hex
    )
    limit_config = runner_limit_config_from_env()
    inherited_environment = {
        **prepare_runner_network_environment(),
        **prepare_runner_trust_environment(),
        **prepare_pixi_environment(
            workspace_path=workspace_path,
            machine=platform.machine(),
        ),
    }
    execution_backend = DirectExecutionBackend(
        inherited_environment=inherited_environment
    )
    workspace = Workspace(workspace_path)
    registration = RunnerRegistration(
        runtime_id=runtime_id,
        runner_id=runner_id,
        protocol_version=_PROTOCOL_VERSION,
        capabilities=_CAPABILITIES,
        health="ok",
        workspace_path=workspace_path,
        metadata={},
        auth_credential_id=credential_id,
        runtime_configuration=runtime_configuration,
    )
    _LOGGER.info(
        "Runtime Runner starting",
        extra={
            "runtime_id": runtime_id,
            "runner_id": runner_id,
            "workspace_path": workspace_path,
            "control_endpoint": endpoint,
            "max_concurrent_operations_per_session": (
                limit_config.max_concurrent_operations_per_session
            ),
            "max_concurrent_system_operations": (
                limit_config.max_concurrent_system_operations
            ),
            "max_concurrent_operations": limit_config.max_concurrent_operations,
            "max_pending_operations_per_owner": (
                limit_config.max_pending_operations_per_owner
            ),
            "max_pending_operations": limit_config.max_pending_operations,
            "max_concurrent_control_operations": (
                limit_config.max_concurrent_control_operations
            ),
        },
    )
    try:
        while True:
            client = GrpcRunnerControlClient.from_endpoint(
                endpoint,
                runner_auth_token=runner_auth_token,
                tls=control_tls,
                allow_insecure=allow_insecure_control,
            )
            transfer_client = GrpcRunnerTransferClient.from_endpoint(
                transfer_endpoint,
                runner_auth_token=runner_auth_token,
                tls=control_tls,
                allow_insecure=allow_insecure_control,
            )
            connection_id = _control_connection_id(base_connection_id)
            operations = RunnerOperations(
                client=client,
                workspace=workspace,
                execution_backend=execution_backend,
            )
            run_loop = RunnerRunLoop(
                client=client,
                operations=operations,
                registration=registration,
                connection_id=connection_id,
                consumer_id=runner_id,
                system_metrics_collector=create_system_metrics_collector(),
                max_concurrent_operations_per_session=(
                    limit_config.max_concurrent_operations_per_session
                ),
                max_concurrent_system_operations=(
                    limit_config.max_concurrent_system_operations
                ),
                max_concurrent_operations=limit_config.max_concurrent_operations,
                max_pending_operations_per_owner=(
                    limit_config.max_pending_operations_per_owner
                ),
                max_pending_operations=limit_config.max_pending_operations,
                max_concurrent_control_operations=(
                    limit_config.max_concurrent_control_operations
                ),
            )

            def accepted_generation(run_loop: RunnerRunLoop = run_loop) -> int | None:
                accepted = run_loop.accepted
                return None if accepted is None else accepted.generation

            transfer_manager = RunnerTransferManager(
                control=client,
                transfer=transfer_client,
                accepted_generation=accepted_generation,
                workspace=workspace,
            )
            try:
                client.set_transfer_intent_handler(transfer_manager.handle_intent)
                client.set_transfer_cancel_handler(transfer_manager.handle_cancel)
                _LOGGER.info(
                    "Runtime Runner connecting to Control",
                    extra={
                        "runtime_id": runtime_id,
                        "runner_id": runner_id,
                        "connection_id": connection_id,
                    },
                )
                await transfer_manager.start()
                await run_loop.run_forever()
            except asyncio.CancelledError:
                raise
            except (
                RuntimeRunnerControlStreamClosed,
                RunnerConnectionRejected,
                grpc.aio.AioRpcError,
            ):
                _LOGGER.warning(
                    "Runtime Runner Control stream disconnected; reconnecting",
                    exc_info=True,
                    extra={"runtime_id": runtime_id, "runner_id": runner_id},
                )
            finally:
                await transfer_manager.close()
                await transfer_client.close()
                await operations.close()
                try:
                    await asyncio.wait_for(
                        client.close(),
                        timeout=_CONTROL_CLIENT_CLOSE_TIMEOUT_SECONDS,
                    )
                except TimeoutError:
                    _LOGGER.warning(
                        "Runtime Runner Control client close timed out",
                        extra={
                            "runtime_id": runtime_id,
                            "runner_id": runner_id,
                            "timeout_seconds": _CONTROL_CLIENT_CLOSE_TIMEOUT_SECONDS,
                        },
                    )
            await asyncio.sleep(_CONTROL_RECONNECT_DELAY_SECONDS)
    finally:
        await execution_backend.close()


def runner_limit_config_from_env() -> RunnerLimitConfig:
    config = RunnerLimitConfig(
        max_concurrent_operations_per_session=_positive_int_env(
            "AZ_RUNTIME_RUNNER_MAX_CONCURRENT_OPERATIONS_PER_SESSION",
            _DEFAULT_MAX_CONCURRENT_OPERATIONS_PER_SESSION,
        ),
        max_concurrent_system_operations=_positive_int_env(
            "AZ_RUNTIME_RUNNER_MAX_CONCURRENT_SYSTEM_OPERATIONS",
            _DEFAULT_MAX_CONCURRENT_SYSTEM_OPERATIONS,
        ),
        max_concurrent_operations=_positive_int_env(
            "AZ_RUNTIME_RUNNER_MAX_CONCURRENT_OPERATIONS",
            _DEFAULT_MAX_CONCURRENT_OPERATIONS,
        ),
        max_pending_operations_per_owner=_positive_int_env(
            "AZ_RUNTIME_RUNNER_MAX_PENDING_OPERATIONS_PER_OWNER",
            _DEFAULT_MAX_PENDING_OPERATIONS_PER_OWNER,
        ),
        max_pending_operations=_positive_int_env(
            "AZ_RUNTIME_RUNNER_MAX_PENDING_OPERATIONS",
            _DEFAULT_MAX_PENDING_OPERATIONS,
        ),
        max_concurrent_control_operations=_positive_int_env(
            "AZ_RUNTIME_RUNNER_MAX_CONCURRENT_CONTROL_OPERATIONS",
            _DEFAULT_MAX_CONCURRENT_CONTROL_OPERATIONS,
        ),
    )
    if config.max_concurrent_operations_per_session > config.max_concurrent_operations:
        raise SystemExit(
            "AZ_RUNTIME_RUNNER_MAX_CONCURRENT_OPERATIONS_PER_SESSION must not "
            "exceed AZ_RUNTIME_RUNNER_MAX_CONCURRENT_OPERATIONS"
        )
    if config.max_concurrent_system_operations > config.max_concurrent_operations:
        raise SystemExit(
            "AZ_RUNTIME_RUNNER_MAX_CONCURRENT_SYSTEM_OPERATIONS must not exceed "
            "AZ_RUNTIME_RUNNER_MAX_CONCURRENT_OPERATIONS"
        )
    if config.max_pending_operations_per_owner < max(
        config.max_concurrent_operations_per_session,
        config.max_concurrent_system_operations,
    ):
        raise SystemExit(
            "AZ_RUNTIME_RUNNER_MAX_PENDING_OPERATIONS_PER_OWNER must not be "
            "smaller than an owner concurrency limit"
        )
    if config.max_pending_operations < config.max_concurrent_operations:
        raise SystemExit(
            "AZ_RUNTIME_RUNNER_MAX_PENDING_OPERATIONS must not be smaller than "
            "AZ_RUNTIME_RUNNER_MAX_CONCURRENT_OPERATIONS"
        )
    if config.max_pending_operations_per_owner > config.max_pending_operations:
        raise SystemExit(
            "AZ_RUNTIME_RUNNER_MAX_PENDING_OPERATIONS_PER_OWNER must not exceed "
            "AZ_RUNTIME_RUNNER_MAX_PENDING_OPERATIONS"
        )
    return config


def _positive_int_env(name: str, default: int) -> int:
    raw_value = os.environ.get(name)
    if raw_value is None:
        return default
    try:
        value = int(raw_value)
    except ValueError as exc:
        raise SystemExit(f"{name} must be a positive integer") from exc
    if value <= 0:
        raise SystemExit(f"{name} must be a positive integer")
    return value


def _control_connection_id(base_connection_id: str) -> str:
    return f"{base_connection_id}:control:{uuid.uuid4().hex}"


def _runtime_configuration_evidence_from_env() -> RuntimeConfigurationEvidence:
    return RuntimeConfigurationEvidence(
        configuration_sequence=parse_configuration_sequence(
            _required_env("AZ_RUNTIME_CONFIGURATION_SEQUENCE")
        ),
        digest=_required_env("AZ_RUNTIME_CONFIGURATION_DIGEST"),
        desired_generation=int(
            _required_env("AZ_RUNTIME_CONFIGURATION_DESIRED_GENERATION")
        ),
    )


def _reject_removed_containment_env() -> None:
    if _REMOVED_CONTAINMENT_ENV in os.environ:
        raise SystemExit(
            f"{_REMOVED_CONTAINMENT_ENV} is no longer supported; "
            "remove the containment configuration before starting the Runner."
        )


def _required_env(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        raise SystemExit(f"{name} is required")
    return value


def resolve_workspace_path(explicit_path: str | None) -> str:
    """Resolve and validate the Agent Workspace path."""
    raw_path = explicit_path if explicit_path is not None else os.environ.get("HOME")
    if raw_path is None or not raw_path.strip():
        raise SystemExit("--workspace-path or HOME is required")
    path = Path(raw_path.strip())
    if not path.is_absolute():
        raise SystemExit("Agent Workspace path must be absolute")
    return str(path.resolve(strict=False))


def _required_bool_env(name: str) -> bool:
    value = _required_env(name).lower()
    if value == "true":
        return True
    if value == "false":
        return False
    raise SystemExit(f"{name} must be true or false")


def _control_tls_from_env() -> GrpcClientTlsConfig | None:
    value = os.environ.get("AZ_RUNTIME_CONTROL_TLS_CA_PEM")
    if value is None:
        return None
    return GrpcClientTlsConfig(root_certificates=value.encode())


if __name__ == "__main__":
    main()
