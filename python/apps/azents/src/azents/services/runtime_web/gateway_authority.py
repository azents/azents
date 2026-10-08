"""Current Agent-service and Runtime orchestration for Gateway admission."""

import enum
import hashlib

from azents_runtime_control.runtime_stream_session import StreamProtocol

from azents.repos.runtime_web.data import RuntimeWebServiceRecord
from azents.repos.runtime_web.gateway_authority_operations import (
    RuntimeWebGatewayAuthorityOperationsRepository,
    RuntimeWebGatewayOperationRejected,
)
from azents.repos.runtime_web.gateway_data import RuntimeWebGatewayAuthority


class RuntimeWebGatewayAuthorityCode(enum.StrEnum):
    """Bounded Gateway errors emitted before application response bytes."""

    UNAUTHENTICATED = "unauthenticated"
    NOT_FOUND = "not_found"
    GONE = "gone"
    RUNTIME_UNAVAILABLE = "runtime_unavailable"


class RuntimeWebGatewayAuthorityError(ValueError):
    """Current durable authority rejected Gateway admission."""

    def __init__(self, code: RuntimeWebGatewayAuthorityCode) -> None:
        super().__init__(code.value)
        self.code = code


class RuntimeWebGatewayAuthorityService:
    """Resolve admission through a completed database-only authority operation."""

    def __init__(
        self, *, operations: RuntimeWebGatewayAuthorityOperationsRepository
    ) -> None:
        self.operations = operations

    async def authorize(
        self,
        *,
        hostname_key: str,
        identity_secret: str,
        protocol: StreamProtocol,
    ) -> RuntimeWebGatewayAuthority:
        """Authorize identity, Agent access, exposure, and current Runtime."""
        del protocol
        try:
            return await self.operations.authorize(
                hostname_key=hostname_key,
                identity_hash=hashlib.sha256(identity_secret.encode()).hexdigest(),
            )
        except RuntimeWebGatewayOperationRejected as error:
            raise RuntimeWebGatewayAuthorityError(
                RuntimeWebGatewayAuthorityCode(error.code.value)
            ) from error

    async def resolve_service(
        self,
        *,
        hostname_key: str,
    ) -> RuntimeWebServiceRecord | None:
        """Resolve a public host label without disclosing private authority."""
        return await self.operations.resolve_service(
            hostname_key=hostname_key,
        )

    async def resolve_service_by_id(
        self,
        *,
        service_id: str,
    ) -> RuntimeWebServiceRecord | None:
        """Resolve the service destination of a consumed auth ticket."""
        return await self.operations.resolve_service_by_id(
            service_id=service_id,
        )

    async def identity_and_access_current(
        self,
        *,
        authority: RuntimeWebGatewayAuthority,
    ) -> bool:
        """Revalidate identity, user access, service state, and Runtime generation."""
        return await self.operations.identity_and_access_current(
            authority=authority,
        )
