"""Agent Runtime Control gRPC server configuration and execution loop."""

import asyncio
import logging
import signal
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from datetime import timedelta
from typing import cast

import boto3
import grpc
from azcommon.logging import RuntimeEnvironment, configure_logging_for_runtime
from mypy_boto3_rds import RDSClient
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, create_async_engine

from azents.broker.redis import RedisBroker
from azents.core.config import PostgreSQLConfig
from azents.core.redis import create_redis_client
from azents.rdb.session import SessionManager
from azents.repos.agent_execution import EventTranscriptRepository
from azents.repos.agent_runtime import AgentRuntimeRepository
from azents.repos.agent_session import AgentSessionRepository
from azents.repos.input_buffer import InputBufferRepository
from azents.runtime.control_protocol.grpc.provider_server import (
    add_runtime_provider_control_servicer,
)
from azents.runtime.control_protocol.grpc.runner_server import (
    add_runtime_runner_control_servicer,
)
from azents.runtime.control_protocol.grpc.state_sinks import (
    RuntimeProviderReportRepositorySink,
    RuntimeRunnerStateRepositorySink,
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
from azents.services.exchange_file import ExchangeFileService
from azents.services.input_buffer import InputBufferService
from azents.services.model_file import ModelFileService
from azents.worker.input.background_completion_publisher import (
    BackgroundCompletionPublisherConfig,
    RuntimeBackgroundCompletionPublisher,
)
from azents.worker.input.queue import DatabaseWorkerInputQueue

_DEFAULT_PORT = 8030
_DEFAULT_RECONCILE_INTERVAL_SECONDS = 15.0
_DEFAULT_START_TIMEOUT_SECONDS = 300.0
_DEFAULT_LIFECYCLE_RETRY_DELAY_SECONDS = 15.0
_LOGGER = logging.getLogger(__name__)


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
    runtime_control_completion_interval_seconds: float = 1.0
    runtime_runner_image: str
    runtime_runner_control_endpoint: str
    rdb_host: str = "localhost"
    rdb_port: int = 5432
    rdb_user: str = "azents"
    rdb_password: str | None = None
    rdb_db_name: str = "azents"
    rdb_use_iam_auth: bool = False
    rdb_region: str = "us-west-2"
    rdb_ssl_mode: str = "prefer"
    rdb_verbose: bool = False


@asynccontextmanager
async def runtime_control_server_lifespan(
    settings: RuntimeControlSettings,
) -> AsyncGenerator[grpc.aio.Server]:
    """Manage runtime-control gRPC server resources."""
    redis = create_redis_client(settings.redis_url)
    coordination_store = RedisRuntimeCoordinationStore(redis)
    broker = RedisBroker(redis)
    control_protocol = RuntimeControlProtocolService(coordination_store)
    engine = _create_engine(settings)
    session_manager = _session_manager(engine)
    runtime_repository = AgentRuntimeRepository()
    session_repository = AgentSessionRepository()
    input_buffer_service = InputBufferService(
        session_manager=session_manager,
        input_buffer_repository=InputBufferRepository(),
        exchange_file_service=cast(ExchangeFileService, object()),
        model_file_service=cast(ModelFileService, object()),
        agent_session_repository=session_repository,
        event_transcript_repository=cast(EventTranscriptRepository, object()),
    )
    worker_input_queue = DatabaseWorkerInputQueue(
        broker=broker,
        session_manager=session_manager,
        agent_runtime_repository=runtime_repository,
        agent_session_repository=session_repository,
        input_buffer_service=input_buffer_service,
    )
    provider_sink = RuntimeProviderReportRepositorySink(
        runtime_repository=runtime_repository,
        session_manager=session_manager,
    )
    runner_sink = RuntimeRunnerStateRepositorySink(
        runtime_repository=runtime_repository,
        session_manager=session_manager,
    )
    reconciler = RuntimeLifecycleReconciler(
        runtime_repository=runtime_repository,
        session_manager=session_manager,
        coordination_store=coordination_store,
        control_protocol=control_protocol,
        config=RuntimeLifecycleDispatchConfig(
            runner_image=settings.runtime_runner_image,
            runner_control_endpoint=settings.runtime_runner_control_endpoint,
            start_timeout=timedelta(
                seconds=settings.runtime_control_start_timeout_seconds
            ),
            lifecycle_retry_delay=timedelta(
                seconds=settings.runtime_control_lifecycle_retry_delay_seconds
            ),
        ),
    )
    stop_reconciler = asyncio.Event()
    reconciler_task = asyncio.create_task(
        _run_reconciler(
            reconciler,
            stop=stop_reconciler,
            interval_seconds=settings.runtime_control_reconcile_interval_seconds,
        ),
        name="runtime-lifecycle-reconciler",
    )
    completion_publisher = RuntimeBackgroundCompletionPublisher(
        coordination_store=coordination_store,
        worker_input_queue=worker_input_queue,
        config=BackgroundCompletionPublisherConfig(
            claimant_id=f"{settings.runtime_control_instance_id}:completion"
        ),
    )
    stop_completion_publisher = asyncio.Event()
    completion_publisher_task = asyncio.create_task(
        _run_background_completion_publisher(
            completion_publisher,
            stop=stop_completion_publisher,
            interval_seconds=settings.runtime_control_completion_interval_seconds,
        ),
        name="runtime-background-completion-publisher",
    )
    server = grpc.aio.server()
    add_runtime_provider_control_servicer(
        server,
        control_protocol=control_protocol,
        report_sink=provider_sink,
        owner_replica_id=settings.runtime_control_instance_id,
        consumer_id=f"{settings.runtime_control_instance_id}:provider",
    )
    add_runtime_runner_control_servicer(
        server,
        control_protocol=control_protocol,
        coordination_store=coordination_store,
        state_sink=runner_sink,
        owner_replica_id=settings.runtime_control_instance_id,
        consumer_id=f"{settings.runtime_control_instance_id}:runner",
    )
    server.add_insecure_port(f"0.0.0.0:{settings.runtime_control_port}")
    await server.start()
    _LOGGER.info(
        "Runtime Control gRPC server started",
        extra={
            "instance_id": settings.runtime_control_instance_id,
            "port": settings.runtime_control_port,
            "reconcile_interval_seconds": (
                settings.runtime_control_reconcile_interval_seconds
            ),
            "completion_interval_seconds": (
                settings.runtime_control_completion_interval_seconds
            ),
            "start_timeout_seconds": settings.runtime_control_start_timeout_seconds,
            "lifecycle_retry_delay_seconds": (
                settings.runtime_control_lifecycle_retry_delay_seconds
            ),
        },
    )
    try:
        yield server
    finally:
        stop_reconciler.set()
        stop_completion_publisher.set()
        reconciler_task.cancel()
        completion_publisher_task.cancel()
        try:
            await reconciler_task
        except asyncio.CancelledError:
            pass
        try:
            await completion_publisher_task
        except asyncio.CancelledError:
            pass
        await server.stop(grace=5)
        await redis.aclose()
        await engine.dispose()


async def _run_reconciler(
    reconciler: RuntimeLifecycleReconciler,
    *,
    stop: asyncio.Event,
    interval_seconds: float,
) -> None:
    while not stop.is_set():
        try:
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


async def _run_background_completion_publisher(
    publisher: RuntimeBackgroundCompletionPublisher,
    *,
    stop: asyncio.Event,
    interval_seconds: float,
) -> None:
    while not stop.is_set():
        try:
            published = await publisher.publish_once()
            if published:
                _LOGGER.info(
                    "Runtime background completion publisher emitted events",
                    extra={"published": published},
                )
        except Exception:
            _LOGGER.exception(
                "Runtime background completion publisher iteration failed"
            )
        try:
            await asyncio.wait_for(stop.wait(), timeout=interval_seconds)
        except TimeoutError:
            continue


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
    settings = RuntimeControlSettings()  # pyright: ignore[reportCallIssue]  # env supplies required deployment settings.
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
