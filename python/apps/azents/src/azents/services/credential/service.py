"""Credential service."""

import dataclasses
from typing import Annotated

from fastapi import Depends

from azents.repos.credential_read_operations import CredentialReadOperationRepository
from azents.services.credential.data import (
    CredentialProjection,
    CredentialRemoveCheck,
    CredentialSummary,
    CredentialType,
    CredentialUnavailableReason,
    LoginCredentialProjection,
)
from azents.services.credential.providers import (
    CredentialProvider,
    EmailCredentialProvider,
    get_credential_providers,
)


@dataclasses.dataclass
class CredentialService:
    """Service that combines Credential provider results."""

    repository: Annotated[
        CredentialReadOperationRepository, Depends(CredentialReadOperationRepository)
    ]
    providers: Annotated[list[CredentialProvider], Depends(get_credential_providers)]

    async def get_user_credentials(
        self,
        *,
        user_id: str,
    ) -> list[CredentialSummary] | None:
        """Return User credential summary list."""
        providers = tuple(self.providers)
        snapshot = await self.repository.read_user_snapshot(
            user_id=user_id, kinds=tuple(provider.read_kind for provider in providers)
        )
        if snapshot is None:
            return None
        summaries: list[CredentialSummary] = []
        for provider, fact in zip(providers, snapshot.facts, strict=True):
            if fact.kind is not provider.read_kind:
                raise ValueError("Credential read fact kind does not match provider.")
            summaries.append(await provider.get_user_summary(fact=fact))
        return self._apply_remove_invariants(summaries)

    async def get_login_projection(self, *, email: str) -> LoginCredentialProjection:
        """Return Public login methods projection."""
        providers = tuple(self.providers)
        snapshot = await self.repository.read_login_snapshot(
            email=email, kinds=tuple(provider.read_kind for provider in providers)
        )
        summaries: list[CredentialSummary] = []
        for provider, fact in zip(providers, snapshot.facts, strict=True):
            if fact.kind is not provider.read_kind:
                raise ValueError("Credential read fact kind does not match provider.")
            summaries.append(await provider.get_login_summary(fact=fact))
        by_type = {summary.type: summary for summary in summaries}
        password = by_type.get(CredentialType.PASSWORD)
        return LoginCredentialProjection(
            has_password=password.valid if password is not None else False,
            email_available=self._email_flow_available(),
        )

    async def get_security_projection(
        self,
        *,
        user_id: str,
    ) -> list[CredentialProjection] | None:
        """Return credential projection for Security API."""
        summaries = await self.get_user_credentials(user_id=user_id)
        if summaries is None:
            return None
        return [
            CredentialProjection(
                type=summary.type,
                configured=summary.configured,
                valid=summary.valid,
                enabled=summary.valid,
                can_login=summary.can_login,
                can_elevate=summary.can_elevate,
                can_remove=summary.can_remove,
                unavailable_reason=summary.unavailable_reason,
            )
            for summary in summaries
        ]

    async def get_elevation_projection(
        self,
        *,
        user_id: str,
    ) -> list[CredentialProjection] | None:
        """Return credential projection for Elevation API."""
        summaries = await self.get_user_credentials(user_id=user_id)
        if summaries is None:
            return None
        return [
            CredentialProjection(
                type=summary.type,
                configured=summary.configured,
                valid=summary.valid,
                enabled=summary.can_elevate,
                can_login=summary.can_login,
                can_elevate=summary.can_elevate,
                can_remove=summary.can_remove,
                unavailable_reason=summary.unavailable_reason,
            )
            for summary in summaries
        ]

    async def check_remove_allowed(
        self,
        *,
        user_id: str,
        credential_type: CredentialType,
    ) -> CredentialRemoveCheck | None:
        """Return Credential removability."""
        summaries = await self.get_user_credentials(user_id=user_id)
        if summaries is None:
            return None
        target = next(
            (summary for summary in summaries if summary.type == credential_type),
            None,
        )
        if target is None or not target.configured:
            return CredentialRemoveCheck(
                allowed=False,
                reason=CredentialUnavailableReason.NOT_CONFIGURED,
            )
        if not target.can_remove:
            return CredentialRemoveCheck(
                allowed=False,
                reason=target.unavailable_reason,
            )
        return CredentialRemoveCheck(allowed=True, reason=None)

    def _email_flow_available(self) -> bool:
        """Return whether email OTP flow can be exposed in Public login."""
        return any(
            isinstance(provider, EmailCredentialProvider)
            and provider.email_service.configured
            for provider in self.providers
        )

    def _apply_remove_invariants(
        self,
        summaries: list[CredentialSummary],
    ) -> list[CredentialSummary]:
        """Return summary list reflecting removal invariant."""
        valid_count = sum(1 for summary in summaries if summary.valid)
        adjusted: list[CredentialSummary] = []
        for summary in summaries:
            can_remove = summary.configured and (not summary.valid or valid_count > 1)
            unavailable_reason = summary.unavailable_reason
            if summary.configured and summary.valid and valid_count <= 1:
                unavailable_reason = CredentialUnavailableReason.LAST_VALID_CREDENTIAL
            adjusted.append(
                summary.model_copy(
                    update={
                        "can_remove": can_remove,
                        "unavailable_reason": unavailable_reason,
                    }
                )
            )
        return adjusted
