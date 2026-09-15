"""Agent-scoped Runtime Web service operations."""

import datetime
from collections.abc import Awaitable, Callable
from typing import Annotated

import sqlalchemy as sa
from azcommon.result import Failure, Result, Success
from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from azents.core.enums import (
    AgentLifecycleStatus,
    AgentRuntimeCapability,
    AgentType,
    WorkspaceUserRole,
)
from azents.rdb.deps import get_session_manager
from azents.rdb.models.runtime_web import RuntimeWebActorKind
from azents.rdb.session import SessionManager
from azents.repos.agent import AgentRepository
from azents.repos.agent_admin import AgentAdminRepository
from azents.repos.runtime_web.data import (
    RuntimeWebConfiguration,
    RuntimeWebMutationResult,
    RuntimeWebServiceRecord,
)
from azents.repos.runtime_web.repository import (
    RuntimeWebRepository,
    RuntimeWebRepositoryConflict,
    RuntimeWebRepositoryQuotaExceeded,
    get_runtime_web_repository,
)
from azents.repos.workspace_user import WorkspaceUserRepository
from azents.services.runtime_web.data import (
    RuntimeWebAccessDenied,
    RuntimeWebActor,
    RuntimeWebCapabilityUnavailable,
    RuntimeWebConfigurationUnavailable,
    RuntimeWebConflict,
    RuntimeWebError,
    RuntimeWebNotFound,
    RuntimeWebOperation,
    RuntimeWebQuotaExceeded,
    RuntimeWebServicePage,
    RuntimeWebServiceProjection,
    operation_identity,
)
from azents.services.runtime_web.service_url import (
    RuntimeWebServiceUrlResolver,
    get_runtime_web_service_url_resolver,
)

_SERVICE_LIMIT = 16
_ACTIVE_AGENT_LIMIT = 16


