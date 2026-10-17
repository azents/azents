"""Real PostgreSQL ownership and personal permission boundary tests."""

import asyncio
import dataclasses
from collections.abc import AsyncIterator
from uuid import uuid4

import pytest
import sqlalchemy as sa
from azcommon.result import Success
from cryptography.fernet import Fernet
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncEngine

from azents.core.crypto import CredentialCipher
from azents.core.enums import AgentType, WorkspaceUserRole
from azents.core.personal_toolkit import (
    PersonalToolkitAccessConflict,
    PersonalToolkitAgentIneligible,
    PersonalToolkitNotFound,
)
from azents.core.personal_toolkit import (
    PersonalToolkitAccessMutation as Mutation,
)
from azents.core.toolkit_ownership import PersonalToolkitAccessMode as Mode
from azents.core.toolkit_ownership import ToolkitOwnerKind as Owner
from azents.rdb.models.agent import RDBAgent
from azents.rdb.models.agent_admin import RDBAgentAdmin
from azents.rdb.models.toolkit import (
    RDBAgentToolkit,
    RDBPersonalToolkitAgent,
    RDBToolkitConfig,
)
from azents.rdb.models.user import RDBUser
from azents.rdb.models.workspace import RDBWorkspace
from azents.rdb.models.workspace_user import RDBWorkspaceUser
from azents.rdb.session import SessionManager
from azents.rdb.session_capabilities import (
    WriteSession,
    create_read_write_session_manager,
)
from azents.repos.toolkit import (
    AgentToolkitRepository,
    ToolkitRepository,
    effective_agent_toolkit_relation,
)
from azents.repos.toolkit.data import AgentToolkitCreate, ToolkitCreate, ToolkitCreation
from azents.repos.toolkit.personal import (
    PersonalToolkitOperations,
    PersonalToolkitRepository,
    eligible_personal_agent_ids,
)
from azents.repos.user import UserRepository
from azents.repos.user.data import UserCreate
from azents.testing.model_selection import (
    make_test_model_selection,
    make_test_selectable_model_option_dicts,
)


def creation() -> ToolkitCreation:
    """Use ordinary configurable fields, including fake encrypted credentials."""
    return ToolkitCreation(
        toolkit_type="mcp",
        slug="personal",
        name="Personal",
        config={"transport": "http"},
        credentials='{"token":"fixture-only"}',
        always_expose_tools=True,
    )


def agent(workspace_id: str, *, private: bool = False) -> RDBAgent:
    """Build a canonical Agent without external dependencies."""
    selection = make_test_model_selection().model_dump(mode="json")
    return RDBAgent(
        workspace_id=workspace_id,
        name="Same name",
        model_selection=selection,
        lightweight_model_selection=selection,
        selectable_model_options=make_test_selectable_model_option_dicts(
            model_selection=selection,
            lightweight_model_selection=selection,
        ),
        main_model_label="default",
        lightweight_model_label="default",
        type=AgentType.PRIVATE if private else AgentType.PUBLIC,
    )


@dataclasses.dataclass(frozen=True)
class Fixture:
    writes: SessionManager[WriteSession]
    repository: PersonalToolkitRepository
    operations: PersonalToolkitOperations
    user_id: str
    other_user_id: str
    workspace_ids: tuple[str, str]
    agent_ids: tuple[str, ...]
    member_id: str


