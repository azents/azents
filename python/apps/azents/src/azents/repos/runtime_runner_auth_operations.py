"""Completed and composable Runner generation authority operations."""

import dataclasses

from azents.core.runtime_runner_credential import RuntimeRunnerCredential
from azents.rdb.session import SessionManager
from azents.rdb.session_capabilities import ReadSession, WriteSession
from azents.repos.agent_runtime import AgentRuntimeRepository


@dataclasses.dataclass(frozen=True)
class RuntimeRunnerAuthenticationOperationRepository:
    """Authenticate a signed Runner credential against current Runtime state."""

    session_manager: SessionManager[ReadSession]
    runtime_repository: AgentRuntimeRepository

    async def authorize_runner(self, credential: RuntimeRunnerCredential) -> bool:
        """Return whether a credential still matches durable Runtime state."""
        async with self.session_manager() as session:
            return await self.authorize_runner_in_transaction(session, credential)

    async def authorize_runner_in_transaction(
        self, session: ReadSession, credential: RuntimeRunnerCredential
    ) -> bool:
        """Describe retained Runner authority without a registration fence."""
        runtime = await self.runtime_repository.get_by_id(
            session, credential.runtime_id
        )
        return (
            runtime is not None
            and runtime.desired_generation == credential.desired_generation
        )

    async def fence_runner_registration_in_transaction(
        self, session: WriteSession, credential: RuntimeRunnerCredential
    ) -> bool:
        """Validate Runner authority inside a caller-owned transaction."""
        runtime = await self.runtime_repository.get_by_id_for_update(
            session, credential.runtime_id
        )
        return (
            runtime is not None
            and runtime.desired_generation == credential.desired_generation
        )
