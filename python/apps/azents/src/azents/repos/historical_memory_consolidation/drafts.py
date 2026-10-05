"""Fenced atomic private file transactions with complete conservative influence."""

from collections.abc import Sequence
from dataclasses import dataclass

import sqlalchemy as sa
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.dialects.postgresql import ARRAY, insert
from sqlalchemy.sql.selectable import Subquery
from uuid6 import uuid7

from azents.core.historical_memory_consolidation import (
    ConsolidationJobPrincipal,
    ConsolidationUnitKey,
)
from azents.rdb.models.agent_session import RDBAgentSession
from azents.rdb.models.historical_memory import RDBHistoricalMemorySource
from azents.rdb.models.historical_memory_consolidation import (
    RDBConsolidationDraft,
    RDBConsolidationDraftDependency,
    RDBConsolidationDraftFile,
    RDBConsolidationEvidence,
    RDBConsolidationMutationReceipt,
    RDBConsolidationRevision,
    RDBConsolidationRevisionDependency,
)
from azents.rdb.session import SessionManager
from azents.rdb.session_capabilities import WriteSession
from azents.repos.historical_memory_consolidation.authority import (
    ConsolidationAuthorityError,
    LockedConsolidationOwner,
    consolidation_job_session,
    require_commit_owner,
)
from azents.repos.historical_memory_consolidation.participant_types import (
    DraftParticipants,
)
from azents.repos.historical_memory_consolidation.participants import (
    ConsolidationParticipantPlan,
)
from azents.repos.historical_memory_consolidation.retry import (
    retry_consolidation_operation,
)
from azents.repos.historical_memory_consolidation.sources import source_predicate


class ConsolidationDraftConflict(ValueError):
    """Missing observation, applicability conflict or stale file/draft ledger."""


@dataclass(frozen=True)
class DraftFileObservation:
    """Server-owned read evidence; never accepted from model tool arguments."""

    draft_revision_id: str
    file_revision_id: str | None
    observation_epoch: int
    content: str | None


@dataclass(frozen=True)
class DraftFileChange:
    """One admitted exact replacement or deletion with its read precondition."""

    path: str
    expected_file_revision_id: str | None
    content: str | None


@dataclass(frozen=True)
class DraftObservedFile:
    """One private file and its execution-safe read identity."""

    path: str
    observation: DraftFileObservation