@pytest.fixture
async def fixture(
    rdb_engine: AsyncEngine, latest_db_schema: None
) -> AsyncIterator[Fixture]:
    """Own isolated committed rows for real transaction interleavings."""
    del latest_db_schema
    writes = create_read_write_session_manager(rdb_engine)
    repository = PersonalToolkitRepository(
        CredentialCipher(Fernet.generate_key().decode())
    )
    async with writes() as session:
        users = [
            await UserRepository().create(
                session, UserCreate(email=f"personal-{uuid4().hex}@example.test")
            )
            for _ in range(2)
        ]
        workspaces = [
            RDBWorkspace(name="Personal policy", handle=f"personal-{uuid4().hex}")
            for _ in range(2)
        ]
        session.write_session.add_all(workspaces)
        await session.write_session.flush()
        members = [
            RDBWorkspaceUser(
                workspace_id=w.id,
                user_id=users[0].id,
                name="Owner",
                role=WorkspaceUserRole.MEMBER,
            )
            for w in workspaces
        ]
        session.write_session.add_all(members)
        session.write_session.add(
            RDBWorkspaceUser(
                workspace_id=workspaces[0].id,
                user_id=users[1].id,
                name="Other member",
                role=WorkspaceUserRole.MEMBER,
            )
        )
        agents = [
            agent(workspaces[0].id),
            agent(workspaces[0].id),
            agent(workspaces[1].id),
            agent(workspaces[1].id, private=True),
        ]
        session.write_session.add_all(agents)
        await session.write_session.flush()
        data = Fixture(
            writes,
            repository,
            PersonalToolkitOperations(writes, repository),
            users[0].id,
            users[1].id,
            (workspaces[0].id, workspaces[1].id),
            tuple(a.id for a in agents),
            members[1].id,
        )
    try:
        yield data
    finally:
        async with writes() as session:
            await session.write_session.execute(
                sa.delete(RDBAgent).where(RDBAgent.workspace_id.in_(data.workspace_ids))
            )
            await session.write_session.execute(
                sa.delete(RDBWorkspace).where(RDBWorkspace.id.in_(data.workspace_ids))
            )
            await session.write_session.execute(
                sa.delete(RDBUser).where(
                    RDBUser.id.in_([data.user_id, data.other_user_id])
                )
            )


async def test_default_all_and_first_restriction_within_workspace(
    fixture: Fixture,
) -> None:
    """First restriction snapshots eligible Agents only inside the Toolkit Workspace."""
    f = fixture
    toolkit = await f.operations.create(
        user_id=f.user_id, workspace_id=f.workspace_ids[0], create=creation()
    )
    assert toolkit.owner.user_id == f.user_id
    assert toolkit.access_mode is Mode.ALL
    async with f.writes() as session:
        later_all = agent(f.workspace_ids[0])
        session.write_session.add(later_all)
        await session.write_session.flush()
    before = await f.operations.read_access(
        user_id=f.user_id, workspace_id=f.workspace_ids[0], toolkit_id=toolkit.id
    )
    assert before is not None and before.allows_agent(later_all.id)
    [selected] = await f.operations.mutate_access(
        user_id=f.user_id,
        workspace_id=f.workspace_ids[0],
        mutations=[
            Mutation(
                toolkit.id,
                None,
                frozenset(),
                frozenset([f.agent_ids[0]]),
                expected_mode=Mode.ALL,
            )
        ],
    )
    assert selected.mode is Mode.SELECTED
    assert set(selected.selected_agent_ids) == {
        f.agent_ids[1],
        later_all.id,
    }
    async with f.writes() as session:
        later_selected = agent(f.workspace_ids[0])
        session.write_session.add(later_selected)
        await session.write_session.flush()
    after = await f.operations.read_access(
        user_id=f.user_id, workspace_id=f.workspace_ids[0], toolkit_id=toolkit.id
    )
    assert after is not None and not after.allows_agent(later_selected.id)
    [edited] = await f.operations.mutate_access(
        user_id=f.user_id,
        workspace_id=f.workspace_ids[0],
        mutations=[
            Mutation(
                toolkit.id,
                None,
                frozenset([f.agent_ids[0]]),
                frozenset([f.agent_ids[1]]),
                expected_mode=Mode.SELECTED,
            )
        ],
    )
    assert set(edited.selected_agent_ids) == {
        f.agent_ids[0],
        later_all.id,
    }
    [all_again] = await f.operations.mutate_access(
        user_id=f.user_id,
        workspace_id=f.workspace_ids[0],
        mutations=[
            Mutation(
                toolkit.id,
                Mode.ALL,
                frozenset(),
                frozenset(),
                expected_mode=Mode.SELECTED,
            )
        ],
    )
    assert all_again.mode is Mode.ALL and all_again.selected_agent_ids == ()
    assert all_again.allows_agent(later_selected.id)


