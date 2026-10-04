"""Real PostgreSQL scoped ownership, evidence and atomic private-file regressions."""

import asyncio
import datetime
import hashlib
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from typing import TypedDict

import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker
from uuid6 import uuid7

from azents.core.enums import WorkspaceUserRole
from azents.core.historical_memory_consolidation import (
    ConsolidationJobPrincipal,
    ConsolidationScope,
    ConsolidationUnitKey,
)
from azents.rdb.models.agent import RDBAgent
from azents.rdb.models.historical_memory import RDBHistoricalMemorySource
from azents.rdb.models.historical_memory_consolidation import (
    RDBConsolidationAttempt,
    RDBConsolidationDraftDependency,
    RDBConsolidationDraftFile,
    RDBConsolidationUnit,
    RDBConsolidationWork,
)
from azents.rdb.models.workspace import RDBWorkspace
from azents.rdb.models.workspace_user import RDBWorkspaceUser
from azents.rdb.session import SessionManager
from azents.rdb.session_capabilities import ReadWriteSession, WriteSession
from azents.repos.agent import AgentRepository
from azents.repos.agent_session import AgentSessionRepository
from azents.repos.historical_memory_consolidation.authority import (
    ConsolidationAuthorityBusyError,
    ConsolidationAuthorityError,
)
from azents.repos.historical_memory_consolidation.drafts import (
    ConsolidationDraftConflict,
    ConsolidationDraftRepository,
    DraftFileChange,
    DraftFileObservation,
)
from azents.repos.historical_memory_consolidation.ownership import (
    ConsolidationOwnershipRepository,
)
from azents.repos.historical_memory_consolidation.sources import (
    ConsolidationSourceRepository,
)
from azents.repos.workspace_user import WorkspaceUserRepository
from azents.repos.workspace_user.data import WorkspaceUserCreate
from azents.testing.consolidation import seed_consolidation_corpus as _seed
from azents.testing.model_selection import (
    make_test_model_selection_dict,
    make_test_selectable_model_option_dicts,
)

_NOW = datetime.datetime(2026, 10, 1, tzinfo=datetime.UTC)


class _MutationArguments(TypedDict):
    tool_call_id: str
    request_digest: str
    expected_draft_revision_id: str
    expected_observation_epoch: int
    changes: list[DraftFileChange]


def _change(
    path: str, observation: DraftFileObservation, content: str | None
) -> DraftFileChange:
    return DraftFileChange(
        path=path,
        expected_file_revision_id=observation.file_revision_id,
        content=content,
    )


async def test_exact_scope_reads_and_duplicate_claim(
    rdb_session_manager: SessionManager[WriteSession],
) -> None:
    corpus = await _seed(rdb_session_manager)
    owners = ConsolidationOwnershipRepository(rdb_session_manager)
    team = await owners.claim(corpus.team)
    personal = await owners.claim(corpus.personal)
    assert team is not None and personal is not None
    assert await owners.claim(corpus.team) is None
    assert team.principal.attempt_id != personal.principal.attempt_id
    sources = ConsolidationSourceRepository(rdb_session_manager)
    for claim, own_source, peer_source in (
        (team, corpus.team_source, corpus.personal_source),
        (personal, corpus.personal_source, corpus.team_source),
    ):
        read = await sources.read(
            claim.principal, source_session_id=own_source, offset=0, max_bytes=12000
        )
        assert read.version.summary_generation == 1
        assert read.text.startswith(claim.principal.unit.scope.value)
        with pytest.raises(ConsolidationAuthorityError):
            await sources.read(
                claim.principal,
                source_session_id=peer_source,
                offset=0,
                max_bytes=12000,
            )


async def test_expiry_takeover_fences_old_owner(
    rdb_session_manager: SessionManager[WriteSession],
) -> None:
    corpus = await _seed(rdb_session_manager)
    owners = ConsolidationOwnershipRepository(rdb_session_manager)
    first = await owners.claim(corpus.team)
    assert first is not None
    async with rdb_session_manager() as session:
        await session.write_session.execute(
            sa.update(RDBConsolidationUnit)
            .where(RDBConsolidationUnit.agent_id == corpus.team.agent_id)
            .values(
                lease_until=sa.func.clock_timestamp() - datetime.timedelta(seconds=1)
            )
        )
        await session.write_session.commit()
    second = await owners.claim(corpus.team)
    assert second is not None
    assert second.principal.owner_generation == first.principal.owner_generation + 1
    with pytest.raises(ConsolidationAuthorityError):
        await owners.renew(first.principal)
    assert await owners.renew(second.principal) is not None