class DraftMutationResult(BaseModel):
    """Bounded safe committed metadata, suitable for idempotent receipt replay."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    draft_revision_id: str = Field(min_length=32, max_length=32)
    changed_paths: tuple[str, ...]
    file_count: int = Field(ge=0)
    byte_count: int = Field(ge=0)


def require_draft_path(path: str) -> None:
    """Restrict private relative keys without aliases, traversal or glob ambiguity."""
    if (
        not path
        or len(path) > 512
        or path.startswith("/")
        or any(part in {"", ".", ".."} for part in path.split("/"))
        or any(character in path for character in "\\\x00\r\n:*?[]{}%")
    ):
        raise ValueError("Private draft file path is invalid.")


async def check_draft_influence(
    session: WriteSession,
    *,
    principal: ConsolidationJobPrincipal,
    owner: LockedConsolidationOwner,
    draft: RDBConsolidationDraft,
) -> None:
    """Recheck all prior working prose and current attempt exposures before use."""
    if draft.invalidated:
        raise ConsolidationAuthorityError("Consolidation draft is unavailable.")
    inherited = sa.select(
        RDBConsolidationDraftDependency.source_session_id,
        RDBConsolidationDraftDependency.summary_generation,
        RDBConsolidationDraftDependency.evidence_hash,
        RDBConsolidationDraftDependency.availability_generation,
        RDBConsolidationDraftDependency.membership_grant_id,
    ).where(RDBConsolidationDraftDependency.draft_id == draft.id)
    exposed = sa.select(
        RDBConsolidationEvidence.source_session_id,
        RDBConsolidationEvidence.summary_generation,
        RDBConsolidationEvidence.evidence_hash,
        RDBConsolidationEvidence.availability_generation,
        RDBConsolidationEvidence.membership_grant_id,
    ).where(RDBConsolidationEvidence.attempt_id == principal.attempt_id)
    influence = inherited.union_all(exposed).subquery("complete_draft_influence")
    if owner.participants is None:
        raise RuntimeError("Consolidation manifest participants are missing.")
    await check_dependency_manifest(
        session,
        key=principal.unit,
        membership_grant_id=owner.attempt.membership_grant_id,
        influence=influence,
        participants=owner.participants,
    )


async def check_dependency_manifest(
    session: WriteSession,
    *,
    key: ConsolidationUnitKey,
    membership_grant_id: str | None,
    influence: Subquery,
    participants: ConsolidationParticipantPlan,
) -> None:
    """Recheck a complete independent manifest under caller-owned authority."""
    source_ids = sa.select(influence.c.source_session_id).distinct()
    expected = sa.select(sa.func.count()).select_from(source_ids.subquery())
    # Permission/version validation stays server-side. These queries cannot
    # acquire a new row after unit ownership: all existing identities, including
    # archived ones, were locked before the unit. Frozen missing identities
    # cannot become accepted if a row appears between validation and use.
    roots = (
        sa.select(RDBAgentSession.id)
        .where(
            RDBAgentSession.id.in_(source_ids),
            RDBAgentSession.id
            == sa.any_(
                sa.literal(sorted(participants.locked_root_ids), type_=ARRAY(sa.Text()))
            ),
            source_predicate(key),
        )
        .order_by(RDBAgentSession.id)
        .subquery()
    )
    roots_complete = await session.write_session.scalar(
        sa.select(
            sa.select(sa.func.count()).select_from(roots).scalar_subquery()
            == expected.scalar_subquery()
        )
    )
    if not roots_complete:
        raise ConsolidationAuthorityError("Consolidation source is unavailable.")
    sources = (
        sa.select(RDBHistoricalMemorySource.source_session_id)
        .where(
            RDBHistoricalMemorySource.source_session_id.in_(source_ids),
            RDBHistoricalMemorySource.source_session_id
            == sa.any_(
                sa.literal(
                    sorted(participants.locked_source_ids), type_=ARRAY(sa.Text())
                )
            ),
        )
        .order_by(RDBHistoricalMemorySource.source_session_id)
        .subquery()
    )
    sources_complete = await session.write_session.scalar(
        sa.select(
            sa.select(sa.func.count()).select_from(sources).scalar_subquery()
            == expected.scalar_subquery()
        )
    )
    if not sources_complete:
        raise ConsolidationAuthorityError("Consolidation source is unavailable.")
    invalid = (
        sa.select(1)
        .select_from(influence)
        .join(
            RDBHistoricalMemorySource,
            RDBHistoricalMemorySource.source_session_id
            == influence.c.source_session_id,
        )
        .where(
            sa.or_(
                RDBHistoricalMemorySource.availability_generation
                != influence.c.availability_generation,
                influence.c.membership_grant_id.is_distinct_from(membership_grant_id),
                RDBHistoricalMemorySource.summary_generation
                < influence.c.summary_generation,
                sa.and_(
                    RDBHistoricalMemorySource.summary_generation
                    == influence.c.summary_generation,
                    RDBHistoricalMemorySource.evidence_hash.is_distinct_from(
                        influence.c.evidence_hash
                    ),
                ),
            )
        )
    )
    if await session.write_session.scalar(sa.select(invalid.exists())):
        raise ConsolidationAuthorityError("Consolidation evidence is no longer valid.")


async def copy_draft_dependencies(
    session: WriteSession,
    *,
    draft_id: str,
    source: type[RDBConsolidationEvidence] | type[RDBConsolidationRevisionDependency],
    predicate: sa.ColumnElement[bool],
) -> None:
    """Copy the complete body-free manifest server-side in one indexed statement."""
    await session.write_session.execute(
        insert(RDBConsolidationDraftDependency)
        .from_select(
            [
                "id",
                "draft_id",
                "source_session_id",
                "summary_generation",
                "evidence_hash",
                "availability_generation",
                "membership_grant_id",
            ],
            sa.select(
                sa.func.replace(sa.cast(sa.func.gen_random_uuid(), sa.Text), "-", ""),
                sa.literal(draft_id),
                source.source_session_id,
                source.summary_generation,
                source.evidence_hash,
                source.availability_generation,
                source.membership_grant_id,
            ).where(predicate),
        )
        .on_conflict_do_nothing(
            constraint="uq_historical_consolidation_draft_dependencies_version"
        )
    )


@dataclass(frozen=True)
class ConsolidationDraftRepository:
    """Own database-only file/manifest/receipt transactions, without Runtime I/O."""

    session_manager: SessionManager[WriteSession]

    @retry_consolidation_operation
    async def inventory(
        self, principal: ConsolidationJobPrincipal
    ) -> tuple[DraftObservedFile, ...]:
        """Read the bounded private set after rechecking its entire influence."""
        async with consolidation_job_session(
            self.session_manager,
            principal,
            participants=DraftParticipants(recovery=False),
        ) as job:
            session, owner = job.session, job.owner
            draft = await self._draft(session, owner)
            await check_draft_influence(
                session, principal=principal, owner=owner, draft=draft
            )
            files = await session.write_session.scalars(
                sa.select(RDBConsolidationDraftFile)
                .where(RDBConsolidationDraftFile.draft_id == draft.id)
                .order_by(RDBConsolidationDraftFile.path)
            )
            result = tuple(
                DraftObservedFile(
                    path=file.path,
                    observation=DraftFileObservation(
                        draft_revision_id=draft.revision_id,
                        file_revision_id=file.revision_id,
                        observation_epoch=owner.attempt.observation_epoch,
                        content=file.content,
                    ),
                )
                for file in files
            )
            await require_commit_owner(session, owner)
        return result

    @retry_consolidation_operation
    async def observe(
        self, principal: ConsolidationJobPrincipal, *, path: str
    ) -> DraftFileObservation:
        """Observe current text or confirmed absence with a non-reusable revision."""
        require_draft_path(path)
        async with consolidation_job_session(
            self.session_manager,
            principal,
            participants=DraftParticipants(recovery=False),
        ) as job:
            session, owner = job.session, job.owner
            draft = await self._draft(session, owner)
            await check_draft_influence(
                session, principal=principal, owner=owner, draft=draft
            )
            file = await session.write_session.get(
                RDBConsolidationDraftFile, (draft.id, path)
            )
            result = DraftFileObservation(
                draft_revision_id=draft.revision_id,
                file_revision_id=None if file is None else file.revision_id,
                observation_epoch=owner.attempt.observation_epoch,
                content=None if file is None else file.content,
            )
            await require_commit_owner(session, owner)
            await session.write_session.flush()
        return result

    @retry_consolidation_operation
    async def replay_receipt(
        self,
        principal: ConsolidationJobPrincipal,
        *,
        tool_call_id: str,
        request_digest: str,
    ) -> DraftMutationResult | None:
        """Reauthorize safe replay before evaluating text applicability."""
        async with consolidation_job_session(
            self.session_manager,
            principal,
            participants=DraftParticipants(recovery=False),
        ) as job:
            session, owner = job.session, job.owner
            draft = await self._draft(session, owner)
            await check_draft_influence(
                session, principal=principal, owner=owner, draft=draft
            )
            receipt = await session.write_session.get(
                RDBConsolidationMutationReceipt, (principal.attempt_id, tool_call_id)
            )
            if receipt is None:
                return None
            if receipt.request_digest != request_digest:
                raise ConsolidationDraftConflict("Mutation receipt digest conflicts.")
            result = DraftMutationResult.model_validate(receipt.result_json)
            await require_commit_owner(session, owner)
        return result

    @retry_consolidation_operation
    async def mutate(
        self,
        principal: ConsolidationJobPrincipal,
        *,
        tool_call_id: str,
        request_digest: str,
        expected_draft_revision_id: str,
        expected_observation_epoch: int,
        changes: Sequence[DraftFileChange],
    ) -> DraftMutationResult:
        """Commit an entire admitted batch; reauthorize before receipt replay."""
        if not 1 <= len(tool_call_id) <= 256:
            raise ValueError("Private mutation tool-call identity is invalid.")
        if len(request_digest) != 64 or any(
            character not in "0123456789abcdef" for character in request_digest
        ):
            raise ValueError("Private mutation request digest is invalid.")
        if not changes:
            raise ValueError("Private mutation batch must contain files.")
        paths = [change.path for change in changes]
        if len(set(paths)) != len(paths):
            raise ValueError("Private mutation batch repeats a file path.")
        for path in paths:
            require_draft_path(path)
        async with consolidation_job_session(
            self.session_manager,
            principal,
            participants=DraftParticipants(recovery=False),
        ) as job:
            session, owner = job.session, job.owner
            draft = await self._draft(session, owner)
            await check_draft_influence(
                session, principal=principal, owner=owner, draft=draft
            )
            receipt = await session.write_session.get(
                RDBConsolidationMutationReceipt, (principal.attempt_id, tool_call_id)
            )
            if receipt is not None:
                if receipt.request_digest != request_digest:
                    raise ConsolidationDraftConflict(
                        "Mutation receipt digest conflicts."
                    )
                result = DraftMutationResult.model_validate(receipt.result_json)
                await require_commit_owner(session, owner)
                return result
            if (
                draft.revision_id != expected_draft_revision_id
                or owner.attempt.observation_epoch != expected_observation_epoch
            ):
                raise ConsolidationDraftConflict("Draft read evidence is stale.")
            files = {
                file.path: file
                for file in await session.write_session.scalars(
                    sa.select(RDBConsolidationDraftFile).where(
                        RDBConsolidationDraftFile.draft_id == draft.id
                    )
                )
            }
            projected = {path: file.content for path, file in files.items()}
            for change in changes:
                existing = files.get(change.path)
                revision = None if existing is None else existing.revision_id
                if revision != change.expected_file_revision_id:
                    raise ConsolidationDraftConflict("File read evidence is stale.")
                if change.content is None:
                    if existing is None:
                        raise ConsolidationDraftConflict("File is already absent.")
                    del projected[change.path]
                else:
                    projected[change.path] = change.content
            byte_count = sum(
                len(content.encode("utf-8")) for content in projected.values()
            )
            made_progress = projected != {
                path: file.content for path, file in files.items()
            }
            for change in changes:
                existing = files.get(change.path)
                if change.content is None:
                    if existing is not None:
                        await session.write_session.delete(existing)
                elif existing is None:
                    session.write_session.add(
                        RDBConsolidationDraftFile(
                            draft_id=draft.id,
                            path=change.path,
                            revision_id=uuid7().hex,
                            content=change.content,
                        )
                    )
                else:
                    existing.content = change.content
                    existing.revision_id = uuid7().hex
            await copy_draft_dependencies(
                session,
                draft_id=draft.id,
                source=RDBConsolidationEvidence,
                predicate=RDBConsolidationEvidence.attempt_id == principal.attempt_id,
            )
            if made_progress:
                draft.last_progress_at = owner.database_now
            draft.revision_id = uuid7().hex
            draft.file_count = len(projected)
            draft.byte_count = byte_count
            result = DraftMutationResult(
                draft_revision_id=draft.revision_id,
                changed_paths=tuple(paths),
                file_count=draft.file_count,
                byte_count=draft.byte_count,
            )
            session.write_session.add(
                RDBConsolidationMutationReceipt(
                    attempt_id=principal.attempt_id,
                    tool_call_id=tool_call_id,
                    request_digest=request_digest,
                    result_json=result.model_dump(mode="json"),
                )
            )
            await require_commit_owner(session, owner)
            await session.write_session.flush()
        return result

    async def _draft(
        self, session: WriteSession, owner: LockedConsolidationOwner
    ) -> RDBConsolidationDraft:
        """Initialize once from published prose and its body-free dependencies."""
        draft = await session.write_session.scalar(
            sa.select(RDBConsolidationDraft).where(
                RDBConsolidationDraft.unit_id == owner.unit.id
            )
        )
        if draft is not None:
            return draft
        draft = RDBConsolidationDraft(
            id=uuid7().hex,
            unit_id=owner.unit.id,
            revision_id=uuid7().hex,
            base_revision_id=owner.unit.published_revision_id,
        )
        session.write_session.add(draft)
        await session.write_session.flush()
        if owner.unit.published_revision_id is not None:
            revision = await session.write_session.get(
                RDBConsolidationRevision, owner.unit.published_revision_id
            )
            if revision is None or revision.unit_id != owner.unit.id:
                raise ConsolidationAuthorityError(
                    "Consolidation checkpoint is unavailable."
                )
            session.write_session.add(
                RDBConsolidationDraftFile(
                    draft_id=draft.id,
                    path="summary.md",
                    revision_id=uuid7().hex,
                    content=revision.markdown,
                )
            )
            draft.file_count = 1
            draft.byte_count = len(revision.markdown.encode("utf-8"))
            await copy_draft_dependencies(
                session,
                draft_id=draft.id,
                source=RDBConsolidationRevisionDependency,
                predicate=RDBConsolidationRevisionDependency.revision_id == revision.id,
            )
        await session.write_session.flush()
        return draft