async def test_ordinary_private_agent_access_is_not_provider_readiness(
    fixture: Fixture,
) -> None:
    """Selected private membership persists but cannot bypass ordinary access loss."""
    f = fixture
    workspace_id = f.workspace_ids[1]
    toolkit = await f.operations.create(
        user_id=f.user_id, workspace_id=workspace_id, create=creation()
    )
    await f.operations.update(
        user_id=f.user_id,
        workspace_id=workspace_id,
        toolkit_id=toolkit.id,
        update={"enabled": False},
    )
    async with f.writes() as session:
        session.write_session.add(
            RDBAgentAdmin(agent_id=f.agent_ids[3], workspace_user_id=f.member_id)
        )
    [snapshot] = await f.operations.mutate_access(
        user_id=f.user_id,
        workspace_id=workspace_id,
        mutations=[
            Mutation(
                toolkit.id,
                None,
                frozenset(),
                frozenset([f.agent_ids[2]]),
                expected_mode=Mode.ALL,
            )
        ],
    )
    assert set(snapshot.selected_agent_ids) == {f.agent_ids[3]}
    async with f.writes() as session:
        await session.write_session.execute(
            sa.delete(RDBAgentAdmin).where(RDBAgentAdmin.agent_id == f.agent_ids[3])
        )
        eligible = set(
            await session.read_session.scalars(
                eligible_personal_agent_ids(f.user_id, workspace_id)
            )
        )
    assert f.agent_ids[3] not in eligible
    retained = await f.operations.read_access(
        user_id=f.user_id, workspace_id=workspace_id, toolkit_id=toolkit.id
    )
    assert retained is not None and f.agent_ids[3] in retained.selected_agent_ids
    with pytest.raises(PersonalToolkitAgentIneligible):
        await f.operations.mutate_access(
            user_id=f.user_id,
            workspace_id=workspace_id,
            mutations=[
                Mutation(
                    toolkit.id,
                    None,
                    frozenset([f.agent_ids[3]]),
                    frozenset(),
                    expected_mode=Mode.SELECTED,
                )
            ],
        )
    async with f.writes() as session:
        await session.write_session.execute(
            sa.delete(RDBWorkspaceUser).where(RDBWorkspaceUser.id == f.member_id)
        )
    assert (
        await f.operations.get(
            user_id=f.user_id, workspace_id=workspace_id, toolkit_id=toolkit.id
        )
        is None
    )
    with pytest.raises(PersonalToolkitNotFound):
        await f.operations.update(
            user_id=f.user_id,
            workspace_id=workspace_id,
            toolkit_id=toolkit.id,
            update={"enabled": True},
        )


