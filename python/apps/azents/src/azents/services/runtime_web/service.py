"""Runtime-independent durable Runtime Web service operations."""

import datetime
from typing import Annotated

import sqlalchemy as sa
from azcommon.result import Failure, Result, Success
from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from azents.rdb.deps import get_session_manager
from azents.rdb.models.runtime_web import (
    RuntimeWebOperationKind,
    RuntimeWebRequesterKind,
    RuntimeWebRequestState,
)
from azents.rdb.session import SessionManager
from azents.repos.agent_session import AgentSessionRepository
from azents.repos.runtime_web.data import (
    RuntimeWebConfiguration,
    RuntimeWebEndpoint,
    derived_operation_key,
)
from azents.repos.runtime_web.repository import (
    RuntimeWebRepository,
    RuntimeWebRepositoryConflict,
    RuntimeWebRepositoryQuotaExceeded,
)
from azents.repos.workspace_user import WorkspaceUserRepository
from azents.services.runtime_web.data import (
    RuntimeWebAccessDenied,
    RuntimeWebActor,
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
from azents.services.runtime_web.url import (
    RuntimeWebEndpointUrlResolver,
    get_runtime_web_endpoint_url_resolver,
)
from azents.services.session_resource_authority import (
    AuthorizedPublicSessionResource,
    PublicSessionResourceDenied,
    authorize_public_session_resource,
    resolve_agent_session_resource,
)

_ENDPOINT_LIMIT = 16
_ACTIVE_SESSION_LIMIT = 4
_ACTIVE_AGENT_LIMIT = 16


class RuntimeWebService:
    """Authorize and coordinate durable Runtime Web state."""

    def __init__(
        self,
        *,
        session_manager: SessionManager[AsyncSession],
        repository: RuntimeWebRepository,
        agent_session_repository: AgentSessionRepository,
        workspace_user_repository: WorkspaceUserRepository,
        url_resolver: RuntimeWebEndpointUrlResolver,
    ) -> None:
        self.session_manager = session_manager
        self.repository = repository
        self.agent_session_repository = agent_session_repository
        self.workspace_user_repository = workspace_user_repository
        self.url_resolver = url_resolver

    async def prepare_endpoint(
        self,
        *,
        workspace_id: str,
        agent_id: str,
        session_id: str,
        user_id: str | None,
        port: int,
        label: str | None,
        actor: RuntimeWebActor,
        operation: RuntimeWebOperation,
    ) -> Result[RuntimeWebServiceProjection, RuntimeWebError]:
        """Prepare a stable endpoint without creating an exposure request."""
        async with self.session_manager() as session:
            access = await self._authorize(
                session,
                workspace_id=workspace_id,
                agent_id=agent_id,
                session_id=session_id,
                user_id=user_id,
                actor=actor,
            )
            if not isinstance(access, AuthorizedPublicSessionResource):
                return Failure(access)
            configuration = await self._configuration(session)
            if isinstance(configuration, RuntimeWebConfigurationUnavailable):
                return Failure(configuration)
            try:
                result = await self.repository.prepare_endpoint(
                    session,
                    workspace_id=workspace_id,
                    agent_id=agent_id,
                    agent_session_id=session_id,
                    port=port,
                    label=label,
                    operation=operation_identity(actor, operation),
                    endpoint_limit=_ENDPOINT_LIMIT,
                )
            except RuntimeWebRepositoryQuotaExceeded as error:
                return Failure(RuntimeWebQuotaExceeded(scope=error.scope))
            return Success(
                await self._projection(session, result.endpoint, configuration)
            )

    async def request_exposure(
        self,
        *,
        workspace_id: str,
        agent_id: str,
        session_id: str,
        user_id: str | None,
        port: int,
        label: str | None,
        actor: RuntimeWebActor,
        operation: RuntimeWebOperation,
    ) -> Result[RuntimeWebServiceProjection, RuntimeWebError]:
        """Submit a pending request without awaiting human approval."""
        async with self.session_manager() as session:
            access = await self._authorize(
                session,
                workspace_id=workspace_id,
                agent_id=agent_id,
                session_id=session_id,
                user_id=user_id,
                actor=actor,
            )
            if not isinstance(access, AuthorizedPublicSessionResource):
                return Failure(access)
            configuration = await self._configuration(session)
            if isinstance(configuration, RuntimeWebConfigurationUnavailable):
                return Failure(configuration)
            identity = operation_identity(actor, operation)
            try:
                prepared = await self.repository.prepare_endpoint(
                    session,
                    workspace_id=workspace_id,
                    agent_id=agent_id,
                    agent_session_id=session_id,
                    port=port,
                    label=label,
                    operation=identity.model_copy(
                        update={"operation_key": self._subkey(operation, "prepare")}
                    ),
                    endpoint_limit=_ENDPOINT_LIMIT,
                )
                result = await self.repository.request_exposure(
                    session,
                    endpoint_id=prepared.endpoint.id,
                    actor_kind=actor.kind,
                    requester_user_id=(
                        actor.actor_id
                        if actor.kind is RuntimeWebRequesterKind.USER
                        else None
                    ),
                    requester_agent_id=(
                        actor.actor_id
                        if actor.kind is RuntimeWebRequesterKind.AGENT
                        else None
                    ),
                    requester_call_id=actor.call_id,
                    label=label,
                    operation=identity,
                )
            except RuntimeWebRepositoryQuotaExceeded as error:
                return Failure(RuntimeWebQuotaExceeded(scope=error.scope))
            except RuntimeWebRepositoryConflict:
                return Failure(RuntimeWebConflict())
            return Success(
                await self._projection(session, result.endpoint, configuration)
            )

    async def direct_create(
        self,
        *,
        workspace_id: str,
        agent_id: str,
        session_id: str,
        user_id: str | None,
        port: int,
        label: str | None,
        actor: RuntimeWebActor,
        operation: RuntimeWebOperation,
        duration_seconds: int,
        duration_configuration_revision: int,
    ) -> Result[RuntimeWebServiceProjection, RuntimeWebError]:
        """Create and approve one user-confirmed exposure atomically."""
        if (
            user_id is None
            or actor.kind is not RuntimeWebRequesterKind.USER
            or actor.actor_id != user_id
        ):
            return Failure(RuntimeWebAccessDenied())
        async with self.session_manager() as session:
            access = await self._authorize(
                session,
                workspace_id=workspace_id,
                agent_id=agent_id,
                session_id=session_id,
                user_id=user_id,
                actor=actor,
            )
            if not isinstance(access, AuthorizedPublicSessionResource):
                return Failure(access)
            configuration = await self._configuration(session)
            if isinstance(configuration, RuntimeWebConfigurationUnavailable):
                return Failure(configuration)
            try:
                result = await self.repository.direct_create(
                    session,
                    workspace_id=workspace_id,
                    agent_id=agent_id,
                    agent_session_id=session_id,
                    port=port,
                    label=label,
                    requester_user_id=user_id,
                    requester_call_id=actor.call_id,
                    duration_seconds=duration_seconds,
                    duration_configuration_revision=duration_configuration_revision,
                    operation=operation_identity(actor, operation),
                    endpoint_limit=_ENDPOINT_LIMIT,
                    active_session_limit=_ACTIVE_SESSION_LIMIT,
                    active_agent_limit=_ACTIVE_AGENT_LIMIT,
                )
            except RuntimeWebRepositoryQuotaExceeded as error:
                return Failure(RuntimeWebQuotaExceeded(scope=error.scope))
            except RuntimeWebRepositoryConflict:
                return Failure(RuntimeWebConflict())
            return Success(
                await self._projection(session, result.endpoint, configuration)
            )

    async def approve_request(
        self,
        *,
        workspace_id: str,
        agent_id: str,
        session_id: str,
        user_id: str,
        actor: RuntimeWebActor,
        request_id: str,
        expected_revision: int,
        operation: RuntimeWebOperation,
        duration_seconds: int,
        duration_configuration_revision: int,
    ) -> Result[RuntimeWebServiceProjection, RuntimeWebError]:
        """Approve an exact pending request."""
        if actor.kind is not RuntimeWebRequesterKind.USER or actor.actor_id != user_id:
            return Failure(RuntimeWebAccessDenied())
        async with self.session_manager() as session:
            endpoint = await self._authorize_resource(
                session,
                workspace_id=workspace_id,
                agent_id=agent_id,
                session_id=session_id,
                user_id=user_id,
                actor=actor,
                resource=await self.repository.endpoint_for_request(
                    session, request_id
                ),
            )
            if not isinstance(endpoint, RuntimeWebEndpoint):
                return Failure(endpoint)
            configuration = await self._configuration(session)
            if isinstance(configuration, RuntimeWebConfigurationUnavailable):
                return Failure(configuration)
            try:
                result = await self.repository.approve_request(
                    session,
                    request_id=request_id,
                    expected_revision=expected_revision,
                    approver_user_id=user_id,
                    duration_seconds=duration_seconds,
                    duration_configuration_revision=duration_configuration_revision,
                    operation=operation_identity(actor, operation),
                    active_session_limit=_ACTIVE_SESSION_LIMIT,
                    active_agent_limit=_ACTIVE_AGENT_LIMIT,
                )
            except RuntimeWebRepositoryQuotaExceeded as error:
                return Failure(RuntimeWebQuotaExceeded(scope=error.scope))
            except RuntimeWebRepositoryConflict:
                return Failure(RuntimeWebConflict())
            return Success(
                await self._projection(session, result.endpoint, configuration)
            )

    async def reject_request(
        self,
        *,
        workspace_id: str,
        agent_id: str,
        session_id: str,
        user_id: str,
        actor: RuntimeWebActor,
        request_id: str,
        expected_revision: int,
        operation: RuntimeWebOperation,
    ) -> Result[RuntimeWebServiceProjection, RuntimeWebError]:
        """Reject an exact pending request."""
        return await self._decide_user_request(
            workspace_id=workspace_id,
            agent_id=agent_id,
            session_id=session_id,
            user_id=user_id,
            actor=actor,
            request_id=request_id,
            expected_revision=expected_revision,
            operation=operation,
            state=RuntimeWebRequestState.REJECTED,
            kind=RuntimeWebOperationKind.REJECT,
        )

    async def cancel_request(
        self,
        *,
        workspace_id: str,
        agent_id: str,
        session_id: str,
        user_id: str | None,
        request_id: str,
        expected_revision: int,
        actor: RuntimeWebActor,
        operation: RuntimeWebOperation,
    ) -> Result[RuntimeWebServiceProjection, RuntimeWebError]:
        """Cancel a pending request without closing an active cycle."""
        async with self.session_manager() as session:
            endpoint = await self._authorize_resource(
                session,
                workspace_id=workspace_id,
                agent_id=agent_id,
                session_id=session_id,
                user_id=user_id,
                actor=actor,
                resource=await self.repository.endpoint_for_request(
                    session, request_id
                ),
            )
            if not isinstance(endpoint, RuntimeWebEndpoint):
                return Failure(endpoint)
            configuration = await self._configuration(session)
            if isinstance(configuration, RuntimeWebConfigurationUnavailable):
                return Failure(configuration)
            try:
                result = await self.repository.decide_request(
                    session,
                    request_id=request_id,
                    expected_revision=expected_revision,
                    decided_by_user_id=(
                        actor.actor_id
                        if actor.kind is RuntimeWebRequesterKind.USER
                        else None
                    ),
                    state=RuntimeWebRequestState.CANCELLED,
                    operation=operation_identity(actor, operation),
                    kind=RuntimeWebOperationKind.CANCEL,
                )
            except RuntimeWebRepositoryConflict:
                return Failure(RuntimeWebConflict())
            return Success(
                await self._projection(session, result.endpoint, configuration)
            )

    async def close_cycle(
        self,
        *,
        workspace_id: str,
        agent_id: str,
        session_id: str,
        user_id: str | None,
        cycle_id: str,
        expected_endpoint_revision: int,
        actor: RuntimeWebActor,
        operation: RuntimeWebOperation,
    ) -> Result[RuntimeWebServiceProjection, RuntimeWebError]:
        """Close an exact cycle without changing the application process."""
        async with self.session_manager() as session:
            endpoint = await self._authorize_resource(
                session,
                workspace_id=workspace_id,
                agent_id=agent_id,
                session_id=session_id,
                user_id=user_id,
                actor=actor,
                resource=await self.repository.endpoint_for_cycle(session, cycle_id),
            )
            if not isinstance(endpoint, RuntimeWebEndpoint):
                return Failure(endpoint)
            configuration = await self._configuration(session)
            if isinstance(configuration, RuntimeWebConfigurationUnavailable):
                return Failure(configuration)
            try:
                result = await self.repository.close_cycle(
                    session,
                    cycle_id=cycle_id,
                    expected_endpoint_revision=expected_endpoint_revision,
                    operation=operation_identity(actor, operation),
                )
            except RuntimeWebRepositoryConflict:
                return Failure(RuntimeWebConflict())
            return Success(
                await self._projection(session, result.endpoint, configuration)
            )

    async def get_service(
        self,
        *,
        workspace_id: str,
        agent_id: str,
        session_id: str,
        user_id: str | None,
        port: int,
        actor: RuntimeWebActor | None,
    ) -> Result[RuntimeWebServiceProjection, RuntimeWebError]:
        """Get one current service projection."""
        async with self.session_manager() as session:
            access = await self._authorize(
                session,
                workspace_id=workspace_id,
                agent_id=agent_id,
                session_id=session_id,
                user_id=user_id,
                actor=actor,
            )
            if not isinstance(access, AuthorizedPublicSessionResource):
                return Failure(access)
            configuration = await self._configuration(session, require_enabled=False)
            if isinstance(configuration, RuntimeWebConfigurationUnavailable):
                return Failure(configuration)
            endpoint = await self.repository.get_endpoint(
                session,
                agent_session_id=session_id,
                port=port,
            )
            if endpoint is None:
                return Failure(RuntimeWebNotFound())
            return Success(await self._projection(session, endpoint, configuration))

    async def get_service_by_endpoint_id(
        self,
        *,
        endpoint_id: str,
        user_id: str,
        actor: RuntimeWebActor,
    ) -> Result[RuntimeWebServiceProjection, RuntimeWebError]:
        """Get one authorized service projection by opaque endpoint ID."""
        async with self.session_manager() as session:
            endpoint = await self.repository.get_endpoint_by_id(
                session,
                endpoint_id,
            )
            if endpoint is None:
                return Failure(RuntimeWebNotFound())
            access = await self._authorize(
                session,
                workspace_id=endpoint.workspace_id,
                agent_id=endpoint.agent_id,
                session_id=endpoint.agent_session_id,
                user_id=user_id,
                actor=actor,
            )
            if not isinstance(access, AuthorizedPublicSessionResource):
                return Failure(access)
            configuration = await self._configuration(session, require_enabled=False)
            if isinstance(configuration, RuntimeWebConfigurationUnavailable):
                return Failure(configuration)
            return Success(await self._projection(session, endpoint, configuration))

    async def list_services(
        self,
        *,
        workspace_id: str,
        agent_id: str,
        session_id: str,
        user_id: str | None,
        offset: int,
        limit: int,
        actor: RuntimeWebActor | None,
    ) -> Result[RuntimeWebServicePage, RuntimeWebError]:
        """List current services for one concrete Session."""
        async with self.session_manager() as session:
            access = await self._authorize(
                session,
                workspace_id=workspace_id,
                agent_id=agent_id,
                session_id=session_id,
                user_id=user_id,
                actor=actor,
            )
            if not isinstance(access, AuthorizedPublicSessionResource):
                return Failure(access)
            configuration = await self._configuration(session, require_enabled=False)
            if isinstance(configuration, RuntimeWebConfigurationUnavailable):
                return Failure(configuration)
            endpoints, total = await self.repository.list_endpoints(
                session,
                agent_session_id=session_id,
                offset=offset,
                limit=limit,
            )
            return Success(
                RuntimeWebServicePage(
                    items=[
                        await self._projection(session, endpoint, configuration)
                        for endpoint in endpoints
                    ],
                    total_count=total,
                )
            )

    async def _decide_user_request(
        self,
        *,
        workspace_id: str,
        agent_id: str,
        session_id: str,
        user_id: str,
        actor: RuntimeWebActor,
        request_id: str,
        expected_revision: int,
        operation: RuntimeWebOperation,
        state: RuntimeWebRequestState,
        kind: RuntimeWebOperationKind,
    ) -> Result[RuntimeWebServiceProjection, RuntimeWebError]:
        if actor.kind is not RuntimeWebRequesterKind.USER or actor.actor_id != user_id:
            return Failure(RuntimeWebAccessDenied())
        async with self.session_manager() as session:
            endpoint = await self._authorize_resource(
                session,
                workspace_id=workspace_id,
                agent_id=agent_id,
                session_id=session_id,
                user_id=user_id,
                actor=actor,
                resource=await self.repository.endpoint_for_request(
                    session, request_id
                ),
            )
            if not isinstance(endpoint, RuntimeWebEndpoint):
                return Failure(endpoint)
            configuration = await self._configuration(session)
            if isinstance(configuration, RuntimeWebConfigurationUnavailable):
                return Failure(configuration)
            try:
                result = await self.repository.decide_request(
                    session,
                    request_id=request_id,
                    expected_revision=expected_revision,
                    decided_by_user_id=user_id,
                    state=state,
                    operation=operation_identity(actor, operation),
                    kind=kind,
                )
            except RuntimeWebRepositoryConflict:
                return Failure(RuntimeWebConflict())
            return Success(
                await self._projection(session, result.endpoint, configuration)
            )

    async def _authorize(
        self,
        session: AsyncSession,
        *,
        workspace_id: str,
        agent_id: str,
        session_id: str,
        user_id: str | None,
        actor: RuntimeWebActor | None,
    ) -> AuthorizedPublicSessionResource | RuntimeWebError:
        agent_session = await self.agent_session_repository.get_by_id(
            session, session_id
        )
        if agent_session is None:
            return RuntimeWebNotFound()
        if user_id is None:
            if (
                actor is None
                or actor.kind is not RuntimeWebRequesterKind.AGENT
                or actor.actor_id != agent_id
            ):
                return RuntimeWebAccessDenied()
            result = await resolve_agent_session_resource(
                session,
                agent_session=agent_session,
                expected_workspace_id=workspace_id,
                expected_agent_id=agent_id,
                agent_session_repository=self.agent_session_repository,
            )
            if isinstance(result, AuthorizedPublicSessionResource):
                return result
            return RuntimeWebNotFound()
        result = await authorize_public_session_resource(
            session,
            agent_session=agent_session,
            user_id=user_id,
            require_active=True,
            denied_as_not_found=True,
            expected_workspace_id=workspace_id,
            expected_agent_id=agent_id,
            agent_session_repository=self.agent_session_repository,
            workspace_user_repository=self.workspace_user_repository,
        )
        if isinstance(result, AuthorizedPublicSessionResource):
            return result
        if isinstance(result, PublicSessionResourceDenied):
            return RuntimeWebAccessDenied()
        return RuntimeWebNotFound()

    async def _authorize_resource(
        self,
        session: AsyncSession,
        *,
        workspace_id: str,
        agent_id: str,
        session_id: str,
        user_id: str | None,
        actor: RuntimeWebActor | None,
        resource: RuntimeWebEndpoint | None,
    ) -> RuntimeWebEndpoint | RuntimeWebError:
        if (
            resource is None
            or resource.workspace_id != workspace_id
            or resource.agent_id != agent_id
            or resource.agent_session_id != session_id
        ):
            return RuntimeWebNotFound()
        access = await self._authorize(
            session,
            workspace_id=workspace_id,
            agent_id=agent_id,
            session_id=session_id,
            user_id=user_id,
            actor=actor,
        )
        if not isinstance(access, AuthorizedPublicSessionResource):
            return access
        return resource

    async def _configuration(
        self,
        session: AsyncSession,
        *,
        require_enabled: bool = True,
    ) -> RuntimeWebConfiguration | RuntimeWebConfigurationUnavailable:
        configuration = await self.repository.get_configuration(session)
        if configuration is None or (require_enabled and not configuration.enabled):
            return RuntimeWebConfigurationUnavailable()
        return configuration

    async def _projection(
        self,
        session: AsyncSession,
        endpoint: RuntimeWebEndpoint,
        configuration: RuntimeWebConfiguration,
    ) -> RuntimeWebServiceProjection:
        now = await session.scalar(sa.select(sa.func.now()))
        if not isinstance(now, datetime.datetime):
            raise RuntimeError("Database did not return current timestamp")
        request = await self.repository.current_request(session, endpoint)
        cycle = await self.repository.current_cycle(session, endpoint)
        url = self.url_resolver.resolve(endpoint.hostname_key)
        return RuntimeWebServiceProjection(
            endpoint=endpoint,
            url=url,
            configuration_state="configured" if url is not None else "unconfigured",
            current_request=request,
            current_cycle=cycle,
            active=(
                cycle is not None and cycle.ended_at is None and cycle.expires_at > now
            ),
            duration_seconds=configuration.active_duration_seconds,
            duration_configuration_revision=(
                configuration.duration_configuration_revision
            ),
            observed_at=now,
        )

    @staticmethod
    def _subkey(operation: RuntimeWebOperation, suffix: str) -> str:
        return derived_operation_key(operation.operation_key, suffix)


def get_runtime_web_service(
    session_manager: Annotated[
        SessionManager[AsyncSession],
        Depends(get_session_manager),
    ],
    repository: Annotated[RuntimeWebRepository, Depends(RuntimeWebRepository)],
    agent_session_repository: Annotated[
        AgentSessionRepository,
        Depends(AgentSessionRepository),
    ],
    workspace_user_repository: Annotated[
        WorkspaceUserRepository,
        Depends(WorkspaceUserRepository),
    ],
    url_resolver: Annotated[
        RuntimeWebEndpointUrlResolver,
        Depends(get_runtime_web_endpoint_url_resolver),
    ],
) -> RuntimeWebService:
    """Create the Runtime Web domain service."""
    return RuntimeWebService(
        session_manager=session_manager,
        repository=repository,
        agent_session_repository=agent_session_repository,
        workspace_user_repository=workspace_user_repository,
        url_resolver=url_resolver,
    )
