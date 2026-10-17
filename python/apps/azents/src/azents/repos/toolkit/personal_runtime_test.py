"""Real durable root lineage, current personal policy and lazy namespace admission."""

import dataclasses
from collections.abc import AsyncIterator
from typing import Literal
from unittest.mock import AsyncMock

import pytest
import sqlalchemy as sa

from azents.core.agent_session_data import AgentSessionCreate
from azents.core.enums import AgentSessionProductMode, WorkspaceUserRole
from azents.core.personal_toolkit import PersonalToolkitAccessMutation
from azents.core.personal_toolkit_runtime import PersonalToolkitExecutionDenied
from azents.core.session_resource_authority import SessionExecutionOwner
from azents.core.toolkit_ownership import PersonalToolkitAccessMode as Mode
from azents.rdb.models.agent import RDBAgent
from azents.rdb.models.agent_runtime import RDBAgentRuntime
from azents.rdb.models.agent_session import RDBAgentSession
from azents.rdb.models.user import RDBUser
from azents.rdb.models.workspace_user import RDBWorkspaceUser
from azents.repos.agent_session import AgentSessionRepository
from azents.repos.session_execution.repository_test import (
    _archive_with_scheduled_continuation,
)
from azents.repos.session_lifecycle_finalizer import SessionLifecycleFinalizerRepository
from azents.repos.toolkit.personal_runtime import (
    PersonalEffectiveToolkitConfig,
    PersonalToolkitRuntimeRepository,
)
from azents.repos.toolkit.personal_test import Fixture, creation
from azents.repos.toolkit.personal_test import (
    fixture as fixture,  # noqa: PLC0414 -- committed ownership fixture
)
from azents.repos.toolkit_namespace import ToolkitNamespaceRepository


@dataclasses.dataclass
class Root:
    owner: SessionExecutionOwner
    workspace_id: str
    agent_id: str
    node_id: str
    session_ids: list[str]


@dataclasses.dataclass
class Harness:
    foundation: Fixture
    repository: PersonalToolkitRuntimeRepository
    roots: list[Root]

    async def root(self, user_id: str | None, agent_index: int) -> Root:
        f = self.foundation
        async with f.writes() as session:
            agent_id = f.agent_ids[agent_index]
            agent = await session.read_session.get(RDBAgent, agent_id)
            assert agent is not None
            created = await AgentSessionRepository().create(
                session,
                AgentSessionCreate(
                    workspace_id=agent.workspace_id,
                    agent_id=agent_id,
                    title=None,
                    product_mode=AgentSessionProductMode.USER
                    if user_id is not None
                    else AgentSessionProductMode.TEAM,
                    associated_user_id=user_id,
                ),
            )
            await AgentSessionRepository().mark_running(session, created.id)
            row = await session.read_session.get(RDBAgentSession, created.id)
            node = await AgentSessionRepository().get_session_agent_by_session_id(
                session, created.id
            )
            assert row is not None and node is not None
            root = Root(
                SessionExecutionOwner(row.id, row.owner_generation),
                row.workspace_id,
                row.agent_id,
                node.id,
                [row.id],
            )
        self.roots.append(root)
        return root

    async def child(self, root: Root, parent_node_id: str) -> Root:
        async with self.foundation.writes() as session:
            child = await AgentSessionRepository().create_child_session_agent(
                session,
                parent_session_agent_id=parent_node_id,
                name=f"child_{len(root.session_ids)}",
                agent_type="default",
                title=None,
                last_task_message=None,
            )
            await AgentSessionRepository().mark_running(session, child.agent_session_id)
            row = await session.read_session.get(
                RDBAgentSession, child.agent_session_id
            )
            assert row is not None
            root.session_ids.append(row.id)
            return Root(
                SessionExecutionOwner(row.id, row.owner_generation),
                row.workspace_id,
                row.agent_id,
                child.id,
                root.session_ids,
            )

    async def sources(self, root: Root) -> list[PersonalEffectiveToolkitConfig]:
        return await self.repository.list_effective(
            owner=root.owner, workspace_id=root.workspace_id, agent_id=root.agent_id
        )


@pytest.fixture
async def runtime(fixture: Fixture) -> AsyncIterator[Harness]:
    h = Harness(
        fixture,
        PersonalToolkitRuntimeRepository(
            fixture.writes, fixture.repository, ToolkitNamespaceRepository(), None
        ),
        [],
    )
    try:
        yield h
    finally:
        async with fixture.writes() as session:
            for root in reversed(h.roots):
                await SessionLifecycleFinalizerRepository().finalize_purged_root_tree(
                    session,
                    root_session_id=root.owner.session_id,
                    session_ids=root.session_ids,
                )
            await session.write_session.execute(
                sa.delete(RDBAgentRuntime).where(
                    RDBAgentRuntime.agent_id.in_(fixture.agent_ids)
                )
            )


async def test_sources_follow_durable_user_root_not_agent_global_inventory(
    runtime: Harness,
) -> None:
    h = runtime
    f = h.foundation
    async with f.writes() as session:
        session.write_session.add(
            RDBWorkspaceUser(
                workspace_id=f.workspace_ids[0],
                user_id=f.other_user_id,
                name="Other",
                role=WorkspaceUserRole.MEMBER,
            )
        )
    mine = await f.operations.create(user_id=f.user_id, create=creation())
    other = await f.operations.create(user_id=f.other_user_id, create=creation())
    first = await h.root(f.user_id, 0)
    second = await h.root(f.other_user_id, 0)
    team = await h.root(None, 0)
    [mine_source] = await h.sources(first)
    [other_source] = await h.sources(second)
    assert mine_source.toolkit.id == mine.id and other_source.toolkit.id == other.id
    assert mine_source.namespace != other_source.namespace
    assert await h.sources(team) == []
    assert (await h.sources(first))[0].namespace == mine_source.namespace
    child = await h.child(first, first.node_id)
    grandchild = await h.child(first, child.node_id)
    for session in [first, child, grandchild]:
        [source] = await h.sources(session)
        assert source.target.owner_user_id == f.user_id
        assert source.target.root_session_id == first.owner.session_id
        assert source.target.execution_owner == session.owner
        assert source.namespace == mine_source.namespace
    with pytest.raises(PersonalToolkitExecutionDenied):
        await h.repository.admit(
            dataclasses.replace(
                mine_source.target,
                owner_user_id=f.other_user_id,
                toolkit_id=other.id,
                source_revision=other.revision,
            )
        )


