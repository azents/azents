"""Account access service for completed admission snapshots."""

import dataclasses
from typing import Annotated

from fastapi import Depends

from azents.core.account_access import (
    ActiveAccountSubjectStatus,
    WorkspaceMembershipAccess,
)
from azents.repos.account_access import AccountAccessOperationRepository


@dataclasses.dataclass(frozen=True)
class AccountAccessService:
    """Expose completed reads without owning sessions or HTTP policy."""

    repository: Annotated[
        AccountAccessOperationRepository, Depends(AccountAccessOperationRepository)
    ]

    async def read_active_subject(
        self, *, user_id: str, session_id: str
    ) -> ActiveAccountSubjectStatus:
        """Return the current exact User and authentication Session status."""
        return await self.repository.read_active_subject(
            user_id=user_id, session_id=session_id
        )

    async def read_workspace_membership(
        self, *, handle: str, user_id: str
    ) -> WorkspaceMembershipAccess:
        """Return detached current membership for core permission projection."""
        return await self.repository.read_workspace_membership(
            handle=handle, user_id=user_id
        )
