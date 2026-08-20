"""User-authorized Scheduled Task management service."""

import dataclasses
import datetime
from typing import Literal

from sqlalchemy.ext.asyncio import AsyncSession

from azents.core.enums import (
    AgentLifecycleStatus,
    AgentSessionKind,
    AgentSessionProductMode,
    AgentSessionStatus,
    ExternalChannelConversationLocation,
    ExternalChannelProvider,
    ScheduledTaskScheduleType,
)
from azents.rdb.session import SessionManager
from azents.repos.agent import AgentRepository
from azents.repos.agent_session.data import AgentSession
from azents.repos.agent_session.repository import AgentSessionRepository
from azents.repos.external_channel.management import (
    ExternalChannelManagementRepository,
)
from azents.repos.external_channel.management_data import ManagedBinding
from azents.repos.external_channel.repository import ExternalChannelRepository
from azents.repos.mailbox import MailboxRepository
from azents.repos.scheduled_task.data import ScheduledTask
from azents.repos.scheduled_task.repository import ScheduledTaskRepository
from azents.repos.scheduled_task.schedule import InvalidScheduledTaskSchedule
from azents.repos.scheduled_task_cycle import ScheduledTaskCycleRepository
from azents.repos.scheduled_task_cycle.data import ScheduledTaskCycleState
from azents.services.scheduled_task.channel import ScheduledTaskChannelService
from azents.services.scheduled_task.service import (
    ScheduledTaskAuthorityValidator,
    ScheduledTaskService,
)

ScheduledTaskExecutionState = Literal[
    "idle",
    "admitted",
    "running",
    "running_with_pending",
]


class ScheduledTaskManagementUnavailable(ValueError):
    """Stable fail-closed management error."""

    def __init__(
        self,
        code: Literal["not_found", "invalid_schedule", "conflict"],
    ) -> None:
        super().__init__(code)
        self.code = code


@dataclasses.dataclass(frozen=True)
class ScheduledTaskSessionProjection:
    """Canonical Session navigation identity for one Task."""

    id: str
    handle: str
    title: str | None


@dataclasses.dataclass(frozen=True)
class ScheduledTaskTargetProjection:
    """Opaque current External Channel target presentation."""

    channel_id: str
    provider: ExternalChannelProvider
    location: ExternalChannelConversationLocation
    label: str


@dataclasses.dataclass(frozen=True)
class ScheduledTaskManagementProjection:
    """Sanitized Task definition and derived management state."""

    id: str
    title: str
    objective: str
    schedule_type: ScheduledTaskScheduleType
    scheduled_at: datetime.datetime | None
    cron_expression: str | None
    timezone: str | None
    next_eligible_at: datetime.datetime
    execution_state: ScheduledTaskExecutionState
    session: ScheduledTaskSessionProjection
    target: ScheduledTaskTargetProjection | None
    created_at: datetime.datetime
    updated_at: datetime.datetime


@dataclasses.dataclass(frozen=True)
class ScheduledTaskCurrentCycleProjection:
    """Sanitized current occurrence state without internal identities."""

    phase: Literal["admitted", "started"]
    scheduled_for: datetime.datetime
    started_at: datetime.datetime | None
    progress_title: str | None
    ordered_tasks: tuple[str, ...]