async def test_owner_scoped_crud_shared_projection_and_cascades(
    fixture: Fixture,
) -> None:
    """Personal IDs cannot leak through shared readers, writes or attachments."""
    f = fixture
    toolkit = await f.operations.create(
        user_id=f.user_id, workspace_id=f.workspace_ids[0], create=creation()
    )
    assert toolkit.credentials == creation().credentials
    assert (
        await f.operations.list_personal(
            user_id=f.other_user_id, workspace_id=f.workspace_ids[0]
        )
        == []
    )
    assert (
        await f.operations.get(
            user_id=f.other_user_id,
            workspace_id=f.workspace_ids[0],
            toolkit_id=toolkit.id,
        )
        is None
    )
    with pytest.raises(PersonalToolkitNotFound):
        await f.operations.update(
            user_id=f.other_user_id,
            workspace_id=f.workspace_ids[0],
            toolkit_id=toolkit.id,
            update={"name": "Foreign"},
        )
    with pytest.raises(PersonalToolkitNotFound):
        await f.operations.delete(
            user_id=f.other_user_id,
            workspace_id=f.workspace_ids[0],
            toolkit_id=toolkit.id,
        )
    shared_repo = ToolkitRepository(f.repository.cipher)
    attachments = AgentToolkitRepository()
    async with f.writes() as session:
        shared = await shared_repo.create(
            session,
            ToolkitCreate(
                workspace_id=f.workspace_ids[0],
                owner_agent_id=None,
                **creation().model_dump(),
            ),
        )
        owned = await shared_repo.create(
            session,
            ToolkitCreate(
                workspace_id=f.workspace_ids[0],
                owner_agent_id=f.agent_ids[0],
                **creation().model_dump(),
            ),
        )
        attachment = await attachments.create(
            session,
            AgentToolkitCreate(
                agent_id=f.agent_ids[0], toolkit_id=shared.id, toolkit_type="mcp"
            ),
        )
        assert isinstance(attachment, Success)
        assert await shared_repo.get_by_id(session, toolkit.id) is None
        assert await shared_repo.get_shared_by_id(session, toolkit.id) is None
        assert (
            await shared_repo.claim_shared_namespace_mutation(session, toolkit.id)
            is None
        )
        assert [
            t.id
            for t in await shared_repo.list_by_workspace(session, f.workspace_ids[0])
        ] == [shared.id]
        assert [
            t.id
            for t in await shared_repo.list_by_owner_agent(
                session, f.agent_ids[0], workspace_id=f.workspace_ids[0]
            )
        ] == [owned.id]
        assert [
            t.id
            for t in await shared_repo.list_available_for_workspace_user(
                session, f.workspace_ids[0], f.user_id
            )
        ] == [shared.id]
        await shared_repo.update_by_id(session, toolkit.id, {"name": "Wrong"})
        await shared_repo.delete_by_id(session, toolkit.id)
        assert (
            await f.repository.get_personal(
                session,
                user_id=f.user_id,
                workspace_id=f.workspace_ids[0],
                toolkit_id=toolkit.id,
            )
            is not None
        )
        with pytest.raises(ValueError, match="shared Toolkit"):
            await attachments.create(
                session,
                AgentToolkitCreate(
                    agent_id=f.agent_ids[0], toolkit_id=toolkit.id, toolkit_type="mcp"
                ),
            )
        # Even malformed historical attachments are excluded from shared projections.
        malformed = RDBAgentToolkit(
            agent_id=f.agent_ids[0], toolkit_id=toolkit.id, toolkit_type="mcp"
        )
        session.write_session.add(malformed)
        await session.write_session.flush()
        assert await attachments.get_by_id(session, malformed.id) is None
        assert len(await attachments.list_by_agent(session, f.agent_ids[0])) == 1
        relation = effective_agent_toolkit_relation(enabled_only=True)
        effective = set(
            await session.read_session.scalars(sa.select(relation.c.toolkit_id))
        )
        assert {shared.id, owned.id} <= effective and toolkit.id not in effective
        assert (
            await f.repository.get_personal(
                session,
                user_id=f.user_id,
                workspace_id=f.workspace_ids[0],
                toolkit_id=shared.id,
            )
            is None
        )
    await f.operations.mutate_access(
        user_id=f.user_id,
        workspace_id=f.workspace_ids[0],
        mutations=[
            Mutation(
                toolkit.id,
                None,
                frozenset(),
                frozenset([f.agent_ids[0]]),
                expected_mode=Mode.ALL,
            )
        ],
    )
    updated = await f.operations.update(
        user_id=f.user_id,
        workspace_id=f.workspace_ids[0],
        toolkit_id=toolkit.id,
        update={"name": "Updated", "credentials": None},
    )
    assert (
        updated.id == toolkit.id
        and updated.name == "Updated"
        and updated.credentials is None
    )
    assert updated.access_mode is Mode.SELECTED
    async with f.writes() as session:
        await session.write_session.execute(
            sa.delete(RDBAgent).where(RDBAgent.workspace_id == f.workspace_ids[1])
        )
        await session.write_session.execute(
            sa.delete(RDBWorkspace).where(RDBWorkspace.id == f.workspace_ids[1])
        )
    snapshot = await f.operations.read_access(
        user_id=f.user_id, workspace_id=f.workspace_ids[0], toolkit_id=toolkit.id
    )
    assert snapshot is not None and set(snapshot.selected_agent_ids) == {f.agent_ids[1]}
    await f.operations.delete(
        user_id=f.user_id, workspace_id=f.workspace_ids[0], toolkit_id=toolkit.id
    )
    async with f.writes() as session:
        assert not list(
            await session.read_session.scalars(
                sa.select(RDBPersonalToolkitAgent.agent_id).where(
                    RDBPersonalToolkitAgent.toolkit_id == toolkit.id
                )
            )
        )


