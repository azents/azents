"""Detached system catalog projection and publication results."""

import dataclasses

from azents.core.enums import LLMProvider


@dataclasses.dataclass(frozen=True)
class SystemCatalogCandidateSummary:
    """One complete replacement projection awaiting atomic publication."""

    provider: LLMProvider
    catalog_id: str
    candidate_snapshot_id: str
    expected_current_snapshot_id: str | None
    visible_count: int
    hidden_count: int
    projection_fingerprint: str


@dataclasses.dataclass(frozen=True)
class SystemCatalogCutoverSummary:
    """Result of an existing scheduled or administrator publication operation."""

    provider: LLMProvider
    catalog_id: str
    snapshot_id: str | None
    visible_count: int
    hidden_count: int
    projection_fingerprint: str
    status: str