async def test_receipt_replay_conflict_and_stale_draft(
    rdb_session_manager: SessionManager[WriteSession],
) -> None:
    corpus = await _seed(rdb_session_manager)
    claim = await ConsolidationOwnershipRepository(rdb_session_manager).claim(
        corpus.team
    )
    assert claim is not None
    drafts = ConsolidationDraftRepository(rdb_session_manager)
    observation = await drafts.observe(claim.principal, path="summary.md")
    assert observation.content is None
    arguments = _MutationArguments(
        tool_call_id="create",
        request_digest=hashlib.sha256(b"exact request").hexdigest(),
        expected_draft_revision_id=observation.draft_revision_id,
        expected_observation_epoch=observation.observation_epoch,
        changes=[_change("summary.md", observation, "overview")],
    )
    result = await drafts.mutate(claim.principal, **arguments)
    assert await drafts.mutate(claim.principal, **arguments) == result
    conflicting = arguments.copy()
    conflicting["request_digest"] = hashlib.sha256(b"other").hexdigest()
    with pytest.raises(ConsolidationDraftConflict, match="digest"):
        await drafts.mutate(claim.principal, **conflicting)
    stale = arguments.copy()
    stale["tool_call_id"] = "new-call"
    with pytest.raises(ConsolidationDraftConflict, match="stale"):
        await drafts.mutate(claim.principal, **stale)
    current = await drafts.observe(claim.principal, path="summary.md")
    assert current.content == "overview"
    assert current.file_revision_id != observation.file_revision_id


async def test_source_exposure_fences_previously_admitted_mutation(
    rdb_session_manager: SessionManager[WriteSession],
) -> None:
    corpus = await _seed(rdb_session_manager)
    claim = await ConsolidationOwnershipRepository(rdb_session_manager).claim(
        corpus.team
    )
    assert claim is not None
    drafts = ConsolidationDraftRepository(rdb_session_manager)
    observation = await drafts.observe(claim.principal, path="summary.md")
    await ConsolidationSourceRepository(rdb_session_manager).read(
        claim.principal, source_session_id=corpus.team_source, offset=0, max_bytes=12000
    )
    with pytest.raises(ConsolidationDraftConflict):
        await drafts.mutate(
            claim.principal,
            tool_call_id="stale",
            request_digest="a" * 64,
            expected_draft_revision_id=observation.draft_revision_id,
            expected_observation_epoch=observation.observation_epoch,
            changes=[_change("summary.md", observation, "premature")],
        )
    current = await drafts.observe(claim.principal, path="summary.md")
    result = await drafts.mutate(
        claim.principal,
        tool_call_id="fresh",
        request_digest="b" * 64,
        expected_draft_revision_id=current.draft_revision_id,
        expected_observation_epoch=current.observation_epoch,
        changes=[_change("summary.md", current, "authorized")],
    )
    assert result.file_count == 1
    async with rdb_session_manager() as session:
        dependencies = list(
            await session.read_session.scalars(
                sa.select(RDBConsolidationDraftDependency)
            )
        )
        assert any(row.source_session_id == corpus.team_source for row in dependencies)


