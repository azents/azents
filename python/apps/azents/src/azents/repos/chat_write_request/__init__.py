"""ChatWriteRequest repository."""

import sqlalchemy as sa
from azcommon.uuid import uuid7
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from azents.rdb.models.chat_write_request import RDBChatWriteRequest

from .data import ChatWriteRequest, ChatWriteRequestCreate


class ChatWriteRequestRepository:
    """REST write idempotency repository."""

    async def create_idempotent(
        self,
        session: AsyncSession,
        create: ChatWriteRequestCreate,
    ) -> tuple[ChatWriteRequest, bool]:
        """Atomically create ChatWriteRequest or fetch existing row.

        :return: `(record, created)` pair. `created` is False when retry.
        """
        stmt = (
            pg_insert(RDBChatWriteRequest)
            .values(
                id=uuid7().hex,
                agent_runtime_id=create.agent_runtime_id,
                session_id=create.session_id,
                user_id=create.user_id,
                client_request_id=create.client_request_id,
                write_type=create.write_type,
                accepted_type=create.accepted_type,
                accepted_id=create.accepted_id,
                history_reload_required=create.history_reload_required,
                payload=create.payload,
            )
            .on_conflict_do_nothing(
                constraint="uq_chat_write_requests_runtime_user_client_request"
            )
            .returning(RDBChatWriteRequest)
        )
        result = await session.execute(stmt)
        rdb = result.scalar_one_or_none()
        if rdb is not None:
            return self._build(rdb), True
        existing = await self.get_by_client_request_id(
            session,
            agent_runtime_id=create.agent_runtime_id,
            user_id=create.user_id,
            client_request_id=create.client_request_id,
        )
        if existing is None:
            raise RuntimeError("Idempotent chat write request lookup failed")
        return existing, False

    async def get_by_client_request_id(
        self,
        session: AsyncSession,
        *,
        agent_runtime_id: str,
        user_id: str,
        client_request_id: str,
    ) -> ChatWriteRequest | None:
        """Fetch REST write record by client request ID."""
        result = await session.execute(
            sa.select(RDBChatWriteRequest).where(
                RDBChatWriteRequest.agent_runtime_id == agent_runtime_id,
                RDBChatWriteRequest.user_id == user_id,
                RDBChatWriteRequest.client_request_id == client_request_id,
            )
        )
        rdb = result.scalar_one_or_none()
        if rdb is None:
            return None
        return self._build(rdb)

    def _build(self, rdb: RDBChatWriteRequest) -> ChatWriteRequest:
        """Convert RDB model to domain model."""
        return ChatWriteRequest(
            id=rdb.id,
            agent_runtime_id=rdb.agent_runtime_id,
            session_id=rdb.session_id,
            user_id=rdb.user_id,
            client_request_id=rdb.client_request_id,
            write_type=rdb.write_type,
            accepted_type=rdb.accepted_type,
            accepted_id=rdb.accepted_id,
            history_reload_required=rdb.history_reload_required,
            payload=rdb.payload,
            created_at=rdb.created_at,
        )
