"""Typed cleanup boundary compatibility without database or Runtime effects."""

import pytest

from azents.rdb.models.event import JSONValue
from azents.services.session_git_worktree import (
    _cleanup_candidate,
    _cleanup_result,
    _decode_cleanup_candidates,
)


def test_new_cleanup_result_preserves_wire_shape_and_counts() -> None:
    """Known outcomes retain version, phase, candidate fields, and all counters."""
    outcomes = ("unresolved", "protected", "removed", "already_absent", "failed")
    candidates = [
        _cleanup_candidate(
            path=f"/workspace/{outcome}",
            outcome=outcome,
            reason_code=None,
            summary=None,
        )
        for outcome in outcomes
    ]
    result = _cleanup_result(phase="processing", candidates=candidates)
    assert result.to_json() == {
        "schema_version": 1,
        "phase": "processing",
        "examined_count": 5,
        "protected_count": 1,
        "removed_count": 1,
        "already_absent_count": 1,
        "failed_count": 1,
        "unresolved_count": 1,
        "candidates": [
            {
                "path": f"/workspace/{outcome}",
                "outcome": outcome,
                "reason_code": None,
                "summary": None,
            }
            for outcome in outcomes
        ],
    }


def test_cleanup_result_snapshots_mutable_candidate_collection() -> None:
    """Later processing list mutations do not mutate an earlier result snapshot."""
    candidates = [
        _cleanup_candidate(
            path="/workspace/worktree",
            outcome="unresolved",
            reason_code=None,
            summary=None,
        )
    ]
    result = _cleanup_result(phase="processing", candidates=candidates)
    candidates.clear()
    assert result.to_json()["examined_count"] == 1


@pytest.mark.parametrize("candidates", [None, "not-a-list", 1, {"outcome": "failed"}])
def test_nonlist_historical_candidates_remain_empty(candidates: JSONValue) -> None:
    """Historical non-list values keep the original empty-list fallback."""
    assert _decode_cleanup_candidates({"candidates": candidates}) == ()


def test_cleanup_cancellation_preserves_opaque_fields_and_invalid_candidates() -> None:
    """Only unresolved records change; unknown fields and malformed dicts roundtrip."""
    unresolved: dict[str, JSONValue] = {
        "path": "/workspace/orphan",
        "outcome": "unresolved",
        "reason_code": None,
        "extension": {"opaque": [True]},
    }
    removed: dict[str, JSONValue] = {
        "outcome": "removed",
        "summary": "",
        "extension": 123,
    }
    malformed: dict[str, JSONValue] = {"outcome": ["failed"], "path": 7}
    raw: dict[str, JSONValue] = {
        "candidates": [unresolved, removed, malformed, None, "skip"],
    }
    decoded = _decode_cleanup_candidates(raw)
    result = _cleanup_result(
        phase="cancelled",
        candidates=[candidate.with_cancellation("Stopped.") for candidate in decoded],
    )
    encoded = result.to_json()
    assert encoded["candidates"] == [
        {**unresolved, "reason_code": "cancelled", "summary": "Stopped."},
        removed,
        malformed,
    ]
    assert encoded["examined_count"] == 3
    assert encoded["unresolved_count"] == 1
    assert encoded["removed_count"] == 1
    assert encoded["failed_count"] == 0
    assert "summary" not in unresolved
    assert decoded[0].reason_code is None
    assert decoded[2].outcome is None


def test_historical_payload_is_detached_from_outer_mapping() -> None:
    """The boundary snapshot ignores later changes to the source dictionary."""
    payload: dict[str, JSONValue] = {"path": "/original", "outcome": "protected"}
    decoded = _decode_cleanup_candidates({"candidates": [payload]})
    payload["path"] = "/changed"
    assert decoded[0].path == "/original"
    assert decoded[0].to_json()["path"] == "/original"
