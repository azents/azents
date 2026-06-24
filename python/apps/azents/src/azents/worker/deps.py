"""Worker dependency injection."""

import os
from collections.abc import AsyncIterator
from typing import Annotated
from uuid import uuid4

from azcommon.infra.s3.service import S3Service
from fastapi import Depends
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from azents.broker.broadcast import WebSocketBroadcast
from azents.broker.redis import RedisBroker
from azents.broker.types import SessionBroker
from azents.core.config import Config
from azents.core.crypto import CredentialCipher
from azents.core.deps import get_appctx, get_config, get_credential_cipher
from azents.core.redis import create_redis_client
from azents.core.s3.deps import get_s3_service
from azents.engine.run.background import BackgroundTaskRegistry
from azents.engine.run.commands import COMMAND_REGISTRY, CommandHandler
from azents.engine.tools.builtin import BuiltinToolkitProvider
from azents.engine.tools.runtime_io import (
    RuntimeRunnerOperationClient as EngineRuntimeRunnerOperationClient,
)
from azents.rdb.deps import get_session_manager
from azents.rdb.session import SessionManager
from azents.repos.agent import AgentRepository
from azents.repos.agent_runtime import AgentRuntimeRepository
from azents.repos.agent_session import AgentSessionRepository
from azents.repos.exchange_file import ExchangeFileRepository
from azents.repos.llm_provider_integration import LLMProviderIntegrationRepository
from azents.repos.memory import MemoryRepository
from azents.repos.session_workspace_project import SessionWorkspaceProjectRepository
from azents.repos.toolkit import ToolkitRepository
from azents.repos.workspace_user import WorkspaceUserRepository
from azents.runtime.control_protocol.runner_operations import (
    RuntimeRunnerOperationClient as ControlRuntimeRunnerOperationClient,
)
from azents.runtime.deps import get_runtime_runner_operation_client
from azents.services.artifact import ArtifactService
from azents.services.chat.live_events import RedisLiveEventStore
from azents.services.exchange_file import ExchangeFileService
from azents.services.input_buffer import InputBufferService
from azents.services.model_file import ModelFileService
from azents.utils.appctx import AppContext

from .config import AgentWorkerConfig
from .health import HealthServer
from .input.background_result_injector import BackgroundTaskResultInjector
from .runtime_io import adapt_runtime_runner_operations

_DEFAULT_HEALTH_PORT = 8012


def get_worker_id() -> str:
    """Create Worker ID. Created only once by Container cache."""
    return uuid4().hex


def get_runtime_tool_operation_client(
    runner_operations: Annotated[
        ControlRuntimeRunnerOperationClient,
        Depends(get_runtime_runner_operation_client),
    ],
) -> EngineRuntimeRunnerOperationClient:
    """Convert Runtime control client to engine runtime I/O protocol."""
    return adapt_runtime_runner_operations(runner_operations)


def get_builtin_toolkit_provider(
    runner_operations: Annotated[
        EngineRuntimeRunnerOperationClient,
        Depends(get_runtime_tool_operation_client),
    ],
    session_manager: Annotated[
        SessionManager[AsyncSession], Depends(get_session_manager)
    ],
    exchange_file_service: Annotated[ExchangeFileService, Depends(ExchangeFileService)],
    artifact_service: Annotated[ArtifactService, Depends(ArtifactService)],
    model_file_service: Annotated[ModelFileService, Depends(ModelFileService)],
) -> BuiltinToolkitProvider:
    """BuiltinToolkitProvider dependency for Worker."""
    return BuiltinToolkitProvider(
        exchange_file_service=exchange_file_service,
        artifact_service=artifact_service,
        model_file_service=model_file_service,
        session_manager=session_manager,
        memory_repo=MemoryRepository(),
        agent_runtime_repo=AgentRuntimeRepository(),
        runner_operations=runner_operations,
        project_repo=SessionWorkspaceProjectRepository(),
    )


async def get_worker_broker(
    appctx: Annotated[AppContext[Config], Depends(get_appctx)],
    worker_id: Annotated[str, Depends(get_worker_id)],
) -> SessionBroker:
    """Worker-only SessionBroker (includes worker_id, calls setup()).

    Cached by AppContext and created only once in same process.
    """

    async def create_broker() -> AsyncIterator[RedisBroker]:
        redis = create_redis_client(appctx.config.redis.url)
        broker = RedisBroker(redis, worker_id=worker_id)
        await broker.setup()
        try:
            yield broker
        finally:
            await redis.aclose()

    return await appctx.get_variable(f"{__name__}.get_worker_broker", create_broker)