async def test_current_restriction_and_reallow_reuse_namespace(
    runtime: Harness,
) -> None:
    h = runtime
    f = h.foundation
    toolkit = await f.operations.create(user_id=f.user_id, create=creation())
    root = await h.root(f.user_id, 0)
    [source] = await h.sources(root)
    await h.repository.admit(source.target)
    await f.operations.mutate_access(
        user_id=f.user_id,
        mutations=[
            PersonalToolkitAccessMutation(
                toolkit.id,
                None,
                frozenset(),
                frozenset([root.agent_id]),
                Mode.ALL,
            )
        ],
    )
    with pytest.raises(PersonalToolkitExecutionDenied):
        await h.repository.admit(source.target)
    assert await h.sources(root) == []
    await f.operations.mutate_access(
        user_id=f.user_id,
        mutations=[
            PersonalToolkitAccessMutation(
                toolkit.id,
                None,
                frozenset([root.agent_id]),
                frozenset(),
                Mode.SELECTED,
            )
        ],
    )
    [allowed] = await h.sources(root)
    assert allowed.namespace == source.namespace


@pytest.mark.parametrize(
    "change",
    [
        "membership",
        "disabled_owner",
        "disabled_source",
        "changed_source",
        "deleted_source",
        "owner_generation",
        "workload",
    ],
)
async def test_prepared_source_repeats_current_authority(
    runtime: Harness, change: str
) -> None:
    h = runtime
    f = h.foundation
    toolkit = await f.operations.create(user_id=f.user_id, create=creation())
    root = await h.root(f.user_id, 0)
    [source] = await h.sources(root)
    target = source.target
    if change == "membership":
        async with f.writes() as session:
            await session.write_session.execute(
                sa.delete(RDBWorkspaceUser).where(RDBWorkspaceUser.user_id == f.user_id)
            )
    elif change == "disabled_owner":
        async with f.writes() as session:
            await session.write_session.execute(
                sa.update(RDBUser)
                .where(RDBUser.id == f.user_id)
                .values(access_disabled_at=sa.func.now())
            )
    elif change == "disabled_source":
        await f.operations.update(
            user_id=f.user_id, toolkit_id=toolkit.id, update={"enabled": False}
        )
    elif change == "changed_source":
        await f.operations.update(
            user_id=f.user_id,
            toolkit_id=toolkit.id,
            update={"credentials": '{"token":"replacement"}'},
        )
    elif change == "deleted_source":
        await f.operations.delete(user_id=f.user_id, toolkit_id=toolkit.id)
    elif change == "owner_generation":
        target = dataclasses.replace(
            target,
            execution_owner=dataclasses.replace(
                target.execution_owner,
                owner_generation=target.execution_owner.owner_generation + 1,
            ),
        )
    else:
        target = dataclasses.replace(target, agent_id=f.agent_ids[1])
    with pytest.raises(PersonalToolkitExecutionDenied):
        await h.repository.admit(target)


async def test_provider_grant_absence_does_not_allocate_personal_namespace(
    runtime: Harness,
) -> None:
    h = runtime
    f = h.foundation
    draft = creation().model_copy(
        update={"toolkit_type": "google", "config": {"tasks": []}, "credentials": None}
    )
    toolkit = await f.operations.create(user_id=f.user_id, create=draft)
    root = await h.root(f.user_id, 0)
    assert await h.sources(root) == []
    async with f.writes() as session:
        assert (
            await h.repository.namespaces.get_active(
                session, agent_id=root.agent_id, toolkit_id=toolkit.id
            )
            is None
        )


async def test_unexpected_storage_failure_is_not_empty_success(
    runtime: Harness, monkeypatch: pytest.MonkeyPatch
) -> None:
    h = runtime
    root = await h.root(h.foundation.user_id, 0)
    monkeypatch.setattr(
        PersonalToolkitRuntimeRepository,
        "_subject",
        AsyncMock(side_effect=RuntimeError("fixture DB failure")),
    )
    with pytest.raises(RuntimeError, match="fixture DB failure"):
        await h.sources(root)


@pytest.mark.parametrize("phase", ["started", "admitted"])
async def test_personal_sources_preserve_canonical_archived_continuation_rules(
    runtime: Harness, phase: Literal["started", "admitted"]
) -> None:
    h = runtime
    f = h.foundation
    await f.operations.create(user_id=f.user_id, create=creation())
    root = await h.root(f.user_id, 0)
    [prepared] = await h.sources(root)
    async with f.writes() as session:
        row = await session.read_session.get(RDBAgentSession, root.owner.session_id)
        assert row is not None
        await _archive_with_scheduled_continuation(
            session, agent_session=row, phase=phase
        )
    if phase == "started":
        [current] = await h.sources(root)
        assert current.target == prepared.target
        assert current.namespace == prepared.namespace
        await h.repository.admit(prepared.target)
    else:
        assert await h.sources(root) == []
        with pytest.raises(PersonalToolkitExecutionDenied):
            await h.repository.admit(prepared.target)
