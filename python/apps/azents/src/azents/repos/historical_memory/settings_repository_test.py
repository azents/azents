"""Historical Memory settings repository tests."""

import datetime
from typing import NamedTuple

import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from azents.core.agent_session_data import AgentSessionCreate
from azents.core.enums import (
    AgentSessionProductMode,
    AgentSessionStatus,
    WorkspaceUserRole,
)
from azents.core.historical_memory_settings import HistoricalMemorySettingsScope
from azents.rdb.models.agent import RDBAgent
from azents.rdb.models.agent_runtime import RDBAgentRuntime
from azents.rdb.models.agent_session import RDBAgentSession
from azents.rdb.models.historical_memory import RDBHistoricalMemorySource
from azents.rdb.models.workspace import RDBWorkspace
from azents.rdb.models.workspace_user import RDBWorkspaceUser
from azents.rdb.session import SessionManager
from azents.repos.agent_session import AgentSessionRepository
from azents.repos.historical_memory.settings import (
    HistoricalMemorySettingsRepository,
)
from azents.repos.historical_memory.settings_data import (
    HistoricalMemorySettingsCursorError,
)
from azents.repos.user import UserRepository
from azents.repos.user.data import UserCreate
from azents.testing.model_selection import (
    make_test_model_selection_dict,
    make_test_selectable_model_option_dicts,
)

_NOW = datetime.datetime(2026, 10, 1, 12, 0, tzinfo=datetime.UTC)


async def _create_source(
    session: AsyncSession,
    *,
    workspace_id: str,
    agent_id: str,
    slug: str,
    product_mode: AgentSessionProductMode,
    associated_user_id: str | None,
    activity_at: datetime.datetime,
    prepared_at: datetime.datetime,
    summary: str,
) -> str:
    """Create one prepared Historical Memory source."""
    source = await AgentSessionRepository().create(
        session,
        AgentSessionCreate(
            workspace_id=workspace_id,
            product_mode=product_mode,
            associated_user_id=associated_user_id,
            agent_id=agent_id,
            title=f"{slug} title",
        ),
    )
    source_row = await session.get(RDBAgentSession, source.id)
    assert source_row is not None
    source_row.last_activity_at = activity_at
    historical = RDBHistoricalMemorySource(
        source_session_id=source.id,
        admitted_at=activity_at,
    )
    historical.completed_source_activity_at = activity_at
    historical.completed_source_tail_event_id = slug.ljust(32, "0")[:32]
    historical.prepared_at = prepared_at
    historical.source_title_snapshot = f"{slug} snapshot"
    historical.summary = summary
    session.add(historical)
    await session.flush()
    return source.id


class _SettingsFixture(NamedTuple):
    """Agent scope and two distinct current members."""

    workspace_id: str
    agent_id: str
    user_id: str
    other_user_id: str


async def _fixture(
    session: AsyncSession,
) -> _SettingsFixture:
    """Create one Memory-disabled Agent and two current members."""
    workspace = RDBWorkspace(name="Historical settings", handle="historical-settings")
    session.add(workspace)
    await session.flush()
    selection = make_test_model_selection_dict()
    agent = RDBAgent(
        workspace_id=workspace.id,
        name="Historical settings",
        model_selection=selection,
        lightweight_model_selection=selection,
        selectable_model_options=make_test_selectable_model_option_dicts(
            model_selection=selection,
            lightweight_model_selection=selection,
        ),
        main_model_label="default",
        lightweight_model_label="lightweight",
        memory_enabled=False,
    )
    session.add(agent)
    await session.flush()
    runtime = RDBAgentRuntime(workspace_id=workspace.id, agent_id=agent.id)
    runtime.workspace_path = "/workspace/agent"
    session.add(runtime)
    first_user = await UserRepository().create(
        session,
        UserCreate(email="historical-settings-1@example.test"),
    )
    second_user = await UserRepository().create(
        session,
        UserCreate(email="historical-settings-2@example.test"),
    )
    for user, name in ((first_user, "First"), (second_user, "Second")):
        session.add(
            RDBWorkspaceUser(
                workspace_id=workspace.id,
                user_id=user.id,
                name=name,
                role=WorkspaceUserRole.MEMBER,
            )
        )
    await session.flush()
    return _SettingsFixture(
        workspace_id=workspace.id,
        agent_id=agent.id,
        user_id=first_user.id,
        other_user_id=second_user.id,
    )


