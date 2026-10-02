"""Session-bound Memory context snapshot persistence and current filtering."""

import dataclasses
import datetime
from typing import Annotated

from fastapi import Depends
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from azents.core.enums import AgentSessionProductMode, EventKind
from azents.core.historical_memory_snapshot import (
    MemoryContextSnapshotState,
    MemorySnapshotConsumer,
)
from azents.engine.events.types import CompactionSummaryPayload
from azents.rdb.session import SessionManager
from azents.repos.historical_memory import HistoricalMemoryRepository
from azents.repos.memory import MemoryRepository
from azents.repos.message import MessageRepository
from azents.repos.toolkit_state import (
    ToolkitStateConflictError,
    ToolkitStateRepository,
)
from azents.repos.toolkit_state.data import ToolkitStateRecord, ToolkitStateUpsert
from azents.services.historical_memory.snapshot import (
    build_memory_context_snapshot,
    filter_memory_context_snapshot,
    render_memory_context_snapshot,
)

_MEMORY_NAMESPACE = "memory"
_CONTEXT_SNAPSHOT_STATE = "context_snapshot"
_HISTORICAL_CANDIDATE_LIMIT = 200


@dataclasses.dataclass
class MemoryContextSnapshotService:
    """Select, persist, filter, and render one Session Memory boundary snapshot."""

    historical_repository: Annotated[
        HistoricalMemoryRepository, Depends(HistoricalMemoryRepository)
    ]
    memory_repository: Annotated[MemoryRepository, Depends(MemoryRepository)]
    message_repository: Annotated[MessageRepository, Depends(MessageRepository)]
    toolkit_state_repository: Annotated[
        ToolkitStateRepository, Depends(ToolkitStateRepository)
    ]

    async def prompt_for_turn(
        self,
        *,
        session_id: str,
        session_manager: SessionManager[AsyncSession],
    ) -> str:
        """Return the current filtered prompt without ordinary-turn reselection."""
        historical_repository = self.historical_repository
        async with session_manager() as session:
            consumer = await historical_repository.get_snapshot_consumer_in_session(
                session,
                session_id=session_id,
            )
            if consumer is None:
                return ""
            record = await self.toolkit_state_repository.get(
                session,
                agent_id=consumer.agent_id,
                session_id=consumer.session_id,
                toolkit_namespace=_MEMORY_NAMESPACE,
                state_name=_CONTEXT_SNAPSHOT_STATE,
            )
            snapshot = self._decode_snapshot(record)
            if (
                snapshot is None
                or snapshot.boundary_head_event_id != consumer.model_input_head_event_id
            ):
                return ""

            filtered = await self._filter_snapshot(
                session,
                snapshot=snapshot,
                consumer=consumer,
            )
            return render_memory_context_snapshot(filtered)

    async def refresh_snapshot(
        self,
        *,
        session_id: str,
        after_compaction: bool,
        session_manager: SessionManager[AsyncSession],
    ) -> bool:
        """Prepare Memory at Run start or after a committed compaction.

        Compaction notification precedes commit, so an unchanged head preserves
        the current snapshot without admitting summaries during failed compaction.
        """
        async with session_manager() as session:
            consumer = (
                await self.historical_repository.get_snapshot_consumer_in_session(
                    session,
                    session_id=session_id,
                )
            )
            if consumer is None:
                return False
            record = await self.toolkit_state_repository.get(
                session,
                agent_id=consumer.agent_id,
                session_id=consumer.session_id,
                toolkit_namespace=_MEMORY_NAMESPACE,
                state_name=_CONTEXT_SNAPSHOT_STATE,
            )
            previous = self._decode_snapshot(record)
            if after_compaction:
                if (
                    previous is not None
                    and previous.boundary_head_event_id
                    == consumer.model_input_head_event_id
                ):
                    return True
                if consumer.model_input_head_event_id is None:
                    return False
            topic = await self._boundary_topic(
                session,
                session_id=consumer.session_id,
                head_event_id=consumer.model_input_head_event_id,
            )
            if consumer.model_input_head_event_id is not None and topic is None:
                return False
            return (
                await self._select_snapshot(
                    session,
                    consumer=consumer,
                    record=record,
                    topic=topic,
                    previous=previous,
                )
                is not None
            )

    async def _select_snapshot(
        self,
        session: AsyncSession,
        *,
        consumer: MemorySnapshotConsumer,
        record: ToolkitStateRecord | None,
        topic: str | None,
        previous: MemoryContextSnapshotState | None,
    ) -> MemoryContextSnapshotState | None:
        historical_repository = self.historical_repository
        saved = await self.memory_repository.list(
            session,
            agent_id=consumer.agent_id,
            user_id=None,
        )
        if (
            consumer.product_mode is AgentSessionProductMode.USER
            and consumer.associated_user_id is not None
        ):
            saved.extend(
                await self.memory_repository.list(
                    session,
                    agent_id=consumer.agent_id,
                    user_id=consumer.associated_user_id,
                )
            )
        historical = (
            await historical_repository.list_available_snapshot_candidates_in_session(
                session,
                agent_id=consumer.agent_id,
                workspace_id=consumer.workspace_id,
                consumer_product_mode=consumer.product_mode,
                associated_user_id=consumer.associated_user_id,
                source_session_ids=None,
                limit=_HISTORICAL_CANDIDATE_LIMIT,
            )
        )
        snapshot = build_memory_context_snapshot(
            boundary_head_event_id=consumer.model_input_head_event_id,
            created_at=datetime.datetime.now(datetime.UTC),
            saved_memories=saved,
            historical_candidates=historical,
            topic=topic,
        )
        if (
            previous is not None
            and previous.saved_entries == snapshot.saved_entries
            and previous.historical_entries == snapshot.historical_entries
        ):
            snapshot = previous.model_copy(
                update={
                    "boundary_head_event_id": consumer.model_input_head_event_id,
                }
            )
            if snapshot == previous:
                return previous
        try:
            await self.toolkit_state_repository.save(
                session,
                ToolkitStateUpsert(
                    agent_id=consumer.agent_id,
                    session_id=consumer.session_id,
                    toolkit_namespace=_MEMORY_NAMESPACE,
                    state_name=_CONTEXT_SNAPSHOT_STATE,
                    state_json=snapshot.model_dump(mode="json"),
                    schema_version=snapshot.schema_version,
                    expected_version=None if record is None else record.version,
                ),
            )
        except ToolkitStateConflictError:
            return None
        return snapshot

    async def _filter_snapshot(
        self,
        session: AsyncSession,
        *,
        snapshot: MemoryContextSnapshotState,
        consumer: MemorySnapshotConsumer,
    ) -> MemoryContextSnapshotState:
        historical_repository = self.historical_repository
        current_saved = await self.memory_repository.list_by_ids(
            session,
            agent_id=consumer.agent_id,
            memory_ids=[entry.memory_id for entry in snapshot.saved_entries],
        )
        available_saved_ids = {
            memory.id
            for memory in current_saved
            if memory.user_id is None
            or (
                consumer.product_mode is AgentSessionProductMode.USER
                and memory.user_id == consumer.associated_user_id
            )
        }
        historical_ids = [
            entry.source_session_id for entry in snapshot.historical_entries
        ]
        current_historical = (
            await historical_repository.list_available_snapshot_candidates_in_session(
                session,
                agent_id=consumer.agent_id,
                workspace_id=consumer.workspace_id,
                consumer_product_mode=consumer.product_mode,
                associated_user_id=consumer.associated_user_id,
                source_session_ids=historical_ids,
                limit=max(1, len(historical_ids)),
            )
        )
        return filter_memory_context_snapshot(
            snapshot,
            available_saved_ids=available_saved_ids,
            available_historical_ids={
                candidate.source_session_id for candidate in current_historical
            },
        )

    async def _boundary_topic(
        self,
        session: AsyncSession,
        *,
        session_id: str,
        head_event_id: str | None,
    ) -> str | None:
        if head_event_id is None:
            return None
        event = await self.message_repository.get_event_by_id(session, head_event_id)
        if (
            event is None
            or event.session_id != session_id
            or event.kind is not EventKind.COMPACTION_SUMMARY
            or not isinstance(event.payload, CompactionSummaryPayload)
        ):
            return None
        return event.payload.content

    @staticmethod
    def _decode_snapshot(
        record: ToolkitStateRecord | None,
    ) -> MemoryContextSnapshotState | None:
        if record is None:
            return None
        try:
            return MemoryContextSnapshotState.model_validate(record.state_json)
        except ValidationError:
            return None
