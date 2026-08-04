"""Worker dependency injection."""

import datetime
import os
from collections.abc import AsyncIterator
from typing import Annotated
from uuid import uuid4

from azcommon.infra.s3.service import S3Service
from azents_runtime_control.grpc_transfer_coordinator_client import (
    GrpcRuntimeTransferCoordinatorClient,
)
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
from azents.engine.run.commands import COMMAND_REGISTRY, CommandHandler
from azents.engine.run.retry_policy import (
    FailedRunRetryPolicy,
    get_failed_run_retry_policy,
)
from azents.engine.tools.builtin import BuiltinToolkitProvider
from azents.engine.tools.builtin_agents import ToolkitAgentsAppendixDedupeStateStore
from azents.engine.tools.claude_rules import (
    ClaudeRulesToolkitProvider,
    ToolkitClaudeRulesAppendixDedupeStateStore,
)
from azents.engine.tools.deps import get_vfs_projection_service
from azents.engine.tools.external_channel import ExternalChannelToolkitProvider
from azents.engine.tools.import_file import ImportFileStagingConfiguration
from azents.engine.tools.runtime_io import (
    RuntimeRunnerOperationClient as EngineRuntimeRunnerOperationClient,
)
from azents.engine.tools.skill import (
    SkillProjectionService,
    SkillStateStore,
    SkillToolkitProvider,
)
from azents.engine.tools.subagent import SubagentToolkitProvider
from azents.rdb.deps import get_session_manager
from azents.rdb.session import SessionManager
from azents.repos.agent import AgentRepository
from azents.repos.agent_execution import AgentRunRepository
from azents.repos.agent_runtime import AgentRuntimeRepository
from azents.repos.agent_session import AgentSessionRepository
from azents.repos.exchange_file import ExchangeFileRepository
from azents.repos.external_channel.work import ExternalChannelWorkRepository
from azents.repos.memory import MemoryRepository
from azents.repos.session_workspace_project import SessionWorkspaceProjectRepository
from azents.repos.toolkit import ToolkitRepository
from azents.repos.workspace_user import WorkspaceUserRepository
from azents.runtime.control_protocol.runner_operations import (
    RuntimeRunnerOperationClient as ControlRuntimeRunnerOperationClient,
)
from azents.runtime.deps import (
    get_runtime_runner_operation_client,
    get_worker_runtime_transfer_coordinator_client,
)
from azents.runtime.runner_operation_adapter import adapt_runtime_runner_operations
from azents.runtime.transfer.present_file_publication import (
    PresentFilePublicationService,
    RuntimeTransferObjectResolver,
)
from azents.runtime.transfer.runtime_image_read import RuntimeImageReadService
from azents.runtime.transfer.runtime_to_provider import (
    RuntimeToProviderBatchService,
    RuntimeToProviderDeliveryService,
)
from azents.runtime.transfer.runtime_to_server import RuntimeToServerTransferService
from azents.runtime.transfer.server_to_runtime import ServerToRuntimeTransferService
from azents.services.agent_runtime.service import AgentRuntimeService
from azents.services.artifact import ArtifactService
from azents.services.chat.live_events import RedisLiveEventStore
from azents.services.exchange_file import ExchangeFileService
from azents.services.external_channel.channel_action import (
    ExternalChannelActionService,
)
from azents.services.external_channel.connection import (
    get_external_channel_credentials_codec,
)
from azents.services.external_channel.credentials import (
    ExternalChannelCredentialsCodec,
)
from azents.services.external_channel.discord_files import DiscordChannelClient
from azents.services.external_channel.file_transfer import (
    ExternalChannelFileTransferService,
    ExternalChannelInboundStagingConfiguration,
    get_discord_file_client,
    get_slack_file_client,
)
from azents.services.external_channel.slack_events import SlackConversationClient
from azents.services.mailbox import MailboxService
from azents.services.model_file import ModelFileService
from azents.services.system_setting.service import SystemSettingsService
from azents.services.vfs import VfsProjectionService
from azents.utils.appctx import AppContext

from .config import AgentWorkerConfig
from .health import HealthServer

_DEFAULT_HEALTH_PORT = 8012
_TRANSFER_MAXIMUM_FILE_BYTES = 8 * 1024 * 1024
_TRANSFER_CHUNK_BYTES = 256 * 1024
_TRANSFER_MULTIPART_PART_BYTES = 5 * 1024 * 1024
_TRANSFER_STATUS_POLL_INTERVAL = datetime.timedelta(milliseconds=250)
_TRANSFER_CONSUMER_RENEW_INTERVAL = datetime.timedelta(seconds=10)
_TRANSFER_DEADLINE = datetime.timedelta(minutes=5)


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


