"""Current Agent service and Runtime admission authority for the Gateway."""

import datetime
import enum

import sqlalchemy as sa

from azents.core.enums import (
    AgentLifecycleStatus,
    AgentRuntimeCapability,
    AgentType,
    RuntimeDesiredState,
    RuntimeProviderObservedState,
    RuntimeRunnerState,
    WorkspaceUserRole,
)
from azents.rdb.session import SessionManager
from azents.rdb.session_capabilities import ReadSession, WriteSession
from azents.repos.agent import AgentRepository
from azents.repos.agent_admin import AgentAdminRepository
from azents.repos.agent_runtime import AgentRuntimeRepository
from azents.repos.agent_runtime.data import AgentRuntime
from azents.repos.runtime_web.data import RuntimeWebServiceRecord
from azents.repos.runtime_web.gateway_data import RuntimeWebGatewayAuthority
from azents.repos.runtime_web.gateway_repository import RuntimeWebGatewayRepository
from azents.repos.runtime_web.repository import RuntimeWebRepository
from azents.repos.workspace_user import WorkspaceUserRepository


class RuntimeWebGatewayOperationCode(enum.StrEnum):
    """Bounded Gateway errors emitted before application response bytes."""

    UNAUTHENTICATED = "unauthenticated"
    NOT_FOUND = "not_found"
    GONE = "gone"
    RUNTIME_UNAVAILABLE = "runtime_unavailable"


class RuntimeWebGatewayOperationRejected(ValueError):
    """Current durable authority rejected Gateway admission."""

    def __init__(self, code: RuntimeWebGatewayOperationCode) -> None:
        super().__init__(code.value)
        self.code = code


