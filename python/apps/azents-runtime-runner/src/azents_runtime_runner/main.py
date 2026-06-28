"""Runtime Runner process entrypoint."""

import asyncio
import logging
import os
import uuid

import grpc
from azents_runtime_control.grpc_runner_client import (
    GrpcRunnerControlClient,
    RuntimeRunnerControlStreamClosed,
)
from azents_runtime_control.runner import (
    RunnerConnectionRejected,
    RunnerRegistration,
    RunnerRunLoop,
)

from azents_runtime_runner.operations import RunnerOperations
from azents_runtime_runner.workspace import Workspace

_PROTOCOL_VERSION = "2026-05-25"
_CAPABILITIES = (
    "bash",
    "file.read",
    "file.write",
    "file.upload",
    "file.download",
    "file.list",
    "file.grep",
    "file.stat",
    "process.start",
    "process.write",
    "file.delete",
    "file.mkdir",
    "file.move",
    "file.bulk_delete",
    "file.bulk_move",
)
_CONTROL_RECONNECT_DELAY_SECONDS = 1.0
_LOGGER = logging.getLogger(__name__)


def main() -> None:
    """Start the Runtime Runner process."""
    logging.basicConfig(
        level=os.environ.get("AZ_LOG_LEVEL", "INFO").upper(),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    asyncio.run(_main())


async def _main() -> None:
    endpoint = _required_env("AZ_RUNTIME_CONTROL_ENDPOINT")
    runtime_id = _required_env("AZ_RUNTIME_ID")
    workspace_path = _required_env("AZ_AGENT_WORKSPACE_PATH")
    runner_id = os.environ.get("AZ_RUNTIME_RUNNER_ID") or f"runner-{uuid.uuid4()}"
    credential_id = _required_env("AZ_RUNTIME_RUNNER_AUTH_CREDENTIAL_ID")
    base_connection_id = (
        os.environ.get("AZ_RUNTIME_RUNNER_CONNECTION_ID") or uuid.uuid4().hex
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
    )
    _LOGGER.info(
        "Runtime Runner starting",
        extra={
            "runtime_id": runtime_id,
            "runner_id": runner_id,
            "workspace_path": workspace_path,
            "control_endpoint": endpoint,
        },
    )
    while True:
        client = GrpcRunnerControlClient.from_endpoint(endpoint)
        connection_id = _control_connection_id(base_connection_id)
        operations = RunnerOperations(client=client, workspace=workspace)
        run_loop = RunnerRunLoop(
            client=client,
            operations=operations,
            registration=registration,
            connection_id=connection_id,
            consumer_id=runner_id,
        )
        try:
            _LOGGER.info(
                "Runtime Runner connecting to Control",
                extra={
                    "runtime_id": runtime_id,
                    "runner_id": runner_id,
                    "connection_id": connection_id,
                },
            )
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
            await asyncio.sleep(_CONTROL_RECONNECT_DELAY_SECONDS)
        finally:
            await operations.close()
            await client.close()


def _control_connection_id(base_connection_id: str) -> str:
    return f"{base_connection_id}:control:{uuid.uuid4().hex}"


def _required_env(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        raise SystemExit(f"{name} is required")
    return value


if __name__ == "__main__":
    main()
