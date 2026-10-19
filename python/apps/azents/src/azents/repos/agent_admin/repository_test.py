"""Persisted Agent administrator uniqueness at the owning repository boundary."""

from azcommon.result import Failure, Success

from azents.core.enums import WorkspaceUserRole
from azents.core.workspace import WorkspaceCreate
from azents.rdb.models.agent import RDBAgent
from azents.rdb.session import SessionManager
from azents.rdb.session_capabilities import WriteSession
from azents.repos.user import UserRepository
from azents.repos.user.data import UserCreate
from azents.repos.workspace import WorkspaceRepository
from azents.repos.workspace_user import WorkspaceUserRepository
from azents.repos.workspace_user.data import WorkspaceUserCreate
from azents.testing.model_selection import (
    make_test_model_selection_dict,
    make_test_selectable_model_option_dicts,
)

from . import AgentAdminRepository
from .data import AgentAdminCreate, DuplicateAdmin


async def test_duplicate_admin_preserves_the_initial_persisted_admin(
    rdb_session_manager: SessionManager[WriteSession],
) -> None:
    """Actual PostgreSQL uniqueness maps to DuplicateAdmin without losing the row."""
    repository = AgentAdminRepository()
    async with rdb_session_manager() as session:
        workspace_result = await WorkspaceRepository().create(
            session, WorkspaceCreate(name="Admin uniqueness", handle="admin-unique")
        )
        assert isinstance(workspace_result, Success)
        workspace_id = await WorkspaceRepository().resolve_id(session, "admin-unique")
        assert workspace_id is not None
        user = await UserRepository().create(
            session, UserCreate(email="admin-unique@example.com")
        )
        member = await WorkspaceUserRepository().create(
            session,
            WorkspaceUserCreate(
                workspace_id=workspace_id,
                user_id=user.id,
                name="Administrator",
                role=WorkspaceUserRole.MEMBER,
            ),
        )
        assert isinstance(member, Success)
        selection = make_test_model_selection_dict()
        agent = RDBAgent(
            workspace_id=workspace_id,
            name="Unique admin agent",
            model_selection=selection,
            lightweight_model_selection=selection,
            selectable_model_options=make_test_selectable_model_option_dicts(
                model_selection=selection, lightweight_model_selection=selection
            ),
            main_model_label="default",
            lightweight_model_label="lightweight",
        )
        session.write_session.add(agent)
        await session.write_session.flush()
        create = AgentAdminCreate(agent_id=agent.id, workspace_user_id=member.value.id)
        first = await repository.create(session, create)
        assert isinstance(first, Success)
        original = first.value

    async with rdb_session_manager() as session:
        duplicate = await repository.create(session, create)
        assert duplicate == Failure(
            DuplicateAdmin(
                agent_id=create.agent_id, workspace_user_id=create.workspace_user_id
            )
        )

    async with rdb_session_manager() as session:
        retained = await repository.list_by_agent(session, create.agent_id)
        assert retained.items == [original]
        assert await repository.count_by_agent(session, create.agent_id) == 1
        assert await repository.is_admin(
            session, create.agent_id, create.workspace_user_id
        )
