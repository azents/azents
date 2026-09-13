"""PostgreSQL authority for Runtime Web Gateway authentication."""

import datetime

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from azents.rdb.models.runtime_web import (
    RDBRuntimeWebAuthBinding,
    RDBRuntimeWebAuthConfiguration,
    RDBRuntimeWebAuthTicket,
    RDBRuntimeWebEndpoint,
    RDBRuntimeWebGatewayAdmissionLease,
    RDBRuntimeWebGatewayIdentity,
    RuntimeWebAuthMode,
)
from azents.rdb.models.session import RDBSession
from azents.rdb.models.user import RDBUser
from azents.repos.runtime_web.gateway_data import (
    RuntimeWebAdmissionLimits,
    RuntimeWebAuthBinding,
    RuntimeWebBrokerBinding,
    RuntimeWebDesiredConfiguration,
    RuntimeWebGatewayIdentity,
    RuntimeWebIssuedBinding,
    RuntimeWebIssuedTicket,
    RuntimeWebRedeemedIdentity,
)
from azents.repos.runtime_web.repository import RuntimeWebRepositoryConflict


class RuntimeWebGatewayCapacityExceeded(ValueError):
    """A shared endpoint, user, or Agent admission quota is exhausted."""

    def __init__(self, scope: str) -> None:
        super().__init__(scope)
        self.scope = scope


