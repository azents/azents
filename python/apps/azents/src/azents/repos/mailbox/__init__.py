"""MailboxItem repository."""

from collections.abc import Sequence
from typing import Any, cast

import sqlalchemy as sa
from azcommon.uuid import uuid7
from pydantic import TypeAdapter
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.engine import CursorResult
from sqlalchemy.ext.asyncio import AsyncSession

from azents.core.enums import MailboxItemKind, MailboxSchedulingMode
from azents.rdb.models.event import JSONValue
from azents.rdb.models.mailbox_item import RDBMailboxItem

from .data import (
    MailboxEnvelopePayload,
    MailboxItem,
    MailboxItemCreate,
    mailbox_payload_from_fields,
)

_MAILBOX_PAYLOAD_ADAPTER = TypeAdapter(MailboxEnvelopePayload)


class MailboxRepository:
    """MailboxItem CRUD repository."""

    async def create(
        self,
        session: AsyncSession,
        create: MailboxItemCreate,
    ) -> MailboxItem:
        """Create MailboxItem row."""
        rdb = RDBMailboxItem(
            session_id=create.session_id,
            kind=create.kind,
            scheduling_mode=create.scheduling_mode,
            requested_model_target_label=create.requested_model_target_label,
            requested_reasoning_effort=create.requested_reasoning_effort,
            sender_user_id=create.sender_user_id,
            idempotency_key=create.idempotency_key,
            payload=(
                create.payload
                or mailbox_payload_from_fields(
                    kind=create.kind,
                    content=create.content,
                    metadata=create.metadata,
                    action=create.action,
                    attachments=create.attachments,
                    file_parts=create.file_parts,
                )
            ).model_dump(mode="json"),
        )
        rdb.order_group = create.order_group or rdb.id
        rdb.order_sequence = create.order_sequence
        session.add(rdb)
        await session.flush()
        return self._build(rdb)

    async def create_idempotent(
        self,
        session: AsyncSession,
        create: MailboxItemCreate,
        *,
        idempotency_key: str,
    ) -> MailboxItem:
        """Atomically upsert MailboxItem by source idempotency key."""
        mailbox_item_id = uuid7().hex
        stmt = (
            pg_insert(RDBMailboxItem)
            .values(
                id=mailbox_item_id,
                session_id=create.session_id,
                kind=create.kind,
                scheduling_mode=create.scheduling_mode,
                requested_model_target_label=create.requested_model_target_label,
                requested_reasoning_effort=create.requested_reasoning_effort,
                sender_user_id=create.sender_user_id,
                idempotency_key=idempotency_key,
                order_group=create.order_group or mailbox_item_id,
                order_sequence=create.order_sequence,
                payload=(
                    create.payload
                    or mailbox_payload_from_fields(
                        kind=create.kind,
                        content=create.content,
                        metadata=create.metadata,
                        action=create.action,
                        attachments=create.attachments,
                        file_parts=create.file_parts,
                    )
                ).model_dump(mode="json"),
            )
            .on_conflict_do_nothing(
                index_elements=[
                    RDBMailboxItem.session_id,
                    RDBMailboxItem.kind,
                    RDBMailboxItem.idempotency_key,
                ],
                index_where=RDBMailboxItem.idempotency_key.is_not(None),
            )
            .returning(RDBMailboxItem)
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
        kind: MailboxItemKind,
        idempotency_key: str,
    ) -> MailboxItem | None:
        """Fetch idempotent MailboxItem by source idempotency key."""
        result = await session.execute(
            sa.select(RDBMailboxItem).where(
                RDBMailboxItem.session_id == session_id,
                RDBMailboxItem.kind == kind,
                RDBMailboxItem.idempotency_key == idempotency_key,
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
    ) -> list[MailboxItem]:
        """Fetch pending input buffers of session in accepted order."""
        result = await session.execute(
            sa.select(RDBMailboxItem)
            .where(RDBMailboxItem.session_id == session_id)
            .order_by(
                RDBMailboxItem.order_group.asc(),
                RDBMailboxItem.order_sequence.asc(),
                RDBMailboxItem.id.asc(),
            )
        )
        return [self._build(rdb) for rdb in result.scalars()]

    async def has_by_session_id_and_scheduling_mode(
        self,
        session: AsyncSession,
        *,
        session_id: str,
        scheduling_mode: MailboxSchedulingMode,
    ) -> bool:
        """Return whether the session has input with the scheduling mode."""
        result = await session.scalar(
            sa.select(
                sa.exists().where(
                    RDBMailboxItem.session_id == session_id,
                    RDBMailboxItem.scheduling_mode == scheduling_mode,
                )
            )
        )
        return bool(result)

    async def has_by_session_id_and_kind(
        self,
        session: AsyncSession,
        *,
        session_id: str,
        kind: MailboxItemKind,
    ) -> bool:
        """Return whether the session has input with the payload kind."""
        result = await session.scalar(
            sa.select(
                sa.exists().where(
                    RDBMailboxItem.session_id == session_id,
                    RDBMailboxItem.kind == kind,
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
    ) -> list[MailboxItem]:
        """Fetch ordered pending list for Phase 3 flush."""
        query = (
            sa.select(RDBMailboxItem)
            .where(RDBMailboxItem.session_id == session_id)
            .order_by(
                RDBMailboxItem.order_group.asc(),
                RDBMailboxItem.order_sequence.asc(),
                RDBMailboxItem.id.asc(),
            )
        )
        if limit is not None:
            query = query.limit(limit)
        result = await session.execute(query)
        return [self._build(rdb) for rdb in result.scalars()]

    async def lock_oldest_by_session_id(
        self,
        session: AsyncSession,
        session_id: str,
    ) -> MailboxItem | None:
        """Lock and return the oldest accepted MailboxItem for a Session."""
        result = await session.execute(
            sa.select(RDBMailboxItem)
            .where(RDBMailboxItem.session_id == session_id)
            .order_by(
                RDBMailboxItem.order_group.asc(),
                RDBMailboxItem.order_sequence.asc(),
                RDBMailboxItem.id.asc(),
            )
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
        """Delete claimed MailboxItem rows inside session scope."""
        if not buffer_ids:
            return 0
        result = cast(
            CursorResult[Any],
            await session.execute(
                sa.delete(RDBMailboxItem).where(
                    RDBMailboxItem.session_id == session_id,
                    RDBMailboxItem.id.in_(buffer_ids),
                )
            ),
        )
        await session.flush()
        return result.rowcount or 0

    async def get_by_id(
        self,
        session: AsyncSession,
        buffer_id: str,
    ) -> MailboxItem | None:
        """Fetch MailboxItem by ID."""
        rdb = await session.get(RDBMailboxItem, buffer_id)
        if rdb is None:
            return None
        return self._build(rdb)

    async def lock_by_session_and_id(
        self,
        session: AsyncSession,
        *,
        session_id: str,
        buffer_id: str,
    ) -> MailboxItem | None:
        """Lock one exact MailboxItem inside its Session scope."""
        rdb = await session.scalar(
            sa.select(RDBMailboxItem)
            .where(
                RDBMailboxItem.session_id == session_id,
                RDBMailboxItem.id == buffer_id,
            )
            .with_for_update()
        )
        return self._build(rdb) if rdb is not None else None

    async def delete_by_session_and_id(
        self,
        session: AsyncSession,
        session_id: str,
        buffer_id: str,
    ) -> bool:
        """Delete MailboxItem whose session and ID match."""
        result = cast(
            CursorResult[Any],
            await session.execute(
                sa.delete(RDBMailboxItem).where(
                    RDBMailboxItem.session_id == session_id,
                    RDBMailboxItem.id == buffer_id,
                )
            ),
        )
        await session.flush()
        return result.rowcount == 1

    async def detach_sender_user_id(
        self,
        session: AsyncSession,
        *,
        sender_user_id: str,
    ) -> int:
        """Detach a deleted User from retained MailboxItem rows."""
        result = cast(
            CursorResult[Any],
            await session.execute(
                sa.update(RDBMailboxItem)
                .where(RDBMailboxItem.sender_user_id == sender_user_id)
                .values(sender_user_id=None)
            ),
        )
        await session.flush()
        return result.rowcount or 0

    async def delete_by_session_id(
        self,
        session: AsyncSession,
        session_id: str,
    ) -> int:
        """Delete all MailboxItems for session."""
        result = cast(
            CursorResult[Any],
            await session.execute(
                sa.delete(RDBMailboxItem).where(RDBMailboxItem.session_id == session_id)
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
        """Transfer pending MailboxItem rows to continuation session."""
        result = cast(
            CursorResult[Any],
            await session.execute(
                sa.update(RDBMailboxItem)
                .where(
                    RDBMailboxItem.session_id == from_session_id,
                )
                .values(session_id=to_session_id)
            ),
        )
        await session.flush()
        return result.rowcount or 0

    def _build(self, rdb: RDBMailboxItem) -> MailboxItem:
        """Convert RDB model to domain model."""
        payload = _MAILBOX_PAYLOAD_ADAPTER.validate_python(rdb.payload)
        presentation = payload.items[0]
        return MailboxItem(
            id=rdb.id,
            session_id=rdb.session_id,
            kind=rdb.kind,
            scheduling_mode=rdb.scheduling_mode,
            requested_model_target_label=rdb.requested_model_target_label,
            requested_reasoning_effort=rdb.requested_reasoning_effort,
            sender_user_id=rdb.sender_user_id,
            order_group=rdb.order_group,
            order_sequence=rdb.order_sequence,
            content=presentation.content,
            idempotency_key=rdb.idempotency_key,
            metadata={str(k): str(v) for k, v in presentation.metadata.items()},
            action=cast("dict[str, JSONValue] | None", presentation.action),
            attachments=[str(uri) for uri in presentation.attachments],
            file_parts=presentation.file_parts,
            payload=payload,
            created_at=rdb.created_at,
        )