def get_skill_toolkit_provider(
    runner_operations: Annotated[
        EngineRuntimeRunnerOperationClient,
        Depends(get_runtime_tool_operation_client),
    ],
    session_manager: Annotated[
        SessionManager[AsyncSession], Depends(get_session_manager)
    ],
    broadcast: Annotated[WebSocketBroadcast, Depends(get_broadcast)],
    vfs_projection_service: Annotated[
        VfsProjectionService,
        Depends(get_vfs_projection_service),
    ],
) -> SkillToolkitProvider:
    """SkillToolkitProvider dependency for Worker with runtime sync support."""
    store = SkillStateStore(session_manager=session_manager)
    return SkillToolkitProvider(
        store=store,
        projection_service=SkillProjectionService(
            store=store,
            session_manager=session_manager,
            runner_operations=runner_operations,
            runtime_repository=AgentRuntimeRepository(),
            project_repository=SessionWorkspaceProjectRepository(),
            broadcast=broadcast,
        ),
        vfs_projection_service=vfs_projection_service,
    )


def get_claude_rules_toolkit_provider(
    session_manager: Annotated[
        SessionManager[AsyncSession], Depends(get_session_manager)
    ],
) -> ClaudeRulesToolkitProvider:
    """ClaudeRulesToolkitProvider dependency for Worker."""
    return ClaudeRulesToolkitProvider(
        store=ToolkitClaudeRulesAppendixDedupeStateStore(
            session_manager=session_manager,
        )
    )


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
    vfs_projection_service: Annotated[
        VfsProjectionService,
        Depends(get_vfs_projection_service),
    ],
    agent_runtime_service: Annotated[
        AgentRuntimeService,
        Depends(),
    ],
    agent_session_repository: Annotated[
        AgentSessionRepository,
        Depends(AgentSessionRepository),
    ],
    config: Annotated[Config, Depends(get_config)],
    s3_service: Annotated[S3Service, Depends(get_s3_service)],
    coordinator: Annotated[
        GrpcRuntimeTransferCoordinatorClient | None,
        Depends(get_worker_runtime_transfer_coordinator_client),
    ],
) -> BuiltinToolkitProvider:
    """BuiltinToolkitProvider dependency for Worker."""
    transfer = create_worker_transfer_services(
        config=config,
        coordinator=coordinator,
        s3_service=s3_service,
        exchange_file_service=exchange_file_service,
        model_file_service=model_file_service,
    )
    return BuiltinToolkitProvider(
        exchange_file_service=exchange_file_service,
        artifact_service=artifact_service,
        model_file_service=model_file_service,
        vfs_projection_service=vfs_projection_service,
        agents_store=ToolkitAgentsAppendixDedupeStateStore(
            session_manager=session_manager,
        ),
        session_manager=session_manager,
        memory_repo=MemoryRepository(),
        agent_runtime_repo=AgentRuntimeRepository(),
        agent_runtime_service=agent_runtime_service,
        runner_operations=runner_operations,
        agent_session_repository=agent_session_repository,
        project_repo=SessionWorkspaceProjectRepository(),
        server_to_runtime_transfer_service=transfer.server_to_runtime,
        runtime_image_read_service=transfer.runtime_image_read,
        runtime_to_server_publication_service=transfer.present_file_publication,
        runtime_to_provider_delivery_service=transfer.provider_delivery,
        import_file_staging_configuration=transfer.import_staging,
    )


def get_worker_external_channel_file_transfer_service(
    session_manager: Annotated[
        SessionManager[AsyncSession], Depends(get_session_manager)
    ],
    repository: Annotated[
        ExternalChannelWorkRepository,
        Depends(ExternalChannelWorkRepository.create),
    ],
    credentials_codec: Annotated[
        ExternalChannelCredentialsCodec,
        Depends(get_external_channel_credentials_codec),
    ],
    slack_client: Annotated[
        SlackConversationClient,
        Depends(get_slack_file_client),
    ],
    discord_client: Annotated[
        DiscordChannelClient,
        Depends(get_discord_file_client),
    ],
    exchange_file_service: Annotated[ExchangeFileService, Depends(ExchangeFileService)],
    system_settings: Annotated[SystemSettingsService, Depends(SystemSettingsService)],
    config: Annotated[Config, Depends(get_config)],
    s3_service: Annotated[S3Service, Depends(get_s3_service)],
    coordinator: Annotated[
        GrpcRuntimeTransferCoordinatorClient | None,
        Depends(get_worker_runtime_transfer_coordinator_client),
    ],
) -> ExternalChannelFileTransferService:
    """Compose the Worker-only inbound provider staging boundary."""
    return ExternalChannelFileTransferService(
        session_manager=session_manager,
        repository=repository,
        credentials_codec=credentials_codec,
        slack_client=slack_client,
        discord_client=discord_client,
        exchange_file_service=exchange_file_service,
        system_settings=system_settings,
        inbound_staging_configuration=(
            create_worker_external_channel_inbound_staging_configuration(
                config=config,
                coordinator=coordinator,
                s3_service=s3_service,
            )
        ),
    )


