"""Completed canonical-mailbox authority read before routing-only Session wake."""

import dataclasses
from typing import Annotated

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from azents.rdb.deps import get_session_manager
from azents.rdb.session import SessionManager
from azents.repos.mailbox import MailboxRepository


@dataclasses.dataclass(frozen=True)
class ExternalChannelMailboxWakeRepository:
    """Finish the mailbox ownership read before a broker dispatch can occur."""

    session_manager: Annotated[
        SessionManager[AsyncSession], Depends(get_session_manager)
    ]
    mailbox_repository: Annotated[MailboxRepository, Depends(MailboxRepository)]

    async def prepare_dispatch(self, *, mailbox_item_id: str, session_id: str) -> bool:
        async with self.session_manager() as session:
            mailbox_item = await self.mailbox_repository.get_by_id(
                session, mailbox_item_id
            )
            if mailbox_item is None:
                await session.commit()
                return False
            if mailbox_item.session_id != session_id:
                raise ValueError("External Channel mailbox wake ownership is invalid.")
            await session.commit()
            return True
