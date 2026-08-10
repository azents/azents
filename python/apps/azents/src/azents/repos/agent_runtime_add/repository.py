"""Persist exact Runtime addition idempotency receipts."""

import sqlalchemy as sa
from azcommon.uuid import uuid7
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from azents.rdb.models.agent_runtime_add import RDBAgentRuntimeAddReceipt

from .data import (
    AgentRuntimeAddReceipt,
    AgentRuntimeAddReceiptCreate,
    AgentRuntimeAddReceiptCreateResult,
)


class AgentRuntimeAddReceiptRepository:
    """Repository for committed Runtime addition receipts."""

    async def get_by_agent_idempotency_key(
        self,
        session: AsyncSession,
        *,
        agent_id: str,
        idempotency_key: str,
    ) -> AgentRuntimeAddReceipt | None:
        """Fetch one receipt by its Agent-scoped idempotency identity."""
        row = await session.scalar(
            sa.select(RDBAgentRuntimeAddReceipt).where(
                RDBAgentRuntimeAddReceipt.agent_id == agent_id,
                RDBAgentRuntimeAddReceipt.idempotency_key == idempotency_key,
            )
        )
        return None if row is None else self._build(row)

    async def create_or_get(
        self,
        session: AsyncSession,
        create: AgentRuntimeAddReceiptCreate,
    ) -> AgentRuntimeAddReceiptCreateResult:
        """Create one receipt or return the concurrent idempotency winner."""
        result = await session.execute(
            insert(RDBAgentRuntimeAddReceipt)
            .values(id=uuid7().hex, **create.model_dump())
            .on_conflict_do_nothing(
                index_elements=["agent_id", "idempotency_key"],
            )
            .returning(RDBAgentRuntimeAddReceipt)
        )
        row = result.scalar_one_or_none()
        if row is not None:
            await session.flush()
            return AgentRuntimeAddReceiptCreateResult(
                receipt=self._build(row),
                created=True,
            )
        existing = await self.get_by_agent_idempotency_key(
            session,
            agent_id=create.agent_id,
            idempotency_key=create.idempotency_key,
        )
        if existing is None:
            raise RuntimeError("Runtime addition receipt creation failed")
        return AgentRuntimeAddReceiptCreateResult(
            receipt=existing,
            created=False,
        )

    def _build(self, row: RDBAgentRuntimeAddReceipt) -> AgentRuntimeAddReceipt:
        """Build one receipt domain value."""
        return AgentRuntimeAddReceipt(
            id=row.id,
            agent_id=row.agent_id,
            workspace_id=row.workspace_id,
            idempotency_key=row.idempotency_key,
            workspace_runtime_profile_id=row.workspace_runtime_profile_id,
            expected_capability_version=row.expected_capability_version,
            committed_capability_version=row.committed_capability_version,
            committed_runtime_profile_selection_version=(
                row.committed_runtime_profile_selection_version
            ),
            agent_runtime_id=row.agent_runtime_id,
            runtime_configuration_revision_id=(row.runtime_configuration_revision_id),
            runtime_desired_generation=row.runtime_desired_generation,
            created_at=row.created_at,
        )
