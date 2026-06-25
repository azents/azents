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
    AgentSessionPrimaryKind,
    AgentSessionRunState,
    AgentSessionStartReason,
    AgentSessionStatus,
)
from azents.rdb.models.agent_runtime import RDBAgentRuntime
from azents.rdb.models.agent_session import RDBAgentSession

from .data import AgentSession, AgentSessionCreate, PendingSessionCommand


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
            primary_kind=create.primary_kind,
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

    async def lock_by_id(
        self,
        session: AsyncSession,
        agent_session_id: str,
    ) -> AgentSession | None:
        """Fetch AgentSession by ID with a row lock."""
        result = await session.execute(
            sa.select(RDBAgentSession)
            .where(RDBAgentSession.id == agent_session_id)
            .with_for_update()
        )
        rdb = result.scalar_one_or_none()
        if rdb is None:
            return None
        return self._build(rdb)

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
        """Compatibility wrapper ensuring the Agent's team primary session."""
        return await self.ensure_team_primary_for_runtime(session, runtime_id)

    async def ensure_team_primary_for_runtime(
        self,
        session: AsyncSession,
        runtime_id: str,
    ) -> AgentSession:
        """Ensure active team primary AgentSession for Runtime's Agent.

        :param session: Database session
        :param runtime_id: AgentRuntime ID
        :return: active team primary AgentSession
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

    async def get_team_primary_by_agent_id(
        self,
        session: AsyncSession,
        agent_id: str,
    ) -> AgentSession | None:
        """Fetch active team primary AgentSession of Agent."""
        result = await session.execute(
            sa.select(RDBAgentSession).where(
                RDBAgentSession.agent_id == agent_id,
                RDBAgentSession.primary_kind == AgentSessionPrimaryKind.TEAM_PRIMARY,
                RDBAgentSession.status == AgentSessionStatus.ACTIVE,
            )
        )
        rdb = result.scalar_one_or_none()
        if rdb is None:
            return None
        return self._build(rdb)

    async def _ensure_active_for_runtime(
        self,
        session: AsyncSession,
        runtime: RDBAgentRuntime,
    ) -> AgentSession:
        """Fetch or create active team primary AgentSession for Runtime's Agent."""
        existing_primary = await self.get_team_primary_by_agent_id(
            session,
            runtime.agent_id,
        )
        if existing_primary is not None:
            return existing_primary

        active = await self.get_active_by_runtime_id(session, runtime.id)
        if active is not None:
            promoted = await self._promote_active_to_team_primary(
                session,
                active.id,
            )
            if promoted is not None:
                return promoted

        return await self._create_team_primary_if_absent(
            session,
            runtime,
            start_reason=AgentSessionStartReason.INITIAL,
        )

    async def _promote_active_to_team_primary(
        self,
        session: AsyncSession,
        session_id: str,
    ) -> AgentSession | None:
        """Promote an existing active AgentSession to team primary."""
        result = await session.execute(
            sa.update(RDBAgentSession)
            .where(
                RDBAgentSession.id == session_id,
                RDBAgentSession.status == AgentSessionStatus.ACTIVE,
            )
            .values(primary_kind=AgentSessionPrimaryKind.TEAM_PRIMARY)
            .returning(RDBAgentSession)
        )
        rdb = result.scalar_one_or_none()
        if rdb is None:
            return None
        await session.flush()
        return self._build(rdb)

    async def _create_team_primary_if_absent(
        self,
        session: AsyncSession,
        runtime: RDBAgentRuntime,
        *,
        start_reason: AgentSessionStartReason,
    ) -> AgentSession:
        """Create team primary AgentSession race-safely or return existing row."""
        result = await session.execute(
            pg_insert(RDBAgentSession)
            .values(
                id=uuid7().hex,
                workspace_id=runtime.workspace_id,
                agent_runtime_id=runtime.id,
                agent_id=runtime.agent_id,
                status=AgentSessionStatus.ACTIVE,
                primary_kind=AgentSessionPrimaryKind.TEAM_PRIMARY,
                start_reason=start_reason,
            )
            .on_conflict_do_nothing(
                index_elements=[RDBAgentSession.agent_id],
                index_where=sa.text(
                    "status = 'active' AND primary_kind = 'team_primary'"
                ),
            )
            .returning(RDBAgentSession)
        )
        rdb = result.scalar_one_or_none()
        if rdb is not None:
            return self._build(rdb)

        primary = await self.get_team_primary_by_agent_id(session, runtime.agent_id)
        if primary is None:
            raise RuntimeError("Team primary AgentSession conflict target not found")
        return primary

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

    async def mark_running(self, session: AsyncSession, session_id: str) -> None:
        """Transition AgentSession run state to RUNNING."""
        await session.execute(
            sa.update(RDBAgentSession)
            .where(RDBAgentSession.id == session_id)
            .values(
                run_state=AgentSessionRunState.RUNNING,
                run_heartbeat_at=sa.func.now(),
            )
        )
        await session.flush()

    async def mark_running_for_input_wakeup(
        self,
        session: AsyncSession,
        session_id: str,
    ) -> None:
        """Transition AgentSession to RUNNING recovery target on buffered input."""
        await session.execute(
            sa.update(RDBAgentSession)
            .where(
                RDBAgentSession.id == session_id,
                RDBAgentSession.run_state != AgentSessionRunState.RUNNING,
            )
            .values(
                run_state=AgentSessionRunState.RUNNING,
                run_heartbeat_at=sa.func.now(),
            )
        )
        await session.flush()

    async def enqueue_pending_command(
        self,
        session: AsyncSession,
        *,
        session_id: str,
        command_id: str,
        command_name: str,
        payload: dict[str, object],
        user_id: str | None,
    ) -> AgentSession | None:
        """Store single pending command in idle AgentSession and mark running."""
        result = await session.execute(
            sa.update(RDBAgentSession)
            .where(
                RDBAgentSession.id == session_id,
                RDBAgentSession.run_state == AgentSessionRunState.IDLE,
                RDBAgentSession.pending_command_id.is_(None),
            )
            .values(
                pending_command_id=command_id,
                pending_command_name=command_name,
                pending_command_payload=payload,
                pending_command_user_id=user_id,
                pending_command_created_at=sa.func.now(),
                run_state=AgentSessionRunState.RUNNING,
                run_heartbeat_at=sa.func.now(),
            )
            .returning(RDBAgentSession)
        )
        rdb = result.scalar_one_or_none()
        if rdb is None:
            return None
        await session.flush()
        return self._build(rdb)

    async def get_pending_command_by_session_id(
        self,
        session: AsyncSession,
        session_id: str,
    ) -> PendingSessionCommand | None:
        """Fetch pending command for AgentSession."""
        result = await session.execute(
            sa.select(RDBAgentSession).where(
                RDBAgentSession.id == session_id,
                RDBAgentSession.pending_command_id.is_not(None),
            )
        )
        rdb = result.scalar_one_or_none()
        if (
            rdb is None
            or rdb.pending_command_id is None
            or rdb.pending_command_name is None
            or rdb.pending_command_payload is None
            or rdb.pending_command_created_at is None
        ):
            return None
        return PendingSessionCommand(
            id=rdb.pending_command_id,
            name=rdb.pending_command_name,
            payload=dict(rdb.pending_command_payload),
            user_id=rdb.pending_command_user_id,
            created_at=rdb.pending_command_created_at,
        )

    async def clear_pending_command(
        self,
        session: AsyncSession,
        *,
        session_id: str,
        command_id: str,
    ) -> None:
        """Remove processed pending command."""
        await session.execute(
            sa.update(RDBAgentSession)
            .where(
                RDBAgentSession.id == session_id,
                RDBAgentSession.pending_command_id == command_id,
            )
            .values(
                pending_command_id=None,
                pending_command_name=None,
                pending_command_payload=None,
                pending_command_user_id=None,
                pending_command_created_at=None,
            )
        )
        await session.flush()

    async def request_stop(
        self,
        session: AsyncSession,
        *,
        session_id: str,
        stop_request_id: str,
        user_id: str | None,
    ) -> AgentSession | None:
        """Record stop intent on running AgentSession."""
        result = await session.execute(
            sa.update(RDBAgentSession)
            .where(
                RDBAgentSession.id == session_id,
                RDBAgentSession.run_state == AgentSessionRunState.RUNNING,
            )
            .values(
                stop_requested_at=sa.func.now(),
                stop_requested_by=user_id,
                stop_request_id=stop_request_id,
            )
            .returning(RDBAgentSession)
        )
        rdb = result.scalar_one_or_none()
        if rdb is None:
            return None
        await session.flush()
        return self._build(rdb)

    async def has_stop_request(
        self,
        session: AsyncSession,
        session_id: str,
    ) -> bool:
        """Check whether AgentSession has stop intent."""
        result = await session.execute(
            sa.select(RDBAgentSession.id).where(
                RDBAgentSession.id == session_id,
                RDBAgentSession.stop_requested_at.is_not(None),
            )
        )
        return result.scalar_one_or_none() is not None

    async def clear_stop_request(
        self,
        session: AsyncSession,
        session_id: str,
    ) -> None:
        """Remove processed stop intent."""
        await session.execute(
            sa.update(RDBAgentSession)
            .where(RDBAgentSession.id == session_id)
            .values(
                stop_requested_at=None,
                stop_requested_by=None,
                stop_request_id=None,
            )
        )
        await session.flush()

    async def mark_idle(self, session: AsyncSession, session_id: str) -> None:
        """Transition AgentSession run state to IDLE."""
        await session.execute(
            sa.update(RDBAgentSession)
            .where(RDBAgentSession.id == session_id)
            .values(
                run_state=AgentSessionRunState.IDLE,
                stop_requested_at=None,
                stop_requested_by=None,
                stop_request_id=None,
            )
        )
        await session.flush()

    async def heartbeat_running(self, session: AsyncSession, session_id: str) -> None:
        """Update heartbeat time of RUNNING AgentSession."""
        await session.execute(
            sa.update(RDBAgentSession)
            .where(
                RDBAgentSession.id == session_id,
                RDBAgentSession.run_state == AgentSessionRunState.RUNNING,
            )
            .values(run_heartbeat_at=sa.func.now())
        )
        await session.flush()

    async def find_stuck_running(
        self,
        session: AsyncSession,
        *,
        stale_threshold: datetime.timedelta,
        limit: int,
    ) -> list[AgentSession]:
        """Fetch old RUNNING AgentSession list."""
        cutoff = sa.func.now() - stale_threshold
        result = await session.execute(
            sa.select(RDBAgentSession)
            .where(
                RDBAgentSession.status == AgentSessionStatus.ACTIVE,
                RDBAgentSession.run_state == AgentSessionRunState.RUNNING,
                RDBAgentSession.run_heartbeat_at < cutoff,
            )
            .order_by(RDBAgentSession.run_heartbeat_at)
            .limit(limit)
        )
        return [self._build(rdb) for rdb in result.scalars()]

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
                primary_kind=AgentSessionPrimaryKind.TEAM_PRIMARY,
                start_reason=start_reason,
            ),
        )
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
            primary_kind=rdb.primary_kind,
            start_reason=rdb.start_reason,
            end_reason=rdb.end_reason,
            started_at=rdb.started_at,
            lifecycle_started_at=rdb.lifecycle_started_at,
            run_state=rdb.run_state,
            run_heartbeat_at=rdb.run_heartbeat_at,
            pending_command_id=rdb.pending_command_id,
            pending_command_name=rdb.pending_command_name,
            pending_command_payload=rdb.pending_command_payload,
            pending_command_user_id=rdb.pending_command_user_id,
            pending_command_created_at=rdb.pending_command_created_at,
            stop_requested_at=rdb.stop_requested_at,
            stop_requested_by=rdb.stop_requested_by,
            stop_request_id=rdb.stop_request_id,
            ended_at=rdb.ended_at,
            created_at=rdb.created_at,
            updated_at=rdb.updated_at,
        )
