"""Current Session, approval, and Runtime admission authority for the Gateway."""

import datetime
import enum
import hashlib
import secrets

import sqlalchemy as sa
from azents_runtime_control.runner_web import RunnerWebIdentity, RunnerWebProtocol
from sqlalchemy.ext.asyncio import AsyncSession

from azents.core.enums import (
    RuntimeDesiredState,
    RuntimeProviderObservedState,
    RuntimeRunnerState,
)
from azents.rdb.session import SessionManager
from azents.repos.agent_runtime import AgentRuntimeRepository
from azents.repos.agent_session import AgentSessionRepository
from azents.repos.runtime_web.data import RuntimeWebEndpoint
from azents.repos.runtime_web.gateway_data import (
    RuntimeWebAdmissionLimits,
    RuntimeWebGatewayAuthority,
)
from azents.repos.runtime_web.gateway_repository import (
    RuntimeWebGatewayRepository,
)
from azents.repos.runtime_web.repository import RuntimeWebRepository
from azents.repos.workspace_user import WorkspaceUserRepository
from azents.services.session_resource_authority import (
    AuthorizedPublicSessionResource,
    authorize_public_session_resource,
)

_REGISTRATION_WINDOW = datetime.timedelta(seconds=10)
_HTTP_ABSOLUTE_WINDOW = datetime.timedelta(minutes=10)


class RuntimeWebGatewayAuthorityCode(enum.StrEnum):
    """Bounded Gateway errors emitted before application response bytes."""

    UNAUTHENTICATED = "unauthenticated"
    NOT_FOUND = "not_found"
    PENDING_APPROVAL = "pending_approval"
    GONE = "gone"
    RUNTIME_UNAVAILABLE = "runtime_unavailable"


class RuntimeWebGatewayAuthorityError(ValueError):
    """Current durable authority rejected Gateway admission."""

    def __init__(self, code: RuntimeWebGatewayAuthorityCode) -> None:
        super().__init__(code.value)
        self.code = code


