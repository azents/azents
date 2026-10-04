"""Independent source inventory, evidence receipts and denial-continuity checks."""

from dataclasses import dataclass

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import insert
from uuid6 import uuid7

from azents.core.enums import (
    AgentSessionKind,
    AgentSessionProductMode,
    AgentSessionStatus,
)
from azents.core.historical_memory_consolidation import (
    ConsolidationJobPrincipal,
    ConsolidationScope,
    ConsolidationSourceVersion,
    ConsolidationUnitKey,
)
from azents.rdb.models.agent_session import RDBAgentSession
from azents.rdb.models.historical_memory import RDBHistoricalMemorySource
from azents.rdb.models.historical_memory_consolidation import RDBConsolidationEvidence
from azents.rdb.session import SessionManager
from azents.rdb.session_capabilities import WriteSession
from azents.repos.historical_memory_consolidation.authority import (
    ConsolidationAuthorityError,
    LockedConsolidationOwner,
    consolidation_job_session,
    require_commit_owner,
)


@dataclass(frozen=True)
class ConsolidationSourceRead:
    """Current bounded evidence and its committed attempt-ledger boundary."""

    version: ConsolidationSourceVersion
    title: str | None
    text: str
    next_offset: int | None
    observation_epoch: int


@dataclass(frozen=True)
class ConsolidationSourceInventoryEntry:
    """Only scoped, body-free metadata actually exposed by the inventory page."""

    version: ConsolidationSourceVersion
    title_snippet: str | None


@dataclass(frozen=True)
class ConsolidationSourceInventoryPage:
    """Bounded source inventory and an explicit stable continuation cursor."""

    entries: tuple[ConsolidationSourceInventoryEntry, ...]
    next_after: str | None
    observation_epoch: int


def source_predicate(key: ConsolidationUnitKey) -> sa.ColumnElement[bool]:
    """Require the source's exact corpus, never the foreground combined view."""
    mode = (
        AgentSessionProductMode.TEAM
        if key.scope is ConsolidationScope.TEAM
        else AgentSessionProductMode.USER
    )
    return sa.and_(
        RDBAgentSession.agent_id == key.agent_id,
        RDBAgentSession.workspace_id == key.workspace_id,
        RDBAgentSession.product_mode == mode,
        RDBAgentSession.associated_user_id.is_not_distinct_from(key.associated_user_id),
        RDBAgentSession.session_kind == AgentSessionKind.ROOT,
        RDBAgentSession.status == AgentSessionStatus.ACTIVE,
    )


async def lock_source(
    session: WriteSession,
    *,
    key: ConsolidationUnitKey,
    source_session_id: str,
) -> RDBHistoricalMemorySource:
    """Lock root then current evidence without waiting on source/lifecycle writers."""
    root = await session.write_session.scalar(
        sa.select(RDBAgentSession)
        .where(RDBAgentSession.id == source_session_id, source_predicate(key))
        .with_for_update(read=True, nowait=True)
    )
    if root is None:
        raise ConsolidationAuthorityError("Consolidation source is unavailable.")
    source = await session.write_session.scalar(
        sa.select(RDBHistoricalMemorySource)
        .where(RDBHistoricalMemorySource.source_session_id == source_session_id)
        .with_for_update(read=True, nowait=True)
    )
    if source is None:
        raise ConsolidationAuthorityError("Consolidation source is unavailable.")
    return source


async def record_evidence(
    session: WriteSession,
    *,
    owner: LockedConsolidationOwner,
    version: ConsolidationSourceVersion,
) -> None:
    """Commit exposure receipt and ledger epoch before model-visible return."""
    await session.write_session.execute(
        insert(RDBConsolidationEvidence)
        .values(id=uuid7().hex, attempt_id=owner.attempt.id, **version.model_dump())
        .on_conflict_do_nothing(
            constraint="uq_historical_consolidation_evidence_version"
        )
    )
    owner.attempt.observation_epoch += 1
    await session.write_session.flush()


