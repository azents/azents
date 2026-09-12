"""Opaque Runtime Web Gateway identity and broker exchange service."""

import datetime
import hashlib
import secrets

from sqlalchemy.ext.asyncio import AsyncSession

from azents.rdb.session import SessionManager
from azents.repos.agent_session import AgentSessionRepository
from azents.repos.runtime_web.gateway_data import (
    RuntimeWebBrokerBinding,
    RuntimeWebDesiredConfiguration,
    RuntimeWebGatewayIdentity,
    RuntimeWebIssuedBinding,
    RuntimeWebIssuedSecret,
    RuntimeWebIssuedTicket,
    RuntimeWebRedeemedIdentity,
)
from azents.repos.runtime_web.gateway_repository import (
    RuntimeWebGatewayRepository,
)
from azents.repos.runtime_web.repository import RuntimeWebRepositoryConflict
from azents.repos.workspace_user import WorkspaceUserRepository
from azents.services.session_resource_authority import (
    AuthorizedPublicSessionResource,
    authorize_public_session_resource,
)

_BINDING_LIFETIME = datetime.timedelta(minutes=2)
_TICKET_LIFETIME = datetime.timedelta(seconds=30)


class RuntimeWebGatewayAuthService:
    """Coordinate opaque secrets without exposing their stored hashes."""

    def __init__(
        self,
        *,
        session_manager: SessionManager[AsyncSession],
        repository: RuntimeWebGatewayRepository,
        agent_session_repository: AgentSessionRepository,
        workspace_user_repository: WorkspaceUserRepository,
        identity_lifetime: datetime.timedelta,
        desired_configuration: RuntimeWebDesiredConfiguration | None,
        chromium_min_version: int,
        chromium_max_version: int,
    ) -> None:
        self.session_manager = session_manager
        self.repository = repository
        self.agent_session_repository = agent_session_repository
        self.workspace_user_repository = workspace_user_repository
        self.identity_lifetime = identity_lifetime
        self.desired_configuration = desired_configuration
        self.chromium_min_version = chromium_min_version
        self.chromium_max_version = chromium_max_version

    async def synchronize_configuration(
        self,
        desired: RuntimeWebDesiredConfiguration,
    ) -> int:
        """Install one monotonic Gateway authentication configuration."""
        async with self.session_manager() as session:
            return await self.repository.synchronize_configuration(
                session,
                desired=desired,
            )

    async def issue_shared_identity(
        self,
        *,
        user_id: str,
        auth_session_id: str,
        browser_profile: str,
        now: datetime.datetime,
    ) -> RuntimeWebIssuedSecret:
        """Mint one shared-mode identity for a trusted Main Web response."""
        await self._ensure_configuration()
        self._validate_browser_profile(browser_profile)
        secret = _secret()
        expires_at = now + self.identity_lifetime
        async with self.session_manager() as session:
            await self.repository.create_identity(
                session,
                secret_hash=_hash(secret),
                user_id=user_id,
                auth_session_id=auth_session_id,
                browser_profile=browser_profile,
                issued_at=now,
                expires_at=expires_at,
            )
        return RuntimeWebIssuedSecret(secret=secret, expires_at=expires_at)

    async def authenticate(
        self,
        *,
        secret: str,
        browser_profile: str,
        now: datetime.datetime,
    ) -> RuntimeWebGatewayIdentity | None:
        """Validate one browser-protected identity cookie."""
        async with self.session_manager() as session:
            return await self.repository.authenticate_identity(
                session,
                secret_hash=_hash(secret),
                browser_profile=browser_profile,
                now=now,
            )

    async def revoke(
        self,
        *,
        secret: str,
        user_id: str,
        auth_session_id: str,
        now: datetime.datetime,
    ) -> bool:
        """Revoke one identity during trusted logout."""
        async with self.session_manager() as session:
            return await self.repository.revoke_identity(
                session,
                secret_hash=_hash(secret),
                user_id=user_id,
                auth_session_id=auth_session_id,
                revoked_at=now,
            )

    async def initiate_separate_domain(
        self,
        *,
        user_id: str,
        auth_session_id: str,
        endpoint_id: str,
        now: datetime.datetime,
    ) -> RuntimeWebIssuedBinding:
        """Create one short-lived Main-origin browser binding."""
        await self._ensure_configuration()
        initiation_id = secrets.token_hex(16)
        main_secret = _secret()
        async with self.session_manager() as session:
            endpoint = await self.repository.get_endpoint_by_id(
                session,
                endpoint_id=endpoint_id,
            )
            if endpoint is None:
                raise RuntimeWebRepositoryConflict(
                    "Runtime Web endpoint is unavailable"
                )
            agent_session = await self.agent_session_repository.get_by_id(
                session,
                endpoint.agent_session_id,
            )
            if agent_session is None:
                raise RuntimeWebRepositoryConflict(
                    "Runtime Web endpoint is unavailable"
                )
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
                raise RuntimeWebRepositoryConflict(
                    "Runtime Web endpoint is unavailable"
                )
            return await self.repository.create_binding(
                session,
                initiation_id=initiation_id,
                main_binding_hash=_hash(main_secret),
                user_id=user_id,
                auth_session_id=auth_session_id,
                endpoint_id=endpoint_id,
                expires_at=now + _BINDING_LIFETIME,
                now=now,
                main_binding_secret=main_secret,
            )

    async def bind_broker(
        self,
        *,
        initiation_id: str,
        now: datetime.datetime,
    ) -> RuntimeWebBrokerBinding:
        """Create a host-only broker binding for the initiation."""
        await self._ensure_configuration()
        broker_secret = _secret()
        async with self.session_manager() as session:
            return await self.repository.bind_broker(
                session,
                initiation_id=initiation_id,
                broker_binding_hash=_hash(broker_secret),
                broker_binding_secret=broker_secret,
                now=now,
            )

    async def mark_broker_bound(
        self,
        *,
        initiation_id: str,
        main_binding_secret: str,
        user_id: str,
        auth_session_id: str,
        now: datetime.datetime,
    ) -> None:
        """Settle the broker callback under Main binding and auth Session proof."""
        await self._ensure_configuration()
        async with self.session_manager() as session:
            await self.repository.mark_broker_bound(
                session,
                initiation_id=initiation_id,
                main_binding_hash=_hash(main_binding_secret),
                user_id=user_id,
                auth_session_id=auth_session_id,
                now=now,
            )

    async def issue_ticket(
        self,
        *,
        initiation_id: str,
        main_binding_secret: str,
        user_id: str,
        auth_session_id: str,
        now: datetime.datetime,
    ) -> RuntimeWebIssuedTicket:
        """Issue a one-use POST-body ticket after the broker callback."""
        await self._ensure_configuration()
        ticket = _secret()
        async with self.session_manager() as session:
            return await self.repository.issue_ticket(
                session,
                initiation_id=initiation_id,
                main_binding_hash=_hash(main_binding_secret),
                user_id=user_id,
                auth_session_id=auth_session_id,
                ticket_hash=_hash(ticket),
                ticket_secret=ticket,
                issued_at=now,
                expires_at=now + _TICKET_LIFETIME,
            )

    async def redeem_ticket(
        self,
        *,
        ticket_secret: str,
        broker_binding_secret: str,
        browser_profile: str,
        now: datetime.datetime,
    ) -> RuntimeWebRedeemedIdentity:
        """Consume a ticket once and establish the common identity."""
        await self._ensure_configuration()
        self._validate_browser_profile(browser_profile)
        identity = _secret()
        expires_at = now + self.identity_lifetime
        async with self.session_manager() as session:
            return await self.repository.redeem_ticket(
                session,
                ticket_hash=_hash(ticket_secret),
                broker_binding_hash=_hash(broker_binding_secret),
                identity_hash=_hash(identity),
                identity_secret=identity,
                browser_profile=browser_profile,
                identity_expires_at=expires_at,
                now=now,
            )

    async def _ensure_configuration(self) -> None:
        if self.desired_configuration is None:
            return
        await self.synchronize_configuration(self.desired_configuration)

    def _validate_browser_profile(self, browser_profile: str) -> None:
        prefix, separator, version_text = browser_profile.partition("-")
        if prefix != "chromium" or separator != "-" or not version_text.isdigit():
            raise RuntimeWebRepositoryConflict(
                "Runtime Web browser profile is unsupported"
            )
        version = int(version_text)
        if not self.chromium_min_version <= version <= self.chromium_max_version:
            raise RuntimeWebRepositoryConflict(
                "Runtime Web browser profile is unsupported"
            )


def _secret() -> str:
    return secrets.token_urlsafe(32)


def _hash(secret: str) -> str:
    return hashlib.sha256(secret.encode()).hexdigest()
