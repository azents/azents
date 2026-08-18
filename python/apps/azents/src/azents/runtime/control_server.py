"""Agent Runtime Control gRPC server configuration and execution loop."""

import asyncio
import dataclasses
import logging
import signal
from collections.abc import AsyncGenerator, AsyncIterator, Callable
from contextlib import AsyncExitStack, asynccontextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Literal, Protocol

import aioboto3
import boto3
import grpc
from azcommon.infra.s3.service import S3Service
from azcommon.logging import RuntimeEnvironment, configure_logging_for_runtime
from kubernetes_asyncio.client.api.authentication_v1_api import AuthenticationV1Api
from kubernetes_asyncio.client.api_client import ApiClient
from kubernetes_asyncio.config import load_incluster_config
from mypy_boto3_rds import RDSClient
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, create_async_engine

from azents.core.config import PostgreSQLConfig
from azents.core.redis import create_redis_client
from azents.core.runtime_provider_credential import RuntimeProviderCredentialVerifier
from azents.core.runtime_runner_credential import RuntimeRunnerCredentialVerifier
from azents.core.runtime_transfer_coordinator_credential import (
    RuntimeTransferCoordinatorCredentialVerifier,
)
from azents.rdb.session import SessionManager
from azents.repos.agent import AgentRepository
from azents.repos.agent_runtime import AgentRuntimeRepository
from azents.repos.runtime_profile.repository import RuntimeProfileRepository
from azents.repos.runtime_provider.repository import RuntimeProviderRepository
from azents.repos.runtime_provider_binding.repository import (
    RuntimeProviderAuthBindingRepository,
)
from azents.repos.runtime_provider_control.repository import (
    RuntimeProviderControlRepository,
)
from azents.repos.runtime_provider_policy.repository import (
    RuntimeProviderPolicyRepository,
)
from azents.runtime.control_protocol.grpc.auth import (
    RuntimeTransferCoordinatorCredentialGrpcAuth,
)
from azents.runtime.control_protocol.grpc.provider_server import (
    add_runtime_provider_control_servicer,
)
from azents.runtime.control_protocol.grpc.runner_server import (
    add_runtime_runner_control_servicer,
)
from azents.runtime.control_protocol.grpc.runner_transfer_server import (
    add_runtime_runner_transfer_servicer,
)
from azents.runtime.control_protocol.grpc.state_sinks import (
    RuntimeProviderReportRepositorySink,
    RuntimeRunnerStateRepositorySink,
)
from azents.runtime.control_protocol.grpc.transfer_coordinator_server import (
    add_runtime_transfer_coordinator_servicer,
)
from azents.runtime.control_protocol.reconciler import (
    RuntimeLifecycleDispatchConfig,
    RuntimeLifecycleReconciler,
)
from azents.runtime.control_protocol.service import (
    RuntimeControlProtocolService,
)
from azents.runtime.coordination.redis import (
    RedisRuntimeCoordinationStore,
)
from azents.runtime.transfer.control import (
    create_runtime_control_transfer_state_store,
)
from azents.runtime.transfer.coordinator import (
    RuntimeTransferCleanup,
    RuntimeTransferCoordinator,
)
from azents.runtime.transfer.data import (
    RUNTIME_TRANSFER_MAXIMUM_AGE,
    RUNTIME_TRANSFER_MAXIMUM_PAGE_SIZE,
)
from azents.runtime.transfer.object_store import (
    RuntimeTransferOrphanRepairResult,
    RuntimeTransferS3Cleanup,
)
from azents.runtime.transfer.result_coordinator import (
    RuntimeRunnerTransferResultCoordinator,
)
from azents.services.runtime_profile_reconciliation.service import (
    RuntimeProfileReconciliationService,
)
from azents.services.runtime_profile_resolution.service import (
    RuntimeProfileResolutionService,
)
from azents.services.runtime_provider_contract.service import (
    RuntimeProviderContractService,
)
from azents.services.runtime_provider_control.provider_auth import (
    KubernetesApiTokenReviewer,
)
from azents.services.runtime_provider_control.service import (
    RuntimeProviderEnrollmentService,
)
from azents.services.runtime_recreation.service import RuntimeRecreationReconciler
from azents.services.runtime_runner_auth.service import (
    RuntimeRunnerAuthenticationService,
)