async def test_multi_connection_mutation_rolls_back_on_later_failure(
    fixture: Fixture,
) -> None:
    """No earlier connection is committed when a later target is foreign."""
    f = fixture
    first = await f.operations.create(
        user_id=f.user_id, workspace_id=f.workspace_ids[0], create=creation()
    )
    foreign = await f.operations.create(
        user_id=f.other_user_id, workspace_id=f.workspace_ids[0], create=creation()
    )
    assert first.id < foreign.id
    with pytest.raises(PersonalToolkitNotFound):
        await f.operations.mutate_access(
            user_id=f.user_id,
            workspace_id=f.workspace_ids[0],
            mutations=[
                Mutation(
                    first.id,
                    None,
                    frozenset(),
                    frozenset([f.agent_ids[0]]),
                    expected_mode=Mode.ALL,
                ),
                Mutation(
                    foreign.id,
                    Mode.SELECTED,
                    frozenset(),
                    frozenset(),
                    expected_mode=Mode.ALL,
                ),
            ],
        )
    snapshot = await f.operations.read_access(
        user_id=f.user_id, workspace_id=f.workspace_ids[0], toolkit_id=first.id
    )
    assert (
        snapshot is not None
        and snapshot.mode is Mode.ALL
        and not snapshot.selected_agent_ids
    )


async def test_concurrent_restrictions_serialize_on_parent(fixture: Fixture) -> None:
    """A contender waits for the parent then changes committed Selected state."""
    f = fixture
    toolkit = await f.operations.create(
        user_id=f.user_id, workspace_id=f.workspace_ids[0], create=creation()
    )
    await f.operations.mutate_access(
        user_id=f.user_id,
        workspace_id=f.workspace_ids[0],
        mutations=[
            Mutation(
                toolkit.id,
                Mode.SELECTED,
                frozenset(),
                frozenset(),
                expected_mode=Mode.ALL,
            )
        ],
    )
    second_pid: asyncio.Future[int] = asyncio.get_running_loop().create_future()

    async def second() -> None:
        async with f.writes() as session:
            pid = await session.read_session.scalar(sa.text("SELECT pg_backend_pid()"))
            second_pid.set_result(pid)
            await f.repository.mutate_access(
                session,
                user_id=f.user_id,
                workspace_id=f.workspace_ids[0],
                mutation=Mutation(
                    toolkit.id,
                    None,
                    frozenset(),
                    frozenset([f.agent_ids[1]]),
                    expected_mode=Mode.SELECTED,
                ),
            )

    task: asyncio.Task[None] | None = None
    try:
        async with f.writes() as session:
            await f.repository.mutate_access(
                session,
                user_id=f.user_id,
                workspace_id=f.workspace_ids[0],
                mutation=Mutation(
                    toolkit.id,
                    None,
                    frozenset(),
                    frozenset([f.agent_ids[0]]),
                    expected_mode=Mode.SELECTED,
                ),
            )
            task = asyncio.create_task(second())
            async with asyncio.timeout(10):
                pid = await second_pid
                while not await session.read_session.scalar(
                    sa.text("SELECT pg_backend_pid() = ANY(pg_blocking_pids(:pid))"),
                    {"pid": pid},
                ):
                    pass  # Each query awaits PostgreSQL; the lock state is the barrier.
        await task
    finally:
        if task is not None and not task.done():
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
    snapshot = await f.operations.read_access(
        user_id=f.user_id, workspace_id=f.workspace_ids[0], toolkit_id=toolkit.id
    )
    assert snapshot is not None and snapshot.mode is Mode.SELECTED
    assert set(snapshot.selected_agent_ids) == set()