@pytest.mark.parametrize("tree", [True, False])
async def test_archive_restore_never_revives_draft_dependency(
    rdb_session_manager: SessionManager[WriteSession], tree: bool
) -> None:
    corpus = await _seed(rdb_session_manager)
    claim = await ConsolidationOwnershipRepository(rdb_session_manager).claim(
        corpus.team
    )
    assert claim is not None
    await ConsolidationSourceRepository(rdb_session_manager).read(
        claim.principal, source_session_id=corpus.team_source, offset=0, max_bytes=12000
    )
    drafts = ConsolidationDraftRepository(rdb_session_manager)
    observed = await drafts.observe(claim.principal, path="summary.md")
    args = _MutationArguments(
        tool_call_id="before-denial",
        request_digest="d" * 64,
        expected_draft_revision_id=observed.draft_revision_id,
        expected_observation_epoch=observed.observation_epoch,
        changes=[_change("summary.md", observed, "influenced")],
    )
    await drafts.mutate(claim.principal, **args)
    async with rdb_session_manager() as session:
        sessions = AgentSessionRepository()
        if tree:
            await sessions.archive_tree(
                session,
                root_session_id=corpus.team_source,
                session_ids=[corpus.team_source],
                archived_at=_NOW,
                purge_after=None,
                policy_revision=1,
                retention_days=None,
            )
        else:
            await sessions.archive(session, corpus.team_source, ended_at=_NOW)
        await sessions.restore_tree(
            session,
            root_session_id=corpus.team_source,
            session_ids=[corpus.team_source],
        )
        source = await session.read_session.get(
            RDBHistoricalMemorySource, corpus.team_source
        )
        assert source is not None and source.availability_generation == 2
        await session.write_session.commit()
    with pytest.raises(ConsolidationAuthorityError):
        await drafts.observe(claim.principal, path="summary.md")
    with pytest.raises(ConsolidationAuthorityError):
        await drafts.mutate(claim.principal, **args)


async def test_membership_recreated_with_same_row_id_cannot_revive_attempt(
    rdb_session_manager: SessionManager[WriteSession],
) -> None:
    corpus = await _seed(rdb_session_manager)
    owners = ConsolidationOwnershipRepository(rdb_session_manager)
    claim = await owners.claim(corpus.personal)
    assert claim is not None
    async with rdb_session_manager() as session:
        member = await session.read_session.scalar(
            sa.select(RDBWorkspaceUser).where(
                RDBWorkspaceUser.workspace_id == corpus.personal.workspace_id
            )
        )
        assert member is not None
        old_identity, row_id = member.memory_grant_identity, member.id
        await session.write_session.delete(member)
        await session.write_session.flush()
        replacement = RDBWorkspaceUser(
            workspace_id=corpus.personal.workspace_id,
            user_id=corpus.personal.associated_user_id or "invalid",
            name="restored",
            role=WorkspaceUserRole.MEMBER,
        )
        replacement.id = row_id
        session.write_session.add(replacement)
        await session.write_session.flush()
        assert replacement.memory_grant_identity != old_identity
        await session.write_session.commit()
    with pytest.raises(ConsolidationAuthorityError):
        await owners.renew(claim.principal)


async def test_oversized_batch_rolls_back_every_file_and_receipt(
    rdb_session_manager: SessionManager[WriteSession],
) -> None:
    corpus = await _seed(rdb_session_manager)
    claim = await ConsolidationOwnershipRepository(rdb_session_manager).claim(
        corpus.team
    )
    assert claim is not None
    drafts = ConsolidationDraftRepository(rdb_session_manager)
    observed = await drafts.observe(claim.principal, path="summary.md")
    with pytest.raises(ValueError, match="budget"):
        await drafts.mutate(
            claim.principal,
            tool_call_id="too-large",
            request_digest="e" * 64,
            expected_draft_revision_id=observed.draft_revision_id,
            expected_observation_epoch=observed.observation_epoch,
            changes=[
                _change("summary.md", observed, "valid first file"),
                DraftFileChange("second.md", None, "한" * 90000),
            ],
        )
    async with rdb_session_manager() as session:
        assert not list(
            await session.read_session.scalars(sa.select(RDBConsolidationDraftFile))
        )
    current = await drafts.observe(claim.principal, path="summary.md")
    assert current.draft_revision_id == observed.draft_revision_id


