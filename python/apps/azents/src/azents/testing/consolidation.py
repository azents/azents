"""Shared synthetic exact-scope source fixtures for consolidation storage tests."""

import datetime
from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession
from uuid6 import uuid7

from azents.core.agent_session_data import AgentSessionCreate
from azents.core.enums import AgentSessionProductMode, WorkspaceUserRole
from azents.core.historical_memory import HistoricalMemoryCompletion
from azents.core.historical_memory_consolidation import (
    ConsolidationScope,
    ConsolidationUnitKey,
)
from azents.rdb.models.agent import RDBAgent
from azents.rdb.models.historical_memory import RDBHistoricalMemorySource
from azents.rdb.models.workspace import RDBWorkspace
from azents.rdb.models.workspace_user import RDBWorkspaceUser
from azents.rdb.session import SessionManager
from azents.repos.agent_session import AgentSessionRepository
from azents.repos.historical_memory import HistoricalMemoryRepository
from azents.repos.user import UserRepository
from azents.repos.user.data import UserCreate
from azents.testing.model_selection import (
    make_test_model_selection_dict,
    make_test_selectable_model_option_dicts,
)

CONSOLIDATION_FIXTURE_TIME = datetime.datetime(2026, 10, 1, tzinfo=datetime.UTC)


@dataclass(frozen=True)
class ConsolidationCorpus:
    """Synthetic source identities, not a fabricated internal execution Session."""

    team: ConsolidationUnitKey
    personal: ConsolidationUnitKey
    team_source: str
    personal_source: str


async def create_consolidation_source(
    session: AsyncSession,
    *,
    manager: SessionManager[AsyncSession],
    key: ConsolidationUnitKey,
    summary: str | None,
    title: str,
) -> str:
    """Create a real root source and publish its canonical prepared outcome."""
    root = await AgentSessionRepository().create(
        session,
        AgentSessionCreate(
            workspace_id=key.workspace_id,
            agent_id=key.agent_id,
            product_mode=(
                AgentSessionProductMode.TEAM
                if key.scope is ConsolidationScope.TEAM
                else AgentSessionProductMode.USER
            ),
            associated_user_id=key.associated_user_id,
            title=title,
        ),
    )
    session.add(
        RDBHistoricalMemorySource(
            source_session_id=root.id, admitted_at=CONSOLIDATION_FIXTURE_TIME
        )
    )
    await session.flush()
    result = await HistoricalMemoryRepository(manager).publish_completed_in_session(
        session,
        source_session_id=root.id,
        completion=HistoricalMemoryCompletion(
            source_activity_at=CONSOLIDATION_FIXTURE_TIME,
            source_tail_event_id=uuid7().hex,
            prepared_at=CONSOLIDATION_FIXTURE_TIME,
            source_title_snapshot=title,
            summary=summary,
        ),
    )
    assert result is not None
    return root.id


async def seed_consolidation_corpus(
    manager: SessionManager[AsyncSession],
) -> ConsolidationCorpus:
    """Seed independent Team and personal sentinels without Runtime startup."""
    slug = uuid7().hex
    async with manager() as session:
        workspace = RDBWorkspace(name=slug, handle=slug)
        session.add(workspace)
        await session.flush()
        selection = make_test_model_selection_dict()
        agent = RDBAgent(
            workspace_id=workspace.id,
            name=slug,
            model_selection=selection,
            lightweight_model_selection=selection,
            selectable_model_options=make_test_selectable_model_option_dicts(
                model_selection=selection, lightweight_model_selection=selection
            ),
            main_model_label="default",
            lightweight_model_label="lightweight",
            memory_enabled=True,
        )
        session.add(agent)
        await session.flush()
        user = await UserRepository().create(
            session, UserCreate(email=f"{slug}@example.test")
        )
        session.add(
            RDBWorkspaceUser(
                workspace_id=workspace.id,
                user_id=user.id,
                name=slug,
                role=WorkspaceUserRole.MEMBER,
            )
        )
        await session.flush()
        team = ConsolidationUnitKey(
            workspace_id=workspace.id,
            agent_id=agent.id,
            scope=ConsolidationScope.TEAM,
            associated_user_id=None,
        )
        personal = ConsolidationUnitKey(
            workspace_id=workspace.id,
            agent_id=agent.id,
            scope=ConsolidationScope.USER,
            associated_user_id=user.id,
        )
        sources = [
            await create_consolidation_source(
                session,
                manager=manager,
                key=key,
                summary=f"{key.scope.value} sentinel 한글",
                title=key.scope.value,
            )
            for key in (team, personal)
        ]
        await session.commit()
    return ConsolidationCorpus(team, personal, sources[0], sources[1])
