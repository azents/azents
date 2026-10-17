"""Same-owner Workspace boundaries and independent per-Toolkit policies."""

import pytest
import sqlalchemy as sa
from sqlalchemy.exc import IntegrityError

from azents.core.toolkit_ownership import PersonalToolkitAccessMode as Mode
from azents.rdb.models.agent import RDBAgent
from azents.rdb.models.toolkit import RDBPersonalToolkitAgent, RDBToolkitConfig
from azents.rdb.models.workspace import RDBWorkspace
from azents.rdb.models.workspace_user import RDBWorkspaceUser
from azents.repos.toolkit.personal import (
    PersonalToolkitAccessMutation as Mutation,
)
from azents.repos.toolkit.personal import (
    PersonalToolkitAgentIneligible,
    PersonalToolkitNotFound,
)
from azents.repos.toolkit.personal_test import Fixture, creation, fixture

__all__ = ["fixture"]


async def test_same_user_workspace_boundary_and_independent_toolkit_policy(
    fixture: Fixture,
) -> None:
    """Same owner cannot use A's parent through B; each policy is independent."""
    f = fixture
    a, b = f.workspace_ids
    first = await f.operations.create(
        user_id=f.user_id, workspace_id=a, create=creation()
    )
    second = await f.operations.create(
        user_id=f.user_id, workspace_id=a, create=creation()
    )
    third = await f.operations.create(
        user_id=f.user_id, workspace_id=b, create=creation()
    )
    assert first.owner.workspace_id == a and third.owner.workspace_id == b
    assert {
        t.id
        for t in await f.operations.list_personal(user_id=f.user_id, workspace_id=a)
    } == {first.id, second.id}
    assert [
        t.id
        for t in await f.operations.list_personal(user_id=f.user_id, workspace_id=b)
    ] == [third.id]
    assert (
        await f.operations.get(user_id=f.user_id, workspace_id=b, toolkit_id=first.id)
        is None
    )
    assert (
        await f.operations.read_access(
            user_id=f.user_id, workspace_id=b, toolkit_id=first.id
        )
        is None
    )
    with pytest.raises(PersonalToolkitNotFound):
        await f.operations.update(
            user_id=f.user_id,
            workspace_id=b,
            toolkit_id=first.id,
            update={"name": "Wrong Workspace"},
        )
    with pytest.raises(PersonalToolkitNotFound):
        await f.operations.delete(
            user_id=f.user_id, workspace_id=b, toolkit_id=first.id
        )
    with pytest.raises(PersonalToolkitNotFound):
        await f.operations.mutate_access(
            user_id=f.user_id,
            workspace_id=b,
            mutations=[
                Mutation(first.id, Mode.SELECTED, frozenset(), frozenset(), Mode.ALL)
            ],
        )
    [restricted] = await f.operations.mutate_access(
        user_id=f.user_id,
        workspace_id=a,
        mutations=[
            Mutation(first.id, None, frozenset(), frozenset([f.agent_ids[0]]), Mode.ALL)
        ],
    )
    assert restricted.workspace_id == a
    assert restricted.selected_agent_ids == (f.agent_ids[1],)
    for untouched, scope in [(second, a), (third, b)]:
        saved = await f.operations.read_access(
            user_id=f.user_id, workspace_id=scope, toolkit_id=untouched.id
        )
        assert (
            saved is not None
            and saved.mode is Mode.ALL
            and saved.selected_agent_ids == ()
        )
    saved_first = await f.operations.get(
        user_id=f.user_id, workspace_id=a, toolkit_id=first.id
    )
    assert saved_first is not None and saved_first.name == first.name


async def test_cross_workspace_agent_intent_rejects_without_policy_transition(
    fixture: Fixture,
) -> None:
    """An accessible Agent in B is not eligible for a Toolkit in A."""
    f = fixture
    a = f.workspace_ids[0]
    toolkit = await f.operations.create(
        user_id=f.user_id, workspace_id=a, create=creation()
    )
    for allow, restrict in [
        (frozenset([f.agent_ids[2]]), frozenset()),
        (frozenset(), frozenset([f.agent_ids[2]])),
    ]:
        with pytest.raises(PersonalToolkitAgentIneligible):
            await f.operations.mutate_access(
                user_id=f.user_id,
                workspace_id=a,
                mutations=[Mutation(toolkit.id, None, allow, restrict, Mode.ALL)],
            )
    snapshot = await f.operations.read_access(
        user_id=f.user_id, workspace_id=a, toolkit_id=toolkit.id
    )
    assert snapshot is not None and snapshot.mode is Mode.ALL


