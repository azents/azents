"""Strict authored routes, whole UTF-8 envelope bounds and explicit empty outcomes."""

import pytest
from pydantic import ValidationError
from uuid6 import uuid7

from azents.core.historical_memory_consolidation import (
    ConsolidationScope,
    ConsolidationUnitKey,
)
from azents.core.historical_memory_publication import (
    ConsolidationCoverage,
    ConsolidationOutputError,
    consolidation_envelope,
    validate_consolidation_overview,
)


def _key(scope: ConsolidationScope) -> ConsolidationUnitKey:
    return ConsolidationUnitKey(
        workspace_id=uuid7().hex,
        agent_id=uuid7().hex,
        scope=scope,
        associated_user_id=uuid7().hex if scope is ConsolidationScope.USER else None,
    )


def _document(key: ConsolidationUnitKey, source_id: str, context: str) -> str:
    return (
        f"## Historical Context\n{context}\n\n## Source Routes\n"
        f"- azents://memory/historical/{key.scope.value}/{source_id}/summary.md"
        " — Source detail\n"
    )


@pytest.mark.parametrize("scope", [ConsolidationScope.TEAM, ConsolidationScope.USER])
async def test_complete_independent_envelope_and_exact_source_routes(
    scope: ConsolidationScope,
) -> None:
    key = _key(scope)
    source_id = uuid7().hex
    result = validate_consolidation_overview(
        key=key,
        markdown=_document(
            key, source_id, "요청과 확인된 결과; 미확인 내용은 구분합니다."
        ),
    )
    assert not result.empty and result.routes[0].source_session_id == source_id
    assert result.rendered_block.startswith("HISTORICAL MEMORY DATA BEGINS\n")
    assert result.rendered_block.endswith("HISTORICAL MEMORY DATA ENDS\n")
    assert key.agent_id in result.rendered_block
    assert "20,000" not in result.rendered_block
    assert len(result.rendered_block.encode()) <= 10000


async def test_byte_limit_includes_scope_provenance_separators_and_unicode() -> None:
    key = _key(ConsolidationScope.TEAM)
    source_id = uuid7().hex
    base = _document(key, source_id, "")
    padding = 10000 - len(consolidation_envelope(key, base).encode())
    exact = _document(key, source_id, "a" * padding)
    result = validate_consolidation_overview(key=key, markdown=exact)
    assert len(result.rendered_block.encode()) == 10000
    for context in ("a" * (padding + 1), "한" * padding):
        with pytest.raises(ConsolidationOutputError, match="10,000"):
            validate_consolidation_overview(
                key=key, markdown=_document(key, source_id, context)
            )


async def test_explicit_empty_outcome_has_no_fabricated_account_or_framing() -> None:
    key = _key(ConsolidationScope.TEAM)
    empty = validate_consolidation_overview(
        key=key, markdown="## Historical Context\n\n## Source Routes\n"
    )
    assert empty.empty and empty.markdown == empty.rendered_block == ""
    assert empty.routes == ()
    with pytest.raises(ConsolidationOutputError):
        validate_consolidation_overview(key=key, markdown="")


@pytest.mark.parametrize(
    "suffix",
    [
        "azents://memory/consolidated/team/summary.md",
        "azents://memory-draft/summary.md",
        "azents://memory/historical/user/" + "a" * 32 + "/summary.md",
        "azents://memory/historical/team/" + "a" * 32 + "/../summary.md",
        "AZENTS://memory/historical/team/" + "a" * 32 + "/summary.md",
        "azents://memory/historical/team/" + "b" * 32 + "/summary.md",
    ],
)
async def test_forged_managed_locator_anywhere_is_not_a_route_bypass(
    suffix: str,
) -> None:
    key = _key(ConsolidationScope.TEAM)
    with pytest.raises(ConsolidationOutputError):
        validate_consolidation_overview(
            key=key, markdown=_document(key, "a" * 32, "Claim plus " + suffix)
        )


@pytest.mark.parametrize(
    "markdown",
    [
        "## Source Routes\n## Historical Context\n",
        "## Historical Context\nUnlinked prose\n## Source Routes\n",
        "## Historical Context\n## Historical Context\n## Source Routes\n",
        "Final reply prose\n## Historical Context\n## Source Routes\n",
        "## Historical Context\n\x00\n## Source Routes\n",
    ],
)
async def test_section_and_payload_failures_are_not_empty_success(
    markdown: str,
) -> None:
    with pytest.raises(ConsolidationOutputError):
        validate_consolidation_overview(
            key=_key(ConsolidationScope.TEAM), markdown=markdown
        )


async def test_exact_bounded_dispositions_do_not_infer_coverage_from_reads() -> None:
    work_id = uuid7().hex
    coverage = ConsolidationCoverage.model_validate(
        {
            "dispositions": [
                {
                    "work_id": work_id,
                    "action": "omitted",
                    "reason": "No useful continuation context",
                }
            ]
        }
    )
    assert coverage.dispositions[0].work_id == work_id
    assert ConsolidationCoverage(dispositions=()).dispositions == ()
    item = {"work_id": work_id, "action": "considered", "reason": "Integrated"}
    with pytest.raises(ValidationError, match="repeats"):
        ConsolidationCoverage.model_validate({"dispositions": [item, item]})
    with pytest.raises(ValidationError):
        ConsolidationCoverage.model_validate({"dispositions": [{**item, "reason": ""}]})
    with pytest.raises(ValidationError):
        ConsolidationCoverage.model_validate(
            {"dispositions": [{**item, "action": "all_seen"}]}
        )