@dataclass(frozen=True)
class ConsolidationSourceRepository:
    """Source reads establish conservative dependencies in a private attempt ledger."""

    session_manager: SessionManager[WriteSession]

    async def inventory(
        self,
        principal: ConsolidationJobPrincipal,
        *,
        after: str | None,
        limit: int,
        source_id_prefix: str | None,
    ) -> ConsolidationSourceInventoryPage:
        """Expose at most fifty scoped source identities and receipt each one."""
        if not 1 <= limit <= 50:
            raise ValueError("Consolidation inventory limit must be 1-50.")
        if source_id_prefix is not None and (
            not 1 <= len(source_id_prefix) <= 32
            or any(
                character not in "0123456789abcdef" for character in source_id_prefix
            )
        ):
            raise ValueError("Consolidation source prefix is invalid.")
        async with consolidation_job_session(self.session_manager, principal) as job:
            session, owner = job.session, job.owner
            query = (
                sa.select(RDBHistoricalMemorySource.source_session_id)
                .join(
                    RDBAgentSession,
                    RDBAgentSession.id == RDBHistoricalMemorySource.source_session_id,
                )
                .where(
                    source_predicate(principal.unit),
                    RDBHistoricalMemorySource.prepared_at.is_not(None),
                    RDBHistoricalMemorySource.summary_generation > 0,
                    RDBHistoricalMemorySource.evidence_hash.is_not(None),
                )
                .order_by(RDBHistoricalMemorySource.source_session_id)
                .limit(limit + 1)
            )
            if after is not None:
                query = query.where(RDBHistoricalMemorySource.source_session_id > after)
            if source_id_prefix is not None:
                query = query.where(
                    RDBHistoricalMemorySource.source_session_id == source_id_prefix
                    if len(source_id_prefix) == 32
                    else RDBHistoricalMemorySource.source_session_id.startswith(
                        source_id_prefix
                    )
                )
            ids = list(await session.write_session.scalars(query))
            entries: list[ConsolidationSourceInventoryEntry] = []
            for source_id in ids[:limit]:
                source = await lock_source(
                    session, key=principal.unit, source_session_id=source_id
                )
                if source.evidence_hash is None:
                    raise ConsolidationAuthorityError(
                        "Consolidation source is unavailable."
                    )
                version = ConsolidationSourceVersion(
                    source_session_id=source_id,
                    summary_generation=source.summary_generation,
                    evidence_hash=source.evidence_hash,
                    availability_generation=source.availability_generation,
                    membership_grant_id=owner.attempt.membership_grant_id,
                )
                await record_evidence(session, owner=owner, version=version)
                title = source.source_title_snapshot
                entries.append(
                    ConsolidationSourceInventoryEntry(
                        version=version,
                        title_snippet=(
                            None
                            if title is None
                            else title.encode("utf-8")[:512].decode(
                                "utf-8", errors="ignore"
                            )
                        ),
                    )
                )
            await require_commit_owner(session, owner)
            result = ConsolidationSourceInventoryPage(
                entries=tuple(entries),
                next_after=ids[limit - 1] if len(ids) > limit else None,
                observation_epoch=owner.attempt.observation_epoch,
            )
        return result

    async def read(
        self,
        principal: ConsolidationJobPrincipal,
        *,
        source_session_id: str,
        offset: int,
        max_bytes: int,
    ) -> ConsolidationSourceRead:
        """Read bounded exact current evidence, including meaningful empty summaries."""
        if offset < 0 or not 4 <= max_bytes <= 12000:
            raise ValueError("Consolidation source read bounds are invalid.")
        async with consolidation_job_session(self.session_manager, principal) as job:
            session, owner = job.session, job.owner
            source = await lock_source(
                session, key=principal.unit, source_session_id=source_session_id
            )
            if (
                source.prepared_at is None
                or source.summary_generation < 1
                or source.evidence_hash is None
            ):
                raise ConsolidationAuthorityError(
                    "Consolidation source is unavailable."
                )
            version = ConsolidationSourceVersion(
                source_session_id=source_session_id,
                summary_generation=source.summary_generation,
                evidence_hash=source.evidence_hash,
                availability_generation=source.availability_generation,
                membership_grant_id=owner.attempt.membership_grant_id,
            )
            summary = source.summary or ""
            text = (
                summary[offset:]
                .encode("utf-8")[:max_bytes]
                .decode("utf-8", errors="ignore")
            )
            end = offset + len(text)
            await record_evidence(session, owner=owner, version=version)
            result = ConsolidationSourceRead(
                version=version,
                title=source.source_title_snapshot,
                text=text,
                next_offset=end if end < len(summary) else None,
                observation_epoch=owner.attempt.observation_epoch,
            )
            await require_commit_owner(session, owner)
        return result