_DEFAULT_PORT = 8030
_DEFAULT_RECONCILE_INTERVAL_SECONDS = 15.0
_DEFAULT_START_TIMEOUT_SECONDS = 300.0
_DEFAULT_LIFECYCLE_RETRY_DELAY_SECONDS = 15.0
_DEFAULT_TRANSFER_REPAIR_INTERVAL_SECONDS = 5.0
_DEFAULT_TRANSFER_OBJECT_PREFIX = "runtime-transfer"
_MAX_TRANSFER_TTL_SECONDS = 3_600
_MAX_TRANSFER_PROCESS_BUFFER_BYTES = 64 * 1024 * 1024
_LOGGER = logging.getLogger(__name__)


class RuntimeTransferRepairCleanup(RuntimeTransferCleanup, Protocol):
    """Cleanup operations used by the periodic transfer repair pass."""

    async def repair_orphans(
        self,
        *,
        now: datetime,
        maximum_age: timedelta,
        page_size: int,
    ) -> RuntimeTransferOrphanRepairResult:
        """Repair one bounded page of untracked storage artifacts."""
        ...


class RuntimeTransferRepairCoordinator(Protocol):
    """Coordinator operations used by one periodic transfer repair pass."""

    async def repair_terminal_correlations(self, *, page_size: int) -> int:
        """Repair retained terminal correlation records."""
        ...

    async def repair_pending(self, *, page_size: int) -> int:
        """Repair pending transfer dispatches."""
        ...

    async def reconcile_generations(self, *, page_size: int) -> int:
        """Reconcile transfer generation ownership."""
        ...

    async def repair_stale_stream_claims(
        self,
        *,
        cleanup: RuntimeTransferCleanup | None,
        page_size: int,
    ) -> int:
        """Repair stale transfer stream claims."""
        ...


