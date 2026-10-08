"""Database-only mailbox visibility composition shared by atomic producers."""

import dataclasses
from typing import Annotated

from fastapi import Depends

from azents.core.enums import MailboxItemKind
from azents.rdb.session_capabilities import ReadSession
from azents.repos.action_execution import ActionExecutionRepository
from azents.repos.agent_execution import EventTranscriptRepository
from azents.repos.mailbox import MailboxRepository


@dataclasses.dataclass(frozen=True)
class MailboxDatabaseRepository:
    """Compose narrower repositories inside a producer-owned transaction."""

    mailbox_item_repository: Annotated[MailboxRepository, Depends(MailboxRepository)]
    event_transcript_repository: Annotated[
        EventTranscriptRepository, Depends(EventTranscriptRepository)
    ]
    action_execution_repository: Annotated[
        ActionExecutionRepository, Depends(ActionExecutionRepository)
    ]

    async def has_seen_action_type(
        self, session: ReadSession, *, session_id: str, action_type: str
    ) -> bool:
        pending = await self.mailbox_item_repository.list_by_session_id(
            session, session_id
        )
        if any(
            item.kind is MailboxItemKind.ACTION_MESSAGE
            and item.presentation.action_identity.action_type == action_type
            for item in pending
        ):
            return True
        if await self.action_execution_repository.has_action_type_by_session_id(
            session, session_id=session_id, action_type=action_type
        ):
            return True
        repository = self.event_transcript_repository
        return await repository.has_action_execution_result_with_type(
            session, session_id=session_id, action_type=action_type
        )
