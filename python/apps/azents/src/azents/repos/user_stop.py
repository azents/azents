"""Separate repository-owned database stages for User Stop finalization."""

import dataclasses
from typing import Annotated

from fastapi import Depends

from azents.core.enums import EventKind
from azents.engine.events.types import (
    AssistantMessagePayload,
    ClientToolResultPayload,
    InterruptedPayload,
    OutputTextPart,
    ReasoningPayload,
    RunMarkerPayload,
)
from azents.rdb.deps import get_session_manager
from azents.rdb.session import SessionManager
from azents.rdb.session_capabilities import WriteSession
from azents.repos.agent_execution import AgentRunRepository, EventTranscriptRepository
from azents.repos.agent_execution.data import EventCreate
from azents.repos.agent_session import AgentSessionRepository
from azents.repos.engine_tool_result_operation import (
    EngineToolResultOperationRepository,
)
from azents.repos.user_stop_data import (
    UserStopCancelledCallsInput,
    UserStopDurableEvents,
    UserStopMarkerInput,
    UserStopOwnerInput,
    UserStopPartialInput,
)
from azents.repos.worker_session import WorkerSessionOperationRepository


def get_user_stop_tool_result_repository(
    session_manager: Annotated[
        SessionManager[WriteSession], Depends(get_session_manager)
    ],
    run_repository: Annotated[AgentRunRepository, Depends(AgentRunRepository)],
    transcript_repository: Annotated[
        EventTranscriptRepository, Depends(EventTranscriptRepository)
    ],
) -> EngineToolResultOperationRepository:
    """Inject the narrow tool-result composition without application callbacks."""
    return EngineToolResultOperationRepository(
        owner=None,
        session_manager=session_manager,
        run_repository=run_repository,
        transcript_repository=transcript_repository,
    )


@dataclasses.dataclass(frozen=True)
class UserStopOperationRepository:
    """Own each original Stop commit separately under the shared Worker guard."""

    session_manager: Annotated[
        SessionManager[WriteSession], Depends(get_session_manager)
    ]
    worker_session_repository: Annotated[
        WorkerSessionOperationRepository, Depends(WorkerSessionOperationRepository)
    ]
    agent_session_repository: Annotated[
        AgentSessionRepository, Depends(AgentSessionRepository)
    ]
    event_transcript_repository: Annotated[
        EventTranscriptRepository, Depends(EventTranscriptRepository)
    ]
    tool_result_repository: Annotated[
        EngineToolResultOperationRepository,
        Depends(get_user_stop_tool_result_repository),
    ]

    async def append_partial_events(self, input: UserStopPartialInput) -> None:
        """Admit eligible live partials once, skipping an empty database action."""
        appendable = [
            event
            for event in input.events
            if isinstance(event.payload, AssistantMessagePayload | ReasoningPayload)
        ]
        if not appendable:
            return
        async with self.session_manager() as session:
            await self.worker_session_repository.assert_owner_generation_in_session(
                session,
                session_id=input.session_id,
                owner_generation=input.owner_generation,
            )
            for event in appendable:
                existing = await self.event_transcript_repository.get_by_external_id(
                    session, input.session_id, event.id
                )
                if existing is not None:
                    continue
                await self.event_transcript_repository.append(
                    session,
                    EventCreate(
                        session_id=input.session_id,
                        kind=event.kind,
                        payload=event.payload.model_dump(
                            mode="json", exclude_none=True
                        ),
                        external_id=event.id,
                        adapter=event.adapter,
                        provider=event.provider,
                        model=event.model,
                        native_format=event.native_format,
                        schema_version=event.schema_version,
                    ),
                )

    async def append_cancelled_tool_results(
        self, input: UserStopCancelledCallsInput
    ) -> None:
        """Deduplicate durable active calls and settle results in one guarded scope."""
        calls_by_id = {call.call_id: call for call in input.active_tool_calls}
        if not calls_by_id:
            return
        if input.run_id is None:
            raise RuntimeError("Active tool calls require a running AgentRun")
        async with self.session_manager() as session:
            await self.worker_session_repository.assert_owner_generation_in_session(
                session,
                session_id=input.session_id,
                owner_generation=input.owner_generation,
            )
            for call in calls_by_id.values():
                payload = ClientToolResultPayload(
                    call_id=call.call_id,
                    name=call.name,
                    wire_dialect=call.wire_dialect,
                    status="cancelled",
                    output=[
                        OutputTextPart(
                            text=(
                                "Tool execution was cancelled "
                                "before a result was recorded."
                            )
                        )
                    ],
                )
                await self.tool_result_repository.finalize_in_session(
                    session,
                    run_id=input.run_id,
                    session_id=input.session_id,
                    call=call,
                    result=payload,
                )

    async def append_user_stop_events(
        self, input: UserStopMarkerInput
    ) -> UserStopDurableEvents:
        """Append the interrupted event and Run marker in their original transaction."""
        interrupted_external_id = f"interrupted:{input.run_id}:user_requested"
        marker_external_id = f"run-marker:{input.run_id}:interrupted"
        async with self.session_manager() as session:
            await self.worker_session_repository.assert_owner_generation_in_session(
                session,
                session_id=input.session_id,
                owner_generation=input.owner_generation,
            )
            interrupted = await self.event_transcript_repository.append(
                session,
                EventCreate(
                    session_id=input.session_id,
                    kind=EventKind.INTERRUPTED,
                    payload=InterruptedPayload(
                        run_id=input.run_id, reason="user_requested"
                    ).model_dump(mode="json", exclude_none=True),
                    external_id=interrupted_external_id,
                ),
            )
            run_marker = await self.event_transcript_repository.append(
                session,
                EventCreate(
                    session_id=input.session_id,
                    kind=EventKind.RUN_MARKER,
                    payload=RunMarkerPayload(
                        run_id=input.run_id, status="interrupted"
                    ).model_dump(mode="json", exclude_none=True),
                    external_id=marker_external_id,
                ),
            )
        return UserStopDurableEvents(interrupted=interrupted, run_marker=run_marker)

    async def clear_stop_request(self, input: UserStopOwnerInput) -> None:
        """Clear consumed Stop intent only in its later guarded transaction."""
        async with self.session_manager() as session:
            await self.worker_session_repository.assert_owner_generation_in_session(
                session,
                session_id=input.session_id,
                owner_generation=input.owner_generation,
            )
            await self.agent_session_repository.clear_stop_request(
                session, session_id=input.session_id
            )
