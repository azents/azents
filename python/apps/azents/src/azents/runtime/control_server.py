"""Agent Runtime Control gRPC server configuration and execution loop."""

import asyncio
import logging
import signal
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from datetime import timedelta

import boto3
import grpc
from azcommon.logging import RuntimeEnvironment, configure_logging_for_runtime
from mypy_boto3_rds import RDSClient
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, create_async_engine

from azents.core.config import PostgreSQLConfig
from azents.core.redis import create_redis_client
from azents.rdb.session import SessionManager
from azents.repos.agent_runtime import AgentRuntimeRepository
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
    runtime_control_auth_enabled: bool = False
    runtime_control_auth_token: str | None = None
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
    control_protocol = RuntimeControlProtocolService(coordination_store)
    control_token = runtime_control_auth_token(settings)
    engine = _create_engine(settings)
    session_manager = _session_manager(engine)
    runtime_repository = AgentRuntimeRepository()
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
            runner_control_auth_token=control_token,
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
    server = grpc.aio.server()
    add_runtime_provider_control_servicer(
        server,
        control_protocol=control_protocol,
        report_sink=provider_sink,
        owner_replica_id=settings.runtime_control_instance_id,
        consumer_id=f"{settings.runtime_control_instance_id}:provider",
        control_auth_token=control_token,
    )
    add_runtime_runner_control_servicer(
        server,
        control_protocol=control_protocol,
        coordination_store=coordination_store,
        state_sink=runner_sink,
        owner_replica_id=settings.runtime_control_instance_id,
        consumer_id=f"{settings.runtime_control_instance_id}:runner",
        control_auth_token=control_token,
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
            "start_timeout_seconds": settings.runtime_control_start_timeout_seconds,
            "lifecycle_retry_delay_seconds": (
                settings.runtime_control_lifecycle_retry_delay_seconds
            ),
            "auth_enabled": settings.runtime_control_auth_enabled,
        },
    )
    try:
        yield server
    finally:
        stop_reconciler.set()
        reconciler_task.cancel()
        try:
            await reconciler_task
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


def runtime_control_auth_token(settings: RuntimeControlSettings) -> str | None:
    if not settings.runtime_control_auth_enabled:
        return None
    token = settings.runtime_control_auth_token
    if token is None:
        raise RuntimeError(
            "AZ_RUNTIME_CONTROL_AUTH_TOKEN is required when "
            "AZ_RUNTIME_CONTROL_AUTH_ENABLED is true"
        )
    normalized = token.strip()
    if not normalized:
        raise RuntimeError(
            "AZ_RUNTIME_CONTROL_AUTH_TOKEN is required when "
            "AZ_RUNTIME_CONTROL_AUTH_ENABLED is true"
        )
    return normalized


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