def get_worker_external_channel_toolkit_provider(
    service: Annotated[ExternalChannelActionService, Depends()],
    file_transfer_service: Annotated[
        ExternalChannelFileTransferService,
        Depends(get_worker_external_channel_file_transfer_service),
    ],
) -> ExternalChannelToolkitProvider:
    """Provide External Channel tools with Worker transfer staging when available."""
    return ExternalChannelToolkitProvider(
        service=service,
        file_transfer_service=file_transfer_service,
    )


class _WorkerTransferServices:
    """Trusted Worker-only feature services sharing one Coordinator client."""

    def __init__(
        self,
        *,
        server_to_runtime: ServerToRuntimeTransferService,
        runtime_image_read: RuntimeImageReadService,
        present_file_publication: PresentFilePublicationService,
        provider_delivery: RuntimeToProviderDeliveryService,
        import_staging: ImportFileStagingConfiguration,
    ) -> None:
        self.server_to_runtime = server_to_runtime
        self.runtime_image_read = runtime_image_read
        self.present_file_publication = present_file_publication
        self.provider_delivery = provider_delivery
        self.import_staging = import_staging


def create_worker_transfer_services(
    *,
    config: Config,
    coordinator: GrpcRuntimeTransferCoordinatorClient | None,
    s3_service: S3Service,
    exchange_file_service: ExchangeFileService,
    model_file_service: ModelFileService,
) -> _WorkerTransferServices:
    """Compose feature consumers without constructing transfer state locally."""
    if coordinator is None:
        raise RuntimeError("Runtime Transfer Coordinator is required by the Worker")
    bucket = config.workspace_s3.bucket
    if not bucket:
        raise ValueError("Runtime transfer requires a workspace S3 bucket")
    object_prefix = _transfer_object_prefix(config)
    resolver = RuntimeTransferObjectResolver(
        bucket=bucket,
        object_prefix=object_prefix,
    )
    server_to_runtime = ServerToRuntimeTransferService(
        coordinator=coordinator,
        clock=_utc_now,
        status_poll_interval=_TRANSFER_STATUS_POLL_INTERVAL,
    )
    runtime_to_server = RuntimeToServerTransferService(
        coordinator=coordinator,
        clock=_utc_now,
        status_poll_interval=_TRANSFER_STATUS_POLL_INTERVAL,
        consumer_lease_renew_interval=_TRANSFER_CONSUMER_RENEW_INTERVAL,
    )
    provider_delivery = RuntimeToProviderDeliveryService(
        batch_service=RuntimeToProviderBatchService(
            coordinator=coordinator,
            resolver=resolver,
            object_store=s3_service,
            clock=_utc_now,
            status_poll_interval=_TRANSFER_STATUS_POLL_INTERVAL,
            consumer_lease_renew_interval=_TRANSFER_CONSUMER_RENEW_INTERVAL,
            maximum_chunk_size=_TRANSFER_CHUNK_BYTES,
        ),
        product_maximum_size=_TRANSFER_MAXIMUM_FILE_BYTES,
        provider_maximum_size=_TRANSFER_MAXIMUM_FILE_BYTES,
        deadline=_TRANSFER_DEADLINE,
        resource_class="external_channel",
    )
    return _WorkerTransferServices(
        server_to_runtime=server_to_runtime,
        runtime_image_read=RuntimeImageReadService(
            transfer_service=runtime_to_server,
            resolver=resolver,
            s3_service=s3_service,
            model_file_service=model_file_service,
            product_maximum_size=_TRANSFER_MAXIMUM_FILE_BYTES,
            deadline=_TRANSFER_DEADLINE,
        ),
        present_file_publication=PresentFilePublicationService(
            transfer_service=runtime_to_server,
            resolver=resolver,
            exchange_file_service=exchange_file_service,
            product_maximum_size=_TRANSFER_MAXIMUM_FILE_BYTES,
            provider_maximum_size=_TRANSFER_MAXIMUM_FILE_BYTES,
            deadline=_TRANSFER_DEADLINE,
        ),
        provider_delivery=provider_delivery,
        import_staging=ImportFileStagingConfiguration(
            s3_service=s3_service,
            workspace_bucket=bucket,
            transfer_object_prefix=object_prefix,
            multipart_copy_threshold=_TRANSFER_MULTIPART_PART_BYTES,
            multipart_part_size=_TRANSFER_MULTIPART_PART_BYTES,
            maximum_size=_TRANSFER_MAXIMUM_FILE_BYTES,
            deadline_after=_TRANSFER_DEADLINE,
        ),
    )


