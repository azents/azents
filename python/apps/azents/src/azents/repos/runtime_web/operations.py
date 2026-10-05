"""Completed database-only Runtime Web authorization and service operations."""

import datetime
from collections.abc import Awaitable, Callable
from typing import Annotated

import sqlalchemy as sa
from azcommon.result import Failure, Result, Success
from fastapi import Depends

from azents.core.enums import (
    AgentLifecycleStatus,
    AgentRuntimeCapability,
    AgentType,
    WorkspaceUserRole,
)
from azents.rdb.deps import get_session_manager
from azents.rdb.models.runtime_web import RuntimeWebActorKind
from azents.rdb.session import SessionManager
from azents.rdb.session_capabilities import ReadSession, WriteSession
from azents.repos.agent import AgentRepository
from azents.repos.agent_admin import AgentAdminRepository
from azents.repos.runtime_web.data import (
    RuntimeWebConfiguration,
    RuntimeWebMutationResult,
    RuntimeWebOperationIdentity,
    RuntimeWebServiceRecord,
)
from azents.repos.runtime_web.operation_data import (
    RuntimeWebCommandIdentity,
    RuntimeWebObservedPage,
    RuntimeWebObservedService,
    RuntimeWebOperationCode,
    RuntimeWebOperationError,
)
from azents.repos.runtime_web.repository import (
    RuntimeWebRepository,
    RuntimeWebRepositoryConflict,
    RuntimeWebRepositoryQuotaExceeded,
    get_runtime_web_repository,
)
from azents.repos.workspace_user import WorkspaceUserRepository

_SERVICE_LIMIT = 16
_ACTIVE_AGENT_LIMIT = 16


