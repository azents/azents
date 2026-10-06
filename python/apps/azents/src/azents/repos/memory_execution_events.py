"""Canonical Memory execution events over the shared Session/Run transcript."""

import dataclasses
from collections.abc import Sequence
from typing import Annotated

import sqlalchemy as sa
from fastapi import Depends

from azents.core.enums import AgentRunPhase, EventKind
from azents.core.historical_memory_consolidation import (
    MemoryAcceptedOutcome,
    MemoryExecutionAuthorityError,
    MemoryExecutionPrincipal,
)
from azents.engine.events.model_messages import TransientModelMessage
from azents.engine.events.types import (
    ClientToolResultPayload,
    Event,
    TokenUsagePayload,
    TurnMarkerPayload,
    UserMessagePayload,
)
from azents.rdb.deps import get_read_only_session_manager, get_session_manager
from azents.rdb.models.event import RDBEvent
from azents.rdb.session import SessionManager
from azents.rdb.session_capabilities import ReadSession, WriteSession
from azents.repos.agent_execution import AgentRunRepository, EventTranscriptRepository
from azents.repos.agent_execution.data import EventCreate
from azents.repos.historical_memory_consolidation.execution import (
    MemoryExecutionRepository,
)
from azents.repos.session_execution.ownership import fence_owned_session_mutation
from azents.repos.session_execution_record import SessionExecutionRecordRepository


@dataclasses.dataclass(frozen=True)
class MemoryExecutionEventsRepository:
    """Compose admitted domain work with common events in short DB operations."""

    session_manager: Annotated[
        SessionManager[WriteSession], Depends(get_session_manager)
    ]
    read_session_manager: Annotated[
        SessionManager[ReadSession], Depends(get_read_only_session_manager)
    ]
    executions: Annotated[MemoryExecutionRepository, Depends(MemoryExecutionRepository)]
    events: Annotated[EventTranscriptRepository, Depends(EventTranscriptRepository)]
    records: Annotated[
        SessionExecutionRecordRepository, Depends(SessionExecutionRecordRepository)
    ]
    runs: Annotated[AgentRunRepository, Depends(AgentRunRepository)]

    async def seed(self, principal: MemoryExecutionPrincipal, content: str) -> None:
        """Seed only this fresh execution, never predecessor or accepted memory."""
        async with self.session_manager() as session:
            await self.executions.admit_in_session(session, principal)
            await self.events.append(
                session,
                EventCreate(
                    session_id=principal.owner.session_id,
                    kind=EventKind.USER_MESSAGE,
                    payload=UserMessagePayload(
                        sender_user_id=None, content=content
                    ).model_dump(mode="json", exclude_none=True),
                    external_id="memory:initial",
                ),
            )

    async def transcript(self, principal: MemoryExecutionPrincipal) -> list[Event]:
        """Read current execution head only; old archived payload is not replayed."""
        await self.executions.authorize_execution(principal)
        async with self.read_session_manager() as session:
            current = await self.records.get_by_id(session, principal.owner.session_id)
            if (
                current is None
                or current.owner_generation != principal.owner.owner_generation
            ):
                raise MemoryExecutionAuthorityError(
                    "Memory execution owner is unavailable."
                )
            return await self.events.list_for_model_input(
                session,
                principal.owner.session_id,
                head_event_id=current.model_input_head_event_id,
            )

    async def append(
        self,
        principal: MemoryExecutionPrincipal,
        messages: Sequence[TransientModelMessage],
        *,
        accepted: MemoryAcceptedOutcome | None,
    ) -> None:
        """Persist admitted output or the exact already accepted submit result."""
        if not messages:
            return
        if accepted is not None:
            observed = await self.executions.inspect_accepted(
                principal.owner.session_id, tool_call_id=accepted.tool_call_id
            )
            if observed != accepted or any(
                not isinstance(message.payload, ClientToolResultPayload)
                or message.payload.name != "submit_memory"
                or (
                    message.payload.call_id != accepted.tool_call_id
                    and message.payload.status != "cancelled"
                )
                for message in messages
            ):
                raise MemoryExecutionAuthorityError(
                    "Accepted Memory tool result is unavailable."
                )
        async with self.session_manager() as session:
            if accepted is None:
                await self.executions.admit_in_session(session, principal)
            else:
                await fence_owned_session_mutation(session, principal.owner)
                cancelled_ids = {
                    message.payload.call_id
                    for message in messages
                    if isinstance(message.payload, ClientToolResultPayload)
                    and message.payload.call_id != accepted.tool_call_id
                }
                if cancelled_ids:
                    admitted_ids = set(
                        await session.read_session.scalars(
                            sa.select(RDBEvent.payload["call_id"].astext).where(
                                RDBEvent.session_id == principal.owner.session_id,
                                RDBEvent.kind == EventKind.CLIENT_TOOL_CALL,
                                RDBEvent.payload["name"].astext == "submit_memory",
                                RDBEvent.payload["call_id"].astext.in_(cancelled_ids),
                            )
                        )
                    )
                    if admitted_ids != cancelled_ids:
                        raise MemoryExecutionAuthorityError(
                            "Cancelled Memory submission was not admitted."
                        )
            for message in messages:
                if isinstance(message.payload, ClientToolResultPayload):
                    await self.events.append(
                        session,
                        EventCreate(
                            session_id=principal.owner.session_id,
                            kind=message.kind,
                            payload=message.payload.model_dump(
                                mode="json", exclude_none=True
                            ),
                            external_id=f"memory:tool-result:{message.payload.call_id}",
                        ),
                    )
                else:
                    await self.events.append(
                        session,
                        EventCreate(
                            session_id=principal.owner.session_id,
                            kind=message.kind,
                            payload=message.payload.model_dump(
                                mode="json", exclude_none=True
                            ),
                        ),
                    )

    async def record_usage(
        self, principal: MemoryExecutionPrincipal, usage: TokenUsagePayload | None
    ) -> None:
        """Use the common Run marker, without a second dispatch ledger."""
        if usage is None:
            return
        async with self.session_manager() as session:
            await self.executions.admit_in_session(session, principal)
            await self.events.append(
                session,
                EventCreate(
                    session_id=principal.owner.session_id,
                    kind=EventKind.TURN_MARKER,
                    payload=TurnMarkerPayload(
                        run_id=principal.run_id, usage=usage
                    ).model_dump(mode="json", exclude_none=True),
                ),
            )

    async def phase(
        self, principal: MemoryExecutionPrincipal, phase: AgentRunPhase
    ) -> None:
        """Keep phase changes on the same admitted actual common Run."""
        async with self.session_manager() as session:
            await self.executions.admit_in_session(session, principal)
            await self.runs.update_phase(session, principal.run_id, phase)
