"""Session Primary Binding ownership and fail-closed database composition."""

from dataclasses import dataclass

import sqlalchemy as sa

from azents.core.enums import (
    AgentLifecycleStatus,
    AgentSessionStartReason,
    AgentSessionStatus,
    ExternalChannelConnectionStatus,
    ExternalChannelResourceStatus,
    ExternalChannelRouteCatalogStatus,
)
from azents.rdb.models.agent import RDBAgent
from azents.rdb.models.agent_session import RDBAgentSession
from azents.rdb.models.external_channel import (
    RDBExternalChannelAgentRoute,
    RDBExternalChannelBinding,
    RDBExternalChannelConnection,
    RDBExternalChannelResource,
)
from azents.rdb.session_capabilities import ReadSession, WriteSession


class SessionPrimaryChannelUnavailable(ValueError):
    """Primary authority is missing, disconnected, or owned elsewhere."""


class SessionPrimaryChannelAmbiguous(ValueError):
    """A backfill must not choose among multiple connected conversations."""


@dataclass(frozen=True)
class SessionPrimaryAssignment:
    """One unambiguous existing Binding designation, not a new connection."""

    session_id: str
    binding_id: str


class SessionPrimaryChannelRepository:
    """Compose Primary mutations inside existing connection/lifecycle owners."""

    async def get_current(
        self,
        session: ReadSession,
        *,
        workspace_id: str,
        agent_id: str,
        session_id: str,
    ) -> str | None:
        """Resolve exact current authority; invalid Primary never means fallback."""
        row = (
            await session.read_session.execute(
                sa.select(RDBAgentSession.primary_channel_binding_id).where(
                    RDBAgentSession.id == session_id,
                    RDBAgentSession.agent_id == agent_id,
                    RDBAgentSession.workspace_id == workspace_id,
                )
            )
        ).one_or_none()
        if row is None:
            raise SessionPrimaryChannelUnavailable("Primary Session is unavailable.")
        binding_id = row[0]
        if binding_id is not None:
            await self._require_binding(
                session, binding_id=binding_id, session_id=session_id
            )
        return binding_id

    async def set_origin_primary(
        self,
        session: WriteSession,
        *,
        session_id: str,
        binding_id: str,
    ) -> bool:
        """Designate the origin of a channel-created Session without replacement."""
        row = (
            await session.write_session.execute(
                sa.select(
                    RDBAgentSession.start_reason,
                    RDBAgentSession.primary_channel_binding_id,
                ).where(
                    RDBAgentSession.id == session_id,
                    RDBAgentSession.status == AgentSessionStatus.ACTIVE,
                )
            )
        ).one_or_none()
        if row is None:
            raise SessionPrimaryChannelUnavailable("Primary Session is not active.")
        reason, primary = row
        if reason != AgentSessionStartReason.EXTERNAL_CHANNEL or primary is not None:
            return False
        await self._require_single_connected(
            session, session_id=session_id, expected_binding_id=binding_id
        )
        await self._require_binding(
            session, binding_id=binding_id, session_id=session_id
        )
        result = await session.write_session.execute(
            sa.update(RDBAgentSession)
            .where(
                RDBAgentSession.id == session_id,
                RDBAgentSession.status == AgentSessionStatus.ACTIVE,
                RDBAgentSession.primary_channel_binding_id.is_(None),
            )
            .values(primary_channel_binding_id=binding_id)
            .returning(RDBAgentSession.id)
        )
        return result.scalar_one_or_none() is not None

    async def clear_for_binding(
        self,
        session: WriteSession,
        *,
        session_id: str,
        binding_id: str,
    ) -> None:
        """Clear only the exact disconnected authority, preserving other rows."""
        await session.write_session.execute(
            sa.update(RDBAgentSession)
            .where(
                RDBAgentSession.id == session_id,
                RDBAgentSession.primary_channel_binding_id == binding_id,
            )
            .values(primary_channel_binding_id=None)
        )

    async def backfill(
        self, session: WriteSession
    ) -> tuple[SessionPrimaryAssignment, ...]:
        """Validate all candidates before changing any current designation."""
        rows = (
            await session.write_session.execute(
                sa.select(
                    RDBExternalChannelBinding.agent_session_id,
                    RDBExternalChannelBinding.id,
                )
                .join(
                    RDBAgentSession,
                    RDBAgentSession.id == RDBExternalChannelBinding.agent_session_id,
                )
                .where(
                    RDBExternalChannelBinding.disconnected_at.is_(None),
                    RDBAgentSession.primary_channel_binding_id.is_(None),
                )
                .order_by(
                    RDBExternalChannelBinding.agent_session_id,
                    RDBExternalChannelBinding.id,
                )
            )
        ).all()
        assignments: dict[str, SessionPrimaryAssignment] = {}
        for session_id, binding_id in rows:
            if session_id in assignments:
                raise SessionPrimaryChannelAmbiguous(
                    "Multiple connected Bindings require an explicit Primary decision."
                )
            await self._require_binding(
                session, binding_id=binding_id, session_id=session_id
            )
            assignments[session_id] = SessionPrimaryAssignment(
                session_id=session_id, binding_id=binding_id
            )
        applied: list[SessionPrimaryAssignment] = []
        for assignment in assignments.values():
            result = await session.write_session.execute(
                sa.update(RDBAgentSession)
                .where(
                    RDBAgentSession.id == assignment.session_id,
                    RDBAgentSession.primary_channel_binding_id.is_(None),
                )
                .values(primary_channel_binding_id=assignment.binding_id)
                .returning(RDBAgentSession.id)
            )
            if result.scalar_one_or_none() is not None:
                applied.append(assignment)
        return tuple(applied)

    async def _require_single_connected(
        self,
        session: ReadSession,
        *,
        session_id: str,
        expected_binding_id: str,
    ) -> None:
        """Reject ambiguity instead of selecting a convenient conversation."""
        ids = list(
            await session.read_session.scalars(
                sa.select(RDBExternalChannelBinding.id).where(
                    RDBExternalChannelBinding.agent_session_id == session_id,
                    RDBExternalChannelBinding.disconnected_at.is_(None),
                )
            )
        )
        if len(ids) > 1:
            raise SessionPrimaryChannelAmbiguous(
                "Multiple connected Bindings require an explicit Primary decision."
            )
        if ids != [expected_binding_id]:
            raise SessionPrimaryChannelUnavailable("Primary Binding is not connected.")

    async def _require_binding(
        self,
        session: ReadSession,
        *,
        binding_id: str,
        session_id: str,
    ) -> None:
        """Validate the existing Session, Agent, route, connection, and resource."""
        found = await session.read_session.scalar(
            sa.select(RDBExternalChannelBinding.id)
            .join(
                RDBAgentSession,
                RDBAgentSession.id == RDBExternalChannelBinding.agent_session_id,
            )
            .join(RDBAgent, RDBAgent.id == RDBAgentSession.agent_id)
            .join(
                RDBExternalChannelAgentRoute,
                RDBExternalChannelAgentRoute.id == RDBExternalChannelBinding.route_id,
            )
            .join(
                RDBExternalChannelConnection,
                RDBExternalChannelConnection.id
                == RDBExternalChannelAgentRoute.connection_id,
            )
            .join(
                RDBExternalChannelResource,
                RDBExternalChannelResource.id == RDBExternalChannelBinding.resource_id,
            )
            .where(
                RDBExternalChannelBinding.id == binding_id,
                RDBExternalChannelBinding.agent_session_id == session_id,
                RDBExternalChannelBinding.disconnected_at.is_(None),
                RDBAgentSession.status == AgentSessionStatus.ACTIVE,
                RDBExternalChannelAgentRoute.agent_id == RDBAgent.id,
                RDBAgent.workspace_id == RDBAgentSession.workspace_id,
                RDBExternalChannelConnection.workspace_id
                == RDBAgentSession.workspace_id,
                RDBExternalChannelAgentRoute.connection_app_mode
                == RDBExternalChannelConnection.app_mode,
                RDBAgent.lifecycle_status == AgentLifecycleStatus.ACTIVE,
                RDBExternalChannelAgentRoute.catalog_status
                == ExternalChannelRouteCatalogStatus.AVAILABLE,
                RDBExternalChannelConnection.status.in_(
                    (
                        ExternalChannelConnectionStatus.ACTIVE,
                        ExternalChannelConnectionStatus.DEGRADED,
                    )
                ),
                RDBExternalChannelConnection.disconnected_at.is_(None),
                RDBExternalChannelResource.connection_id
                == RDBExternalChannelConnection.id,
                RDBExternalChannelResource.status
                == ExternalChannelResourceStatus.ACTIVE,
            )
        )
        if found is None:
            raise SessionPrimaryChannelUnavailable(
                "Primary Binding is disconnected or has incompatible owners."
            )
