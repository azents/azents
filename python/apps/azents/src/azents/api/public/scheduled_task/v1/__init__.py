"""Scheduled Task v1 Public API."""

from textwrap import dedent
from typing import Annotated, NoReturn

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status

from azents.core.auth.deps import WorkspaceMember, get_workspace_member
from azents.core.scheduled_task_management import ScheduledTaskManagementUnavailable
from azents.services.scheduled_task.management import (
    ScheduledTaskManagementService,
    get_scheduled_task_management_service,
)
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
