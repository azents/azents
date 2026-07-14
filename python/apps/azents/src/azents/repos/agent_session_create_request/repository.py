"""AgentSession create-request idempotency repository."""

import datetime

import sqlalchemy as sa
from azcommon.uuid import uuid7
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from azents.rdb.models.agent_session_create_request import (
    RDBAgentSessionCreateRequest,
)

from .data import (
    AgentSessionCreateRequestClaim,
    AgentSessionCreateRequestClaimResult,
    AgentSessionCreateRequestRecord,
)


class AgentSessionCreateRequestRepository:
    """Own global AgentSession create-request idempotency authority."""

    async def claim(
        self,
        session: AsyncSession,
        claim: AgentSessionCreateRequestClaim,
    ) -> AgentSessionCreateRequestClaimResult:
        """Claim one request key or return its committed existing authority."""
        result = await session.execute(
            pg_insert(RDBAgentSessionCreateRequest)
            .values(
                id=uuid7().hex,
                user_id=claim.user_id,
                agent_id=claim.agent_id,
                client_request_id=claim.client_request_id,
                payload_hash=claim.payload_hash,
                agent_session_id=None,
                input_buffer_id=None,
                input_buffer_snapshot=None,
                completed_at=None,
            )
            .on_conflict_do_nothing(
                constraint=RDBAgentSessionCreateRequest.UQ_USER_AGENT_CLIENT_REQUEST
            )
            .returning(RDBAgentSessionCreateRequest)
        )
        rdb = result.scalar_one_or_none()
        if rdb is not None:
            return AgentSessionCreateRequestClaimResult(
                record=self._build(rdb),
                claimed=True,
            )
        existing = await self.get_by_key(
            session,
            user_id=claim.user_id,
            agent_id=claim.agent_id,
            client_request_id=claim.client_request_id,
        )
        if existing is None:
            raise RuntimeError("AgentSession create-request authority lookup failed")
        if (
            existing.agent_session_id is None
            or existing.input_buffer_id is None
            or existing.input_buffer_snapshot is None
            or existing.completed_at is None
        ):
            raise RuntimeError("Committed AgentSession create request is incomplete")
        return AgentSessionCreateRequestClaimResult(
            record=existing,
            claimed=False,
        )

    async def complete(
        self,
        session: AsyncSession,
        *,
        request_id: str,
        agent_session_id: str,
        input_buffer_id: str,
        input_buffer_snapshot: dict[str, object],
        completed_at: datetime.datetime,
    ) -> AgentSessionCreateRequestRecord:
        """Complete the authority in the transaction that creates its resources."""
        result = await session.execute(
            sa.update(RDBAgentSessionCreateRequest)
            .where(
                RDBAgentSessionCreateRequest.id == request_id,
                RDBAgentSessionCreateRequest.agent_session_id.is_(None),
                RDBAgentSessionCreateRequest.input_buffer_id.is_(None),
                RDBAgentSessionCreateRequest.completed_at.is_(None),
            )
            .values(
                agent_session_id=agent_session_id,
                input_buffer_id=input_buffer_id,
                input_buffer_snapshot=input_buffer_snapshot,
                completed_at=completed_at,
            )
            .returning(RDBAgentSessionCreateRequest)
        )
        rdb = result.scalar_one_or_none()
        if rdb is None:
            raise RuntimeError("AgentSession create-request completion lost authority")
        return self._build(rdb)

    async def abandon_pending_claim(
        self,
        session: AsyncSession,
        *,
        request_id: str,
    ) -> None:
        """Delete an incomplete claim when final authorization rejects the request."""
        result = await session.execute(
            sa.delete(RDBAgentSessionCreateRequest)
            .where(
                RDBAgentSessionCreateRequest.id == request_id,
                RDBAgentSessionCreateRequest.agent_session_id.is_(None),
                RDBAgentSessionCreateRequest.input_buffer_id.is_(None),
                RDBAgentSessionCreateRequest.input_buffer_snapshot.is_(None),
                RDBAgentSessionCreateRequest.completed_at.is_(None),
            )
            .returning(RDBAgentSessionCreateRequest.id)
        )
        if result.scalar_one_or_none() is None:
            raise RuntimeError(
                "AgentSession create-request pending claim was not released"
            )

    async def get_by_key(
        self,
        session: AsyncSession,
        *,
        user_id: str,
        agent_id: str,
        client_request_id: str,
    ) -> AgentSessionCreateRequestRecord | None:
        """Fetch one create-request authority by its global scope key."""
        result = await session.execute(
            sa.select(RDBAgentSessionCreateRequest).where(
                RDBAgentSessionCreateRequest.user_id == user_id,
                RDBAgentSessionCreateRequest.agent_id == agent_id,
                RDBAgentSessionCreateRequest.client_request_id == client_request_id,
            )
        )
        rdb = result.scalar_one_or_none()
        return None if rdb is None else self._build(rdb)

    def _build(
        self,
        rdb: RDBAgentSessionCreateRequest,
    ) -> AgentSessionCreateRequestRecord:
        """Convert one ORM row to its data model."""
        return AgentSessionCreateRequestRecord(
            id=rdb.id,
            user_id=rdb.user_id,
            agent_id=rdb.agent_id,
            client_request_id=rdb.client_request_id,
            payload_hash=rdb.payload_hash,
            agent_session_id=rdb.agent_session_id,
            input_buffer_id=rdb.input_buffer_id,
            input_buffer_snapshot=rdb.input_buffer_snapshot,
            created_at=rdb.created_at,
            completed_at=rdb.completed_at,
        )
