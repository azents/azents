"""Runtime Runner credential authentication service."""

import dataclasses

from azents.core.runtime_runner_credential import (
    RuntimeRunnerCredential,
    RuntimeRunnerCredentialInvalid,
    RuntimeRunnerCredentialVerifier,
)
from azents.rdb.session import SessionManager
from azents.rdb.session_capabilities import ReadSession, WriteSession
from azents.repos.agent_runtime import AgentRuntimeRepository


@dataclasses.dataclass(frozen=True)
class RuntimeRunnerAuthenticationService:
    """Authenticate a signed Runner credential against current Runtime state."""

    session_manager: SessionManager[WriteSession]
    runtime_repository: AgentRuntimeRepository
    verifier: RuntimeRunnerCredentialVerifier

    async def authenticate_runner(self, secret: str) -> RuntimeRunnerCredential:
        """Verify token claims and bind them to the current Runtime generation."""
        credential = self.verifier.verify(secret)
        if not await self.authorize_runner(credential):
            raise RuntimeRunnerCredentialInvalid(
                "Runtime Runner credential is not bound to the current Runtime"
            )
        return credential

    async def authorize_runner(
        self,
        credential: RuntimeRunnerCredential,
    ) -> bool:
        """Return whether a credential still matches durable Runtime state."""
        async with self.session_manager() as session:
            return await self.authorize_runner_in_transaction(session, credential)

    async def authorize_runner_in_transaction(
        self,
        session: ReadSession,
        credential: RuntimeRunnerCredential,
    ) -> bool:
        """Describe retained Runner authority without a registration fence."""
        runtime = await self.runtime_repository.get_by_id(
            session,
            credential.runtime_id,
        )
        return runtime is not None and runtime.desired_generation == (
            credential.desired_generation
        )

    async def fence_runner_registration_in_transaction(
        self,
        session: WriteSession,
        credential: RuntimeRunnerCredential,
    ) -> bool:
        """Exclude Runtime replacement through actual connection acceptance."""
        runtime = await self.runtime_repository.get_by_id_for_update(
            session,
            credential.runtime_id,
        )
        return runtime is not None and runtime.desired_generation == (
            credential.desired_generation
        )
