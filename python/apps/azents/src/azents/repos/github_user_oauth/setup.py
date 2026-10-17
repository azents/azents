"""Completed exact management and selected Platform installation admission."""

import dataclasses
from typing import Annotated

from fastapi import Depends

from azents.core.github_user_creation import (
    GitHubCreationSubject,
    GitHubPersonalCreationSubject,
)
from azents.core.github_user_oauth import GitHubUserErrorCode, GitHubUserOAuthError
from azents.repos.github_user_oauth.operations import GitHubUserOAuthOperationRepository
from azents.repos.toolkit_operations import ToolkitOperationsRepository
from azents.repos.toolkit_operations.data import PlatformToolkitAuthority


@dataclasses.dataclass(frozen=True)
class GitHubSetupRepository:
    """Reuse creation's current-user/App installation authority without publication."""

    operations: Annotated[GitHubUserOAuthOperationRepository, Depends()]
    toolkits: Annotated[ToolkitOperationsRepository, Depends()]

    async def authorize_platform(
        self,
        subject: GitHubCreationSubject,
        authority: PlatformToolkitAuthority,
    ) -> None:
        """Finish scope and target admission before external SDK operations begin."""
        if authority.user_id != subject.user_id:
            raise GitHubUserOAuthError(
                GitHubUserErrorCode.AUTHORITY,
                "Platform GitHub installation authority does not match this user.",
            )
        async with self.operations.session_manager() as session:
            if isinstance(subject, GitHubPersonalCreationSubject):
                await self.operations.authorize_personal_scope_in_session(
                    session,
                    user_id=subject.user_id,
                    session_id=subject.session_id,
                )
            else:
                await self.operations.authorize_scope_in_session(
                    session, **dataclasses.asdict(subject)
                )
            rejected = await self.toolkits.validate_platform_authority(
                session, authority
            )
            if rejected is not None:
                raise GitHubUserOAuthError(
                    GitHubUserErrorCode.AUTHORITY, rejected.detail
                )