class RuntimeWebGatewayRepository:
    """Own all Runtime Web identity, binding, ticket, and epoch transactions."""

    async def synchronize_configuration(
        self,
        session: AsyncSession,
        *,
        desired: RuntimeWebDesiredConfiguration,
    ) -> int:
        """Install a monotonic configuration and return its active epoch."""
        configuration = await session.scalar(
            sa.select(RDBRuntimeWebAuthConfiguration)
            .where(RDBRuntimeWebAuthConfiguration.id == 1)
            .with_for_update()
        )
        if configuration is None:
            configuration = RDBRuntimeWebAuthConfiguration(
                enabled=desired.enabled,
                mode=desired.mode,
                configuration_version=desired.configuration_version,
                fingerprint=desired.fingerprint,
                active_epoch=1,
                duration_configuration_revision=1,
                active_duration_seconds=desired.active_duration_seconds,
            )
            session.add(configuration)
            await session.flush()
            return configuration.active_epoch
        if desired.configuration_version < configuration.configuration_version:
            raise RuntimeWebRepositoryConflict(
                "Runtime Web configuration version regressed"
            )
        if desired.configuration_version == configuration.configuration_version:
            if (
                desired.fingerprint != configuration.fingerprint
                or desired.enabled != configuration.enabled
                or desired.mode is not configuration.mode
                or desired.active_duration_seconds
                != configuration.active_duration_seconds
            ):
                raise RuntimeWebRepositoryConflict(
                    "Runtime Web configuration changed without a version advance"
                )
            return configuration.active_epoch
        security_changed = (
            desired.fingerprint != configuration.fingerprint
            or desired.enabled != configuration.enabled
            or desired.mode is not configuration.mode
        )
        duration_changed = (
            desired.active_duration_seconds != configuration.active_duration_seconds
        )
        configuration.enabled = desired.enabled
        configuration.mode = desired.mode
        configuration.configuration_version = desired.configuration_version
        configuration.fingerprint = desired.fingerprint
        configuration.active_duration_seconds = desired.active_duration_seconds
        if security_changed:
            configuration.active_epoch += 1
        if duration_changed:
            configuration.duration_configuration_revision += 1
        await session.flush()
        return configuration.active_epoch

    async def create_identity(
        self,
        session: AsyncSession,
        *,
        secret_hash: str,
        user_id: str,
        auth_session_id: str,
        browser_profile: str,
        issued_at: datetime.datetime,
        expires_at: datetime.datetime,
    ) -> RuntimeWebGatewayIdentity:
        """Create one identity under the current enabled mode and epoch."""
        configuration = await self._locked_enabled_configuration(session)
        if configuration.mode is not RuntimeWebAuthMode.SHARED_COOKIE:
            raise RuntimeWebRepositoryConflict(
                "Runtime Web shared-cookie authentication is disabled"
            )
        await self._require_active_auth_session(
            session,
            user_id=user_id,
            auth_session_id=auth_session_id,
            now=issued_at,
        )
        rdb = RDBRuntimeWebGatewayIdentity(
            secret_hash=secret_hash,
            user_id=user_id,
            auth_session_id=auth_session_id,
            mode=configuration.mode,
            epoch=configuration.active_epoch,
            browser_profile=browser_profile,
            issued_at=issued_at,
            expires_at=expires_at,
        )
        session.add(rdb)
        await session.flush()
        return self._identity(rdb)

    async def authenticate_identity(
        self,
        session: AsyncSession,
        *,
        secret_hash: str,
        browser_profile: str,
        now: datetime.datetime,
    ) -> RuntimeWebGatewayIdentity | None:
        """Validate identity, auth Session, mode, epoch, profile, and deadlines."""
        row = await session.execute(
            sa.select(RDBRuntimeWebGatewayIdentity, RDBSession, RDBUser)
            .join(
                RDBSession,
                RDBSession.id == RDBRuntimeWebGatewayIdentity.auth_session_id,
            )
            .join(RDBUser, RDBUser.id == RDBRuntimeWebGatewayIdentity.user_id)
            .where(
                RDBRuntimeWebGatewayIdentity.secret_hash == secret_hash,
                RDBRuntimeWebGatewayIdentity.revoked_at.is_(None),
                RDBRuntimeWebGatewayIdentity.expires_at > now,
                RDBRuntimeWebGatewayIdentity.browser_profile == browser_profile,
                RDBSession.user_id == RDBRuntimeWebGatewayIdentity.user_id,
                RDBSession.revoked_at.is_(None),
                RDBSession.expires_at > now,
                RDBUser.access_disabled_at.is_(None),
            )
        )
        matched = row.one_or_none()
        if matched is None:
            return None
        identity, _auth_session, _user = matched._t
        configuration = await session.get(RDBRuntimeWebAuthConfiguration, 1)
        if (
            configuration is None
            or not configuration.enabled
            or identity.mode is not configuration.mode
            or identity.epoch != configuration.active_epoch
        ):
            return None
        return self._identity(identity)

    async def identity_authority_current(
        self,
        session: AsyncSession,
        *,
        identity_id: str,
        user_id: str,
        auth_session_id: str,
        browser_profile: str,
        epoch: int,
        now: datetime.datetime,
    ) -> bool:
        """Revalidate an admitted identity without retaining its opaque secret."""
        current = await session.scalar(
            sa.select(sa.literal(True))
            .select_from(RDBRuntimeWebGatewayIdentity)
            .join(
                RDBSession,
                RDBSession.id == RDBRuntimeWebGatewayIdentity.auth_session_id,
            )
            .join(RDBUser, RDBUser.id == RDBRuntimeWebGatewayIdentity.user_id)
            .join(
                RDBRuntimeWebAuthConfiguration,
                RDBRuntimeWebAuthConfiguration.id == 1,
            )
            .where(
                RDBRuntimeWebGatewayIdentity.id == identity_id,
                RDBRuntimeWebGatewayIdentity.user_id == user_id,
                RDBRuntimeWebGatewayIdentity.auth_session_id == auth_session_id,
                RDBRuntimeWebGatewayIdentity.browser_profile == browser_profile,
                RDBRuntimeWebGatewayIdentity.epoch == epoch,
                RDBRuntimeWebGatewayIdentity.revoked_at.is_(None),
                RDBRuntimeWebGatewayIdentity.expires_at > now,
                RDBSession.user_id == user_id,
                RDBSession.revoked_at.is_(None),
                RDBSession.expires_at > now,
                RDBUser.access_disabled_at.is_(None),
                RDBRuntimeWebAuthConfiguration.enabled.is_(True),
                RDBRuntimeWebAuthConfiguration.active_epoch == epoch,
                RDBRuntimeWebAuthConfiguration.mode
                == RDBRuntimeWebGatewayIdentity.mode,
            )
        )
        return current is True

    async def revoke_identity(
        self,
        session: AsyncSession,
        *,
        secret_hash: str,
        user_id: str,
        auth_session_id: str,
        revoked_at: datetime.datetime,
    ) -> bool:
        """Revoke the exact opaque identity when present."""
        identity_id = await session.scalar(
            sa.update(RDBRuntimeWebGatewayIdentity)
            .where(
                RDBRuntimeWebGatewayIdentity.secret_hash == secret_hash,
                RDBRuntimeWebGatewayIdentity.user_id == user_id,
                RDBRuntimeWebGatewayIdentity.auth_session_id == auth_session_id,
                RDBRuntimeWebGatewayIdentity.revoked_at.is_(None),
            )
            .values(revoked_at=revoked_at)
            .returning(RDBRuntimeWebGatewayIdentity.id)
        )
        return identity_id is not None

    async def create_binding(
        self,
        session: AsyncSession,
        *,
        initiation_id: str,
        main_binding_hash: str,
        user_id: str,
        auth_session_id: str,
        endpoint_id: str,
        expires_at: datetime.datetime,
        now: datetime.datetime,
        main_binding_secret: str,
    ) -> RuntimeWebIssuedBinding:
        """Create a trusted Main-origin initiation for one endpoint."""
        configuration = await self._locked_enabled_configuration(session)
        if configuration.mode is not RuntimeWebAuthMode.SEPARATE_DOMAIN:
            raise RuntimeWebRepositoryConflict(
                "Runtime Web separate-domain authentication is disabled"
            )
        await self._require_active_auth_session(
            session,
            user_id=user_id,
            auth_session_id=auth_session_id,
            now=now,
        )
        endpoint = await session.get(RDBRuntimeWebEndpoint, endpoint_id)
        if endpoint is None:
            raise RuntimeWebRepositoryConflict("Runtime Web endpoint not found")
        rdb = RDBRuntimeWebAuthBinding(
            initiation_id=initiation_id,
            main_binding_hash=main_binding_hash,
            user_id=user_id,
            auth_session_id=auth_session_id,
            endpoint_id=endpoint_id,
            epoch=configuration.active_epoch,
            expires_at=expires_at,
        )
        session.add(rdb)
        await session.flush()
        return RuntimeWebIssuedBinding(
            binding=self._binding(rdb),
            main_binding_secret=main_binding_secret,
        )

    async def bind_broker(
        self,
        session: AsyncSession,
        *,
        initiation_id: str,
        broker_binding_hash: str,
        broker_binding_secret: str,
        now: datetime.datetime,
    ) -> RuntimeWebBrokerBinding:
        """Attach one broker-host binding secret exactly once."""
        binding = await session.scalar(
            sa.select(RDBRuntimeWebAuthBinding)
            .where(RDBRuntimeWebAuthBinding.initiation_id == initiation_id)
            .with_for_update()
        )
        if (
            binding is None
            or binding.expires_at <= now
            or binding.settled_at is not None
            or binding.broker_binding_hash is not None
        ):
            raise RuntimeWebRepositoryConflict("Runtime Web binding is unavailable")
        binding.broker_binding_hash = broker_binding_hash
        await session.flush()
        return RuntimeWebBrokerBinding(
            binding=self._binding(binding),
            broker_binding_secret=broker_binding_secret,
        )

    async def mark_broker_bound(
        self,
        session: AsyncSession,
        *,
        initiation_id: str,
        main_binding_hash: str,
        user_id: str,
        auth_session_id: str,
        now: datetime.datetime,
    ) -> RuntimeWebAuthBinding:
        """Accept the exact broker callback under Main-origin proof."""
        binding = await session.scalar(
            sa.select(RDBRuntimeWebAuthBinding)
            .where(
                RDBRuntimeWebAuthBinding.initiation_id == initiation_id,
                RDBRuntimeWebAuthBinding.main_binding_hash == main_binding_hash,
                RDBRuntimeWebAuthBinding.user_id == user_id,
                RDBRuntimeWebAuthBinding.auth_session_id == auth_session_id,
            )
            .with_for_update()
        )
        if (
            binding is None
            or binding.expires_at <= now
            or binding.settled_at is not None
            or binding.broker_binding_hash is None
        ):
            raise RuntimeWebRepositoryConflict("Runtime Web binding is unavailable")
        if binding.broker_bound_at is None:
            binding.broker_bound_at = now
            await session.flush()
        return self._binding(binding)

    async def issue_ticket(
        self,
        session: AsyncSession,
        *,
        initiation_id: str,
        main_binding_hash: str,
        user_id: str,
        auth_session_id: str,
        ticket_hash: str,
        ticket_secret: str,
        issued_at: datetime.datetime,
        expires_at: datetime.datetime,
    ) -> RuntimeWebIssuedTicket:
        """Issue one ticket only after the broker callback completed."""
        binding = await session.scalar(
            sa.select(RDBRuntimeWebAuthBinding)
            .where(
                RDBRuntimeWebAuthBinding.initiation_id == initiation_id,
                RDBRuntimeWebAuthBinding.main_binding_hash == main_binding_hash,
                RDBRuntimeWebAuthBinding.user_id == user_id,
                RDBRuntimeWebAuthBinding.auth_session_id == auth_session_id,
            )
            .with_for_update()
        )
        configuration = await self._locked_enabled_configuration(session)
        if (
            binding is None
            or binding.expires_at <= issued_at
            or binding.settled_at is not None
            or binding.broker_bound_at is None
            or binding.broker_binding_hash is None
            or binding.epoch != configuration.active_epoch
        ):
            raise RuntimeWebRepositoryConflict("Runtime Web binding is unavailable")
        await self._require_active_auth_session(
            session,
            user_id=binding.user_id,
            auth_session_id=binding.auth_session_id,
            now=issued_at,
        )
        ticket = RDBRuntimeWebAuthTicket(
            binding_id=binding.id,
            secret_hash=ticket_hash,
            user_id=binding.user_id,
            auth_session_id=binding.auth_session_id,
            endpoint_id=binding.endpoint_id,
            epoch=binding.epoch,
            issued_at=issued_at,
            expires_at=expires_at,
        )
        session.add(ticket)
        await session.flush()
        return RuntimeWebIssuedTicket(
            ticket_secret=ticket_secret,
            endpoint_id=binding.endpoint_id,
            expires_at=expires_at,
        )

    async def redeem_ticket(
        self,
        session: AsyncSession,
        *,
        ticket_hash: str,
        broker_binding_hash: str,
        identity_hash: str,
        identity_secret: str,
        browser_profile: str,
        identity_expires_at: datetime.datetime,
        now: datetime.datetime,
    ) -> RuntimeWebRedeemedIdentity:
        """Atomically consume a broker-bound ticket and create the identity."""
        ticket = await session.scalar(
            sa.select(RDBRuntimeWebAuthTicket)
            .where(RDBRuntimeWebAuthTicket.secret_hash == ticket_hash)
            .with_for_update()
        )
        if ticket is None:
            raise RuntimeWebRepositoryConflict("Runtime Web ticket is unavailable")
        binding = await session.scalar(
            sa.select(RDBRuntimeWebAuthBinding)
            .where(
                RDBRuntimeWebAuthBinding.id == ticket.binding_id,
                RDBRuntimeWebAuthBinding.broker_binding_hash == broker_binding_hash,
            )
            .with_for_update()
        )
        configuration = await self._locked_enabled_configuration(session)
        if (
            binding is None
            or binding.settled_at is not None
            or binding.expires_at <= now
            or binding.broker_bound_at is None
            or ticket.consumed_at is not None
            or ticket.expires_at <= now
            or ticket.epoch != configuration.active_epoch
            or binding.epoch != configuration.active_epoch
            or ticket.endpoint_id != binding.endpoint_id
            or ticket.auth_session_id != binding.auth_session_id
            or ticket.user_id != binding.user_id
        ):
            raise RuntimeWebRepositoryConflict("Runtime Web ticket is unavailable")
        await self._require_active_auth_session(
            session,
            user_id=ticket.user_id,
            auth_session_id=ticket.auth_session_id,
            now=now,
        )
        identity = RDBRuntimeWebGatewayIdentity(
            secret_hash=identity_hash,
            user_id=ticket.user_id,
            auth_session_id=ticket.auth_session_id,
            mode=configuration.mode,
            epoch=configuration.active_epoch,
            browser_profile=browser_profile,
            issued_at=now,
            expires_at=identity_expires_at,
        )
        session.add(identity)
        ticket.consumed_at = now
        binding.settled_at = now
        await session.flush()
        return RuntimeWebRedeemedIdentity(
            secret=identity_secret,
            expires_at=identity_expires_at,
            endpoint_id=ticket.endpoint_id,
        )

    async def get_endpoint_by_hostname(
        self,
        session: AsyncSession,
        *,
        hostname_key: str,
    ) -> RDBRuntimeWebEndpoint | None:
        """Resolve the permanent random endpoint host label."""
        return await session.scalar(
            sa.select(RDBRuntimeWebEndpoint).where(
                RDBRuntimeWebEndpoint.hostname_key == hostname_key
            )
        )

    async def get_endpoint_by_id(
        self,
        session: AsyncSession,
        *,
        endpoint_id: str,
    ) -> RDBRuntimeWebEndpoint | None:
        """Resolve one stable endpoint by its opaque identifier."""
        return await session.get(RDBRuntimeWebEndpoint, endpoint_id)

    async def acquire_admission(
        self,
        session: AsyncSession,
        *,
        tunnel_id: str,
        endpoint_id: str,
        user_id: str,
        agent_id: str,
        websocket: bool,
        lease_expires_at: datetime.datetime,
        now: datetime.datetime,
        limits: RuntimeWebAdmissionLimits,
    ) -> str:
        """Acquire shared scope counts under deterministic transaction locks."""
        scope_keys = sorted(
            (
                f"runtime-web-admission:agent:{agent_id}:{websocket}",
                f"runtime-web-admission:endpoint:{endpoint_id}:{websocket}",
                f"runtime-web-admission:user:{user_id}:{websocket}",
            )
        )
        for scope_key in scope_keys:
            await session.execute(
                sa.text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))"),
                {"key": scope_key},
            )
        await session.execute(
            sa.delete(RDBRuntimeWebGatewayAdmissionLease).where(
                RDBRuntimeWebGatewayAdmissionLease.lease_expires_at <= now
            )
        )
        scopes = (
            (
                "endpoint",
                RDBRuntimeWebGatewayAdmissionLease.endpoint_id,
                endpoint_id,
                limits.endpoint,
            ),
            (
                "user",
                RDBRuntimeWebGatewayAdmissionLease.user_id,
                user_id,
                limits.user,
            ),
            (
                "agent",
                RDBRuntimeWebGatewayAdmissionLease.agent_id,
                agent_id,
                limits.agent,
            ),
        )
        for scope, column, subject_id, limit in scopes:
            count = await session.scalar(
                sa.select(sa.func.count(RDBRuntimeWebGatewayAdmissionLease.id)).where(
                    column == subject_id,
                    RDBRuntimeWebGatewayAdmissionLease.websocket == websocket,
                    RDBRuntimeWebGatewayAdmissionLease.lease_expires_at > now,
                )
            )
            if (count or 0) >= limit:
                raise RuntimeWebGatewayCapacityExceeded(scope)
        admission = RDBRuntimeWebGatewayAdmissionLease(
            tunnel_id=tunnel_id,
            endpoint_id=endpoint_id,
            user_id=user_id,
            agent_id=agent_id,
            websocket=websocket,
            lease_expires_at=lease_expires_at,
        )
        session.add(admission)
        await session.flush()
        return admission.id

    async def release_admission(
        self,
        session: AsyncSession,
        *,
        tunnel_id: str,
    ) -> None:
        """Release one exact Gateway-owned shared admission."""
        await session.execute(
            sa.delete(RDBRuntimeWebGatewayAdmissionLease).where(
                RDBRuntimeWebGatewayAdmissionLease.tunnel_id == tunnel_id
            )
        )

    async def _locked_enabled_configuration(
        self,
        session: AsyncSession,
    ) -> RDBRuntimeWebAuthConfiguration:
        configuration = await session.scalar(
            sa.select(RDBRuntimeWebAuthConfiguration)
            .where(RDBRuntimeWebAuthConfiguration.id == 1)
            .with_for_update()
        )
        if configuration is None or not configuration.enabled:
            raise RuntimeWebRepositoryConflict(
                "Runtime Web authentication is unavailable"
            )
        return configuration

    async def _require_active_auth_session(
        self,
        session: AsyncSession,
        *,
        user_id: str,
        auth_session_id: str,
        now: datetime.datetime,
    ) -> None:
        active = await session.scalar(
            sa.select(sa.literal(True))
            .select_from(RDBSession)
            .join(RDBUser, RDBUser.id == RDBSession.user_id)
            .where(
                RDBSession.id == auth_session_id,
                RDBSession.user_id == user_id,
                RDBSession.revoked_at.is_(None),
                RDBSession.expires_at > now,
                RDBUser.access_disabled_at.is_(None),
            )
        )
        if active is not True:
            raise RuntimeWebRepositoryConflict(
                "Runtime Web authentication Session is unavailable"
            )

    @staticmethod
    def _identity(
        identity: RDBRuntimeWebGatewayIdentity,
    ) -> RuntimeWebGatewayIdentity:
        return RuntimeWebGatewayIdentity(
            id=identity.id,
            user_id=identity.user_id,
            auth_session_id=identity.auth_session_id,
            mode=identity.mode,
            epoch=identity.epoch,
            browser_profile=identity.browser_profile,
            issued_at=identity.issued_at,
            expires_at=identity.expires_at,
        )

    @staticmethod
    def _binding(binding: RDBRuntimeWebAuthBinding) -> RuntimeWebAuthBinding:
        return RuntimeWebAuthBinding(
            id=binding.id,
            initiation_id=binding.initiation_id,
            user_id=binding.user_id,
            auth_session_id=binding.auth_session_id,
            endpoint_id=binding.endpoint_id,
            epoch=binding.epoch,
            expires_at=binding.expires_at,
            broker_bound=binding.broker_bound_at is not None,
            settled=binding.settled_at is not None,
        )
