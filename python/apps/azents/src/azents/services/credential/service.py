"""Credential service."""

import dataclasses
from typing import Annotated

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from azents.rdb.deps import get_session_manager
from azents.rdb.session import SessionManager
from azents.repos.user import UserRepository
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

    session_manager: Annotated[
        SessionManager[AsyncSession], Depends(get_session_manager)
    ]
    providers: Annotated[list[CredentialProvider], Depends(get_credential_providers)]
    user_repo: Annotated[UserRepository, Depends()]

    async def get_user_credentials(
        self,
        *,
        user_id: str,
    ) -> list[CredentialSummary] | None:
        """Return User credential summary list."""
        async with self.session_manager() as session:
            user = await self.user_repo.get(session, user_id)
            if user is None:
                return None
            summaries = [
                await provider.get_user_summary(session, user_id=user_id)
                for provider in self.providers
            ]
        return self._apply_remove_invariants(summaries)

    async def get_login_projection(self, *, email: str) -> LoginCredentialProjection:
        """Return Public login methods projection."""
        async with self.session_manager() as session:
            summaries = [
                await provider.get_login_summary(session, email=email)
                for provider in self.providers
            ]
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
