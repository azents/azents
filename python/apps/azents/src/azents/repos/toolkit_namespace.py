"""Durable Agent-local Toolkit namespace allocation."""

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from azents.rdb.models.toolkit import (
    RDBAgentToolkitNamespaceReservation,
    RDBAgentToolkitNamespaceSequence,
)
from azents.repos.toolkit_namespace_data import AgentToolkitNamespaceReservation


class ToolkitNamespaceRepository:
    """Allocate and retain Agent-local Toolkit namespaces."""

    async def get_active(
        self,
        session: AsyncSession,
        *,
        agent_id: str,
        toolkit_id: str,
    ) -> AgentToolkitNamespaceReservation | None:
        """Return the active reservation for one Agent and Toolkit."""
        result = await session.execute(
            sa.select(RDBAgentToolkitNamespaceReservation).where(
                RDBAgentToolkitNamespaceReservation.agent_id == agent_id,
                RDBAgentToolkitNamespaceReservation.toolkit_id == toolkit_id,
            )
        )
        row = result.scalar_one_or_none()
        return None if row is None else self._build(row)

    async def ensure_active(
        self,
        session: AsyncSession,
        *,
        agent_id: str,
        toolkit_id: str,
        base_slug: str,
    ) -> AgentToolkitNamespaceReservation:
        """Reuse a matching active reservation or allocate a new one.

        The caller must hold the Agent row lock for the complete transaction.
        """
        existing = await self.get_active(
            session,
            agent_id=agent_id,
            toolkit_id=toolkit_id,
        )
        if existing is not None and existing.base_slug == base_slug:
            return existing
        if existing is not None:
            await session.execute(
                sa.update(RDBAgentToolkitNamespaceReservation)
                .where(RDBAgentToolkitNamespaceReservation.id == existing.id)
                .values(toolkit_id=None)
            )
            await session.flush()
        return await self._allocate(
            session,
            agent_id=agent_id,
            toolkit_id=toolkit_id,
            base_slug=base_slug,
        )

    async def _allocate(
        self,
        session: AsyncSession,
        *,
        agent_id: str,
        toolkit_id: str,
        base_slug: str,
    ) -> AgentToolkitNamespaceReservation:
        sequence_result = await session.execute(
            sa.select(RDBAgentToolkitNamespaceSequence)
            .where(
                RDBAgentToolkitNamespaceSequence.agent_id == agent_id,
                RDBAgentToolkitNamespaceSequence.base_slug == base_slug,
            )
            .with_for_update()
        )
        sequence = sequence_result.scalar_one_or_none()
        if sequence is None:
            sequence = RDBAgentToolkitNamespaceSequence(
                agent_id=agent_id,
                base_slug=base_slug,
            )
            session.add(sequence)
            await session.flush()

        while True:
            sequence.last_ordinal += 1
            ordinal = sequence.last_ordinal
            namespace = base_slug if ordinal == 1 else f"{base_slug}_{ordinal}"
            conflict = await session.scalar(
                sa.select(RDBAgentToolkitNamespaceReservation.id).where(
                    RDBAgentToolkitNamespaceReservation.agent_id == agent_id,
                    RDBAgentToolkitNamespaceReservation.namespace == namespace,
                )
            )
            if conflict is not None:
                continue
            row = RDBAgentToolkitNamespaceReservation(
                agent_id=agent_id,
                toolkit_id=toolkit_id,
                base_slug=base_slug,
                ordinal=ordinal,
                namespace=namespace,
            )
            session.add(row)
            await session.flush()
            return self._build(row)

    @staticmethod
    def _build(
        row: RDBAgentToolkitNamespaceReservation,
    ) -> AgentToolkitNamespaceReservation:
        return AgentToolkitNamespaceReservation.model_validate(
            row, from_attributes=True
        )