async def get_worker_redis(
    appctx: Annotated[AppContext[Config], Depends(get_appctx)],
) -> Redis:
    """Worker-only Redis client.

    Cached by AppContext and created only once in same process.
    """

    async def create_redis() -> AsyncIterator[Redis]:
        redis = create_redis_client(appctx.config.redis.url)
        try:
            yield redis
        finally:
            await redis.aclose()

    return await appctx.get_variable(f"{__name__}.get_worker_redis", create_redis)


async def get_broadcast(
    appctx: Annotated[AppContext[Config], Depends(get_appctx)],
) -> WebSocketBroadcast:
    """Worker-only WebSocketBroadcast dependency (cached by AppContext)."""

    async def create() -> AsyncIterator[WebSocketBroadcast]:
        redis = create_redis_client(appctx.config.redis.url)
        broadcast = WebSocketBroadcast(redis)
        try:
            yield broadcast
        finally:
            await redis.aclose()

    return await appctx.get_variable(f"{__name__}.get_broadcast", create)


def get_health_server(
    worker_redis: Annotated[Redis, Depends(get_worker_redis)],
) -> HealthServer:
    """HealthServer dependency.

    :param worker_redis: Redis client
    :return: HealthServer instance
    """
    port = int(os.environ.get("AZ_WORKER_HEALTH_PORT", str(_DEFAULT_HEALTH_PORT)))
    return HealthServer(worker_redis, port=port)


def get_llm_provider_integration_repository(
    cipher: Annotated[CredentialCipher, Depends(get_credential_cipher)],
) -> LLMProviderIntegrationRepository:
    """LLM provider integration repository dependency."""
    return LLMProviderIntegrationRepository(cipher=cipher)


def get_toolkit_repository(
    cipher: Annotated[CredentialCipher, Depends(get_credential_cipher)],
) -> ToolkitRepository:
    """Toolkit repository dependency."""
    return ToolkitRepository(cipher=cipher)


def get_worker_config(
    config: Annotated[Config, Depends(get_config)],
) -> AgentWorkerConfig:
    """Worker run settings dependency."""
    return AgentWorkerConfig(
        web_url=config.web_url,
        oauth_secret_key=config.credential_encryption.key,
        mcp_proxy_url=config.mcp_proxy_url,
    )


def get_live_event_store(
    worker_redis: Annotated[Redis, Depends(get_worker_redis)],
) -> RedisLiveEventStore:
    """Worker live event store dependency."""
    return RedisLiveEventStore(worker_redis)


def get_command_registry() -> dict[str, CommandHandler]:
    """Worker command registry dependency."""
    return COMMAND_REGISTRY


def get_exchange_file_service(
    config: Annotated[Config, Depends(get_config)],
    session_manager: Annotated[
        SessionManager[AsyncSession], Depends(get_session_manager)
    ],
    s3_service: Annotated[S3Service, Depends(get_s3_service)],
    exchange_file_repository: Annotated[
        ExchangeFileRepository, Depends(ExchangeFileRepository)
    ],
    agent_repository: Annotated[AgentRepository, Depends(AgentRepository)],
    agent_session_repository: Annotated[
        AgentSessionRepository, Depends(AgentSessionRepository)
    ],
    workspace_user_repository: Annotated[
        WorkspaceUserRepository, Depends(WorkspaceUserRepository)
    ],
) -> ExchangeFileService:
    """ExchangeFileService dependency for Worker."""
    return ExchangeFileService(
        exchange_file_repository=exchange_file_repository,
        agent_repository=agent_repository,
        agent_session_repository=agent_session_repository,
        workspace_user_repository=workspace_user_repository,
        session_manager=session_manager,
        s3_service=s3_service,
        config=config,
    )


def get_background_registry(
    broker: Annotated[SessionBroker, Depends(get_worker_broker)],
    session_manager: Annotated[
        SessionManager[AsyncSession], Depends(get_session_manager)
    ],
    input_buffer_service: Annotated[InputBufferService, Depends(InputBufferService)],
) -> BackgroundTaskRegistry:
    """BackgroundTaskRegistry dependency."""
    background_result_injector = BackgroundTaskResultInjector(
        broker=broker,
        session_manager=session_manager,
        input_buffer_service=input_buffer_service,
    )
    return BackgroundTaskRegistry(on_complete=background_result_injector.inject)
