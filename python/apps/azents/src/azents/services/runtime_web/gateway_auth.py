"""Opaque Runtime Web Gateway orchestration over completed database operations."""

import datetime
import hashlib
import secrets

from azents.repos.runtime_web.gateway_auth_operations import (
    RuntimeWebGatewayAuthOperationsRepository,
)
from azents.repos.runtime_web.gateway_data import (
    RuntimeWebBrokerBinding,
    RuntimeWebDesiredConfiguration,
    RuntimeWebGatewayIdentity,
    RuntimeWebIssuedBinding,
    RuntimeWebIssuedSecret,
    RuntimeWebIssuedTicket,
    RuntimeWebRedeemedIdentity,
)

_BINDING_LIFETIME = datetime.timedelta(minutes=2)
_TICKET_LIFETIME = datetime.timedelta(seconds=30)


class RuntimeWebGatewayAuthService:
    """Generate opaque secrets and sequence completed repository operations."""

    def __init__(
        self,
        *,
        operations: RuntimeWebGatewayAuthOperationsRepository,
        identity_lifetime: datetime.timedelta,
        desired_configuration: RuntimeWebDesiredConfiguration | None,
    ) -> None:
        self.operations = operations
        self.identity_lifetime = identity_lifetime
        self.desired_configuration = desired_configuration

    async def synchronize_configuration(
        self,
        desired: RuntimeWebDesiredConfiguration,
    ) -> None:
        """Install the current Gateway authentication configuration."""
        await self.operations.synchronize_configuration(
            desired=desired,
        )

    async def issue_shared_identity(
        self,
        *,
        user_id: str,
        auth_session_id: str,
        now: datetime.datetime,
    ) -> RuntimeWebIssuedSecret:
        """Mint one shared-mode identity for a trusted Main Web response."""
        await self._ensure_configuration()
        secret = _secret()
        expires_at = now + self.identity_lifetime
        await self.operations.issue_shared_identity(
            user_id=user_id,
            auth_session_id=auth_session_id,
            now=now,
            secret_hash=_hash(secret),
            expires_at=expires_at,
        )
        return RuntimeWebIssuedSecret(secret=secret, expires_at=expires_at)

    async def authenticate(
        self,
        *,
        secret: str,
        now: datetime.datetime,
    ) -> RuntimeWebGatewayIdentity | None:
        """Validate one opaque identity cookie."""
        return await self.operations.authenticate(
            secret_hash=_hash(secret),
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
        return await self.operations.revoke(
            secret_hash=_hash(secret),
            user_id=user_id,
            auth_session_id=auth_session_id,
            now=now,
        )

    async def initiate_separate_domain(
        self,
        *,
        user_id: str,
        auth_session_id: str,
        service_id: str,
        now: datetime.datetime,
    ) -> RuntimeWebIssuedBinding:
        """Create one short-lived Main-origin browser binding."""
        await self._ensure_configuration()
        initiation_id = secrets.token_hex(16)
        main_secret = _secret()
        return await self.operations.initiate_separate_domain(
            user_id=user_id,
            auth_session_id=auth_session_id,
            service_id=service_id,
            now=now,
            initiation_id=initiation_id,
            main_binding_hash=_hash(main_secret),
            main_binding_secret=main_secret,
            expires_at=now + _BINDING_LIFETIME,
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
        return await self.operations.bind_broker(
            initiation_id=initiation_id,
            now=now,
            broker_binding_hash=_hash(broker_secret),
            broker_binding_secret=broker_secret,
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
        await self.operations.mark_broker_bound(
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
        return await self.operations.issue_ticket(
            initiation_id=initiation_id,
            main_binding_hash=_hash(main_binding_secret),
            user_id=user_id,
            auth_session_id=auth_session_id,
            now=now,
            ticket_hash=_hash(ticket),
            ticket_secret=ticket,
            expires_at=now + _TICKET_LIFETIME,
        )

    async def redeem_ticket(
        self,
        *,
        ticket_secret: str,
        broker_binding_secret: str,
        now: datetime.datetime,
    ) -> RuntimeWebRedeemedIdentity:
        """Consume a ticket once and establish the common identity."""
        await self._ensure_configuration()
        identity = _secret()
        expires_at = now + self.identity_lifetime
        return await self.operations.redeem_ticket(
            ticket_hash=_hash(ticket_secret),
            broker_binding_hash=_hash(broker_binding_secret),
            now=now,
            identity_hash=_hash(identity),
            identity_secret=identity,
            identity_expires_at=expires_at,
        )

    async def _ensure_configuration(self) -> None:
        if self.desired_configuration is None:
            return
        await self.synchronize_configuration(self.desired_configuration)


def _secret() -> str:
    return secrets.token_urlsafe(32)


def _hash(secret: str) -> str:
    return hashlib.sha256(secret.encode()).hexdigest()