class ScheduledTaskManagementService:
    """Manage Scheduled Tasks for one authenticated Workspace member."""

    def __init__(
        self,
        *,
        session_manager: SessionManager[AsyncSession],
        agent_repository: AgentRepository,
        agent_session_repository: AgentSessionRepository,
        task_repository: ScheduledTaskRepository,
        cycle_repository: ScheduledTaskCycleRepository,
        mailbox_repository: MailboxRepository,
        external_channel_repository: ExternalChannelRepository,
        external_channel_management_repository: ExternalChannelManagementRepository,
        channel_service: ScheduledTaskChannelService,
        authority_validator: ScheduledTaskAuthorityValidator,
    ) -> None:
        self.session_manager = session_manager
        self.agent_repository = agent_repository
        self.agent_session_repository = agent_session_repository
        self.task_repository = task_repository
        self.cycle_repository = cycle_repository
        self.mailbox_repository = mailbox_repository
        self.external_channel_repository = external_channel_repository
        self.external_channel_management_repository = (
            external_channel_management_repository
        )
        self.channel_service = channel_service
        self.authority_validator = authority_validator

    def _task_service(self) -> ScheduledTaskService:
        return ScheduledTaskService(
            repository=self.task_repository,
            cycle_repository=self.cycle_repository,
            mailbox_repository=self.mailbox_repository,
            authority_validator=self.authority_validator,
        )

    async def list_tasks(
        self,
        *,
        workspace_id: str,
        agent_id: str,
        user_id: str,
        session_id: str | None,
    ) -> list[ScheduledTaskManagementProjection]:
        """List Tasks in one selected Session or every authorized Agent Session."""
        async with self.session_manager() as session:
            await self._require_agent(
                session,
                workspace_id=workspace_id,
                agent_id=agent_id,
            )
            if session_id is not None:
                sessions = [
                    await self._require_session(
                        session,
                        workspace_id=workspace_id,
                        agent_id=agent_id,
                        user_id=user_id,
                        session_id=session_id,
                    )
                ]
            else:
                team_sessions = (
                    await self.agent_session_repository.list_active_by_agent_id(
                        session,
                        agent_id,
                    )
                )
                user_sessions = await (
                    self.agent_session_repository.list_active_user_by_agent_and_user(
                        session,
                        agent_id=agent_id,
                        associated_user_id=user_id,
                    )
                )
                sessions = [*team_sessions, *user_sessions]
            projections: list[ScheduledTaskManagementProjection] = []
            for agent_session in sessions:
                tasks = await self.task_repository.list_by_session_id(
                    session,
                    agent_session.id,
                )
                bindings = await self._binding_map(
                    session,
                    workspace_id=workspace_id,
                    agent_id=agent_id,
                    session_id=agent_session.id,
                )
                for task in tasks:
                    projections.append(
                        await self._project_task(
                            session,
                            task=task,
                            agent_session=agent_session,
                            bindings=bindings,
                        )
                    )
            return projections

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
        """Create one Task for an existing authorized root Session."""
        async with self.session_manager() as session:
            agent_session = await self._lock_and_require_session(
                session,
                workspace_id=workspace_id,
                agent_id=agent_id,
                user_id=user_id,
                session_id=session_id,
            )
            await self._lock_bindings(session, binding_ids=[channel_id])
            await self._require_binding_authorities(
                session,
                workspace_id=workspace_id,
                agent_id=agent_id,
                session_id=session_id,
                binding_ids=[channel_id],
            )
            try:
                task = await self._task_service().create(
                    session,
                    workspace_id=workspace_id,
                    agent_id=agent_id,
                    session_id=session_id,
                    title=title,
                    objective=objective,
                    at=at,
                    cron=cron,
                    timezone=timezone,
                    binding_id=channel_id,
                )
            except InvalidScheduledTaskSchedule:
                raise ScheduledTaskManagementUnavailable("invalid_schedule") from None
            bindings = await self._binding_map(
                session,
                workspace_id=workspace_id,
                agent_id=agent_id,
                session_id=session_id,
            )
            projection = await self._project_task(
                session,
                task=task,
                agent_session=agent_session,
                bindings=bindings,
            )
            await session.commit()
        await self.channel_service.execute_registration(task)
        return projection

    async def get(
        self,
        *,
        workspace_id: str,
        agent_id: str,
        user_id: str,
        task_id: str,
    ) -> ScheduledTaskManagementProjection:
        """Get one exact authorized Task."""
        async with self.session_manager() as session:
            task, agent_session = await self._require_task(
                session,
                workspace_id=workspace_id,
                agent_id=agent_id,
                user_id=user_id,
                task_id=task_id,
            )
            bindings = await self._binding_map(
                session,
                workspace_id=workspace_id,
                agent_id=agent_id,
                session_id=agent_session.id,
            )
            return await self._project_task(
                session,
                task=task,
                agent_session=agent_session,
                bindings=bindings,
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
        """Replace future Task definition fields under deterministic Binding locks."""
        async with self.session_manager() as session:
            candidate, agent_session = await self._lock_and_require_task(
                session,
                workspace_id=workspace_id,
                agent_id=agent_id,
                user_id=user_id,
                task_id=task_id,
            )
            await self._lock_bindings(
                session,
                binding_ids=[candidate.binding_id, channel_id],
            )
            await self._require_binding_authorities(
                session,
                workspace_id=workspace_id,
                agent_id=agent_id,
                session_id=agent_session.id,
                binding_ids=[candidate.binding_id, channel_id],
            )
            service = self._task_service()
            target = await service.lock_management_mutation_target(
                session,
                task_id=task_id,
                expected_binding_id=candidate.binding_id,
            )
            if target is None or target.task.session_id != agent_session.id:
                raise ScheduledTaskManagementUnavailable("not_found")
            try:
                replaced = await service.replace_locked_provider_target(
                    session,
                    target=target,
                    expected_binding_id=candidate.binding_id,
                    title=title,
                    objective=objective,
                    at=at,
                    cron=cron,
                    timezone=timezone,
                    binding_id=channel_id,
                )
            except InvalidScheduledTaskSchedule as error:
                code: Literal["invalid_schedule", "conflict"] = (
                    "conflict"
                    if "active cycle cannot be edited" in str(error)
                    else "invalid_schedule"
                )
                raise ScheduledTaskManagementUnavailable(code) from None
            if replaced is None:
                raise ScheduledTaskManagementUnavailable("not_found")
            bindings = await self._binding_map(
                session,
                workspace_id=workspace_id,
                agent_id=agent_id,
                session_id=agent_session.id,
            )
            projection = await self._project_task(
                session,
                task=replaced,
                agent_session=agent_session,
                bindings=bindings,
            )
            await session.commit()
            return projection

    async def delete(
        self,
        *,
        workspace_id: str,
        agent_id: str,
        user_id: str,
        task_id: str,
    ) -> None:
        """Permanently delete one exact authorized Task."""
        async with self.session_manager() as session:
            candidate, agent_session = await self._lock_and_require_task(
                session,
                workspace_id=workspace_id,
                agent_id=agent_id,
                user_id=user_id,
                task_id=task_id,
            )
            await self._lock_bindings(
                session,
                binding_ids=[candidate.binding_id],
            )
            await self._require_binding_authorities(
                session,
                workspace_id=workspace_id,
                agent_id=agent_id,
                session_id=agent_session.id,
                binding_ids=[candidate.binding_id],
            )
            service = self._task_service()
            target = await service.lock_management_mutation_target(
                session,
                task_id=task_id,
                expected_binding_id=candidate.binding_id,
            )
            if target is None or target.task.session_id != agent_session.id:
                raise ScheduledTaskManagementUnavailable("not_found")
            try:
                deleted = await service.delete_locked_provider_target(
                    session,
                    target=target,
                    expected_binding_id=candidate.binding_id,
                )
            except InvalidScheduledTaskSchedule:
                raise ScheduledTaskManagementUnavailable("invalid_schedule") from None
            if not deleted:
                raise ScheduledTaskManagementUnavailable("not_found")
            await session.commit()

    async def get_current_cycle(
        self,
        *,
        workspace_id: str,
        agent_id: str,
        user_id: str,
        task_id: str,
    ) -> ScheduledTaskCurrentCycleProjection | None:
        """Read the sanitized current-cycle projection for one exact Task."""
        async with self.session_manager() as session:
            task, _ = await self._require_task(
                session,
                workspace_id=workspace_id,
                agent_id=agent_id,
                user_id=user_id,
                task_id=task_id,
            )
            cycle = await self._cycle(session, task)
            if cycle is None:
                return None
            return _current_cycle_projection(cycle)

    async def _require_task(
        self,
        session: AsyncSession,
        *,
        workspace_id: str,
        agent_id: str,
        user_id: str,
        task_id: str,
    ) -> tuple[ScheduledTask, AgentSession]:
        task = await self.task_repository.get_by_id(session, task_id)
        if (
            task is None
            or task.workspace_id != workspace_id
            or task.agent_id != agent_id
        ):
            raise ScheduledTaskManagementUnavailable("not_found")
        agent_session = await self._require_session(
            session,
            workspace_id=workspace_id,
            agent_id=agent_id,
            user_id=user_id,
            session_id=task.session_id,
        )
        return task, agent_session

    async def _require_agent(
        self,
        session: AsyncSession,
        *,
        workspace_id: str,
        agent_id: str,
    ) -> None:
        agent = await self.agent_repository.get_by_id(session, agent_id)
        if (
            agent is None
            or agent.workspace_id != workspace_id
            or agent.lifecycle_status is not AgentLifecycleStatus.ACTIVE
            or not agent.enabled
        ):
            raise ScheduledTaskManagementUnavailable("not_found")

    async def _lock_and_require_task(
        self,
        session: AsyncSession,
        *,
        workspace_id: str,
        agent_id: str,
        user_id: str,
        task_id: str,
    ) -> tuple[ScheduledTask, AgentSession]:
        """Read one exact Task, then lock and revalidate its current authority."""
        task = await self.task_repository.get_by_id(session, task_id)
        if (
            task is None
            or task.workspace_id != workspace_id
            or task.agent_id != agent_id
        ):
            raise ScheduledTaskManagementUnavailable("not_found")
        agent_session = await self._lock_and_require_session(
            session,
            workspace_id=workspace_id,
            agent_id=agent_id,
            user_id=user_id,
            session_id=task.session_id,
        )
        return task, agent_session

    async def _lock_and_require_session(
        self,
        session: AsyncSession,
        *,
        workspace_id: str,
        agent_id: str,
        user_id: str,
        session_id: str,
    ) -> AgentSession:
        """Lock and revalidate one writable root Session and its Agent."""
        agent_session = await self.agent_session_repository.lock_by_id(
            session,
            session_id,
        )
        if not _authorized_session(
            agent_session,
            workspace_id=workspace_id,
            agent_id=agent_id,
            user_id=user_id,
        ):
            raise ScheduledTaskManagementUnavailable("not_found")
        agent = await self.agent_repository.lock_by_id(session, agent_id)
        if (
            agent is None
            or agent.workspace_id != workspace_id
            or agent.lifecycle_status is not AgentLifecycleStatus.ACTIVE
            or not agent.enabled
        ):
            raise ScheduledTaskManagementUnavailable("not_found")
        assert agent_session is not None
        return agent_session

    async def _require_session(
        self,
        session: AsyncSession,
        *,
        workspace_id: str,
        agent_id: str,
        user_id: str,
        session_id: str,
    ) -> AgentSession:
        await self._require_agent(
            session,
            workspace_id=workspace_id,
            agent_id=agent_id,
        )
        agent_session = await self.agent_session_repository.get_by_id(
            session,
            session_id,
        )
        if not _authorized_session(
            agent_session,
            workspace_id=workspace_id,
            agent_id=agent_id,
            user_id=user_id,
        ):
            raise ScheduledTaskManagementUnavailable("not_found")
        assert agent_session is not None
        return agent_session

    async def _project_task(
        self,
        session: AsyncSession,
        *,
        task: ScheduledTask,
        agent_session: AgentSession,
        bindings: dict[str, ManagedBinding],
    ) -> ScheduledTaskManagementProjection:
        cycle = await self._cycle(session, task)
        execution_state: ScheduledTaskExecutionState = "idle"
        if cycle is not None:
            if cycle.phase == "admitted":
                execution_state = "admitted"
            elif task.pending_scheduled_for is not None:
                execution_state = "running_with_pending"
            else:
                execution_state = "running"
        target: ScheduledTaskTargetProjection | None = None
        if task.binding_id is not None:
            binding = bindings.get(task.binding_id)
            if binding is not None and binding.disconnected_at is None:
                target = ScheduledTaskTargetProjection(
                    channel_id=binding.id,
                    provider=binding.provider,
                    location=binding.conversation_location,
                    label=binding.resource_label,
                )
        return ScheduledTaskManagementProjection(
            id=task.id,
            title=task.title,
            objective=task.objective,
            schedule_type=task.schedule_type,
            scheduled_at=task.scheduled_at,
            cron_expression=task.cron_expression,
            timezone=task.timezone,
            next_eligible_at=task.next_eligible_at,
            execution_state=execution_state,
            session=ScheduledTaskSessionProjection(
                id=agent_session.id,
                handle=agent_session.handle,
                title=agent_session.title,
            ),
            target=target,
            created_at=task.created_at,
            updated_at=task.updated_at,
        )

    async def _cycle(
        self,
        session: AsyncSession,
        task: ScheduledTask,
    ) -> ScheduledTaskCycleState | None:
        if task.active_cycle_id is None:
            return None
        record = await self.cycle_repository.get(
            session,
            agent_id=task.agent_id,
            session_id=task.session_id,
            cycle_id=task.active_cycle_id,
        )
        if record is None:
            raise RuntimeError("Scheduled Task active cycle state is missing.")
        return record.state

    async def _binding_map(
        self,
        session: AsyncSession,
        *,
        workspace_id: str,
        agent_id: str,
        session_id: str,
    ) -> dict[str, ManagedBinding]:
        bindings = await self.external_channel_management_repository.list_bindings(
            session,
            workspace_id=workspace_id,
            agent_id=agent_id,
            agent_session_id=session_id,
        )
        return {binding.id: binding for binding in bindings}

    async def _require_binding_authorities(
        self,
        session: AsyncSession,
        *,
        workspace_id: str,
        agent_id: str,
        session_id: str,
        binding_ids: list[str | None],
    ) -> None:
        """Revalidate every current/requested Binding after deterministic locks."""
        for binding_id in sorted(
            binding_id for binding_id in set(binding_ids) if binding_id is not None
        ):
            try:
                await self.authority_validator.validate_target(
                    session,
                    workspace_id=workspace_id,
                    agent_id=agent_id,
                    session_id=session_id,
                    binding_id=binding_id,
                )
            except InvalidScheduledTaskSchedule:
                raise ScheduledTaskManagementUnavailable("not_found") from None

    async def _lock_bindings(
        self,
        session: AsyncSession,
        *,
        binding_ids: list[str | None],
    ) -> None:
        for binding_id in sorted(
            binding_id for binding_id in set(binding_ids) if binding_id is not None
        ):
            await self.external_channel_repository.lock_binding(
                session,
                binding_id=binding_id,
            )


def _authorized_session(
    agent_session: AgentSession | None,
    *,
    workspace_id: str,
    agent_id: str,
    user_id: str,
) -> bool:
    return (
        agent_session is not None
        and agent_session.workspace_id == workspace_id
        and agent_session.agent_id == agent_id
        and agent_session.session_kind is AgentSessionKind.ROOT
        and agent_session.status is AgentSessionStatus.ACTIVE
        and agent_session.product_mode
        in {
            AgentSessionProductMode.TEAM,
            AgentSessionProductMode.USER,
        }
        and (
            agent_session.product_mode is not AgentSessionProductMode.USER
            or agent_session.associated_user_id == user_id
        )
    )


def _current_cycle_projection(
    cycle: ScheduledTaskCycleState,
) -> ScheduledTaskCurrentCycleProjection:
    return ScheduledTaskCurrentCycleProjection(
        phase=cycle.phase,
        scheduled_for=cycle.scheduled_for,
        started_at=cycle.started_at,
        progress_title=cycle.progress_title,
        ordered_tasks=tuple(cycle.ordered_tasks),
    )


__all__ = [
    "ScheduledTaskCurrentCycleProjection",
    "ScheduledTaskManagementProjection",
    "ScheduledTaskManagementService",
    "ScheduledTaskManagementUnavailable",
    "ScheduledTaskSessionProjection",
    "ScheduledTaskTargetProjection",
]