async def test_source_purge_retains_independent_influence_and_denies_use(
    rdb_session_manager: SessionManager[WriteSession],
) -> None:
    corpus = await _seed(rdb_session_manager)
    claim = await ConsolidationOwnershipRepository(rdb_session_manager).claim(
        corpus.team
    )
    assert claim is not None
    await ConsolidationSourceRepository(rdb_session_manager).read(
        claim.principal, source_session_id=corpus.team_source, offset=0, max_bytes=12000
    )
    drafts = ConsolidationDraftRepository(rdb_session_manager)
    observed = await drafts.observe(claim.principal, path="summary.md")
    await drafts.mutate(
        claim.principal,
        tool_call_id="dependent",
        request_digest="f" * 64,
        expected_draft_revision_id=observed.draft_revision_id,
        expected_observation_epoch=observed.observation_epoch,
        changes=[_change("summary.md", observed, "depends on purged source")],
    )
    async with rdb_session_manager() as session:
        await session.write_session.execute(
            sa.delete(RDBHistoricalMemorySource).where(
                RDBHistoricalMemorySource.source_session_id == corpus.team_source
            )
        )
        await session.write_session.commit()
    async with rdb_session_manager() as session:
        assert (
            await session.read_session.scalar(
                sa.select(sa.func.count()).select_from(RDBConsolidationDraftDependency)
            )
            == 1
        )
        assert (
            await session.read_session.scalar(
                sa.select(sa.func.count()).select_from(RDBConsolidationWork)
            )
            == 2
        )
    with pytest.raises(ConsolidationAuthorityError):
        await drafts.observe(claim.principal, path="summary.md")


async def test_multifile_commit_and_delete_recreate_never_reuses_identity(
    rdb_session_manager: SessionManager[WriteSession],
) -> None:
    corpus = await _seed(rdb_session_manager)
    claim = await ConsolidationOwnershipRepository(rdb_session_manager).claim(
        corpus.team
    )
    assert claim is not None
    drafts = ConsolidationDraftRepository(rdb_session_manager)
    first = await drafts.observe(claim.principal, path="summary.md")
    second = await drafts.observe(claim.principal, path="notes.md")
    assert first.observation_epoch == second.observation_epoch
    await drafts.mutate(
        claim.principal,
        tool_call_id="batch",
        request_digest="1" * 64,
        expected_draft_revision_id=first.draft_revision_id,
        expected_observation_epoch=first.observation_epoch,
        changes=[
            _change("summary.md", first, "main"),
            _change("notes.md", second, "notes"),
        ],
    )
    before = await drafts.observe(claim.principal, path="notes.md")
    await drafts.mutate(
        claim.principal,
        tool_call_id="delete",
        request_digest="2" * 64,
        expected_draft_revision_id=before.draft_revision_id,
        expected_observation_epoch=before.observation_epoch,
        changes=[_change("notes.md", before, None)],
    )
    absent = await drafts.observe(claim.principal, path="notes.md")
    assert absent.content is None and absent.file_revision_id is None
    await drafts.mutate(
        claim.principal,
        tool_call_id="recreate",
        request_digest="3" * 64,
        expected_draft_revision_id=absent.draft_revision_id,
        expected_observation_epoch=absent.observation_epoch,
        changes=[_change("notes.md", absent, "notes")],
    )
    after = await drafts.observe(claim.principal, path="notes.md")
    assert after.content == before.content
    assert after.file_revision_id != before.file_revision_id
    assert after.draft_revision_id != before.draft_revision_id


async def test_membership_repository_restores_fresh_enrollment(
    rdb_session_manager: SessionManager[WriteSession],
) -> None:
    corpus = await _seed(rdb_session_manager)
    assert corpus.personal.associated_user_id is not None
    async with rdb_session_manager() as session:
        member = await session.read_session.scalar(
            sa.select(RDBWorkspaceUser).where(
                RDBWorkspaceUser.workspace_id == corpus.personal.workspace_id
            )
        )
        assert member is not None
        old_grant = member.memory_grant_identity
        repository = WorkspaceUserRepository()
        await repository.delete(session, member.id)
        await repository.create(
            session,
            WorkspaceUserCreate(
                workspace_id=corpus.personal.workspace_id,
                user_id=corpus.personal.associated_user_id,
                name="restored",
                role=WorkspaceUserRole.MEMBER,
            ),
        )
        await session.write_session.flush()
        work = list(
            await session.read_session.scalars(
                sa.select(RDBConsolidationWork)
                .where(RDBConsolidationWork.source_session_id == corpus.personal_source)
                .order_by(RDBConsolidationWork.sequence)
            )
        )
        assert len(work) == 3
        assert work[0].membership_grant_id == work[1].membership_grant_id == old_grant
        assert work[2].membership_grant_id != old_grant
        assert work[0].summary_generation == work[2].summary_generation == 1


