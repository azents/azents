"""Scheduled Task v1 Public API."""

from textwrap import dedent
from typing import Annotated, NoReturn

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from azents.core.auth.deps import WorkspaceMember, get_workspace_member
from azents.engine.tools.deps import get_scheduled_task_channel_service
from azents.rdb.deps import get_session_manager
from azents.rdb.session import SessionManager
from azents.repos.agent import AgentRepository
from azents.repos.agent_session.repository import AgentSessionRepository
from azents.repos.external_channel.management import (
    ExternalChannelManagementRepository,
)
from azents.repos.external_channel.repository import ExternalChannelRepository
from azents.repos.mailbox import MailboxRepository
from azents.repos.scheduled_task.repository import ScheduledTaskRepository
from azents.repos.scheduled_task_cycle import ScheduledTaskCycleRepository
from azents.services.scheduled_task.channel import ScheduledTaskChannelService
from azents.services.scheduled_task.management import (
    ScheduledTaskManagementService,
    ScheduledTaskManagementUnavailable,
)
from azents.services.scheduled_task.service import RDBScheduledTaskAuthorityValidator
from azents.utils.fastapi.route import RouteMounter

from .data import (
    ScheduledTaskCreateRequest,
    ScheduledTaskCurrentCycleEnvelope,
    ScheduledTaskCurrentCycleResponse,
    ScheduledTaskListResponse,
    ScheduledTaskReplaceRequest,
    ScheduledTaskResponse,
)

router = APIRouter()


