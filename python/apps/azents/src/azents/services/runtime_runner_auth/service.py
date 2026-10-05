"""Runner authentication over completed generation authority operations."""

import dataclasses

from azents.core.runtime_runner_credential import (
    RuntimeRunnerCredential,
    RuntimeRunnerCredentialInvalid,
    RuntimeRunnerCredentialVerifier,
)
from azents.repos.runtime_runner_auth_operations import (
    RuntimeRunnerAuthenticationOperationRepository,
)


@dataclasses.dataclass(frozen=True)
class RuntimeRunnerAuthenticationService:
    """Authenticate a signed Runner credential against current Runtime state."""

    operations: RuntimeRunnerAuthenticationOperationRepository
    verifier: RuntimeRunnerCredentialVerifier

    async def authenticate_runner(self, secret: str) -> RuntimeRunnerCredential:
        """Verify token claims and bind them to the current Runtime generation."""
        credential = self.verifier.verify(secret)
        if not await self.authorize_runner(credential):
            raise RuntimeRunnerCredentialInvalid(
                "Runtime Runner credential is not bound to the current Runtime"
            )
        return credential

    async def authorize_runner(self, credential: RuntimeRunnerCredential) -> bool:
        """Return whether a credential still matches durable Runtime state."""
        return await self.operations.authorize_runner(credential)
