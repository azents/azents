"""Completed Runtime reconciliation reads and separate marker/timeout mutations."""

import dataclasses
from datetime import timedelta
from typing import Annotated

from fastapi import Depends

from azents.core.enums import RuntimeDesiredState, RuntimeProviderObservedState
from azents.core.runtime_profile import RuntimeConfigurationStateStatus
from azents.rdb.deps import get_session_manager
from azents.rdb.session import SessionManager
from azents.rdb.session_capabilities import WriteSession
from azents.repos.agent_runtime import AgentRuntimeRepository
from azents.repos.agent_runtime.data import AgentRuntime
from azents.repos.runtime_profile.data import RuntimeConfigurationState
from azents.repos.runtime_profile.repository import RuntimeProfileRepository
from azents.repos.runtime_reconciliation_data import (
    RuntimeObserveRepairInput,
    RuntimeReconciliationCandidates,
    RuntimeReconciliationTimeouts,
)


@dataclasses.dataclass(frozen=True)
class RuntimeReconciliationOperationRepository:
    """Own the five original reconciliation scopes without dispatch machinery."""

    session_manager: Annotated[
        SessionManager[WriteSession], Depends(get_session_manager)
    ]
    runtime_repository: Annotated[
        AgentRuntimeRepository, Depends(AgentRuntimeRepository)
    ]
    profile_repository: Annotated[
        RuntimeProfileRepository, Depends(RuntimeProfileRepository)
    ]

    async def collect_candidates(
        self, *, limit: int, retry_delay: timedelta, observe_interval: timedelta
    ) -> RuntimeReconciliationCandidates:
        """Select the three ordered hint lists together before any external work."""
        async with self.session_manager() as session:
            lifecycle = (
                await self.runtime_repository.find_lifecycle_dispatch_candidates(
                    session, limit=limit, retry_delay=retry_delay
                )
            )
            observe = await self.runtime_repository.find_provider_observe_candidates(
                session, limit=limit, observe_interval=observe_interval
            )
            adoption = (
                await self.runtime_repository.find_configuration_adoption_candidates(
                    session, limit=limit
                )
            )
            return RuntimeReconciliationCandidates(
                lifecycle=tuple(lifecycle),
                observe=tuple(observe),
                configuration_adoption=tuple(adoption),
            )

    async def prepare_periodic_observation(self, runtime: AgentRuntime) -> bool:
        """Commit the original profile gate and observe marker before dispatch."""
        async with self.session_manager() as session:
            state = await self.profile_repository.get_configuration_state(
                session, runtime_id=runtime.id
            )
            if (
                runtime.desired_state is RuntimeDesiredState.RUNNING
                and runtime.provider_observed_state
                is RuntimeProviderObservedState.RUNNING
                and state is not None
                and state.desired.status is RuntimeConfigurationStateStatus.READY
                and state.applied is not None
                and state.desired.sequence != state.applied.sequence
                and state.desired.provider_acknowledged_at is not None
                and state.desired.provider_reported_digest == state.desired.digest
            ):
                return False
            await self.runtime_repository.mark_provider_observe_requested(
                session, runtime.id
            )
        return True

    async def load_adoption_state(
        self, *, runtime_id: str
    ) -> RuntimeConfigurationState | None:
        """Finish the profile read before the application's pure impact mapping."""
        async with self.session_manager() as session:
            return await self.profile_repository.get_configuration_state(
                session, runtime_id=runtime_id
            )

    async def load_observe_repair_target(
        self, input: RuntimeObserveRepairInput
    ) -> AgentRuntime | None:
        """Complete the exact current Runtime/Provider/configuration evidence read."""
        async with self.session_manager() as session:
            runtime = await self.runtime_repository.get_by_id(session, input.runtime_id)
            if (
                runtime is None
                or runtime.runtime_provider_id != input.provider_id
                or runtime.runtime_provider_resource_id is None
                or runtime.desired_state is not RuntimeDesiredState.RUNNING
                or runtime.provider_observed_state
                is not RuntimeProviderObservedState.RUNNING
                or runtime.provider_generation != input.provider_generation
                or runtime.provider_observed_generation
                != input.observed_desired_generation
                or runtime.desired_generation != input.observed_desired_generation
            ):
                return None
            state = await self.profile_repository.get_configuration_state(
                session, runtime_id=runtime.id
            )
            if (
                state is None
                or state.applied is None
                or state.desired.status is not RuntimeConfigurationStateStatus.READY
                or state.desired.sequence != state.applied.sequence
                or state.desired.sequence
                != input.runtime_configuration.configuration_sequence
            ):
                return None
            matches = (
                await self.profile_repository.configuration_evidence_matches_current(
                    session,
                    runtime_id=runtime.id,
                    provider_id=runtime.runtime_provider_resource_id,
                    evidence=input.runtime_configuration,
                )
            )
            if not matches:
                return None
            return runtime

    async def mark_start_timeouts(
        self, *, stale_threshold: timedelta, limit: int
    ) -> RuntimeReconciliationTimeouts:
        """Complete timeout mutation separately, after refresh/dispatch attempts."""
        async with self.session_manager() as session:
            timed_out = await self.runtime_repository.mark_start_timeouts(
                session, stale_threshold=stale_threshold, limit=limit
            )
        return RuntimeReconciliationTimeouts(count=len(timed_out))
