"""Database-only durable Event mutations for composed Engine operations."""

import dataclasses
from collections.abc import Sequence
from typing import Literal

from sqlalchemy.ext.asyncio import AsyncSession

from azents.core.enums import EventKind
from azents.core.inference_profile import SessionInferenceState
from azents.engine.events.tool_calls import tool_call_external_id
from azents.engine.events.types import (
    ClientToolCallPayload,
    Event,
    RunMarkerPayload,
    TokenUsagePayload,
    TurnMarkerPayload,
)
from azents.repos.agent_execution.data import EventCreate
from azents.repos.engine_event_contracts import TranscriptRepository


@dataclasses.dataclass(frozen=True)
class EngineEventMutationRepository:
    """Compose Event serialization and markers inside repository transactions."""

    transcript_repository: TranscriptRepository

    async def append_events(
        self,
        session: AsyncSession,
        events: Sequence[Event],
        *,
        tool_call_run_id: str | None,
    ) -> list[Event]:
        """Append normalized Events with their original canonical metadata."""
        appended: list[Event] = []
        for event in events:
            external_id = event.external_id
            if tool_call_run_id is not None and isinstance(
                event.payload, ClientToolCallPayload
            ):
                external_id = tool_call_external_id(
                    tool_call_run_id, event.payload.call_id
                )
            appended.append(
                await self.transcript_repository.append(
                    session,
                    EventCreate(
                        session_id=event.session_id,
                        kind=event.kind,
                        payload=event.payload.model_dump(
                            mode="json", exclude_none=True
                        ),
                        external_id=external_id,
                        adapter=event.adapter,
                        provider=event.provider,
                        model=event.model,
                        native_format=event.native_format,
                        schema_version=event.schema_version,
                    ),
                )
            )
        return appended

    async def append_run_marker(
        self,
        session: AsyncSession,
        *,
        session_id: str,
        run_id: str,
        status: Literal["completed", "stopped", "failed", "interrupted"],
    ) -> Event:
        """Append or reuse the deterministic terminal Run marker."""
        external_id = f"run-marker:{run_id}:{status}"
        existing = await self.transcript_repository.get_by_external_id(
            session, session_id, external_id
        )
        if existing is not None:
            return existing
        return await self.transcript_repository.append(
            session,
            EventCreate(
                session_id=session_id,
                kind=EventKind.RUN_MARKER,
                payload=RunMarkerPayload(run_id=run_id, status=status).model_dump(
                    mode="json", exclude_none=True
                ),
                external_id=external_id,
            ),
        )

    async def append_turn_marker(
        self,
        session: AsyncSession,
        *,
        session_id: str,
        run_id: str,
        usage: TokenUsagePayload | None,
        inference_state: SessionInferenceState | None,
    ) -> Event | None:
        """Append immutable usage and inference provenance when usage exists."""
        if usage is None:
            return None
        applied_profile = (
            inference_state.applied_profile if inference_state is not None else None
        )
        payload = TurnMarkerPayload(
            run_id=run_id,
            usage=usage,
            applied_inference_profile=applied_profile,
            applied_model_route=(
                inference_state.applied_model_route
                if inference_state is not None
                else None
            ),
            effective_context_window_tokens=(
                inference_state.effective_context_window_tokens
                if inference_state is not None
                else None
            ),
            effective_auto_compaction_threshold_tokens=(
                inference_state.effective_auto_compaction_threshold_tokens
                if inference_state is not None
                else None
            ),
        ).model_dump(mode="json", exclude_none=True)
        if applied_profile is not None:
            payload["applied_inference_profile"] = applied_profile.model_dump(
                mode="json"
            )
        return await self.transcript_repository.append(
            session,
            EventCreate(
                session_id=session_id,
                kind=EventKind.TURN_MARKER,
                payload=payload,
            ),
        )