async def test_stale_selected_editor_cannot_restrict_new_all_policy(
    fixture: Fixture,
) -> None:
    """Expected mode is checked under the lock before changing future eligibility."""
    f = fixture
    toolkit = await f.operations.create(
        user_id=f.user_id, workspace_id=f.workspace_ids[0], create=creation()
    )
    await f.operations.mutate_access(
        user_id=f.user_id,
        workspace_id=f.workspace_ids[0],
        mutations=[
            Mutation(toolkit.id, Mode.SELECTED, frozenset(), frozenset(), Mode.ALL)
        ],
    )
    stale = Mutation(
        toolkit.id, None, frozenset(), frozenset([f.agent_ids[0]]), Mode.SELECTED
    )
    await f.operations.mutate_access(
        user_id=f.user_id,
        workspace_id=f.workspace_ids[0],
        mutations=[
            Mutation(toolkit.id, Mode.ALL, frozenset(), frozenset(), Mode.SELECTED)
        ],
    )
    before = await f.operations.get(
        user_id=f.user_id, workspace_id=f.workspace_ids[0], toolkit_id=toolkit.id
    )
    with pytest.raises(PersonalToolkitAccessConflict, match="reload"):
        await f.operations.mutate_access(
            user_id=f.user_id, workspace_id=f.workspace_ids[0], mutations=[stale]
        )
    after = await f.operations.get(
        user_id=f.user_id, workspace_id=f.workspace_ids[0], toolkit_id=toolkit.id
    )
    assert before is not None and after is not None
    assert after.revision == before.revision and after.access_mode is Mode.ALL
    snapshot = await f.operations.read_access(
        user_id=f.user_id, workspace_id=f.workspace_ids[0], toolkit_id=toolkit.id
    )
    assert snapshot is not None and snapshot.selected_agent_ids == ()


async def test_stale_mode_conflict_rolls_back_complete_batch(fixture: Fixture) -> None:
    """A stale All editor cannot commit earlier changes in a multi-target save."""
    f = fixture
    first = await f.operations.create(
        user_id=f.user_id, workspace_id=f.workspace_ids[0], create=creation()
    )
    second = await f.operations.create(
        user_id=f.user_id, workspace_id=f.workspace_ids[0], create=creation()
    )
    await f.operations.mutate_access(
        user_id=f.user_id,
        workspace_id=f.workspace_ids[0],
        mutations=[
            Mutation(second.id, Mode.SELECTED, frozenset(), frozenset(), Mode.ALL)
        ],
    )
    with pytest.raises(PersonalToolkitAccessConflict):
        await f.operations.mutate_access(
            user_id=f.user_id,
            workspace_id=f.workspace_ids[0],
            mutations=[
                Mutation(
                    first.id, None, frozenset(), frozenset([f.agent_ids[0]]), Mode.ALL
                ),
                Mutation(
                    second.id, None, frozenset(), frozenset([f.agent_ids[1]]), Mode.ALL
                ),
            ],
        )
    unchanged = await f.operations.read_access(
        user_id=f.user_id, workspace_id=f.workspace_ids[0], toolkit_id=first.id
    )
    assert unchanged is not None and unchanged.mode is Mode.ALL


@pytest.mark.parametrize("kind", [Owner.WORKSPACE, Owner.AGENT])
async def test_database_rejects_personal_keys_with_non_user_kind(
    fixture: Fixture,
    kind: Owner,
) -> None:
    """Persisted ownership discriminator and keys are one constrained authority."""
    f = fixture
    with pytest.raises(
        IntegrityError, match="ck_toolkit_configs_owner_shape|not-null constraint"
    ):
        async with f.writes() as session:
            session.write_session.add(
                RDBToolkitConfig(
                    owner_kind=kind,
                    workspace_id=f.workspace_ids[0],
                    owner_agent_id=None,
                    owner_user_id=f.user_id,
                    personal_access_mode=Mode.ALL,
                    toolkit_type="mcp",
                    slug="bad-kind",
                    name="Bad kind",
                    config={},
                )
            )
            await session.write_session.flush()


