"""Database-only Mailbox admission compositions and completed operations."""

import dataclasses
from collections.abc import Sequence
from typing import Annotated

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from azents.core.enums import MailboxSchedulingMode
from azents.core.mailbox_data import MailboxItemCreate
from azents.rdb.deps import get_session_manager
from azents.rdb.session import SessionManager
from azents.repos.agent_session import AgentSessionRepository
from azents.repos.mailbox import MailboxRepository
from azents.repos.mailbox.admission_data import MailboxAdmissionResult, MailboxEnqueue


@dataclasses.dataclass
class MailboxAdmissionRepository:
    """Compose Mailbox admission with its matching Session wake transition."""

    session_manager: Annotated[
        SessionManager[AsyncSession], Depends(get_session_manager)
    ]
    mailbox_item_repository: Annotated[MailboxRepository, Depends(MailboxRepository)]
    agent_session_repository: Annotated[
        AgentSessionRepository, Depends(AgentSessionRepository)
    ]

    async def enqueue_in_session(
        self,
        session: AsyncSession,
        input: MailboxEnqueue,
    ) -> MailboxAdmissionResult:
        """Create one pending input and persist its wake transition."""
        result = await self._enqueue_without_running_transition(session, input)
        if input.scheduling_mode is MailboxSchedulingMode.WAKE_SESSION:
            await self.agent_session_repository.mark_running_for_input_wakeup(
                session,
                input.session_id,
            )
        return result

    async def _enqueue_without_running_transition(
        self,
        session: AsyncSession,
        input: MailboxEnqueue,
    ) -> MailboxAdmissionResult:
        """Create one pending input before applying its Session transition."""
        existing = None
        if input.idempotency_key is not None:
            existing = await self.mailbox_item_repository.get_by_idempotency_key(
                session,
                session_id=input.session_id,
                kind=input.kind,
                idempotency_key=input.idempotency_key,
            )
        if existing is None:
            created = True
            create = MailboxItemCreate(
                session_id=input.session_id,
                kind=input.kind,
                scheduling_mode=input.scheduling_mode,
                requested_model_target_label=input.requested_model_target_label,
                requested_reasoning_effort=input.requested_reasoning_effort,
                requested_enabled_execution_options=(
                    input.requested_enabled_execution_options
                ),
                sender_user_id=input.sender_user_id,
                order_group=input.order_group,
                order_sequence=input.order_sequence,
                content=input.content,
                idempotency_key=input.idempotency_key,
                metadata=input.metadata,
                action=input.action,
                attachments=input.attachments,
                file_parts=input.file_parts,
                payload=input.payload,
            )
            if input.idempotency_key is None:
                mailbox_item = await self.mailbox_item_repository.create(
                    session,
                    create,
                )
            else:
                mailbox_item = await self.mailbox_item_repository.create_idempotent(
                    session,
                    create,
                    idempotency_key=input.idempotency_key,
                )
        else:
            created = False
            mailbox_item = existing
        if mailbox_item.scheduling_mode != input.scheduling_mode:
            raise ValueError(
                "Input idempotency key already used for another scheduling mode"
            )
        if (
            mailbox_item.requested_model_target_label
            != input.requested_model_target_label
            or mailbox_item.requested_reasoning_effort
            != input.requested_reasoning_effort
            or mailbox_item.requested_enabled_execution_options
            != input.requested_enabled_execution_options
        ):
            raise ValueError(
                "Input idempotency key already used for another inference profile"
            )
        return MailboxAdmissionResult(mailbox_item=mailbox_item, created=created)

    async def enqueue_many_in_session(
        self,
        session: AsyncSession,
        inputs: Sequence[MailboxEnqueue],
    ) -> list[MailboxAdmissionResult]:
        """Create pending inputs and persist each distinct wake transition."""
        results = [
            await self._enqueue_without_running_transition(session, input)
            for input in inputs
        ]
        wake_session_ids = {
            input.session_id
            for input in inputs
            if input.scheduling_mode is MailboxSchedulingMode.WAKE_SESSION
        }
        for session_id in sorted(wake_session_ids):
            await self.agent_session_repository.mark_running_for_input_wakeup(
                session,
                session_id,
            )
        return results

    async def enqueue_idle_continuations_in_session(
        self,
        session: AsyncSession,
        inputs: Sequence[MailboxEnqueue],
    ) -> list[MailboxAdmissionResult]:
        """Create idle-hook inputs whose composing operation owns Session state."""
        return [
            await self._enqueue_without_running_transition(session, input)
            for input in inputs
        ]

    async def enqueue_many(
        self,
        inputs: Sequence[MailboxEnqueue],
    ) -> list[MailboxAdmissionResult]:
        """Create pending inputs in one completed transaction."""
        async with self.session_manager() as session:
            return await self.enqueue_many_in_session(session, inputs)
