"""Completed database-only Gateway identity and broker exchange operations."""

import datetime

from azents.core.enums import (
    AgentLifecycleStatus,
    AgentRuntimeCapability,
    AgentType,
    WorkspaceUserRole,
)
from azents.rdb.session import SessionManager
from azents.rdb.session_capabilities import WriteSession
from azents.repos.agent import AgentRepository
from azents.repos.agent_admin import AgentAdminRepository
from azents.repos.runtime_web.gateway_data import (
    RuntimeWebBrokerBinding,
    RuntimeWebDesiredConfiguration,
    RuntimeWebGatewayIdentity,
    RuntimeWebIssuedBinding,
    RuntimeWebIssuedTicket,
    RuntimeWebRedeemedIdentity,
)
from azents.repos.runtime_web.gateway_repository import (
    RuntimeWebGatewayRepository,
)
from azents.repos.runtime_web.repository import RuntimeWebRepositoryConflict
from azents.repos.workspace_user import WorkspaceUserRepository


class RuntimeWebGatewayAuthOperationsRepository:
    """Finish authentication operations before returning detached outputs."""

    def __init__(
        self,
        *,
        session_manager: SessionManager[WriteSession],
        repository: RuntimeWebGatewayRepository,
        agent_repository: AgentRepository,
        agent_admin_repository: AgentAdminRepository,
        workspace_user_repository: WorkspaceUserRepository,
    ) -> None:
        self.session_manager = session_manager
        self.repository = repository
        self.agent_repository = agent_repository
        self.agent_admin_repository = agent_admin_repository
        self.workspace_user_repository = workspace_user_repository

    async def synchronize_configuration(
        self,
        desired: RuntimeWebDesiredConfiguration,
    ) -> None:
        """Install the current Gateway authentication configuration."""
        async with self.session_manager() as session:
            await self.repository.synchronize_configuration(
                session,
                desired=desired,
            )

    async def issue_shared_identity(
        self,
        *,
        user_id: str,
        auth_session_id: str,
        now: datetime.datetime,
        secret_hash: str,
        expires_at: datetime.datetime,
    ) -> None:
        """Mint one shared-mode identity for a trusted Main Web response."""
        async with self.session_manager() as session:
            await self.repository.create_identity(
                session,
                secret_hash=secret_hash,
                user_id=user_id,
                auth_session_id=auth_session_id,
                issued_at=now,
                expires_at=expires_at,
            )

    async def authenticate(
        self,
        *,
        secret_hash: str,
        now: datetime.datetime,
    ) -> RuntimeWebGatewayIdentity | None:
        """Validate one opaque identity cookie."""
        async with self.session_manager() as session:
            return await self.repository.authenticate_identity(
                session,
                secret_hash=secret_hash,
                now=now,
            )

    async def revoke(
        self,
        *,
        secret_hash: str,
        user_id: str,
        auth_session_id: str,
        now: datetime.datetime,
    ) -> bool:
        """Revoke one identity during trusted logout."""
        async with self.session_manager() as session:
            return await self.repository.revoke_identity(
                session,
                secret_hash=secret_hash,
                user_id=user_id,
                auth_session_id=auth_session_id,
                revoked_at=now,
            )

    async def initiate_separate_domain(
        self,
        *,
        user_id: str,
        auth_session_id: str,
        service_id: str,
        now: datetime.datetime,
        initiation_id: str,
        main_binding_hash: str,
        main_binding_secret: str,
        expires_at: datetime.datetime,
    ) -> RuntimeWebIssuedBinding:
        """Create one short-lived Main-origin browser binding."""
        async with self.session_manager() as session:
            service = await self.repository.get_service_by_id(
                session,
                service_id=service_id,
            )
            if service is None:
                raise RuntimeWebRepositoryConflict("Runtime Web service is unavailable")
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
                raise RuntimeWebRepositoryConflict("Runtime Web service is unavailable")
            if (
                agent.type is AgentType.PRIVATE
                and member.role is not WorkspaceUserRole.OWNER
                and not await self.agent_admin_repository.is_admin(
                    session,
                    agent.id,
                    member.id,
                )
            ):
                raise RuntimeWebRepositoryConflict("Runtime Web service is unavailable")
            return await self.repository.create_binding(
                session,
                initiation_id=initiation_id,
                main_binding_hash=main_binding_hash,
                user_id=user_id,
                auth_session_id=auth_session_id,
                service_id=service_id,
                expires_at=expires_at,
                now=now,
                main_binding_secret=main_binding_secret,
            )

    async def bind_broker(
        self,
        *,
        initiation_id: str,
        now: datetime.datetime,
        broker_binding_hash: str,
        broker_binding_secret: str,
    ) -> RuntimeWebBrokerBinding:
        """Create a host-only broker binding for the initiation."""
        async with self.session_manager() as session:
            return await self.repository.bind_broker(
                session,
                initiation_id=initiation_id,
                broker_binding_hash=broker_binding_hash,
                broker_binding_secret=broker_binding_secret,
                now=now,
            )

    async def mark_broker_bound(
        self,
        *,
        initiation_id: str,
        main_binding_hash: str,
        user_id: str,
        auth_session_id: str,
        now: datetime.datetime,
    ) -> None:
        """Settle the broker callback under Main binding and auth Session proof."""
        async with self.session_manager() as session:
            await self.repository.mark_broker_bound(
                session,
                initiation_id=initiation_id,
                main_binding_hash=main_binding_hash,
                user_id=user_id,
                auth_session_id=auth_session_id,
                now=now,
            )

    async def issue_ticket(
        self,
        *,
        initiation_id: str,
        main_binding_hash: str,
        user_id: str,
        auth_session_id: str,
        now: datetime.datetime,
        ticket_hash: str,
        ticket_secret: str,
        expires_at: datetime.datetime,
    ) -> RuntimeWebIssuedTicket:
        """Issue a one-use POST-body ticket after the broker callback."""
        async with self.session_manager() as session:
            return await self.repository.issue_ticket(
                session,
                initiation_id=initiation_id,
                main_binding_hash=main_binding_hash,
                user_id=user_id,
                auth_session_id=auth_session_id,
                ticket_hash=ticket_hash,
                ticket_secret=ticket_secret,
                issued_at=now,
                expires_at=expires_at,
            )

    async def redeem_ticket(
        self,
        *,
        ticket_hash: str,
        broker_binding_hash: str,
        now: datetime.datetime,
        identity_hash: str,
        identity_secret: str,
        identity_expires_at: datetime.datetime,
    ) -> RuntimeWebRedeemedIdentity:
        """Consume a ticket once and establish the common identity."""
        async with self.session_manager() as session:
            return await self.repository.redeem_ticket(
                session,
                ticket_hash=ticket_hash,
                broker_binding_hash=broker_binding_hash,
                identity_hash=identity_hash,
                identity_secret=identity_secret,
                identity_expires_at=identity_expires_at,
                now=now,
            )