class RuntimeWebOperationsRepository:
    """Authorize and coordinate durable Runtime Web service state."""

    def __init__(
        self,
        *,
        session_manager: SessionManager[WriteSession],
        repository: RuntimeWebRepository,
        agent_repository: AgentRepository,
        agent_admin_repository: AgentAdminRepository,
        workspace_user_repository: WorkspaceUserRepository,
    ) -> None:
        self.session_manager = session_manager
        self.repository = repository
        self.agent_repository = agent_repository
        self.agent_admin_repository = agent_admin_repository
        self.workspace_user_repository = workspace_user_repository

    async def create_service(
        self,
        *,
        workspace_id: str,
        agent_id: str,
        user_id: str,
        workspace_user_id: str,
        role: WorkspaceUserRole,
        port: int,
        label: str | None,
        selected_duration_seconds: int,
        turn_on: bool,
        operation: RuntimeWebCommandIdentity,
    ) -> Result[RuntimeWebObservedService, RuntimeWebOperationError]:
        """Create one user-managed service."""
        if (
            operation.actor_kind is not RuntimeWebActorKind.USER
            or operation.actor_id != user_id
        ):
            return Failure(
                RuntimeWebOperationError(
                    RuntimeWebOperationCode.ACCESS_DENIED, scope=None
                )
            )
        async with self.session_manager() as session:
            access = await self._authorize_user(
                session,
                workspace_id=workspace_id,
                agent_id=agent_id,
                user_id=user_id,
                workspace_user_id=workspace_user_id,
                role=role,
            )
            if access is not None:
                return Failure(access)
            configuration = await self._configuration(session)
            if isinstance(configuration, RuntimeWebOperationError):
                return Failure(configuration)
            try:
                result = await self.repository.create_service(
                    session,
                    workspace_id=workspace_id,
                    agent_id=agent_id,
                    port=port,
                    label=label,
                    selected_duration_seconds=selected_duration_seconds,
                    turn_on=turn_on,
                    operation=_receipt_identity(operation),
                    service_limit=_SERVICE_LIMIT,
                    active_agent_limit=_ACTIVE_AGENT_LIMIT,
                )
            except RuntimeWebRepositoryQuotaExceeded as error:
                return Failure(
                    RuntimeWebOperationError(
                        RuntimeWebOperationCode.QUOTA_EXCEEDED, scope=error.scope
                    )
                )
            except RuntimeWebRepositoryConflict:
                return Failure(
                    RuntimeWebOperationError(
                        RuntimeWebOperationCode.CONFLICT, scope=None
                    )
                )
            return Success(await self._projection(session, result.service))

    async def request_service(
        self,
        *,
        workspace_id: str,
        agent_id: str,
        port: int,
        label: str | None,
        operation: RuntimeWebCommandIdentity,
    ) -> Result[RuntimeWebObservedService, RuntimeWebOperationError]:
        """Create a missing Off service or return the existing row unchanged."""
        async with self.session_manager() as session:
            access = await self._authorize_agent(
                session,
                workspace_id=workspace_id,
                agent_id=agent_id,
                operation=operation,
            )
            if access is not None:
                return Failure(access)
            configuration = await self._configuration(session)
            if isinstance(configuration, RuntimeWebOperationError):
                return Failure(configuration)
            try:
                result = await self.repository.request_service(
                    session,
                    workspace_id=workspace_id,
                    agent_id=agent_id,
                    port=port,
                    label=label,
                    operation=_receipt_identity(operation),
                    service_limit=_SERVICE_LIMIT,
                )
            except RuntimeWebRepositoryQuotaExceeded as error:
                return Failure(
                    RuntimeWebOperationError(
                        RuntimeWebOperationCode.QUOTA_EXCEEDED, scope=error.scope
                    )
                )
            except RuntimeWebRepositoryConflict:
                return Failure(
                    RuntimeWebOperationError(
                        RuntimeWebOperationCode.CONFLICT, scope=None
                    )
                )
            return Success(await self._projection(session, result.service))

    async def update_service(
        self,
        *,
        workspace_id: str,
        agent_id: str,
        service_id: str,
        user_id: str,
        workspace_user_id: str,
        role: WorkspaceUserRole,
        expected_revision: int,
        label_present: bool,
        label: str | None,
        selected_duration_seconds: int | None,
        operation: RuntimeWebCommandIdentity,
    ) -> Result[RuntimeWebObservedService, RuntimeWebOperationError]:
        """Update service label or selected duration."""
        return await self._user_mutation(
            workspace_id=workspace_id,
            agent_id=agent_id,
            service_id=service_id,
            user_id=user_id,
            workspace_user_id=workspace_user_id,
            role=role,
            operation=operation,
            mutate=lambda session: self.repository.update_service(
                session,
                service_id=service_id,
                expected_revision=expected_revision,
                label_present=label_present,
                label=label,
                selected_duration_seconds=selected_duration_seconds,
                operation=_receipt_identity(operation),
            ),
        )

    async def turn_on(
        self,
        *,
        workspace_id: str,
        agent_id: str,
        service_id: str,
        user_id: str,
        workspace_user_id: str,
        role: WorkspaceUserRole,
        expected_revision: int,
        selected_duration_seconds: int | None,
        operation: RuntimeWebCommandIdentity,
    ) -> Result[RuntimeWebObservedService, RuntimeWebOperationError]:
        """Turn an Off service On."""
        return await self._user_mutation(
            workspace_id=workspace_id,
            agent_id=agent_id,
            service_id=service_id,
            user_id=user_id,
            workspace_user_id=workspace_user_id,
            role=role,
            operation=operation,
            mutate=lambda session: self.repository.turn_on(
                session,
                service_id=service_id,
                expected_revision=expected_revision,
                selected_duration_seconds=selected_duration_seconds,
                operation=_receipt_identity(operation),
                active_agent_limit=_ACTIVE_AGENT_LIMIT,
            ),
        )

    async def turn_off(
        self,
        *,
        workspace_id: str,
        agent_id: str,
        service_id: str,
        user_id: str,
        workspace_user_id: str,
        role: WorkspaceUserRole,
        expected_revision: int,
        operation: RuntimeWebCommandIdentity,
    ) -> Result[RuntimeWebObservedService, RuntimeWebOperationError]:
        """Turn one exact service Off."""
        return await self._user_mutation(
            workspace_id=workspace_id,
            agent_id=agent_id,
            service_id=service_id,
            user_id=user_id,
            workspace_user_id=workspace_user_id,
            role=role,
            operation=operation,
            mutate=lambda session: self.repository.turn_off(
                session,
                service_id=service_id,
                expected_revision=expected_revision,
                operation=_receipt_identity(operation),
            ),
        )

    async def reset_expiration(
        self,
        *,
        workspace_id: str,
        agent_id: str,
        service_id: str,
        user_id: str,
        workspace_user_id: str,
        role: WorkspaceUserRole,
        expected_revision: int,
        operation: RuntimeWebCommandIdentity,
    ) -> Result[RuntimeWebObservedService, RuntimeWebOperationError]:
        """Restart one current service exposure window."""
        return await self._user_mutation(
            workspace_id=workspace_id,
            agent_id=agent_id,
            service_id=service_id,
            user_id=user_id,
            workspace_user_id=workspace_user_id,
            role=role,
            operation=operation,
            mutate=lambda session: self.repository.reset_expiration(
                session,
                service_id=service_id,
                expected_revision=expected_revision,
                operation=_receipt_identity(operation),
            ),
        )

    async def delete_service(
        self,
        *,
        workspace_id: str,
        agent_id: str,
        service_id: str,
        user_id: str,
        workspace_user_id: str,
        role: WorkspaceUserRole,
        expected_revision: int,
        operation: RuntimeWebCommandIdentity,
    ) -> Result[bool, RuntimeWebOperationError]:
        """Delete one exact service after Agent authorization."""
        if (
            operation.actor_kind is not RuntimeWebActorKind.USER
            or operation.actor_id != user_id
        ):
            return Failure(
                RuntimeWebOperationError(
                    RuntimeWebOperationCode.ACCESS_DENIED, scope=None
                )
            )
        async with self.session_manager() as session:
            access = await self._authorize_user(
                session,
                workspace_id=workspace_id,
                agent_id=agent_id,
                user_id=user_id,
                workspace_user_id=workspace_user_id,
                role=role,
            )
            if access is not None:
                return Failure(access)
            configuration = await self._configuration(session)
            if isinstance(configuration, RuntimeWebOperationError):
                return Failure(configuration)
            try:
                deleted = await self.repository.delete_service(
                    session,
                    agent_id=agent_id,
                    service_id=service_id,
                    expected_revision=expected_revision,
                    operation=_receipt_identity(operation),
                )
            except RuntimeWebRepositoryConflict:
                return Failure(
                    RuntimeWebOperationError(
                        RuntimeWebOperationCode.CONFLICT, scope=None
                    )
                )
            return Success(deleted)

    async def close_service(
        self,
        *,
        workspace_id: str,
        agent_id: str,
        service_id: str,
        operation: RuntimeWebCommandIdentity,
    ) -> Result[RuntimeWebObservedService, RuntimeWebOperationError]:
        """Idempotently turn one exact service Off for an Agent caller."""
        async with self.session_manager() as session:
            access = await self._authorize_agent(
                session,
                workspace_id=workspace_id,
                agent_id=agent_id,
                operation=operation,
            )
            if access is not None:
                return Failure(access)
            record = await self.repository.get_service_by_id(session, service_id)
            if record is None or record.agent_id != agent_id:
                return Failure(
                    RuntimeWebOperationError(
                        RuntimeWebOperationCode.NOT_FOUND, scope=None
                    )
                )
            configuration = await self._configuration(session)
            if isinstance(configuration, RuntimeWebOperationError):
                return Failure(configuration)
            try:
                result = await self.repository.close_service(
                    session,
                    service_id=service_id,
                    operation=_receipt_identity(operation),
                )
            except RuntimeWebRepositoryConflict:
                return Failure(
                    RuntimeWebOperationError(
                        RuntimeWebOperationCode.CONFLICT, scope=None
                    )
                )
            return Success(await self._projection(session, result.service))

    async def get_service(
        self,
        *,
        workspace_id: str,
        agent_id: str,
        service_id: str,
        user_id: str,
        workspace_user_id: str,
        role: WorkspaceUserRole,
    ) -> Result[RuntimeWebObservedService, RuntimeWebOperationError]:
        """Get one current service through an Agent-nested route."""
        async with self.session_manager() as session:
            access = await self._authorize_user(
                session,
                workspace_id=workspace_id,
                agent_id=agent_id,
                user_id=user_id,
                workspace_user_id=workspace_user_id,
                role=role,
            )
            if access is not None:
                return Failure(access)
            record = await self.repository.get_service_by_id(session, service_id)
            if record is None or record.agent_id != agent_id:
                return Failure(
                    RuntimeWebOperationError(
                        RuntimeWebOperationCode.NOT_FOUND, scope=None
                    )
                )
            return Success(await self._projection(session, record))

    async def get_service_by_id_for_user(
        self,
        *,
        service_id: str,
        user_id: str,
    ) -> Result[RuntimeWebObservedService, RuntimeWebOperationError]:
        """Get one authorized service by opaque ID for trusted Main Web."""
        async with self.session_manager() as session:
            record = await self.repository.get_service_by_id(session, service_id)
            if record is None:
                return Failure(
                    RuntimeWebOperationError(
                        RuntimeWebOperationCode.NOT_FOUND, scope=None
                    )
                )
            member = await self.workspace_user_repository.get_by_workspace_and_user(
                session,
                record.workspace_id,
                user_id,
            )
            if member is None:
                return Failure(
                    RuntimeWebOperationError(
                        RuntimeWebOperationCode.NOT_FOUND, scope=None
                    )
                )
            access = await self._authorize_user(
                session,
                workspace_id=record.workspace_id,
                agent_id=record.agent_id,
                user_id=user_id,
                workspace_user_id=member.id,
                role=member.role,
            )
            if access is not None:
                return Failure(access)
            return Success(await self._projection(session, record))

    async def turn_on_by_id_for_user(
        self,
        *,
        service_id: str,
        user_id: str,
        expected_revision: int,
        selected_duration_seconds: int,
        operation: RuntimeWebCommandIdentity,
    ) -> Result[RuntimeWebObservedService, RuntimeWebOperationError]:
        """Turn On through the trusted service URL activation surface."""
        async with self.session_manager() as session:
            record = await self.repository.get_service_by_id(session, service_id)
            if record is None:
                return Failure(
                    RuntimeWebOperationError(
                        RuntimeWebOperationCode.NOT_FOUND, scope=None
                    )
                )
            member = await self.workspace_user_repository.get_by_workspace_and_user(
                session,
                record.workspace_id,
                user_id,
            )
            if member is None:
                return Failure(
                    RuntimeWebOperationError(
                        RuntimeWebOperationCode.NOT_FOUND, scope=None
                    )
                )
            return await self._user_mutation_in_session(
                session,
                workspace_id=record.workspace_id,
                agent_id=record.agent_id,
                service_id=record.id,
                user_id=user_id,
                workspace_user_id=member.id,
                role=member.role,
                operation=operation,
                mutate=lambda current_session: self.repository.turn_on(
                    current_session,
                    service_id=record.id,
                    expected_revision=expected_revision,
                    selected_duration_seconds=selected_duration_seconds,
                    operation=_receipt_identity(operation),
                    active_agent_limit=_ACTIVE_AGENT_LIMIT,
                ),
            )

    async def list_services(
        self,
        *,
        workspace_id: str,
        agent_id: str,
        user_id: str | None,
        workspace_user_id: str | None,
        role: WorkspaceUserRole | None,
        offset: int,
        limit: int,
        operation: RuntimeWebCommandIdentity | None,
    ) -> Result[RuntimeWebObservedPage, RuntimeWebOperationError]:
        """List current services for one Agent."""
        async with self.session_manager() as session:
            if user_id is None:
                if operation is None:
                    return Failure(
                        RuntimeWebOperationError(
                            RuntimeWebOperationCode.ACCESS_DENIED, scope=None
                        )
                    )
                access = await self._authorize_agent(
                    session,
                    workspace_id=workspace_id,
                    agent_id=agent_id,
                    operation=operation,
                )
            else:
                if workspace_user_id is None or role is None:
                    return Failure(
                        RuntimeWebOperationError(
                            RuntimeWebOperationCode.ACCESS_DENIED, scope=None
                        )
                    )
                access = await self._authorize_user(
                    session,
                    workspace_id=workspace_id,
                    agent_id=agent_id,
                    user_id=user_id,
                    workspace_user_id=workspace_user_id,
                    role=role,
                )
            if access is not None:
                return Failure(access)
            page = await self.repository.list_services(
                session,
                agent_id=agent_id,
                offset=offset,
                limit=limit,
            )
            return Success(
                RuntimeWebObservedPage(
                    items=[
                        await self._projection(session, record) for record in page.items
                    ],
                    total_count=page.total,
                )
            )

    async def _user_mutation(
        self,
        *,
        workspace_id: str,
        agent_id: str,
        service_id: str,
        user_id: str,
        workspace_user_id: str,
        role: WorkspaceUserRole,
        operation: RuntimeWebCommandIdentity,
        mutate: Callable[[WriteSession], Awaitable[RuntimeWebMutationResult]],
    ) -> Result[RuntimeWebObservedService, RuntimeWebOperationError]:
        if (
            operation.actor_kind is not RuntimeWebActorKind.USER
            or operation.actor_id != user_id
        ):
            return Failure(
                RuntimeWebOperationError(
                    RuntimeWebOperationCode.ACCESS_DENIED, scope=None
                )
            )
        async with self.session_manager() as session:
            return await self._user_mutation_in_session(
                session,
                workspace_id=workspace_id,
                agent_id=agent_id,
                service_id=service_id,
                user_id=user_id,
                workspace_user_id=workspace_user_id,
                role=role,
                operation=operation,
                mutate=mutate,
            )

    async def _user_mutation_in_session(
        self,
        session: WriteSession,
        *,
        workspace_id: str,
        agent_id: str,
        service_id: str,
        user_id: str,
        workspace_user_id: str,
        role: WorkspaceUserRole,
        operation: RuntimeWebCommandIdentity,
        mutate: Callable[[WriteSession], Awaitable[RuntimeWebMutationResult]],
    ) -> Result[RuntimeWebObservedService, RuntimeWebOperationError]:
        if (
            operation.actor_kind is not RuntimeWebActorKind.USER
            or operation.actor_id != user_id
        ):
            return Failure(
                RuntimeWebOperationError(
                    RuntimeWebOperationCode.ACCESS_DENIED, scope=None
                )
            )
        access = await self._authorize_user(
            session,
            workspace_id=workspace_id,
            agent_id=agent_id,
            user_id=user_id,
            workspace_user_id=workspace_user_id,
            role=role,
        )
        if access is not None:
            return Failure(access)
        record = await self.repository.get_service_by_id(session, service_id)
        if record is None or record.agent_id != agent_id:
            return Failure(
                RuntimeWebOperationError(RuntimeWebOperationCode.NOT_FOUND, scope=None)
            )
        configuration = await self._configuration(session)
        if isinstance(configuration, RuntimeWebOperationError):
            return Failure(configuration)
        try:
            result = await mutate(session)
        except RuntimeWebRepositoryQuotaExceeded as error:
            return Failure(
                RuntimeWebOperationError(
                    RuntimeWebOperationCode.QUOTA_EXCEEDED, scope=error.scope
                )
            )
        except RuntimeWebRepositoryConflict:
            return Failure(
                RuntimeWebOperationError(RuntimeWebOperationCode.CONFLICT, scope=None)
            )
        return Success(await self._projection(session, result.service))

    async def _authorize_user(
        self,
        session: ReadSession,
        *,
        workspace_id: str,
        agent_id: str,
        user_id: str,
        workspace_user_id: str,
        role: WorkspaceUserRole,
    ) -> RuntimeWebOperationError | None:
        member = await self.workspace_user_repository.get_by_workspace_and_user(
            session,
            workspace_id,
            user_id,
        )
        if member is None or member.id != workspace_user_id or member.role is not role:
            return RuntimeWebOperationError(
                RuntimeWebOperationCode.ACCESS_DENIED, scope=None
            )
        agent = await self.agent_repository.get_by_id(session, agent_id)
        if (
            agent is None
            or agent.workspace_id != workspace_id
            or agent.lifecycle_status is not AgentLifecycleStatus.ACTIVE
        ):
            return RuntimeWebOperationError(
                RuntimeWebOperationCode.NOT_FOUND, scope=None
            )
        if agent.type is AgentType.PRIVATE and role is not WorkspaceUserRole.OWNER:
            if not await self.agent_admin_repository.is_admin(
                session,
                agent_id,
                workspace_user_id,
            ):
                return RuntimeWebOperationError(
                    RuntimeWebOperationCode.ACCESS_DENIED, scope=None
                )
        if agent.runtime_capability is not AgentRuntimeCapability.MANAGED:
            return RuntimeWebOperationError(
                RuntimeWebOperationCode.CAPABILITY_UNAVAILABLE, scope=None
            )
        return None

    async def _authorize_agent(
        self,
        session: ReadSession,
        *,
        workspace_id: str,
        agent_id: str,
        operation: RuntimeWebCommandIdentity,
    ) -> RuntimeWebOperationError | None:
        if (
            operation.actor_kind is not RuntimeWebActorKind.AGENT
            or operation.actor_id != agent_id
        ):
            return RuntimeWebOperationError(
                RuntimeWebOperationCode.ACCESS_DENIED, scope=None
            )
        agent = await self.agent_repository.get_by_id(session, agent_id)
        if (
            agent is None
            or agent.workspace_id != workspace_id
            or agent.lifecycle_status is not AgentLifecycleStatus.ACTIVE
        ):
            return RuntimeWebOperationError(
                RuntimeWebOperationCode.NOT_FOUND, scope=None
            )
        if agent.runtime_capability is not AgentRuntimeCapability.MANAGED:
            return RuntimeWebOperationError(
                RuntimeWebOperationCode.CAPABILITY_UNAVAILABLE, scope=None
            )
        return None

    async def _configuration(
        self,
        session: ReadSession,
    ) -> RuntimeWebConfiguration | RuntimeWebOperationError:
        configuration = await self.repository.get_configuration(session)
        if configuration is None or not configuration.enabled:
            return RuntimeWebOperationError(
                RuntimeWebOperationCode.CONFIGURATION_UNAVAILABLE, scope=None
            )
        return configuration

    async def _projection(
        self,
        session: ReadSession,
        record: RuntimeWebServiceRecord,
    ) -> RuntimeWebObservedService:
        now = await session.read_session.scalar(sa.select(sa.func.now()))
        if not isinstance(now, datetime.datetime):
            raise RuntimeError("Database did not return current timestamp")
        return RuntimeWebObservedService(record=record, observed_at=now)


def _receipt_identity(
    command: RuntimeWebCommandIdentity,
) -> RuntimeWebOperationIdentity:
    return RuntimeWebOperationIdentity(
        actor_kind=command.actor_kind,
        actor_id=command.actor_id,
        execution_id=command.execution_id,
        operation_key=command.operation_key,
    )


def get_runtime_web_operations_repository(
    session_manager: Annotated[
        SessionManager[WriteSession], Depends(get_session_manager)
    ],
    repository: Annotated[RuntimeWebRepository, Depends(get_runtime_web_repository)],
    agent_repository: Annotated[AgentRepository, Depends(AgentRepository)],
    agent_admin_repository: Annotated[
        AgentAdminRepository, Depends(AgentAdminRepository)
    ],
    workspace_user_repository: Annotated[
        WorkspaceUserRepository, Depends(WorkspaceUserRepository)
    ],
) -> RuntimeWebOperationsRepository:
    """Compose narrow authorities under one completed operation owner."""
    return RuntimeWebOperationsRepository(
        session_manager=session_manager,
        repository=repository,
        agent_repository=agent_repository,
        agent_admin_repository=agent_admin_repository,
        workspace_user_repository=workspace_user_repository,
    )
