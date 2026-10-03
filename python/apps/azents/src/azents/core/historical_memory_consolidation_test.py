"""Exact-unit and canonical source-evidence contract tests."""

import datetime

import pytest
from pydantic import ValidationError

from azents.core.historical_memory import HistoricalMemoryCompletion
from azents.core.historical_memory_consolidation import (
    ConsolidationJobPrincipal,
    ConsolidationScope,
    ConsolidationSourceVersion,
    ConsolidationUnitKey,
    prepared_source_evidence_hash,
)

_AGENT = "a" * 32
_WORKSPACE = "b" * 32
_USER = "c" * 32
_NOW = datetime.datetime(2026, 10, 2, 0, 0, tzinfo=datetime.UTC)


def _completion(summary: str | None) -> HistoricalMemoryCompletion:
    return HistoricalMemoryCompletion(
        source_activity_at=_NOW,
        source_tail_event_id="d" * 32,
        prepared_at=_NOW + datetime.timedelta(minutes=1),
        source_title_snapshot="Task history",
        summary=summary,
    )


@pytest.mark.parametrize(
    ("scope", "user"),
    [(ConsolidationScope.TEAM, None), (ConsolidationScope.USER, _USER)],
)
def test_unit_has_exactly_one_valid_corpus_owner(
    scope: ConsolidationScope, user: str | None
) -> None:
    unit = ConsolidationUnitKey(
        agent_id=_AGENT,
        workspace_id=_WORKSPACE,
        scope=scope,
        associated_user_id=user,
    )
    assert unit.scope is scope
    assert unit.associated_user_id == user


@pytest.mark.parametrize(
    ("scope", "user"),
    [(ConsolidationScope.TEAM, _USER), (ConsolidationScope.USER, None)],
)
def test_invalid_scope_owner_cannot_widen_input_authority(
    scope: ConsolidationScope, user: str | None
) -> None:
    with pytest.raises(ValidationError):
        ConsolidationUnitKey(
            agent_id=_AGENT,
            workspace_id=_WORKSPACE,
            scope=scope,
            associated_user_id=user,
        )


def test_job_principal_rejects_fabricated_foreground_identity_fields() -> None:
    unit = ConsolidationUnitKey(
        agent_id=_AGENT,
        workspace_id=_WORKSPACE,
        scope=ConsolidationScope.TEAM,
        associated_user_id=None,
    )
    principal = ConsolidationJobPrincipal(
        unit=unit,
        attempt_id="e" * 32,
        owner_generation=1,
        owner_token="f" * 32,
    )
    payload = principal.model_dump(mode="json")
    payload["session_id"] = "1" * 32
    with pytest.raises(ValidationError, match="Extra inputs"):
        ConsolidationJobPrincipal.model_validate(payload)


@pytest.mark.parametrize("generation", [0, -1])
def test_job_principal_requires_an_admitted_owner_generation(generation: int) -> None:
    with pytest.raises(ValidationError):
        ConsolidationJobPrincipal(
            unit=ConsolidationUnitKey(
                agent_id=_AGENT,
                workspace_id=_WORKSPACE,
                scope=ConsolidationScope.USER,
                associated_user_id=_USER,
            ),
            attempt_id="e" * 32,
            owner_generation=generation,
            owner_token="f" * 32,
        )


def test_source_version_keeps_content_and_availability_generations_distinct() -> None:
    version = ConsolidationSourceVersion(
        source_session_id="1" * 32,
        summary_generation=2,
        evidence_hash=prepared_source_evidence_hash(_completion("summary")),
        availability_generation=4,
        membership_grant_id="2" * 32,
    )
    assert version.summary_generation == 2
    assert version.availability_generation == 4
    assert version.membership_grant_id == "2" * 32


def test_evidence_hash_is_deterministic_and_normalizes_equal_instants() -> None:
    completion = _completion("Supported progress")
    offset = datetime.timezone(datetime.timedelta(hours=9))
    equivalent = completion.model_copy(
        update={
            "source_activity_at": completion.source_activity_at.astimezone(offset),
            "prepared_at": completion.prepared_at.astimezone(offset),
        }
    )
    assert prepared_source_evidence_hash(completion) == prepared_source_evidence_hash(
        equivalent
    )
    assert len(prepared_source_evidence_hash(completion)) == 64


@pytest.mark.parametrize(
    "change",
    [
        {"summary": "Different evidence"},
        {"summary": "Supported progress "},
        {"source_title_snapshot": "Another title"},
        {"source_tail_event_id": "3" * 32},
        {"source_activity_at": _NOW + datetime.timedelta(seconds=1)},
        {"prepared_at": _NOW + datetime.timedelta(minutes=2)},
    ],
)
def test_hash_covers_every_supplied_evidence_field(change: dict[str, object]) -> None:
    completion = _completion("Supported progress")
    changed = completion.model_copy(update=change)
    assert prepared_source_evidence_hash(completion) != prepared_source_evidence_hash(
        changed
    )


def test_hash_uses_existing_empty_published_result_representation() -> None:
    assert prepared_source_evidence_hash(_completion(None)) == (
        prepared_source_evidence_hash(_completion(""))
    )


def test_hash_does_not_semantically_normalize_distinct_unicode_bytes() -> None:
    assert prepared_source_evidence_hash(_completion("caf\u00e9")) != (
        prepared_source_evidence_hash(_completion("cafe\u0301"))
    )


@pytest.mark.parametrize("digest", ["x" * 64, "0" * 63, "A" * 64])
def test_source_version_requires_canonical_sha256(digest: str) -> None:
    with pytest.raises(ValidationError):
        ConsolidationSourceVersion(
            source_session_id="1" * 32,
            summary_generation=1,
            evidence_hash=digest,
            availability_generation=1,
            membership_grant_id=None,
        )
