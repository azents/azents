"""Provider-neutral System Settings application orchestration."""

import dataclasses
from collections.abc import Awaitable, Callable
from typing import Annotated

from fastapi import Depends

from azents.core.system_setting import (
    ResolvedSystemSetting,
    SystemSettingCandidateExpired,
    SystemSettingSection,
)
from azents.core.system_setting_data import (
    CurrentSystemSettingHealth,
    StoredSystemSettingCandidate,
    SystemSettingActivated,
    SystemSettingCandidateValidationResult,
    SystemSettingCandidateValidationSnapshot,
    SystemSettingExpiryCommitted,
    SystemSettingHealthResult,
    SystemSettingMutation,
    SystemSettingMutationResult,
    SystemSettingState,
)
from azents.repos.system_setting.operations import SystemSettingsRepository

SystemSettingCandidateValidator = Callable[
    [SystemSettingCandidateValidationSnapshot],
    Awaitable[SystemSettingCandidateValidationResult],
]


@dataclasses.dataclass(frozen=True)
class SystemSettingsService:
    """Sequence completed Section operations and external validation."""

    repository: Annotated[SystemSettingsRepository, Depends(SystemSettingsRepository)]

    async def resolve(self, section: SystemSettingSection) -> ResolvedSystemSetting:
        """Resolve the current effective Section."""
        return await self.repository.resolve(section)

    async def mutate(
        self, mutation: SystemSettingMutation
    ) -> SystemSettingMutationResult:
        """Apply one atomic Section mutation."""
        return await self.repository.mutate(mutation)

    async def get_candidate(
        self, section: SystemSettingSection
    ) -> StoredSystemSettingCandidate | None:
        """Read a non-expired candidate."""
        return await self.repository.get_candidate(section)

    async def get_state(self, section: SystemSettingSection) -> SystemSettingState:
        """Read the internal state for redacted domain projection."""
        return await self.repository.get_state(section)

    async def prepare_candidate_validation(
        self, section: SystemSettingSection, *, candidate_id: str | None
    ) -> SystemSettingCandidateValidationSnapshot:
        """Complete the candidate preparation before external validation."""
        result = await self.repository.prepare_candidate_validation(
            section, candidate_id=candidate_id
        )
        if isinstance(result, SystemSettingExpiryCommitted):
            raise SystemSettingCandidateExpired(
                section=result.section, candidate_id=result.candidate_id
            )
        return result

    async def validate_candidate(
        self,
        *,
        section: SystemSettingSection,
        candidate_id: str | None,
        validator: SystemSettingCandidateValidator,
    ) -> SystemSettingMutationResult:
        """Run external validation between completed database operations."""
        snapshot = await self.prepare_candidate_validation(
            section, candidate_id=candidate_id
        )
        result = await validator(snapshot)
        return await self._record_candidate_validation(snapshot=snapshot, result=result)

    async def _record_candidate_validation(
        self,
        *,
        snapshot: SystemSettingCandidateValidationSnapshot,
        result: SystemSettingCandidateValidationResult,
    ) -> SystemSettingMutationResult:
        output = await self.repository.record_candidate_validation(
            snapshot=snapshot, result=result
        )
        if isinstance(output, SystemSettingExpiryCommitted):
            raise SystemSettingCandidateExpired(
                section=output.section, candidate_id=output.candidate_id
            )
        return output

    async def confirm_candidate(
        self,
        *,
        section: SystemSettingSection,
        candidate_id: str,
        expected_version: int,
        confirmation_action: str,
        actor_user_id: str | None,
    ) -> SystemSettingActivated:
        """Confirm with concrete GitHub impact under the Section lock."""
        result = await self.repository.confirm_candidate(
            section=section,
            candidate_id=candidate_id,
            expected_version=expected_version,
            confirmation_action=confirmation_action,
            actor_user_id=actor_user_id,
        )
        if isinstance(result, SystemSettingExpiryCommitted):
            raise SystemSettingCandidateExpired(
                section=result.section, candidate_id=result.candidate_id
            )
        return result

    async def cancel_candidate(
        self,
        *,
        section: SystemSettingSection,
        candidate_id: str,
        actor_user_id: str | None,
    ) -> None:
        """Erase the candidate before reporting a committed expiry."""
        result = await self.repository.cancel_candidate(
            section=section, candidate_id=candidate_id, actor_user_id=actor_user_id
        )
        if isinstance(result, SystemSettingExpiryCommitted):
            raise SystemSettingCandidateExpired(
                section=result.section, candidate_id=result.candidate_id
            )

    async def get_current_health(
        self, section: SystemSettingSection
    ) -> CurrentSystemSettingHealth:
        """Read health matching the captured effective generation."""
        return await self.repository.get_current_health(section)

    async def record_health(
        self,
        *,
        section: SystemSettingSection,
        expected_generation: str,
        result: SystemSettingHealthResult,
        actor_user_id: str | None,
    ) -> CurrentSystemSettingHealth:
        """Persist health after rechecking current generation."""
        return await self.repository.record_health(
            section=section,
            expected_generation=expected_generation,
            result=result,
            actor_user_id=actor_user_id,
        )