class RuntimeControlSettings(BaseSettings):
    """runtime-control server settings."""

    model_config = SettingsConfigDict(
        env_prefix="AZ_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    runtime_env: RuntimeEnvironment = RuntimeEnvironment.LOCAL
    sentry_dsn: str | None = None
    redis_url: str = "redis://localhost:6379"
    runtime_control_port: int = _DEFAULT_PORT
    runtime_control_instance_id: str = "azents-runtime-control-local"
    runtime_control_reconcile_interval_seconds: float = (
        _DEFAULT_RECONCILE_INTERVAL_SECONDS
    )
    runtime_control_lifecycle_retry_delay_seconds: float = (
        _DEFAULT_LIFECYCLE_RETRY_DELAY_SECONDS
    )
    runtime_control_start_timeout_seconds: float = _DEFAULT_START_TIMEOUT_SECONDS
    runtime_control_kubernetes_token_review_enabled: bool = False
    runtime_control_transfer_backend: Literal["memory", "redis"] = "redis"
    runtime_control_transfer_redis_namespace: str = "azents:runtime:transfer"
    runtime_control_transfer_per_runtime_attempts: int = 8
    runtime_control_transfer_per_runtime_bytes: int = 8 * 1024 * 1024
    runtime_control_transfer_deployment_attempts: int = 32
    runtime_control_transfer_deployment_bytes: int = 32 * 1024 * 1024
    runtime_control_transfer_admission_lease_seconds: float = 300.0
    runtime_control_transfer_consumer_lease_seconds: float = 60.0
    runtime_control_transfer_stream_lease_seconds: float = 30.0
    runtime_control_transfer_terminal_ttl_seconds: float = 300.0
    runtime_control_transfer_list_page_size: int = 100
    runtime_control_transfer_max_concurrent_downloads: int = 4
    runtime_control_transfer_max_concurrent_uploads: int = 4
    runtime_control_transfer_chunk_bytes: int = 256 * 1024
    runtime_control_transfer_multipart_part_bytes: int = 5 * 1024 * 1024
    runtime_control_transfer_repair_interval_seconds: float = (
        _DEFAULT_TRANSFER_REPAIR_INTERVAL_SECONDS
    )
    runtime_control_transfer_object_prefix: str = _DEFAULT_TRANSFER_OBJECT_PREFIX
    runtime_control_transfer_coordinator_credential_skew_seconds: float = 5.0
    runtime_control_transfer_coordinator_credential_lifetime_seconds: float = 30.0
    runtime_control_workspace_s3_bucket: str = ""
    runtime_control_workspace_s3_prefix: str = "v1"
    runtime_control_workspace_s3_endpoint_url: str | None = None
    runtime_control_workspace_s3_access_key_id: str | None = None
    runtime_control_workspace_s3_secret_access_key: str | None = None
    runtime_control_allow_insecure: bool
    runtime_control_tls_certificate_file: str | None = None
    runtime_control_tls_private_key_file: str | None = None
    runtime_control_tls_ca_file: str | None = None
    runtime_runner_image: str
    runtime_runner_control_endpoint: str
    runtime_runner_transfer_endpoint: str
    credential_encryption_key: str
    rdb_host: str = "localhost"
    rdb_port: int = 5432
    rdb_user: str = "azents"
    rdb_password: str | None = None
    rdb_db_name: str = "azents"
    rdb_use_iam_auth: bool = False
    rdb_region: str = "us-west-2"
    rdb_ssl_mode: str = "prefer"
    rdb_verbose: bool = False


@dataclasses.dataclass(frozen=True)
class _RuntimeControlTransport:
    """Runtime Control server and client trust configuration."""

    server_credentials: grpc.ServerCredentials | None
    ca_pem: str | None
    allow_insecure: bool


@asynccontextmanager
async def runtime_control_server_lifespan(
    settings: RuntimeControlSettings,
) -> AsyncGenerator[grpc.aio.Server]:
    """Manage runtime-control gRPC server resources."""
    validate_runtime_control_transfer_settings(settings)
    redis = create_redis_client(settings.redis_url)
    coordination_store = RedisRuntimeCoordinationStore(redis)
    clock = _utc_now
    transfer_state = create_runtime_control_transfer_state_store(
        settings=settings,
        redis=redis,
        clock=clock,
    )
    resources = AsyncExitStack()
    transfer_s3 = await resources.enter_async_context(
        _runtime_transfer_s3_service(settings)
    )
    transfer_cleanup = RuntimeTransferS3Cleanup(
        object_store=transfer_s3,
        bucket=settings.runtime_control_workspace_s3_bucket,
        object_prefix=_transfer_object_prefix(settings),
    )
    transfer_coordinator = RuntimeTransferCoordinator(
        state_store=transfer_state,
        coordination_store=coordination_store,
        cleanup=transfer_cleanup,
        clock=clock,
    )
    control_protocol = RuntimeControlProtocolService(
        coordination_store,
        runner_generation_observer=transfer_coordinator,
    )
    transfer_result_coordinator = RuntimeRunnerTransferResultCoordinator(
        state_store=transfer_state,
        coordination_store=coordination_store,
        control_protocol=control_protocol,
        terminal_coordinator=transfer_coordinator,
        clock=clock,
    )
    coordinator_credential_verifier = RuntimeTransferCoordinatorCredentialVerifier(
        settings.credential_encryption_key,
        clock=clock,
        clock_skew=timedelta(
            seconds=settings.runtime_control_transfer_coordinator_credential_skew_seconds
        ),
        maximum_lifetime=_coordinator_credential_lifetime(settings),
    )
    transport = runtime_control_transport(settings)
    engine = _create_engine(settings)
    session_manager = _session_manager(engine)
    agent_repository = AgentRepository()
    runtime_repository = AgentRuntimeRepository()
    policy_repository = RuntimeProviderPolicyRepository()
    profile_repository = RuntimeProfileRepository()
    provider_repository = RuntimeProviderRepository()
    provider_control_repository = RuntimeProviderControlRepository()
    profile_resolution = RuntimeProfileResolutionService(
        session_manager=session_manager,
        agent_repository=agent_repository,
        runtime_repository=runtime_repository,
        profile_repository=profile_repository,
        provider_repository=provider_repository,
        provider_policy_repository=policy_repository,
    )
    profile_reconciliation = RuntimeProfileReconciliationService(
        session_manager=session_manager,
        profile_repository=profile_repository,
        resolution_service=profile_resolution,
    )
    kubernetes_api_client: ApiClient | None = None
    kubernetes_token_reviewer = None
    if settings.runtime_control_kubernetes_token_review_enabled:
        load_incluster_config()
        kubernetes_api_client = ApiClient()
        kubernetes_token_reviewer = KubernetesApiTokenReviewer(
            AuthenticationV1Api(kubernetes_api_client)
        )
    enrollment_service = RuntimeProviderEnrollmentService(
        session_manager=session_manager,
        repository=provider_control_repository,
        provider_repository=provider_repository,
        binding_repository=RuntimeProviderAuthBindingRepository(),
        verifier=RuntimeProviderCredentialVerifier(settings.credential_encryption_key),
        kubernetes_token_reviewer=kubernetes_token_reviewer,
        auth_registry=None,
    )
    contract_service = RuntimeProviderContractService(
        session_manager=session_manager,
        provider_repository=provider_repository,
        policy_repository=policy_repository,
        profile_repository=profile_repository,
    )
    provider_sink = RuntimeProviderReportRepositorySink(
        runtime_repository=runtime_repository,
        profile_repository=profile_repository,
        session_manager=session_manager,
    )
    runner_sink = RuntimeRunnerStateRepositorySink(
        runtime_repository=runtime_repository,
        profile_repository=profile_repository,
        session_manager=session_manager,
    )
    runner_credential_verifier = RuntimeRunnerCredentialVerifier(
        settings.credential_encryption_key
    )
    runner_authenticator = RuntimeRunnerAuthenticationService(
        session_manager=session_manager,
        runtime_repository=runtime_repository,
        verifier=runner_credential_verifier,
    )
    reconciler = RuntimeLifecycleReconciler(
        agent_repository=agent_repository,
        runtime_repository=runtime_repository,
        profile_repository=profile_repository,
        session_manager=session_manager,
        coordination_store=coordination_store,
        control_protocol=control_protocol,
        config=RuntimeLifecycleDispatchConfig(
            runner_image=settings.runtime_runner_image,
            runner_control_endpoint=settings.runtime_runner_control_endpoint,
            runner_transfer_endpoint=settings.runtime_runner_transfer_endpoint,
            runner_credential_identifier=runner_credential_verifier,
            runner_control_tls_ca_pem=transport.ca_pem,
            allow_insecure_runner_control=transport.allow_insecure,
            start_timeout=timedelta(
                seconds=settings.runtime_control_start_timeout_seconds
            ),
            lifecycle_retry_delay=timedelta(
                seconds=settings.runtime_control_lifecycle_retry_delay_seconds
            ),
        ),
    )
    recreation_reconciler = RuntimeRecreationReconciler(
        session_manager=session_manager,
        profile_repository=profile_repository,
        runtime_repository=runtime_repository,
        agent_repository=agent_repository,
    )
    stop_reconciler = asyncio.Event()
    reconciler_task = asyncio.create_task(
        _run_reconciler(
            reconciler,
            profile_reconciliation,
            recreation_reconciler,
            stop=stop_reconciler,
            interval_seconds=settings.runtime_control_reconcile_interval_seconds,
        ),
        name="runtime-lifecycle-reconciler",
    )
    stop_transfer_repair = asyncio.Event()
    transfer_repair_task = asyncio.create_task(
        _run_transfer_repair(
            transfer_coordinator,
            cleanup=transfer_cleanup,
            clock=clock,
            stop=stop_transfer_repair,
            interval_seconds=settings.runtime_control_transfer_repair_interval_seconds,
            page_size=settings.runtime_control_transfer_list_page_size,
        ),
        name="runtime-transfer-repair",
    )
    server = grpc.aio.server()
    add_runtime_provider_control_servicer(
        server,
        control_protocol=control_protocol,
        report_sink=provider_sink,
        observe_completion_handler=reconciler,
        owner_replica_id=settings.runtime_control_instance_id,
        consumer_id=f"{settings.runtime_control_instance_id}:provider",
        credential_authenticator=enrollment_service,
        connection_tracker=enrollment_service,
        contract_proposer=contract_service,
        runner_credential_issuer=runner_credential_verifier,
    )
    add_runtime_runner_control_servicer(
        server,
        control_protocol=control_protocol,
        coordination_store=coordination_store,
        state_sink=runner_sink,
        owner_replica_id=settings.runtime_control_instance_id,
        consumer_id=f"{settings.runtime_control_instance_id}:runner",
        runner_authenticator=runner_authenticator,
        transfer_result_sink=transfer_result_coordinator,
    )
    add_runtime_runner_transfer_servicer(
        server,
        state_store=transfer_state,
        coordination_store=coordination_store,
        object_store=transfer_s3,
        terminal_sink=transfer_coordinator,
        bucket=settings.runtime_control_workspace_s3_bucket,
        object_prefix=_transfer_object_prefix(settings),
        owner_replica_id=settings.runtime_control_instance_id,
        runner_authenticator=runner_authenticator,
        clock=clock,
        max_concurrent_downloads=(
            settings.runtime_control_transfer_max_concurrent_downloads
        ),
        max_concurrent_uploads=settings.runtime_control_transfer_max_concurrent_uploads,
        maximum_chunk_bytes=settings.runtime_control_transfer_chunk_bytes,
        multipart_part_bytes=settings.runtime_control_transfer_multipart_part_bytes,
    )
    add_runtime_transfer_coordinator_servicer(
        server,
        coordinator=transfer_coordinator,
        credential_auth=RuntimeTransferCoordinatorCredentialGrpcAuth(
            coordinator_credential_verifier
        ),
    )
    listen_address = f"0.0.0.0:{settings.runtime_control_port}"
    if transport.server_credentials is None:
        server.add_insecure_port(listen_address)
    else:
        server.add_secure_port(listen_address, transport.server_credentials)
    await server.start()
    _LOGGER.info(
        "Runtime Control gRPC server started",
        extra={
            "instance_id": settings.runtime_control_instance_id,
            "port": settings.runtime_control_port,
            "reconcile_interval_seconds": (
                settings.runtime_control_reconcile_interval_seconds
            ),
            "start_timeout_seconds": settings.runtime_control_start_timeout_seconds,
            "lifecycle_retry_delay_seconds": (
                settings.runtime_control_lifecycle_retry_delay_seconds
            ),
            "runner_authentication": "runtime_bound_credential",
            "tls_enabled": transport.server_credentials is not None,
        },
    )
    try:
        yield server
    finally:
        stop_reconciler.set()
        stop_transfer_repair.set()
        reconciler_task.cancel()
        transfer_repair_task.cancel()
        try:
            await reconciler_task
        except asyncio.CancelledError:
            pass
        try:
            await transfer_repair_task
        except asyncio.CancelledError:
            pass
        await server.stop(grace=5)
        if kubernetes_api_client is not None:
            await kubernetes_api_client.close()
        await resources.aclose()
        await redis.aclose()
        await engine.dispose()


async def _run_reconciler(
    reconciler: RuntimeLifecycleReconciler,
    profile_reconciliation: RuntimeProfileReconciliationService,
    recreation_reconciler: RuntimeRecreationReconciler,
    *,
    stop: asyncio.Event,
    interval_seconds: float,
) -> None:
    while not stop.is_set():
        try:
            profile_result = await profile_reconciliation.reconcile_once()
            if (
                profile_result.reconciled_agents
                or profile_result.blocked_agents
                or profile_result.stale_tasks
            ):
                _LOGGER.info(
                    "Runtime Profile reconciliation updated desired configurations",
                    extra={
                        "claimed_tasks": profile_result.claimed_tasks,
                        "reconciled_agents": profile_result.reconciled_agents,
                        "blocked_agents": profile_result.blocked_agents,
                        "skipped_agents": profile_result.skipped_agents,
                        "stale_tasks": profile_result.stale_tasks,
                        "continued_tasks": profile_result.continued_tasks,
                        "retried_tasks": profile_result.retried_tasks,
                    },
                )
            recreation_result = await recreation_reconciler.reconcile_once()
            if recreation_result.dispatched_items or recreation_result.completed_items:
                _LOGGER.info(
                    "Runtime recreation reconcile advanced operations",
                    extra={
                        "operations": recreation_result.operations,
                        "processed_items": recreation_result.processed_items,
                        "dispatched_items": recreation_result.dispatched_items,
                        "completed_items": recreation_result.completed_items,
                    },
                )
            dispatched = await reconciler.reconcile_once()
            if dispatched:
                _LOGGER.info(
                    "Runtime lifecycle reconcile dispatched commands",
                    extra={"dispatched": dispatched},
                )
        except Exception:
            _LOGGER.exception("Runtime lifecycle reconciler iteration failed")
        try:
            await asyncio.wait_for(stop.wait(), timeout=interval_seconds)
        except TimeoutError:
            continue


async def _run_transfer_repair(
    coordinator: RuntimeTransferCoordinator,
    *,
    cleanup: RuntimeTransferS3Cleanup,
    clock: Callable[[], datetime],
    stop: asyncio.Event,
    interval_seconds: float,
    page_size: int,
) -> None:
    """Run bounded transfer dispatch, generation, and stale-stream repair."""
    if interval_seconds <= 0:
        raise ValueError("Runtime transfer repair interval must be positive")
    while not stop.is_set():
        try:
            observed = await repair_transfer_once(
                coordinator,
                cleanup=cleanup,
                now=clock(),
                page_size=page_size,
            )
            if observed:
                _LOGGER.info(
                    "Runtime transfer repair observed records",
                    extra={"observed": observed},
                )
        except Exception:
            _LOGGER.exception("Runtime transfer repair iteration failed")
        try:
            await asyncio.wait_for(stop.wait(), timeout=interval_seconds)
        except TimeoutError:
            continue


async def repair_transfer_once(
    coordinator: RuntimeTransferRepairCoordinator,
    *,
    cleanup: RuntimeTransferRepairCleanup,
    now: datetime,
    page_size: int,
) -> int:
    """Run one bounded transfer repair pass.

    :param coordinator: process-owned transfer coordinator
    :param cleanup: trusted S3 multipart cleanup collaborator
    :param now: authoritative timezone-aware repair time
    :param page_size: maximum records loaded per state-store list operation
    :returns: number of records observed across repair categories
    """
    if page_size <= 0:
        raise ValueError("Runtime transfer repair page size must be positive")
    terminals = await coordinator.repair_terminal_correlations(page_size=page_size)
    pending = await coordinator.repair_pending(page_size=page_size)
    generations = await coordinator.reconcile_generations(page_size=page_size)
    stale = await coordinator.repair_stale_stream_claims(
        cleanup=cleanup,
        page_size=page_size,
    )
    orphans = await cleanup.repair_orphans(
        now=now,
        maximum_age=RUNTIME_TRANSFER_MAXIMUM_AGE,
        page_size=page_size,
    )
    _LOGGER.info(
        "Runtime transfer orphan repair completed",
        extra={
            "listed_objects": orphans.listed_objects,
            "deleted_objects": orphans.deleted_objects,
            "listed_multipart_uploads": orphans.listed_multipart_uploads,
            "aborted_multipart_uploads": orphans.aborted_multipart_uploads,
            "failed_cleanups": orphans.failed_cleanups,
            "skipped_storage_entries": orphans.skipped_storage_entries,
        },
    )
    return terminals + pending + generations + stale + orphans.observed


@asynccontextmanager
async def _runtime_transfer_s3_service(
    settings: RuntimeControlSettings,
) -> AsyncIterator[S3Service]:
    """Create one process-lifetime trusted S3 service for transfer RPCs."""
    bucket = settings.runtime_control_workspace_s3_bucket
    if not bucket:
        raise ValueError("Runtime Control workspace S3 bucket is required")
    client_kwargs: dict[str, Any] = {}
    if settings.runtime_control_workspace_s3_endpoint_url is not None:
        client_kwargs["endpoint_url"] = (
            settings.runtime_control_workspace_s3_endpoint_url
        )
    access_key_id = settings.runtime_control_workspace_s3_access_key_id
    secret_access_key = settings.runtime_control_workspace_s3_secret_access_key
    if (access_key_id is None) != (secret_access_key is None):
        raise ValueError("Runtime Control S3 credentials must be configured together")
    if access_key_id is not None and secret_access_key is not None:
        client_kwargs["aws_access_key_id"] = access_key_id
        client_kwargs["aws_secret_access_key"] = secret_access_key
    session = aioboto3.Session()
    async with session.client("s3", **client_kwargs) as client:
        yield S3Service(s3_client=client)


def _transfer_object_prefix(settings: RuntimeControlSettings) -> str:
    """Return the internal workspace namespace for opaque transfer objects."""
    prefix = "/".join(
        value.strip("/")
        for value in (
            settings.runtime_control_workspace_s3_prefix,
            settings.runtime_control_transfer_object_prefix,
        )
        if value.strip("/")
    )
    if not prefix:
        raise ValueError("Runtime transfer object prefix is required")
    return prefix


def _coordinator_credential_lifetime(
    settings: RuntimeControlSettings,
) -> timedelta:
    """Validate the configured trusted coordinator credential lifetime."""
    lifetime = timedelta(
        seconds=settings.runtime_control_transfer_coordinator_credential_lifetime_seconds
    )
    if not timedelta() < lifetime <= timedelta(seconds=60):
        raise ValueError(
            "Runtime transfer coordinator credential lifetime must be within 60 seconds"
        )
    return lifetime


def validate_runtime_control_transfer_settings(
    settings: RuntimeControlSettings,
) -> None:
    """Reject unsafe or unbounded Runtime Transfer deployment settings."""
    positive = {
        "per-runtime attempts": settings.runtime_control_transfer_per_runtime_attempts,
        "per-runtime bytes": settings.runtime_control_transfer_per_runtime_bytes,
        "deployment attempts": settings.runtime_control_transfer_deployment_attempts,
        "deployment bytes": settings.runtime_control_transfer_deployment_bytes,
        "list page size": settings.runtime_control_transfer_list_page_size,
        "maximum concurrent downloads": (
            settings.runtime_control_transfer_max_concurrent_downloads
        ),
        "maximum concurrent uploads": (
            settings.runtime_control_transfer_max_concurrent_uploads
        ),
        "chunk bytes": settings.runtime_control_transfer_chunk_bytes,
        "multipart part bytes": settings.runtime_control_transfer_multipart_part_bytes,
    }
    if any(value <= 0 for value in positive.values()):
        raise ValueError("Runtime transfer limits must be positive")
    if (
        settings.runtime_control_transfer_list_page_size
        > RUNTIME_TRANSFER_MAXIMUM_PAGE_SIZE
    ):
        raise ValueError("Runtime transfer list page size must not exceed 1000")
    bounded_ttls = {
        "admission lease": settings.runtime_control_transfer_admission_lease_seconds,
        "consumer lease": settings.runtime_control_transfer_consumer_lease_seconds,
        "stream lease": settings.runtime_control_transfer_stream_lease_seconds,
        "terminal TTL": settings.runtime_control_transfer_terminal_ttl_seconds,
    }
    if any(
        not 0 < value <= _MAX_TRANSFER_TTL_SECONDS for value in bounded_ttls.values()
    ):
        raise ValueError("Runtime transfer TTL settings must be within 3,600 seconds")
    if not settings.runtime_control_transfer_redis_namespace.strip():
        raise ValueError("Runtime transfer Redis namespace is required")
    if settings.runtime_control_transfer_multipart_part_bytes < 5 * 1024 * 1024:
        raise ValueError("Runtime transfer multipart part bytes must be at least 5 MiB")
    concurrent_buffers = (
        settings.runtime_control_transfer_max_concurrent_downloads
        + settings.runtime_control_transfer_max_concurrent_uploads
    ) * settings.runtime_control_transfer_chunk_bytes
    if concurrent_buffers > _MAX_TRANSFER_PROCESS_BUFFER_BYTES:
        raise ValueError("Runtime transfer process buffers exceed the configured bound")


def _utc_now() -> datetime:
    """Return the Runtime Control process clock."""
    return datetime.now(UTC)


def runtime_control_transport(
    settings: RuntimeControlSettings,
) -> _RuntimeControlTransport:
    """Build server credentials and Runner trust material."""
    if settings.runtime_control_allow_insecure:
        return _RuntimeControlTransport(
            server_credentials=None,
            ca_pem=None,
            allow_insecure=True,
        )
    certificate_path = _required_tls_path(
        settings.runtime_control_tls_certificate_file,
        "AZ_RUNTIME_CONTROL_TLS_CERTIFICATE_FILE",
    )
    private_key_path = _required_tls_path(
        settings.runtime_control_tls_private_key_file,
        "AZ_RUNTIME_CONTROL_TLS_PRIVATE_KEY_FILE",
    )
    ca_path = _required_tls_path(
        settings.runtime_control_tls_ca_file,
        "AZ_RUNTIME_CONTROL_TLS_CA_FILE",
    )
    certificate = certificate_path.read_bytes()
    private_key = private_key_path.read_bytes()
    ca_pem = ca_path.read_text()
    if not certificate.strip() or not private_key.strip() or not ca_pem.strip():
        raise RuntimeError("Runtime Control TLS files must not be empty")
    return _RuntimeControlTransport(
        server_credentials=grpc.ssl_server_credentials([(private_key, certificate)]),
        ca_pem=ca_pem,
        allow_insecure=False,
    )


def _required_tls_path(value: str | None, env_name: str) -> Path:
    if value is None or not value.strip():
        raise RuntimeError(
            f"{env_name} is required when AZ_RUNTIME_CONTROL_ALLOW_INSECURE is false"
        )
    return Path(value)


def _postgres_config(settings: RuntimeControlSettings) -> PostgreSQLConfig:
    return PostgreSQLConfig(
        host=settings.rdb_host,
        port=settings.rdb_port,
        user=settings.rdb_user,
        password=settings.rdb_password,
        db_name=settings.rdb_db_name,
        use_iam_auth=settings.rdb_use_iam_auth,
        region=settings.rdb_region,
        ssl_mode=settings.rdb_ssl_mode,
        verbose=settings.rdb_verbose,
    )


def _create_engine(settings: RuntimeControlSettings) -> AsyncEngine:
    db_config = _postgres_config(settings)
    if db_config.use_iam_auth:
        rds_client: RDSClient = boto3.client("rds", region_name=db_config.region)
        engine = create_async_engine(
            db_config.get_sqlalchemy_uri(),
            connect_args={"sslmode": db_config.ssl_mode},
            echo=db_config.verbose,
            pool_pre_ping=True,
        )

        def _provide_token(
            dialect: object,
            conn_rec: object,
            cargs: object,
            cparams: dict[str, object],
        ) -> None:
            del dialect, conn_rec, cargs
            cparams["password"] = rds_client.generate_db_auth_token(
                DBHostname=db_config.host,
                Port=db_config.port,
                DBUsername=db_config.user,
                Region=db_config.region,
            )

        event.listen(engine.sync_engine, "do_connect", _provide_token)
        return engine
    return create_async_engine(
        db_config.get_sqlalchemy_uri(with_password=True),
        connect_args={"sslmode": db_config.ssl_mode},
        echo=db_config.verbose,
        pool_pre_ping=True,
    )


def _session_manager(engine: AsyncEngine) -> SessionManager[AsyncSession]:
    @asynccontextmanager
    async def session_manager() -> AsyncGenerator[AsyncSession, None]:
        async with AsyncSession(engine, expire_on_commit=False) as session:
            try:
                yield session
            except Exception:
                await session.rollback()
                raise
            else:
                await session.commit()

    return session_manager


async def run_runtime_control_server() -> None:
    """Run the runtime-control server."""
    settings = RuntimeControlSettings()  # env supplies required deployment settings.
    configure_logging_for_runtime(
        runtime_env=settings.runtime_env,
        inhouse_name="azents",
        configure_uvicorn=False,
        sentry_dsn=settings.sentry_dsn,
    )
    _LOGGER.info(
        "Runtime Control process starting",
        extra={
            "instance_id": settings.runtime_control_instance_id,
            "runtime_env": settings.runtime_env.value,
        },
    )
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for signum in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(signum, stop.set)
    async with runtime_control_server_lifespan(settings):
        await stop.wait()