async def test_two_real_transactions_admit_exactly_one_owner(
    rdb_engine: AsyncEngine, latest_db_schema: None
) -> None:
    """Two released contenders use independent connections and committed state."""
    factory = async_sessionmaker(rdb_engine, expire_on_commit=False)

    @asynccontextmanager
    async def manager() -> AsyncGenerator[WriteSession, None]:
        async with factory.begin() as session:
            yield ReadWriteSession(session)

    slug = uuid7().hex
    async with manager() as session:
        workspace = RDBWorkspace(name=slug, handle=slug)
        session.write_session.add(workspace)
        await session.write_session.flush()
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
        session.write_session.add(agent)
        await session.write_session.flush()
        key = ConsolidationUnitKey(
            agent_id=agent.id,
            workspace_id=workspace.id,
            scope=ConsolidationScope.TEAM,
            associated_user_id=None,
        )
    try:
        gate = asyncio.Event()
        repository = ConsolidationOwnershipRepository(manager)

        async def contender() -> bool:
            await gate.wait()
            return await repository.claim(key) is not None

        left = asyncio.create_task(contender())
        right = asyncio.create_task(contender())
        gate.set()
        assert sorted(await asyncio.gather(left, right)) == [False, True]
        async with manager() as session:
            unit = await session.write_session.scalar(
                sa.select(RDBConsolidationUnit).where(
                    RDBConsolidationUnit.agent_id == key.agent_id
                )
            )
            assert unit is not None and unit.owner_generation == 1
            assert unit.active_attempt_id is not None and unit.owner_token is not None
            principal = ConsolidationJobPrincipal(
                unit=key,
                attempt_id=unit.active_attempt_id,
                owner_generation=unit.owner_generation,
                owner_token=unit.owner_token,
            )
            assert (
                await session.write_session.scalar(
                    sa.select(sa.func.count())
                    .select_from(RDBConsolidationAttempt)
                    .where(RDBConsolidationAttempt.unit_id == unit.id)
                )
                == 1
            )
        async with manager() as holder:
            await holder.write_session.scalar(
                sa.select(RDBAgent).where(RDBAgent.id == key.agent_id).with_for_update()
            )
            with pytest.raises(ConsolidationAuthorityBusyError, match="temporarily"):
                await repository.renew(principal)
        assert await repository.renew(principal) is not None
    finally:
        async with manager() as session:
            await session.write_session.execute(
                sa.delete(RDBAgent).where(RDBAgent.id == key.agent_id)
            )
            await session.write_session.execute(
                sa.delete(RDBWorkspace).where(RDBWorkspace.id == key.workspace_id)
            )


@pytest.mark.parametrize("personal", [False, True])
async def test_memory_disable_restore_retains_denial_continuity(
    rdb_session_manager: SessionManager[WriteSession], personal: bool
) -> None:
    corpus = await _seed(rdb_session_manager)
    key = corpus.personal if personal else corpus.team
    source_id = corpus.personal_source if personal else corpus.team_source
    claim = await ConsolidationOwnershipRepository(rdb_session_manager).claim(key)
    assert claim is not None
    await ConsolidationSourceRepository(rdb_session_manager).read(
        claim.principal, source_session_id=source_id, offset=0, max_bytes=12000
    )
    drafts = ConsolidationDraftRepository(rdb_session_manager)
    before = await drafts.observe(claim.principal, path="summary.md")
    await drafts.mutate(
        claim.principal,
        tool_call_id="memory-dependency",
        request_digest="4" * 64,
        expected_draft_revision_id=before.draft_revision_id,
        expected_observation_epoch=before.observation_epoch,
        changes=[_change("summary.md", before, "depends on Memory authority")],
    )
    async with rdb_session_manager() as session:
        agents = AgentRepository()
        await agents.update_by_id(session, key.agent_id, {"memory_enabled": False})
        await agents.update_by_id(session, key.agent_id, {"memory_enabled": True})
        source = await session.read_session.get(RDBHistoricalMemorySource, source_id)
        assert source is not None and source.availability_generation == 2
        await session.write_session.commit()
    with pytest.raises(ConsolidationAuthorityError):
        await drafts.observe(claim.principal, path="summary.md")
