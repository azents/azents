"""ChatWriteRequest repository."""

import sqlalchemy as sa
from azcommon.uuid import uuid7
from sqlalchemy.dialects.postgresql import insert as pg_insert

from azents.rdb.models.chat_write_request import RDBChatWriteRequest
from azents.rdb.session_capabilities import ReadSession, WriteSession
from azents.repos.mutation_result import mutation_result

from .data import ChatWriteRequest, ChatWriteRequestCreate, IdempotentChatWriteResult


class ChatWriteRequestRepository:
    """REST write idempotency repository."""

    async def create_idempotent(
        self,
        session: WriteSession,
        create: ChatWriteRequestCreate,
    ) -> IdempotentChatWriteResult:
        """Atomically create ChatWriteRequest or fetch existing row.

        :return: Named request result; ``created`` is False for a retry.
        """
        insert = pg_insert(RDBChatWriteRequest).values(
            id=uuid7().hex,
            session_id=create.session_id,
            requester_user_id=create.requester_user_id,
            creation_agent_id=create.creation_agent_id,
            client_request_id=create.client_request_id,
            write_type=create.write_type,
            accepted_type=create.accepted_type,
            accepted_id=create.accepted_id,
            history_reload_required=create.history_reload_required,
            payload=create.payload,
        )
        if create.creation_agent_id is None:
            insert = insert.on_conflict_do_nothing(
                constraint="uq_chat_write_requests_session_requester_client_request"
            )
        else:
            insert = insert.on_conflict_do_nothing(
                index_elements=[
                    RDBChatWriteRequest.creation_agent_id,
                    RDBChatWriteRequest.requester_user_id,
                    RDBChatWriteRequest.client_request_id,
                ],
                index_where=RDBChatWriteRequest.creation_agent_id.is_not(None),
            )
        stmt = insert.returning(RDBChatWriteRequest)
        result = await session.write_session.execute(stmt)
        rdb = result.scalar_one_or_none()
        if rdb is not None:
            return IdempotentChatWriteResult(record=self._build(rdb), created=True)
        if create.creation_agent_id is None:
            existing = await self.get_by_client_request_id(
                session,
                session_id=create.session_id,
                requester_user_id=create.requester_user_id,
                client_request_id=create.client_request_id,
            )
        else:
            existing = await self.get_by_session_creation_client_request_id(
                session,
                agent_id=create.creation_agent_id,
                requester_user_id=create.requester_user_id,
                client_request_id=create.client_request_id,
            )
        if existing is None:
            raise RuntimeError("Idempotent chat write request lookup failed")
        return IdempotentChatWriteResult(record=existing, created=False)

    async def get_by_session_creation_client_request_id(
        self,
        session: ReadSession,
        *,
        agent_id: str,
        requester_user_id: str,
        client_request_id: str,
    ) -> ChatWriteRequest | None:
        """Fetch an Agent-scoped Session creation request."""
        result = await session.read_session.execute(
            sa.select(RDBChatWriteRequest).where(
                RDBChatWriteRequest.creation_agent_id == agent_id,
                RDBChatWriteRequest.requester_user_id == requester_user_id,
                RDBChatWriteRequest.client_request_id == client_request_id,
            )
        )
        rdb = result.scalar_one_or_none()
        if rdb is None:
            return None
        return self._build(rdb)

    async def get_by_client_request_id(
        self,
        session: ReadSession,
        *,
        session_id: str,
        requester_user_id: str,
        client_request_id: str,
    ) -> ChatWriteRequest | None:
        """Fetch REST write record by client request ID."""
        result = await session.read_session.execute(
            sa.select(RDBChatWriteRequest).where(
                RDBChatWriteRequest.session_id == session_id,
                RDBChatWriteRequest.requester_user_id == requester_user_id,
                RDBChatWriteRequest.client_request_id == client_request_id,
            )
        )
        rdb = result.scalar_one_or_none()
        if rdb is None:
            return None
        return self._build(rdb)

    async def delete_by_requester_user_id(
        self,
        session: WriteSession,
        *,
        requester_user_id: str,
    ) -> int:
        """Delete retained idempotency records owned by one User."""
        result = mutation_result(
            await session.write_session.execute(
                sa.delete(RDBChatWriteRequest).where(
                    RDBChatWriteRequest.requester_user_id == requester_user_id
                )
            )
        )
        await session.write_session.flush()
        return result.rowcount or 0

    def _build(self, rdb: RDBChatWriteRequest) -> ChatWriteRequest:
        """Convert RDB model to domain model."""
        return ChatWriteRequest(
            id=rdb.id,
            session_id=rdb.session_id,
            requester_user_id=rdb.requester_user_id,
            creation_agent_id=rdb.creation_agent_id,
            client_request_id=rdb.client_request_id,
            write_type=rdb.write_type,
            accepted_type=rdb.accepted_type,
            accepted_id=rdb.accepted_id,
            history_reload_required=rdb.history_reload_required,
            payload=rdb.payload,
            created_at=rdb.created_at,
        )