@pytest.mark.parametrize(
    "shape",
    [
        "missing_owner",
        "user_without_workspace",
        "agent_and_user",
        "shared_policy",
        "user_without_policy",
    ],
)
async def test_database_rejects_invalid_owner_shapes(
    fixture: Fixture, shape: str
) -> None:
    """The database rejects illegal combinations without repository validation."""
    f = fixture
    values = {
        "missing_owner": (None, None, None, None),
        "user_without_workspace": (None, None, f.user_id, Mode.ALL),
        "agent_and_user": (f.workspace_ids[0], f.agent_ids[0], f.user_id, Mode.ALL),
        "shared_policy": (f.workspace_ids[0], None, None, Mode.ALL),
        "user_without_policy": (f.workspace_ids[0], None, f.user_id, None),
    }
    workspace, owner_agent, owner_user, mode = values[shape]
    with pytest.raises(
        IntegrityError, match="ck_toolkit_configs_owner_shape|not-null constraint"
    ):
        async with f.writes() as session:
            await session.write_session.execute(
                sa.insert(RDBToolkitConfig).values(
                    id=uuid4().hex,
                    workspace_id=workspace,
                    owner_agent_id=owner_agent,
                    owner_user_id=owner_user,
                    owner_kind=Owner.USER
                    if owner_user is not None
                    else Owner.WORKSPACE,
                    personal_access_mode=mode,
                    toolkit_type="mcp",
                    slug="bad",
                    name="Bad",
                    config={},
                )
            )
            await session.write_session.flush()


async def test_membership_owner_fk_and_user_disable(fixture: Fixture) -> None:
    """Membership cannot target shared/foreign owners; disabled Users lose admission."""
    f = fixture
    toolkit = await f.operations.create(
        user_id=f.user_id, workspace_id=f.workspace_ids[0], create=creation()
    )
    with pytest.raises(IntegrityError, match="fk_personal_toolkit_agents_owner"):
        async with f.writes() as session:
            session.write_session.add(
                RDBPersonalToolkitAgent(
                    toolkit_id=toolkit.id,
                    owner_user_id=f.other_user_id,
                    workspace_id=f.workspace_ids[0],
                    agent_id=f.agent_ids[0],
                )
            )
            await session.write_session.flush()
    async with f.writes() as session:
        shared = await ToolkitRepository().create(
            session,
            ToolkitCreate(
                workspace_id=f.workspace_ids[0],
                owner_agent_id=None,
                toolkit_type="mcp",
                slug="shared",
                name="Shared",
                config={},
                always_expose_tools=False,
            ),
        )
    with pytest.raises(IntegrityError, match="fk_personal_toolkit_agents_owner"):
        async with f.writes() as session:
            session.write_session.add(
                RDBPersonalToolkitAgent(
                    toolkit_id=shared.id,
                    owner_user_id=f.user_id,
                    workspace_id=f.workspace_ids[0],
                    agent_id=f.agent_ids[0],
                )
            )
            await session.write_session.flush()
    async with f.writes() as session:
        await session.write_session.execute(
            sa.update(RDBUser)
            .where(RDBUser.id == f.user_id)
            .values(access_disabled_at=sa.func.now())
        )
    assert (
        await f.operations.list_personal(
            user_id=f.user_id, workspace_id=f.workspace_ids[0]
        )
        == []
    )
    assert (
        await f.operations.read_access(
            user_id=f.user_id, workspace_id=f.workspace_ids[0], toolkit_id=toolkit.id
        )
        is None
    )
    with pytest.raises(PersonalToolkitNotFound):
        await f.operations.mutate_access(
            user_id=f.user_id,
            workspace_id=f.workspace_ids[0],
            mutations=[
                Mutation(
                    toolkit.id,
                    Mode.ALL,
                    frozenset(),
                    frozenset(),
                    expected_mode=Mode.SELECTED,
                )
            ],
        )
    async with f.writes() as session:
        await session.write_session.execute(
            sa.delete(RDBUser).where(RDBUser.id == f.user_id)
        )
        assert await session.read_session.get(RDBToolkitConfig, toolkit.id) is None
