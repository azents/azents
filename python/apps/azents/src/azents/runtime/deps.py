"""Agent Runtime dependency providers."""

from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Annotated

from azents_runtime_control.grpc_tls import GrpcClientTlsConfig
from azents_runtime_control.grpc_transfer_coordinator_client import (
    GrpcRuntimeTransferCoordinatorClient,
)
from fastapi import Depends

from azents.core.config import Config
from azents.core.deps import get_appctx, get_config
from azents.core.redis import create_redis_client
from azents.core.runtime_transfer_coordinator_credential import (
    RuntimeTransferCoordinatorCredentialSupplier,
    RuntimeTransferCoordinatorCredentialVerifier,
)
from azents.runtime.control_protocol.runner_operations import (
    RuntimeRunnerOperationClient,
)
from azents.runtime.control_protocol.service import (
    RuntimeControlProtocolService,
)
from azents.runtime.coordination.redis import (
    RedisRuntimeCoordinationStore,
)
from azents.runtime.coordination.store import RuntimeCoordinationStore
from azents.utils.appctx import AppContext

_API_SERVICE_IDENTITY = "azents-api"
_WORKER_SERVICE_IDENTITY = "azents-worker"


async def get_runtime_coordination_store(
    appctx: Annotated[AppContext[Config], Depends(get_appctx)],
    config: Annotated[Config, Depends(get_config)],
) -> RuntimeCoordinationStore:
    """Return the process-wide Runtime Coordination Store."""

    async def create() -> AsyncIterator[RuntimeCoordinationStore]:
        redis = create_redis_client(config.redis.url)
        try:
            yield RedisRuntimeCoordinationStore(redis)
        finally:
            await redis.aclose()

    return await appctx.get_variable(
        f"{__name__}.get_runtime_coordination_store",
        create,
    )


def get_runtime_control_protocol(
    store: Annotated[RuntimeCoordinationStore, Depends(get_runtime_coordination_store)],
) -> RuntimeControlProtocolService:
    """Return the Runtime control protocol service."""
    return RuntimeControlProtocolService(store)


def get_runtime_runner_operation_client(
    control_protocol: Annotated[
        RuntimeControlProtocolService,
        Depends(get_runtime_control_protocol),
    ],
    store: Annotated[RuntimeCoordinationStore, Depends(get_runtime_coordination_store)],
) -> RuntimeRunnerOperationClient:
    """Return the Runtime Runner operation client."""
    return RuntimeRunnerOperationClient(
        control_protocol=control_protocol,
        coordination_store=store,
    )


async def get_api_runtime_transfer_coordinator_client(
    appctx: Annotated[AppContext[Config], Depends(get_appctx)],
    config: Annotated[Config, Depends(get_config)],
) -> GrpcRuntimeTransferCoordinatorClient | None:
    """Return the API process Coordinator client when transfer is configured."""
    return await _get_runtime_transfer_coordinator_client(
        appctx=appctx,
        config=config,
        service_identity=_API_SERVICE_IDENTITY,
    )


async def get_worker_runtime_transfer_coordinator_client(
    appctx: Annotated[AppContext[Config], Depends(get_appctx)],
    config: Annotated[Config, Depends(get_config)],
) -> GrpcRuntimeTransferCoordinatorClient | None:
    """Return the Worker process Coordinator client when transfer is configured."""
    return await _get_runtime_transfer_coordinator_client(
        appctx=appctx,
        config=config,
        service_identity=_WORKER_SERVICE_IDENTITY,
    )


async def _get_runtime_transfer_coordinator_client(
    *,
    appctx: AppContext[Config],
    config: Config,
    service_identity: str,
) -> GrpcRuntimeTransferCoordinatorClient | None:
    """Create one process-owned authenticated Coordinator client."""
    coordinator_config = config.runtime_transfer_coordinator
    if not coordinator_config.enabled:
        return None
    endpoint = coordinator_config.endpoint
    if endpoint is None or not endpoint.strip():
        raise ValueError("Runtime Transfer Coordinator endpoint is required")

    async def create() -> AsyncIterator[GrpcRuntimeTransferCoordinatorClient]:
        tls = _coordinator_tls_config(coordinator_config.tls_ca_file)
        if tls is None and not coordinator_config.allow_insecure:
            raise ValueError(
                "Runtime Transfer Coordinator TLS trust is required unless "
                "insecure transport is explicitly allowed"
            )
        verifier = RuntimeTransferCoordinatorCredentialVerifier(
            config.credential_encryption.key,
            clock=_utc_now,
        )
        supplier = RuntimeTransferCoordinatorCredentialSupplier(
            verifier=verifier,
            service_identity=service_identity,
            clock=_utc_now,
            lifetime=timedelta(seconds=coordinator_config.credential_lifetime_seconds),
        )
        client = GrpcRuntimeTransferCoordinatorClient.from_endpoint(
            endpoint,
            credential_supplier=supplier,
            tls=tls,
            allow_insecure=coordinator_config.allow_insecure,
        )
        try:
            yield client
        finally:
            await client.close()

    return await appctx.get_variable(
        f"{__name__}.runtime_transfer_coordinator_client.{service_identity}",
        create,
    )


def _coordinator_tls_config(tls_ca_file: Path | None) -> GrpcClientTlsConfig | None:
    """Load the configured Coordinator trust bundle without accepting empty trust."""
    if tls_ca_file is None:
        return None
    return GrpcClientTlsConfig(root_certificates=tls_ca_file.read_bytes())


def _utc_now() -> datetime:
    """Return the timezone-aware process clock for credential issuance."""
    return datetime.now(UTC)
