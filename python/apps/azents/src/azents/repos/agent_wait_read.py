"""Completed descendant reads used between application mailbox checks."""

from dataclasses import dataclass
from typing import Annotated

import sqlalchemy as sa
from fastapi import Depends

from azents.core.enums import EventKind
from azents.rdb.deps import get_session_manager
from azents.rdb.models.event import RDBEvent
from azents.rdb.session import SessionManager
from azents.rdb.session_capabilities import WriteSession
from azents.repos.agent_execution import AgentRunRepository
from azents.repos.agent_session import AgentSessionRepository
from azents.repos.agent_wait_read_data import (
    AgentWaitDescendantSnapshot,
    AgentWaitDescendantState,
)


@dataclass(frozen=True)
class AgentWaitReadRepository:
    """Read descendants without locks or application mailbox callbacks."""

    session_manager: Annotated[
        SessionManager[WriteSession], Depends(get_session_manager)
    ]
    agent_session_repository: Annotated[
        AgentSessionRepository, Depends(AgentSessionRepository)
    ]
    agent_run_repository: Annotated[AgentRunRepository, Depends(AgentRunRepository)]

    async def process_revision(
        self, session_id: str, runtime_id: str, runner_generation: int
    ) -> int:
        """Recover committed observation position, independent of compaction."""
        metadata = RDBEvent.payload["metadata"]
        statement = sa.select(
            sa.func.max(
                sa.cast(metadata["shell_wait_revision"].as_string(), sa.BigInteger)
            )
        ).where(
            RDBEvent.session_id == session_id,
            RDBEvent.kind == EventKind.CLIENT_TOOL_RESULT,
            RDBEvent.reverted.is_(False),
            RDBEvent.payload["name"].as_string() == "wait",
            RDBEvent.payload["status"].as_string() == "completed",
            metadata["shell_wait_runtime_id"].as_string() == runtime_id,
            sa.cast(metadata["shell_wait_generation"].as_string(), sa.BigInteger)
            == runner_generation,
        )
        async with self.session_manager() as session:
            revision = await session.read_session.scalar(statement)
        return revision if revision is not None else 0

    async def descendants(self, session_id: str) -> AgentWaitDescendantSnapshot:
        """Return the original descendant sequence and latest durable facts."""
        async with self.session_manager() as session:
            current = (
                await self.agent_session_repository.get_session_agent_by_session_id(
                    session,
                    session_id,
                )
            )
            if current is None:
                result = AgentWaitDescendantSnapshot(descendants=())
            else:
                descendants = (
                    await self.agent_session_repository.list_descendant_session_agents(
                        session,
                        session_agent_id=current.id,
                        include_self=False,
                    )
                )
                session_ids = [agent.agent_session_id for agent in descendants]
                sessions = await self.agent_session_repository.list_by_ids(
                    session,
                    agent_session_ids=session_ids,
                )
                runs = await self.agent_run_repository.list_latest_by_session_ids(
                    session,
                    session_ids=session_ids,
                )
                result = AgentWaitDescendantSnapshot(
                    descendants=tuple(
                        AgentWaitDescendantState(
                            session_id=agent.agent_session_id,
                            path=agent.path,
                            session=sessions.get(agent.agent_session_id),
                            run=runs.get(agent.agent_session_id),
                        )
                        for agent in descendants
                    )
                )
        return result
