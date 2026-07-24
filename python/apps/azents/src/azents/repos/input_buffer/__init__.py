"""InputBuffer repository."""

from collections.abc import Sequence
from typing import Any, cast

import sqlalchemy as sa
from azcommon.uuid import uuid7
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.engine import CursorResult
from sqlalchemy.ext.asyncio import AsyncSession

from azents.core.enums import InputBufferKind, InputBufferSchedulingMode
from azents.engine.events.types import FileOutputPart
from azents.rdb.models.event import JSONValue
from azents.rdb.models.input_buffer import RDBInputBuffer

from .data import InputBuffer, InputBufferCreate


class InputBufferRepository:
    """InputBuffer CRUD repository."""

    async def create(
        self,
        session: AsyncSession,
        create: InputBufferCreate,
    ) -> InputBuffer:
        """Create InputBuffer row."""
        rdb = RDBInputBuffer(
            session_id=create.session_id,
            kind=create.kind,
            scheduling_mode=create.scheduling_mode,
            requested_model_target_label=create.requested_model_target_label,
            requested_reasoning_effort=create.requested_reasoning_effort,
            sender_user_id=create.sender_user_id,
            content=create.content,
            idempotency_key=create.idempotency_key,
            metadata_=create.metadata,
            action=cast("dict[str, object] | None", create.action),
            attachments=create.attachments,
            file_parts=[
                part.model_dump(mode="json", exclude_none=True)
                for part in create.file_parts
            ],
        )
        session.add(rdb)
        await session.flush()
        return self._build(rdb)

    async def create_idempotent(
        self,
        session: AsyncSession,
        create: InputBufferCreate,
        *,
        idempotency_key: str,
    ) -> InputBuffer:
        """Atomically upsert InputBuffer by source idempotency key."""
        stmt = (
            pg_insert(RDBInputBuffer)
            .values(
                id=uuid7().hex,
                session_id=create.session_id,
                kind=create.kind,
                scheduling_mode=create.scheduling_mode,
                requested_model_target_label=create.requested_model_target_label,
                requested_reasoning_effort=create.requested_reasoning_effort,
                sender_user_id=create.sender_user_id,
                content=create.content,
                idempotency_key=idempotency_key,
                metadata_=create.metadata,
                action=cast("dict[str, object] | None", create.action),
                attachments=create.attachments,
                file_parts=[
                    part.model_dump(mode="json", exclude_none=True)
                    for part in create.file_parts
                ],
            )
            .on_conflict_do_nothing(
                index_elements=[
                    RDBInputBuffer.session_id,
                    RDBInputBuffer.kind,
                    RDBInputBuffer.idempotency_key,
                ],
                index_where=RDBInputBuffer.idempotency_key.is_not(None),
            )
            .returning(RDBInputBuffer)
        )
        result = await session.execute(stmt)
        rdb = result.scalar_one_or_none()
        if rdb is None:
            existing = await self.get_by_idempotency_key(
                session,
                session_id=create.session_id,
                kind=create.kind,
                idempotency_key=idempotency_key,
            )
            if existing is None:
                raise RuntimeError("Idempotent input buffer lookup failed")
            return existing
        return self._build(rdb)

    async def get_by_idempotency_key(
        self,
        session: AsyncSession,
        *,
        session_id: str,
        kind: InputBufferKind,
        idempotency_key: str,
    ) -> InputBuffer | None:
        """Fetch idempotent InputBuffer by source idempotency key."""
        result = await session.execute(
            sa.select(RDBInputBuffer).where(
                RDBInputBuffer.session_id == session_id,
                RDBInputBuffer.kind == kind,
                RDBInputBuffer.idempotency_key == idempotency_key,
            )
        )
        rdb = result.scalar_one_or_none()
        if rdb is None:
            return None
        return self._build(rdb)

    async def list_by_session_id(
        self,
        session: AsyncSession,
        session_id: str,
    ) -> list[InputBuffer]:
        """Fetch pending input buffers of session in accepted order."""
        result = await session.execute(
            sa.select(RDBInputBuffer)
            .where(RDBInputBuffer.session_id == session_id)
            .order_by(RDBInputBuffer.id.asc())
        )
        return [self._build(rdb) for rdb in result.scalars()]

    async def has_by_session_id_and_scheduling_mode(
        self,
        session: AsyncSession,
        *,
        session_id: str,
        scheduling_mode: InputBufferSchedulingMode,
    ) -> bool:
        """Return whether the session has input with the scheduling mode."""
        result = await session.scalar(
            sa.select(
                sa.exists().where(
                    RDBInputBuffer.session_id == session_id,
                    RDBInputBuffer.scheduling_mode == scheduling_mode,
                )
            )
        )
        return bool(result)

    async def has_by_session_id_and_kind(
        self,
        session: AsyncSession,
        *,
        session_id: str,
        kind: InputBufferKind,
    ) -> bool:
        """Return whether the session has input with the payload kind."""
        result = await session.scalar(
            sa.select(
                sa.exists().where(
                    RDBInputBuffer.session_id == session_id,
                    RDBInputBuffer.kind == kind,
                )
            )
        )
        return bool(result)

    async def list_for_flush(
        self,
        session: AsyncSession,
        session_id: str,
        *,
        limit: int | None = None,
    ) -> list[InputBuffer]:
        """Fetch ordered pending list for Phase 3 flush."""
        query = (
            sa.select(RDBInputBuffer)
            .where(RDBInputBuffer.session_id == session_id)
            .order_by(RDBInputBuffer.id.asc())
        )
        if limit is not None:
            query = query.limit(limit)
        result = await session.execute(query)
        return [self._build(rdb) for rdb in result.scalars()]

    async def lock_oldest_by_session_id(
        self,
        session: AsyncSession,
        session_id: str,
    ) -> InputBuffer | None:
        """Lock and return the oldest accepted InputBuffer for a Session."""
        result = await session.execute(
            sa.select(RDBInputBuffer)
            .where(RDBInputBuffer.session_id == session_id)
            .order_by(RDBInputBuffer.id.asc())
            .limit(1)
            .with_for_update()
        )
        rdb = result.scalar_one_or_none()
        return self._build(rdb) if rdb is not None else None

    async def delete_claimed_by_ids(
        self,
        session: AsyncSession,
        session_id: str,
        buffer_ids: Sequence[str],
    ) -> int:
        """Delete claimed InputBuffer rows inside session scope."""
        if not buffer_ids:
            return 0
        result = cast(
            CursorResult[Any],
            await session.execute(
                sa.delete(RDBInputBuffer).where(
                    RDBInputBuffer.session_id == session_id,
                    RDBInputBuffer.id.in_(buffer_ids),
                )
            ),
        )
        await session.flush()
        return result.rowcount or 0

    async def get_by_id(
        self,
        session: AsyncSession,
        buffer_id: str,
    ) -> InputBuffer | None:
        """Fetch InputBuffer by ID."""
        rdb = await session.get(RDBInputBuffer, buffer_id)
        if rdb is None:
            return None
        return self._build(rdb)

    async def delete_by_session_and_id(
        self,
        session: AsyncSession,
        session_id: str,
        buffer_id: str,
    ) -> bool:
        """Delete InputBuffer whose session and ID match."""
        result = cast(
            CursorResult[Any],
            await session.execute(
                sa.delete(RDBInputBuffer).where(
                    RDBInputBuffer.session_id == session_id,
                    RDBInputBuffer.id == buffer_id,
                )
            ),
        )
        await session.flush()
        return result.rowcount == 1

    async def delete_by_session_id(
        self,
        session: AsyncSession,
        session_id: str,
    ) -> int:
        """Delete all InputBuffers for session."""
        result = cast(
            CursorResult[Any],
            await session.execute(
                sa.delete(RDBInputBuffer).where(RDBInputBuffer.session_id == session_id)
            ),
        )
        await session.flush()
        return result.rowcount or 0

    async def move_by_session_id(
        self,
        session: AsyncSession,
        *,
        from_session_id: str,
        to_session_id: str,
    ) -> int:
        """Transfer pending InputBuffer rows to continuation session."""
        result = cast(
            CursorResult[Any],
            await session.execute(
                sa.update(RDBInputBuffer)
                .where(
                    RDBInputBuffer.session_id == from_session_id,
                )
                .values(session_id=to_session_id)
            ),
        )
        await session.flush()
        return result.rowcount or 0

    def _build(self, rdb: RDBInputBuffer) -> InputBuffer:
        """Convert RDB model to domain model."""
        return InputBuffer(
            id=rdb.id,
            session_id=rdb.session_id,
            kind=rdb.kind,
            scheduling_mode=rdb.scheduling_mode,
            requested_model_target_label=rdb.requested_model_target_label,
            requested_reasoning_effort=rdb.requested_reasoning_effort,
            sender_user_id=rdb.sender_user_id,
            content=rdb.content,
            idempotency_key=rdb.idempotency_key,
            metadata={str(k): str(v) for k, v in rdb.metadata_.items()},
            action=cast("dict[str, JSONValue] | None", rdb.action),
            attachments=[str(uri) for uri in rdb.attachments],
            file_parts=[FileOutputPart.model_validate(part) for part in rdb.file_parts],
            created_at=rdb.created_at,
        )