async def test_settings_list_is_scope_search_cursor_and_enablement_independent(
    rdb_session_manager: SessionManager[AsyncSession],
) -> None:
    """Settings remain visible while disabled and paginate by the stable key."""
    async with rdb_session_manager() as session:
        workspace_id, agent_id, user_id, other_user_id = await _fixture(session)
        newest = await _create_source(
            session,
            workspace_id=workspace_id,
            agent_id=agent_id,
            slug="newest",
            product_mode=AgentSessionProductMode.TEAM,
            associated_user_id=None,
            activity_at=_NOW - datetime.timedelta(hours=1),
            prepared_at=_NOW - datetime.timedelta(minutes=20),
            summary="Alpha current decision",
        )
        middle = await _create_source(
            session,
            workspace_id=workspace_id,
            agent_id=agent_id,
            slug="middle",
            product_mode=AgentSessionProductMode.TEAM,
            associated_user_id=None,
            activity_at=_NOW - datetime.timedelta(hours=2),
            prepared_at=_NOW - datetime.timedelta(minutes=30),
            summary="Beta delivery result",
        )
        oldest = await _create_source(
            session,
            workspace_id=workspace_id,
            agent_id=agent_id,
            slug="oldest",
            product_mode=AgentSessionProductMode.TEAM,
            associated_user_id=None,
            activity_at=_NOW - datetime.timedelta(hours=3),
            prepared_at=_NOW - datetime.timedelta(minutes=40),
            summary="Gamma follow-up",
        )
        own = await _create_source(
            session,
            workspace_id=workspace_id,
            agent_id=agent_id,
            slug="personal-own",
            product_mode=AgentSessionProductMode.USER,
            associated_user_id=user_id,
            activity_at=_NOW - datetime.timedelta(hours=4),
            prepared_at=_NOW - datetime.timedelta(minutes=50),
            summary="Private owner note",
        )
        await _create_source(
            session,
            workspace_id=workspace_id,
            agent_id=agent_id,
            slug="personal-other",
            product_mode=AgentSessionProductMode.USER,
            associated_user_id=other_user_id,
            activity_at=_NOW - datetime.timedelta(hours=5),
            prepared_at=_NOW - datetime.timedelta(hours=1),
            summary="Other user secret",
        )
        await session.commit()

    repository = HistoricalMemorySettingsRepository(session_manager=rdb_session_manager)
    first = await repository.list(
        workspace_id=workspace_id,
        agent_id=agent_id,
        user_id=user_id,
        scope=HistoricalMemorySettingsScope.TEAM,
        query=None,
        cursor=None,
        limit=2,
    )
    second = await repository.list(
        workspace_id=workspace_id,
        agent_id=agent_id,
        user_id=user_id,
        scope=HistoricalMemorySettingsScope.TEAM,
        query=None,
        cursor=first.next_cursor,
        limit=2,
    )
    personal = await repository.list(
        workspace_id=workspace_id,
        agent_id=agent_id,
        user_id=user_id,
        scope=HistoricalMemorySettingsScope.USER,
        query=None,
        cursor=None,
        limit=20,
    )
    searched = await repository.list(
        workspace_id=workspace_id,
        agent_id=agent_id,
        user_id=user_id,
        scope=HistoricalMemorySettingsScope.TEAM,
        query="DELIVERY",
        cursor=None,
        limit=20,
    )

    assert [item.source_session_id for item in first.items] == [newest, middle]
    assert first.next_cursor is not None
    assert [item.source_session_id for item in second.items] == [oldest]
    assert second.next_cursor is None
    assert [item.source_session_id for item in personal.items] == [own]
    assert [item.source_session_id for item in searched.items] == [middle]


async def test_settings_filters_lifecycle_membership_and_exact_detail(
    rdb_session_manager: SessionManager[AsyncSession],
) -> None:
    """Archived and membership-denied sources are non-enumerating."""
    async with rdb_session_manager() as session:
        workspace_id, agent_id, user_id, _ = await _fixture(session)
        visible = await _create_source(
            session,
            workspace_id=workspace_id,
            agent_id=agent_id,
            slug="visible",
            product_mode=AgentSessionProductMode.USER,
            associated_user_id=user_id,
            activity_at=_NOW - datetime.timedelta(hours=2),
            prepared_at=_NOW - datetime.timedelta(hours=1),
            summary="Visible personal history",
        )
        archived = await _create_source(
            session,
            workspace_id=workspace_id,
            agent_id=agent_id,
            slug="archived",
            product_mode=AgentSessionProductMode.TEAM,
            associated_user_id=None,
            activity_at=_NOW - datetime.timedelta(hours=3),
            prepared_at=_NOW - datetime.timedelta(hours=2),
            summary="Archived history",
        )
        archived_row = await session.get(RDBAgentSession, archived)
        assert archived_row is not None
        archived_row.status = AgentSessionStatus.ARCHIVED
        await session.commit()

    repository = HistoricalMemorySettingsRepository(session_manager=rdb_session_manager)
    record = await repository.get(
        workspace_id=workspace_id,
        agent_id=agent_id,
        user_id=user_id,
        source_session_id=visible,
    )
    hidden = await repository.get(
        workspace_id=workspace_id,
        agent_id=agent_id,
        user_id=user_id,
        source_session_id=archived,
    )
    assert record is not None
    assert record.summary == "Visible personal history"
    assert hidden is None

    async with rdb_session_manager() as session:
        await session.execute(
            sa.delete(RDBWorkspaceUser).where(
                RDBWorkspaceUser.workspace_id == workspace_id,
                RDBWorkspaceUser.user_id == user_id,
            )
        )
        await session.commit()
    assert (
        await repository.get(
            workspace_id=workspace_id,
            agent_id=agent_id,
            user_id=user_id,
            source_session_id=visible,
        )
        is None
    )


@pytest.mark.parametrize("cursor", ["not-a-cursor", "\ud55c\uae00", "\U0001f680"])
async def test_settings_rejects_malformed_cursor(
    rdb_session_manager: SessionManager[AsyncSession],
    cursor: str,
) -> None:
    """Opaque cursor validation fails before executing a settings query."""
    repository = HistoricalMemorySettingsRepository(session_manager=rdb_session_manager)
    with pytest.raises(HistoricalMemorySettingsCursorError):
        await repository.list(
            workspace_id="w" * 32,
            agent_id="a" * 32,
            user_id="u" * 32,
            scope=HistoricalMemorySettingsScope.TEAM,
            query=None,
            cursor=cursor,
            limit=20,
        )
