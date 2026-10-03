"""Database-only availability projection inside model-input preparation."""

import dataclasses
from collections.abc import Sequence
from typing import Protocol

from sqlalchemy.ext.asyncio import AsyncSession

from azents.core.enums import ExchangeFileStatus, ModelFileStatus
from azents.engine.events.input_projection import (
    exchange_attachment_object_keys,
    model_file_ids,
    refresh_attachment_availability,
    replace_unavailable_file_parts,
)
from azents.engine.events.types import Event
from azents.repos.engine_event_contracts import EventPayloadRepository


class ModelFileStatusRepository(Protocol):
    """Narrow ModelFile status lookup used by availability projection."""

    async def list_statuses_for_session(
        self,
        session: AsyncSession,
        *,
        session_id: str,
        model_file_ids: Sequence[str],
    ) -> dict[str, ModelFileStatus]:
        """Return statuses for ModelFiles belonging to the Session."""
        ...


class ExchangeFileStatusRepository(Protocol):
    """Narrow ExchangeFile status lookup used by availability projection."""

    async def list_statuses_by_object_key(
        self,
        session: AsyncSession,
        *,
        object_keys: Sequence[str],
    ) -> dict[str, ExchangeFileStatus]:
        """Return ExchangeFile statuses by object key."""
        ...


@dataclasses.dataclass(frozen=True)
class EngineInputProjectionRepository:
    """Compose durable attachment and FilePart projection in one DB scope."""

    exchange_file_repository: ExchangeFileStatusRepository
    model_file_repository: ModelFileStatusRepository
    transcript_repository: EventPayloadRepository

    async def apply_in_session(
        self,
        session: AsyncSession,
        *,
        session_id: str,
        transcript: Sequence[Event],
    ) -> list[Event]:
        """Refresh Exchange availability before replacing unavailable FileParts."""
        events = list(transcript)
        object_keys = exchange_attachment_object_keys(events)
        if object_keys:
            statuses = await self.exchange_file_repository.list_statuses_by_object_key(
                session,
                object_keys=object_keys,
            )
            updated: list[Event] = []
            for event in events:
                payload = refresh_attachment_availability(event.payload, statuses)
                if payload is None:
                    updated.append(event)
                else:
                    updated.append(
                        await self.transcript_repository.update_payload(
                            session, event.id, payload
                        )
                    )
            events = updated
        file_ids = model_file_ids(events)
        if file_ids:
            file_statuses = await self.model_file_repository.list_statuses_for_session(
                session,
                session_id=session_id,
                model_file_ids=file_ids,
            )
            updated = []
            for event in events:
                payload = replace_unavailable_file_parts(event.payload, file_statuses)
                if payload is None:
                    updated.append(event)
                else:
                    updated.append(
                        await self.transcript_repository.update_payload(
                            session, event.id, payload
                        )
                    )
            events = updated
        return events