class RuntimeWebService:
    """Authorize and coordinate durable Runtime Web service state."""

    def __init__(
        self,
        *,
        session_manager: SessionManager[AsyncSession],
        repository: RuntimeWebRepository,
        agent_repository: AgentRepository,
        agent_admin_repository: AgentAdminRepository,
        workspace_user_repository: WorkspaceUserRepository,
        url_resolver: RuntimeWebServiceUrlResolver,
    ) -> None:
        self.session_manager = session_manager
        self.repository = repository
        self.agent_repository = agent_repository
        self.agent_admin_repository = agent_admin_repository
        self.workspace_user_repository = workspace_user_repository
        self.url_resolver = url_resolver

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
        actor: RuntimeWebActor,
        operation: RuntimeWebOperation,
    ) -> Result[RuntimeWebServiceProjection, RuntimeWebError]:
        """Create one user-managed service."""
        if actor.kind is not RuntimeWebActorKind.USER or actor.actor_id != user_id:
            return Failure(RuntimeWebAccessDenied())
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
            if isinstance(configuration, RuntimeWebConfigurationUnavailable):
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
                    operation=operation_identity(actor, operation),
                    service_limit=_SERVICE_LIMIT,
                    active_agent_limit=_ACTIVE_AGENT_LIMIT,
                )
            except RuntimeWebRepositoryQuotaExceeded as error:
                return Failure(RuntimeWebQuotaExceeded(scope=error.scope))
            except RuntimeWebRepositoryConflict:
                return Failure(RuntimeWebConflict())
            return Success(await self._projection(session, result.service))

    async def request_service(
        self,
        *,
        workspace_id: str,
        agent_id: str,
        port: int,
        label: str | None,
        actor: RuntimeWebActor,
        operation: RuntimeWebOperation,
    ) -> Result[RuntimeWebServiceProjection, RuntimeWebError]:
        """Create a missing Off service or return the existing row unchanged."""
        async with self.session_manager() as session:
            access = await self._authorize_agent(
                session,
                workspace_id=workspace_id,
                agent_id=agent_id,
                actor=actor,
            )
            if access is not None:
                return Failure(access)
            configuration = await self._configuration(session)
            if isinstance(configuration, RuntimeWebConfigurationUnavailable):
                return Failure(configuration)
            try:
                result = await self.repository.request_service(
                    session,
                    workspace_id=workspace_id,
                    agent_id=agent_id,
                    port=port,
                    label=label,
                    operation=operation_identity(actor, operation),
                    service_limit=_SERVICE_LIMIT,
                )
            except RuntimeWebRepositoryQuotaExceeded as error:
                return Failure(RuntimeWebQuotaExceeded(scope=error.scope))
            except RuntimeWebRepositoryConflict:
                return Failure(RuntimeWebConflict())
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
        actor: RuntimeWebActor,
        operation: RuntimeWebOperation,
    ) -> Result[RuntimeWebServiceProjection, RuntimeWebError]:
        """Update service label or selected duration."""
        return await self._user_mutation(
            workspace_id=workspace_id,
            agent_id=agent_id,
            service_id=service_id,
            user_id=user_id,
            workspace_user_id=workspace_user_id,
            role=role,
            actor=actor,
            mutate=lambda session: self.repository.update_service(
                session,
                service_id=service_id,
                expected_revision=expected_revision,
                label_present=label_present,
                label=label,
                selected_duration_seconds=selected_duration_seconds,
                operation=operation_identity(actor, operation),
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
        actor: RuntimeWebActor,
        operation: RuntimeWebOperation,
    ) -> Result[RuntimeWebServiceProjection, RuntimeWebError]:
        """Turn an Off service On."""
        return await self._user_mutation(
            workspace_id=workspace_id,
            agent_id=agent_id,
            service_id=service_id,
            user_id=user_id,
            workspace_user_id=workspace_user_id,
            role=role,
            actor=actor,
            mutate=lambda session: self.repository.turn_on(
                session,
                service_id=service_id,
                expected_revision=expected_revision,
                selected_duration_seconds=selected_duration_seconds,
                operation=operation_identity(actor, operation),
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
        actor: RuntimeWebActor,
        operation: RuntimeWebOperation,
    ) -> Result[RuntimeWebServiceProjection, RuntimeWebError]:
        """Turn one exact service Off."""
        return await self._user_mutation(
            workspace_id=workspace_id,
            agent_id=agent_id,
            service_id=service_id,
            user_id=user_id,
            workspace_user_id=workspace_user_id,
            role=role,
            actor=actor,
            mutate=lambda session: self.repository.turn_off(
                session,
                service_id=service_id,
                expected_revision=expected_revision,
                operation=operation_identity(actor, operation),
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
        actor: RuntimeWebActor,
        operation: RuntimeWebOperation,
    ) -> Result[RuntimeWebServiceProjection, RuntimeWebError]:
        """Restart one current service exposure window."""
        return await self._user_mutation(
            workspace_id=workspace_id,
            agent_id=agent_id,
            service_id=service_id,
            user_id=user_id,
            workspace_user_id=workspace_user_id,
            role=role,
            actor=actor,
            mutate=lambda session: self.repository.reset_expiration(
                session,
                service_id=service_id,
                expected_revision=expected_revision,
                operation=operation_identity(actor, operation),
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
        actor: RuntimeWebActor,
        operation: RuntimeWebOperation,
    ) -> Result[bool, RuntimeWebError]:
        """Delete one exact service after Agent authorization."""
        if actor.kind is not RuntimeWebActorKind.USER or actor.actor_id != user_id:
            return Failure(RuntimeWebAccessDenied())
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
            if isinstance(configuration, RuntimeWebConfigurationUnavailable):
                return Failure(configuration)
            try:
                deleted = await self.repository.delete_service(
                    session,
                    agent_id=agent_id,
                    service_id=service_id,
                    expected_revision=expected_revision,
                    operation=operation_identity(actor, operation),
                )
            except RuntimeWebRepositoryConflict:
                return Failure(RuntimeWebConflict())
            return Success(deleted)

    async def close_service(
        self,
        *,
        workspace_id: str,
        agent_id: str,
        service_id: str,
        actor: RuntimeWebActor,
        operation: RuntimeWebOperation,
    ) -> Result[RuntimeWebServiceProjection, RuntimeWebError]:
        """Idempotently turn one exact service Off for an Agent caller."""
        async with self.session_manager() as session:
            access = await self._authorize_agent(
                session,
                workspace_id=workspace_id,
                agent_id=agent_id,
                actor=actor,
            )
            if access is not None:
                return Failure(access)
            record = await self.repository.get_service_by_id(session, service_id)
            if record is None or record.agent_id != agent_id:
                return Failure(RuntimeWebNotFound())
            configuration = await self._configuration(session)
            if isinstance(configuration, RuntimeWebConfigurationUnavailable):
                return Failure(configuration)
            try:
                result = await self.repository.close_service(
                    session,
                    service_id=service_id,
                    operation=operation_identity(actor, operation),
                )
            except RuntimeWebRepositoryConflict:
                return Failure(RuntimeWebConflict())
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
    ) -> Result[RuntimeWebServiceProjection, RuntimeWebError]:
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
                return Failure(RuntimeWebNotFound())
            return Success(await self._projection(session, record))

    async def get_service_by_id_for_user(
        self,
        *,
        service_id: str,
        user_id: str,
    ) -> Result[RuntimeWebServiceProjection, RuntimeWebError]:
        """Get one authorized service by opaque ID for trusted Main Web."""
        async with self.session_manager() as session:
            record = await self.repository.get_service_by_id(session, service_id)
            if record is None:
                return Failure(RuntimeWebNotFound())
            member = await self.workspace_user_repository.get_by_workspace_and_user(
                session,
                record.workspace_id,
                user_id,
            )
            if member is None:
                return Failure(RuntimeWebNotFound())
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
        actor: RuntimeWebActor,
        operation: RuntimeWebOperation,
    ) -> Result[RuntimeWebServiceProjection, RuntimeWebError]:
        """Turn On through the trusted service URL activation surface."""
        async with self.session_manager() as session:
            record = await self.repository.get_service_by_id(session, service_id)
            if record is None:
                return Failure(RuntimeWebNotFound())
            member = await self.workspace_user_repository.get_by_workspace_and_user(
                session,
                record.workspace_id,
                user_id,
            )
            if member is None:
                return Failure(RuntimeWebNotFound())
        return await self.turn_on(
            workspace_id=record.workspace_id,
            agent_id=record.agent_id,
            service_id=record.id,
            user_id=user_id,
            workspace_user_id=member.id,
            role=member.role,
            expected_revision=expected_revision,
            selected_duration_seconds=selected_duration_seconds,
            actor=actor,
            operation=operation,
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
        actor: RuntimeWebActor | None,
    ) -> Result[RuntimeWebServicePage, RuntimeWebError]:
        """List current services for one Agent."""
        async with self.session_manager() as session:
            if user_id is None:
                if actor is None:
                    return Failure(RuntimeWebAccessDenied())
                access = await self._authorize_agent(
                    session,
                    workspace_id=workspace_id,
                    agent_id=agent_id,
                    actor=actor,
                )
            else:
                if workspace_user_id is None or role is None:
                    return Failure(RuntimeWebAccessDenied())
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
                RuntimeWebServicePage(
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
        actor: RuntimeWebActor,
        mutate: Callable[[AsyncSession], Awaitable[RuntimeWebMutationResult]],
    ) -> Result[RuntimeWebServiceProjection, RuntimeWebError]:
        if actor.kind is not RuntimeWebActorKind.USER or actor.actor_id != user_id:
            return Failure(RuntimeWebAccessDenied())
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
                return Failure(RuntimeWebNotFound())
            configuration = await self._configuration(session)
            if isinstance(configuration, RuntimeWebConfigurationUnavailable):
                return Failure(configuration)
            try:
                result = await mutate(session)
            except RuntimeWebRepositoryQuotaExceeded as error:
                return Failure(RuntimeWebQuotaExceeded(scope=error.scope))
            except RuntimeWebRepositoryConflict:
                return Failure(RuntimeWebConflict())
            return Success(await self._projection(session, result.service))

    async def _authorize_user(
        self,
        session: AsyncSession,
        *,
        workspace_id: str,
        agent_id: str,
        user_id: str,
        workspace_user_id: str,
        role: WorkspaceUserRole,
    ) -> RuntimeWebError | None:
        member = await self.workspace_user_repository.get_by_workspace_and_user(
            session,
            workspace_id,
            user_id,
        )
        if member is None or member.id != workspace_user_id or member.role is not role:
            return RuntimeWebAccessDenied()
        agent = await self.agent_repository.get_by_id(session, agent_id)
        if (
            agent is None
            or agent.workspace_id != workspace_id
            or agent.lifecycle_status is not AgentLifecycleStatus.ACTIVE
        ):
            return RuntimeWebNotFound()
        if agent.type is AgentType.PRIVATE and role is not WorkspaceUserRole.OWNER:
            if not await self.agent_admin_repository.is_admin(
                session,
                agent_id,
                workspace_user_id,
            ):
                return RuntimeWebAccessDenied()
        if agent.runtime_capability is not AgentRuntimeCapability.MANAGED:
            return RuntimeWebCapabilityUnavailable()
        return None

    async def _authorize_agent(
        self,
        session: AsyncSession,
        *,
        workspace_id: str,
        agent_id: str,
        actor: RuntimeWebActor,
    ) -> RuntimeWebError | None:
        if actor.kind is not RuntimeWebActorKind.AGENT or actor.actor_id != agent_id:
            return RuntimeWebAccessDenied()
        agent = await self.agent_repository.get_by_id(session, agent_id)
        if (
            agent is None
            or agent.workspace_id != workspace_id
            or agent.lifecycle_status is not AgentLifecycleStatus.ACTIVE
        ):
            return RuntimeWebNotFound()
        if agent.runtime_capability is not AgentRuntimeCapability.MANAGED:
            return RuntimeWebCapabilityUnavailable()
        return None

    async def _configuration(
        self,
        session: AsyncSession,
    ) -> RuntimeWebConfiguration | RuntimeWebConfigurationUnavailable:
        configuration = await self.repository.get_configuration(session)
        if configuration is None or not configuration.enabled:
            return RuntimeWebConfigurationUnavailable()
        return configuration

    async def _projection(
        self,
        session: AsyncSession,
        record: RuntimeWebServiceRecord,
    ) -> RuntimeWebServiceProjection:
        now = await session.scalar(sa.select(sa.func.now()))
        if not isinstance(now, datetime.datetime):
            raise RuntimeError("Database did not return current timestamp")
        return RuntimeWebServiceProjection.from_record(
            record,
            url=self.url_resolver.resolve(record.hostname_key),
            observed_at=now,
        )


def get_runtime_web_service(
    session_manager: Annotated[
        SessionManager[AsyncSession],
        Depends(get_session_manager),
    ],
    repository: Annotated[
        RuntimeWebRepository,
        Depends(get_runtime_web_repository),
    ],
    agent_repository: Annotated[AgentRepository, Depends(AgentRepository)],
    agent_admin_repository: Annotated[
        AgentAdminRepository,
        Depends(AgentAdminRepository),
    ],
    workspace_user_repository: Annotated[
        WorkspaceUserRepository,
        Depends(WorkspaceUserRepository),
    ],
    url_resolver: Annotated[
        RuntimeWebServiceUrlResolver,
        Depends(get_runtime_web_service_url_resolver),
    ],
) -> RuntimeWebService:
    """Create the Runtime Web domain service."""
    return RuntimeWebService(
        session_manager=session_manager,
        repository=repository,
        agent_repository=agent_repository,
        agent_admin_repository=agent_admin_repository,
        workspace_user_repository=workspace_user_repository,
        url_resolver=url_resolver,
    )