class RuntimeWebGatewayAuthorityService:
    """Resolve one request against current identity and Session authority."""

    def __init__(
        self,
        *,
        session_manager: SessionManager[AsyncSession],
        gateway_repository: RuntimeWebGatewayRepository,
        runtime_web_repository: RuntimeWebRepository,
        agent_session_repository: AgentSessionRepository,
        workspace_user_repository: WorkspaceUserRepository,
        runtime_repository: AgentRuntimeRepository,
    ) -> None:
        self.session_manager = session_manager
        self.gateway_repository = gateway_repository
        self.runtime_web_repository = runtime_web_repository
        self.agent_session_repository = agent_session_repository
        self.workspace_user_repository = workspace_user_repository
        self.runtime_repository = runtime_repository

    async def authorize(
        self,
        *,
        hostname_key: str,
        identity_secret: str,
        browser_profile: str,
        protocol: RunnerWebProtocol,
    ) -> RuntimeWebGatewayAuthority:
        """Authorize identity, Session membership, approval, and current Runtime."""
        async with self.session_manager() as session:
            now = await self._database_now(session)
            identity = await self.gateway_repository.authenticate_identity(
                session,
                secret_hash=hashlib.sha256(identity_secret.encode()).hexdigest(),
                browser_profile=browser_profile,
                now=now,
            )
            if identity is None:
                raise RuntimeWebGatewayAuthorityError(
                    RuntimeWebGatewayAuthorityCode.UNAUTHENTICATED
                )
            endpoint_rdb = await self.gateway_repository.get_endpoint_by_hostname(
                session,
                hostname_key=hostname_key,
            )
            if endpoint_rdb is None:
                raise RuntimeWebGatewayAuthorityError(
                    RuntimeWebGatewayAuthorityCode.NOT_FOUND
                )
            endpoint = await self.runtime_web_repository.get_endpoint(
                session,
                agent_session_id=endpoint_rdb.agent_session_id,
                port=endpoint_rdb.port,
            )
            if endpoint is None:
                raise RuntimeWebGatewayAuthorityError(
                    RuntimeWebGatewayAuthorityCode.NOT_FOUND
                )
            access = await self._authorize_endpoint(
                session,
                endpoint=endpoint,
                user_id=identity.user_id,
            )
            if access is None:
                raise RuntimeWebGatewayAuthorityError(
                    RuntimeWebGatewayAuthorityCode.NOT_FOUND
                )
            request = await self.runtime_web_repository.current_request(
                session,
                endpoint,
            )
            cycle = await self.runtime_web_repository.current_cycle(
                session,
                endpoint,
            )
            active = (
                cycle is not None
                and cycle.ended_at is None
                and cycle.expires_at > now
                and cycle.close_barrier == endpoint.close_barrier
                and endpoint.current_cycle_id == cycle.id
            )
            if not active:
                code = (
                    RuntimeWebGatewayAuthorityCode.PENDING_APPROVAL
                    if request is not None and request.state.value == "pending"
                    else RuntimeWebGatewayAuthorityCode.GONE
                )
                raise RuntimeWebGatewayAuthorityError(code)
            runtime = await self.runtime_repository.get_by_agent_id(
                session,
                endpoint.agent_id,
            )
            runtime_ready = (
                runtime is not None
                and runtime.desired_state is RuntimeDesiredState.RUNNING
                and runtime.provider_observed_state
                is RuntimeProviderObservedState.RUNNING
                and runtime.runner_state is RuntimeRunnerState.READY
                and runtime.desired_generation >= 1
                and runtime.runner_generation == runtime.desired_generation
            )
            if not runtime_ready or runtime is None:
                raise RuntimeWebGatewayAuthorityError(
                    RuntimeWebGatewayAuthorityCode.RUNTIME_UNAVAILABLE
                )
            return RuntimeWebGatewayAuthority(
                identity=identity,
                endpoint=endpoint,
                request=request,
                cycle=cycle,
                runtime_id=runtime.id,
                desired_generation=runtime.desired_generation,
                runner_generation=runtime.runner_generation,
                active=True,
                runtime_ready=True,
            )

    async def resolve_endpoint(
        self,
        *,
        hostname_key: str,
    ) -> RuntimeWebEndpoint | None:
        """Resolve a public host label without disclosing private authority."""
        async with self.session_manager() as session:
            endpoint_rdb = await self.gateway_repository.get_endpoint_by_hostname(
                session,
                hostname_key=hostname_key,
            )
            if endpoint_rdb is None:
                return None
            return await self.runtime_web_repository.get_endpoint(
                session,
                agent_session_id=endpoint_rdb.agent_session_id,
                port=endpoint_rdb.port,
            )

    async def resolve_endpoint_by_id(
        self,
        *,
        endpoint_id: str,
    ) -> RuntimeWebEndpoint | None:
        """Resolve the endpoint destination of a consumed auth ticket."""
        async with self.session_manager() as session:
            endpoint_rdb = await self.gateway_repository.get_endpoint_by_id(
                session,
                endpoint_id=endpoint_id,
            )
            if endpoint_rdb is None:
                return None
            return await self.runtime_web_repository.get_endpoint(
                session,
                agent_session_id=endpoint_rdb.agent_session_id,
                port=endpoint_rdb.port,
            )

    async def source_endpoint_matches_root(
        self,
        *,
        source_hostname_key: str,
        target_endpoint: RuntimeWebEndpoint,
    ) -> bool:
        """Return whether two exact endpoint labels share one root Session."""
        async with self.session_manager() as session:
            source = await self.gateway_repository.get_endpoint_by_hostname(
                session,
                hostname_key=source_hostname_key,
            )
            if source is None:
                return False
            source_session = await self.agent_session_repository.get_by_id(
                session,
                source.agent_session_id,
            )
            target_session = await self.agent_session_repository.get_by_id(
                session,
                target_endpoint.agent_session_id,
            )
            if source_session is None or target_session is None:
                return False
            source_root = await self._root_session_id(session, source_session.id)
            target_root = await self._root_session_id(session, target_session.id)
            return source_root is not None and source_root == target_root

    def tunnel_identity(
        self,
        *,
        authority: RuntimeWebGatewayAuthority,
        protocol: RunnerWebProtocol,
        now: datetime.datetime,
    ) -> RunnerWebIdentity:
        """Create one exact non-replayable transport identity."""
        cycle = authority.cycle
        runtime_id = authority.runtime_id
        desired_generation = authority.desired_generation
        runner_generation = authority.runner_generation
        if (
            cycle is None
            or runtime_id is None
            or desired_generation is None
            or runner_generation is None
        ):
            raise RuntimeWebGatewayAuthorityError(
                RuntimeWebGatewayAuthorityCode.RUNTIME_UNAVAILABLE
            )
        transport_deadline = (
            min(cycle.expires_at, now + _HTTP_ABSOLUTE_WINDOW)
            if protocol is RunnerWebProtocol.HTTP
            else cycle.expires_at
        )
        return RunnerWebIdentity(
            tunnel_id=secrets.token_hex(32),
            endpoint_id=authority.endpoint.id,
            cycle_id=cycle.id,
            endpoint_authority_revision=authority.endpoint.authority_revision,
            close_barrier=authority.endpoint.close_barrier,
            runtime_id=runtime_id,
            desired_generation=desired_generation,
            runner_generation=runner_generation,
            port=authority.endpoint.port,
            join_nonce=secrets.token_urlsafe(32),
            registration_deadline_at=min(
                cycle.expires_at,
                now + _REGISTRATION_WINDOW,
            ),
            approval_deadline_at=transport_deadline,
            transport_deadline_at=transport_deadline,
        )

    async def acquire_admission(
        self,
        *,
        authority: RuntimeWebGatewayAuthority,
        identity: RunnerWebIdentity,
        protocol: RunnerWebProtocol,
        limits: RuntimeWebAdmissionLimits,
        now: datetime.datetime,
    ) -> None:
        """Acquire shared endpoint, user, and Agent connection capacity."""
        async with self.session_manager() as session:
            await self.gateway_repository.acquire_admission(
                session,
                tunnel_id=identity.tunnel_id,
                endpoint_id=authority.endpoint.id,
                user_id=authority.identity.user_id,
                agent_id=authority.endpoint.agent_id,
                websocket=protocol is RunnerWebProtocol.WEBSOCKET,
                lease_expires_at=identity.transport_deadline_at,
                now=now,
                limits=limits,
            )

    async def release_admission(self, *, tunnel_id: str) -> None:
        """Release shared capacity when the public transport ends."""
        async with self.session_manager() as session:
            await self.gateway_repository.release_admission(
                session,
                tunnel_id=tunnel_id,
            )

    async def identity_and_access_current(
        self,
        *,
        authority: RuntimeWebGatewayAuthority,
    ) -> bool:
        """Revalidate identity, auth Session, user, and Session membership."""
        async with self.session_manager() as session:
            now = await self._database_now(session)
            current = await self.gateway_repository.identity_authority_current(
                session,
                identity_id=authority.identity.id,
                user_id=authority.identity.user_id,
                auth_session_id=authority.identity.auth_session_id,
                browser_profile=authority.identity.browser_profile,
                epoch=authority.identity.epoch,
                now=now,
            )
            if not current:
                return False
            return (
                await self._authorize_endpoint(
                    session,
                    endpoint=authority.endpoint,
                    user_id=authority.identity.user_id,
                )
                is not None
            )

    async def _authorize_endpoint(
        self,
        session: AsyncSession,
        *,
        endpoint: RuntimeWebEndpoint,
        user_id: str,
    ) -> AuthorizedPublicSessionResource | None:
        agent_session = await self.agent_session_repository.get_by_id(
            session,
            endpoint.agent_session_id,
        )
        if agent_session is None:
            return None
        access = await authorize_public_session_resource(
            session,
            agent_session=agent_session,
            user_id=user_id,
            require_active=True,
            denied_as_not_found=True,
            expected_workspace_id=endpoint.workspace_id,
            expected_agent_id=endpoint.agent_id,
            agent_session_repository=self.agent_session_repository,
            workspace_user_repository=self.workspace_user_repository,
        )
        if not isinstance(access, AuthorizedPublicSessionResource):
            return None
        return access

    async def _root_session_id(
        self,
        session: AsyncSession,
        agent_session_id: str,
    ) -> str | None:
        agent_session = await self.agent_session_repository.get_by_id(
            session,
            agent_session_id,
        )
        if agent_session is None:
            return None
        root_agent = (
            await self.agent_session_repository.get_root_session_agent_by_session_id(
                session,
                agent_session_id,
            )
        )
        return (
            root_agent.agent_session_id if root_agent is not None else agent_session.id
        )

    @staticmethod
    async def _database_now(session: AsyncSession) -> datetime.datetime:
        now = await session.scalar(sa.select(sa.func.now()))
        if not isinstance(now, datetime.datetime):
            raise RuntimeError("Database did not return current timestamp")
        return now