def create_worker_external_channel_inbound_staging_configuration(
    *,
    config: Config,
    coordinator: GrpcRuntimeTransferCoordinatorClient | None,
    s3_service: S3Service,
) -> ExternalChannelInboundStagingConfiguration:
    """Return trusted provider staging for the required Worker Coordinator."""
    if coordinator is None:
        raise RuntimeError("Runtime Transfer Coordinator is required by the Worker")
    bucket = config.workspace_s3.bucket
    if not bucket:
        raise ValueError("Runtime transfer requires a workspace S3 bucket")
    return ExternalChannelInboundStagingConfiguration(
        s3_service=s3_service,
        workspace_bucket=bucket,
        transfer_object_prefix=_transfer_object_prefix(config),
        stream_chunk_size=_TRANSFER_CHUNK_BYTES,
        multipart_part_size=_TRANSFER_MULTIPART_PART_BYTES,
        multipart_copy_threshold=_TRANSFER_MULTIPART_PART_BYTES,
        multipart_copy_part_size=_TRANSFER_MULTIPART_PART_BYTES,
        deadline_after=_TRANSFER_DEADLINE,
    )


def _transfer_object_prefix(config: Config) -> str:
    """Derive the configured transfer namespace beneath the workspace prefix."""
    return "/".join(
        part.strip("/")
        for part in (
            config.workspace_s3.prefix,
            config.runtime_transfer_coordinator.object_prefix,
        )
        if part.strip("/")
    )


def _utc_now() -> datetime.datetime:
    """Return the timezone-aware Worker clock for transfer deadlines."""
    return datetime.datetime.now(datetime.UTC)


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


def get_subagent_toolkit_provider(
    session_manager: Annotated[
        SessionManager[AsyncSession], Depends(get_session_manager)
    ],
    broker: Annotated[SessionBroker, Depends(get_worker_broker)],
    mailbox_item_service: Annotated[MailboxService, Depends(MailboxService)],
    agent_repository: Annotated[AgentRepository, Depends(AgentRepository)],
) -> SubagentToolkitProvider:
    """SubagentToolkitProvider dependency for Worker."""
    return SubagentToolkitProvider(
        session_manager=session_manager,
        broker=broker,
        mailbox_item_service=mailbox_item_service,
        agent_repository=agent_repository,
    )


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


def get_health_server(
    worker_redis: Annotated[Redis, Depends(get_worker_redis)],
) -> HealthServer:
    """HealthServer dependency.

    :param worker_redis: Redis client
    :return: HealthServer instance
    """
    port = int(os.environ.get("AZ_WORKER_HEALTH_PORT", str(_DEFAULT_HEALTH_PORT)))
    return HealthServer(worker_redis, port=port)


def get_toolkit_repository(
    cipher: Annotated[CredentialCipher, Depends(get_credential_cipher)],
) -> ToolkitRepository:
    """Toolkit repository dependency."""
    return ToolkitRepository(cipher=cipher)


def get_worker_config(
    config: Annotated[Config, Depends(get_config)],
    failed_run_retry_policy: Annotated[
        FailedRunRetryPolicy,
        Depends(get_failed_run_retry_policy),
    ],
) -> AgentWorkerConfig:
    """Worker run settings dependency."""
    return AgentWorkerConfig(
        web_url=config.web_url,
        oauth_secret_key=config.credential_encryption.key,
        mcp_proxy_url=config.mcp_proxy_url,
        openai_responses_websocket_enabled=(config.openai_responses_websocket_enabled),
        failed_run_retry_policy=failed_run_retry_policy,
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
    agent_run_repository: Annotated[AgentRunRepository, Depends(AgentRunRepository)],
    workspace_user_repository: Annotated[
        WorkspaceUserRepository, Depends(WorkspaceUserRepository)
    ],
) -> ExchangeFileService:
    """ExchangeFileService dependency for Worker."""
    return ExchangeFileService(
        exchange_file_repository=exchange_file_repository,
        agent_repository=agent_repository,
        agent_session_repository=agent_session_repository,
        agent_run_repository=agent_run_repository,
        workspace_user_repository=workspace_user_repository,
        session_manager=session_manager,
        s3_service=s3_service,
        config=config,
    )
