"""Synthetic whole-document fixtures and genuine repository publication helpers."""

import datetime

from uuid6 import uuid7

from azents.core.historical_memory_consolidation import (
    ConsolidationDisposition,
    ConsolidationScope,
    ConsolidationUnitKey,
)
from azents.core.historical_memory_publication import (
    ConsolidationCoverage,
    ConsolidationWorkDisposition,
    validate_consolidation_overview,
)
from azents.core.historical_memory_snapshot import ConsolidatedMemorySnapshotEntry
from azents.rdb.session import SessionManager
from azents.rdb.session_capabilities import WriteSession
from azents.repos.historical_memory_consolidation.drafts import (
    ConsolidationDraftRepository,
    DraftFileChange,
)
from azents.repos.historical_memory_consolidation.ownership import (
    ConsolidationOwnershipRepository,
)
from azents.repos.historical_memory_consolidation.publication import (
    ConsolidationPublicationRepository,
)
from azents.repos.historical_memory_consolidation.recovery import (
    ConsolidationRecoveryRepository,
)
from azents.repos.historical_memory_consolidation.work import (
    ConsolidationWorkRepository,
)

CONTEXT_FIXTURE_TIME = datetime.datetime(2026, 10, 3, tzinfo=datetime.UTC)


def context_entry(
    *,
    scope: ConsolidationScope,
    text: str,
    exact_bytes: int | None,
) -> ConsolidatedMemorySnapshotEntry:
    """Build valid self-contained envelopes, optionally at an exact byte boundary."""
    key = ConsolidationUnitKey(
        agent_id="a" * 32,
        workspace_id="b" * 32,
        scope=scope,
        associated_user_id="c" * 32 if scope is ConsolidationScope.USER else None,
    )
    route = (
        f"- azents://memory/historical/{scope.value}/{'d' * 32}/summary.md — Details\n"
    )
    markdown = f"## Historical Context\n{text}\n\n## Source Routes\n{route}"
    overview = validate_consolidation_overview(key=key, markdown=markdown)
    if exact_bytes is not None:
        missing = exact_bytes - len(overview.rendered_block.encode())
        assert missing >= 0
        markdown = markdown.replace(text, text + "x" * missing, 1)
        overview = validate_consolidation_overview(key=key, markdown=markdown)
        assert len(overview.rendered_block.encode()) == exact_bytes
    return ConsolidatedMemorySnapshotEntry(
        unit=key,
        unit_id=uuid7().hex,
        revision_id=uuid7().hex,
        rendered_block=overview.rendered_block,
        published_at=CONTEXT_FIXTURE_TIME,
    )


async def publish_context_overview(
    manager: SessionManager[WriteSession],
    *,
    key: ConsolidationUnitKey,
    markdown: str,
) -> str:
    """Publish through real evidence, draft, exact coverage and ownership fences."""
    claim = await ConsolidationOwnershipRepository(manager).claim(key)
    assert claim is not None
    principal = claim.principal
    await ConsolidationRecoveryRepository(manager).prepare(principal)
    work = ConsolidationWorkRepository(manager)
    page = await work.page(principal, after_sequence=None, limit=50)
    assert page.entries
    coverage = ConsolidationCoverage(
        dispositions=tuple(
            ConsolidationWorkDisposition(
                work_id=entry.work_id,
                action=ConsolidationDisposition.CONSIDERED,
                reason="Synthetic integration fixture",
            )
            for entry in page.entries
        )
    )
    drafts = ConsolidationDraftRepository(manager)
    summary = await drafts.observe(principal, path="summary.md")
    journal = await drafts.observe(principal, path="coverage.json")
    await drafts.mutate(
        principal,
        tool_call_id=uuid7().hex,
        request_digest="a" * 64,
        expected_draft_revision_id=summary.draft_revision_id,
        expected_observation_epoch=summary.observation_epoch,
        changes=[
            DraftFileChange("summary.md", summary.file_revision_id, markdown),
            DraftFileChange(
                "coverage.json", journal.file_revision_id, coverage.model_dump_json()
            ),
        ],
    )
    repository = ConsolidationPublicationRepository(manager)
    frozen = await repository.freeze(principal)
    await work.record_coverage(
        principal,
        expected_draft_revision_id=frozen.revision_id,
        coverage=frozen.coverage,
    )
    result = await repository.publish(
        principal,
        expected_draft_revision_id=frozen.revision_id,
        expected_observation_epoch=frozen.observation_epoch,
        overview=validate_consolidation_overview(key=key, markdown=markdown),
    )
    return result.revision_id
