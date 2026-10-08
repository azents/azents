"""Whole-document fixtures and real explicit current-result submissions."""

import datetime

from uuid6 import uuid7

from azents.core.historical_memory_consolidation import (
    ConsolidationScope,
    ConsolidationUnitKey,
    MemoryAcceptedOutcome,
)
from azents.core.historical_memory_publication import render_submitted_markdown
from azents.core.historical_memory_snapshot import ConsolidatedMemorySnapshotEntry
from azents.rdb.session import SessionManager
from azents.rdb.session_capabilities import WriteSession
from azents.repos.session_execution_file import SessionExecutionFileRepository
from azents.testing.consolidation import memory_execution_repository
from azents.testing.consolidation_vfs import create_memory_test_principal

CONTEXT_FIXTURE_TIME = datetime.datetime(2026, 10, 3, tzinfo=datetime.UTC)


def context_entry(
    *, scope: ConsolidationScope, text: str, exact_bytes: int | None
) -> ConsolidatedMemorySnapshotEntry:
    key = ConsolidationUnitKey(
        agent_id="a" * 32,
        workspace_id="b" * 32,
        scope=scope,
        associated_user_id="c" * 32 if scope is ConsolidationScope.USER else None,
    )
    markdown = text
    result = render_submitted_markdown(key=key, markdown=markdown)
    if exact_bytes is not None:
        missing = exact_bytes - len(result.rendered_block.encode())
        assert missing >= 0
        markdown += "x" * missing
        result = render_submitted_markdown(key=key, markdown=markdown)
        assert len(result.rendered_block.encode()) == exact_bytes
    return ConsolidatedMemorySnapshotEntry(
        unit=key,
        rendered_block=result.rendered_block,
        published_at=CONTEXT_FIXTURE_TIME,
    )


async def publish_context_overview(
    manager: SessionManager[WriteSession], *, key: ConsolidationUnitKey, markdown: str
) -> MemoryAcceptedOutcome:
    principal = await create_memory_test_principal(manager, key)
    repository = memory_execution_repository(manager)
    await repository.provision_inputs(principal)
    await SessionExecutionFileRepository(manager).write(
        principal.owner,
        "summary.md",
        markdown,
        expected_content=None,
        require_observation=False,
        overwrite=False,
    )
    return await repository.submit(
        principal, tool_call_id=uuid7().hex, authored_path="summary.md"
    )
