"""User-authorized Scheduled Task sequencing around completed owner operations."""

from typing import Annotated

from fastapi import Depends

from azents.core.scheduled_task_management import (
    ScheduledTaskCurrentCycleProjection,
    ScheduledTaskManagementProjection,
)
from azents.rdb.deps import get_read_only_session_manager, get_session_manager
from azents.rdb.session import SessionManager
from azents.rdb.session_capabilities import ReadSession, WriteSession
from azents.repos.agent import AgentRepository
from azents.repos.agent_session import AgentSessionRepository
from azents.repos.external_channel.management import (
    ExternalChannelManagementRepository,
)
from azents.repos.external_channel.repository import ExternalChannelRepository
from azents.repos.mailbox import MailboxRepository
from azents.repos.scheduled_task.definition import RDBScheduledTaskAuthorityValidator
from azents.repos.scheduled_task.management_operations import (
    ScheduledTaskManagementRepository,
)
from azents.repos.scheduled_task.repository import ScheduledTaskRepository
from azents.repos.scheduled_task_cycle import ScheduledTaskCycleRepository
from azents.services.scheduled_task.channel import (
    ScheduledTaskChannelService,
    get_scheduled_task_channel_service,
)


class ScheduledTaskManagementService:
    """Manage Scheduled Tasks through completed authorized database operations."""

    def __init__(
        self,
        *,
        operations: ScheduledTaskManagementRepository,
        channel_service: ScheduledTaskChannelService,
    ) -> None:
        self.operations = operations
        self.channel_service = channel_service

    async def list_tasks(
        self,
        *,
        workspace_id: str,
        agent_id: str,
        user_id: str,
        session_id: str | None,
    ) -> list[ScheduledTaskManagementProjection]:
        """Sequence the completed list_tasks owner operation."""
        return await self.operations.list_tasks(
            workspace_id=workspace_id,
            agent_id=agent_id,
            user_id=user_id,
            session_id=session_id,
        )

    async def create(
        self,
        *,
        workspace_id: str,
        agent_id: str,
        user_id: str,
        session_id: str,
        title: str,
        objective: str,
        at: str | None,
        cron: str | None,
        timezone: str | None,
        channel_id: str | None,
    ) -> ScheduledTaskManagementProjection:
        """Sequence the completed create owner operation."""
        mutation = await self.operations.create(
            workspace_id=workspace_id,
            agent_id=agent_id,
            user_id=user_id,
            session_id=session_id,
            title=title,
            objective=objective,
            at=at,
            cron=cron,
            timezone=timezone,
            channel_id=channel_id,
        )
        await self.channel_service.execute_registration(mutation.task)
        return mutation.projection

    async def get(
        self,
        *,
        workspace_id: str,
        agent_id: str,
        user_id: str,
        task_id: str,
    ) -> ScheduledTaskManagementProjection:
        """Sequence the completed get owner operation."""
        return await self.operations.get(
            workspace_id=workspace_id,
            agent_id=agent_id,
            user_id=user_id,
            task_id=task_id,
        )

    async def replace(
        self,
        *,
        workspace_id: str,
        agent_id: str,
        user_id: str,
        task_id: str,
        title: str,
        objective: str,
        at: str | None,
        cron: str | None,
        timezone: str | None,
        channel_id: str | None,
    ) -> ScheduledTaskManagementProjection:
        """Sequence the completed replace owner operation."""
        mutation = await self.operations.replace(
            workspace_id=workspace_id,
            agent_id=agent_id,
            user_id=user_id,
            task_id=task_id,
            title=title,
            objective=objective,
            at=at,
            cron=cron,
            timezone=timezone,
            channel_id=channel_id,
        )
        return mutation.projection

    async def delete(
        self,
        *,
        workspace_id: str,
        agent_id: str,
        user_id: str,
        task_id: str,
    ) -> None:
        """Sequence the completed delete owner operation."""
        deleted = await self.operations.delete(
            workspace_id=workspace_id,
            agent_id=agent_id,
            user_id=user_id,
            task_id=task_id,
        )
        await self.channel_service.execute_deletion(deleted)

    async def get_current_cycle(
        self,
        *,
        workspace_id: str,
        agent_id: str,
        user_id: str,
        task_id: str,
    ) -> ScheduledTaskCurrentCycleProjection | None:
        """Sequence the completed get_current_cycle owner operation."""
        return await self.operations.get_current_cycle(
            workspace_id=workspace_id,
            agent_id=agent_id,
            user_id=user_id,
            task_id=task_id,
        )


def get_scheduled_task_management_service(
    read_session_manager: Annotated[
        SessionManager[ReadSession], Depends(get_read_only_session_manager)
    ],
    session_manager: Annotated[
        SessionManager[WriteSession],
        Depends(get_session_manager),
    ],
    agent_repository: Annotated[AgentRepository, Depends()],
    agent_session_repository: Annotated[AgentSessionRepository, Depends()],
    task_repository: Annotated[ScheduledTaskRepository, Depends()],
    cycle_repository: Annotated[ScheduledTaskCycleRepository, Depends()],
    mailbox_repository: Annotated[MailboxRepository, Depends()],
    external_channel_repository: Annotated[
        ExternalChannelRepository,
        Depends(ExternalChannelRepository.create),
    ],
    external_channel_management_repository: Annotated[
        ExternalChannelManagementRepository,
        Depends(ExternalChannelManagementRepository.create),
    ],
    channel_service: Annotated[
        ScheduledTaskChannelService,
        Depends(get_scheduled_task_channel_service),
    ],
) -> ScheduledTaskManagementService:
    """Compose the user-authorized Scheduled Task management service."""
    return ScheduledTaskManagementService(
        operations=ScheduledTaskManagementRepository(
            read_session_manager=read_session_manager,
            session_manager=session_manager,
            agent_repository=agent_repository,
            agent_session_repository=agent_session_repository,
            task_repository=task_repository,
            cycle_repository=cycle_repository,
            mailbox_repository=mailbox_repository,
            external_channel_repository=external_channel_repository,
            external_channel_management_repository=(
                external_channel_management_repository
            ),
            authority_validator=RDBScheduledTaskAuthorityValidator(),
        ),
        channel_service=channel_service,
    )