def get_scheduled_task_management_service(
    session_manager: Annotated[
        SessionManager[AsyncSession],
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
        session_manager=session_manager,
        agent_repository=agent_repository,
        agent_session_repository=agent_session_repository,
        task_repository=task_repository,
        cycle_repository=cycle_repository,
        mailbox_repository=mailbox_repository,
        external_channel_repository=external_channel_repository,
        external_channel_management_repository=(external_channel_management_repository),
        channel_service=channel_service,
        authority_validator=RDBScheduledTaskAuthorityValidator(),
    )


@router.get("/workspaces/{handle}/agents/{agent_id}/scheduled-tasks")
async def list_scheduled_tasks(
    member: Annotated[WorkspaceMember, Depends(get_workspace_member)],
    service: Annotated[
        ScheduledTaskManagementService,
        Depends(get_scheduled_task_management_service),
    ],
    *,
    agent_id: str,
    session_id: Annotated[str | None, Query(min_length=32, max_length=32)] = None,
) -> ScheduledTaskListResponse:
    """List every Task in one selected or all authorized Agent Sessions."""
    try:
        tasks = await service.list_tasks(
            workspace_id=member.workspace_id,
            agent_id=agent_id,
            user_id=member.user_id,
            session_id=session_id,
        )
    except ScheduledTaskManagementUnavailable as error:
        _raise_unavailable(error)
    return ScheduledTaskListResponse(
        items=[ScheduledTaskResponse.convert_from(task) for task in tasks]
    )


@router.post(
    "/workspaces/{handle}/agents/{agent_id}/scheduled-tasks",
    status_code=status.HTTP_201_CREATED,
)
async def create_scheduled_task(
    member: Annotated[WorkspaceMember, Depends(get_workspace_member)],
    service: Annotated[
        ScheduledTaskManagementService,
        Depends(get_scheduled_task_management_service),
    ],
    request_body: ScheduledTaskCreateRequest,
    *,
    agent_id: str,
) -> ScheduledTaskResponse:
    """Create a Task for one existing authorized Session."""
    try:
        task = await service.create(
            workspace_id=member.workspace_id,
            agent_id=agent_id,
            user_id=member.user_id,
            session_id=request_body.session_id,
            title=request_body.title,
            objective=request_body.objective,
            at=request_body.at,
            cron=request_body.cron,
            timezone=request_body.timezone,
            channel_id=request_body.channel_id,
        )
    except ScheduledTaskManagementUnavailable as error:
        _raise_unavailable(error)
    return ScheduledTaskResponse.convert_from(task)


@router.get("/workspaces/{handle}/agents/{agent_id}/scheduled-tasks/{task_id}")
async def get_scheduled_task(
    member: Annotated[WorkspaceMember, Depends(get_workspace_member)],
    service: Annotated[
        ScheduledTaskManagementService,
        Depends(get_scheduled_task_management_service),
    ],
    *,
    agent_id: str,
    task_id: str,
) -> ScheduledTaskResponse:
    """Get one exact authorized Scheduled Task."""
    try:
        task = await service.get(
            workspace_id=member.workspace_id,
            agent_id=agent_id,
            user_id=member.user_id,
            task_id=task_id,
        )
    except ScheduledTaskManagementUnavailable as error:
        _raise_unavailable(error)
    return ScheduledTaskResponse.convert_from(task)


@router.put("/workspaces/{handle}/agents/{agent_id}/scheduled-tasks/{task_id}")
async def replace_scheduled_task(
    member: Annotated[WorkspaceMember, Depends(get_workspace_member)],
    service: Annotated[
        ScheduledTaskManagementService,
        Depends(get_scheduled_task_management_service),
    ],
    request_body: ScheduledTaskReplaceRequest,
    *,
    agent_id: str,
    task_id: str,
) -> ScheduledTaskResponse:
    """Replace editable fields that govern future work."""
    try:
        task = await service.replace(
            workspace_id=member.workspace_id,
            agent_id=agent_id,
            user_id=member.user_id,
            task_id=task_id,
            title=request_body.title,
            objective=request_body.objective,
            at=request_body.at,
            cron=request_body.cron,
            timezone=request_body.timezone,
            channel_id=request_body.channel_id,
        )
    except ScheduledTaskManagementUnavailable as error:
        _raise_unavailable(error)
    return ScheduledTaskResponse.convert_from(task)


@router.delete(
    "/workspaces/{handle}/agents/{agent_id}/scheduled-tasks/{task_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_scheduled_task(
    member: Annotated[WorkspaceMember, Depends(get_workspace_member)],
    service: Annotated[
        ScheduledTaskManagementService,
        Depends(get_scheduled_task_management_service),
    ],
    *,
    agent_id: str,
    task_id: str,
) -> Response:
    """Permanently delete one exact authorized Scheduled Task."""
    try:
        await service.delete(
            workspace_id=member.workspace_id,
            agent_id=agent_id,
            user_id=member.user_id,
            task_id=task_id,
        )
    except ScheduledTaskManagementUnavailable as error:
        _raise_unavailable(error)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get(
    "/workspaces/{handle}/agents/{agent_id}/scheduled-tasks/{task_id}/cycle",
)
async def get_scheduled_task_cycle(
    member: Annotated[WorkspaceMember, Depends(get_workspace_member)],
    service: Annotated[
        ScheduledTaskManagementService,
        Depends(get_scheduled_task_management_service),
    ],
    *,
    agent_id: str,
    task_id: str,
) -> ScheduledTaskCurrentCycleEnvelope:
    """Read the sanitized current-cycle projection."""
    try:
        cycle = await service.get_current_cycle(
            workspace_id=member.workspace_id,
            agent_id=agent_id,
            user_id=member.user_id,
            task_id=task_id,
        )
    except ScheduledTaskManagementUnavailable as error:
        _raise_unavailable(error)
    return ScheduledTaskCurrentCycleEnvelope(
        current_cycle=(
            None
            if cycle is None
            else ScheduledTaskCurrentCycleResponse.convert_from(cycle)
        )
    )


def _raise_unavailable(error: ScheduledTaskManagementUnavailable) -> NoReturn:
    if error.code == "not_found":
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": error.code},
        ) from None
    if error.code == "conflict":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"code": error.code},
        ) from None
    raise HTTPException(
        status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
        detail={"code": error.code},
    ) from None


def mount(mounter: RouteMounter) -> None:
    """Mount Scheduled Task v1 Public API routes."""
    mounter(
        router,
        prefix="/scheduled-task/v1",
        tag="Scheduled Task v1",
        description=dedent(
            """
            Scheduled Task API (Public)

            Manage future Scheduled Task definitions and read sanitized current
            occurrence progress for authorized Agent Sessions.
            """
        ),
    )
