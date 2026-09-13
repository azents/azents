"""External account linking service."""

import datetime
from typing import Annotated

from fastapi import Depends

from azents.core.external_account_link import (
    ExternalAccountLinkView,
    ExternalAccountNativeLinkState,
    VerifiedExternalAccountActor,
)
from azents.repos.external_account_link import ExternalAccountLinkRepository


class ExternalAccountLinkService:
    """Sequence completed external account link repository operations."""

    def __init__(
        self,
        repository: Annotated[
            ExternalAccountLinkRepository,
            Depends(ExternalAccountLinkRepository),
        ],
    ) -> None:
        self.repository = repository

    async def get_native_link_state(
        self,
        *,
        actor: VerifiedExternalAccountActor,
        now: datetime.datetime,
    ) -> ExternalAccountNativeLinkState:
        """Resolve current actor-private link state."""
        return await self.repository.get_native_link_state(actor=actor, now=now)

    async def list_links(
        self,
        *,
        user_id: str,
        now: datetime.datetime,
    ) -> list[ExternalAccountLinkView]:
        """List the current User's active global provider identity links."""
        return await self.repository.list_links(user_id=user_id, now=now)

    async def unlink(
        self,
        *,
        user_id: str,
        auth_session_id: str,
        link_id: str,
        now: datetime.datetime,
    ) -> ExternalAccountLinkView:
        """Terminally unlink one elevated owner link."""
        return await self.repository.unlink(
            user_id=user_id,
            auth_session_id=auth_session_id,
            link_id=link_id,
            now=now,
        )