@pytest.mark.parametrize("claimed_scope", [0, 1])
async def test_database_enforces_membership_workspace_on_both_sides(
    fixture: Fixture, claimed_scope: int
) -> None:
    """Neither the parent's scope nor the foreign Agent scope bypasses both FKs."""
    f = fixture
    toolkit = await f.operations.create(
        user_id=f.user_id, workspace_id=f.workspace_ids[0], create=creation()
    )
    constraint = (
        "fk_personal_toolkit_agents_agent_workspace"
        if claimed_scope == 0
        else "fk_personal_toolkit_agents_owner"
    )
    with pytest.raises(IntegrityError, match=constraint):
        async with f.writes() as session:
            session.write_session.add(
                RDBPersonalToolkitAgent(
                    toolkit_id=toolkit.id,
                    owner_user_id=f.user_id,
                    workspace_id=f.workspace_ids[claimed_scope],
                    agent_id=f.agent_ids[2],
                )
            )
            await session.write_session.flush()


async def test_ordinary_workspace_membership_is_required(fixture: Fixture) -> None:
    """Shared-manager authority is unnecessary; ordinary membership is required."""
    f = fixture
    b = f.workspace_ids[1]
    with pytest.raises(PersonalToolkitNotFound):
        await f.operations.create(
            user_id=f.other_user_id, workspace_id=b, create=creation()
        )
    own = await f.operations.create(
        user_id=f.user_id, workspace_id=b, create=creation()
    )
    async with f.writes() as session:
        await session.write_session.execute(
            sa.delete(RDBWorkspaceUser).where(RDBWorkspaceUser.id == f.member_id)
        )
    assert await f.operations.list_personal(user_id=f.user_id, workspace_id=b) == []
    assert (
        await f.operations.get(user_id=f.user_id, workspace_id=b, toolkit_id=own.id)
        is None
    )


async def test_workspace_delete_removes_only_its_personal_connections(
    fixture: Fixture,
) -> None:
    """Real Workspace lifetime owns scoped parents, not another Workspace's."""
    f = fixture
    a, b = f.workspace_ids
    first = await f.operations.create(
        user_id=f.user_id, workspace_id=a, create=creation()
    )
    second = await f.operations.create(
        user_id=f.user_id, workspace_id=b, create=creation()
    )
    async with f.writes() as session:
        await session.write_session.execute(
            sa.delete(RDBAgent).where(RDBAgent.workspace_id == b)
        )
        await session.write_session.execute(
            sa.delete(RDBWorkspace).where(RDBWorkspace.id == b)
        )
        assert await session.read_session.get(RDBToolkitConfig, second.id) is None
    assert (
        await f.operations.get(user_id=f.user_id, workspace_id=a, toolkit_id=first.id)
        is not None
    )


async def test_batch_with_other_workspace_parent_is_atomic(fixture: Fixture) -> None:
    """A later B target rolls back any earlier policy edit in A."""
    f = fixture
    a, b = f.workspace_ids
    first = await f.operations.create(
        user_id=f.user_id, workspace_id=a, create=creation()
    )
    foreign = await f.operations.create(
        user_id=f.user_id, workspace_id=b, create=creation()
    )
    assert first.id < foreign.id
    with pytest.raises(PersonalToolkitNotFound):
        await f.operations.mutate_access(
            user_id=f.user_id,
            workspace_id=a,
            mutations=[
                Mutation(
                    first.id, None, frozenset(), frozenset([f.agent_ids[0]]), Mode.ALL
                ),
                Mutation(foreign.id, Mode.SELECTED, frozenset(), frozenset(), Mode.ALL),
            ],
        )
    saved = await f.operations.read_access(
        user_id=f.user_id, workspace_id=a, toolkit_id=first.id
    )
    assert (
        saved is not None and saved.mode is Mode.ALL and saved.selected_agent_ids == ()
    )
