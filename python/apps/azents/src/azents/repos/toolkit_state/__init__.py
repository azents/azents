"""Toolkit State repository."""

import sqlalchemy as sa
from azcommon.uuid import uuid7
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from azents.rdb.models.toolkit_state import RDBToolkitState

from .data import ToolkitStateRecord, ToolkitStateUpsert


class ToolkitStateConflictError(Exception):
    """Toolkit State optimistic lock conflict."""


class ToolkitStateRepository:
    """Session-bound Toolkit State CRUD repository."""

    async def get(
        self,
        session: AsyncSession,
        *,
        agent_id: str,
        session_id: str,
        toolkit_namespace: str,
        state_name: str,
    ) -> ToolkitStateRecord | None:
        """Fetch Toolkit State by identity."""
        stmt = sa.select(RDBToolkitState).where(
            RDBToolkitState.agent_id == agent_id,
            RDBToolkitState.session_id == session_id,
            RDBToolkitState.toolkit_namespace == toolkit_namespace,
            RDBToolkitState.state_name == state_name,
        )
        result = await session.execute(stmt)
        rdb = result.scalar_one_or_none()
        if rdb is None:
            return None
        return self._build(rdb)

    async def save(
        self,
        session: AsyncSession,
        state: ToolkitStateUpsert,
    ) -> ToolkitStateRecord:
        """Store Toolkit State based on optimistic lock."""
        if state.expected_version is None:
            stmt = (
                insert(RDBToolkitState)
                .values(
                    id=uuid7().hex,
                    agent_id=state.agent_id,
                    session_id=state.session_id,
                    toolkit_namespace=state.toolkit_namespace,
                    state_name=state.state_name,
                    state_json=state.state_json,
                    schema_version=state.schema_version,
                    version=1,
                )
                .on_conflict_do_nothing(constraint="uq_toolkit_states_identity")
                .returning(RDBToolkitState)
            )
            result = await session.execute(stmt)
            await session.flush()
            rdb = result.scalar_one_or_none()
            if rdb is None:
                raise ToolkitStateConflictError(
                    "Toolkit State already exists for identity"
                )
            return self._build(rdb)

        stmt = (
            sa.update(RDBToolkitState)
            .where(
                RDBToolkitState.agent_id == state.agent_id,
                RDBToolkitState.session_id == state.session_id,
                RDBToolkitState.toolkit_namespace == state.toolkit_namespace,
                RDBToolkitState.state_name == state.state_name,
                RDBToolkitState.version == state.expected_version,
            )
            .values(
                state_json=state.state_json,
                schema_version=state.schema_version,
                version=RDBToolkitState.version + 1,
                updated_at=sa.func.now(),
            )
            .returning(RDBToolkitState)
        )

        result = await session.execute(stmt)
        await session.flush()
        rdb = result.scalar_one_or_none()
        if rdb is None:
            raise ToolkitStateConflictError("Toolkit State version conflict")
        return self._build(rdb)

    def _build(self, rdb: RDBToolkitState) -> ToolkitStateRecord:
        """Convert RDB model to domain model."""
        return ToolkitStateRecord(
            id=rdb.id,
            agent_id=rdb.agent_id,
            session_id=rdb.session_id,
            toolkit_namespace=rdb.toolkit_namespace,
            state_name=rdb.state_name,
            state_json=rdb.state_json,
            schema_version=rdb.schema_version,
            version=rdb.version,
            created_at=rdb.created_at,
            updated_at=rdb.updated_at,
        )
