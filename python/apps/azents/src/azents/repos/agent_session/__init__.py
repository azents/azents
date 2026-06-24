"""AgentSession repository."""

import datetime
from dataclasses import dataclass
from typing import Any, cast

import sqlalchemy as sa
from azcommon.uuid import uuid7
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.engine import CursorResult
from sqlalchemy.ext.asyncio import AsyncSession

from azents.core.enums import (
    AgentSessionEndReason,
    AgentSessionStartReason,
    AgentSessionStatus,
)
from azents.rdb.models.agent_runtime import RDBAgentRuntime
from azents.rdb.models.agent_session import RDBAgentSession

from .data import AgentSession, AgentSessionCreate


@dataclass(frozen=True)
class AgentSessionRotation:
    """AgentSession rollover result."""

    previous: AgentSession | None
    current: AgentSession


class AgentSessionRepository:
    """AgentSession CRUD repository."""

    async def create(
        self,
        session: AsyncSession,
        create: AgentSessionCreate,
    ) -> AgentSession:
        """Create AgentSession."""
        rdb = RDBAgentSession(
            workspace_id=create.workspace_id,
            agent_runtime_id=create.agent_runtime_id,
            agent_id=create.agent_id,
            start_reason=create.start_reason,
        )
        session.add(rdb)
        await session.flush()
        return self._build(rdb)

    async def get_by_id(
        self,
        session: AsyncSession,
        agent_session_id: str,
    ) -> AgentSession | None:
        """Fetch AgentSession by ID."""
        rdb = await session.get(RDBAgentSession, agent_session_id)
        if rdb is None:
            return None
        return self._build(rdb)

    async def get_active_by_runtime_id(
        self,
        session: AsyncSession,
        runtime_id: str,
    ) -> AgentSession | None:
        """Fetch active AgentSession of AgentRuntime."""
        result = await session.execute(
            sa.select(RDBAgentSession).where(
                RDBAgentSession.agent_runtime_id == runtime_id,
                RDBAgentSession.status == AgentSessionStatus.ACTIVE,
            )
        )
        rdb = result.scalar_one_or_none()
        if rdb is None:
            return None
        return self._build(rdb)

    async def list_by_workspace(
        self,
        session: AsyncSession,
        workspace_id: str,
    ) -> list[AgentSession]:
        """Fetch workspace AgentSession list in latest-first order."""
        result = await session.execute(
            sa.select(RDBAgentSession)
            .where(RDBAgentSession.workspace_id == workspace_id)
            .order_by(RDBAgentSession.updated_at.desc())
        )
        return [self._build(rdb) for rdb in result.scalars()]

    async def delete_by_id(
        self,
        session: AsyncSession,
        agent_session_id: str,
    ) -> None:
        """Delete AgentSession by ID."""
        await session.execute(
            sa.delete(RDBAgentSession).where(RDBAgentSession.id == agent_session_id)
        )
        await session.flush()

    async def ensure_active(
        self,
        session: AsyncSession,
        runtime_id: str,
    ) -> AgentSession:
        """Ensure active AgentSession of AgentRuntime.

        :param session: Database session
        :param runtime_id: AgentRuntime ID
        :return: active AgentSession
        """
        runtime = await session.get(RDBAgentRuntime, runtime_id)
        if runtime is None:
            raise ValueError("AgentRuntime not found")

        return await self._ensure_active_for_runtime(session, runtime)

    async def ensure_active_with_runtime_lock(
        self,
        session: AsyncSession,
        runtime_id: str,
    ) -> AgentSession:
        """Ensure active AgentSession after acquiring AgentRuntime row lock."""
        result = await session.execute(
            sa.select(RDBAgentRuntime)
            .where(RDBAgentRuntime.id == runtime_id)
            .with_for_update()
        )
        runtime = result.scalar_one_or_none()
        if runtime is None:
            raise ValueError("AgentRuntime not found")

        return await self._ensure_active_for_runtime(session, runtime)

    async def _ensure_active_for_runtime(
        self,
        session: AsyncSession,
        runtime: RDBAgentRuntime,
    ) -> AgentSession:
        """Fetch or create active AgentSession based on Runtime row."""

        if runtime.current_session_id is not None:
            current = await self.get_by_id(session, runtime.current_session_id)
            if current is not None and current.status == AgentSessionStatus.ACTIVE:
                return current

        active = await self.get_active_by_runtime_id(session, runtime.id)
        if active is not None:
            runtime.current_session_id = active.id
            await session.flush()
            return active

        created = await self._create_active_if_absent(
            session,
            runtime,
            start_reason=AgentSessionStartReason.INITIAL,
        )
        runtime.current_session_id = created.id
        await session.flush()
        return created

    async def _create_active_if_absent(
        self,
        session: AsyncSession,
        runtime: RDBAgentRuntime,
        *,
        start_reason: AgentSessionStartReason,
    ) -> AgentSession:
        """Create active AgentSession race-safely or return existing row."""
        result = await session.execute(
            pg_insert(RDBAgentSession)
            .values(
                id=uuid7().hex,
                workspace_id=runtime.workspace_id,
                agent_runtime_id=runtime.id,
                agent_id=runtime.agent_id,
                status=AgentSessionStatus.ACTIVE,
                start_reason=start_reason,
            )
            .on_conflict_do_nothing(
                index_elements=[RDBAgentSession.agent_runtime_id],
                index_where=sa.text("status = 'active'"),
            )
            .returning(RDBAgentSession)
        )
        rdb = result.scalar_one_or_none()
        if rdb is not None:
            return self._build(rdb)

        active = await self.get_active_by_runtime_id(session, runtime.id)
        if active is None:
            raise RuntimeError("Active AgentSession conflict target not found")
        return active

    async def archive(
        self,
        session: AsyncSession,
        agent_session_id: str,
        *,
        ended_at: datetime.datetime,
        end_reason: AgentSessionEndReason | None = None,
    ) -> None:
        """Transition AgentSession to archived state."""
        await session.execute(
            sa.update(RDBAgentSession)
            .where(RDBAgentSession.id == agent_session_id)
            .values(
                status=AgentSessionStatus.ARCHIVED,
                ended_at=ended_at,
                end_reason=end_reason,
            )
        )
        await session.flush()

    async def claim_lifecycle_start(
        self,
        session: AsyncSession,
        agent_session_id: str,
        *,
        now: datetime.datetime,
    ) -> bool:
        """Claim AgentSession lifecycle start marker once initially."""
        result = cast(
            CursorResult[Any],
            await session.execute(
                sa.update(RDBAgentSession)
                .where(
                    RDBAgentSession.id == agent_session_id,
                    RDBAgentSession.lifecycle_started_at.is_(None),
                )
                .values(lifecycle_started_at=now)
            ),
        )
        await session.flush()
        return result.rowcount == 1

    async def get_lifecycle_started_at(
        self,
        session: AsyncSession,
        agent_session_id: str,
    ) -> datetime.datetime | None:
        """Fetch AgentSession lifecycle start marker time."""
        result = await session.execute(
            sa.select(RDBAgentSession.lifecycle_started_at).where(
                RDBAgentSession.id == agent_session_id
            )
        )
        return result.scalar_one_or_none()

    async def rotate_active(
        self,
        session: AsyncSession,
        runtime_id: str,
        *,
        start_reason: AgentSessionStartReason,
        end_reason: AgentSessionEndReason,
        now: datetime.datetime,
    ) -> AgentSession:
        """End current active AgentSession with preservation and create new active.

        :param session: Database session
        :param runtime_id: AgentRuntime ID
        :param start_reason: New AgentSession start reason
        :param end_reason: Existing AgentSession end reason
        :param now: Rotation reference time
        :return: New active AgentSession
        """
        rotation = await self.rotate_active_with_previous(
            session,
            runtime_id,
            start_reason=start_reason,
            end_reason=end_reason,
            now=now,
        )
        return rotation.current

    async def rotate_active_with_previous(
        self,
        session: AsyncSession,
        runtime_id: str,
        *,
        start_reason: AgentSessionStartReason,
        end_reason: AgentSessionEndReason,
        now: datetime.datetime,
    ) -> AgentSessionRotation:
        """Rotate current active AgentSession and return previous session too."""
        result = await session.execute(
            sa.select(RDBAgentRuntime)
            .where(RDBAgentRuntime.id == runtime_id)
            .with_for_update()
        )
        runtime = result.scalar_one_or_none()
        if runtime is None:
            raise ValueError("AgentRuntime not found")

        current = await self.get_active_by_runtime_id(session, runtime_id)
        if current is not None:
            await self.archive(
                session,
                current.id,
                ended_at=now,
                end_reason=end_reason,
            )

        created = await self.create(
            session,
            AgentSessionCreate(
                workspace_id=runtime.workspace_id,
                agent_runtime_id=runtime.id,
                agent_id=runtime.agent_id,
                start_reason=start_reason,
            ),
        )
        runtime.current_session_id = created.id
        await session.flush()
        return AgentSessionRotation(previous=current, current=created)

    def _build(self, rdb: RDBAgentSession) -> AgentSession:
        """Convert RDB model to domain model."""
        return AgentSession(
            id=rdb.id,
            workspace_id=rdb.workspace_id,
            agent_runtime_id=rdb.agent_runtime_id,
            agent_id=rdb.agent_id,
            status=rdb.status,
            start_reason=rdb.start_reason,
            end_reason=rdb.end_reason,
            started_at=rdb.started_at,
            lifecycle_started_at=rdb.lifecycle_started_at,
            ended_at=rdb.ended_at,
            created_at=rdb.created_at,
            updated_at=rdb.updated_at,
        )