class RuntimeWebGatewayAuthorityOperationsRepository:
    """Resolve one request against current identity and Agent service authority."""

    def __init__(
        self,
        *,
        session_manager: SessionManager[WriteSession],
        gateway_repository: RuntimeWebGatewayRepository,
        runtime_web_repository: RuntimeWebRepository,
        agent_repository: AgentRepository,
        agent_admin_repository: AgentAdminRepository,
        workspace_user_repository: WorkspaceUserRepository,
        runtime_repository: AgentRuntimeRepository,
    ) -> None:
        self.session_manager = session_manager
        self.gateway_repository = gateway_repository
        self.runtime_web_repository = runtime_web_repository
        self.agent_repository = agent_repository
        self.agent_admin_repository = agent_admin_repository
        self.workspace_user_repository = workspace_user_repository
        self.runtime_repository = runtime_repository

    async def authorize(
        self,
        *,
        hostname_key: str,
        identity_hash: str,
    ) -> RuntimeWebGatewayAuthority:
        """Authorize identity, Agent access, exposure, and current Runtime."""
        async with self.session_manager() as session:
            now = await self._database_now(session)
            identity = await self.gateway_repository.authenticate_identity(
                session,
                secret_hash=identity_hash,
                now=now,
            )
            if identity is None:
                raise RuntimeWebGatewayOperationRejected(
                    RuntimeWebGatewayOperationCode.UNAUTHENTICATED
                )
            service = await self.runtime_web_repository.get_service_by_hostname(
                session,
                hostname_key=hostname_key,
            )
            if service is None or not await self._authorize_service(
                session,
                service=service,
                user_id=identity.user_id,
            ):
                raise RuntimeWebGatewayOperationRejected(
                    RuntimeWebGatewayOperationCode.NOT_FOUND
                )
            if (
                service.exposure_deadline_at is None
                or service.exposure_deadline_at <= now
            ):
                raise RuntimeWebGatewayOperationRejected(
                    RuntimeWebGatewayOperationCode.GONE
                )
            runtime = await self.runtime_repository.get_by_agent_id(
                session,
                service.agent_id,
            )
            if not _runtime_ready(runtime):
                raise RuntimeWebGatewayOperationRejected(
                    RuntimeWebGatewayOperationCode.RUNTIME_UNAVAILABLE
                )
            assert runtime is not None
            return RuntimeWebGatewayAuthority(
                identity=identity,
                service=service,
                runtime_id=runtime.id,
                desired_generation=runtime.desired_generation,
                runner_generation=runtime.runner_generation,
                exposure_deadline_at=service.exposure_deadline_at,
            )

    async def resolve_service(
        self,
        *,
        hostname_key: str,
    ) -> RuntimeWebServiceRecord | None:
        """Resolve a public host label without disclosing private authority."""
        async with self.session_manager() as session:
            return await self.runtime_web_repository.get_service_by_hostname(
                session,
                hostname_key=hostname_key,
            )

    async def resolve_service_by_id(
        self,
        *,
        service_id: str,
    ) -> RuntimeWebServiceRecord | None:
        """Resolve the service destination of a consumed auth ticket."""
        async with self.session_manager() as session:
            return await self.runtime_web_repository.get_service_by_id(
                session,
                service_id,
            )

    async def identity_and_access_current(
        self,
        *,
        authority: RuntimeWebGatewayAuthority,
    ) -> bool:
        """Revalidate identity, user access, service state, and Runtime generation."""
        async with self.session_manager() as session:
            now = await self._database_now(session)
            identity_current = await self.gateway_repository.identity_authority_current(
                session,
                identity_id=authority.identity.id,
                user_id=authority.identity.user_id,
                auth_session_id=authority.identity.auth_session_id,
                now=now,
            )
            service = await self.runtime_web_repository.get_service_by_id(
                session,
                authority.service.id,
            )
            if (
                not identity_current
                or service is None
                or service.exposure_deadline_at is None
                or service.exposure_deadline_at <= now
                or not await self._authorize_service(
                    session,
                    service=service,
                    user_id=authority.identity.user_id,
                )
            ):
                return False
            runtime = await self.runtime_repository.get_by_agent_id(
                session,
                service.agent_id,
            )
            return (
                _runtime_ready(runtime)
                and runtime is not None
                and runtime.id == authority.runtime_id
                and runtime.desired_generation == authority.desired_generation
                and runtime.runner_generation == authority.runner_generation
            )

    async def _authorize_service(
        self,
        session: ReadSession,
        *,
        service: RuntimeWebServiceRecord,
        user_id: str,
    ) -> bool:
        member = await self.workspace_user_repository.get_by_workspace_and_user(
            session,
            service.workspace_id,
            user_id,
        )
        agent = await self.agent_repository.get_by_id(session, service.agent_id)
        if (
            member is None
            or agent is None
            or agent.workspace_id != service.workspace_id
            or agent.lifecycle_status is not AgentLifecycleStatus.ACTIVE
            or agent.runtime_capability is not AgentRuntimeCapability.MANAGED
        ):
            return False
        if (
            agent.type is not AgentType.PRIVATE
            or member.role is WorkspaceUserRole.OWNER
        ):
            return True
        return await self.agent_admin_repository.is_admin(
            session,
            agent.id,
            member.id,
        )

    @staticmethod
    async def _database_now(session: ReadSession) -> datetime.datetime:
        now = await session.read_session.scalar(sa.select(sa.func.now()))
        if not isinstance(now, datetime.datetime):
            raise RuntimeError("Database did not return current timestamp")
        return now


def _runtime_ready(runtime: AgentRuntime | None) -> bool:
    """Return whether current Provider and Runner evidence can serve Runtime Web."""
    return (
        runtime is not None
        and runtime.desired_state is RuntimeDesiredState.RUNNING
        and runtime.desired_generation >= 1
        and runtime.provider_observed_state is RuntimeProviderObservedState.RUNNING
        and runtime.provider_observed_generation == runtime.desired_generation
        and runtime.runner_state is RuntimeRunnerState.READY
        and runtime.runner_generation >= 1
    )
