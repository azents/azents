"""Agent Runtime Control gRPC server configuration and execution loop."""

import asyncio
import dataclasses
import logging
import os
import signal
import sys
import time
import uuid
from collections.abc import AsyncGenerator, AsyncIterator, Callable
from contextlib import AsyncExitStack, asynccontextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Literal, Protocol

import aioboto3
import boto3
import grpc
from aiohttp import web
from azcommon.infra.s3.service import S3Service
from azcommon.logging import RuntimeEnvironment, configure_logging_for_runtime
from azents_runtime_control.proto import (
    runtime_web_session_pb2,
    runtime_web_session_pb2_grpc,
)
from azents_runtime_control.runner import RunnerStateReport as SharedRunnerStateReport
from azents_runtime_control.runtime_configuration import (
    RuntimeConfigurationEvidence,
)
from azents_runtime_control.runtime_web_capacity import CapacityProfile
from azents_runtime_control.runtime_web_session import (
    APPROVED_SESSION_PROFILE,
    RUNTIME_WEB_PROTOCOL_FINGERPRINT,
    OwnerSessionEpoch,
    RunnerSessionOffer,
    validate_runner_web_connect_address,
)
from kubernetes_asyncio.client.api.authentication_v1_api import AuthenticationV1Api
from kubernetes_asyncio.client.api_client import ApiClient
from kubernetes_asyncio.config import load_incluster_config
from mypy_boto3_rds import RDSClient
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict
from redis.asyncio import Redis
from redis.exceptions import RedisError
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
from azents.repos.runtime_connection_generation.repository import (
    CURRENT_ALLOCATOR_VERSION,
    RuntimeConnectionGenerationRepository,
)
from azents.repos.runtime_lifecycle_dispatch.repository import (
    RuntimeLifecycleDispatchRepository,
)
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
from azents.repos.runtime_web.session_route_repository import (
    RuntimeWebSessionRouteConflict,
    RuntimeWebSessionRouteRepository,
)
from azents.runtime.control_protocol.data import RuntimeRunnerRegistration
from azents.runtime.control_protocol.grpc.auth import (
    RuntimeTransferCoordinatorCredentialGrpcAuth,
)
from azents.runtime.control_protocol.grpc.provider_server import (
    add_runtime_provider_control_servicer,
)
from azents.runtime.control_protocol.grpc.runner_server import (
    RuntimeWebSessionOfferProvider,
    add_runtime_runner_control_servicer,
)
from azents.runtime.control_protocol.grpc.runner_terminal_broker import (
    CoordinatedRuntimeRunnerTerminalBroker,
)
from azents.runtime.control_protocol.grpc.runner_terminal_server import (
    add_runtime_runner_terminal_servicer,
)
from azents.runtime.control_protocol.grpc.runner_transfer_server import (
    add_runtime_runner_transfer_servicer,
)
from azents.runtime.control_protocol.grpc.runtime_web_session_server import (
    RuntimeWebCapacityBackend,
    RuntimeWebCapacityConfig,
    RuntimeWebCapacityRegistry,
    RuntimeWebControlDataPlane,
    RuntimeWebControlHardLimits,
    RuntimeWebTrustedPeerAuthenticator,
    add_runtime_web_session_servicers,
    create_runtime_web_control_operations_application,
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
from azents.runtime.terminal_coordination.redis import (
    RedisRuntimeTerminalCoordinationStore,
)
from azents.runtime.terminal_coordination.store import (
    RuntimeTerminalCoordinationStore,
)
from azents.runtime.terminal_dispatcher import (
    RuntimeTerminalControlDispatcherAdapter,
)
from azents.runtime.terminal_integration import (
    CompositeRuntimeRunnerGenerationObserver,
    CoordinatedRuntimeTerminalInvalidationPublisher,
    RuntimeTerminalRunnerGenerationObserver,
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
from azents.runtime.web_session_owner import (
    RuntimeWebOwnedSession,
    RuntimeWebOwnerSessionRegistry,
    RuntimeWebSessionOwnerManager,
)
from azents.runtime.web_session_relay import (
    GrpcPersistentControlRelay,
    PersistentRelayConnection,
    RelaySessionKey,
    RuntimeWebRelayPool,
)
from azents.services.runtime_connection_registration.service import (
    RuntimeProviderConnectionRegistrationService,
    RuntimeRunnerConnectionRegistrationService,
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
_DEFAULT_TERMINAL_REPAIR_INTERVAL_SECONDS = 1.0
_TERMINAL_REPAIR_LIMIT = 100
_DEFAULT_TRANSFER_OBJECT_PREFIX = "runtime-transfer"
_MAX_TRANSFER_TTL_SECONDS = 3_600
_MAX_TRANSFER_PROCESS_BUFFER_BYTES = 64 * 1024 * 1024
_RUNTIME_WEB_SESSION_OFFER_WAIT_SECONDS = 10.0
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


class _DisabledRuntimeWebSessionOfferProvider:
    """Return no session offer when Runtime Web is disabled."""

    async def offer_for_runner(
        self,
        *,
        runtime_id: str,
        runner_generation: int,
    ) -> RunnerSessionOffer | None:
        del runtime_id, runner_generation
        return None

    async def owned_for_runner(
        self,
        *,
        runtime_id: str,
        runner_generation: int,
    ) -> RuntimeWebOwnedSession | None:
        del runtime_id, runner_generation
        return None

    async def renew_owner(self, owner: OwnerSessionEpoch) -> bool:
        del owner
        return False

    async def mark_owner_draining(self, owner: OwnerSessionEpoch) -> bool:
        del owner
        return False

    async def release_owner(self, owner: OwnerSessionEpoch) -> bool:
        del owner
        return False


class _OwnerRuntimeWebSessionOfferProvider:
    """Acquire one exact Owner epoch for each registered Runner generation."""

    def __init__(
        self,
        *,
        session_manager: SessionManager[AsyncSession],
        runtime_repository: AgentRuntimeRepository,
        owner_manager: RuntimeWebSessionOwnerManager,
        generation_gate: _RuntimeWebRunnerGenerationGate,
    ) -> None:
        self.session_manager = session_manager
        self.runtime_repository = runtime_repository
        self.owner_manager = owner_manager
        self.generation_gate = generation_gate
        self.owned: dict[str, RuntimeWebOwnedSession] = {}
        self.lock = asyncio.Lock()

    async def offer_for_runner(
        self,
        *,
        runtime_id: str,
        runner_generation: int,
    ) -> RunnerSessionOffer | None:
        ready = await self.generation_gate.wait(
            runtime_id=runtime_id,
            runner_generation=runner_generation,
            timeout_seconds=_RUNTIME_WEB_SESSION_OFFER_WAIT_SECONDS,
        )
        async with self.session_manager() as session:
            runtime = await self.runtime_repository.get_by_id(session, runtime_id)
        if (
            not ready
            or runtime is None
            or runtime.desired_generation <= 0
            or runtime.runner_generation != runner_generation
        ):
            _LOGGER.warning(
                "Runtime Web session offer unavailable",
                extra={
                    "runner_generation": runner_generation,
                    "reason": "runner_generation_not_current",
                },
            )
            return None
        async with self.lock:
            previous = self.owned.pop(runtime_id, None)
            if previous is not None:
                await self.owner_manager.release(previous)
            try:
                owned = await self.owner_manager.acquire(
                    runtime_id=runtime_id,
                    desired_generation=runtime.desired_generation,
                    runner_generation=runner_generation,
                )
            except RuntimeWebSessionRouteConflict:
                _LOGGER.warning(
                    "Runtime Web session offer unavailable",
                    extra={
                        "runner_generation": runner_generation,
                        "reason": "owner_route_conflict",
                    },
                )
                return None
            self.owned[runtime_id] = owned
            _LOGGER.info(
                "Runtime Web session offer issued",
                extra={
                    "runner_generation": runner_generation,
                    "owner_replica_id": owned.route.owner_replica_id,
                    "lease_generation": owned.route.lease_generation,
                },
            )
            return owned.offer

    async def owned_for_runner(
        self,
        *,
        runtime_id: str,
        runner_generation: int,
    ) -> RuntimeWebOwnedSession | None:
        """Return the exact offer already issued to one Runner generation."""
        async with self.lock:
            owned = self.owned.get(runtime_id)
            if (
                owned is None
                or owned.offer.owner.runner_generation != runner_generation
            ):
                return None
            return owned

    async def renew_owner(self, owner: OwnerSessionEpoch) -> bool:
        async with self.lock:
            current = self.owned.get(owner.runtime_id)
        if current is None or current.offer.owner != owner:
            return False
        renewed = await self.owner_manager.renew(current)
        async with self.lock:
            if self.owned.get(owner.runtime_id) != current:
                return False
            self.owned[owner.runtime_id] = renewed
        return True

    async def mark_owner_draining(self, owner: OwnerSessionEpoch) -> bool:
        async with self.lock:
            current = self.owned.get(owner.runtime_id)
        if current is None or current.offer.owner != owner:
            return False
        draining = await self.owner_manager.mark_draining(current)
        async with self.lock:
            if self.owned.get(owner.runtime_id) != current:
                return False
            self.owned[owner.runtime_id] = draining
        return True

    async def release_owner(self, owner: OwnerSessionEpoch) -> bool:
        async with self.lock:
            current = self.owned.get(owner.runtime_id)
            if current is None or current.offer.owner != owner:
                return False
            self.owned.pop(owner.runtime_id)
        return await self.owner_manager.release(current)


class _RuntimeWebRunnerGenerationGate:
    """Signal exact Runner-generation persistence without polling."""

    def __init__(self) -> None:
        self.ready: set[tuple[str, int]] = set()
        self.events: dict[tuple[str, int], asyncio.Event] = {}
        self.lock = asyncio.Lock()

    async def mark(self, *, runtime_id: str, runner_generation: int) -> None:
        key = (runtime_id, runner_generation)
        async with self.lock:
            self.ready.add(key)
            event = self.events.get(key)
            if event is not None:
                event.set()

    async def wait(
        self,
        *,
        runtime_id: str,
        runner_generation: int,
        timeout_seconds: float,
    ) -> bool:
        key = (runtime_id, runner_generation)
        async with self.lock:
            if key in self.ready:
                return True
            event = self.events.setdefault(key, asyncio.Event())
        try:
            await asyncio.wait_for(event.wait(), timeout=timeout_seconds)
        except TimeoutError:
            async with self.lock:
                if self.events.get(key) is event:
                    self.events.pop(key)
            return False
        async with self.lock:
            self.ready.discard(key)
            if self.events.get(key) is event:
                self.events.pop(key)
        return True


class _RuntimeWebRunnerStateSink:
    """Signal after the ordinary Runner report is durably persisted."""

    def __init__(
        self,
        *,
        delegate: RuntimeRunnerStateRepositorySink,
        generation_gate: _RuntimeWebRunnerGenerationGate,
    ) -> None:
        self.delegate = delegate
        self.generation_gate = generation_gate

    async def validate_runner_registration(
        self,
        registration: RuntimeRunnerRegistration,
    ) -> bool:
        return await self.delegate.validate_runner_registration(registration)

    async def configuration_evidence_for_runner_heartbeat(
        self,
        *,
        runtime_id: str,
    ) -> RuntimeConfigurationEvidence | None:
        return await self.delegate.configuration_evidence_for_runner_heartbeat(
            runtime_id=runtime_id
        )

    async def record_runner_state(self, report: SharedRunnerStateReport) -> None:
        await self.delegate.record_runner_state(report)
        await self.generation_gate.mark(
            runtime_id=report.runtime_id,
            runner_generation=report.runner_generation,
        )


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
    runtime_control_web_transport_enabled: bool = False
    runtime_control_trusted_port: int = 8032
    runtime_control_trusted_advertise_address: str = ""
    runtime_control_trusted_gateway_peer_identities: str = ""
    runtime_control_trusted_control_peer_identities: str = ""
    runtime_control_web_route_lease_seconds: float = 10.0
    runtime_control_runner_web_connect_address: str = ""
    runtime_control_runner_web_tls_server_name: str = ""
    runtime_control_web_metrics_port: int = Field(default=8033, ge=1, le=65_535)
    runtime_control_web_capacity_backend: Literal["memory", "redis"] = "memory"
    runtime_control_web_capacity_maximum_active_streams: int | None = None
    runtime_control_web_capacity_maximum_sse_streams: int | None = None
    runtime_control_web_capacity_maximum_websocket_streams: int | None = None
    runtime_control_web_capacity_maximum_pending_opens: int | None = None
    runtime_control_web_capacity_maximum_buffer_bytes: int | None = None
    runtime_control_web_capacity_inbound_bytes_per_second: int | None = None
    runtime_control_web_capacity_outbound_bytes_per_second: int | None = None
    runtime_control_web_capacity_burst_bytes: int | None = None
    runtime_control_web_capacity_redis_namespace: str = "azents:runtime:web:capacity"
    runtime_control_web_capacity_redis_ttl_seconds: int = Field(
        default=30,
        ge=1,
        le=300,
    )
    runtime_control_web_maximum_relay_sessions: int = Field(
        default=32,
        ge=1,
        le=256,
    )
    runtime_control_web_hard_maximum_sessions: int | None = None
    runtime_control_web_hard_maximum_active_streams: int | None = None
    runtime_control_web_hard_maximum_application_buffer_bytes: int | None = None
    runtime_control_web_hard_maximum_control_buffer_bytes: int | None = None
    runtime_control_web_hard_maximum_queued_envelopes: int | None = None
    runtime_control_web_hard_maximum_pending_tasks: int | None = None
    runtime_control_web_hard_maximum_event_loop_lag_milliseconds: int | None = None
    runtime_control_web_hard_maximum_resident_memory_bytes: int | None = None
    runtime_control_instance_id: str = "azents-runtime-control-local"
    runtime_control_reconcile_interval_seconds: float = (
        _DEFAULT_RECONCILE_INTERVAL_SECONDS
    )
    runtime_control_lifecycle_retry_delay_seconds: float = (
        _DEFAULT_LIFECYCLE_RETRY_DELAY_SECONDS
    )
    runtime_control_start_timeout_seconds: float = _DEFAULT_START_TIMEOUT_SECONDS
    testenv_runtime_control_heartbeat_interval_seconds: int = Field(
        default=20,
        gt=0,
    )
    runtime_control_kubernetes_token_review_enabled: bool = False
    runtime_control_transfer_backend: Literal["memory", "redis"] = "redis"
    runtime_control_transfer_redis_namespace: str = "azents:runtime:transfer:v2"
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


@dataclasses.dataclass(frozen=True)
class _RuntimeWebTrustedTransport:
    """Mutually authenticated Gateway/Control transport configuration."""

    server_credentials: grpc.ServerCredentials | None
    channel_credentials: grpc.ChannelCredentials | None
    allow_insecure: bool


class _ChannelRelay:
    """Close one persistent relay and its owned gRPC channel together."""

    def __init__(
        self,
        *,
        relay: GrpcPersistentControlRelay,
        channel: grpc.aio.Channel,
    ) -> None:
        self.relay = relay
        self.channel = channel

    async def send(
        self,
        envelope: runtime_web_session_pb2.RuntimeWebSessionEnvelope,
    ) -> None:
        await self.relay.send(envelope)

    async def close(self) -> None:
        try:
            await self.relay.close()
        finally:
            await self.channel.close()

    async def wait_closed(self) -> None:
        await self.relay.wait_closed()


class _RuntimeWebCapacityRedisAdapter:
    """Expose the exact coroutine-based capacity Redis contract."""

    def __init__(self, client: Redis) -> None:
        self.client = client

    async def get(self, name: str) -> bytes | str | None:
        return await self.client.get(name)

    async def set(self, name: str, value: str, *, ex: int) -> object:
        return await self.client.set(name, value, ex=ex)


@asynccontextmanager
async def runtime_control_server_lifespan(
    settings: RuntimeControlSettings,
) -> AsyncGenerator[grpc.aio.Server]:
    """Manage runtime-control gRPC server resources."""
    validate_runtime_control_transfer_settings(settings)
    validate_runtime_control_web_settings(settings)
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
    terminal_coordination = RedisRuntimeTerminalCoordinationStore(redis)
    runner_generation_observer = CompositeRuntimeRunnerGenerationObserver(
        transfer_coordinator,
        RuntimeTerminalRunnerGenerationObserver(
            store=terminal_coordination,
            clock=clock,
        ),
    )
    control_protocol = RuntimeControlProtocolService(
        coordination_store,
        runner_generation_observer=runner_generation_observer,
    )
    terminal_dispatcher = RuntimeTerminalControlDispatcherAdapter(
        control_protocol=control_protocol,
        terminal_coordination=terminal_coordination,
        runtime_coordination=coordination_store,
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
    generation_repository = RuntimeConnectionGenerationRepository()
    async with session_manager() as session:
        cutover = await generation_repository.get_cutover(session)
    if cutover is None or cutover.allocator_version != CURRENT_ALLOCATOR_VERSION:
        raise RuntimeError("Runtime connection generation authority is not activated")
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
    web_runner_generation_gate = _RuntimeWebRunnerGenerationGate()
    runner_sink = _RuntimeWebRunnerStateSink(
        delegate=RuntimeRunnerStateRepositorySink(
            runtime_repository=runtime_repository,
            profile_repository=profile_repository,
            session_manager=session_manager,
        ),
        generation_gate=web_runner_generation_gate,
    )
    runner_credential_verifier = RuntimeRunnerCredentialVerifier(
        settings.credential_encryption_key
    )
    runner_authenticator = RuntimeRunnerAuthenticationService(
        session_manager=session_manager,
        runtime_repository=runtime_repository,
        verifier=runner_credential_verifier,
    )
    provider_connection_registrar = RuntimeProviderConnectionRegistrationService(
        session_manager=session_manager,
        generation_repository=generation_repository,
        coordination_store=coordination_store,
        provider_control=enrollment_service,
        clock=clock,
        heartbeat_interval_seconds=(
            settings.testenv_runtime_control_heartbeat_interval_seconds
        ),
    )
    runner_connection_registrar = RuntimeRunnerConnectionRegistrationService(
        session_manager=session_manager,
        generation_repository=generation_repository,
        coordination_store=coordination_store,
        runner_authentication=runner_authenticator,
        generation_observer=runner_generation_observer,
        heartbeat_interval_seconds=(
            settings.testenv_runtime_control_heartbeat_interval_seconds
        ),
    )
    web_session_offer_provider: RuntimeWebSessionOfferProvider = (
        _DisabledRuntimeWebSessionOfferProvider()
    )
    owner_offer_provider: _OwnerRuntimeWebSessionOfferProvider | None = None
    owner_registry: RuntimeWebOwnerSessionRegistry | None = None
    web_data_plane: RuntimeWebControlDataPlane | None = None
    trusted_transport: _RuntimeWebTrustedTransport | None = None
    if settings.runtime_control_web_transport_enabled:
        trusted_transport = runtime_web_trusted_transport(settings)
        control_boot_id = uuid.uuid4().hex
        route_repository = RuntimeWebSessionRouteRepository()
        owner_manager = RuntimeWebSessionOwnerManager(
            session_manager=session_manager,
            repository=route_repository,
            owner_replica_id=settings.runtime_control_instance_id,
            owner_boot_id=control_boot_id,
            trusted_owner_address=(settings.runtime_control_trusted_advertise_address),
            runner_connect_address=(
                settings.runtime_control_runner_web_connect_address
            ),
            runner_tls_server_name=(
                settings.runtime_control_runner_web_tls_server_name
            ),
            lease_seconds=settings.runtime_control_web_route_lease_seconds,
            clock=clock,
        )
        owner_offer_provider = _OwnerRuntimeWebSessionOfferProvider(
            session_manager=session_manager,
            runtime_repository=runtime_repository,
            owner_manager=owner_manager,
            generation_gate=web_runner_generation_gate,
        )
        web_session_offer_provider = owner_offer_provider
        owner_registry = RuntimeWebOwnerSessionRegistry(
            session_manager=session_manager,
            repository=route_repository,
            clock=clock,
        )
        capacity_registry = RuntimeWebCapacityRegistry(
            config=_runtime_web_capacity_config(settings),
            redis=_RuntimeWebCapacityRedisAdapter(redis),
            monotonic_clock_milliseconds=lambda: int(time.monotonic() * 1000),
            recoverable_errors=(RedisError, OSError, TimeoutError),
        )

        async def connect_relay(
            key: RelaySessionKey,
        ) -> PersistentRelayConnection:
            data_plane = web_data_plane
            relay_transport = trusted_transport
            if data_plane is None or relay_transport is None:
                raise RuntimeError("Runtime Web relay composition is unavailable")
            channel = _runtime_web_relay_channel(
                await data_plane.owner_address(key.owner),
                transport=relay_transport,
            )
            hello = _runtime_web_relay_hello(
                key=key,
                control_boot_id=control_boot_id,
                clock=clock,
            )
            try:
                relay = await GrpcPersistentControlRelay.connect(
                    key=key,
                    stream=(
                        runtime_web_session_pb2_grpc.RuntimeWebControlSessionStub(
                            channel
                        ).Relay
                    ),
                    hello=hello,
                    handler=lambda envelope: data_plane.relay_response(
                        key,
                        envelope,
                    ),
                    timeout_seconds=10,
                    resources=data_plane.resources,
                )
            except BaseException:
                await channel.close()
                raise
            return _ChannelRelay(relay=relay, channel=channel)

        relay_pool = RuntimeWebRelayPool(
            connector=connect_relay,
            maximum_sessions=settings.runtime_control_web_maximum_relay_sessions,
            peer_boot_id=control_boot_id,
        )
        resident_memory_sampler = create_runtime_web_control_resident_memory_sampler(
            platform=sys.platform,
        )
        web_data_plane = RuntimeWebControlDataPlane(
            session_manager=session_manager,
            route_repository=route_repository,
            owner_replica_id=settings.runtime_control_instance_id,
            control_boot_id=control_boot_id,
            capacity_registry=capacity_registry,
            relay_pool=relay_pool,
            runner_metrics=coordination_store,
            clock=clock,
            metrics_recoverable_errors=(RedisError, OSError, TimeoutError),
            owner_lifecycle=owner_offer_provider,
            long_lived_grace_seconds=5,
            finite_grace_seconds=120,
            hard_limits=_runtime_web_control_hard_limits(settings),
            resident_memory_bytes=resident_memory_sampler.current_bytes,
        )
    reconciler = RuntimeLifecycleReconciler(
        agent_repository=agent_repository,
        runtime_repository=runtime_repository,
        profile_repository=profile_repository,
        session_manager=session_manager,
        dispatch_repository=RuntimeLifecycleDispatchRepository(
            agent_repository=agent_repository,
            runtime_repository=runtime_repository,
            profile_repository=profile_repository,
            session_manager=session_manager,
        ),
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
        terminal_invalidation_publisher=(
            CoordinatedRuntimeTerminalInvalidationPublisher(
                store=terminal_coordination,
                dispatcher=terminal_dispatcher,
                clock=clock,
            )
        ),
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
    stop_terminal_repair = asyncio.Event()
    terminal_repair_task = asyncio.create_task(
        _run_terminal_repair(
            terminal_coordination,
            dispatcher=terminal_dispatcher,
            clock=clock,
            stop=stop_terminal_repair,
            interval_seconds=_DEFAULT_TERMINAL_REPAIR_INTERVAL_SECONDS,
            limit=_TERMINAL_REPAIR_LIMIT,
        ),
        name="runtime-terminal-repair",
    )
    server = grpc.aio.server()
    trusted_server: grpc.aio.Server | None = None
    if settings.runtime_control_web_transport_enabled:
        trusted_server = grpc.aio.server()
        if (
            web_data_plane is None
            or owner_offer_provider is None
            or owner_registry is None
        ):
            raise RuntimeError("Runtime Web Control composition is incomplete")
        peer_authenticator = RuntimeWebTrustedPeerAuthenticator(
            allow_insecure=settings.runtime_control_allow_insecure,
            gateway_identities=(
                frozenset()
                if settings.runtime_control_allow_insecure
                else _peer_identities(
                    settings.runtime_control_trusted_gateway_peer_identities
                )
            ),
            control_identities=(
                frozenset()
                if settings.runtime_control_allow_insecure
                else _peer_identities(
                    settings.runtime_control_trusted_control_peer_identities
                )
            ),
        )
        add_runtime_web_session_servicers(
            trusted_server=trusted_server,
            runner_server=server,
            data_plane=web_data_plane,
            offer_provider=owner_offer_provider,
            owner_registry=owner_registry,
            runner_authenticator=runner_authenticator,
            peer_authenticator=peer_authenticator,
            clock=clock,
            owner_renew_interval_seconds=max(
                0.1,
                settings.runtime_control_web_route_lease_seconds / 3,
            ),
        )
    add_runtime_provider_control_servicer(
        server,
        control_protocol=control_protocol,
        report_sink=provider_sink,
        observe_completion_handler=reconciler,
        owner_replica_id=settings.runtime_control_instance_id,
        consumer_id=f"{settings.runtime_control_instance_id}:provider",
        credential_authenticator=enrollment_service,
        connection_tracker=enrollment_service,
        connection_registrar=provider_connection_registrar,
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
        connection_registrar=runner_connection_registrar,
        transfer_result_sink=transfer_result_coordinator,
        web_session_offer_provider=web_session_offer_provider,
    )
    add_runtime_runner_terminal_servicer(
        server,
        broker=CoordinatedRuntimeRunnerTerminalBroker(
            store=terminal_coordination,
            clock=clock,
            monotonic_clock=time.monotonic,
        ),
        runner_authenticator=runner_authenticator,
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
    if trusted_server is not None and trusted_transport is not None:
        trusted_listen_address = f"0.0.0.0:{settings.runtime_control_trusted_port}"
        if trusted_transport.server_credentials is None:
            trusted_server.add_insecure_port(trusted_listen_address)
        else:
            trusted_server.add_secure_port(
                trusted_listen_address,
                trusted_transport.server_credentials,
            )
    await server.start()
    if trusted_server is not None:
        await trusted_server.start()
    web_operations_runner: web.AppRunner | None = None
    web_process_sampler_task: asyncio.Task[None] | None = None
    if web_data_plane is not None:
        web_operations_runner = web.AppRunner(
            create_runtime_web_control_operations_application(web_data_plane)
        )
        await web_operations_runner.setup()
        await web.TCPSite(
            web_operations_runner,
            host="0.0.0.0",
            port=settings.runtime_control_web_metrics_port,
        ).start()
        web_process_sampler_task = asyncio.create_task(
            _refresh_runtime_web_control_process_pressure(
                web_data_plane,
                resident_memory_sampler=resident_memory_sampler,
            ),
            name="runtime-web-control-process-pressure",
        )
    _LOGGER.info(
        "Runtime Control gRPC server started",
        extra={
            "instance_id": settings.runtime_control_instance_id,
            "port": settings.runtime_control_port,
            "trusted_port": settings.runtime_control_trusted_port,
            "trusted_advertise_address": (
                settings.runtime_control_trusted_advertise_address
            ),
            "reconcile_interval_seconds": (
                settings.runtime_control_reconcile_interval_seconds
            ),
            "start_timeout_seconds": settings.runtime_control_start_timeout_seconds,
            "lifecycle_retry_delay_seconds": (
                settings.runtime_control_lifecycle_retry_delay_seconds
            ),
            "runner_authentication": "runtime_bound_credential",
            "tls_enabled": transport.server_credentials is not None,
            "web_transport_enabled": settings.runtime_control_web_transport_enabled,
            "web_metrics_port": (
                settings.runtime_control_web_metrics_port
                if settings.runtime_control_web_transport_enabled
                else None
            ),
            "trusted_tls_enabled": (
                trusted_transport is not None
                and trusted_transport.server_credentials is not None
            ),
        },
    )
    try:
        yield server
    finally:
        stop_reconciler.set()
        stop_transfer_repair.set()
        stop_terminal_repair.set()
        reconciler_task.cancel()
        transfer_repair_task.cancel()
        terminal_repair_task.cancel()
        try:
            await reconciler_task
        except asyncio.CancelledError:
            pass
        try:
            await transfer_repair_task
        except asyncio.CancelledError:
            pass
        try:
            await terminal_repair_task
        except asyncio.CancelledError:
            pass
        if web_data_plane is not None:
            await web_data_plane.begin_drain()
        if web_process_sampler_task is not None:
            web_process_sampler_task.cancel()
            try:
                await web_process_sampler_task
            except asyncio.CancelledError:
                pass
        if trusted_server is not None:
            await trusted_server.stop(grace=0)
        await server.stop(grace=0)
        if web_operations_runner is not None:
            await web_operations_runner.cleanup()
        if web_data_plane is not None:
            await web_data_plane.close()
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


async def _run_terminal_repair(
    coordination: RuntimeTerminalCoordinationStore,
    *,
    dispatcher: RuntimeTerminalControlDispatcherAdapter,
    clock: Callable[[], datetime],
    stop: asyncio.Event,
    interval_seconds: float,
    limit: int,
) -> None:
    """Run bounded volatile Terminal lifecycle deadline repair."""
    if interval_seconds <= 0:
        raise ValueError("Runtime Terminal repair interval must be positive")
    if limit <= 0:
        raise ValueError("Runtime Terminal repair limit must be positive")
    while not stop.is_set():
        try:
            now = clock()
            repaired = await coordination.repair_expired(
                current_time=now,
                limit=limit,
            )
            for terminal_id in repaired.terminal_ids:
                record = await coordination.get_terminal(
                    terminal_id,
                    current_time=now,
                )
                if record is None or record.termination_reason is None:
                    continue
                await dispatcher.terminate_terminal(
                    record,
                    reason=record.termination_reason,
                    requested_at=now,
                )
            if repaired.terminal_ids:
                _LOGGER.info(
                    "Runtime Terminal repair requested termination",
                    extra={"terminal_count": len(repaired.terminal_ids)},
                )
        except Exception:
            _LOGGER.exception("Runtime Terminal repair iteration failed")
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


def validate_runtime_control_web_settings(
    settings: RuntimeControlSettings,
) -> None:
    """Reject unsafe or ambiguous Runtime Web owner transport settings."""
    if not settings.runtime_control_web_transport_enabled:
        return
    if not 1 <= settings.runtime_control_web_route_lease_seconds <= 60:
        raise ValueError("Runtime Web route lease must be within 1 to 60 seconds")
    address = settings.runtime_control_trusted_advertise_address.strip()
    if not address or "://" in address or ":" not in address:
        raise ValueError("Runtime Web trusted advertise address must be host:port")
    validate_runner_web_connect_address(
        settings.runtime_control_runner_web_connect_address
    )
    if not settings.runtime_control_runner_web_tls_server_name.strip():
        raise ValueError("Runtime Web Runner TLS server name is required")
    if settings.runtime_control_trusted_port < 0:
        raise ValueError("Runtime Web trusted port must not be negative")
    if settings.runtime_control_web_metrics_port in {
        settings.runtime_control_port,
        settings.runtime_control_trusted_port,
    }:
        raise ValueError("Runtime Web metrics port must be separate")
    _runtime_web_capacity_config(settings)
    _runtime_web_control_hard_limits(settings)
    if not settings.runtime_control_allow_insecure:
        _peer_identities(settings.runtime_control_trusted_gateway_peer_identities)
        _peer_identities(settings.runtime_control_trusted_control_peer_identities)


def _runtime_web_capacity_config(
    settings: RuntimeControlSettings,
) -> RuntimeWebCapacityConfig:
    values = {
        "maximum active streams": (
            settings.runtime_control_web_capacity_maximum_active_streams
        ),
        "maximum SSE streams": (
            settings.runtime_control_web_capacity_maximum_sse_streams
        ),
        "maximum WebSocket streams": (
            settings.runtime_control_web_capacity_maximum_websocket_streams
        ),
        "maximum pending opens": (
            settings.runtime_control_web_capacity_maximum_pending_opens
        ),
        "maximum buffer bytes": (
            settings.runtime_control_web_capacity_maximum_buffer_bytes
        ),
        "inbound bytes per second": (
            settings.runtime_control_web_capacity_inbound_bytes_per_second
        ),
        "outbound bytes per second": (
            settings.runtime_control_web_capacity_outbound_bytes_per_second
        ),
        "burst bytes": settings.runtime_control_web_capacity_burst_bytes,
    }
    missing = tuple(name for name, value in values.items() if value is None)
    if missing:
        raise ValueError(
            "Runtime Web capacity settings are required: " + ", ".join(sorted(missing))
        )
    positive = {name: value for name, value in values.items() if value is not None}
    if any(value <= 0 for value in positive.values()):
        raise ValueError("Runtime Web capacity settings must be positive")
    return RuntimeWebCapacityConfig(
        backend=RuntimeWebCapacityBackend(
            settings.runtime_control_web_capacity_backend
        ),
        profile=CapacityProfile(
            maximum_active_streams=positive["maximum active streams"],
            maximum_sse_streams=positive["maximum SSE streams"],
            maximum_websocket_streams=positive["maximum WebSocket streams"],
            maximum_pending_opens=positive["maximum pending opens"],
            maximum_buffer_bytes=positive["maximum buffer bytes"],
            inbound_bytes_per_second=positive["inbound bytes per second"],
            outbound_bytes_per_second=positive["outbound bytes per second"],
            burst_bytes=positive["burst bytes"],
        ),
        redis_namespace=settings.runtime_control_web_capacity_redis_namespace,
        redis_ttl_seconds=settings.runtime_control_web_capacity_redis_ttl_seconds,
    )


def _runtime_web_control_hard_limits(
    settings: RuntimeControlSettings,
) -> RuntimeWebControlHardLimits:
    values = {
        "maximum sessions": settings.runtime_control_web_hard_maximum_sessions,
        "maximum active streams": (
            settings.runtime_control_web_hard_maximum_active_streams
        ),
        "maximum application buffer bytes": (
            settings.runtime_control_web_hard_maximum_application_buffer_bytes
        ),
        "maximum control buffer bytes": (
            settings.runtime_control_web_hard_maximum_control_buffer_bytes
        ),
        "maximum queued envelopes": (
            settings.runtime_control_web_hard_maximum_queued_envelopes
        ),
        "maximum pending tasks": (
            settings.runtime_control_web_hard_maximum_pending_tasks
        ),
        "maximum event-loop lag milliseconds": (
            settings.runtime_control_web_hard_maximum_event_loop_lag_milliseconds
        ),
        "maximum resident memory bytes": (
            settings.runtime_control_web_hard_maximum_resident_memory_bytes
        ),
    }
    missing = tuple(name for name, value in values.items() if value is None)
    if missing:
        raise ValueError(
            "Runtime Web Control hard-limit settings are required: "
            + ", ".join(sorted(missing))
        )
    positive = {name: value for name, value in values.items() if value is not None}
    if any(value <= 0 for value in positive.values()):
        raise ValueError("Runtime Web Control hard-limit settings must be positive")
    limits = RuntimeWebControlHardLimits(
        maximum_sessions=positive["maximum sessions"],
        maximum_active_streams=positive["maximum active streams"],
        maximum_application_buffer_bytes=positive["maximum application buffer bytes"],
        maximum_control_buffer_bytes=positive["maximum control buffer bytes"],
        maximum_queued_envelopes=positive["maximum queued envelopes"],
        maximum_pending_tasks=positive["maximum pending tasks"],
        maximum_event_loop_lag_milliseconds=positive[
            "maximum event-loop lag milliseconds"
        ],
        maximum_resident_memory_bytes=positive["maximum resident memory bytes"],
    )
    capacity = _runtime_web_capacity_config(settings)
    if limits.maximum_active_streams < capacity.profile.maximum_active_streams:
        raise ValueError(
            "Runtime Web Control hard stream limit must not be smaller than "
            "one Runtime capacity limit"
        )
    if limits.maximum_application_buffer_bytes < capacity.profile.maximum_buffer_bytes:
        raise ValueError(
            "Runtime Web Control hard application-buffer limit must not be "
            "smaller than one Runtime capacity limit"
        )
    return limits


class RuntimeWebControlResidentMemorySampler:
    """Read current Control RSS without retaining process or application content."""

    def __init__(self, *, statm_path: Path, page_size_bytes: int) -> None:
        if page_size_bytes <= 0:
            raise ValueError("Runtime Web Control RSS page size must be positive")
        self.statm_path = statm_path
        self.page_size_bytes = page_size_bytes

    def current_bytes(self) -> int:
        """Return current RSS bytes from the Linux procfs resident-page field."""
        try:
            fields = self.statm_path.read_text(encoding="ascii").split()
        except OSError as error:
            raise RuntimeError(
                "Runtime Web Control current RSS sample is unavailable"
            ) from error
        if len(fields) < 2:
            raise RuntimeError("Runtime Web Control current RSS sample is invalid")
        try:
            resident_pages = int(fields[1])
        except ValueError as error:
            raise RuntimeError(
                "Runtime Web Control current RSS sample is invalid"
            ) from error
        if resident_pages < 0:
            raise RuntimeError("Runtime Web Control current RSS sample is invalid")
        return resident_pages * self.page_size_bytes


def create_runtime_web_control_resident_memory_sampler(
    *,
    platform: str,
) -> RuntimeWebControlResidentMemorySampler:
    """Select one explicit current-RSS backend or fail safely."""
    if platform.startswith("linux"):
        return RuntimeWebControlResidentMemorySampler(
            statm_path=Path("/proc/self/statm"),
            page_size_bytes=int(os.sysconf("SC_PAGE_SIZE")),
        )
    raise RuntimeError(
        "Runtime Web Control current RSS sampling is unsupported on platform "
        f"{platform!r}"
    )


async def _refresh_runtime_web_control_process_pressure(
    data_plane: RuntimeWebControlDataPlane,
    *,
    resident_memory_sampler: RuntimeWebControlResidentMemorySampler,
) -> None:
    """Continuously measure event-loop progress for probes and metrics."""
    loop = asyncio.get_running_loop()
    expected = loop.time()
    while True:
        expected += 0.25
        await asyncio.sleep(max(0.0, expected - loop.time()))
        observed = loop.time()
        data_plane.update_process_pressure(
            lag_milliseconds=max(0.0, (observed - expected) * 1000),
            resident_memory_bytes=resident_memory_sampler.current_bytes(),
        )


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


def runtime_web_trusted_transport(
    settings: RuntimeControlSettings,
) -> _RuntimeWebTrustedTransport:
    """Build the isolated mutually authenticated Gateway/Control transport."""
    if settings.runtime_control_allow_insecure:
        return _RuntimeWebTrustedTransport(
            server_credentials=None,
            channel_credentials=None,
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
    ca = ca_path.read_bytes()
    if not certificate.strip() or not private_key.strip() or not ca.strip():
        raise RuntimeError("Runtime Web trusted TLS files must not be empty")
    return _RuntimeWebTrustedTransport(
        server_credentials=grpc.ssl_server_credentials(
            [(private_key, certificate)],
            root_certificates=ca,
            require_client_auth=True,
        ),
        channel_credentials=grpc.ssl_channel_credentials(
            root_certificates=ca,
            private_key=private_key,
            certificate_chain=certificate,
        ),
        allow_insecure=False,
    )


def _runtime_web_relay_channel(
    endpoint: str,
    *,
    transport: _RuntimeWebTrustedTransport,
) -> grpc.aio.Channel:
    if not endpoint.strip():
        raise ValueError("Runtime Web owner address must not be empty")
    if transport.channel_credentials is not None:
        return grpc.aio.secure_channel(endpoint, transport.channel_credentials)
    if transport.allow_insecure:
        return grpc.aio.insecure_channel(endpoint)
    raise RuntimeError("Runtime Web relay transport is not configured")


def _runtime_web_relay_hello(
    *,
    key: RelaySessionKey,
    control_boot_id: str,
    clock: Callable[[], datetime],
) -> runtime_web_session_pb2.RuntimeWebSessionEnvelope:
    """Create one exact Control-to-Owner persistent relay handshake."""
    deadline = clock() + timedelta(seconds=10)
    hello = runtime_web_session_pb2.RuntimeWebSessionHello(
        role=runtime_web_session_pb2.RUNTIME_WEB_SESSION_PEER_ROLE_CONTROL,
        runtime_id=key.owner.runtime_id,
        desired_generation=key.owner.desired_generation,
        runner_generation=key.owner.runner_generation,
        session_nonce=key.owner.session_lease_id,
        maximum_data_frame_bytes=APPROVED_SESSION_PROFILE.data_frame_bytes,
        request_stream_window_bytes=(
            APPROVED_SESSION_PROFILE.request_stream_window_bytes
        ),
        response_stream_window_bytes=(
            APPROVED_SESSION_PROFILE.response_stream_window_bytes
        ),
        request_session_window_bytes=(
            APPROVED_SESSION_PROFILE.request_session_window_bytes
        ),
        response_session_window_bytes=(
            APPROVED_SESSION_PROFILE.response_session_window_bytes
        ),
    )
    hello.deadline_at.FromDatetime(deadline)
    return runtime_web_session_pb2.RuntimeWebSessionEnvelope(
        protocol_fingerprint=RUNTIME_WEB_PROTOCOL_FINGERPRINT,
        session_id=key.owner.session_lease_id,
        peer_boot_id=control_boot_id,
        owner_boot_id=key.owner.owner_boot_id,
        session_lease_id=key.owner.session_lease_id,
        lease_generation=key.owner.lease_generation,
        hello=hello,
    )


def _peer_identities(value: str) -> frozenset[str]:
    identities = frozenset(item.strip() for item in value.split(",") if item.strip())
    if not identities:
        raise ValueError("Runtime Web trusted peer identities must not be empty")
    return identities


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
