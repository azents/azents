"""Completed database operations used by the Event Engine adapter."""

import dataclasses
from collections.abc import Sequence

from azents.core.enums import AgentRunStatus, EventKind
from azents.engine.events.types import (
    AgentRunState,
    Event,
    SystemErrorPayload,
)
from azents.engine.io.user_input import RunUserMessage
from azents.rdb.session import SessionManager
from azents.rdb.session_capabilities import WriteSession
from azents.repos.agent_execution.data import EventCreate
from azents.repos.agent_session import AgentSessionRepository
from azents.repos.engine_event_contracts import (
    AgentRunCreateRepository,
    SessionHeadRepository,
    TranscriptRepository,
)


@dataclasses.dataclass(frozen=True)
class EngineRunPreparation:
    """Detached transcript events and active Run state for Engine execution."""

    user_message_events: list[Event]
    run_state: AgentRunState


@dataclasses.dataclass
class EngineEventOperationRepository:
    """Own completed Event Engine transcript and Run operations."""

    session_manager: SessionManager[WriteSession]
    run_repository: AgentRunCreateRepository
    agent_session_repository: AgentSessionRepository
    session_head_repository: SessionHeadRepository
    transcript_repository: TranscriptRepository

    async def append_system_error(
        self,
        *,
        session_id: str,
        content: str,
    ) -> Event:
        """Append a recoverable system error in one completed transaction."""
        async with self.session_manager() as session:
            return await self.transcript_repository.append(
                session,
                EventCreate(
                    session_id=session_id,
                    kind=EventKind.SYSTEM_ERROR,
                    payload=SystemErrorPayload(
                        content=content,
                        severity="error",
                        recoverable=True,
                    ).model_dump(
                        mode="json",
                        exclude_none=True,
                    ),
                ),
            )

    async def prepare_compaction(self, *, session_id: str) -> list[Event]:
        """Validate the Session and return its current model-input transcript."""
        async with self.session_manager() as session:
            await self._ensure_agent_session(session, session_id)
            session_state = await self.session_head_repository.get_by_id(
                session,
                session_id,
            )
            head_event_id = (
                session_state.model_input_head_event_id
                if session_state is not None
                else None
            )
            return await self.transcript_repository.list_for_model_input(
                session,
                session_id,
                head_event_id=head_event_id,
            )

    async def prepare_run(
        self,
        *,
        session_id: str,
        run_id: str,
        user_messages: Sequence[RunUserMessage],
    ) -> EngineRunPreparation:
        """Append initial inputs and validate the active Run atomically."""
        async with self.session_manager() as session:
            await self._ensure_agent_session(session, session_id)
            user_message_events = await self._append_user_messages(
                session,
                session_id,
                user_messages,
            )
            run_state = await self.run_repository.get_by_id(session, run_id)
            if run_state is None or run_state.status is not AgentRunStatus.RUNNING:
                raise RuntimeError(
                    "AgentRun must be activated before engine invocation"
                )
            return EngineRunPreparation(
                user_message_events=user_message_events,
                run_state=run_state,
            )

    async def append_user_messages(
        self,
        *,
        session_id: str,
        user_messages: Sequence[RunUserMessage],
    ) -> list[Event]:
        """Append polled input messages in one completed transaction."""
        async with self.session_manager() as session:
            return await self._append_user_messages(
                session,
                session_id,
                user_messages,
            )

    async def _ensure_agent_session(
        self,
        session: WriteSession,
        session_id: str,
    ) -> None:
        """Ensure the AgentSession exists before event processing."""
        agent_session = await self.agent_session_repository.get_by_id(
            session,
            session_id,
        )
        if agent_session is None:
            raise ValueError("AgentSession not found")

    async def _append_user_messages(
        self,
        session: WriteSession,
        session_id: str,
        user_messages: Sequence[RunUserMessage],
    ) -> list[Event]:
        """Append Run user-message inputs with external-ID deduplication."""
        appended: list[Event] = []
        for user_message in user_messages:
            existing = await self.transcript_repository.get_by_external_id(
                session,
                session_id,
                user_message.external_id,
            )
            if existing is not None:
                continue
            appended.append(
                await self.transcript_repository.append(
                    session,
                    EventCreate(
                        session_id=session_id,
                        kind=EventKind.USER_MESSAGE,
                        payload=user_message.payload.model_dump(
                            mode="json",
                            exclude_none=True,
                        ),
                        external_id=user_message.external_id,
                    ),
                )
            )
        return appended
